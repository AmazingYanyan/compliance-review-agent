"""处理管线（P3）：材料分类 → 文本/表格查找 → 印章/签名匹配。

单一 Procrastinate 任务 processing.run 串行执行三个阶段，结果写入 results +
result_sources。每个阶段失败记录 error_code 并标记 run FAILED（可重试）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.classification import classify_file
from app.core.config import settings
from app.core.db import engine
from app.llm_client import get_llm_client
from app.models import (
    ProcessingRun,
    Result,
    ResultSource,
    RunFile,
    RunState,
    RunStep,
    StepState,
    Task,
    TaskFile,
    TaskState,
)
from app.queue import app
from app.text_search import FoundEvidence, search_check_item
from app.vision_match import CropEvidence, load_crops, match_by_text, match_by_vision


def _leaves_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    for material in snapshot.get("materials", []):
        for check in material.get("checks", []):
            leaves.append({**check, "material_type": material["material_type"]})
    return leaves


# ---------------------------------------------------------------------------
# 耗时观测（Step 1）：RunStep 记录阶段/检查项/窗口的起止与状态
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _step_key_hash(step_key: str, extra: str = "") -> str:
    """input_hash 用 step_key + extra 的稳定短哈希，保证 (run_id, step_key, input_hash) 唯一。"""
    import hashlib

    return hashlib.sha256(f"{step_key}|{extra}".encode("utf-8")).hexdigest()[:64]


def _record_step(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    step_key: str,
    input_hash: str,
    *,
    state: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    file_id: uuid.UUID | None = None,
    last_error_code: str | None = None,
    attempt: int = 0,
) -> None:
    """写/更新一条 RunStep（按 run_id+step_key+input_hash upsert）。"""
    existing = session.exec(
        select(RunStep).where(
            RunStep.run_id == run_id,
            RunStep.step_key == step_key,
            RunStep.input_hash == input_hash,
        )
    ).first()
    if existing:
        existing.state = state
        existing.started_at = started_at or existing.started_at
        existing.finished_at = finished_at or existing.finished_at
        existing.last_error_code = last_error_code
        existing.attempt = attempt
        session.add(existing)
    else:
        session.add(
            RunStep(
                task_id=task_id,
                run_id=run_id,
                file_id=file_id,
                step_key=step_key,
                input_hash=input_hash,
                state=state,
                attempt=attempt,
                last_error_code=last_error_code,
                started_at=started_at,
                finished_at=finished_at,
            )
        )


def _touch_step(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    step_key: str,
    state: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    last_error_code: str | None = None,
) -> None:
    """在独立 Session 里写/更新一条 RunStep（阶段/检查项级观测）。"""
    input_hash = _step_key_hash(step_key)
    with Session(engine) as session:
        _record_step(
            session,
            task_id,
            run_id,
            step_key,
            input_hash,
            state=state,
            started_at=started_at,
            finished_at=finished_at,
            last_error_code=last_error_code,
        )
        session.commit()


# ---------------------------------------------------------------------------
# 结果写入
# ---------------------------------------------------------------------------


def _write_text_result(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    evidence: FoundEvidence,
    rank: int,
) -> None:
    result = Result(
        task_id=task_id,
        run_id=run_id,
        check_item_id=check_item["id"],
        kind=evidence.kind,
        text=evidence.text,
        table_html=evidence.table_html,
        relation_status=evidence.relation_status,
        rank=rank,
        fingerprint=evidence.fingerprint,
    )
    session.add(result)
    session.flush()
    src = evidence.source
    session.add(
        ResultSource(
            task_id=task_id,
            result_id=result.id,
            file_id=src.file_id,
            page_id=src.page_id,
            block_id=src.block_id,
            start_char=evidence.start_char,
            end_char=evidence.end_char,
            source_page_number=src.source_page_number,
            bbox=src.bbox,
            polygon=src.polygon,
            location_precision=_location_precision(src),
        )
    )


def _location_precision(src: Any) -> str:
    if src.bbox or src.polygon:
        return "region"
    if src.page_id:
        return "page"
    return "none"


def _write_crop_result(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    evidence: CropEvidence,
    rank: int,
) -> None:
    kind = "seal" if check_item.get("result_mode") == "seal" else "signature"
    result = Result(
        task_id=task_id,
        run_id=run_id,
        check_item_id=check_item["id"],
        kind=kind,
        text=evidence.text,
        crop_id=evidence.crop_id,
        recognition_source=evidence.recognition_source,
        relation_status=evidence.relation_status,
        rank=rank,
    )
    session.add(result)
    session.flush()
    if evidence.file_id:
        session.add(
            ResultSource(
                task_id=task_id,
                result_id=result.id,
                file_id=evidence.file_id,
                page_id=evidence.page_id,
                block_id=evidence.block_id,
                bbox=evidence.bbox,
                polygon=evidence.polygon,
                location_precision="region" if (evidence.bbox or evidence.polygon) else "page",
            )
        )


def _write_not_found(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    reason: str,
) -> None:
    session.add(
        Result(
            task_id=task_id,
            run_id=run_id,
            check_item_id=check_item["id"],
            kind="not_found",
            not_found_reason=reason,
            rank=0,
        )
    )


# ---------------------------------------------------------------------------
# 阶段
# ---------------------------------------------------------------------------


def _classify_stage(task_id: uuid.UUID, run_id: uuid.UUID, client: Any) -> None:
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
        file_ids = [rf.file_id for rf in run_files]

    for file_id in file_ids:
        with Session(engine) as session:
            result = classify_file(
                task_id=task_id,
                file_id=file_id,
                client=client,
                max_chars=settings.LLM_WINDOW_CHARACTERS,
                overlap_chars=settings.LLM_WINDOW_OVERLAP_CHARACTERS,
            )
            rf = session.exec(
                select(RunFile).where(
                    RunFile.run_id == run_id,
                    RunFile.task_id == task_id,
                    RunFile.file_id == file_id,
                )
            ).first()
            if rf:
                rf.effective_material_type = (
                    None if result.material_type == "unknown" or result.mixed else result.material_type
                )
                rf.classification_source = "llm"
                rf.classification_reason = result.reason
                session.add(rf)
                session.commit()


def _search_stage(task_id: uuid.UUID, run_id: uuid.UUID, snapshot: dict[str, Any], client: Any) -> None:
    leaves = _leaves_from_snapshot(snapshot)
    # 材料类型 → file_ids（仅已分类的）
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
    material_files: dict[str, list[uuid.UUID]] = {}
    for rf in run_files:
        if rf.effective_material_type:
            material_files.setdefault(rf.effective_material_type, []).append(rf.file_id)

    for leaf in leaves:
        if leaf.get("result_mode") in ("seal", "signature"):
            continue
        check_id = leaf["id"]
        material = leaf["material_type"]
        file_ids = material_files.get(material, [])
        step_key = f"check:{check_id}"

        _touch_step(task_id, run_id, step_key, StepState.RUNNING.value, started_at=_now())

        if not file_ids:
            # 缺材料 → material_missing
            with Session(engine) as session:
                _write_not_found(session, task_id, run_id, leaf, "material_missing")
                session.commit()
            _touch_step(task_id, run_id, step_key, StepState.SUCCEEDED.value, finished_at=_now())
            continue

        evidence, failed_reason = search_check_item(
            task_id=task_id,
            check_item=leaf,
            file_ids=file_ids,
            client=client,
            max_chars=settings.LLM_WINDOW_CHARACTERS,
            overlap_chars=settings.LLM_WINDOW_OVERLAP_CHARACTERS,
        )
        with Session(engine) as session:
            if failed_reason == "LLM_FATAL":
                # 鉴权/参数等致命错误：整项失败，标记 run 失败
                _touch_step(
                    task_id, run_id, step_key, StepState.FAILED.value,
                    finished_at=_now(), last_error_code="LLM_FATAL",
                )
                _mark_run_failed(session, run_id, "SEARCH_FAILED")
                session.commit()
                return
            if failed_reason == "PARTIAL_COVERAGE":
                # 部分窗口未覆盖：不判 not_found，标记需人工复核
                _write_not_found(session, task_id, run_id, leaf, "coverage_incomplete")
            elif not evidence:
                _write_not_found(session, task_id, run_id, leaf, "no_matching_evidence")
            else:
                for rank, ev in enumerate(evidence):
                    _write_text_result(session, task_id, run_id, leaf, ev, rank)
            session.commit()
        _touch_step(task_id, run_id, step_key, StepState.SUCCEEDED.value, finished_at=_now())


def _vision_stage(task_id: uuid.UUID, run_id: uuid.UUID, snapshot: dict[str, Any], client: Any) -> None:
    leaves = _leaves_from_snapshot(snapshot)
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
    material_files: dict[str, list[uuid.UUID]] = {}
    for rf in run_files:
        if rf.effective_material_type:
            material_files.setdefault(rf.effective_material_type, []).append(rf.file_id)

    # 预取依赖项结果（如审计机构名）
    with Session(engine) as session:
        dep_texts: dict[str, str] = {}
        for leaf in leaves:
            for dep in leaf.get("dependencies", []):
                if dep not in dep_texts:
                    dep_texts[dep] = ""
        if dep_texts:
            rows = session.exec(
                select(Result).where(
                    Result.run_id == run_id,
                    Result.task_id == task_id,
                    Result.check_item_id.in_(list(dep_texts.keys())),  # type: ignore[attr-defined]
                )
            ).all()
            for row in rows:
                if row.text:
                    dep_texts[row.check_item_id] = row.text

    for leaf in leaves:
        if leaf.get("result_mode") not in ("seal", "signature"):
            continue
        material = leaf["material_type"]
        file_ids = material_files.get(material, [])
        if not file_ids:
            with Session(engine) as session:
                _write_not_found(session, task_id, run_id, leaf, "material_missing")
                session.commit()
            continue

        with Session(engine) as session:
            crops = load_crops(session, task_id, file_ids)

        target_text = None
        for dep in leaf.get("dependencies", []):
            if dep_texts.get(dep):
                target_text = dep_texts[dep]
                break

        # 先文字匹配
        evidence: list[CropEvidence] = match_by_text(crops, target_text)

        # 文字不足以确定（无依赖目标，或文字没匹配到）→ 视觉兜底
        if not evidence:
            evidence = match_by_vision(
                crops=crops,
                check_item=leaf,
                client=client,
                batch_size=settings.VISION_IMAGES_PER_BATCH,
                max_edge=settings.VISION_MAX_IMAGE_EDGE,
            )

        with Session(engine) as session:
            if not evidence:
                _write_not_found(session, task_id, run_id, leaf, "no_matching_evidence")
            else:
                for rank, ev in enumerate(evidence):
                    _write_crop_result(session, task_id, run_id, leaf, ev, rank)
            session.commit()


def _mark_run_failed(session: Session, run_id: uuid.UUID, code: str) -> None:
    run = session.get(ProcessingRun, run_id)
    if run:
        run.state = RunState.FAILED.value
        run.error_code = code
        run.finished_at = _now()
        session.add(run)


def _complete_run(run_id: uuid.UUID) -> None:
    with Session(engine) as session:
        run = session.get(ProcessingRun, run_id)
        if not run:
            return
        if run.state == RunState.FAILED.value:
            # 阶段已标记失败，不覆盖
            return
        run.state = RunState.READY.value
        run.stage = "done"
        run.coverage_complete = True
        run.finished_at = _now()
        session.add(run)
        # 任务状态 → 待核对
        task = session.get(Task, run.task_id)
        if task and task.state == TaskState.PROCESSING.value:
            task.state = TaskState.REVIEWING.value
            session.add(task)
        session.commit()


# ---------------------------------------------------------------------------
# 入口任务
# ---------------------------------------------------------------------------


@app.task(name="processing.run", queue="processing")
def run_pipeline(run_id: str) -> None:
    rid = uuid.UUID(run_id)
    with Session(engine) as session:
        run = session.get(ProcessingRun, rid)
        if not run or run.state not in (RunState.QUEUED.value, RunState.RUNNING.value):
            return
        task_id = run.task_id
        snapshot = run.checklist_snapshot or {}
        run.state = RunState.RUNNING.value
        run.started_at = _now()
        session.add(run)
        session.commit()

    client = get_llm_client()

    # 阶段 1：材料分类
    _touch_step(task_id, rid, "stage:classify", StepState.RUNNING.value, started_at=_now())
    try:
        _classify_stage(task_id, rid, client)
        _touch_step(task_id, rid, "stage:classify", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:classify", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"CLASSIFY_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"CLASSIFY_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    # 阶段 2：文本/表格查找
    _touch_step(task_id, rid, "stage:search", StepState.RUNNING.value, started_at=_now())
    try:
        _search_stage(task_id, rid, snapshot, client)
        _touch_step(task_id, rid, "stage:search", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:search", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"SEARCH_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"SEARCH_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    # 阶段 3：印章/签名匹配
    _touch_step(task_id, rid, "stage:vision", StepState.RUNNING.value, started_at=_now())
    try:
        _vision_stage(task_id, rid, snapshot, client)
        _touch_step(task_id, rid, "stage:vision", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:vision", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"VISION_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"VISION_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    _complete_run(rid)
