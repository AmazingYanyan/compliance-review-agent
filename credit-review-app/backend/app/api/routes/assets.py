import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Asset, Task
from app.storage import resolve

router = APIRouter(tags=["assets"])


@router.get("/tasks/{task_id}/assets/{asset_id}")
def get_asset(
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> FileResponse:
    # 先校验任务归属，再查资产，避免跨账号通过 asset_id 越权读取
    task = session.exec(
        select(Task).where(Task.id == task_id, Task.owner_user_id == current_user.id)
    ).first()
    if not task:
        raise HTTPException(
            status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
        )
    asset = session.exec(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.task_id == task_id,
        )
    ).first()
    if not asset:
        raise HTTPException(
            status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
        )
    path = resolve(asset.storage_key)
    if not path.exists():
        raise HTTPException(
            status_code=404, detail={"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
        )
    return FileResponse(path, media_type=asset.media_type or "application/octet-stream")
