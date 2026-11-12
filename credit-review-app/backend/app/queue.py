"""Procrastinate 任务队列（PostgreSQL 持久化队列）。

本模块提供跨进程共享的 Procrastinate app，以及“同事务入队”辅助函数：
业务写入与队列入队在同一数据库事务内提交/回滚，避免“业务已提交却无任务”。
"""

import procrastinate

from app.core.config import settings


def _dsn() -> str:
    url = settings.DATABASE_URL
    for scheme in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql+psycopg3://"):
        if url.startswith(scheme):
            return "postgresql://" + url[len(scheme):]
    return url


app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_dsn()),
)


def enqueue(task, **task_kwargs) -> int:
    """在 API 进程内入队一个任务（确保 app 已 open，建立连接池）。

    worker 进程由 run_worker 已 open app，可直接 task.defer()；API 进程需经此函数。
    """
    with app.open():
        return task.configure(task_kwargs=task_kwargs).defer()


def enqueue_in_session(session, task, **task_kwargs) -> int:
    """在给定 SQLModel Session 的当前事务内同事务入队。

    业务写入与队列入队在同一数据库事务内提交/回滚。调用前需先 session.flush()
    业务写入，使底层连接可用。
    """
    raw = session.connection().connection.dbapi_connection
    return task.configure(task_kwargs=task_kwargs, connection=raw).defer()
