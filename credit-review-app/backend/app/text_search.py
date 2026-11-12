"""文本/表格证据摘录（P3-7）：按清单项在 OCR 块里分窗查找，生成结果与出处。

- 每个检查项在对应材料类型的全部文件 OCR 块里分窗查找
- 模型只返回 source_refs（block_id + 可选 start_char/end_char），代码按引用截取原文
- 每个 evidence 生成一条 Result + 对应 ResultSource；表格项取完整 table_html
- 仅当覆盖完整（所有窗口都成功执行）且都未找到时才产生 not_found
"""

from __future__ import annotations

import hashlib
import uuid
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
    OcrPage,
    RelationStatus,
    ResultKind,
)

SEARCH_SYSTEM = (
    "你是银行信贷资料核对的证据摘录助手。你只根据给定文本块判断某个检查项能否在原文中"
    "找到对应证据。你绝不生成新的原文段落，只返回 source_refs 引用（block_id，以及可选的 "
    "start_char/end_char 表示引用范围）。找不到就 outcome=not_found。"
    "block_id 必须原样复制给定文本块里的 block_id 字符串（形如 8-4-4-4-12 的 UUID），"
    "严禁编造不存在的 block_id。"
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


@dataclass
class Window:
    bundle_id: str
    blocks: list[SourceBlock] = field(default_factory=list)


def load_source_blocks(
    task_id: uuid.UUID, file_ids: list[uuid.UUID]
) -> list[SourceBlock]:
    """加载指定文件的全部 OCR 文本块，关联页信息。"""
    if not file_ids:
        return []
    with Session(engine) as session:
        page_by_id: dict[uuid.UUID, OcrPage] = {}
        pages = session.exec(
            select(OcrPage).where(OcrPage.task_id == task_id)
        ).all()
        for p in pages:
            page_by_id[p.id] = p

        blocks: list[SourceBlock] = []
        for file_id in file_ids:
            rows = session.exec(
                select(OcrBlock)
                .where(OcrBlock.task_id == task_id, OcrBlock.file_id == file_id)
                .order_by(OcrBlock.sequence_index)
            ).all()
            for row in rows:
                text = (row.canonical_text or "").strip()
                if not text and not row.table_html:
                    continue
                page = page_by_id.get(row.page_id) if row.page_id else None
                blocks.append(
                    SourceBlock(
                        block_id=row.id,
                        file_id=file_id,
                        page_id=row.page_id,
                        text=text,
                        table_html=row.table_html,
                        bbox=row.bbox,
                        polygon=row.polygon,
                        source_page_number=page.source_page_number if page else None,
                        ocr_page_index=page.ocr_page_index if page else 0,
                        page_width_px=page.width_px if page else None,
                        page_height_px=page.height_px if page else None,
                        coordinate_space=page.coordinate_space if page else "unknown",
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
            parts.append(f'block_id={b.block_id} 文本="{text}"')
    return "\n".join(parts)


def chunk_source_blocks(
    blocks: list[SourceBlock], max_chars: int, overlap_chars: int
) -> list[Window]:
    windows: list[Window] = []
    current: list[SourceBlock] = []
    current_chars = 0
    for block in blocks:
        block_chars = len(block.text)
        if current and current_chars + block_chars > max_chars:
            windows.append(Window(bundle_id=f"window-{len(windows)}", blocks=list(current)))
            current, current_chars = _recede(current, overlap_chars)
        current.append(block)
        current_chars += block_chars
    if current:
        windows.append(Window(bundle_id=f"window-{len(windows)}", blocks=list(current)))
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


def _fingerprint(check_item_id: str, block_id: uuid.UUID, start: int | None, end: int | None) -> str:
    payload = f"{check_item_id}|{block_id}|{start}|{end}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:64]


def _dedup_evidence(evidence: list["FoundEvidence"]) -> list["FoundEvidence"]:
    """同一检查项内做包含关系去重：若 A.text 包含 B.text，去掉短的 B（保留完整条款）。

    先按文本长度降序，保证完整条款优先保留；去重后按来源页序恢复展示顺序。
    """
    if len(evidence) <= 1:
        return evidence
    deduped: list[FoundEvidence] = []
    for ev in sorted(evidence, key=lambda e: len(e.text or ""), reverse=True):
        if ev.text and any(
            ev.text in o.text and ev.text != o.text for o in deduped
        ):
            continue
        deduped.append(ev)
    deduped.sort(key=lambda e: (e.source.source_page_number or 0, e.source.block_id))
    return deduped


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
    fingerprint: str


def search_check_item(
    task_id: uuid.UUID,
    check_item: dict[str, Any],
    file_ids: list[uuid.UUID],
    client: LLMClient,
    max_chars: int,
    overlap_chars: int,
) -> tuple[list[FoundEvidence], str | None]:
    """查找单个检查项。返回 (evidence 列表, 失败原因或 None)。

    失败原因非 None 表示存在技术失败（不能安全判 not_found）。
    """
    result_mode = check_item.get("result_mode", "verbatim_quotes")
    check_id = check_item["id"]
    label = check_item.get("label", check_id)

    blocks = load_source_blocks(task_id, file_ids)
    if not blocks:
        # 有材料槽位但无 OCR 文本 → 视为无证据（不是技术失败）
        return [], None

    windows = chunk_source_blocks(blocks, max_chars, overlap_chars)
    found: list[FoundEvidence] = []
    seen: set[str] = set()
    uncovered = 0  # 未覆盖（格式错误/超时）的窗口数

    for window in windows:
        user = (
            f"检查项：{label}（id={check_id}，结果模式={result_mode}）\n"
            "请判断该检查项能否在下面的文本块里找到对应证据，找到就返回引用。\n"
            + _window_text(window.blocks)
        )
        data: dict[str, Any] | None = None
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
            except LLMFatalError:
                # 鉴权/参数错误：继续其他窗口也无意义，整项失败
                return found, "LLM_FATAL"
            except LLMTransientError:
                if attempt >= settings.LLM_MAX_TRANSIENT_RETRIES:
                    uncovered += 1
                continue
            except LLMFormatError:
                # 模型输出格式无法通过校验：该窗口视为未覆盖，继续其他窗口
                uncovered += 1
                break
        if data is None:
            continue
        output = TextSearchOutput.model_validate(data)

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
                    fp = _fingerprint(check_id, block.block_id, ref.start_char, ref.end_char)
                    if fp in seen:
                        continue
                    seen.add(fp)
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
                            fingerprint=fp,
                        )
                    )
    found = _dedup_evidence(found)
    if found:
        return found, None
    if uncovered > 0:
        # 部分窗口未覆盖：不能安全判 not_found，返回部分覆盖标记
        return [], "PARTIAL_COVERAGE"
    return [], None
