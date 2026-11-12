"""本地维护命令行。

用法（在 backend/ 目录或容器 /app/backend 下）：
    python -m app.cli migrate
    python -m app.cli seed-users
    python -m app.cli reset-password --username <name> --password <pw>
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.core.config import settings
from app.crud import create_user, get_user_by_username, set_user_password
from app.models import AuthSession, User


def _alembic_upgrade() -> None:
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")


def _procrastinate_schema() -> None:
    from sqlalchemy import text

    from app.core.db import engine
    from app.queue import app

    # apply_schema 不幂等（会重复 CREATE TYPE），已存在则跳过
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('procrastinate_jobs') IS NOT NULL")
        ).scalar_one()
    if exists:
        print("Procrastinate schema 已存在，跳过")
        return
    with app.open():
        app.schema_manager.apply_schema()


def migrate() -> None:
    print("应用业务迁移…")
    _alembic_upgrade()
    print("应用 Procrastinate schema…")
    _procrastinate_schema()
    print("迁移完成")


def seed_users() -> None:
    raw = settings.INITIAL_USERS_JSON
    users = json.loads(raw) if raw else []
    config_usernames = {
        (entry.get("username") or "").strip().lower()
        for entry in users
        if (entry.get("username") or "").strip()
    }
    with Session(engine) as session:
        # 禁用不在配置里的账号（保证只有配置账号可登录，数据保留）
        for u in session.exec(select(User)).all():
            if u.username not in config_usernames and u.is_active:
                u.is_active = False
                session.add(u)
                print(f"已禁用账号：{u.username}")

        for entry in users:
            username = (entry.get("username") or "").strip()
            password = entry.get("password") or ""
            if not username or not password:
                print(f"跳过无效账号条目: {entry}")
                continue
            existing = get_user_by_username(session=session, username=username)
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    session.add(existing)
                    print(f"已启用账号：{username}")
                else:
                    print(f"账号已存在：{username}")
                continue
            create_user(session=session, username=username, password=password)
            print(f"已创建账号：{username}")
        session.commit()
    print("账号初始化完成")


def reset_password(username: str, password: str) -> None:
    with Session(engine) as session:
        user = get_user_by_username(session=session, username=username)
        if not user:
            print(f"账号不存在：{username}")
            return
        set_user_password(session=session, user=user, password=password)
        # 撤销该用户既有会话
        sessions = session.exec(
            select(AuthSession).where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        for s in sessions:
            s.revoked_at = datetime.now(UTC)
        session.commit()
        print(f"已重置密码并撤销会话：{username}")


def import_ocr_json(file_id: str, json_path: str) -> None:
    """把外部已完成的 OCR 结果 json（每页对象数组）导入，替代 worker 的下载/轮询。

    json 形如 [ {prunedResult, markdown, outputImages, inputImage}, ... ]（每页一个对象），
    与 PaddleOCR-VL 官方导出格式一致。
    """
    import uuid as _uuid

    from app.models import Crop, OcrBlock, OcrJob, OcrPage, TaskFile
    from app.ocr_client import build_request_config
    from app.ocr_normalize import parse_page
    from app.storage import write_bytes

    fid = _uuid.UUID(file_id)
    with Session(engine) as session:
        tf = session.get(TaskFile, fid)
        if not tf:
            print(f"文件不存在: {file_id}")
            return
        task_id = tf.task_id
        original_name = tf.original_name

    with open(json_path, encoding="utf-8") as fh:
        pages = json.load(fh)
    if not isinstance(pages, list):
        print("JSON 格式不正确：应为每页对象组成的数组")
        return

    # 清理该文件旧 OCR 数据（按外键依赖顺序：crops → blocks → pages → jobs）
    with Session(engine) as session:
        for c in session.exec(select(Crop).where(Crop.file_id == fid)).all():
            session.delete(c)
        for b in session.exec(select(OcrBlock).where(OcrBlock.file_id == fid)).all():
            session.delete(b)
        for p in session.exec(select(OcrPage).where(OcrPage.file_id == fid)).all():
            session.delete(p)
        for j in session.exec(select(OcrJob).where(OcrJob.file_id == fid)).all():
            session.delete(j)
        session.commit()

    job = OcrJob(
        task_id=task_id,
        file_id=fid,
        request_config_hash=build_request_config()[1],
        state="SUCCEEDED",
        provider_job_id="imported",
        submitted_at=datetime.now(UTC),
        provider_metadata={"source": "import-ocr-json", "page_count": len(pages)},
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    # 归档原始 json
    jsonl_key = f"ocr/{task_id}/{fid}/{job_id}/imported.json"
    write_bytes(jsonl_key, json.dumps(pages, ensure_ascii=False).encode("utf-8"))

    with Session(engine) as session:
        for page_index, page_obj in enumerate(pages):
            page_meta, blocks, crops = parse_page(page_obj)
            ocr_page = OcrPage(
                task_id=task_id,
                file_id=fid,
                ocr_job_id=job_id,
                provider_line_index=page_index,
                provider_item_index=0,
                ocr_page_index=page_index,
                source_page_number=page_index + 1,
                mapping_status="unverified",
                width_px=page_meta["width_px"],
                height_px=page_meta["height_px"],
                coordinate_space=page_meta["coordinate_space"],
                transform_metadata=page_meta["transform_metadata"],
            )
            session.add(ocr_page)
            session.flush()
            for b in blocks:
                session.add(OcrBlock(task_id=task_id, file_id=fid, page_id=ocr_page.id, **b))
            session.flush()
            # 外部结果图片（带签名 URL）不下载，仅记录元数据
            for c in crops:
                session.add(
                    Crop(
                        task_id=task_id,
                        file_id=fid,
                        page_id=ocr_page.id,
                        provider_label=c["provider_label"],
                        kind=c["kind"],
                        recognized_text=c["recognized_text"],
                        bbox=c["bbox"],
                        polygon=c["polygon"],
                        image_status="failed" if c.get("image_url") else "pending",
                    )
                )
        session.commit()
    print(f"已导入 {len(pages)} 页 OCR 结果到文件「{original_name}」（job={job_id}）")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate")
    sub.add_parser("seed-users")

    rp = sub.add_parser("reset-password")
    rp.add_argument("--username", required=True)
    rp.add_argument("--password", required=True)

    imp = sub.add_parser("import-ocr-json")
    imp.add_argument("--file-id", required=True)
    imp.add_argument("--json", required=True)

    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "seed-users":
        seed_users()
    elif args.command == "reset-password":
        reset_password(args.username, args.password)
    elif args.command == "import-ocr-json":
        import_ocr_json(args.file_id, args.json)


if __name__ == "__main__":
    main()
