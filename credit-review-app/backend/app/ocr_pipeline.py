"""OCR 后台流水线：提交 → 轮询 → 下载归档 → 规范化。

每个阶段是独立的 Procrastinate 任务，作业状态持久化在 ocr_jobs，
worker 重启后可基于已知 provider_job_id 恢复查询，不重复提交。
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import Asset, Crop, OcrBlock, OcrJob, OcrPage, TaskFile
from app.ocr_client import OcrClient, build_request_config
from app.ocr_normalize import parse_jsonl, parse_page
from app.queue import app
from app.storage import write_bytes


def _now() -> datetime:
    return datetime.now(UTC)


def _deadline() -> datetime:
    return _now() + timedelta(seconds=settings.OCR_TOTAL_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------


@app.task(name="ocr.submit", queue="ocr")
def ocr_submit(file_id: str) -> None:
    fid = uuid.UUID(file_id)
    with Session(engine) as session:
        task_file = session.get(TaskFile, fid)
        if not task_file:
            return
        # 已有成功 OCR 结果（例如经 import-ocr-json 导入）则跳过，不重复提交
        succeeded = session.exec(
            select(OcrJob).where(OcrJob.file_id == fid, OcrJob.state == "SUCCEEDED")
        ).first()
        if succeeded:
            return
        # 已有未终结的作业则复用，不重复提交
        existing = session.exec(
            select(OcrJob).where(
                OcrJob.file_id == fid,
                OcrJob.state.in_(
                    ["NOT_SUBMITTED", "SUBMITTED", "RUNNING", "DOWNLOADING", "SUBMISSION_UNKNOWN"]
                ),
            )
        ).first()
        if existing:
            return

        # 读取原文件字节
        asset = session.get(Asset, task_file.original_asset_id) if task_file.original_asset_id else None
        if not asset:
            _mark_failed(session, task_file.task_id, fid, "ASSET_NOT_FOUND")
            return
        from app.storage import read_bytes

        try:
            file_bytes = read_bytes(asset.storage_key)
        except Exception:
            _mark_failed(session, task_file.task_id, fid, "ASSET_READ_FAILED")
            return

        config_hash = build_request_config()[1]
        job = OcrJob(
            task_id=task_file.task_id,
            file_id=fid,
            request_config_hash=config_hash,
            state="NOT_SUBMITTED",
            attempt=0,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        # 提取标量，避免 session 关闭后访问 ORM 对象
        job_id = job.id
        original_name = task_file.original_name
        media_type = task_file.media_type

    client = OcrClient()
    try:
        provider_job_id = client.submit(file_bytes, original_name, media_type)
    except Exception as exc:  # noqa: BLE001
        with Session(engine) as session:
            j = session.get(OcrJob, job_id)
            if j:
                # 连接级错误视为“未确定是否已提交”，保守占位
                j.state = "SUBMISSION_UNKNOWN"
                j.last_error_code = type(exc).__name__
                j.deadline_at = _deadline()
                session.add(j)
                session.commit()
        return
    finally:
        client.close()

    with Session(engine) as session:
        j = session.get(OcrJob, job_id)
        if j:
            j.provider_job_id = provider_job_id
            j.state = "SUBMITTED"
            j.submitted_at = _now()
            j.next_poll_at = _now() + timedelta(seconds=settings.OCR_POLL_INTERVAL_SECONDS)
            j.deadline_at = _deadline()
            session.add(j)
            session.commit()
            job_id_str = str(j.id)

    ocr_poll.configure(
        task_kwargs={"ocr_job_id": job_id_str},
        schedule_at=_now() + timedelta(seconds=settings.OCR_POLL_INTERVAL_SECONDS),
    ).defer()


# ---------------------------------------------------------------------------
# 轮询
# ---------------------------------------------------------------------------


@app.task(name="ocr.poll", queue="ocr")
def ocr_poll(ocr_job_id: str) -> None:
    oid = uuid.UUID(ocr_job_id)
    with Session(engine) as session:
        job = session.get(OcrJob, oid)
        if not job or job.state not in ("SUBMITTED", "RUNNING"):
            return
        provider_job_id = job.provider_job_id
    if not provider_job_id:
        return

    client = OcrClient()
    try:
        data = client.get(provider_job_id)
    except Exception as exc:  # noqa: BLE001
        with Session(engine) as session:
            j = session.get(OcrJob, oid)
            if j:
                j.attempt += 1
                j.last_error_code = type(exc).__name__
                j.next_poll_at = _now() + timedelta(seconds=settings.OCR_POLL_INTERVAL_SECONDS)
                session.add(j)
                session.commit()
        _reschedule_poll(oid)
        return
    finally:
        client.close()

    state = data.get("state")
    now = _now()

    with Session(engine) as session:
        j = session.get(OcrJob, oid)
        if not j:
            return
        j.state = "RUNNING" if state in ("pending", "running") else j.state
        if state in ("pending", "running"):
            if now >= (j.deadline_at or now):
                j.state = "FAILED"
                j.last_error_code = "OCR_TIMEOUT"
                session.add(j)
                session.commit()
                return
            j.next_poll_at = now + timedelta(seconds=settings.OCR_POLL_INTERVAL_SECONDS)
            session.add(j)
            session.commit()
            _reschedule_poll(oid)
            return
        if state == "done":
            json_url = (data.get("resultUrl") or {}).get("jsonUrl")
            if not json_url:
                j.state = "FAILED"
                j.last_error_code = "OCR_RESULT_INVALID"
                session.add(j)
                session.commit()
                return
            j.state = "DOWNLOADING"
            j.provider_metadata = {"json_url": json_url}
            session.add(j)
            session.commit()
            ocr_download.configure(task_kwargs={"ocr_job_id": ocr_job_id}).defer()
            return
        if state == "failed":
            j.state = "FAILED"
            j.last_error_code = (data.get("errorMsg") or "OCR_FAILED")[:64]
            session.add(j)
            session.commit()
            return


def _reschedule_poll(ocr_job_id: uuid.UUID) -> None:
    ocr_poll.configure(
        task_kwargs={"ocr_job_id": str(ocr_job_id)},
        schedule_at=_now() + timedelta(seconds=settings.OCR_POLL_INTERVAL_SECONDS),
    ).defer()


# ---------------------------------------------------------------------------
# 下载 + 归档 + 规范化
# ---------------------------------------------------------------------------


@app.task(name="ocr.download", queue="ocr")
def ocr_download(ocr_job_id: str) -> None:
    oid = uuid.UUID(ocr_job_id)
    with Session(engine) as session:
        job = session.get(OcrJob, oid)
        if not job or job.state != "DOWNLOADING":
            return
        task_id = job.task_id
        file_id = job.file_id
        json_url = (job.provider_metadata or {}).get("json_url")
    if not json_url:
        return

    client = OcrClient()
    try:
        jsonl = client.download_jsonl(json_url)
    except Exception as exc:  # noqa: BLE001
        _mark_failed_job(oid, "ASSET_DOWNLOAD_FAILED")
        return
    finally:
        client.close()

    # 归档 JSONL
    jsonl_key = f"ocr/{task_id}/{file_id}/{oid}/result.jsonl"
    write_bytes(jsonl_key, jsonl)

    try:
        _ingest(oid, task_id, file_id, jsonl)
    except Exception as exc:  # noqa: BLE001
        _mark_failed_job(oid, f"INGEST_FAILED:{type(exc).__name__}"[:64])
        return

    with Session(engine) as session:
        j = session.get(OcrJob, oid)
        if j:
            j.state = "SUCCEEDED"
            j.result_asset_id = None  # JSONL 归档键在 provider_metadata
            j.provider_metadata = {**(j.provider_metadata or {}), "jsonl_key": jsonl_key}
            session.add(j)
            session.commit()


def _ingest(ocr_job_id: uuid.UUID, task_id: uuid.UUID, file_id: uuid.UUID, jsonl: bytes) -> None:
    pages = parse_jsonl(jsonl)
    client = OcrClient()
    try:
        with Session(engine) as session:
            for page_index, p in enumerate(pages):
                page_meta, blocks, crops = parse_page(p["page"])
                ocr_page = OcrPage(
                    task_id=task_id,
                    file_id=file_id,
                    ocr_job_id=ocr_job_id,
                    provider_line_index=p["line_index"],
                    provider_item_index=p["item_index"],
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
                    session.add(OcrBlock(
                        task_id=task_id, file_id=file_id, page_id=ocr_page.id, **b
                    ))
                session.flush()

                for c in crops:
                    crop = Crop(
                        task_id=task_id, file_id=file_id, page_id=ocr_page.id,
                        provider_label=c["provider_label"], kind=c["kind"],
                        recognized_text=c["recognized_text"],
                        bbox=c["bbox"], polygon=c["polygon"],
                    )
                    session.add(crop)
                    session.flush()
                    # 下载裁剪图并归档
                    url = c["image_url"]
                    if url:
                        try:
                            img_bytes = client.download_image(url)
                            img_key = f"ocr/{task_id}/{file_id}/{ocr_job_id}/crops/{crop.id}.jpg"
                            write_bytes(img_key, img_bytes)
                            asset = Asset(
                                task_id=task_id, file_id=file_id, kind="crop",
                                storage_key=img_key, size_bytes=len(img_bytes),
                                media_type="image/jpeg",
                            )
                            session.add(asset)
                            session.flush()
                            crop.image_asset_id = asset.id
                            crop.image_status = "downloaded"
                        except Exception:  # noqa: BLE001
                            crop.image_status = "failed"
            session.commit()
    finally:
        client.close()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _mark_failed(session: Session, task_id: uuid.UUID, file_id: uuid.UUID, code: str) -> None:
    job = OcrJob(
        task_id=task_id,
        file_id=file_id,
        request_config_hash=build_request_config()[1],
        state="FAILED",
        last_error_code=code,
    )
    session.add(job)
    session.commit()


def _mark_failed_job(ocr_job_id: uuid.UUID, code: str) -> None:
    with Session(engine) as session:
        j = session.get(OcrJob, ocr_job_id)
        if j:
            j.state = "FAILED"
            j.last_error_code = code
            session.add(j)
            session.commit()
