import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlmodel import select

from app.api.deps import CurrentUser, OwnedTask, SessionDep, require_csrf
from app.core.config import settings
from app.crud import add_task_file, get_task_file, list_task_files, touch_task
from app.models import (
    Asset,
    MaterialType,
    OcrJob,
    ProcessingRun,
    RunFile,
    TaskFile,
    TaskFilePublic,
)
from app.ocr_pipeline import ocr_submit
from app.queue import enqueue
from app.storage import write_bytes

router = APIRouter(tags=["files"])

ALLOWED_MEDIA = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

_MAGIC = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}

_CHUNK = 1024 * 1024  # 1MiB


def _sniff_media(head: bytes) -> str | None:
    for media, magic in _MAGIC.items():
        if head.startswith(magic):
            return media
    return None


def _ocr_status(session, file_id: uuid.UUID) -> str | None:
    job = session.exec(
        select(OcrJob).where(OcrJob.file_id == file_id).order_by(OcrJob.created_at.desc())
    ).first()
    if not job:
        return None
    if job.state == "SUCCEEDED":
        return "done"
    if job.state == "FAILED":
        return "failed"
    return "processing"


def _effective_material_type(session, file_id: uuid.UUID) -> str | None:
    """文件实际生效的类别：人工覆盖优先，否则取最新 run 的自动分类。"""
    f = session.get(TaskFile, file_id)
    if f and f.manual_material_type:
        return f.manual_material_type
    rf = session.exec(
        select(RunFile)
        .join(ProcessingRun, RunFile.run_id == ProcessingRun.id)
        .where(RunFile.file_id == file_id, RunFile.effective_material_type.is_not(None))
        .order_by(ProcessingRun.created_at.desc())
    ).first()
    return rf.effective_material_type if rf else None


def _to_public(session, f: TaskFile) -> TaskFilePublic:
    return TaskFilePublic(
        id=f.id,
        original_name=f.original_name,
        media_type=f.media_type,
        size_bytes=f.size_bytes,
        sha256=f.sha256,
        original_asset_id=f.original_asset_id,
        material_type=_effective_material_type(session, f.id),
        page_count=f.source_page_count,
        ocr_status=_ocr_status(session, f.id),
        created_at=f.created_at,
    )


def _task_total_bytes(session: SessionDep, task_id: uuid.UUID) -> int:
    total = 0
    for f in list_task_files(session=session, task_id=task_id):
        total += f.size_bytes
    return total


@router.get("/tasks/{task_id}/files", response_model=list[TaskFilePublic])
def list_files(task: OwnedTask, session: SessionDep) -> list[TaskFilePublic]:
    files = list_task_files(session=session, task_id=task.id)
    return [_to_public(session, f) for f in files]


async def _save_upload(file: UploadFile, task_id: uuid.UUID) -> tuple[str, str, int, str]:
    """流式保存上传文件，返回 (storage_key, media_type, size, sha256)。"""
    # 读取头部嗅探真实类型
    head = await file.read(16)
    media = _sniff_media(head)
    if not media or media not in ALLOWED_MEDIA:
        raise HTTPException(
            status_code=415,
            detail={"code": "INVALID_FILE", "message": "仅支持 PDF、JPEG、PNG 文件"},
        )

    file_id = uuid.uuid4()
    storage_key = f"originals/{task_id}/{file_id}/original.bin"
    tmp_path = Path(settings.DATA_DIR) / "_tmp" / f"{file_id}.upload"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    size = 0
    try:
        with tmp_path.open("wb") as out:
            hasher.update(head)
            out.write(head)
            size += len(head)
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.UPLOAD_MAX_FILE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail={"code": "UPLOAD_LIMIT_EXCEEDED", "message": "单文件超出大小上限"},
                    )
                hasher.update(chunk)
                out.write(chunk)
        sha256 = hasher.hexdigest()
        write_bytes(storage_key, tmp_path.read_bytes())
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return storage_key, media, size, sha256


@router.post("/tasks/{task_id}/files", response_model=TaskFilePublic, status_code=201, dependencies=[Depends(require_csrf)])
async def upload_file(file: UploadFile, task: OwnedTask, current_user: CurrentUser, session: SessionDep) -> TaskFilePublic:
    if task.state == "COMPLETED":
        raise HTTPException(status_code=409, detail={"code": "TASK_READ_ONLY", "message": "任务已完成，不可上传"})

    existing = list_task_files(session=session, task_id=task.id)
    if len(existing) >= settings.UPLOAD_MAX_FILES_PER_TASK:
        raise HTTPException(
            status_code=413,
            detail={"code": "UPLOAD_LIMIT_EXCEEDED", "message": "文件数量超出上限"},
        )
    if _task_total_bytes(session, task.id) >= settings.UPLOAD_MAX_TASK_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "UPLOAD_LIMIT_EXCEEDED", "message": "任务文件总量超出上限"},
        )

    storage_key, media, size, sha256 = await _save_upload(file, task.id)

    # 同任务内字节去重：相同内容返回原 fileId
    for f in existing:
        if f.sha256 == sha256:
            return _to_public(session, f)

    db_file = add_task_file(
        session=session,
        task_id=task.id,
        original_name=file.filename or "unnamed",
        media_type=media,
        size_bytes=size,
        sha256=sha256,
    )
    asset = Asset(
        task_id=task.id,
        file_id=db_file.id,
        kind="original",
        storage_key=storage_key,
        sha256=sha256,
        media_type=media,
        size_bytes=size,
    )
    session.add(asset)
    db_file.original_asset_id = asset.id
    session.add(db_file)
    session.commit()
    session.refresh(db_file)
    # 上传首个文件后，任务从「草稿」进入「处理中」
    if task.state == "DRAFT":
        task.state = "PROCESSING"
    touch_task(session=session, task=task)
    # 触发后台 OCR（仅当服务已配置）
    if settings.ocr_configured:
        enqueue(ocr_submit, file_id=str(db_file.id))
    return _to_public(session, db_file)


@router.delete("/tasks/{task_id}/files/{file_id}", status_code=200, dependencies=[Depends(require_csrf)])
def delete_file(task: OwnedTask, session: SessionDep, file_id: uuid.UUID) -> dict:
    if task.state == "COMPLETED":
        raise HTTPException(status_code=409, detail={"code": "TASK_READ_ONLY", "message": "任务已完成"})
    db_file = get_task_file(session=session, task_id=task.id, file_id=file_id)
    if not db_file or db_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "文件不存在"})
    db_file.deleted_at = datetime.now(UTC)
    session.add(db_file)
    session.commit()
    touch_task(session=session, task=task)
    return {"message": "已移除"}


@router.patch("/tasks/{task_id}/files/{file_id}/classification", status_code=200, dependencies=[Depends(require_csrf)])
def classify_file(
    body: dict,
    task: OwnedTask,
    session: SessionDep,
    file_id: uuid.UUID,
) -> dict:
    if task.state == "COMPLETED":
        raise HTTPException(status_code=409, detail={"code": "TASK_READ_ONLY", "message": "任务已完成"})
    db_file = get_task_file(session=session, task_id=task.id, file_id=file_id)
    if not db_file or db_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "文件不存在"})
    material = body.get("material_type")
    valid = {m.value for m in MaterialType}
    if material is not None and material not in valid:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REQUEST", "message": "无效的材料类别"},
        )
    db_file.manual_material_type = material
    session.add(db_file)
    session.commit()
    return _to_public(session, db_file).model_dump()
