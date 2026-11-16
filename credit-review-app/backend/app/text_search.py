"""文本/表格证据摘录（P3-7）：按清单项在 OCR 块里分窗查找，生成结果与出处。

- 每个检查项在对应材料类型的全部文件 OCR 块里分窗查找
- 模型只返回 source_refs（block_id + 可选 start_char/end_char），代码按引用截取原文
- 每个 evidence 生成一条 Result + 对应 ResultSource；表格项取完整 table_html
- K1：``load_source_blocks`` 与 ``classification.load_file_blocks`` 共用
  ``source_ordering.order_blocks`` 的稳定排序键 ``(file_order, page_key, page_ordinal)``
- K2：``Result.fingerprint`` 语义本轮改为「内容 hash」（不含 UUID / 不含字符偏移）；
  实际发给模型的请求 hash 只进 JSONL trace 与证据
- K3：去重键 ``(check_item_id, content_hash)``，稳定出处顺序
  ``(source_page_number, page_ordinal, content_hash)``，移除随机 block_id
- 覆盖：有摘录但存在未覆盖窗口时仍报告 ``PARTIAL_COVERAGE``，保留已成功摘录
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.llm_client import LLMClient, LLMFatalError, LLMFormatError, LLMTransientError
from app.llm_schemas import TEXT_SEARCH_SCHEMA, TextSearchOutput
from app.models import (
    LocationPrecision,
    OcrBlock,
    RelationStatus,
    ResultKind,
)
from app.source_ordering import (
    content_hash as _stable_content_hash,
    load_file_keys,
    load_page_map,
    order_blocks,
)

SEARCH_SYSTEM = (
    "你是银行信贷资料核对的证据摘录助手。你只根据给定文本块判断某个检查项能否在原文中"
    "找到对应证据。你绝不生成新的原文段落，只返回 source_refs 引用（block_id，以及可选的 "
    "start_char/end_char 表示引用范围）。找不到就 outcome=not_found。"
    "block_id 必须原样复制给定文本块里的 block_id 字符串（形如 8-4-4-4-12 的 UUID），"
    "严禁编造不存在的 block_id。"
    # 本批不改运行时提示词文本；强监管约束与版本模板见 app.prompt_registry（K6，后续批次切换）
)


@dataclass
class SourceBlock:
    block_id: uuid.UUID
    file_id: uuid.UUID
    page_id: uuid.UUID | None
    text: str
    table_html: str | None
    bbox: Any | None
    polygon: Any | None
    source_page_number: int | None
    ocr_page_index: int
    page_width_px: int | None
    page_height_px: int | None
    coordinate_space: str
    # --- K1 / K2 新增字段（全部带默认值，兼容既有构造与单测） ---
    file_key: str = ""
    page_key: int = 0
    page_ordinal: int = 0
    content_hash: str = ""
    order_source: str = ""


@dataclass
class Window:
    bundle_id: str
    blocks: list[SourceBlock] = field(default_factory=list)
    # 请求侧 hash（_window_text 含 block_id=<UUID>），只进 trace / 证据，不写 RunStep.input_hash
    window_text_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.window_text_sha256:
            self.window_text_sha256 = hashlib.sha256(
                _window_text(self.blocks).encode("utf-8")
            ).hexdigest()


def load_source_blocks(
    task_id: uuid.UUID, file_ids: list[uuid.UUID]
) -> list[SourceBlock]:
    """加载指定文件的全部 OCR 文本块，按 K1 稳定键排序并计算内容 hash。"""
    if not file_ids:
        return []
    with Session(engine) as session:
        page_by_id = load_page_map(session, task_id, file_ids)
        file_key_by_id = load_file_keys(session, file_ids)
        rows: list[OcrBlock] = []
        for file_id in file_ids:
            rows.extend(
                session.exec(
                    select(OcrBlock).where(
                        OcrBlock.task_id == task_id, OcrBlock.file_id == file_id
                    )
                ).all()
            )
        ordered = order_blocks(rows, page_by_id, file_key_by_id)
        blocks: list[SourceBlock] = []
        for item in ordered:
            row = item.row
            page = page_by_id.get(row.page_id) if row.page_id else None
            blocks.append(
                SourceBlock(
                    block_id=row.id,
                    file_id=row.file_id or file_ids[0],
                    page_id=row.page_id,
                    text=item.canonical_text,
                    table_html=row.table_html,
                    bbox=row.bbox,
                    polygon=row.polygon,
                    source_page_number=item.source_page_number,
                    ocr_page_index=item.ocr_page_index,
                    page_width_px=page.width_px if page else None,
                    page_height_px=page.height_px if page else None,
                    coordinate_space=page.coordinate_space if page else "unknown",
                    file_key=item.file_key,
                    page_key=item.page_key,
                    page_ordinal=item.page_ordinal,
                    content_hash=item.content_hash,
                    order_source=item.order_source,
                )
            )
        return blocks


def _window_text(blocks: list[SourceBlock]) -> str:
    parts: list[str] = []
    for b in blocks:
        text = b.text.strip()
        if not text and b.table_html:
            text = f"[表格]{b.table_html[:2000]}"
        if text:
            # 请求侧保留 block_id=<UUID> 标注（K2：请求 hash 与内容 hash 严格分栏）
            parts.append(f'block_id={b.block_id} 文本="{text}"')
    return "\n".join(parts)


def chunk_source_blocks(
    blocks: list[SourceBlock], max_chars: int, overlap_chars: int
) -> list[Window]:
    """按字符预算分窗；bundle_id 稳定为 ``w{idx}``，并计算 window_text_sha256。"""
    windows: list[Window] = []
    current: list[SourceBlock] = []
    current_chars = 0
    for block in blocks:
        block_chars = len(block.text)
        if current and current_chars + block_chars > max_chars:
            windows.append(Window(bundle_id=f"w{len(windows)}", blocks=list(current)))
            current, current_chars = _recede(current, overlap_chars)
        current.append(block)
        current_chars += block_chars
    if current:
        windows.append(Window(bundle_id=f"w{len(windows)}", blocks=list(current)))
    return windows


def _recede(blocks: list[SourceBlock], overlap_chars: int) -> tuple[list[SourceBlock], int]:
    keep: list[SourceBlock] = []
    chars = 0
    for block in reversed(blocks):
        keep.insert(0, block)
        chars += len(block.text)
        if chars >= overlap_chars:
            break
    return keep, chars


def _location_precision(block: SourceBlock) -> str:
    if block.bbox or block.polygon:
        return LocationPrecision.region.value
    if block.page_id:
        return LocationPrecision.page.value
    return LocationPrecision.none.value


def _slice_text(text: str, start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return text
    s = start or 0
    e = end if end is not None else len(text)
    return text[s:e]


# 营业执照字段型材料的字段标签。OCR 常把相邻字段合并成一个块，
# 摘录时需按字段边界截断，避免把「住所」等无关字段混进目标字段。
_LICENSE_FIELD_LABELS = [
    "名称",
    "类型",
    "住所",
    "法定代表人",
    "注册资本",
    "成立日期",
    "营业期限",
    "登记机关",
]

_LICENSE_CHECK_FIELD = {
    "license.business_scope": "经营范围",
    "license.operating_term": "营业期限",
    "license.registration_status": "登记状态",
}


def _truncate_license_field(text: str, check_id: str) -> str:
    """对营业执照字段型检查项，截断目标字段之后混入的其他字段标签。"""
    field = _LICENSE_CHECK_FIELD.get(check_id)
    if not field or not text:
        return text
    idx = text.find(field)
    if idx < 0:
        return text
    rest = text[idx + len(field):]
    cut = len(rest)
    for other in _LICENSE_FIELD_LABELS:
        b = rest.find(other)
        if 0 <= b < cut:
            cut = b
    return text[: idx + len(field) + cut].strip()


def _content_hash(
    file_key: str, page_key: int, page_ordinal: int, canonical_text: str
) -> str:
    """K2 内容 hash：不含 UUID、不含 start/end 偏移，跨导入可复算。

    与 ``_fingerprint`` 的旧语义（含随机 OcrBlock UUID + 偏移）严格分栏；
    复用 ``Result.fingerprint`` 字段，交接说明中须写明语义变更。
    """
    return _stable_content_hash(file_key, page_key, page_ordinal, canonical_text)


def _dedup_evidence(
    evidence: list["FoundEvidence"], check_item_id: str = ""
) -> list["FoundEvidence"]:
    """K3 去重：键 ``(check_item_id, content_hash)``；稳定出处顺序。

    * 同检查项 + 同出处 + 同原文，跨偏移 / 相邻窗口重复引用只保留一条；
    * 不同出处（page_ordinal 不同）相同正文 → content_hash 不同 → 全部保留；
    * 同出处合法支持多检查项 → 去重键含 check_item_id，各项互不干扰；
    * 排序键不含随机 block_id，``Result.rank`` 与响应到达顺序无关。
    """
    seen: set[tuple[str, str]] = set()
    unique: list[FoundEvidence] = []
    for ev in evidence:
        key = (check_item_id, ev.content_hash)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ev)
    unique.sort(
        key=lambda e: (
            e.source.source_page_number or 0,
            e.source.page_ordinal,
            e.content_hash,
        )
    )
    return unique


@dataclass
class FoundEvidence:
    """代码侧组装好的一条证据（含截取后的原文与出处）。"""

    text: str | None
    table_html: str | None
    kind: str
    relation_status: str
    source: SourceBlock
    start_char: int | None
    end_char: int | None
    # 语义本轮改为 K2 内容 hash（不含 UUID / 偏移），字段名沿用 Result.fingerprint 以兼容写入
    fingerprint: str

    @property
    def content_hash(self) -> str:
        """K2 内容 hash（与 ``fingerprint`` 同值，供去重/排序显式使用）。"""
        return self.fingerprint


@dataclass
class SearchOutcome:
    """单个检查项的查找结果与覆盖事实。

    ``failed_reason`` 取值：``None`` / ``PARTIAL_COVERAGE`` / ``LLM_FATAL``。
    **有摘录但存在未覆盖窗口时仍报告 PARTIAL_COVERAGE**（旧实现在此丢计数）。
    """

    evidence: list[FoundEvidence] = field(default_factory=list)
    covered_windows: int = 0
    total_windows: int = 0
    uncovered_window_ids: list[str] = field(default_factory=list)
    failed_reason: str | None = None
    anomalies: list[str] = field(default_factory=list)

    @property
    def fully_covered(self) -> bool:
        return bool(
            self.total_windows
            and self.covered_windows == self.total_windows
            and not self.uncovered_window_ids
            and self.failed_reason is None
        )


def search_check_item_outcome(
    task_id: uuid.UUID,
    check_item: dict[str, Any],
    file_ids: list[uuid.UUID],
    client: LLMClient,
    max_chars: int,
    overlap_chars: int,
) -> SearchOutcome:
    """查找单个检查项，返回结构化覆盖结果（新主实现）。"""
    result_mode = check_item.get("result_mode", "verbatim_quotes")
    check_id = check_item["id"]
    label = check_item.get("label", check_id)

    blocks = load_source_blocks(task_id, file_ids)
    if not blocks:
        # 有材料槽位但无 OCR 文本 → 视为无证据（不是技术失败；由调用方判 no_matching_evidence）
        return SearchOutcome(total_windows=0)

    windows = chunk_source_blocks(blocks, max_chars, overlap_chars)
    outcome = SearchOutcome(total_windows=len(windows))
    found: list[FoundEvidence] = []
    seen: set[tuple[str, str]] = set()

    for window_index, window in enumerate(windows):
        user = (
            f"检查项：{label}（id={check_id}，结果模式={result_mode}）\n"
            "请判断该检查项能否在下面的文本块里找到对应证据，找到就返回引用。\n"
            + _window_text(window.blocks)
        )
        data: dict[str, Any] | None = None
        window_failure: str | None = None
        # 窗口级容错：格式错误降级为未覆盖；瞬时错误重试；致命错误整项失败
        for attempt in range(settings.LLM_MAX_TRANSIENT_RETRIES + 1):
            try:
                data = client.complete_json(
                    system=SEARCH_SYSTEM,
                    user=user,
                    schema_name="text_search_output",
                    json_schema=TEXT_SEARCH_SCHEMA,
                    validator=TextSearchOutput.model_validate,
                )
                break
            except LLMFatalError as exc:
                window_failure = "LLM_FATAL"
                outcome.anomalies.append(
                    f"{window.bundle_id}:LLM_FATAL:{type(exc).__name__}"
                )
                break
            except LLMTransientError as exc:
                if attempt >= settings.LLM_MAX_TRANSIENT_RETRIES:
                    window_failure = "LLM_TRANSIENT_EXHAUSTED"
                    outcome.anomalies.append(
                        f"{window.bundle_id}:LLM_TRANSIENT_EXHAUSTED:{type(exc).__name__}"
                    )
                continue
            except LLMFormatError as exc:
                window_failure = "LLM_FORMAT"
                outcome.anomalies.append(
                    f"{window.bundle_id}:LLM_FORMAT:{type(exc).__name__}"
                )
                break

        if window_failure == "LLM_FATAL":
            outcome.failed_reason = "LLM_FATAL"
            outcome.uncovered_window_ids.append(window.bundle_id)
            outcome.uncovered_window_ids.extend(
                w.bundle_id for w in windows[window_index + 1:]
            )
            break
        if data is None:
            outcome.uncovered_window_ids.append(window.bundle_id)
            continue

        try:
            output = TextSearchOutput.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            outcome.uncovered_window_ids.append(window.bundle_id)
            outcome.anomalies.append(
                f"{window.bundle_id}:INVALID_OUTPUT:{type(exc).__name__}"
            )
            continue
        outcome.covered_windows += 1

        block_by_id = {str(b.block_id): b for b in window.blocks}
        for check in output.check_results:
            if check.check_item_id != check_id:
                continue
            if check.outcome != "found":
                continue
            for evidence in check.evidence:
                for ref in evidence.source_refs:
                    block = block_by_id.get(ref.block_id)
                    if block is None:
                        continue
                    # K3 去重键：使用 K2 内容 hash，不含 UUID / 偏移
                    key = (check_id, block.content_hash)
                    if key in seen:
                        continue
                    seen.add(key)
                    is_table = bool(block.table_html) and result_mode == "full_table"
                    if is_table:
                        kind = ResultKind.table.value
                        text = None
                        table_html = block.table_html
                    else:
                        kind = ResultKind.text.value
                        # 回查原始块取完整原文，避免用模型返回的 start_char/end_char
                        # 截取导致断句（模型字符偏移不可靠，会切断条款）
                        text = _truncate_license_field(block.text, check_id)
                        table_html = None
                    if not text and not table_html:
                        continue
                    found.append(
                        FoundEvidence(
                            text=text,
                            table_html=table_html,
                            kind=kind,
                            relation_status=evidence.relation_status or RelationStatus.matched.value,
                            source=block,
                            start_char=None,
                            end_char=None,
                            fingerprint=block.content_hash,
                        )
                    )

    outcome.evidence = _dedup_evidence(found, check_id)
    if outcome.failed_reason != "LLM_FATAL" and outcome.uncovered_window_ids:
        # 根因修复：即使已有摘录，只要存在未覆盖窗口就必须报告 PARTIAL_COVERAGE
        outcome.failed_reason = "PARTIAL_COVERAGE"
    return outcome


def search_check_item(
    task_id: uuid.UUID,
    check_item: dict[str, Any],
    file_ids: list[uuid.UUID],
    client: LLMClient,
    max_chars: int,
    overlap_chars: int,
) -> tuple[list[FoundEvidence], str | None]:
    """兼容 wrapper：返回 ``(evidence 列表, 失败原因或 None)``。

    供既有单测 / 基线观测器 / 回滚使用；语义已修复为「有摘录 + 未覆盖窗口 →
    PARTIAL_COVERAGE」。新代码应优先使用 ``search_check_item_outcome``。
    """
    outcome = search_check_item_outcome(
        task_id=task_id,
        check_item=check_item,
        file_ids=file_ids,
        client=client,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return outcome.evidence, outcome.failed_reason


# ---------------------------------------------------------------------------
# T03 批量搜索校验：本批每个检查项恰好一项 + 引用块必须属于当前窗口
# ---------------------------------------------------------------------------


@dataclass
class BatchCheckResult:
    """批量响应中单个检查项在本窗口的校验结果。"""

    check_item_id: str
    covered: bool  # 本窗口对该检查项覆盖是否达成（有可采信响应即达成）
    evidence: list[FoundEvidence]
    anomalies: list[str]


@dataclass
class BatchValidation:
    per_check: dict[str, BatchCheckResult]
    error_codes: list[str]


def validate_batch_response(
    data: dict[str, Any],
    check_items: list[dict[str, Any]],
    window: Window,
    *,
    finish_reason: str | None = None,
) -> BatchValidation:
    """校验一个「窗口 × 检查项批次」的模型响应。

    * 本批每个检查项在 ``check_results`` 里**恰好一项**：缺项 → ``BATCH_MISSING_CHECK``
      （X=1 也用它，批大小 1）、重复 → ``BATCH_DUPLICATE_CHECK``、多余非法 ID →
      ``INVALID_CHECK_ID``。空 ``check_results`` 与非法 ID 顶替都判缺项 → 未覆盖。
    * ``check_results=[{outcome:"not_found"}]`` 是明确回答本窗口无候选 → 覆盖达成。
    * 引用的 ``block_id`` 必须属于当前窗口：幻引 → ``INVALID_BLOCK_REF``，该引用
      **零 Result 行落库**，但窗口仍算覆盖达成（S5）。
    * 输出截断（``finish_reason == "length"``）→ ``OUTPUT_TRUNCATED``，保留可验证结果。
    * 一条证据可引用多个相邻块、同一块可被多个检查项引用：每个有效引用各生成一条
      ``FoundEvidence``，回查 OCR 原文取完整正文，主条款/分项/例外分别保留。
    """
    expected_ids = [leaf["id"] for leaf in check_items]
    expected_set = set(expected_ids)
    block_by_id = {str(b.block_id): b for b in window.blocks}
    result_mode = {
        leaf["id"]: leaf.get("result_mode", "verbatim_quotes") for leaf in check_items
    }

    error_codes: list[str] = []

    def add(code: str) -> None:
        if code not in error_codes:
            error_codes.append(code)

    try:
        output = TextSearchOutput.model_validate(data)
    except Exception:  # noqa: BLE001
        add("FORMAT_FAILED")
        return BatchValidation(
            per_check={
                cid: BatchCheckResult(cid, False, [], ["FORMAT_FAILED"])
                for cid in expected_ids
            },
            error_codes=error_codes,
        )

    returned = output.check_results
    ids = [cr.check_item_id for cr in returned]
    counts = Counter(ids)
    if any(cid not in expected_set for cid in ids):
        add("INVALID_CHECK_ID")
    if any(counts.get(cid, 0) > 1 for cid in expected_set):
        add("BATCH_DUPLICATE_CHECK")
    if any(counts.get(cid, 0) == 0 for cid in expected_ids):
        add("BATCH_MISSING_CHECK")
    if finish_reason == "length":
        add("OUTPUT_TRUNCATED")

    per_check: dict[str, BatchCheckResult] = {}
    for cid in expected_ids:
        matching = [cr for cr in returned if cr.check_item_id == cid]
        if len(matching) != 1:
            code = "BATCH_MISSING_CHECK" if not matching else "BATCH_DUPLICATE_CHECK"
            per_check[cid] = BatchCheckResult(cid, False, [], [code])
            continue

        check = matching[0]
        evidence_list: list[FoundEvidence] = []
        anomalies: list[str] = []
        seen_in_window: set[str] = set()
        if check.outcome == "found":
            for ev in check.evidence:
                for ref in ev.source_refs:
                    block = block_by_id.get(ref.block_id)
                    if block is None:
                        anomalies.append("INVALID_BLOCK_REF")
                        continue
                    if block.content_hash in seen_in_window:
                        continue
                    seen_in_window.add(block.content_hash)
                    is_table = bool(block.table_html) and result_mode[cid] == "full_table"
                    if is_table:
                        kind = ResultKind.table.value
                        text = None
                        table_html = block.table_html
                    else:
                        kind = ResultKind.text.value
                        text = _truncate_license_field(block.text, cid)
                        table_html = None
                    if not text and not table_html:
                        continue
                    evidence_list.append(
                        FoundEvidence(
                            text=text,
                            table_html=table_html,
                            kind=kind,
                            relation_status=ev.relation_status or RelationStatus.matched.value,
                            source=block,
                            start_char=None,
                            end_char=None,
                            fingerprint=block.content_hash,
                        )
                    )
        for code in anomalies:
            add(code)
        per_check[cid] = BatchCheckResult(cid, True, evidence_list, anomalies)
    return BatchValidation(per_check=per_check, error_codes=error_codes)
