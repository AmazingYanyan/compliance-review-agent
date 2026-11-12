export interface UserPublic {
  id: string
  username: string
  is_active: boolean
  created_at: string
}

export interface MeResponse {
  user: UserPublic
  csrf_token: string
}

export interface Role {
  code: string
  label: string
  enabled: boolean
  checklist_version: string | null
  disabled_reason: string | null
}

export interface Capabilities {
  roles: Role[]
  product_code: string
  checklist_version: string | null
  ocr_configured: boolean
  llm_configured: boolean
}

export interface Task {
  id: string
  name: string
  product_code: string
  customer_role: string
  checklist_version: string | null
  state: string
  input_revision: number
  created_at: string
  updated_at: string
  completed_at: string | null
  file_count: number
  ocr_done_count: number
  ocr_processing_count: number
  ocr_failed_count: number
}

export interface TaskFile {
  id: string
  original_name: string
  media_type: string
  size_bytes: number
  sha256: string
  original_asset_id: string | null
  material_type: string | null
  page_count: number | null
  ocr_status: string | null
  created_at: string
}

export const OCR_STATUS_LABEL: Record<string, string> = {
  processing: "识别中",
  done: "已识别",
  failed: "识别失败",
}

export const CUSTOMER_ROLE_LABEL: Record<string, string> = {
  borrower: "借款人",
  guarantor: "保证人",
  pledgor: "抵（质）押人",
}

export const TASK_STATE_LABEL: Record<string, string> = {
  DRAFT: "未开始",
  PROCESSING: "识别中",
  REVIEWING: "待核对",
  FAILED: "识别失败",
  COMPLETED: "已完成",
}

export const MATERIAL_LABEL: Record<string, string> = {
  business_license: "营业执照",
  articles_of_association: "公司章程",
  audited_financials: "最近一年已审计财报",
}

export interface ResultSource {
  file_id: string | null
  file_name: string | null
  page_id: string | null
  block_id: string | null
  source_page_number: number | null
  ocr_page_index: number | null
  location_precision: string | null
  bbox: number[] | null
  polygon: number[] | null
  coordinate_space: string | null
  page_width_px: number | null
  page_height_px: number | null
  raster_asset_id: string | null
  start_char: number | null
  end_char: number | null
}

export interface Decision {
  result_id: string
  decision: string
  reject_reason: string | null
  version: number
  updated_at: string | null
  carried_from_result_id: string | null
}

export interface Statistics {
  total: number
  unselected: number
  accepted: number
  rejected: number
  missing_reason: number
  accept_rate: number | null
  reject_rate: number | null
  can_complete: boolean
}

export interface Result {
  id: string
  task_id: string
  run_id: string
  check_item_id: string
  check_label: string
  group_label: string | null
  material_type: string | null
  kind: string
  text: string | null
  table_html: string | null
  crop_id: string | null
  recognition_source: string | null
  relation_status: string | null
  not_found_reason: string | null
  rank: number
  sources: ResultSource[]
  decision: Decision
  editable: boolean
}

export interface ResultList {
  run_id: string | null
  is_stale: boolean
  editable: boolean
  statistics: { overall: Statistics; materials: { material_type: string; statistics: Statistics }[] } | null
  items: Result[]
  next_cursor: string | null
}

export interface RunView {
  id: string
  task_id: string
  input_revision: number
  state: string
  stage: string | null
  coverage_complete: boolean
  files: { file_id: string; effective_material_type: string | null }[]
  error_code: string | null
  created_at: string
  finished_at: string | null
}

export const NOT_FOUND_REASON_LABEL: Record<string, string> = {
  no_matching_evidence: "未找到相关证据",
  material_missing: "未上传该材料",
  coverage_incomplete: "识别覆盖不完整，请人工复核",
}
