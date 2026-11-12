import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, OwnedTask, SessionDep, require_csrf
from app.crud import create_task, list_tasks_for_user, touch_task
from app.models import CustomerRole, OcrJob, ProductCode, Task, TaskFile, TaskPublic

router = APIRouter(tags=["tasks"])

BORROWER_CHECKLIST_VERSION = "borrower-wcl-v1"


class TaskCreateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    customer_role: str = Field(default=CustomerRole.borrower.value)
    product_code: str = Field(default=ProductCode.working_capital_loan.value)


class TaskUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _effective_state(stored: str, fc: int, done: int, proc: int, failed: int) -> str:
    """根据文件 OCR 进度推导任务对外展示的状态。

    完成态/失败态是持久化的业务状态，优先保留；其余按进度推导：
    无文件→未开始(DRAFT)，识别中→PROCESSING，识别完待核对→REVIEWING。
    """
    if stored in ("COMPLETED", "FAILED"):
        return stored
    if fc == 0:
        return "DRAFT"
    if proc > 0:
        return "PROCESSING"
    return "REVIEWING"


def _to_public(task: Task, session) -> TaskPublic:
    pub = TaskPublic.model_validate(task)
    fc, done, proc, failed = _task_progress(session, task.id)
    pub.file_count = fc
    pub.ocr_done_count = done
    pub.ocr_processing_count = proc
    pub.ocr_failed_count = failed
    pub.state = _effective_state(task.state, fc, done, proc, failed)
    return pub


def _task_progress(session, task_id: uuid.UUID) -> tuple[int, int, int, int]:
    """统计任务的（文件数, 已识别, 识别中, 识别失败）。"""
    files = session.exec(
        select(TaskFile).where(TaskFile.task_id == task_id, TaskFile.deleted_at.is_(None))
    ).all()
    done = processing = failed = 0
    for f in files:
        job = session.exec(
            select(OcrJob).where(OcrJob.file_id == f.id).order_by(OcrJob.created_at.desc())
        ).first()
        if not job:
            continue
        if job.state == "SUCCEEDED":
            done += 1
        elif job.state == "FAILED":
            failed += 1
        else:
            processing += 1
    return len(files), done, processing, failed


@router.get("/tasks", response_model=list[TaskPublic])
def list_tasks(current_user: CurrentUser, session: SessionDep) -> list[TaskPublic]:
    tasks = list_tasks_for_user(session=session, owner_id=current_user.id)
    return [_to_public(t, session) for t in tasks]


@router.post("/tasks", response_model=TaskPublic, status_code=201, dependencies=[Depends(require_csrf)])
def create_task_endpoint(body: TaskCreateIn, current_user: CurrentUser, session: SessionDep) -> TaskPublic:
    role = body.customer_role
    if role != CustomerRole.borrower.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "ROLE_DISABLED", "message": "该客户类型检查清单待配置，暂不可创建任务"},
        )
    if body.product_code != ProductCode.working_capital_loan.value:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REQUEST", "message": "仅支持流动资金贷款"},
        )
    name = (body.name or "").strip() or f"资料核对 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    task = create_task(
        session=session,
        owner_id=current_user.id,
        name=name,
        product_code=body.product_code,
        customer_role=role,
        checklist_version=BORROWER_CHECKLIST_VERSION,
    )
    return _to_public(task, session)


@router.get("/tasks/{task_id}", response_model=TaskPublic)
def get_task(task: OwnedTask, session: SessionDep) -> TaskPublic:
    return _to_public(task, session)


@router.patch("/tasks/{task_id}", response_model=TaskPublic, dependencies=[Depends(require_csrf)])
def update_task(body: TaskUpdateIn, task: OwnedTask, session: SessionDep) -> TaskPublic:
    if task.state == "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail={"code": "TASK_READ_ONLY", "message": "任务已完成，不可修改"},
        )
    task.name = body.name.strip()
    return _to_public(touch_task(session=session, task=task), session)


@router.delete("/tasks/{task_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_task(task: OwnedTask, session: SessionDep) -> None:
    """软删除任务：标记 deleted_at，数据保留可审计追溯。

    已完成任务只读，与 update_task / files / runs 的写操作保持一致：
    COMPLETED 态直接拒绝，不写 deleted_at。
    """
    if task.state == "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail={"code": "TASK_READ_ONLY", "message": "任务已完成，不可删除"},
        )
    task.deleted_at = datetime.now(UTC)
    session.add(task)
    session.commit()
