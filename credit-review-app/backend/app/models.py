import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Column, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# 枚举（字符串存储，迁移中用 CHECK 约束）
# ---------------------------------------------------------------------------


class CustomerRole(StrEnum):
    borrower = "borrower"
    guarantor = "guarantor"
    pledgor = "pledgor"


class ProductCode(StrEnum):
    working_capital_loan = "working_capital_loan"


class MaterialType(StrEnum):
    business_license = "business_license"
    articles_of_association = "articles_of_association"
    audited_financials = "audited_financials"


class TaskState(StrEnum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    REVIEWING = "REVIEWING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class AssetKind(StrEnum):
    original = "original"
    ocr_raw = "ocr_raw"
    page_raster = "page_raster"
    crop = "crop"


class RunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class StepState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class SearchStatus(StrEnum):
    found = "found"
    not_found = "not_found"


class ResultKind(StrEnum):
    text = "text"
    table = "table"
    seal = "seal"
    signature = "signature"
    not_found = "not_found"


class RecognitionSource(StrEnum):
    ocr = "ocr"
    vision = "vision"


class RelationStatus(StrEnum):
    matched = "matched"
    needs_review = "needs_review"


class LocationPrecision(StrEnum):
    region = "region"
    page = "page"
    none = "none"


class DecisionValue(StrEnum):
    unselected = "unselected"
    accepted = "accepted"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# 用户与会话
# ---------------------------------------------------------------------------


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(max_length=64, unique=True, index=True)
    password_hash: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=get_datetime_utc)


class AuthSession(SQLModel, table=True):
    __tablename__ = "auth_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sid: str = Field(max_length=64, unique=True, index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    expires_at: datetime
    revoked_at: datetime | None = Field(default=None)
    csrf_token: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=get_datetime_utc)


# ---------------------------------------------------------------------------
# 任务与文件
# ---------------------------------------------------------------------------


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=120)
    product_code: str = Field(max_length=64)
    customer_role: str = Field(max_length=32)
    checklist_version: str | None = Field(default=None, max_length=64)
    state: str = Field(default=TaskState.DRAFT.value, max_length=20)
    input_revision: int = Field(default=0)
    current_run_id: uuid.UUID | None = Field(default=None)
    last_ready_run_id: uuid.UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    updated_at: datetime = Field(default_factory=get_datetime_utc)
    completed_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)

    __table_args__ = (
        Index("ix_tasks_owner_updated", "owner_user_id", "updated_at", "id"),
        Index("ix_tasks_owner_deleted", "owner_user_id", "deleted_at"),
    )


class TaskFile(SQLModel, table=True):
    __tablename__ = "task_files"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(foreign_key="tasks.id", index=True)
    original_name: str = Field(max_length=512)
    media_type: str = Field(max_length=128)
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    sha256: str = Field(max_length=64)
    original_asset_id: uuid.UUID | None = Field(default=None)
    source_page_count: int | None = Field(default=None)
    manual_material_type: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    deleted_at: datetime | None = Field(default=None)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_task_files_task_id_id"),
        Index("ix_task_files_task_deleted", "task_id", "deleted_at"),
    )


class Asset(SQLModel, table=True):
    __tablename__ = "assets"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    kind: str = Field(max_length=32)
    storage_key: str = Field(max_length=512)
    sha256: str | None = Field(default=None, max_length=64)
    media_type: str | None = Field(default=None, max_length=128)
    size_bytes: int | None = Field(default=None, sa_column=Column(BigInteger))
    width_px: int | None = Field(default=None)
    height_px: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=get_datetime_utc)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_assets_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["task_files.task_id", "task_files.id"],
            name="fk_assets_task_file",
        ),
    )


class ViewState(SQLModel, table=True):
    __tablename__ = "view_states"

    user_id: uuid.UUID = Field(primary_key=True, foreign_key="users.id")
    task_id: uuid.UUID = Field(primary_key=True, foreign_key="tasks.id")
    material_type: str = Field(primary_key=True, max_length=64)
    file_id: uuid.UUID | None = Field(default=None)
    page_number: int | None = Field(default=None)
    zoom: float | None = Field(default=None)
    left_anchor: dict | None = Field(default=None, sa_column=Column(JSONB))
    right_anchor: dict | None = Field(default=None, sa_column=Column(JSONB))
    updated_at: datetime = Field(default_factory=get_datetime_utc)


class IdempotencyKey(SQLModel, table=True):
    __tablename__ = "idempotency_keys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    task_id: uuid.UUID | None = Field(default=None, index=True)
    key: str = Field(max_length=64)
    operation: str = Field(max_length=64)
    request_hash: str = Field(max_length=64)
    response_status: int | None = Field(default=None)
    response_body: dict | None = Field(default=None, sa_column=Column(JSONB))
    expires_at: datetime

    __table_args__ = (
        UniqueConstraint("user_id", "task_id", "key", "operation", name="uq_idem_user_task_key_op"),
    )


# ---------------------------------------------------------------------------
# OCR 相关枚举
# ---------------------------------------------------------------------------


class OcrJobState(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    DOWNLOADING = "DOWNLOADING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"


class CropKind(StrEnum):
    seal = "seal"
    signature = "signature"
    image = "image"
    unknown = "unknown"


class CropImageStatus(StrEnum):
    pending = "pending"
    downloaded = "downloaded"
    failed = "failed"


class PageMappingStatus(StrEnum):
    verified = "verified"
    unverified = "unverified"


# ---------------------------------------------------------------------------
# OCR：作业 / 页 / 块 / 裁剪图
# ---------------------------------------------------------------------------


class OcrJob(SQLModel, table=True):
    __tablename__ = "ocr_jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    request_config_hash: str = Field(max_length=64)
    provider_job_id: str | None = Field(default=None, max_length=128)
    state: str = Field(default=OcrJobState.NOT_SUBMITTED.value, max_length=32)
    attempt: int = Field(default=0)
    submitted_at: datetime | None = Field(default=None)
    next_poll_at: datetime | None = Field(default=None)
    deadline_at: datetime | None = Field(default=None)
    result_asset_id: uuid.UUID | None = Field(default=None)
    last_error_code: str | None = Field(default=None, max_length=64)
    provider_metadata: dict | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=get_datetime_utc)
    updated_at: datetime = Field(default_factory=get_datetime_utc)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_ocr_jobs_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["task_files.task_id", "task_files.id"],
            name="fk_ocr_jobs_task_file",
        ),
        Index("ix_ocr_jobs_state_next_poll", "state", "next_poll_at"),
    )


class OcrPage(SQLModel, table=True):
    __tablename__ = "ocr_pages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    ocr_job_id: uuid.UUID | None = Field(default=None)
    provider_line_index: int = Field(default=0)
    provider_item_index: int = Field(default=0)
    ocr_page_index: int = Field(default=0)
    source_page_number: int | None = Field(default=None)
    mapping_status: str = Field(default=PageMappingStatus.unverified.value, max_length=16)
    raster_asset_id: uuid.UUID | None = Field(default=None)
    width_px: int | None = Field(default=None)
    height_px: int | None = Field(default=None)
    coordinate_space: str = Field(default="unknown", max_length=32)
    transform_metadata: dict | None = Field(default=None, sa_column=Column(JSONB))

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_ocr_pages_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["task_files.task_id", "task_files.id"],
            name="fk_ocr_pages_task_file",
        ),
        ForeignKeyConstraint(
            ["task_id", "ocr_job_id"],
            ["ocr_jobs.task_id", "ocr_jobs.id"],
            name="fk_ocr_pages_task_job",
        ),
    )


class OcrBlock(SQLModel, table=True):
    __tablename__ = "ocr_blocks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    page_id: uuid.UUID | None = Field(default=None)
    provider_block_id: str | None = Field(default=None, max_length=128)
    group_id: str | None = Field(default=None, max_length=128)
    global_block_id: str | None = Field(default=None, max_length=128)
    global_group_id: str | None = Field(default=None, max_length=128)
    sequence_index: int = Field(default=0)
    label: str | None = Field(default=None, max_length=32)
    canonical_text: str = Field(default="")
    table_html: str | None = Field(default=None)
    bbox: Any | None = Field(default=None, sa_column=Column(JSONB))
    polygon: Any | None = Field(default=None, sa_column=Column(JSONB))
    raw_content_ref: str | None = Field(default=None, max_length=512)
    crop_id: uuid.UUID | None = Field(default=None)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_ocr_blocks_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["task_files.task_id", "task_files.id"],
            name="fk_ocr_blocks_task_file",
        ),
        ForeignKeyConstraint(
            ["task_id", "page_id"],
            ["ocr_pages.task_id", "ocr_pages.id"],
            name="fk_ocr_blocks_task_page",
        ),
    )


class Crop(SQLModel, table=True):
    __tablename__ = "crops"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    page_id: uuid.UUID | None = Field(default=None)
    block_id: uuid.UUID | None = Field(default=None)
    provider_label: str | None = Field(default=None, max_length=32)
    kind: str = Field(default=CropKind.unknown.value, max_length=16)
    recognized_text: str | None = Field(default=None)
    image_asset_id: uuid.UUID | None = Field(default=None)
    bbox: Any | None = Field(default=None, sa_column=Column(JSONB))
    polygon: Any | None = Field(default=None, sa_column=Column(JSONB))
    image_status: str = Field(default=CropImageStatus.pending.value, max_length=16)
    created_at: datetime = Field(default_factory=get_datetime_utc)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_crops_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "page_id"],
            ["ocr_pages.task_id", "ocr_pages.id"],
            name="fk_crops_task_page",
        ),
        ForeignKeyConstraint(
            ["task_id", "block_id"],
            ["ocr_blocks.task_id", "ocr_blocks.id"],
            name="fk_crops_task_block",
        ),
    )


# ---------------------------------------------------------------------------
# 处理管线（P3）：run / 文件快照 / 步骤 / 检查执行 / 结果 / 出处
# ---------------------------------------------------------------------------


class ProcessingRun(SQLModel, table=True):
    __tablename__ = "processing_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(foreign_key="tasks.id", index=True)
    input_revision: int = Field(default=0)
    checklist_snapshot: dict | None = Field(default=None, sa_column=Column(JSONB))
    checklist_hash: str = Field(max_length=64)
    model_snapshot: dict | None = Field(default=None, sa_column=Column(JSONB))
    state: str = Field(default=RunState.QUEUED.value, max_length=20)
    stage: str | None = Field(default=None, max_length=64)
    input_manifest_hash: str | None = Field(default=None, max_length=64)
    coverage_complete: bool = Field(default=False)
    error_code: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_runs_task_id_id"),
        Index("ix_runs_task_revision", "task_id", "input_revision"),
    )


class RunFile(SQLModel, table=True):
    __tablename__ = "run_files"

    run_id: uuid.UUID = Field(primary_key=True)
    file_id: uuid.UUID = Field(primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    effective_material_type: str | None = Field(default=None, max_length=64)
    classification_source: str | None = Field(default=None, max_length=32)
    classification_reason: str | None = Field(default=None)
    ocr_job_id: uuid.UUID | None = Field(default=None)

    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "run_id"],
            ["processing_runs.task_id", "processing_runs.id"],
            name="fk_run_files_run",
        ),
        ForeignKeyConstraint(
            ["task_id", "file_id"],
            ["task_files.task_id", "task_files.id"],
            name="fk_run_files_task_file",
        ),
    )


class RunStep(SQLModel, table=True):
    __tablename__ = "run_steps"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    run_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    step_key: str = Field(max_length=64)
    input_hash: str = Field(max_length=64)
    state: str = Field(default=StepState.QUEUED.value, max_length=20)
    attempt: int = Field(default=0)
    provider_request_id: str | None = Field(default=None, max_length=128)
    result_asset_id: uuid.UUID | None = Field(default=None)
    last_error_code: str | None = Field(default=None, max_length=64)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_run_steps_task_id_id"),
        UniqueConstraint("run_id", "step_key", "input_hash", name="uq_run_steps_key_hash"),
        ForeignKeyConstraint(
            ["task_id", "run_id"],
            ["processing_runs.task_id", "processing_runs.id"],
            name="fk_run_steps_run",
        ),
    )


class CheckExecution(SQLModel, table=True):
    __tablename__ = "check_executions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    run_id: uuid.UUID = Field(index=True)
    check_item_id: str = Field(max_length=128)
    dependency_hash: str = Field(max_length=64)
    search_status: str = Field(default=SearchStatus.not_found.value, max_length=16)
    coverage: dict | None = Field(default=None, sa_column=Column(JSONB))
    completed_at: datetime | None = Field(default=None)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_check_exec_task_id_id"),
        UniqueConstraint("run_id", "check_item_id", name="uq_check_exec_run_item"),
        ForeignKeyConstraint(
            ["task_id", "run_id"],
            ["processing_runs.task_id", "processing_runs.id"],
            name="fk_check_exec_run",
        ),
    )


class Result(SQLModel, table=True):
    __tablename__ = "results"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    run_id: uuid.UUID = Field(index=True)
    check_execution_id: uuid.UUID | None = Field(default=None, index=True)
    check_item_id: str = Field(max_length=128)
    kind: str = Field(max_length=16)
    text: str | None = Field(default=None)
    table_html: str | None = Field(default=None)
    crop_id: uuid.UUID | None = Field(default=None)
    recognition_source: str | None = Field(default=None, max_length=16)
    relation_status: str | None = Field(default=None, max_length=16)
    not_found_reason: str | None = Field(default=None)
    rank: int = Field(default=0)
    fingerprint: str | None = Field(default=None, max_length=64)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_results_task_id_id"),
        Index("ix_results_run_item_rank", "run_id", "check_item_id", "rank", "id"),
        ForeignKeyConstraint(
            ["task_id", "run_id"],
            ["processing_runs.task_id", "processing_runs.id"],
            name="fk_results_run",
        ),
        ForeignKeyConstraint(
            ["task_id", "crop_id"],
            ["crops.task_id", "crops.id"],
            name="fk_results_crop",
        ),
    )


class ResultSource(SQLModel, table=True):
    __tablename__ = "result_sources"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    result_id: uuid.UUID = Field(index=True)
    file_id: uuid.UUID | None = Field(default=None)
    page_id: uuid.UUID | None = Field(default=None)
    block_id: uuid.UUID | None = Field(default=None)
    start_char: int | None = Field(default=None)
    end_char: int | None = Field(default=None)
    source_page_number: int | None = Field(default=None)
    bbox: Any | None = Field(default=None, sa_column=Column(JSONB))
    polygon: Any | None = Field(default=None, sa_column=Column(JSONB))
    location_precision: str = Field(default=LocationPrecision.none.value, max_length=16)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_result_sources_task_id_id"),
        ForeignKeyConstraint(
            ["task_id", "result_id"],
            ["results.task_id", "results.id"],
            name="fk_result_sources_result",
        ),
        ForeignKeyConstraint(
            ["task_id", "block_id"],
            ["ocr_blocks.task_id", "ocr_blocks.id"],
            name="fk_result_sources_block",
        ),
    )


# ---------------------------------------------------------------------------
# 决策（P4）：人工确认状态机
# ---------------------------------------------------------------------------


class Decision(SQLModel, table=True):
    __tablename__ = "decisions"

    result_id: uuid.UUID = Field(primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    decision: str = Field(default=DecisionValue.unselected.value, max_length=16)
    reject_reason: str | None = Field(default=None)
    version: int = Field(default=0)
    actor_user_id: uuid.UUID | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    carried_from_result_id: uuid.UUID | None = Field(default=None)

    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "result_id"],
            ["results.task_id", "results.id"],
            name="fk_decisions_result",
        ),
    )


class DecisionEvent(SQLModel, table=True):
    __tablename__ = "decision_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    result_id: uuid.UUID = Field(index=True)
    actor_user_id: uuid.UUID | None = Field(default=None)
    event_type: str = Field(max_length=32)
    before: dict | None = Field(default=None, sa_column=Column(JSONB))
    after: dict | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=get_datetime_utc)

    __table_args__ = (
        UniqueConstraint("task_id", "id", name="uq_decision_events_task_id_id"),
    )


# ---------------------------------------------------------------------------
# API DTO
# ---------------------------------------------------------------------------


class UserPublic(SQLModel):
    id: uuid.UUID
    username: str
    is_active: bool
    created_at: datetime


class LoginResponse(SQLModel):
    user: UserPublic
    csrf_token: str


class Message(SQLModel):
    message: str


class TaskPublic(SQLModel):
    id: uuid.UUID
    name: str
    product_code: str
    customer_role: str
    checklist_version: str | None
    state: str
    input_revision: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    # 进度信息（由文件 OCR 状态动态计算，非持久化字段）
    file_count: int = 0
    ocr_done_count: int = 0
    ocr_processing_count: int = 0
    ocr_failed_count: int = 0


class TaskFilePublic(SQLModel):
    id: uuid.UUID
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    original_asset_id: uuid.UUID | None
    material_type: str | None
    page_count: int | None
    ocr_status: str | None = None
    created_at: datetime


class Capabilities(SQLModel):
    roles: list[dict]
    product_code: str
    checklist_version: str | None
    ocr_configured: bool
    llm_configured: bool
