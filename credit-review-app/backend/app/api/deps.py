import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import AuthSession, Task, User

SESSION_COOKIE = "session"


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "SESSION_EXPIRED", "message": "会话无效或已过期"},
    )


def get_current_user(request: Request, session: SessionDep) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()
    payload = security.decode_session_token(token)
    if not payload:
        raise _unauthorized()
    sid = payload.get("sid")
    sub = payload.get("sub")
    if not sid or not sub:
        raise _unauthorized()
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.sid == sid)
    ).first()
    if (
        not auth_session
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.now(UTC)
    ):
        raise _unauthorized()
    user = session.get(User, uuid.UUID(sub))
    if not user or not user.is_active:
        raise _unauthorized()
    # 把当前会话挂到 request.state，供 CSRF 校验复用
    request.state.auth_session = auth_session
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _origin_allowed(origin: str, allowed: str) -> bool:
    """Origin 校验：localhost / 127.0.0.1 / ::1 视为等价回环地址，scheme 与端口需一致。"""
    if origin == allowed:
        return True
    from urllib.parse import urlparse

    o, a = urlparse(origin), urlparse(allowed)
    if o.scheme != a.scheme or o.port != a.port:
        return False
    loopback = {"localhost", "127.0.0.1", "::1"}
    return o.hostname in loopback and a.hostname in loopback


def require_csrf(request: Request, _: CurrentUser) -> None:
    """写请求（登录除外）校验 CSRF token 与 Origin。"""
    origin = request.headers.get("origin")
    if origin and not _origin_allowed(origin, settings.PUBLIC_ORIGIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_FAILED", "message": "Origin 校验失败"},
        )
    provided = request.headers.get("X-CSRF-Token")
    auth_session: AuthSession | None = getattr(request.state, "auth_session", None)
    if not provided or not auth_session or provided != auth_session.csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_FAILED", "message": "CSRF token 校验失败"},
        )


def get_owned_task(task_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Task:
    task = session.exec(
        select(Task).where(
            Task.id == task_id,
            Task.owner_user_id == current_user.id,
            Task.deleted_at.is_(None),
        )
    ).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "任务不存在"},
        )
    return task


OwnedTask = Annotated[Task, Depends(get_owned_task)]
