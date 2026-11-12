import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))

ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def create_session_token(subject: str | Any, sid: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    expire = now + expires_delta
    to_encode = {
        "sub": str(subject),
        "sid": sid,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_sid() -> str:
    return uuid.uuid4().hex


def session_expires_delta() -> timedelta:
    return timedelta(hours=settings.SESSION_HOURS)
