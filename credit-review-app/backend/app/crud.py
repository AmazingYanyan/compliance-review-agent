import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import Task, TaskFile, User

DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def _now() -> datetime:
    return datetime.now(UTC)


# --- 用户 ---


def get_user_by_username(*, session: Session, username: str) -> User | None:
    stmt = select(User).where(User.username == username.strip().lower())
    return session.exec(stmt).first()


def authenticate(*, session: Session, username: str, password: str) -> User | None:
    db_user = get_user_by_username(session=session, username=username)
    if not db_user:
        # 时序攻击防护：用户不存在时也跑一次哈希校验
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_hash = verify_password(password, db_user.password_hash)
    if not verified:
        return None
    if updated_hash:
        db_user.password_hash = updated_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_user(*, session: Session, username: str, password: str) -> User:
    db_user = User(
        username=username.strip().lower(),
        password_hash=get_password_hash(password),
        is_active=True,
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def set_user_password(*, session: Session, user: User, password: str) -> None:
    user.password_hash = get_password_hash(password)
    session.add(user)
    session.commit()


# --- 任务 ---


def get_task_for_user(*, session: Session, task_id: uuid.UUID, owner_id: uuid.UUID) -> Task | None:
    stmt = select(Task).where(
        Task.id == task_id, Task.owner_user_id == owner_id, Task.deleted_at.is_(None)
    )
    return session.exec(stmt).first()


def create_task(
    *,
    session: Session,
    owner_id: uuid.UUID,
    name: str,
    product_code: str,
    customer_role: str,
    checklist_version: str | None,
) -> Task:
    db_task = Task(
        owner_user_id=owner_id,
        name=name,
        product_code=product_code,
        customer_role=customer_role,
        checklist_version=checklist_version,
        state="DRAFT",
        input_revision=0,
    )
    session.add(db_task)
    session.commit()
    session.refresh(db_task)
    return db_task


def list_tasks_for_user(*, session: Session, owner_id: uuid.UUID) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.owner_user_id == owner_id, Task.deleted_at.is_(None))
        .order_by(Task.updated_at.desc(), Task.id)
    )
    return list(session.exec(stmt).all())


def touch_task(*, session: Session, task: Task) -> Task:
    task.updated_at = _now()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# --- 文件 ---


def list_task_files(*, session: Session, task_id: uuid.UUID) -> list[TaskFile]:
    stmt = select(TaskFile).where(
        TaskFile.task_id == task_id, TaskFile.deleted_at.is_(None)
    )
    return list(session.exec(stmt).all())


def get_task_file(*, session: Session, task_id: uuid.UUID, file_id: uuid.UUID) -> TaskFile | None:
    stmt = select(TaskFile).where(
        TaskFile.task_id == task_id, TaskFile.id == file_id
    )
    return session.exec(stmt).first()


def add_task_file(
    *,
    session: Session,
    task_id: uuid.UUID,
    original_name: str,
    media_type: str,
    size_bytes: int,
    sha256: str,
) -> TaskFile:
    db_file = TaskFile(
        task_id=task_id,
        original_name=original_name,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
    )
    session.add(db_file)
    session.commit()
    session.refresh(db_file)
    return db_file
