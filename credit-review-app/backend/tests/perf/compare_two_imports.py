#!/usr/bin/env python3
"""QA 性能试验 · 两次导入稳定分窗对照（资产 3）。

目标
----
用 **同一份 15 页 OCR JSON** 导入两个互相隔离的任务，导出：

* 有序块清单（按「文件 + 物理页 + 页内稳定序号」排序，不含任何导入 UUID）；
* 分窗边界（窗口数、每窗块数/字符数、首末稳定标识、窗口内容 hash）；
* 「与导入 UUID 无关的内容 hash」：由 文件标识 + 物理页 + 页内序号 + 原文 计算；
* 确认「应查块全覆盖」：所有非空文本块都落在至少一个窗口里，且窗口内顺序单调；
* 两份结果的 diff 结论。

两套口径（关键）
----------------
* ``expected``：按稳定有序块清单重新构造 SourceBlock 后调用**同一个**
  ``chunk_source_blocks`` / ``chunk_blocks``。这是「稳定分窗修复后应达到」的口径。
* ``actual``：直接调用现有 ``load_source_blocks`` / ``load_file_blocks`` +
  ``chunk_source_blocks`` / ``chunk_blocks``。这是「当前 HEAD 实测」口径。
  现有代码只 ``order_by(OcrBlock.sequence_index)``（176 块仅 25 个不同值），
  同值行按 DB 物理序，窗口边界可能漂移；本脚本如实记录，不做任何推算填充。

约束
----
* 不修改任何业务代码、不新建迁移、不调用外部 OCR / LLM；
* 只新建两个隔离 Task/File，跑完 ``deleted_at`` 软删，run/ocr_* 保留可追溯；
* 脚本前后各读一次 2 条真实业务任务的状态，确认未被触碰；
* stdout 只输出纯 JSON（诊断走 stderr），证据同时落容器内磁盘兜底。

用法（宿主机项目根目录）
------------------------
    OCR_JSON="/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json"
    docker cp "$OCR_JSON" credit-review-app-worker-1:/tmp/qa_compare_ocr_slice.json
    docker exec -i credit-review-app-worker-1 python - \
        --evidence-out /tmp/qa_compare_two_imports.json \
        < backend/tests/perf/compare_two_imports.py > /tmp/qa_compare_stdout.json
    docker cp credit-review-app-worker-1:/tmp/qa_compare_two_imports.json \
        backend/tests/perf/evidence/compare_two_imports.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.checklist import checklist_hash
from app.classification import BlockRef, chunk_blocks, load_file_blocks
from app.cli import import_ocr_json
from app.core.config import settings
from app.core.db import engine
from app.models import OcrBlock, OcrPage, Task, TaskFile, User
from app.text_search import SourceBlock, chunk_source_blocks, load_source_blocks

OCR_JSON_SHA256 = "8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b"
OCR_JSON_PAGE_COUNT = 15
CHECKLIST_VERSION = "borrower-wcl-v1"
WINDOW_CHARACTERS = 8000
WINDOW_OVERLAP_CHARACTERS = 500
PROTECTED_TASK_IDS = [
    "607e6d41-4d47-4582-a5ad-07313b6c17bd",
    "ee59108d-e4f1-4aa8-bf2e-afe07d457384",
]
TASK_NAME_PREFIX = "QA-PERF-两次导入分窗对照"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _sha256_str(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _round(value: float) -> float:
    return round(value, 3)


def _emit(evidence: dict[str, Any], out_path: str) -> None:
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n"
    try:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[compare] 容器内证据落盘失败: {type(exc).__name__}: {exc}\n")
    sys.stdout.write(payload)
    sys.stdout.flush()


def _verify_ocr_json(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise RuntimeError(f"容器内 OCR JSON 不存在：{path}")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != OCR_JSON_SHA256:
        raise RuntimeError(
            f"OCR JSON SHA256 不匹配：实测 {digest} != 固定值 {OCR_JSON_SHA256}"
        )
    pages = json.loads(raw.decode("utf-8"))
    if not isinstance(pages, list) or len(pages) != OCR_JSON_PAGE_COUNT:
        raise RuntimeError("OCR JSON 不是 15 页对象数组")
    return {
        "container_path": path,
        "sha256": digest,
        "size_bytes": len(raw),
        "page_count": len(pages),
        "sha256_matches_fixed_constant": True,
    }


def _read_protected(session: Session) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tid in PROTECTED_TASK_IDS:
        row = session.get(Task, uuid.UUID(tid))
        out[tid] = {
            "exists": row is not None,
            "state": row.state if row else None,
            "deleted_at": row.deleted_at.isoformat() if row and row.deleted_at else None,
            "input_revision": row.input_revision if row else None,
        }
    return out


def _create_isolated(label: str) -> tuple[uuid.UUID, uuid.UUID, float]:
    t0 = time.perf_counter()
    with Session(engine) as session:
        owner = session.exec(select(User).where(User.is_active == True)).first()  # noqa: E712
        if not owner:
            raise RuntimeError("库内无 active 用户，无法创建隔离任务 owner")
        task = Task(
            owner_user_id=owner.id,
            name=f"{TASK_NAME_PREFIX}-{label}",
            product_code="working_capital_loan",
            customer_role="borrower",
            checklist_version=CHECKLIST_VERSION,
            state="PROCESSING",
            input_revision=0,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        file_row = TaskFile(
            task_id=task_id,
            original_name="《北京银行股份有限公司章程》 切分15页.PDF",
            media_type="application/pdf",
            size_bytes=0,
            # 两份隔离数据导入的是同一份 15 页 OCR JSON，必须声明为同一份文件内容。
            # source_ordering 的 file_key 取 TaskFile.sha256；若 A/B 不同，
            # K2 content_hash = sha256(file_key|page_key|page_ordinal|canonical_text)
            # 与 stable_key 前缀会天然不等，级联导致所有分窗签名比对失败
            # （T02 兼容回归实测 19/24，根因即此处造数，非业务代码）。
            sha256=OCR_JSON_SHA256,
            source_page_count=OCR_JSON_PAGE_COUNT,
        )
        session.add(file_row)
        session.flush()
        file_id = file_row.id
        session.commit()
    return task_id, file_id, _round(time.perf_counter() - t0)


def _soft_delete(task_id: uuid.UUID) -> str | None:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        deleted_at = datetime.now(UTC)
        task.deleted_at = deleted_at
        session.add(task)
        session.commit()
    return deleted_at.isoformat()


# ---------------------------------------------------------------------------
# 稳定有序块清单
# ---------------------------------------------------------------------------


def _load_stable_blocks(session: Session, task_id: uuid.UUID,
                        file_id: uuid.UUID) -> list[dict[str, Any]]:
    """稳定有序块清单。

    T01/T02 后优先复用业务实现 ``app.source_ordering.order_blocks``（K1 稳定排序键
    ``(file_order, page_key, page_ordinal)`` + K2 内容 hash），保证 QA 的 expected 口径
    与线上分窗实现完全一致；旧镜像无该模块时回退到 QA 独立排序（手写次级键）。
    两种口径都 **不把任何 DB UUID 写进 stable_key / 内容 hash**。
    """
    pages = session.exec(
        select(OcrPage).where(OcrPage.task_id == task_id, OcrPage.file_id == file_id)
    ).all()
    page_by_id = {p.id: p for p in pages}
    rows = session.exec(
        select(OcrBlock).where(OcrBlock.task_id == task_id, OcrBlock.file_id == file_id)
    ).all()

    business_ordered = None
    try:
        from app.source_ordering import load_file_keys, order_blocks
        business_ordered = order_blocks(
            rows, page_by_id, load_file_keys(session, [file_id])
        )
    except ImportError:
        business_ordered = None

    if business_ordered is not None:
        out: list[dict[str, Any]] = []
        for ob in business_ordered:
            row = ob.row
            page = page_by_id.get(row.page_id) if row.page_id else None
            out.append({
                "db_uuid": row.id,
                "page": ob.source_page_number,
                "ocr_page_index": ob.ocr_page_index,
                "provider_line_index": page.provider_line_index if page else 0,
                "page_inner_seq": ob.page_ordinal,
                "page_key": ob.page_key,
                "sequence_index": row.sequence_index,
                "provider_block_id": row.provider_block_id or "",
                "text": ob.canonical_text,
                "table_html": row.table_html,
                "label": row.label,
                "bbox": row.bbox,
                "polygon": row.polygon,
                "page_id": row.page_id,
                "page_width_px": page.width_px if page else None,
                "page_height_px": page.height_px if page else None,
                "coordinate_space": page.coordinate_space if page else "unknown",
                "order_source": ob.order_source,
                "file_key": ob.file_key,
                "business_content_hash": ob.content_hash,
                # stable_key 不含任何 UUID：file_key|page_key|page_ordinal|内容 hash 前缀
                "stable_key": (
                    f"{ob.file_key}|{ob.page_key}|{ob.page_ordinal}|{ob.content_hash[:16]}"
                ),
                "ordering": "business_order_blocks",
            })
        return out

    # ---- 旧镜像回退：QA 独立稳定排序（与业务实现不同，仅用于交叉核对） ----
    prepared: list[dict[str, Any]] = []
    for row in rows:
        text = (row.canonical_text or "").strip()
        if not text and not row.table_html:
            continue  # 与 load_source_blocks / load_file_blocks 的过滤规则一致
        page = page_by_id.get(row.page_id) if row.page_id else None
        prepared.append({
            "db_uuid": row.id,
            "page": page.source_page_number if page else None,
            "ocr_page_index": page.ocr_page_index if page else 0,
            "provider_line_index": page.provider_line_index if page else 0,
            "sequence_index": row.sequence_index,
            "provider_block_id": row.provider_block_id or "",
            "text": text,
            "table_html": row.table_html,
            "label": row.label,
            "bbox": row.bbox,
            "polygon": row.polygon,
            "page_id": row.page_id,
            "page_width_px": page.width_px if page else None,
            "page_height_px": page.height_px if page else None,
            "coordinate_space": page.coordinate_space if page else "unknown",
            "order_source": None,
            "file_key": None,
            "business_content_hash": None,
        })
    prepared.sort(key=lambda b: (
        b["ocr_page_index"] or 0,
        b["provider_line_index"] or 0,
        b["sequence_index"],
        b["provider_block_id"],
        b["text"],
    ))
    seq_by_page: dict[Any, int] = {}
    out = []
    for b in prepared:
        page_key = b["page"]
        page_seq = seq_by_page.get(page_key, 0)
        seq_by_page[page_key] = page_seq + 1
        b["page_inner_seq"] = page_seq
        b["page_key"] = page_key
        b["stable_key"] = (
            f"{b['page']}|{b['ocr_page_index']}|{page_seq}|"
            f"{b['provider_block_id']}|{b['sequence_index']}"
        )
        b["ordering"] = "qa_independent_fallback"
        out.append(b)
    return out


def _export_ordered_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "page": b["page"],
        "ocr_page_index": b["ocr_page_index"],
        "page_inner_seq": b["page_inner_seq"],
        "provider_block_id": b["provider_block_id"],
        "sequence_index": b["sequence_index"],
        "label": b["label"],
        "text_sha256": _sha256_str(b["text"]),
        "text_length": len(b["text"]),
        "table_html_sha256": (
            _sha256_str(b["table_html"]) if b["table_html"] else None
        ),
        "stable_key": b["stable_key"],
    } for b in blocks]


def _content_hash(blocks: list[dict[str, Any]]) -> str:
    """与导入 UUID 无关：文件内相对位置 + 物理页 + 页内序号 + 原文 + 表格。"""
    lines = []
    for b in blocks:
        table_hash = _sha256_str(b["table_html"]) if b["table_html"] else "-"
        lines.append(
            f"{b['page']}|{b['page_inner_seq']}|{b['provider_block_id']}|"
            f"{b['sequence_index']}|{_sha256_str(b['text'])}|{table_hash}"
        )
    return _sha256_str("\n".join(lines))


def _to_source_blocks(blocks: list[dict[str, Any]],
                      file_id: uuid.UUID) -> list[SourceBlock]:
    return [SourceBlock(
        block_id=b["db_uuid"],
        file_id=file_id,
        page_id=b["page_id"],
        text=b["text"],
        table_html=b["table_html"],
        bbox=b["bbox"],
        polygon=b["polygon"],
        source_page_number=b["page"],
        ocr_page_index=b["ocr_page_index"],
        page_width_px=b["page_width_px"],
        page_height_px=b["page_height_px"],
        coordinate_space=b["coordinate_space"],
    ) for b in blocks]


def _to_block_refs(blocks: list[dict[str, Any]]) -> list[BlockRef]:
    return [BlockRef(block_id=b["db_uuid"], text=b["text"],
                     table_html=b["table_html"]) for b in blocks]


# ---------------------------------------------------------------------------
# 分窗导出
# ---------------------------------------------------------------------------


def _describe_windows(windows: list[Any], kind: str,
                      stable_key_by_uuid: dict[uuid.UUID, str],
                      stable_index: dict[str, int],
                      window_text_func: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, w in enumerate(windows):
        blocks = w.blocks
        keys = [stable_key_by_uuid.get(b.block_id, f"unknown:{b.block_id}")
                for b in blocks]
        indexes = [stable_index.get(k, -1) for k in keys]
        content_lines = [
            f"{k}|{_sha256_str((b.text or '').strip())}"
            for k, b in zip(keys, blocks)
        ]
        out.append({
            "window_index": idx,
            "bundle_id": w.bundle_id,
            "block_count": len(blocks),
            "char_count": sum(len(b.text or "") for b in blocks),
            "first_stable_key": keys[0] if keys else None,
            "last_stable_key": keys[-1] if keys else None,
            "source_page_numbers": sorted({
                b.source_page_number for b in blocks
                if getattr(b, "source_page_number", None) is not None
            }) if kind == "search" else [],
            # 不含随机 UUID 的窗口内容 hash：稳定键 + 原文 hash
            "window_content_hash": _sha256_str("\n".join(content_lines)),
            # 现有 _window_text 含随机 OcrBlock UUID，仅本次导入内自洽（run 绑定产物）
            "window_text_sha256_run_bound": _sha256_str(window_text_func(blocks)),
            # T01/T02 新增 Window.window_text_sha256（业务侧请求 hash）
            "window_text_sha256_from_business_window": getattr(w, "window_text_sha256", None) or None,
            "stable_keys": keys,
            "stable_indexes": indexes,
            "order_monotonic_vs_stable_order": (
                all(i >= 0 for i in indexes) and indexes == sorted(indexes)
            ),
        })
    return out


def _coverage(windows: list[dict[str, Any]],
              all_keys: list[str]) -> dict[str, Any]:
    covered: set[str] = set()
    occurrences: dict[str, int] = {}
    for w in windows:
        for k in w["stable_keys"]:
            covered.add(k)
            occurrences[k] = occurrences.get(k, 0) + 1
    expected_set = set(all_keys)
    return {
        "expected_block_count": len(expected_set),
        "covered_block_count": len(covered & expected_set),
        "all_blocks_covered": expected_set.issubset(covered),
        "uncovered_stable_keys": sorted(expected_set - covered)[:20],
        "unexpected_stable_keys": sorted(covered - expected_set)[:20],
        "blocks_in_multiple_windows": sum(1 for v in occurrences.values() if v > 1),
        "max_occurrences": max(occurrences.values()) if occurrences else 0,
        "per_window_order_monotonic": all(
            w["order_monotonic_vs_stable_order"] for w in windows
        ),
    }


def _collect(task_id: uuid.UUID, file_id: uuid.UUID, label: str) -> dict[str, Any]:
    import app.classification as classification_mod
    import app.text_search as text_search_mod

    with Session(engine) as session:
        blocks = _load_stable_blocks(session, task_id, file_id)
    ordered = _export_ordered_blocks(blocks)
    stable_keys = [b["stable_key"] for b in ordered]
    stable_index = {k: i for i, k in enumerate(stable_keys)}
    stable_key_by_uuid = {b["db_uuid"]: b["stable_key"] for b in blocks}

    # expected：按稳定顺序重排后调用同一个分窗函数
    expected_search = chunk_source_blocks(
        _to_source_blocks(blocks, file_id), WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS
    )
    expected_classify = chunk_blocks(
        _to_block_refs(blocks), WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS
    )
    # actual：直接调用现有 load_*（当前 HEAD 的排序口径）
    actual_source_blocks = load_source_blocks(task_id, [file_id])
    actual_classify_blocks = load_file_blocks(task_id, file_id)
    actual_search = chunk_source_blocks(
        actual_source_blocks, WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS
    )
    actual_classify = chunk_blocks(
        actual_classify_blocks, WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS
    )

    expected_search_views = _describe_windows(
        expected_search, "search", stable_key_by_uuid, stable_index,
        text_search_mod._window_text,
    )
    expected_classify_views = _describe_windows(
        expected_classify, "classify", stable_key_by_uuid, stable_index,
        classification_mod._window_text,
    )
    actual_search_views = _describe_windows(
        actual_search, "search", stable_key_by_uuid, stable_index,
        text_search_mod._window_text,
    )
    actual_classify_views = _describe_windows(
        actual_classify, "classify", stable_key_by_uuid, stable_index,
        classification_mod._window_text,
    )

    return {
        "label": label,
        "task_id": str(task_id),
        "file_id": str(file_id),
        "source_block_count": len(ordered),
        "source_total_characters": sum(b["text_length"] for b in ordered),
        "distinct_sequence_index_values": len({
            b["sequence_index"] for b in ordered
        }),
        "content_hash_excluding_import_uuid": _content_hash(blocks),
        "content_hash_k2_business_aggregate": (
            _sha256_str("\n".join(
                b["business_content_hash"] for b in blocks
                if b.get("business_content_hash")
            ))
            if any(b.get("business_content_hash") for b in blocks) else None
        ),
        "ordering_source": blocks[0].get("ordering") if blocks else None,
        "order_sources_used": sorted({
            b.get("order_source") for b in blocks if b.get("order_source")
        }),
        "order_sources_note": (
            "单块页的 order_source 会是 canonical_text_sha256（所有排序级只有 1 个取值时的末级回退），"
            "这类页只有 1 个块、不存在阅读顺序问题；['bbox','canonical_text_sha256'] 属如实记录，"
            "不是旧数据异常（工程师 T02 提示）。"
        ),
        "ordered_block_list_sha256": _json_sha256(ordered),
        "ordered_blocks": ordered,
        "expected_windows": {
            "search": expected_search_views,
            "classify": expected_classify_views,
            "search_window_count": len(expected_search_views),
            "classify_window_count": len(expected_classify_views),
            "search_coverage": _coverage(expected_search_views, stable_keys),
            "classify_coverage": _coverage(expected_classify_views, stable_keys),
        },
        "actual_windows": {
            "search": actual_search_views,
            "classify": actual_classify_views,
            "search_window_count": len(actual_search_views),
            "classify_window_count": len(actual_classify_views),
            "search_coverage": _coverage(actual_search_views, stable_keys),
            "classify_coverage": _coverage(actual_classify_views, stable_keys),
        },
        "parameters": {
            "max_chars": WINDOW_CHARACTERS,
            "overlap_chars": WINDOW_OVERLAP_CHARACTERS,
            "runtime_llm_window_characters": settings.LLM_WINDOW_CHARACTERS,
            "runtime_llm_window_overlap_characters": settings.LLM_WINDOW_OVERLAP_CHARACTERS,
            "parameters_match_runtime": (
                settings.LLM_WINDOW_CHARACTERS == WINDOW_CHARACTERS
                and settings.LLM_WINDOW_OVERLAP_CHARACTERS == WINDOW_OVERLAP_CHARACTERS
            ),
        },
    }


# ---------------------------------------------------------------------------
# 对照
# ---------------------------------------------------------------------------


def _window_signature(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只取「与导入 UUID 无关」的窗口字段做对照。"""
    return [{
        "window_index": w["window_index"],
        "block_count": w["block_count"],
        "char_count": w["char_count"],
        "first_stable_key": w["first_stable_key"],
        "last_stable_key": w["last_stable_key"],
        "window_content_hash": w["window_content_hash"],
        "order_monotonic_vs_stable_order": w["order_monotonic_vs_stable_order"],
    } for w in views]


def _diff_windows(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    sa, sb = _window_signature(a), _window_signature(b)
    if sa == sb:
        return {"equal": True, "differences": []}
    differences = []
    for i in range(max(len(sa), len(sb))):
        x = sa[i] if i < len(sa) else None
        y = sb[i] if i < len(sb) else None
        if x != y:
            differences.append({"window_index": i, "a": x, "b": y})
    return {"equal": False, "differences": differences[:20]}


def _compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("内容 hash 与导入 UUID 无关且两次一致",
        a["content_hash_excluding_import_uuid"] == b["content_hash_excluding_import_uuid"],
        f"A={a['content_hash_excluding_import_uuid']} B={b['content_hash_excluding_import_uuid']}")
    add("有序块清单两次一致",
        a["ordered_block_list_sha256"] == b["ordered_block_list_sha256"],
        f"A={a['ordered_block_list_sha256']} B={b['ordered_block_list_sha256']}")
    add("块数与总字符数两次一致",
        a["source_block_count"] == b["source_block_count"]
        and a["source_total_characters"] == b["source_total_characters"],
        f"A={a['source_block_count']}块/{a['source_total_characters']}字 "
        f"B={b['source_block_count']}块/{b['source_total_characters']}字")

    for kind in ("expected", "actual"):
        for stage in ("search", "classify"):
            d = _diff_windows(
                a[f"{kind}_windows"][stage], b[f"{kind}_windows"][stage]
            )
            add(f"{kind}.{stage} 两次导入分窗边界一致", d["equal"],
                f"differences={len(d['differences'])}")

    for label, data in (("A", a), ("B", b)):
        for kind in ("expected", "actual"):
            for stage in ("search", "classify"):
                cov = data[f"{kind}_windows"][f"{stage}_coverage"]
                add(f"{label}.{kind}.{stage} 应查块全覆盖",
                    cov["all_blocks_covered"],
                    f"covered={cov['covered_block_count']}/{cov['expected_block_count']} "
                    f"跨窗重复块={cov['blocks_in_multiple_windows']}")
                add(f"{label}.{kind}.{stage} 窗口内顺序相对稳定序单调",
                    cov["per_window_order_monotonic"],
                    f"per_window={[w['order_monotonic_vs_stable_order'] for w in data[f'{kind}_windows'][stage]]}")

    # 现有 _window_text 含随机 UUID：跨导入必然不同（如实记录，不当作失败项）
    rt_a = [w["window_text_sha256_run_bound"] for w in a["actual_windows"]["search"]]
    rt_b = [w["window_text_sha256_run_bound"] for w in b["actual_windows"]["search"]]
    add("（披露）现有 _window_text 跨导入不同（run 绑定产物，非失败项）",
        rt_a != rt_b,
        f"A={rt_a} B={rt_b}")

    passed = sum(1 for c in checks if c["ok"])
    failed = sum(1 for c in checks if not c["ok"])
    return {
        "method": (
            "A/B 各自导出稳定有序块清单、内容 hash 与两套分窗口径后逐字段比对；"
            "所有结论来自本脚本对真实 DB 行的读取，未使用任何推算值。"
        ),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": passed,
            "failed": failed,
            "note": "「（披露）」项按预期为 True；其余任一 False 都代表当前 HEAD 的稳定分窗未达标。",
        },
        "expected_search_diff": _diff_windows(
            a["expected_windows"]["search"], b["expected_windows"]["search"]
        ),
        "actual_search_diff": _diff_windows(
            a["actual_windows"]["search"], b["actual_windows"]["search"]
        ),
        "expected_classify_diff": _diff_windows(
            a["expected_windows"]["classify"], b["expected_windows"]["classify"]
        ),
        "actual_classify_diff": _diff_windows(
            a["actual_windows"]["classify"], b["actual_windows"]["classify"]
        ),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="两次导入稳定分窗对照")
    parser.add_argument("--ocr-json", default="/tmp/qa_compare_ocr_slice.json")
    parser.add_argument("--evidence-out", default="/tmp/qa_compare_two_imports.json")
    parser.add_argument("--keep-task", action="store_true", help="跑完不软删隔离任务")
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "schema_version": "qa-compare-two-imports-1",
        "ran_at": _now_iso(),
        "status": "running",
        "scope": "同一 15 页 OCR JSON 两次导入的稳定分窗对照；不调用外部 OCR/LLM，不改业务代码",
        "protected_real_tasks": PROTECTED_TASK_IDS,
        "blockers": [],
    }
    task_ids: list[uuid.UUID] = []
    with Session(engine) as session:
        evidence["protected_before"] = _read_protected(session)

    try:
        evidence["ocr_json"] = _verify_ocr_json(args.ocr_json)
        evidence["checklist"] = {
            "version": CHECKLIST_VERSION,
            "checklist_hash": checklist_hash(CHECKLIST_VERSION),
        }
        t0 = time.perf_counter()
        a_task, a_file, a_setup = _create_isolated("A")
        b_task, b_file, b_setup = _create_isolated("B")
        task_ids = [a_task, b_task]
        evidence["isolation"] = {
            "A": {"task_id": str(a_task), "file_id": str(a_file)},
            "B": {"task_id": str(b_task), "file_id": str(b_file)},
            "setup_seconds": {"A": a_setup, "B": b_setup},
            "soft_delete_note": "仅软删隔离 tasks 行；ocr_* 全部保留可追溯",
        }

        import_times: dict[str, float] = {}
        for label, fid in (("A", a_file), ("B", b_file)):
            t = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                import_ocr_json(str(fid), args.ocr_json)
            import_times[label] = _round(time.perf_counter() - t)
        evidence["isolation"]["import_seconds"] = import_times

        evidence["A"] = _collect(a_task, a_file, "A")
        evidence["B"] = _collect(b_task, b_file, "B")
        evidence["diff"] = _compare(evidence["A"], evidence["B"])
        evidence["status"] = "measured"
        evidence["total_measured_seconds"] = _round(time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001
        evidence["status"] = "blocked"
        evidence["blockers"].append({
            "stage": "setup_or_measurement",
            "error": f"{type(exc).__name__}: {exc}"[:800],
            "note": "未完成字段保持缺失，不填推算值",
        })
    finally:
        if not args.keep_task:
            deleted: dict[str, str | None] = {}
            for label, tid in zip(("A", "B"), task_ids):
                deleted[label] = _soft_delete(tid)
            evidence["isolation"]["soft_deleted_at"] = deleted
        with Session(engine) as session:
            evidence["protected_after"] = _read_protected(session)
        evidence["protected_unchanged"] = (
            evidence.get("protected_before") == evidence.get("protected_after")
        )

    _emit(evidence, args.evidence_out)
    return 0 if evidence["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
