"""处理管线运行（P3-5）：创建 run、查询 run 状态、结果集。

POST /tasks/{task_id}/runs 创建 processing_run 并冻结清单快照与文件集合，
同事务入队 Procrastinate 任务。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUser, OwnedTask, SessionDep, require_csrf
from app.checklist import checklist_hash, get_checklist
from app.core.config import settings
from app.crud import list_task_files
from app.decisions import compute_statistics, decision_to_view, write_decision
from app.models import (
    Decision,
    OcrJob,
    OcrPage,
    ProcessingRun,
    Result,
    ResultSource,
    RunFile,
    RunState,
    RunStep,
    TaskFile,
    TaskState,
)
from app.processing_pipeline import run_pipeline
from app.queue import enqueue_in_session

router = APIRouter(tags=["runs"])

BORROWER_CHECKLIST_VERSION = "borrower-wcl-v1"


class RunCreate(BaseModel):
    retry_failed_only: bool = True


class DecisionWrite(BaseModel):
    run_id: uuid.UUID
    decision: str
    reject_reason: str | None = None


class CompleteRequest(BaseModel):
    run_id: uuid.UUID
    input_revision: int


def _all_files_ocr_done(session: Session, task_id: uuid.UUID) -> bool:
    files = list_task_files(session=session, task_id=task_id)
    if not files:
        return False
    for f in files:
        job = session.exec(
            select(OcrJob).where(OcrJob.file_id == f.id).order_by(OcrJob.created_at.desc())
        ).first()
        if not job or job.state != "SUCCEEDED":
            return False
    return True


@router.post("/tasks/{task_id}/runs", status_code=202, dependencies=[Depends(require_csrf)])
def create_run(
    body: RunCreate,
    task: OwnedTask,
    session: SessionDep,
) -> dict:
    if task.state == TaskState.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "TASK_READ_ONLY", "message": "任务已完成，不可重新核对"},
        )

    files = list_task_files(session=session, task_id=task.id)
    if not files:
        raise HTTPException(
            status_code=409,
            detail={"code": "NO_FILES", "message": "请先上传资料文件"},
        )

    # 所有文件 OCR 完成才可开始核对
    if not _all_files_ocr_done(session, task.id):
        raise HTTPException(
            status_code=409,
            detail={"code": "OCR_NOT_READY", "message": "资料仍在识别中，请稍后再试"},
        )

    # 已有未完成的 run 则拒绝
    existing = session.exec(
        select(ProcessingRun).where(
            ProcessingRun.task_id == task.id,
            ProcessingRun.state.in_([RunState.QUEUED.value, RunState.RUNNING.value]),
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_IN_PROGRESS", "message": "已有核对任务在处理中"},
        )

    checklist = get_checklist(BORROWER_CHECKLIST_VERSION)
    run = ProcessingRun(
        task_id=task.id,
        input_revision=task.input_revision,
        checklist_snapshot=checklist,
        checklist_hash=checklist_hash(BORROWER_CHECKLIST_VERSION),
        model_snapshot={
            "text_model": settings.LLM_TEXT_MODEL,
            "vision_model": settings.LLM_VISION_MODEL,
        },
        state=RunState.QUEUED.value,
    )
    session.add(run)
    session.flush()

    for f in files:
        session.add(RunFile(run_id=run.id, file_id=f.id, task_id=task.id))

    # 任务状态 → 处理中
    task.state = TaskState.PROCESSING.value
    session.add(task)
    session.flush()

    # 同事务入队：run 创建与队列入队原子提交
    enqueue_in_session(session, run_pipeline, run_id=str(run.id))
    session.commit()
    session.refresh(run)

    return _run_to_view(session, run)


@router.get("/tasks/{task_id}/runs/{run_id}")
def get_run(task: OwnedTask, run_id: uuid.UUID, session: SessionDep) -> dict:
    run = session.exec(
        select(ProcessingRun).where(
            ProcessingRun.id == run_id, ProcessingRun.task_id == task.id
        )
    ).first()
    if not run:
        raise HTTPException(
            status_code=404,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "核对任务不存在"},
        )
    return _run_to_view(session, run)


def _run_to_view(session: Session, run: ProcessingRun) -> dict:
    run_files = session.exec(
        select(RunFile).where(RunFile.run_id == run.id, RunFile.task_id == run.task_id)
    ).all()
    files = [
        {
            "file_id": str(rf.file_id),
            "effective_material_type": rf.effective_material_type,
        }
        for rf in run_files
    ]
    return {
        "id": str(run.id),
        "task_id": str(run.task_id),
        "input_revision": run.input_revision,
        "state": run.state,
        "stage": run.stage,
        "coverage_complete": run.coverage_complete,
        "files": files,
        "error_code": run.error_code,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


# ---------------------------------------------------------------------------
# 结果集
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}/results")
def list_results(task: OwnedTask, session: SessionDep) -> dict:
    run = session.exec(
        select(ProcessingRun)
        .where(ProcessingRun.task_id == task.id)
        .order_by(ProcessingRun.created_at.desc())
    ).first()
    if not run:
        return {"run_id": None, "is_stale": False, "editable": False, "statistics": None, "items": [], "next_cursor": None}

    results = session.exec(
        select(Result)
        .where(Result.run_id == run.id, Result.task_id == task.id)
        .order_by(Result.check_item_id, Result.rank, Result.id)
    ).all()

    meta = _check_meta_map(run.checklist_snapshot or {})

    # 加载 decisions
    result_ids = [r.id for r in results]
    dec_by_result: dict[uuid.UUID, Decision] = {}
    if result_ids:
        decisions = session.exec(
            select(Decision).where(
                Decision.task_id == task.id,
                Decision.result_id.in_(result_ids),  # type: ignore[attr-defined]
            )
        ).all()
        dec_by_result = {d.result_id: d for d in decisions}

    items = [
        _result_to_view(session, task.id, run.id, r, meta, dec_by_result.get(r.id))
        for r in results
    ]
    statistics = compute_statistics(session, task.id, run.id, meta)
    return {
        "run_id": str(run.id),
        "is_stale": run.input_revision != task.input_revision,
        "editable": run.state == RunState.READY.value and task.state != TaskState.COMPLETED.value,
        "statistics": statistics,
        "items": items,
        "next_cursor": None,
    }


@router.get("/tasks/{task_id}/runs/{run_id}/timing")
def run_timing(task: OwnedTask, run_id: uuid.UUID, session: SessionDep) -> dict:
    """返回 run 与各阶段/检查项步骤的起止与耗时（性能观测 Step 1）。"""
    run = session.get(ProcessingRun, run_id)
    if not run or run.task_id != task.id:
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "run 不存在"})

    steps = session.exec(
        select(RunStep)
        .where(RunStep.run_id == run_id, RunStep.task_id == task.id)
        .order_by(RunStep.started_at, RunStep.step_key)
    ).all()

    def _elapsed(s: ProcessingRun | RunStep) -> float | None:
        if s.started_at and s.finished_at:
            return round((s.finished_at - s.started_at).total_seconds(), 3)
        return None

    step_views = [
        {
            "step_key": s.step_key,
            "state": s.state,
            "attempt": s.attempt,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            "elapsed_seconds": _elapsed(s),
            "last_error_code": s.last_error_code,
        }
        for s in steps
    ]
    return {
        "run_id": str(run_id),
        "state": run.state,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "elapsed_seconds": _elapsed(run),
        "steps": step_views,
    }


def _check_meta_map(snapshot: dict) -> dict[str, dict]:
    """check_item_id → {label, group_label, material_type}。"""
    meta: dict[str, dict] = {}
    for material in snapshot.get("materials", []):
        for check in material.get("checks", []):
            meta[check["id"]] = {
                "label": check.get("label", check["id"]),
                "group_label": check.get("group_label"),
                "material_type": material["material_type"],
            }
    return meta


def _result_to_view(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    r: Result,
    meta: dict[str, dict],
    decision: Decision | None,
) -> dict:
    check_meta = meta.get(r.check_item_id, {})
    sources = session.exec(
        select(ResultSource).where(
            ResultSource.result_id == r.id, ResultSource.task_id == task_id
        )
    ).all()
    source_views = []
    for s in sources:
        file_name = None
        if s.file_id:
            f = session.get(TaskFile, s.file_id)
            file_name = f.original_name if f else None
        # 从 OCR 页取真实尺寸与坐标空间（用于前端高亮定位）
        page = session.get(OcrPage, s.page_id) if s.page_id else None
        source_views.append(
            {
                "file_id": str(s.file_id) if s.file_id else None,
                "file_name": file_name,
                "page_id": str(s.page_id) if s.page_id else None,
                "block_id": str(s.block_id) if s.block_id else None,
                "source_page_number": s.source_page_number,
                "ocr_page_index": page.ocr_page_index if page else None,
                "location_precision": s.location_precision,
                "bbox": s.bbox,
                "polygon": s.polygon,
                "coordinate_space": page.coordinate_space if page else "unknown",
                "page_width_px": page.width_px if page else None,
                "page_height_px": page.height_px if page else None,
                "raster_asset_id": str(page.raster_asset_id) if page and page.raster_asset_id else None,
                "start_char": s.start_char,
                "end_char": s.end_char,
            }
        )

    return {
        "id": str(r.id),
        "task_id": str(task_id),
        "run_id": str(run_id),
        "check_item_id": r.check_item_id,
        "check_label": check_meta.get("label", r.check_item_id),
        "group_label": check_meta.get("group_label"),
        "material_type": check_meta.get("material_type"),
        "kind": r.kind,
        "text": r.text,
        "table_html": r.table_html,
        "crop_id": str(r.crop_id) if r.crop_id else None,
        "image_asset_id": None,
        "image_url": None,
        "recognition_source": r.recognition_source,
        "relation_status": r.relation_status,
        "not_found_reason": r.not_found_reason,
        "rank": r.rank,
        "sources": source_views,
        "decision": decision_to_view(decision)
        if decision
        else {
            "result_id": str(r.id),
            "decision": "unselected",
            "reject_reason": None,
            "version": 0,
            "updated_at": None,
            "carried_from_result_id": None,
        },
        "editable": True,
    }


# ---------------------------------------------------------------------------
# 决策（接受/拒绝）
# ---------------------------------------------------------------------------


@router.patch("/tasks/{task_id}/results/{result_id}/decision", dependencies=[Depends(require_csrf)])
def update_decision(
    body: DecisionWrite,
    task: OwnedTask,
    result_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> dict:
    run = session.exec(
        select(ProcessingRun).where(
            ProcessingRun.id == body.run_id, ProcessingRun.task_id == task.id
        )
    ).first()
    if not run or run.state != RunState.READY.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_NOT_READY", "message": "核对结果尚未就绪或已过期"},
        )
    if task.state == TaskState.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "TASK_READ_ONLY", "message": "任务已完成，不可修改"},
        )

    result = session.exec(
        select(Result).where(Result.id == result_id, Result.task_id == task.id, Result.run_id == body.run_id)
    ).first()
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "结果不存在"},
        )

    decision, err = write_decision(
        session=session,
        task_id=task.id,
        result_id=result_id,
        decision=body.decision,
        reject_reason=body.reject_reason,
        actor_user_id=current_user.id,
    )
    if err:
        raise HTTPException(status_code=422, detail={"code": "INVALID_DECISION", "message": err})
    session.commit()
    session.refresh(decision)

    meta = _check_meta_map(run.checklist_snapshot or {})
    statistics = compute_statistics(session, task.id, body.run_id, meta)
    return {
        "decision": decision_to_view(decision),
        "statistics": statistics,
    }


def _incomplete_items(session: Session, task_id: uuid.UUID, run_id: uuid.UUID, meta: dict[str, dict]) -> dict:
    """返回未完成的具体条目：未确认项 + 拒绝缺原因项。"""
    results = session.exec(
        select(Result).where(Result.run_id == run_id, Result.task_id == task_id)
    ).all()
    result_ids = [r.id for r in results]
    dec_by_result: dict[uuid.UUID, Decision] = {}
    if result_ids:
        decisions = session.exec(
            select(Decision).where(
                Decision.task_id == task_id,
                Decision.result_id.in_(result_ids),  # type: ignore[attr-defined]
            )
        ).all()
        dec_by_result = {d.result_id: d for d in decisions}

    unselected: list[dict] = []
    missing_reason: list[dict] = []
    for r in results:
        d = dec_by_result.get(r.id)
        value = d.decision if d else "unselected"
        label = meta.get(r.check_item_id, {}).get("label", r.check_item_id)
        if value == "unselected":
            unselected.append({"check_item_id": r.check_item_id, "check_label": label})
        elif value == "rejected" and not (d.reject_reason or "").strip():
            missing_reason.append({"check_item_id": r.check_item_id, "check_label": label})
    return {"unselected": unselected, "missing_reason": missing_reason}


@router.post("/tasks/{task_id}/complete", dependencies=[Depends(require_csrf)])
def complete_task(body: CompleteRequest, task: OwnedTask, session: SessionDep) -> dict:
    run = session.exec(
        select(ProcessingRun).where(
            ProcessingRun.id == body.run_id, ProcessingRun.task_id == task.id
        )
    ).first()
    if not run or run.state != RunState.READY.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_NOT_READY", "message": "核对结果尚未就绪"},
        )
    if body.input_revision != task.input_revision:
        raise HTTPException(
            status_code=409,
            detail={"code": "REVISION_CONFLICT", "message": "资料已变更，请刷新后重新核对"},
        )

    meta = _check_meta_map(run.checklist_snapshot or {})
    statistics = compute_statistics(session, task.id, body.run_id, meta)
    if not statistics["overall"]["can_complete"]:
        incomplete = _incomplete_items(session, task.id, body.run_id, meta)
        raise HTTPException(
            status_code=409,
            detail={"code": "NOT_COMPLETE", "message": "仍有未确认项或拒绝未填原因，无法完成", "incomplete": incomplete},
        )

    task.state = TaskState.COMPLETED.value
    task.completed_at = datetime.now(UTC)
    task.last_ready_run_id = run.id
    session.add(task)
    session.commit()
    return {"state": TaskState.COMPLETED.value, "statistics": statistics}
