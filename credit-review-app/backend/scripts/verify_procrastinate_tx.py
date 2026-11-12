"""P0 验证脚本：Procrastinate 同事务入队。

证明：业务写入与队列入队在同一个数据库事务内一起提交或一起回滚，
不会出现“业务行已提交但任务永久丢失”或“事务回滚却启动了半条任务”。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import engine
from app.queue import app


@app.task(name="verify.noop")
def noop_task(x: int) -> None:
    pass


def _job_count(raw) -> int:
    with raw.cursor() as cur:
        cur.execute("SELECT count(*) FROM procrastinate_jobs")
        return cur.fetchone()[0]


def _defer(raw, x: int):
    return noop_task.configure(task_kwargs={"x": x}, connection=raw).defer()


_INSERT = text(
    "INSERT INTO tasks (id, owner_user_id, name, product_code, customer_role, state, input_revision, created_at, updated_at)"
    " VALUES (:id, :owner, :name, 'working_capital_loan', 'borrower', 'DRAFT', 0, :now, :now)"
)


def main() -> None:
    with engine.connect() as conn:
        user_id = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()

    # --- 场景 1：回滚 → 业务行与任务都回滚 ---
    with engine.connect() as conn:
        tx = conn.begin()
        raw = conn.connection.dbapi_connection
        conn.execute(_INSERT, {"id": uuid.uuid4(), "owner": user_id, "name": "rollback-case", "now": datetime.now(UTC)})
        _defer(raw, x=1)
        tx.rollback()

    with engine.connect() as conn:
        task_rows = conn.execute(text("SELECT count(*) FROM tasks WHERE name='rollback-case'")).scalar_one()
        raw = conn.connection.dbapi_connection
        job_rows = _job_count(raw)

    print(f"[回滚] 业务行数={task_rows} 任务数={job_rows}")
    assert task_rows == 0 and job_rows == 0, "回滚后业务行与任务都应为 0"

    # --- 场景 2：提交 → 业务行与任务都提交 ---
    with engine.connect() as conn:
        tx = conn.begin()
        raw = conn.connection.dbapi_connection
        conn.execute(_INSERT, {"id": uuid.uuid4(), "owner": user_id, "name": "commit-case", "now": datetime.now(UTC)})
        _defer(raw, x=2)
        tx.commit()

    with engine.connect() as conn:
        task_rows = conn.execute(text("SELECT count(*) FROM tasks WHERE name='commit-case'")).scalar_one()
        raw = conn.connection.dbapi_connection
        job_rows = _job_count(raw)

    print(f"[提交] 业务行数={task_rows} 任务数={job_rows}")
    assert task_rows == 1 and job_rows == 1, "提交后业务行与任务都应为 1"

    print("✅ 同事务入队验证通过：业务写入与队列入队原子提交/回滚。")


if __name__ == "__main__":
    main()
