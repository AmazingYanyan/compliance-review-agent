from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, SESSION_COOKIE, SessionDep
from app.core import security
from app.core.config import settings
from app.crud import authenticate
from app.models import AuthSession, LoginResponse, UserPublic

router = APIRouter(tags=["auth"], prefix="/auth")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginIn, response: Response, session: SessionDep) -> LoginResponse:
    user = authenticate(session=session, username=body.username, password=body.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"},
        )
    sid = security.generate_sid()
    csrf_token = security.generate_csrf_token()
    auth_session = AuthSession(
        sid=sid,
        user_id=user.id,
        expires_at=datetime.now(UTC) + security.session_expires_delta(),
        csrf_token=csrf_token,
    )
    session.add(auth_session)
    session.commit()

    token = security.create_session_token(
        user.id, sid, expires_delta=security.session_expires_delta()
    )
    _set_session_cookie(response, token)
    return LoginResponse(user=UserPublic.model_validate(user), csrf_token=csrf_token)


@router.get("/me", response_model=LoginResponse)
def me(request: Request, current_user: CurrentUser, session: SessionDep) -> LoginResponse:
    auth_session: AuthSession = request.state.auth_session
    return LoginResponse(
        user=UserPublic.model_validate(current_user),
        csrf_token=auth_session.csrf_token,
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, current_user: CurrentUser, session: SessionDep) -> None:
    auth_session: AuthSession = request.state.auth_session
    auth_session.revoked_at = datetime.now(UTC)
    session.add(auth_session)
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
