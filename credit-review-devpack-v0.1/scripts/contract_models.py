# Contract DTOs V0.1 generated with Pydantic 2; not database models.
# Reuse in the application schema layer and keep OpenAPI/contracts synchronized.
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, NAMESPACE_URL, uuid5
from pydantic import BaseModel, ConfigDict, Field, ValidationError

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
MaterialType = Literal['business_license', 'articles_of_association', 'audited_financials']
Role = Literal['borrower', 'guarantor', 'pledgor']
TaskState = Literal['DRAFT', 'PROCESSING', 'REVIEWING', 'FAILED', 'COMPLETED']
RunState = Literal['QUEUED', 'RUNNING', 'READY', 'FAILED', 'SUPERSEDED']
DecisionValue = Literal['unselected', 'accepted', 'rejected']

class ClassificationOutput(Strict):
    bundle_id: str
    material_type: Literal['business_license', 'articles_of_association', 'audited_financials', 'unknown']
    mixed: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=1000)
    source_block_ids: list[UUID]

class SourceRef(Strict):
    block_id: UUID
    start_char: int | None = Field(ge=0)
    end_char: int | None = Field(ge=0)

class TextEvidence(Strict):
    source_refs: list[SourceRef] = Field(min_length=1)
    relation_status: Literal['matched', 'needs_review']
    relevance_reason: str = Field(max_length=1000)

class CheckSearch(Strict):
    check_item_id: str
    outcome: Literal['found', 'not_found']
    evidence: list[TextEvidence]

class TextSearchOutput(Strict):
    bundle_id: str
    check_results: list[CheckSearch]

class ImageMatch(Strict):
    crop_id: UUID
    recognized_text: str | None
    relation_status: Literal['matched', 'needs_review']
    relevance_reason: str = Field(max_length=1000)

class VisionMatchOutput(Strict):
    bundle_id: str
    check_item_id: str
    matches: list[ImageMatch]

class LeafCheck(Strict):
    id: str
    label: str
    group_label: str | None
    result_mode: Literal['verbatim_quotes', 'full_table', 'seal', 'signature']
    dependencies: list[str]
    required: bool

class MaterialChecklist(Strict):
    material_type: MaterialType
    label: str
    checks: list[LeafCheck] = Field(min_length=1)

class Checklist(Strict):
    version: str
    product_code: Literal['working_capital_loan']
    customer_role: Role
    enabled: bool
    annual_policy: Literal['extract_only']
    materials: list[MaterialChecklist] = Field(min_length=1)

class Point(Strict):
    x: float
    y: float

class Box(Strict):
    x0: float
    y0: float
    x1: float
    y1: float

class NormalizedBlock(Strict):
    block_id: UUID
    provider_block_id: int | None
    provider_group_id: int | None
    sequence_index: int = Field(ge=0)
    label: str
    canonical_text: str
    table_html: str | None
    bbox: Box | None
    polygon: list[Point] | None
    crop_ids: list[UUID]

class NormalizedCrop(Strict):
    crop_id: UUID
    block_id: UUID
    provider_label: str
    kind: Literal['seal', 'signature', 'image', 'unknown']
    recognized_text: str | None
    image_key: str | None
    image_asset_id: UUID | None
    image_status: Literal['not_downloaded', 'ready', 'failed']

class NormalizedPage(Strict):
    page_id: UUID
    task_id: UUID
    file_id: UUID
    ocr_job_id: UUID
    provider_line_index: int = Field(ge=0)
    provider_item_index: int = Field(ge=0)
    ocr_page_index: int = Field(ge=0)
    source_page_number: int | None = Field(ge=1)
    mapping_status: Literal['verified', 'unverified']
    raster_asset_id: UUID | None
    width_px: int | None = Field(gt=0)
    height_px: int | None = Field(gt=0)
    coordinate_space: Literal['ocr_input_image_pixels', 'unknown']
    blocks: list[NormalizedBlock]
    crops: list[NormalizedCrop]

class User(Strict):
    id: UUID
    username: str

class AuthResponse(Strict):
    user: User
    csrf_token: str

class LoginRequest(Strict):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class ApiError(Strict):
    code: str
    message: str
    request_id: str
    details: dict

class Statistics(Strict):
    total: int = Field(ge=0)
    unselected: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    missing_reason: int = Field(ge=0)
    accept_rate: float | None = Field(ge=0, le=1)
    reject_rate: float | None = Field(ge=0, le=1)
    can_complete: bool

class MaterialStatistics(Strict):
    material_type: MaterialType
    statistics: Statistics

class StatisticsResponse(Strict):
    overall: Statistics
    materials: list[MaterialStatistics]

class TaskSummary(Strict):
    id: UUID
    name: str
    product_code: str
    customer_role: Role
    checklist_version: str
    state: TaskState
    input_revision: int = Field(ge=0)
    current_run_id: UUID | None
    last_ready_run_id: UUID | None
    stage: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

class TaskDetail(TaskSummary):
    statistics: StatisticsResponse | None
    active_file_count: int = Field(ge=0)
    editable: bool

class TaskPage(Strict):
    items: list[TaskSummary]
    next_cursor: str | None

class TaskCreate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    customer_role: Role
    product_code: Literal['working_capital_loan'] = 'working_capital_loan'

class TaskRename(Strict):
    name: str = Field(min_length=1, max_length=120)

class RoleCapability(Strict):
    code: Role
    label: str
    enabled: bool
    checklist_version: str | None
    disabled_reason: str | None

class Capabilities(Strict):
    roles: list[RoleCapability]
    limits: dict[str, int]
    ocr_configured: bool
    llm_text_configured: bool
    llm_vision_configured: bool

class FileView(Strict):
    id: UUID
    task_id: UUID
    original_name: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    source_page_count: int | None = Field(ge=1)
    effective_material_type: MaterialType | None
    classification_source: Literal['manual', 'model', 'unclassified']
    processing_state: str
    error_code: str | None
    created_at: datetime

class FilePage(Strict):
    items: list[FileView]
    next_cursor: str | None

class FileMutation(Strict):
    file: FileView | None
    new_file_id: UUID | None
    input_revision: int = Field(ge=0)
    run_id: UUID | None

class ClassificationWrite(Strict):
    material_type: MaterialType | None

class RunCreate(Strict):
    retry_failed_only: bool = True

class FileProgress(Strict):
    file_id: UUID
    stage: str
    extracted_pages: int | None = Field(ge=0)
    total_pages: int | None = Field(ge=1)
    error_code: str | None

class RunView(Strict):
    id: UUID
    task_id: UUID
    input_revision: int
    state: RunState
    stage: str
    coverage_complete: bool
    files: list[FileProgress]
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None

class SourceView(Strict):
    file_id: UUID
    file_name: str
    page_id: UUID
    block_id: UUID
    source_page_number: int | None = Field(ge=1)
    ocr_page_index: int = Field(ge=0)
    location_precision: Literal['region', 'page', 'none']
    bbox: Box | None
    polygon: list[Point] | None
    coordinate_space: Literal['ocr_input_image_pixels', 'unknown']
    page_width_px: int | None = Field(gt=0)
    page_height_px: int | None = Field(gt=0)
    raster_asset_id: UUID | None
    start_char: int | None = Field(ge=0)
    end_char: int | None = Field(ge=0)

class Decision(Strict):
    result_id: UUID
    decision: DecisionValue
    reject_reason: str | None = Field(max_length=4000)
    version: int = Field(ge=0)
    updated_at: datetime | None
    carried_from_result_id: UUID | None

class ResultView(Strict):
    id: UUID
    task_id: UUID
    run_id: UUID
    check_item_id: str
    check_label: str
    group_label: str | None
    material_type: MaterialType
    rank: int = Field(ge=0)
    kind: Literal['text', 'table', 'seal', 'signature', 'not_found']
    text: str | None
    table_html: str | None
    crop_id: UUID | None
    image_asset_id: UUID | None
    image_url: str | None
    recognition_source: Literal['ocr', 'vision'] | None
    relation_status: Literal['matched', 'needs_review'] | None
    not_found_reason: Literal['material_missing', 'no_matching_evidence', 'unclassifiable_image'] | None
    sources: list[SourceView]
    decision: Decision
    editable: bool

class ResultPage(Strict):
    run_id: UUID
    is_stale: bool
    editable: bool
    items: list[ResultView]
    next_cursor: str | None

class DecisionWrite(Strict):
    run_id: UUID
    decision: DecisionValue
    reject_reason: str | None = Field(max_length=4000)

class DecisionResponse(Strict):
    decision: Decision
    statistics: StatisticsResponse

class CompleteRequest(Strict):
    run_id: UUID
    input_revision: int = Field(ge=0)

class ScrollAnchor(Strict):
    offset_ratio: float = Field(ge=0, le=1)
    result_id: UUID | None

class ViewState(Strict):
    material_type: MaterialType
    file_id: UUID | None
    page_number: int = Field(ge=1)
    zoom: float = Field(ge=0.25, le=4)
    left_anchor: ScrollAnchor
    right_anchor: ScrollAnchor

class ViewStateList(Strict):
    items: list[ViewState]
