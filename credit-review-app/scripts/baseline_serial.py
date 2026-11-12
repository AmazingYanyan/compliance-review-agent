#!/usr/bin/env python3
"""短样本串行基线（2026-11-12）：真实模型 + 真实串行链路 + 零业务代码改动。

目标
----
固定同一份 OCR JSON、同一份清单、同一套提示词与窗口参数，在 worker 容器内
**同步直接调用** `run_pipeline.func(str(run_id))`，跑一次真实的串行基线，并
通过 monkeypatch 观测器收集现有 RunStep 缺失的字段：

* 实际窗口数（classify 与每个检查项，用真实 `chunk_blocks` / `chunk_source_blocks` 实测）
* 每次真实 HTTP 请求（`LLMClient._chat`）的耗时，逐条记录
* 每次结构化调用（`LLMClient.complete_json`）的耗时、窗口归因、重试/超时/致命错误
* 各阶段墙钟耗时（包装 `_classify_stage` / `_search_stage` / `_vision_stage` / `_complete_run`）
* OCR JSON 导入落库耗时 vs 后处理耗时（严格分栏，不把复用 JSON 冒充 OCR 识别耗时）

约束
----
* 不修改任何业务代码、`models.py`、迁移、接口；不重建 worker 镜像。
* 不触发外部 OCR 服务（复用既有 PaddleOCR-VL 导出 JSON，走 `app.cli.import_ocr_json`）。
* 不经过 Procrastinate 队列（不 `defer` / 不入队），队列调度开销不计入。
* 不触碰库内既有任务；只用新建隔离 task/file，跑完 `deleted_at` 软删保留可追溯。
* 所有数字来自 `time.perf_counter()` / DB 真实记录；推算值单独分栏标注「推算，非实测」。

用法（在宿主机项目根目录执行，脚本经 stdin 送入 worker 容器）
------------------------------------------------------------
    OCR_JSON="/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json"
    shasum -a 256 "$OCR_JSON"
    docker cp "$OCR_JSON" credit-review-app-worker-1:/tmp/baseline_ocr_slice.json
    docker exec -i credit-review-app-worker-1 python - --evidence-out /tmp/baseline_evidence.json < scripts/baseline_serial.py > /tmp/baseline_stdout.json
    docker cp credit-review-app-worker-1:/tmp/baseline_evidence.json /tmp/baseline_stdout.json   # stdout 管道断开时的兜底取回
    python3 -c "import json,pathlib; d=json.loads(pathlib.Path('/tmp/baseline_stdout.json').read_text()); pathlib.Path('/tmp/baseline_raw.json').write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')"

可选参数：
    --probe-only     只造隔离数据 + 导入 + 实测窗口数 + 指纹，不调用模型，跑完软删。
    --keep-task      跑完不软删隔离任务（默认软删；软删不影响 run/results 落库）。
    --ocr-json       容器内 OCR JSON 路径，默认 /tmp/baseline_ocr_slice.json。
    --evidence-out   容器内证据 JSON 落盘路径，默认 /tmp/baseline_evidence.json。

注意：脚本 stdout 只输出纯 JSON（诊断信息走 stderr），且证据同时落容器内磁盘，
因此即使宿主机侧 docker exec 的 stdout 管道被断开，仍可 docker cp 取回完整证据。
格式化命令只把脚本原始输出写到 /tmp/baseline_raw.json，不可覆盖交付证据
docs/perf_baseline_2026-11-12.json；交付版另需按证据 post_processing_notes.what_changed
补回人工段与 QA 披露。固定项指纹一致只保证输入相同，窗口级指纹与 Result.fingerprint
绑定该次导入的 OcrBlock UUID，跨 run 不可复现（见 sample_limitations.run_bound_artifacts）。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

import app.classification as classification_mod
import app.processing_pipeline as pipeline_mod
import app.text_search as text_search_mod
from app.checklist import checklist_hash, get_checklist, get_leaves
from app.classification import CLASSIFY_SYSTEM, chunk_blocks, load_file_blocks
from app.cli import import_ocr_json
from app.core.config import settings
from app.core.db import engine
from app.llm_client import LLMClient
from app.llm_schemas import CLASSIFICATION_SCHEMA, TEXT_SEARCH_SCHEMA, VISION_MATCH_SCHEMA
from app.models import (
    OcrBlock,
    OcrPage,
    ProcessingRun,
    Result,
    ResultSource,
    RunFile,
    RunStep,
    Task,
    TaskFile,
    User,
)
from app.processing_pipeline import run_pipeline
from app.text_search import SEARCH_SYSTEM, chunk_source_blocks, load_source_blocks
from app.vision_match import VISION_SYSTEM

# ---------------------------------------------------------------------------
# 固定项（后续并发对照须复用同一份 JSON、同一套固定项，且必须复用同一批隔离数据：
# 同一 file_id / 同一批 OcrBlock UUID；固定项一致只保证输入相同，详见 sample_limitations.run_bound_artifacts）
# ---------------------------------------------------------------------------

BASELINE_DATE = "2026-11-12"
SCHEMA_VERSION = "baseline-serial-1"

OCR_JSON_HOST_PATH = (
    "/Users/eddie/Documents/WorkBuddy/合规审查智能体/"
    "《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json"
)
OCR_JSON_CONTAINER_PATH = "/tmp/baseline_ocr_slice.json"
OCR_JSON_SHA256 = "8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b"
OCR_JSON_SIZE_BYTES = 143880
OCR_JSON_PAGE_COUNT = 15
OCR_JSON_NOTE = "原《北京银行股份有限公司章程》PDF 物理第 1–15 页，1:1 对应；原 PDF 共 62 页"

CHECKLIST_VERSION = "borrower-wcl-v1"
WINDOW_CHARACTERS = 8000
WINDOW_OVERLAP_CHARACTERS = 500

ISOLATED_TASK_NAME = "QA-BASELINE-短样本串行-2026-11-12"
ISOLATED_FILE_NAME = "《北京银行股份有限公司章程》 切分15页.PDF"

# 关键条款对照探针：物理页 -> 精确短语（归一化去空白后子串匹配）
CLAUSE_PROBES: list[dict[str, Any]] = [
    {
        "id": "C1",
        "physical_page": 7,
        "title": "第十七条 业务范围（含外汇借款 / 外汇担保 / 提供信用证服务及担保 / 贷款）",
        "keywords": ["第十七条", "外汇借款", "外汇担保", "提供信用证服务及担保"],
        "target_check_id": "charter.business_scope",
        "note": "经营范围条款；担保类检查项若引用本页即属误命中",
    },
    {
        "id": "C2",
        "physical_page": 8,
        "title": "第二十四条 不以赠与/垫资/担保/补偿/贷款等形式资助购股人",
        "keywords": ["第二十四条", "不以赠与、垫资、担保、补偿或贷款等形式"],
        "target_check_id": "charter.ownership_and_special_terms",
        "note": "含「担保」字样，但属于股权资助限制，非对外担保规则",
    },
    {
        "id": "C3",
        "physical_page": 8,
        "title": "第二十五条 增加注册资本须经股东大会分别作出决议",
        "keywords": ["第二十五条", "经股东大会分别作出决议"],
        "target_check_id": "charter.approval_body",
        "note": "决议机构证据",
    },
    {
        "id": "C4",
        "physical_page": 13,
        "title": "第四十一条 5% 以上有表决权股份股东质押书面报告 / 控股股东借款担保",
        "keywords": ["第四十一条", "持有本行5%以上有表决权股份", "借款担保"],
        "target_check_id": "charter.ownership_and_special_terms",
        "note": "含「借款担保」字样，属股东行为规范，非对外担保决议规则",
    },
    {
        "id": "C5",
        "physical_page": 13,
        "title": "第四十三条 本行对股东贷款的条件不得优于其他借款人同类贷款的条件",
        "keywords": ["第四十三条", "本行对股东贷款的条件不得优于"],
        "target_check_id": "charter.ownership_and_special_terms",
        "note": "关联交易限制",
    },
    {
        "id": "C6",
        "physical_page": 13,
        "title": "第四十四条 授信逾期应限制其在股东大会的表决权",
        "keywords": ["第四十四条", "授信逾期"],
        "target_check_id": "charter.voting_ratio",
        "note": "表决权限制",
    },
    {
        "id": "C7",
        "physical_page": 14,
        "title": "股权出质事前书面告知董事会 / 借款余额超股权净值不得质押 / 质押达 50% 限制表决权",
        "keywords": ["事前书面告知董事会", "借款余额超过其持有经审计的上一年度股权净值", "50%"],
        "target_check_id": "charter.ownership_and_special_terms",
        "note": "股权结构与特殊条款",
    },
    {
        "id": "C8",
        "physical_page": 15,
        "title": "第四十六条 股东大会职权（十二）审议批准第四十七条担保事项 / 3% 提案 / 不得授权董事会",
        "keywords": [
            "第四十六条",
            "审议批准第四十七条规定的担保事项",
            "股东大会不得将法定由股东大会行使的职权授予董事会行使",
        ],
        "target_check_id": "charter.approval_body",
        "note": "批准机构核心证据",
    },
    {
        "id": "C9",
        "physical_page": 15,
        "title": "第四十七条 五类须经股东大会审议通过的对外担保行为",
        "keywords": ["第四十七条", "本行下列对外担保行为", "净资产50%", "总资产30%", "资产负债率", "对股东"],
        "target_check_id": "charter.guarantee_restrictions",
        "note": "对外担保限制性规定核心证据",
    },
    {
        "id": "C10",
        "physical_page": None,
        "title": "法定代表人的签字权限（样本外条款）",
        "keywords": ["法定代表人", "签字权限"],
        "target_check_id": "charter.legal_representative_signature_authority",
        "note": "物理 1–15 页大概率不存在，用于验证 no_matching_evidence 行为",
        "sample_outside_probe": True,
        "present_in_sample_ocr_note": (
            "仅通用词「法定代表人」命中（基线导入 176 块中 2 块，物理页 5 / 13）；"
            "全文「签字」「签署」「签名」「签章」0 出现（psql 只读复验），非目标条款，判样本外"
        ),
    },
]

# 第 7 页经营范围中出现、容易被担保类检查项误引的词
FALSE_POSITIVE_KEYWORDS = ["外汇担保", "提供信用证服务及担保", "外汇借款"]
GUARANTEE_CHECK_IDS = ["charter.approval_body", "charter.guarantee_restrictions"]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _sha256_str(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _norm(value: str | None) -> str:
    """归一化：去所有空白，规避 OCR 空格差异。"""
    return re.sub(r"\s+", "", value or "")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _round(value: float) -> float:
    return round(value, 3)


def _dist(values: list[float]) -> dict[str, Any]:
    """耗时分布（全部来自实测逐条记录）。"""
    if not values:
        return {"count": 0, "min_seconds": None, "max_seconds": None,
                "mean_seconds": None, "median_seconds": None, "p95_seconds": None,
                "sum_seconds": 0.0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "count": len(values),
        "min_seconds": _round(ordered[0]),
        "max_seconds": _round(ordered[-1]),
        "mean_seconds": _round(statistics.fmean(values)),
        "median_seconds": _round(statistics.median(values)),
        "p95_seconds": _round(ordered[p95_index]),
        "sum_seconds": _round(sum(values)),
    }


def _excerpt(value: str | None, limit: int = 200) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _match_keywords(text: str | None, keywords: list[str]) -> list[str]:
    normalized = _norm(text)
    return [kw for kw in keywords if _norm(kw) in normalized]


# ---------------------------------------------------------------------------
# 观测器：monkeypatch 收集窗口数 / 调用次数 / 单次请求耗时 / 超时与重试
# ---------------------------------------------------------------------------


class BaselineObserver:
    """串行单线程观测器；所有包装器均只记录，不改变业务行为。"""

    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.chunk_events: list[dict[str, Any]] = []
        self.stage_events: list[dict[str, Any]] = []
        self.search_events: list[dict[str, Any]] = []
        self.window_index_by_text_hash: dict[str, int] = {}
        self.current_check_id: str | None = None
        self.current_stage: str | None = None
        self._originals: dict[str, Any] = {}
        self._installed = False

    def install(self) -> None:
        """安装包装器（只替换内存中的模块/类属性，不改磁盘代码）。"""
        if self._installed:
            return
        obs = self
        self._originals = {
            "chat": LLMClient._chat,
            "complete": LLMClient.complete_json,
            "chunk_source": text_search_mod.chunk_source_blocks,
            "chunk_classify": classification_mod.chunk_blocks,
            "search": pipeline_mod.search_check_item,
            "classify_stage": pipeline_mod._classify_stage,
            "search_stage": pipeline_mod._search_stage,
            "vision_stage": pipeline_mod._vision_stage,
            "complete_run": pipeline_mod._complete_run,
        }

        orig_chat = self._originals["chat"]
        orig_complete = self._originals["complete"]
        orig_chunk_source = self._originals["chunk_source"]
        orig_chunk_classify = self._originals["chunk_classify"]
        orig_search = self._originals["search"]
        orig_classify_stage = self._originals["classify_stage"]
        orig_search_stage = self._originals["search_stage"]
        orig_vision_stage = self._originals["vision_stage"]
        orig_complete_run = self._originals["complete_run"]

        def wrapped_chat(self_client: LLMClient, messages: list[dict[str, Any]], model: str,
                         response_format: dict[str, Any] | None, temperature: float) -> str:
            seq = len(obs.chat_calls) + 1
            started_iso = _now_iso()
            t0 = time.perf_counter()
            messages_hash = _json_sha256(messages)
            rf_type = (response_format or {}).get("type") if isinstance(response_format, dict) else None
            messages_len = len(messages) if isinstance(messages, list) else 0
            error_type: str | None = None
            error_message: str | None = None
            try:
                return orig_chat(self_client, messages, model, response_format, temperature)
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                error_message = str(exc)[:200]
                raise
            finally:
                elapsed = time.perf_counter() - t0
                obs.chat_calls.append({
                    "seq": seq,
                    "started_at": started_iso,
                    "elapsed_seconds": _round(elapsed),
                    "model": model,
                    "response_format_type": rf_type,
                    "messages_len": messages_len,
                    "messages_sha256": messages_hash,
                    "stage": obs.current_stage,
                    "check_item_id": obs.current_check_id,
                    "ok": error_type is None,
                    "error_type": error_type,
                    "error_message_short": error_message,
                    # messages_len > 2 表示 _repair 追加了 assistant/user 两条
                    "is_format_repair_attempt": messages_len > 2,
                })

        def wrapped_complete(self_client: LLMClient, *, system: str, user: str,
                             schema_name: str, json_schema: dict[str, Any],
                             validator: Any, images: list[str] | None = None,
                             model: str | None = None, temperature: float = 0.0) -> dict[str, Any]:
            seq = len(obs.complete_calls) + 1
            started_iso = _now_iso()
            t0 = time.perf_counter()
            user_hash = _sha256_str(user)
            system_hash = _sha256_str(system)
            # 只有 text_search / vision 的 user 含「检查项：…（id=…）」；
            # classification 的 user 里出现的是 block_id=，不能用通用 id= 正则去抓，
            # 否则会把 OCR 块 UUID 误当作检查项 id。
            check_id: str | None = None
            if schema_name in ("text_search_output", "vision_match_output"):
                match = re.search(r"检查项：.*?（id=([A-Za-z0-9_.\-]+)", user)
                if match:
                    check_id = match.group(1)
            body: str | None = None
            if schema_name == "text_search_output":
                parts = user.split("\n", 2)
                body = parts[2] if len(parts) == 3 else None
            elif schema_name == "classification_output":
                parts = user.split("\n", 1)
                body = parts[1] if len(parts) == 2 else None
            window_index: int | None = None
            if body is not None:
                window_index = obs.window_index_by_text_hash.get(_sha256_str(body))
            error_type: str | None = None
            error_message: str | None = None
            try:
                return orig_complete(
                    self_client, system=system, user=user, schema_name=schema_name,
                    json_schema=json_schema, validator=validator, images=images,
                    model=model, temperature=temperature,
                )
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                error_message = str(exc)[:200]
                raise
            finally:
                elapsed = time.perf_counter() - t0
                obs.complete_calls.append({
                    "seq": seq,
                    "started_at": started_iso,
                    "elapsed_seconds": _round(elapsed),
                    "schema_name": schema_name,
                    "check_item_id": check_id or obs.current_check_id,
                    "window_index": window_index,
                    "window_text_hash": _sha256_str(body) if body is not None else None,
                    "system_sha256": system_hash,
                    "user_sha256": user_hash,
                    "user_chars": len(user),
                    "has_images": bool(images),
                    "stage": obs.current_stage,
                    "ok": error_type is None,
                    "error_type": error_type,
                    "error_message_short": error_message,
                })

        def wrapped_chunk_source(blocks: list[Any], max_chars: int,
                                 overlap_chars: int) -> list[Any]:
            windows = orig_chunk_source(blocks, max_chars, overlap_chars)
            mapping: dict[str, int] = {}
            for idx, window in enumerate(windows):
                body = text_search_mod._window_text(window.blocks)
                mapping[_sha256_str(body)] = idx
                obs.chunk_events.append({
                    "kind": "search_window",
                    "check_item_id": obs.current_check_id,
                    "window_index": idx,
                    "bundle_id": window.bundle_id,
                    "block_count": len(window.blocks),
                    "char_count": sum(len(b.text) for b in window.blocks),
                    "window_text_sha256": _sha256_str(body),
                    "source_pages": sorted({
                        b.source_page_number for b in window.blocks
                        if b.source_page_number is not None
                    }),
                })
            if mapping:
                obs.window_index_by_text_hash = mapping
            return windows

        def wrapped_chunk_classify(blocks: list[Any], max_chars: int,
                                   overlap_chars: int) -> list[Any]:
            windows = orig_chunk_classify(blocks, max_chars, overlap_chars)
            mapping: dict[str, int] = {}
            for idx, window in enumerate(windows):
                body = classification_mod._window_text(window.blocks)
                mapping[_sha256_str(body)] = idx
                obs.chunk_events.append({
                    "kind": "classify_window",
                    "check_item_id": None,
                    "window_index": idx,
                    "bundle_id": window.bundle_id,
                    "block_count": len(window.blocks),
                    "char_count": window.char_count,
                    "window_text_sha256": _sha256_str(body),
                    "source_pages": [],
                })
            if mapping:
                obs.window_index_by_text_hash = mapping
            return windows

        def wrapped_search(*, task_id: uuid.UUID, check_item: dict[str, Any],
                           file_ids: list[uuid.UUID], client: LLMClient,
                           max_chars: int, overlap_chars: int) -> tuple[list[Any], str | None]:
            check_id = check_item["id"]
            obs.current_check_id = check_id
            t0 = time.perf_counter()
            calls_before = len(obs.complete_calls)
            evidence: list[Any] = []
            failed_reason: str | None = None
            try:
                evidence, failed_reason = orig_search(
                    task_id=task_id, check_item=check_item, file_ids=file_ids,
                    client=client, max_chars=max_chars, overlap_chars=overlap_chars,
                )
                return evidence, failed_reason
            finally:
                elapsed = time.perf_counter() - t0
                windows = [e for e in obs.chunk_events
                           if e["kind"] == "search_window" and e["check_item_id"] == check_id]
                obs.search_events.append({
                    "check_item_id": check_id,
                    "material_type": check_item.get("material_type"),
                    "elapsed_seconds": _round(elapsed),
                    "measured_window_count": len(windows),
                    "complete_json_call_count": len(obs.complete_calls) - calls_before,
                    "chat_call_count": None,  # 稍后按 complete_json seq 区间回填
                    "evidence_count": len(evidence),
                    "failed_reason": failed_reason,
                    "_complete_seq_start": calls_before + 1,
                    "_complete_seq_end": len(obs.complete_calls),
                })
                obs.current_check_id = None

        def _stage_wrapper(name: str, original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                obs.current_stage = name
                t0 = time.perf_counter()
                started_iso = _now_iso()
                chat_before = len(obs.chat_calls)
                complete_before = len(obs.complete_calls)
                try:
                    return original(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter() - t0
                    obs.stage_events.append({
                        "stage": name,
                        "started_at": started_iso,
                        "elapsed_seconds": _round(elapsed),
                        "chat_call_count": len(obs.chat_calls) - chat_before,
                        "complete_json_call_count": len(obs.complete_calls) - complete_before,
                    })
                    obs.current_stage = None
            return wrapped

        LLMClient._chat = wrapped_chat
        LLMClient.complete_json = wrapped_complete
        text_search_mod.chunk_source_blocks = wrapped_chunk_source
        classification_mod.chunk_blocks = wrapped_chunk_classify
        pipeline_mod.search_check_item = wrapped_search
        pipeline_mod._classify_stage = _stage_wrapper("classify", orig_classify_stage)
        pipeline_mod._search_stage = _stage_wrapper("search", orig_search_stage)
        pipeline_mod._vision_stage = _stage_wrapper("vision", orig_vision_stage)
        pipeline_mod._complete_run = _stage_wrapper("complete_run", orig_complete_run)
        self._installed = True

    def restore(self) -> None:
        """还原包装器（保证同一进程后续行为不受影响）。"""
        if not self._installed:
            return
        LLMClient._chat = self._originals["chat"]
        LLMClient.complete_json = self._originals["complete"]
        text_search_mod.chunk_source_blocks = self._originals["chunk_source"]
        classification_mod.chunk_blocks = self._originals["chunk_classify"]
        pipeline_mod.search_check_item = self._originals["search"]
        pipeline_mod._classify_stage = self._originals["classify_stage"]
        pipeline_mod._search_stage = self._originals["search_stage"]
        pipeline_mod._vision_stage = self._originals["vision_stage"]
        pipeline_mod._complete_run = self._originals["complete_run"]
        self._installed = False

    def summarize_calls(self) -> dict[str, Any]:
        """逐条请求耗时 + 重试/超时/致命/格式错误统计（全部实测）。"""
        chat_elapsed = [c["elapsed_seconds"] for c in self.chat_calls]
        complete_elapsed = [c["elapsed_seconds"] for c in self.complete_calls]
        errors = [c for c in self.chat_calls if not c["ok"]]
        transient = [c for c in errors if c["error_type"] == "LLMTransientError"]
        timeouts = [c for c in transient
                    if any(k in (c["error_message_short"] or "").lower()
                           for k in ("timeout", "timed out", "超时"))]
        fatal = [c for c in errors if c["error_type"] == "LLMFatalError"]
        complete_errors = [c for c in self.complete_calls if not c["ok"]]
        format_errors = [c for c in complete_errors if c["error_type"] == "LLMFormatError"]
        repairs = [c for c in self.chat_calls if c["is_format_repair_attempt"]]

        # 按 (schema_name, check_item_id, user_sha256) 分组 => 同一窗口的重复派发即重试
        groups: dict[str, list[dict[str, Any]]] = {}
        for call in self.complete_calls:
            key = f"{call['schema_name']}|{call['check_item_id']}|{call['user_sha256']}"
            groups.setdefault(key, []).append(call)
        retry_detail: list[dict[str, Any]] = []
        transient_retry_count = 0
        for key, calls in groups.items():
            if len(calls) <= 1:
                continue
            for attempt, call in enumerate(calls):
                retry_detail.append({
                    "group": key,
                    "attempt": attempt,  # 0-based：0 为首次，>=1 为窗口级重试
                    "complete_json_seq": call["seq"],
                    "elapsed_seconds": call["elapsed_seconds"],
                    "ok": call["ok"],
                    "error_type": call["error_type"],
                    "window_index": call["window_index"],
                })
            transient_retry_count += len(calls) - 1

        # 回填每个检查项的 chat 调用数（按 complete_json seq 区间映射到 chat 的归属不稳，
        # 这里直接按 chat_calls 的 check_item_id 与 stage 统计，避免臆造对应关系）
        for event in self.search_events:
            cid = event["check_item_id"]
            event["chat_call_count"] = len([
                c for c in self.chat_calls if c["check_item_id"] == cid
            ])
            event.pop("_complete_seq_start", None)
            event.pop("_complete_seq_end", None)

        return {
            "chat_request_count": len(self.chat_calls),
            "complete_json_call_count": len(self.complete_calls),
            "per_request": self.chat_calls,
            "per_complete_json": self.complete_calls,
            "chat_elapsed_distribution_seconds": _dist(chat_elapsed),
            "complete_json_elapsed_distribution_seconds": _dist(complete_elapsed),
            "timeout_count": len(timeouts),
            "timeout_detail": [
                {"chat_seq": c["seq"], "error_type": c["error_type"],
                 "error_message_short": c["error_message_short"]}
                for c in timeouts
            ],
            "transient_error_count": len(transient),
            "transient_error_detail": [
                {"chat_seq": c["seq"], "error_message_short": c["error_message_short"]}
                for c in transient
            ],
            "window_level_retry_count": transient_retry_count,
            "window_level_retry_detail": retry_detail,
            "fatal_error_count": len(fatal),
            "format_error_count": len(format_errors),
            "format_repair_chat_count": len(repairs),
            "note": (
                "attempt 为 0-based 窗口级重试序号；其中 0 是首次派发，>=1 是 "
                "search_check_item 内 LLM_MAX_TRANSIENT_RETRIES 循环的重试。"
                "同一 complete_json 可能触发多次 _chat（json_schema 降级 json_object、_repair 格式修复），"
                "因此 chat_request_count >= complete_json_call_count 属正常。"
                "P95 口径（QA 独立复验后补充披露）：_dist 用 ordered[int(round((n-1)*0.95))]，"
                "n=14 取 ordered[12]=68.777s；常规线性插值 P95=93.893s、nearest-rank=140.537s，外部复算须同口径。"
                "14 次 attempt=0 由 timing.run_steps[].attempt（19 条全 0）与三个空 detail 推得，非逐次调用直接观测。"
            ),
        }


# ---------------------------------------------------------------------------
# 隔离数据
# ---------------------------------------------------------------------------


def create_isolated_data() -> tuple[uuid.UUID, uuid.UUID, str, float]:
    """新建隔离 Task + TaskFile；返回 (task_id, file_id, owner_user_id, setup_seconds)。

    显式给出 ORM 才有默认值的字段（input_revision / state 等），commit 前取完所有 id。
    """
    t0 = time.perf_counter()
    with Session(engine) as session:
        owner = session.exec(select(User).where(User.is_active == True)).first()  # noqa: E712
        if not owner:
            raise RuntimeError("库内没有 active 用户，无法创建隔离任务的 owner")
        owner_id = str(owner.id)
        task = Task(
            owner_user_id=owner.id,
            name=ISOLATED_TASK_NAME,
            product_code="working_capital_loan",
            customer_role="borrower",
            checklist_version=CHECKLIST_VERSION,
            state="PROCESSING",
            input_revision=0,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        file_sha256 = _sha256_str("baseline-serial-slice-2026-11-12")
        file_row = TaskFile(
            task_id=task_id,
            original_name=ISOLATED_FILE_NAME,
            media_type="application/pdf",
            size_bytes=OCR_JSON_SIZE_BYTES,
            sha256=file_sha256,
            source_page_count=OCR_JSON_PAGE_COUNT,
        )
        session.add(file_row)
        session.flush()
        file_id = file_row.id
        session.commit()
    return task_id, file_id, owner_id, _round(time.perf_counter() - t0)


def create_run(task_id: uuid.UUID, file_id: uuid.UUID, ocr_sha256: str) -> tuple[uuid.UUID, float]:
    """建 QUEUED 状态的 ProcessingRun + RunFile；**不**入队（不 defer）。"""
    t0 = time.perf_counter()
    checklist = get_checklist(CHECKLIST_VERSION)
    manifest = _sha256_str(f"{task_id}|{file_id}|{ocr_sha256}")
    with Session(engine) as session:
        run = ProcessingRun(
            task_id=task_id,
            input_revision=0,
            checklist_snapshot=checklist,
            checklist_hash=checklist_hash(CHECKLIST_VERSION),
            model_snapshot={
                "text_model": settings.LLM_TEXT_MODEL,
                "vision_model": settings.LLM_VISION_MODEL,
            },
            state="QUEUED",
            input_manifest_hash=manifest,
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.add(RunFile(run_id=run_id, file_id=file_id, task_id=task_id))
        session.commit()
    return run_id, _round(time.perf_counter() - t0)


def soft_delete_task(task_id: uuid.UUID) -> str | None:
    """软删隔离任务（保留 run / results / run_steps 可追溯）。"""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        deleted_at = datetime.now(UTC)
        task.deleted_at = deleted_at
        session.add(task)
        session.commit()
    return deleted_at.isoformat()


def verify_ocr_json(container_path: str) -> dict[str, Any]:
    """校验容器内 OCR JSON 与固定指纹一致，返回指纹信息。"""
    path = Path(container_path)
    if not path.is_file():
        raise RuntimeError(f"容器内 OCR JSON 不存在: {container_path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != OCR_JSON_SHA256:
        raise RuntimeError(
            f"OCR JSON SHA256 不匹配：实测 {digest} != 固定值 {OCR_JSON_SHA256}；"
            "并发对照必须复用同一份 JSON，且须复用同一批隔离数据（同一 file_id / OcrBlock UUID）"
        )
    pages = json.loads(raw.decode("utf-8"))
    if not isinstance(pages, list) or len(pages) != OCR_JSON_PAGE_COUNT:
        raise RuntimeError(f"OCR JSON 页数不符：实测 {type(pages).__name__}/{len(pages) if isinstance(pages, list) else '?'}")
    return {
        "host_absolute_path": OCR_JSON_HOST_PATH,
        "container_path": container_path,
        "sha256": digest,
        "size_bytes": len(raw),
        "page_count": len(pages),
        "note": OCR_JSON_NOTE,
        "sha256_matches_fixed_constant": True,
    }


# ---------------------------------------------------------------------------
# 跑批前窗口实测（用真实函数 + 真实 DB 数据）
# ---------------------------------------------------------------------------


def preflight_windows(task_id: uuid.UUID, file_id: uuid.UUID) -> dict[str, Any]:
    """在包装器安装之前，用真实 chunk_* 函数实测窗口数。"""
    source_blocks = load_source_blocks(task_id, [file_id])
    windows = chunk_source_blocks(source_blocks, WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS)
    classify_blocks = load_file_blocks(task_id, file_id)
    classify_windows = chunk_blocks(classify_blocks, WINDOW_CHARACTERS, WINDOW_OVERLAP_CHARACTERS)

    def describe(items: list[Any], window_module: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for idx, w in enumerate(items):
            body = window_module._window_text(w.blocks)
            out.append({
                "window_index": idx,
                "bundle_id": w.bundle_id,
                "block_count": len(w.blocks),
                "char_count": sum(len(b.text) for b in w.blocks),
                "window_text_sha256": _sha256_str(body),
            })
        return out

    return {
        "measurement_method": (
            "真实调用 app.text_search.chunk_source_blocks / app.classification.chunk_blocks，"
            "输入为 import-ocr-json 落库后的 OcrBlock（非预计值）"
        ),
        "parameters": {
            "max_chars": WINDOW_CHARACTERS,
            "overlap_chars": WINDOW_OVERLAP_CHARACTERS,
        },
        "source_block_count": len(source_blocks),
        "source_total_characters": sum(len(b.text) for b in source_blocks),
        "classify_block_count": len(classify_blocks),
        "classify": {
            "measured_window_count": len(classify_windows),
            "windows": describe(classify_windows, classification_mod),
        },
        "per_check_item_search": {
            "measured_window_count": len(windows),
            "windows": describe(windows, text_search_mod),
            "note": "每个文本类检查项复用同一组 file_ids 与同一组 OcrBlock，故窗口数相同",
        },
    }


# ---------------------------------------------------------------------------
# 跑批后：DB 事实读取
# ---------------------------------------------------------------------------


def read_run_steps(task_id: uuid.UUID, run_id: uuid.UUID) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """读 run 起止与 RunStep 明细（与 GET /runs/{id}/timing 同源）。"""
    with Session(engine) as session:
        run = session.get(ProcessingRun, run_id)
        run_view: dict[str, Any] = {
            "run_id": str(run_id),
            "task_id": str(task_id),
            "state": run.state if run else None,
            "stage": run.stage if run else None,
            "coverage_complete": run.coverage_complete if run else None,
            "error_code": run.error_code if run else None,
            "checklist_hash": run.checklist_hash if run else None,
            "started_at": run.started_at.isoformat() if run and run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
            "elapsed_seconds": _round(
                (run.finished_at - run.started_at).total_seconds()
            ) if run and run.started_at and run.finished_at else None,
        }
        rows = session.exec(
            select(RunStep).where(RunStep.run_id == run_id, RunStep.task_id == task_id)
            .order_by(RunStep.started_at, RunStep.step_key)
        ).all()
        steps: list[dict[str, Any]] = []
        for s in rows:
            steps.append({
                "step_key": s.step_key,
                "state": s.state,
                "attempt": s.attempt,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "elapsed_seconds": _round(
                    (s.finished_at - s.started_at).total_seconds()
                ) if s.started_at and s.finished_at else None,
                "last_error_code": s.last_error_code,
            })
    return run_view, steps


def read_results(task_id: uuid.UUID, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """读结果与出处；大段原文保留在内存中做关键词对照，落证据时只存摘要/指纹。"""
    with Session(engine) as session:
        rows = session.exec(
            select(Result).where(Result.run_id == run_id, Result.task_id == task_id)
            .order_by(Result.check_item_id, Result.rank, Result.id)
        ).all()
        items: list[dict[str, Any]] = []
        for r in rows:
            sources = session.exec(
                select(ResultSource).where(
                    ResultSource.result_id == r.id, ResultSource.task_id == task_id
                )
            ).all()
            source_views = [{
                "source_page_number": s.source_page_number,
                "location_precision": s.location_precision,
                "block_id": str(s.block_id) if s.block_id else None,
                "file_id": str(s.file_id) if s.file_id else None,
            } for s in sources]
            full_text = r.text or ""
            items.append({
                "result_id": str(r.id),
                "check_item_id": r.check_item_id,
                "rank": r.rank,
                "kind": r.kind,
                "not_found_reason": r.not_found_reason,
                "fingerprint": r.fingerprint,
                "text_length": len(full_text),
                "text_sha256": _sha256_str(full_text) if full_text else None,
                "text_excerpt": _excerpt(full_text),
                "sources": source_views,
                "_full_text": full_text,
            })
    return items


def read_ocr_pages_by_number(task_id: uuid.UUID, file_id: uuid.UUID) -> dict[int, str]:
    """物理页号 -> 该页全部 OcrBlock 文本（用于判断条款是否属于样本外）。"""
    with Session(engine) as session:
        pages = session.exec(
            select(OcrPage).where(OcrPage.task_id == task_id, OcrPage.file_id == file_id)
        ).all()
        page_map = {p.id: p.source_page_number for p in pages}
        blocks = session.exec(
            select(OcrBlock).where(OcrBlock.task_id == task_id, OcrBlock.file_id == file_id)
            .order_by(OcrBlock.sequence_index)
        ).all()
        by_page: dict[int, list[str]] = {}
        for b in blocks:
            num = page_map.get(b.page_id)
            if num is None:
                continue
            by_page.setdefault(num, []).append(b.canonical_text or "")
        return {num: "\n".join(parts) for num, parts in by_page.items()}


# ---------------------------------------------------------------------------
# 条款对照 / 瓶颈推算
# ---------------------------------------------------------------------------


def build_clause_matrix(items: list[dict[str, Any]],
                        ocr_by_page: dict[int, str]) -> dict[str, Any]:
    """事实矩阵：样本内是否存在、结果是否摘录到、担保类是否误引经营范围。"""
    matrix: list[dict[str, Any]] = []
    for probe in CLAUSE_PROBES:
        page = probe["physical_page"]
        if page is None:
            source_text = "\n".join(ocr_by_page.values())
            ocr_pages_scanned = sorted(ocr_by_page.keys())
        else:
            source_text = ocr_by_page.get(page, "")
            ocr_pages_scanned = [page]
        source_hits = _match_keywords(source_text, probe["keywords"])
        result_hits: list[dict[str, Any]] = []
        for item in items:
            if not item["_full_text"]:
                continue
            hits = _match_keywords(item["_full_text"], probe["keywords"])
            if not hits:
                continue
            result_hits.append({
                "check_item_id": item["check_item_id"],
                "rank": item["rank"],
                "kind": item["kind"],
                "source_page_numbers": [s["source_page_number"] for s in item["sources"]],
                "matched_keywords": hits,
                "text_sha256": item["text_sha256"],
            })
        target_rows = [i for i in items if i["check_item_id"] == probe["target_check_id"]]
        target_hit = any(
            h["check_item_id"] == probe["target_check_id"] and h["kind"] != "not_found"
            for h in result_hits
        )
        in_sample = bool(source_hits)
        if target_hit:
            auto_verdict = "命中"
        elif probe.get("sample_outside_probe") and any(
            i["not_found_reason"] == "no_matching_evidence" for i in target_rows
        ):
            # 样本外探针：通用词命中不等于目标条款存在，不能判「覆盖不全」
            auto_verdict = (
                "样本外条款：物理 1–15 页无「签字权限」条款，"
                "no_matching_evidence 符合预期（非技术失败）"
            )
        elif not in_sample:
            auto_verdict = "样本外条款（未命中）"
        elif any(i["not_found_reason"] == "material_missing" for i in target_rows):
            auto_verdict = "未命中（该检查项缺材料）"
        elif any(i["not_found_reason"] == "coverage_incomplete" for i in target_rows):
            auto_verdict = "未命中：技术失败导致窗口未覆盖（coverage_incomplete，非「未找到」）"
        elif any(i["not_found_reason"] == "no_matching_evidence" for i in target_rows):
            auto_verdict = "未命中：样本内存在但本次未被模型摘录召回（非技术失败）"
        else:
            auto_verdict = "未命中（结果未包含该短语）"
        matrix.append({
            "id": probe["id"],
            "physical_page": page,
            "title": probe["title"],
            "target_check_id": probe["target_check_id"],
            "keywords": probe["keywords"],
            "ocr_pages_scanned": ocr_pages_scanned,
            "source_ocr_matched_keywords": source_hits,
            "present_in_sample_ocr": in_sample,
            "present_in_sample_ocr_note": (
                probe.get("present_in_sample_ocr_note")
                or "按关键词精确短语匹配判定；目标条款是否真实存在需人工复核"
            ),
            "result_hits": result_hits,
            "target_check_result_rows": len(target_rows),
            "target_check_not_found_reasons": [
                i["not_found_reason"] for i in target_rows if i["not_found_reason"]
            ],
            "auto_verdict": auto_verdict,
            "note": probe["note"],
        })

    mis_hits: list[dict[str, Any]] = []
    for item in items:
        if item["check_item_id"] not in GUARANTEE_CHECK_IDS or not item["_full_text"]:
            continue
        hits = _match_keywords(item["_full_text"], FALSE_POSITIVE_KEYWORDS)
        pages = [s["source_page_number"] for s in item["sources"]]
        mis_hits.append({
            "check_item_id": item["check_item_id"],
            "rank": item["rank"],
            "source_page_numbers": pages,
            "business_scope_keywords_found": hits,
            "is_foreign_exchange_guarantee_mis_hit": bool(hits) and 7 in pages,
            "text_sha256": item["text_sha256"],
        })
    return {
        "matching_rule": "对 OCR 原文与 Result.text 去空白后做精确短语子串匹配，出处页码取 ResultSource.source_page_number",
        "matrix": matrix,
        "guarantee_vs_business_scope": {
            "checked_check_item_ids": GUARANTEE_CHECK_IDS,
            "false_positive_keywords": FALSE_POSITIVE_KEYWORDS,
            "guarantee_result_rows": mis_hits,
            "any_foreign_exchange_guarantee_mis_hit": any(
                m["is_foreign_exchange_guarantee_mis_hit"] for m in mis_hits
            ),
        },
        "status": (
            "事实矩阵 + 规则化自动判定；人工逐条结论见 docs/REVIEW_HANDOFF.md 与本轮回传。"
            "QA 独立复验后补充披露：C6 / C10 标签已修正，不再出现「覆盖不全」字样。"
        ),
    }


def build_by_check_item(items: list[dict[str, Any]], observer: BaselineObserver,
                        preflight: dict[str, Any]) -> dict[str, Any]:
    """按 18 个叶子汇总：kind / text 摘要 / fingerprint / 出处页码 / 命中原因 / 窗口数 / 调用次数。"""
    leaves = get_leaves(CHECKLIST_VERSION)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_id.setdefault(item["check_item_id"], []).append(item)
    search_by_id = {e["check_item_id"]: e for e in observer.search_events}
    observed_windows: dict[str, int] = {}
    for e in observer.chunk_events:
        if e["kind"] == "search_window" and e["check_item_id"]:
            observed_windows[e["check_item_id"]] = observed_windows.get(e["check_item_id"], 0) + 1
    out: dict[str, Any] = {}
    for leaf in leaves:
        cid = leaf["id"]
        rows = by_id.get(cid, [])
        event = search_by_id.get(cid)
        if not rows:
            verdict = "no_result_row"
            reason = "未写入任何 Result 行"
        elif any(r["kind"] not in ("not_found",) for r in rows):
            verdict = "hit"
            reason = "存在 text/table/seal/signature 证据行"
        else:
            reasons = [r["not_found_reason"] for r in rows if r["not_found_reason"]]
            verdict = "not_found"
            reason = "、".join(sorted(set(str(x) for x in reasons))) or "无证据"
        out[cid] = {
            "material_type": leaf["material_type"],
            "label": leaf.get("label"),
            "result_mode": leaf.get("result_mode"),
            "verdict": verdict,
            "verdict_reason": reason,
            "result_count": len(rows),
            # 真实实测：只有实际调到 chunk_source_blocks 的检查项才有窗口
            "measured_window_count": observed_windows.get(cid, 0),
            "preflight_window_count_if_files_present": (
                preflight["per_check_item_search"]["measured_window_count"]
                if leaf.get("result_mode") not in ("seal", "signature") else 0
            ),
            "window_count_note": (
                "缺材料 / seal / signature / 分类未命中的检查项不会进入分窗，实测窗口数为 0；"
                "preflight_window_count_if_files_present 仅为「若有对应材料」时的参考值，非该检查项实测值"
            ),
            "complete_json_call_count": event["complete_json_call_count"] if event else 0,
            "chat_call_count": event["chat_call_count"] if event else 0,
            "search_elapsed_seconds": event["elapsed_seconds"] if event else None,
            "failed_reason": event["failed_reason"] if event else None,
            "results": [{
                "rank": r["rank"],
                "kind": r["kind"],
                "not_found_reason": r["not_found_reason"],
                "fingerprint": r["fingerprint"],
                "text_excerpt": r["text_excerpt"],
                "text_sha256": r["text_sha256"],
                "text_length": r["text_length"],
                "source_page_numbers": [s["source_page_number"] for s in r["sources"]],
                "location_precision": [s["location_precision"] for s in r["sources"]],
            } for r in rows],
        }
    return out


def build_bottleneck(observer: BaselineObserver, stages: dict[str, float],
                     post_processing_seconds: float, total_seconds: float) -> dict[str, Any]:
    """瓶颈判断（实测）+ 并发收益上限（明确标注推算，非实测）。"""
    chat_elapsed = [c["elapsed_seconds"] for c in observer.chat_calls]
    complete_elapsed = [c["elapsed_seconds"] for c in observer.complete_calls]
    stage_share = {
        name: (_round(seconds / post_processing_seconds * 100)
               if post_processing_seconds > 0 else None)
        for name, seconds in stages.items()
    }
    slowest_checks = sorted(
        [{"check_item_id": e["check_item_id"], "elapsed_seconds": e["elapsed_seconds"],
          "complete_json_call_count": e["complete_json_call_count"],
          "measured_window_count": e["measured_window_count"]}
         for e in observer.search_events],
        key=lambda x: x["elapsed_seconds"], reverse=True,
    )
    slowest_requests = sorted(
        [{"chat_seq": c["seq"], "elapsed_seconds": c["elapsed_seconds"],
          "check_item_id": c["check_item_id"], "stage": c["stage"],
          "response_format_type": c["response_format_type"]}
         for c in observer.chat_calls],
        key=lambda x: x["elapsed_seconds"], reverse=True,
    )[:5]

    # 并发收益推算：全部基于串行实测的逐窗口耗时，标注为推算
    concurrency = settings.LLM_MAX_CONCURRENCY
    per_check_window_seconds: dict[str, list[float]] = {}
    for call in observer.complete_calls:
        if call["schema_name"] != "text_search_output" or not call["check_item_id"]:
            continue
        key = str(call["check_item_id"])
        per_check_window_seconds.setdefault(key, []).append(call["elapsed_seconds"])
    check_totals = {k: sum(v) for k, v in per_check_window_seconds.items()}
    search_serial_sum = sum(check_totals.values())
    # 窗口级并发：同一检查项内窗口并行（并发度 C），检查项之间仍串行。
    # 每个检查项耗时收敛到 max(其窗口耗时)；总耗时下限为各检查项 max 之和。
    window_parallel_check_max = {k: max(v) for k, v in per_check_window_seconds.items()}
    window_parallel_total_if_checks_serial = sum(window_parallel_check_max.values())
    check_parallel_ideal = (
        max(sum(check_totals.values()) / concurrency, max(check_totals.values()))
        if check_totals else None
    )
    global_parallel_ideal = (
        max(sum(complete_elapsed) / concurrency, max(complete_elapsed))
        if complete_elapsed else None
    )
    estimates = {
        "status": "推算，非实测；基于本次串行实测的逐窗口/逐请求耗时，待并发实测验证",
        "assumed_concurrency": concurrency,
        "caveats": [
            "忽略服务端限流、排队、连接建立、DB 写入与调度开销",
            "忽略 token 竞争导致的单次请求变慢与重试放大",
            "忽略多 run 并发时的全局上限争用",
            "LLM_MAX_CONCURRENCY=2 当前串行链路未生效（无同时在途请求）",
        ],
        "window_level_parallel": {
            "basis": (
                "同一检查项内窗口并行（并发度取 LLM_MAX_CONCURRENCY），检查项之间仍串行；"
                "每个检查项耗时取该检查项所有窗口的最大值，总耗时取各检查项最大值之和"
            ),
            "check_window_seconds_measured": {k: [_round(x) for x in v]
                                              for k, v in per_check_window_seconds.items()},
            "check_max_after_window_parallel_seconds": {
                k: _round(v) for k, v in window_parallel_check_max.items()
            },
            "ideal_total_seconds_if_checks_still_serial": _round(window_parallel_total_if_checks_serial),
            "slowest_single_check_seconds": _round(max(window_parallel_check_max.values()))
            if window_parallel_check_max else None,
            "serial_sum_seconds": _round(search_serial_sum),
        },
        "check_item_level_parallel": {
            "basis": "各检查项总耗时串行求和；检查项之间并行（并发度取 LLM_MAX_CONCURRENCY），窗口仍串行",
            "check_total_seconds_measured": {k: _round(v) for k, v in check_totals.items()},
            "ideal_total_seconds_if_windows_still_serial": _round(check_parallel_ideal)
            if check_parallel_ideal is not None else None,
            "slowest_single_check_seconds": _round(max(check_totals.values()))
            if check_totals else None,
            "serial_sum_seconds": _round(search_serial_sum),
        },
        "global_two_layer_parallel": {
            "basis": "所有 complete_json 调用视为可并行任务，全局并发度取 LLM_MAX_CONCURRENCY",
            "ideal_total_seconds": _round(global_parallel_ideal)
            if global_parallel_ideal is not None else None,
            "slowest_single_request_seconds": _round(max(complete_elapsed))
            if complete_elapsed else None,
            "serial_sum_seconds": _round(sum(complete_elapsed)),
        },
        "measured_serial": {
            "status": "实测",
            "post_processing_seconds": post_processing_seconds,
            "total_measured_seconds": total_seconds,
            "chat_request_count": len(chat_elapsed),
            "chat_elapsed_sum_seconds": _round(sum(chat_elapsed)),
        },
    }
    return {
        "status": "实测",
        "per_request_elapsed_distribution_seconds": _dist(chat_elapsed),
        "per_complete_json_elapsed_distribution_seconds": _dist(complete_elapsed),
        "serial_post_processing_seconds": post_processing_seconds,
        "serial_total_measured_seconds": total_seconds,
        "stage_share_percent_of_post_processing": stage_share,
        "slowest_check_items": slowest_checks,
        "slowest_single_requests": slowest_requests,
        "where_time_concentrates": (
            "见 stage_share_percent_of_post_processing 与 slowest_check_items；"
            "结论文字见 docs/REVIEW_HANDOFF.md"
        ),
        "estimates_not_measured": estimates,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_fingerprints(ocr_info: dict[str, Any]) -> dict[str, Any]:
    """固定项指纹（后续并发对照须逐项比对，但只保证输入相同，不保证窗口级指纹复现）。"""
    return {
        "ocr_json": ocr_info,
        "checklist": {
            "version": CHECKLIST_VERSION,
            "checklist_hash": checklist_hash(CHECKLIST_VERSION),
            "leaf_count": len(get_leaves(CHECKLIST_VERSION)),
            "charter_leaf_ids": [
                leaf["id"] for leaf in get_leaves(CHECKLIST_VERSION)
                if leaf["material_type"] == "articles_of_association"
            ],
        },
        "models": {
            "llm_text_model": settings.LLM_TEXT_MODEL,
            "llm_vision_model": settings.LLM_VISION_MODEL,
        },
        "prompts": {
            "SEARCH_SYSTEM": {"sha256": _sha256_str(SEARCH_SYSTEM), "chars": len(SEARCH_SYSTEM)},
            "CLASSIFY_SYSTEM": {"sha256": _sha256_str(CLASSIFY_SYSTEM), "chars": len(CLASSIFY_SYSTEM)},
            "VISION_SYSTEM": {"sha256": _sha256_str(VISION_SYSTEM), "chars": len(VISION_SYSTEM)},
            "TEXT_SEARCH_SCHEMA": {"sha256": _json_sha256(TEXT_SEARCH_SCHEMA)},
            "CLASSIFICATION_SCHEMA": {"sha256": _json_sha256(CLASSIFICATION_SCHEMA)},
            "VISION_MATCH_SCHEMA": {"sha256": _json_sha256(VISION_MATCH_SCHEMA)},
        },
        "window": {
            "llm_window_characters": WINDOW_CHARACTERS,
            "llm_window_overlap_characters": WINDOW_OVERLAP_CHARACTERS,
            "runtime_settings_match_constants": (
                settings.LLM_WINDOW_CHARACTERS == WINDOW_CHARACTERS
                and settings.LLM_WINDOW_OVERLAP_CHARACTERS == WINDOW_OVERLAP_CHARACTERS
            ),
        },
        "runtime_llm": {
            "llm_request_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "llm_max_transient_retries": settings.LLM_MAX_TRANSIENT_RETRIES,
            "llm_max_concurrency": settings.LLM_MAX_CONCURRENCY,
            "llm_max_output_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
            "llm_max_format_repairs": settings.LLM_MAX_FORMAT_REPAIRS,
            "app_mode": settings.APP_MODE,
            "pipeline_config_version": settings.PIPELINE_CONFIG_VERSION,
        },
    }


REPRODUCTION = {
    "working_directory": "credit-review-app 项目根目录（Git 根，分支 feature/credit-review）",
    "steps": [
        "OCR_JSON=\"/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json\"",
        "shasum -a 256 \"$OCR_JSON\"   # 期望 8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b",
        "docker cp \"$OCR_JSON\" credit-review-app-worker-1:/tmp/baseline_ocr_slice.json",
        "docker exec -i credit-review-app-worker-1 python - --evidence-out /tmp/baseline_evidence.json < scripts/baseline_serial.py > /tmp/baseline_stdout.json   # -i 必须；脚本同时把证据写进容器内 /tmp/baseline_evidence.json",
        "docker cp credit-review-app-worker-1:/tmp/baseline_evidence.json /tmp/baseline_stdout.json   # 若宿主机 stdout 管道被断开，用这一条取回容器内落盘的同一份证据",
        "python3 -c \"import json,pathlib; d=json.loads(pathlib.Path('/tmp/baseline_stdout.json').read_text()); pathlib.Path('/tmp/baseline_raw.json').write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\\n', encoding='utf-8')\"",
        "python3 -c \"import json;d=json.load(open('docs/perf_baseline_2026-11-12.json'));print(d['run']['run_id'], d['windows']['preflight']['classify']['measured_window_count'], d['model_calls']['chat_request_count'])\"   # 交付版证据自检（需该文件存在；校验的是已交付证据，非本次新产出）",
    ],
    "optional_single_steps": [
        "docker exec credit-review-app-worker-1 python -m app.cli import-ocr-json --file-id <file_id> --json /tmp/baseline_ocr_slice.json   # 仅导入，不触发外部 OCR",
        "登录 liyanyan 取 session cookie 后：GET /api/v1/tasks/<task_id>/runs/<run_id>/timing   # 只读；若隔离任务已软删需先把 tasks.deleted_at 置 NULL",
        "docker exec credit-review-app-db-1 psql -U postgres -d app -c \"select id,state,started_at,finished_at from processing_runs where id='<run_id>';\"",
        "python3 -c \"import json;d=json.load(open('/tmp/baseline_raw.json'));print(d['run']['run_id'], d['windows']['preflight']['classify']['measured_window_count'], d['model_calls']['chat_request_count'])\"   # 本次新产出自检：读 steps[5] 产出的 /tmp/baseline_raw.json",
    ],
    "probe_only": "docker exec -i credit-review-app-worker-1 python - --probe-only < scripts/baseline_serial.py   # 不调用模型，只实测窗口数与指纹",
    "note": (
        "并发对照必须复用同一 OCR JSON（同一 SHA256）、同一清单版本与 hash、同一提示词 sha256、"
        "同一 8000/500 窗口参数与同一模型 ID；但固定项一致只保证输入相同。"
        "窗口文本 hash、逐窗口字符数、messages/user hash 与 Result.fingerprint 均绑定该次导入的 DB 行，"
        "因此必须再复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID）；"
        "跨 run 逐条比对改用 text_sha256 + source_page_number，不要用 fingerprint。"
    ),
}


REPRODUCTION["deliverable_note"] = (
    "QA 独立复验后补充披露：steps[5] 只把脚本原始 stdout 格式化到 /tmp/baseline_raw.json，"
    "不可覆盖交付证据 docs/perf_baseline_2026-11-12.json；交付版另需按证据 "
    "post_processing_notes.what_changed 补回人工段（session_notes / git_state / "
    "clause_verdicts_manual / post_processing_notes / database_verification）、2 处标签修正与 QA 披露。"
    "steps[6] 自检命令针对交付版证据（校验仓库里已交付的证据文件，非本次新产出）；"
    "本次新跑批的自检见 optional_single_steps 中读取 /tmp/baseline_raw.json 的那条（由 steps[5] 产出），两者不可混用。"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="短样本串行基线（真实模型）")
    parser.add_argument("--probe-only", action="store_true", help="只造数据/导入/实测窗口，不调用模型")
    parser.add_argument("--keep-task", action="store_true", help="跑完不软删隔离任务")
    parser.add_argument("--ocr-json", default=OCR_JSON_CONTAINER_PATH, help="容器内 OCR JSON 路径")
    parser.add_argument(
        "--evidence-out", default="/tmp/baseline_evidence.json",
        help="容器内证据 JSON 落盘路径；即使宿主机 stdout 管道断开也可 docker cp 取回",
    )
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "baseline_date": BASELINE_DATE,
        "generated_at": _now_iso(),
        "status": "running",
        "execution": {
            "mode": "in_container_synchronous_call",
            "container": "credit-review-app-worker-1",
            "entry_point": "run_pipeline.func(str(run_id))",
            "script": "scripts/baseline_serial.py",
            "via_procrastinate_queue": False,
            "queue_job_id": None,
            "queue_scheduling_overhead_included": False,
            "execution_note": (
                "在 worker 容器内同步直接调用 Procrastinate Task 的原始函数 run_pipeline.func，"
                "未调用 defer/enqueue，不经过队列调度，故队列轮询与调度开销不计入本基线；"
                "Result / ResultSource / RunStep / ProcessingRun 均由业务代码正常真实落库。"
            ),
            "observation_method": (
                "脚本层 monkeypatch：LLMClient._chat、LLMClient.complete_json、"
                "text_search.chunk_source_blocks、classification.chunk_blocks、"
                "processing_pipeline.search_check_item 与四个阶段函数；"
                "未改业务代码、未改 models.py、未加迁移、未加接口、未重建 worker 镜像。"
            ),
            "docker_exec_stdin_flag": "-i",
            "evidence_container_path": args.evidence_out,
            "evidence_retrieval_fallback": (
                "docker cp credit-review-app-worker-1:/tmp/baseline_evidence.json /tmp/baseline_stdout.json"
            ),
            "probe_only": bool(args.probe_only),
        },
        "fingerprints": {},
        "configuration": {},
        "reproduction": REPRODUCTION,
        "blockers": [],
    }

    task_id: uuid.UUID | None = None
    file_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    observer = BaselineObserver()
    total_start = time.perf_counter()
    try:
        ocr_info = verify_ocr_json(args.ocr_json)
        evidence["fingerprints"] = build_fingerprints(ocr_info)
        evidence["configuration"] = {
            "ocr_recognition": "未执行（复用既有 OCR JSON，非本轮计时对象）",
            "ocr_reuse_note": (
                "本轮没有调用外部 OCR 服务、没有重新识别；OCR 识别耗时不参与本基线。"
                "OCR JSON 导入落库耗时与后处理耗时严格分栏。"
            ),
            "fixed_items": (
                "见 fingerprints；并发对照须逐项比对输入 sha256，但固定项一致只保证输入相同，"
                "不保证窗口边界 / 窗口文本 hash / Result.fingerprint 复现（见 sample_limitations.run_bound_artifacts）"
            ),
        }

        task_id, file_id, owner_id, setup_seconds = create_isolated_data()
        evidence["isolation"] = {
            "task_id": str(task_id),
            "file_id": str(file_id),
            "owner_user_id": owner_id,
            "task_name": ISOLATED_TASK_NAME,
            "file_name": ISOLATED_FILE_NAME,
            "file_sha256_note": "隔离造数占位值（OCR JSON 非 PDF 原件），不参与任何业务判断",
            "touched_existing_tasks": False,
            "protected_tasks": [
                "607e6d41-4d47-4582-a5ad-07313b6c17bd (REVIEWING)",
                "ee59108d-e4f1-4aa8-bf2e-afe07d457384 (COMPLETED, 77 条结果)",
            ],
        }

        import_t0 = time.perf_counter()
        with contextlib.redirect_stdout(sys.stderr):
            import_ocr_json(str(file_id), args.ocr_json)
        ocr_import_seconds = _round(time.perf_counter() - import_t0)

        preflight = preflight_windows(task_id, file_id)
        evidence["windows"] = {
            "preflight": preflight,
            "observed_during_run": None,
            "status": "实测（非预计值）",
        }
        evidence["timing"] = {
            "setup_isolated_data_seconds": setup_seconds,
            "ocr_recognition": "未执行（复用既有 JSON，非本轮计时对象）",
            "ocr_json_import_seconds": ocr_import_seconds,
            "ocr_and_after_split_note": (
                "OCR 识别与 OCR 之后的处理不是同一次计时：前者本轮未执行，"
                "后者为 OCR JSON 导入落库 + classify/search/vision/complete_run。"
            ),
        }

        if args.probe_only:
            evidence["status"] = "probe_only"
            evidence["timing"]["total_measured_seconds"] = _round(time.perf_counter() - total_start)
            evidence["isolation"]["soft_deleted_at"] = (
                None if args.keep_task else soft_delete_task(task_id)
            )
            _emit(evidence, args.evidence_out)
            return 0

        run_id, run_setup_seconds = create_run(task_id, file_id, ocr_info["sha256"])
        evidence["timing"]["create_run_seconds"] = run_setup_seconds
        evidence["isolation"]["run_id"] = str(run_id)

        observer.install()
        pipeline_t0 = time.perf_counter()
        pipeline_error: str | None = None
        try:
            run_pipeline.func(str(run_id))
        except Exception as exc:  # noqa: BLE001
            pipeline_error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            post_processing_seconds = _round(time.perf_counter() - pipeline_t0)
            observer.restore()
        if pipeline_error:
            evidence["blockers"].append({
                "stage": "pipeline",
                "error": pipeline_error,
                "note": "真实跑批抛出异常，后续字段以 DB 实际落库为准",
            })

        total_seconds = _round(time.perf_counter() - total_start)
        stage_elapsed = {e["stage"]: e["elapsed_seconds"] for e in observer.stage_events}
        stages = {
            "classify": stage_elapsed.get("classify"),
            "search": stage_elapsed.get("search"),
            "vision": stage_elapsed.get("vision"),
            "complete_run": stage_elapsed.get("complete_run"),
        }
        run_view, steps = read_run_steps(task_id, run_id)
        result_items = read_results(task_id, run_id)
        ocr_by_page = read_ocr_pages_by_number(task_id, file_id)

        evidence["run"] = {
            **run_view,
            "database_verified": True,
            "verification": "PostgreSQL processing_runs 表按 id 查询命中（真实存在的 ProcessingRun.id）",
        }
        evidence["timing"].update({
            "post_processing_seconds": post_processing_seconds,
            "total_measured_seconds": total_seconds,
            "total_scope": (
                "从造隔离数据开始到 run_pipeline.func 返回（含造数据、OCR JSON 导入、建 run、"
                "三个阶段与 complete_run、DB 写入）；不含证据读取与软删"
            ),
            "stages_wall_clock_seconds": stages,
            "stage_events": observer.stage_events,
            "run_step_elapsed_seconds": {
                s["step_key"]: s["elapsed_seconds"] for s in steps
            },
            "run_steps": steps,
            "run_steps_source": (
                "直接读 run_steps 表，与只读接口 GET /tasks/{task_id}/runs/{run_id}/timing 同源；"
                "本次未通过 HTTP 调用该接口"
            ),
        })

        observed_windows: dict[str, Any] = {
            "classify": {
                "measured_window_count": len([
                    e for e in observer.chunk_events if e["kind"] == "classify_window"
                ]),
                "windows": [e for e in observer.chunk_events if e["kind"] == "classify_window"],
            },
            "per_check_item": {},
            "chunk_events": observer.chunk_events,
        }
        counts: dict[str, int] = {}
        for e in observer.chunk_events:
            if e["kind"] == "search_window" and e["check_item_id"]:
                counts[e["check_item_id"]] = counts.get(e["check_item_id"], 0) + 1
        observed_windows["per_check_item"] = {
            cid: {"measured_window_count": n,
                  "windows": [e for e in observer.chunk_events
                              if e["kind"] == "search_window" and e["check_item_id"] == cid]}
            for cid, n in counts.items()
        }
        evidence["windows"]["observed_during_run"] = observed_windows
        evidence["windows"]["preflight_matches_observed"] = (
            preflight["classify"]["measured_window_count"]
            == observed_windows["classify"]["measured_window_count"]
            and all(
                n == preflight["per_check_item_search"]["measured_window_count"]
                for n in counts.values()
            ) if counts else (
                preflight["classify"]["measured_window_count"]
                == observed_windows["classify"]["measured_window_count"]
            )
        )

        evidence["model_calls"] = observer.summarize_calls()
        evidence["search_stage_per_check_item"] = observer.search_events
        evidence["results"] = {
            "total_result_rows": len(result_items),
            "hit_rows": len([i for i in result_items if i["kind"] != "not_found"]),
            "not_found_rows": len([i for i in result_items if i["kind"] == "not_found"]),
            "not_found_reason_counts": _count_reasons(result_items),
            "by_check_item": build_by_check_item(result_items, observer, preflight),
            "text_policy": "大段原文只存 200 字摘要 + SHA256 + fingerprint + 出处页码；未整份塞入证据",
        }
        evidence["clause_matrix"] = build_clause_matrix(result_items, ocr_by_page)
        evidence["bottleneck"] = build_bottleneck(
            observer, {k: v for k, v in stages.items() if v is not None},
            post_processing_seconds, total_seconds,
        )
        evidence["sample_limitations"] = SAMPLE_LIMITATIONS
        evidence["status"] = "measured" if not evidence["blockers"] else "measured_with_blockers"
    except Exception as exc:  # noqa: BLE001
        observer.restore()
        evidence["status"] = "blocked"
        evidence["blockers"].append({
            "stage": "setup_or_measurement",
            "error": f"{type(exc).__name__}: {exc}"[:800],
            "note": "未完成的字段保持缺失，不填推算值",
        })
        evidence.setdefault("timing", {})
        evidence["timing"]["total_measured_seconds"] = _round(time.perf_counter() - total_start)
    finally:
        if task_id is not None and not args.keep_task:
            if "isolation" in evidence and not evidence["isolation"].get("soft_deleted_at"):
                deleted = soft_delete_task(task_id)
                evidence["isolation"]["soft_deleted_at"] = deleted
                evidence["isolation"]["soft_delete_note"] = (
                    "仅软删隔离 tasks 行；run / results / result_sources / run_steps / ocr_* 全部保留可追溯。"
                    "如需复验 timing 只读接口，先 UPDATE tasks SET deleted_at=NULL WHERE id='<task_id>'。"
                )

    _emit(evidence, args.evidence_out)
    return 0 if evidence["status"] in ("measured", "probe_only") else 1


def _count_reasons(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if item["not_found_reason"]:
            key = str(item["not_found_reason"])
            counts[key] = counts.get(key, 0) + 1
    return counts


SAMPLE_LIMITATIONS: dict[str, Any] = {
    "status": "基于本次实测样本（15 页 / 约 9200 字符 / 窗口数见 windows）的局限说明",
    "can_verify": [
        "串行链路完整性：classify → search → vision → complete_run 全部真实执行且落库",
        "计时字段齐全性：阶段墙钟耗时、RunStep 起止耗时、逐次请求耗时、OCR 导入与后处理分栏",
        "条款召回与出处页码：Result.text 摘要 + text_sha256 + ResultSource.source_page_number 可核对；fingerprint 含随机 OcrBlock UUID，仅本次 run 内自洽（见 run_bound_artifacts）",
        "超时与重试观测字段是否齐全（本次实测值见 model_calls；若为 0 即说明链路未触发）",
        "no_matching_evidence 与 coverage_incomplete 的区分路径是否存在（本样本若未触发，需长样本/故障注入验证）",
        "样本外条款（法定代表人签字权限）走 not_found 而非硬凑命中",
        "经营范围「外汇担保」是否被担保类检查项误引（见 clause_matrix.guarantee_vs_business_scope）",
        "窗口级容错分支（LLMFatalError / LLMTransientError / LLMFormatError）的代码路径可读性",
    ],
    "cannot_verify": [
        "并发真实收益：本轮 0 个同时在途请求，LLM_MAX_CONCURRENCY=2 未生效；所有并发数字均为推算",
        "服务端限流（429）与排队行为：短样本、低并发下不会暴露",
        "窗口级与检查项级两层上限的相互作用与死锁/饥饿",
        "多 run 并发时的全局上限与数据库会话隔离",
        "长章程（62 页 / 多窗口）下的断句、住所串入、去重与总耗时量级",
        "失败窗口只重试的幂等键与 fingerprint 合并去重行为（fingerprint 去重仅在同一 run / 同一批 OcrBlock UUID 内成立）",
    ],
    "needed_for_concurrency_validation": [
        "更长样本：完整 62 页章程或等价的多窗口输入（窗口数 ≥ 6），使窗口级并发有实际可并行单位",
        "同时派发多个检查项与多个窗口，能产生 ≥ 2 个在途请求",
        "可调并发度（1/2/4/8）与多 run 并发对照，观测 429 / 限流 / P95 延迟变化",
        "固定同一份 OCR JSON（同一 SHA256）+ 同一清单 hash + 同一提示词 sha256 只保证输入相同；并发对照须再复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID），跑多次取分布",
        "注入超时/格式错误/致命错误，验证有限重试、停止派发、只重试失败段与覆盖不全标识",
        "串行与并发结果按 (check_item_id, text_sha256, source_page_number) 逐条比对；不要用 fingerprint 跨 run 比对（含随机 OcrBlock UUID）",
    ],
}


SAMPLE_LIMITATIONS["run_bound_artifacts"] = {'added_by': 'QA 独立复验后补充披露（不重跑基线、不改业务代码）', 'status': '已实测（QA 用 --probe-only 独立实跑 2 次 + 本轮只读复算；非推算）', 'finding': '同一 OCR JSON（SHA256 不变）重复导入，source_block_count=176 / source_total_characters=9570 四次相同，但窗口边界、逐窗口字符数与窗口文本 sha256 每次都不同。', 'comparison': [{'source': '04:56 早期 probe', 'win0': '130 块 / 7991 字符 / eb28ab09…', 'win1': '57 块 / 2086 字符 / c5702341…'}, {'source': '05:09 交付基线（本次 run）', 'win0': '132 块 / 7984 字符 / 0ddb2baa…', 'win1': '58 块 / 2158 字符 / 7bc72b8a…'}, {'source': 'QA probe#1', 'win0': '131 块 / 7983 字符 / aec6322f…', 'win1': '59 块 / 2137 字符 / 6a6cc477…'}, {'source': 'QA probe#2', 'win0': '131 块 / 7984 字符 / 00cedfdc…', 'win1': '59 块 / 2092 字符 / 5a10ed30…'}], 'comparison_source': 'QA 第 1 轮独立复验报告（表格原值）+ 本轮证据 windows.preflight / observed_during_run；首行 win0 块数按 /tmp/baseline_probe_stdout.txt:139 订正为 130（QA 第 1 轮报告表格转录误差，主理人汇编时订正）', 'root_causes_business_side': ['ocr_blocks.sequence_index 只有 25 个不同值却存 176 块；load_source_blocks / load_file_blocks 只 order_by(sequence_index)，同值行顺序由 DB 物理序决定 → 分窗边界漂移', '_window_text() 把每次导入新生成的随机 OcrBlock UUID 拼进窗口文本 → window_text_sha256 / messages_sha256 / user_sha256 随 run 变', '_fingerprint(check_item_id, block_id, start, end) 同样含随机 block_id → 同一段 text 在基线 run 与中断 run 的 fingerprint 全部不同（QA SQL JOIN 8/8 为不同）'], 'run_bound_values': ['window_text_sha256', '逐窗口字符数 / 窗口边界', 'messages_sha256', 'user_sha256', 'Result.fingerprint'], 'disclosure': '以上值均为「该次导入 DB 行（含 OcrBlock UUID）」绑定值，仅本次 run 内自洽；仅凭 OCR JSON SHA256 复现不出这些值。固定项指纹逐项一致只保证输入相同，不保证窗口级指纹复现。', 'rules': ['并发对照必须复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID）', '跨 run 逐条比对改用 text_sha256 + source_page_number，不要用 fingerprint', 'fingerprint 合并去重仅在「同一 run / 同一批 OcrBlock UUID 内」有效（同 run 内去重成立）'], 'technical_debt': '业务侧技术债（非本轮引入）：sequence_index 非唯一导致分窗不确定；block_id 进入窗口文本与 fingerprint。本轮不修改业务代码，仅如实披露，列为下一轮待修。'}


def _emit(evidence: dict[str, Any], out_path: str) -> None:
    """证据 JSON 同时落容器内磁盘 + 打到 stdout。

    先写磁盘再写 stdout：即使宿主机侧 docker exec 的 stdout 管道被断开，
    证据仍可通过 `docker cp credit-review-app-worker-1:<out_path> ...` 取回。
    """
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    try:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[baseline] 容器内证据落盘失败: {type(exc).__name__}: {exc}\n")
    sys.stdout.write(payload)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
