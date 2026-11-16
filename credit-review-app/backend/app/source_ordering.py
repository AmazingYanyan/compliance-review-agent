"""K1 稳定排序键（text_search 与 classification 共用同一实现）。

排序键 ``(file_order, page_key, page_ordinal)``：

* ``file_order``：按 ``str(file_id)`` 字典序得到的 0-based 序号；
  ``file_key`` 优先取 ``TaskFile.sha256``（随文件内容稳定、不含 UUID），
  缺失时回退 ``file-order-{file_order}``。
* ``page_key`` = ``source_page_number if not None else ocr_page_index``。
* ``page_ordinal``：页内按阅读顺序排序后的 0-based 序号，**不含任何 UUID**。

页内阅读顺序：bbox 的 ``(top, left)`` → 回退 ``sequence_index`` →
回退 ``provider_block_id`` / ``global_block_id`` 自然序 → 回退
``sha256(canonical_text)``。使用处通过 ``order_source`` 能追溯用了哪一级，
``ORDER_FALLBACK_NOTE`` 标注旧数据回退的局限。

K2 内容 hash：``sha256(f"{file_key}|{page_key}|{page_ordinal}|{canonical_text}")[:64]``，
不含 UUID、不含 start/end 偏移，跨导入可复算。
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.models import OcrBlock, OcrPage, TaskFile

ORDER_SOURCE_BBOX = "bbox"
ORDER_SOURCE_SEQUENCE_INDEX = "sequence_index"
ORDER_SOURCE_PROVIDER_BLOCK_ID = "provider_block_id"
ORDER_SOURCE_GLOBAL_BLOCK_ID = "global_block_id"
ORDER_SOURCE_CANONICAL_TEXT_SHA256 = "canonical_text_sha256"
ORDER_FALLBACK_NOTE = "旧数据回退、阅读顺序不保证"


@dataclass(frozen=True)
class OrderedBlock:
    """稳定排序后的一块 OCR 文本（row 为原始 OcrBlock，供使用处读取其余字段）。"""

    row: Any
    file_order: int
    file_key: str
    page_key: int
    page_ordinal: int
    order_source: str
    canonical_text: str
    content_hash: str
    source_page_number: int | None
    ocr_page_index: int


def content_hash(file_key: str, page_key: int, page_ordinal: int, canonical_text: str) -> str:
    """K2 内容 hash：不含 UUID、不含字符偏移，跨导入可复算。"""
    payload = f"{file_key}|{page_key}|{page_ordinal}|{canonical_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:64]


def _bbox_top_left(bbox: Any) -> tuple[float, float] | None:
    """从 bbox 提取 (top, left)，兼容 [x1,y1,x2,y2] 与常见 dict 形式。"""
    if bbox is None:
        return None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            left = float(bbox[0])
            top = float(bbox[1])
        except (TypeError, ValueError):
            return None
        if math.isnan(left) or math.isnan(top):
            return None
        return (top, left)
    if isinstance(bbox, dict):
        for top_key, left_key in (("top", "left"), ("y", "x"), ("y1", "x1")):
            if top_key in bbox and left_key in bbox:
                try:
                    top = float(bbox[top_key])
                    left = float(bbox[left_key])
                except (TypeError, ValueError):
                    return None
                if math.isnan(left) or math.isnan(top):
                    return None
                return (top, left)
        nested = bbox.get("bbox") or bbox.get("box")
        if isinstance(nested, (list, tuple)):
            return _bbox_top_left(nested)
    return None


def load_page_map(
    session: Session, task_id: uuid.UUID, file_ids: list[uuid.UUID]
) -> dict[uuid.UUID, OcrPage]:
    """加载页信息映射；text_search 与 classification 走同一函数。"""
    stmt = select(OcrPage).where(OcrPage.task_id == task_id)
    if file_ids:
        stmt = stmt.where(OcrPage.file_id.in_(file_ids))  # type: ignore[attr-defined]
    return {page.id: page for page in session.exec(stmt).all()}


def load_file_keys(session: Session, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """file_id → file_key（TaskFile.sha256）；缺失或空值由 order_blocks 回退。"""
    if not file_ids:
        return {}
    rows = session.exec(
        select(TaskFile).where(TaskFile.id.in_(file_ids))  # type: ignore[attr-defined]
    ).all()
    return {row.id: (row.sha256 or "").strip() for row in rows}


@dataclass(frozen=True)
class _Prepared:
    row: Any
    file_id: uuid.UUID
    file_id_str: str
    file_key: str
    page_key: int
    source_page_number: int | None
    ocr_page_index: int
    canonical_text: str
    bbox_key: tuple[float, float] | None
    sequence_index: int
    provider_block_id: str
    global_block_id: str
    text_sha256: str


def _choose_order_source(group: list[_Prepared]) -> str:
    """判定该页的决定级排序来源，供使用处追溯回退级别。"""
    bbox_values = [item.bbox_key for item in group]
    if all(value is not None for value in bbox_values) and len(set(bbox_values)) > 1:
        return ORDER_SOURCE_BBOX
    if len({item.sequence_index for item in group}) > 1:
        return ORDER_SOURCE_SEQUENCE_INDEX
    provider_values = [item.provider_block_id for item in group]
    if all(provider_values) and len(set(provider_values)) > 1:
        return ORDER_SOURCE_PROVIDER_BLOCK_ID
    global_values = [item.global_block_id for item in group]
    if all(global_values) and len(set(global_values)) > 1:
        return ORDER_SOURCE_GLOBAL_BLOCK_ID
    return ORDER_SOURCE_CANONICAL_TEXT_SHA256


def _sort_key(item: _Prepared) -> tuple[Any, ...]:
    """统一复合键：bbox → sequence_index → provider/global 自然序 → 原文 hash。

    bbox 缺失时用 ``(inf, inf)`` 占位，保证同一页内键类型一致、排序确定；
    这种情况会由 ``_choose_order_source`` 记录为回退。
    """
    bbox_key = item.bbox_key if item.bbox_key is not None else (float("inf"), float("inf"))
    return (
        bbox_key,
        item.sequence_index,
        item.provider_block_id,
        item.global_block_id,
        item.text_sha256,
    )


def order_blocks(
    rows: list[Any],
    page_by_id: dict[uuid.UUID, OcrPage],
    file_key_by_id: dict[uuid.UUID, str],
) -> list[OrderedBlock]:
    """按 K1 稳定排序键返回有序块清单（不含任何 UUID 的排序字段）。"""
    prepared: list[_Prepared] = []
    for row in rows:
        text = (row.canonical_text or "").strip()
        if not text and not row.table_html:
            continue  # 纯图块不参与文字分窗（与既有过滤规则一致）
        page = page_by_id.get(row.page_id) if row.page_id else None
        source_page_number = page.source_page_number if page else None
        ocr_page_index = int(page.ocr_page_index) if page else 0
        page_key = int(
            source_page_number if source_page_number is not None else ocr_page_index
        )
        file_id = row.file_id or uuid.UUID(int=0)
        prepared.append(
            _Prepared(
                row=row,
                file_id=file_id,
                file_id_str=str(file_id),
                file_key=file_key_by_id.get(file_id, ""),
                page_key=page_key,
                source_page_number=source_page_number,
                ocr_page_index=ocr_page_index,
                canonical_text=text,
                bbox_key=_bbox_top_left(row.bbox),
                sequence_index=int(row.sequence_index or 0),
                provider_block_id=str(row.provider_block_id or ""),
                global_block_id=str(row.global_block_id or ""),
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    if not prepared:
        return []

    file_ids_sorted = sorted({item.file_id_str for item in prepared})
    file_order_by_str = {file_id_str: idx for idx, file_id_str in enumerate(file_ids_sorted)}

    groups: dict[tuple[int, int], list[_Prepared]] = {}
    for item in prepared:
        file_order = file_order_by_str[item.file_id_str]
        groups.setdefault((file_order, item.page_key), []).append(item)

    ordered: list[OrderedBlock] = []
    for file_order, page_key in sorted(groups):
        group = groups[(file_order, page_key)]
        order_source = _choose_order_source(group)
        sorted_group = sorted(group, key=_sort_key)
        for page_ordinal, item in enumerate(sorted_group):
            file_key = item.file_key or f"file-order-{file_order}"
            digest = content_hash(file_key, page_key, page_ordinal, item.canonical_text)
            ordered.append(
                OrderedBlock(
                    row=item.row,
                    file_order=file_order,
                    file_key=file_key,
                    page_key=page_key,
                    page_ordinal=page_ordinal,
                    order_source=order_source,
                    canonical_text=item.canonical_text,
                    content_hash=digest,
                    source_page_number=item.source_page_number,
                    ocr_page_index=item.ocr_page_index,
                )
            )
    return ordered
