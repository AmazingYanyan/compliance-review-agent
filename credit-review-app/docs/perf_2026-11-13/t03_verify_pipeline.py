#!/usr/bin/env python3
"""T03 三组验收 · 容器内主脚本（worker 容器执行）。

零真实模型 / 零外部 OCR：monkeypatch 底层
``openai.resources.chat.completions.Completions.create``，固定响应 + 可控延迟 +
故障注入；真实 ``complete_json`` / ``_chat`` / ``_IN_FLIGHT`` 链路照常运行，
因此 RequestTrace 的 t_submit / t_http_start 是真实记录。

用法（宿主机）：
  docker cp "<15页OCR.json>" credit-review-app-worker-1:/tmp/t03_ocr.json
  docker exec -i credit-review-app-worker-1 python - \
      --evidence-out /tmp/t03_pipeline_evidence.json \
      --setup-out /tmp/t03_setup.json --ocr-json /tmp/t03_ocr.json \
      < docs/perf_2026-11-13/t03_verify_pipeline.py
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

from openai.resources.chat.completions import Completions
from sqlmodel import Session, select

import app.processing_pipeline as pipeline_mod
from app.checklist import checklist_hash, get_checklist
from app.cli import import_ocr_json
from app.core.config import settings
from app.core.db import engine
from app.models import (
    Decision,
    OcrBlock,
    OcrJob,
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

PROTECTED = [
    "607e6d41-4d47-4582-a5ad-07313b6c17bd",
    "ee59108d-e4f1-4aa8-bf2e-afe07d457384",
]
OCR_SHA = "8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b"
BLOCK_ID_RE = re.compile(
    r"block_id=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
BATCH_CHECK_RE = re.compile(r"check_item_id\s*[=:]\s*[\"']?([A-Za-z0-9_.\-]+)")
CHECK_ID_RE = re.compile(r"检查项：.*?（id=([A-Za-z0-9_.\-]+)")

# A/C/G2 用：三块全不同文 → w0=[b0,b1] / w1=[b1,b2]，可用第一块文本区分窗口
SYNTH_TEXTS = [
    "第一条 公司经营范围包括外汇担保业务。",
    "第二条 股东会为公司的权力机构，依法行使职权。",
    "第三条 对外担保须经出席股东三分之二以上表决权通过。",
]
# B 去重用：b0/b1 同文不同出处（不同 page_ordinal → 不同 content_hash）
SYNTH_TEXTS_DEDUP = [
    "第一条 公司经营范围包括外汇担保业务。",
    "第一条 公司经营范围包括外汇担保业务。",
    "第三条 对外担保须经出席股东三分之二以上表决权通过。",
]
C3 = ["charter.business_scope", "charter.approval_body", "charter.guarantee_restrictions"]
C2 = ["charter.business_scope", "charter.approval_body"]
C1 = ["charter.business_scope"]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _emit(payload: dict[str, Any], path: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"[t03] 落盘失败 {path}: {type(exc).__name__}: {exc}\n")
    sys.stdout.write(text)
    sys.stdout.flush()


def _protected_snapshot() -> dict[str, Any]:
    with Session(engine) as s:
        return {
            tid: {
                "exists": (row := s.get(Task, uuid.UUID(tid))) is not None,
                "state": row.state if row else None,
                "deleted_at": row.deleted_at.isoformat() if row and row.deleted_at else None,
                "input_revision": row.input_revision if row else None,
            }
            for tid in PROTECTED
        }


def _owner(s: Session) -> User:
    row = s.exec(select(User).where(User.is_active == True)).first()  # noqa: E712
    if not row:
        raise RuntimeError("库内无 active 用户")
    return row


def _create_synthetic(label: str, texts: list[str]) -> tuple[uuid.UUID, uuid.UUID, list[str]]:
    """隔离 Task + TaskFile + SUCCEEDED OcrJob(next_poll_at NULL) + 合成 OCR 块。"""
    with Session(engine) as s:
        owner = _owner(s)
        task = Task(
            owner_user_id=owner.id, name=f"T03-验收-{label}",
            product_code="working_capital_loan", customer_role="borrower",
            checklist_version="borrower-wcl-v1", state="PROCESSING", input_revision=0,
        )
        s.add(task)
        s.flush()
        f = TaskFile(
            task_id=task.id, original_name="固定响应章程.pdf",
            media_type="application/pdf", size_bytes=0,
            sha256=_sha(f"t03-synthetic-{label}"), source_page_count=1,
        )
        s.add(f)
        s.flush()
        job = OcrJob(
            task_id=task.id, file_id=f.id,
            request_config_hash=_sha("t03-fixed-request-config"),
            state="SUCCEEDED", next_poll_at=None,
            provider_job_id="t03-imported", provider_metadata={"source": "t03-selftest"},
        )
        s.add(job)
        s.flush()
        page = OcrPage(
            task_id=task.id, file_id=f.id, ocr_job_id=job.id,
            provider_line_index=0, provider_item_index=0, ocr_page_index=0,
            source_page_number=7, mapping_status="unverified",
            coordinate_space="ocr_input_image_pixels", width_px=1000, height_px=1400,
        )
        s.add(page)
        s.flush()
        block_ids: list[str] = []
        for idx, text in enumerate(texts):
            b = OcrBlock(
                task_id=task.id, file_id=f.id, page_id=page.id,
                provider_block_id=str(idx), sequence_index=idx, label="text",
                canonical_text=text, table_html=None,
                bbox=[100, 100 + idx * 200, 900, 180 + idx * 200], polygon=None,
            )
            s.add(b)
            s.flush()
            block_ids.append(str(b.id))
        tid, fid = task.id, f.id
        s.commit()
    return tid, fid, block_ids


def _create_realocr(label: str, ocr_json: str) -> tuple[uuid.UUID, uuid.UUID]:
    """隔离 Task + TaskFile(sha256=OCR_SHA) + import_ocr_json + 挂 SUCCEEDED job。"""
    with Session(engine) as s:
        owner = _owner(s)
        task = Task(
            owner_user_id=owner.id, name=f"T03-验收-{label}",
            product_code="working_capital_loan", customer_role="borrower",
            checklist_version="borrower-wcl-v1", state="PROCESSING", input_revision=0,
        )
        s.add(task)
        s.flush()
        f = TaskFile(
            task_id=task.id, original_name="《北京银行股份有限公司章程》 切分15页.PDF",
            media_type="application/pdf", size_bytes=0,
            sha256=OCR_SHA, source_page_count=15,
        )
        s.add(f)
        s.flush()
        tid, fid = task.id, f.id
        s.commit()
    with contextlib.redirect_stdout(sys.stderr):
        import_ocr_json(str(fid), ocr_json)
    with Session(engine) as s:
        for job in s.exec(select(OcrJob).where(OcrJob.task_id == tid)).all():
            job.state = "SUCCEEDED"
            job.next_poll_at = None
            s.add(job)
        s.commit()
    return tid, fid


def _snapshot(check_ids: list[str]) -> dict[str, Any]:
    full = get_checklist("borrower-wcl-v1")
    materials = []
    for m in full["materials"]:
        checks = [c for c in m["checks"] if c["id"] in check_ids]
        if checks:
            materials.append({"material_type": m["material_type"], "label": m.get("label", ""),
                              "checks": checks})
    return {"version": full["version"], "materials": materials}


def _create_run(task_id: uuid.UUID, file_id: uuid.UUID, check_ids: list[str], *,
                state: str = "QUEUED", coverage_complete: bool = False) -> uuid.UUID:
    with Session(engine) as s:
        run = ProcessingRun(
            task_id=task_id, input_revision=0,
            checklist_snapshot=_snapshot(check_ids),
            checklist_hash=checklist_hash("borrower-wcl-v1"),
            model_snapshot={}, state=state, stage=None,
            coverage_complete=coverage_complete, error_code=None, finished_at=None,
        )
        s.add(run)
        s.flush()
        s.add(RunFile(run_id=run.id, file_id=file_id, task_id=task_id))
        s.commit()
        return run.id


def _soft_delete(task_id: uuid.UUID) -> None:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if t:
            t.deleted_at = datetime.now(UTC)
            s.add(t)
            s.commit()


def _accept_all(task_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """给 run 的全部 Result 补 accepted Decision，供 HTTP complete 200 断言。"""
    with Session(engine) as s:
        for r in s.exec(select(Result).where(Result.run_id == run_id, Result.task_id == task_id)).all():
            d = s.exec(select(Decision).where(Decision.result_id == r.id)).first()
            if d:
                d.decision = "accepted"
                s.add(d)
            else:
                s.add(Decision(result_id=r.id, task_id=task_id, decision="accepted",
                               reject_reason=None, version=1, updated_at=datetime.now(UTC)))
        s.commit()


def _read_facts(task_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any]:
    with Session(engine) as s:
        run = s.get(ProcessingRun, run_id)
        results = s.exec(
            select(Result).where(Result.run_id == run_id, Result.task_id == task_id)
            .order_by(Result.check_item_id, Result.rank, Result.id)
        ).all()
        steps = s.exec(
            select(RunStep).where(RunStep.run_id == run_id, RunStep.task_id == task_id)
        ).all()
        rows = []
        for r in results:
            srcs = s.exec(select(ResultSource).where(ResultSource.result_id == r.id)).all()
            rows.append({
                "check_item_id": r.check_item_id, "kind": r.kind,
                "not_found_reason": r.not_found_reason, "rank": r.rank,
                "text": r.text, "text_sha256": _sha(r.text) if r.text else None,
                "fingerprint": r.fingerprint,
                "source_page_numbers": [x.source_page_number for x in srcs],
                "source_block_ids": [str(x.block_id) for x in srcs if x.block_id],
                "run_id": str(r.run_id), "task_id": str(r.task_id),
            })
        return {
            "run_state": run.state if run else None,
            "stage": run.stage if run else None,
            "coverage_complete": run.coverage_complete if run else None,
            "error_code": run.error_code if run else None,
            "run_config": (run.model_snapshot or {}).get("run_config") if run else None,
            "results": rows,
            "steps": [
                {"step_key": st.step_key, "state": st.state,
                 "last_error_code": st.last_error_code, "run_id": str(st.run_id)}
                for st in sorted(steps, key=lambda x: x.step_key)
            ],
        }


# ---------------------------------------------------------------------------
# 固定响应 / 可控延迟 / 在途计数 / 故障注入
# ---------------------------------------------------------------------------


class FixedMock:
    def __init__(self, *, mode: str = "found", ref_policy: str = "first_last",
                 ref_by_check: dict[str, str] | None = None,
                 delay_map: dict[tuple[str, str], float] | None = None,
                 inject_map: dict[tuple[str, str], str] | None = None) -> None:
        self.mode = mode
        self.ref_policy = ref_policy
        self.ref_by_check = ref_by_check or {}
        self.delay_map = delay_map or {}
        self.inject_map = inject_map or {}
        self.lock = threading.Lock()
        self.inflight = 0
        self.peak = 0
        self.seq = 0
        self.records: list[dict[str, Any]] = []

    def _classify(self, kwargs: dict[str, Any]) -> tuple[str, list[str], list[str], str]:
        system = ""
        user = ""
        for m in kwargs.get("messages") or []:
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
            if not isinstance(c, str):
                c = ""
            if m.get("role") == "system":
                system = c
            elif m.get("role") == "user":
                user = c
        rf = kwargs.get("response_format") or {}
        schema = ""
        if isinstance(rf, dict):
            js = rf.get("json_schema")
            schema = str(js.get("name")) if isinstance(js, dict) and js.get("name") else str(rf.get("type") or "")
        block_ids = BLOCK_ID_RE.findall(user) or BLOCK_ID_RE.findall(system)
        batch = list(dict.fromkeys(BATCH_CHECK_RE.findall(user)))
        single = CHECK_ID_RE.search(user)
        check_ids = batch or ([single.group(1)] if single else [])
        # 窗口键用第一块 UUID（稳定、与到达顺序无关）
        window_key = block_ids[0] if block_ids else ""
        return schema, check_ids, block_ids, window_key

    def _refs(self, cid: str, idx: int, block_ids: list[str]) -> list[str]:
        if not block_ids:
            return []
        pol = self.ref_by_check.get(cid, self.ref_policy)
        if pol == "first":
            return [block_ids[0]]
        if pol == "last":
            return [block_ids[-1]]
        if pol == "all":
            return list(block_ids)
        return [block_ids[0], block_ids[-1]] if len(block_ids) > 1 else [block_ids[0]]

    def _response(self, schema: str, check_ids: list[str], block_ids: list[str]) -> str:
        if schema == "classification_output":
            return json.dumps({
                "bundle_id": "merged", "material_type": "articles_of_association",
                "mixed": False, "confidence": 0.9, "reason": "固定响应",
                "source_block_ids": [],
            }, ensure_ascii=False)
        if schema == "vision_match_output":
            return json.dumps({"bundle_id": "w0", "check_item_id": "", "matches": []}, ensure_ascii=False)
        if self.mode == "empty":
            crs: list[dict[str, Any]] = []
        elif self.mode == "invalid_id_only":
            crs = [{
                "check_item_id": "bogus.not_in_batch", "outcome": "found",
                "evidence": [{"source_refs": [
                    {"block_id": b, "start_char": None, "end_char": None}
                    for b in self._refs("bogus.not_in_batch", 0, block_ids)
                ], "relation_status": "matched", "relevance_reason": "顶替"}],
            }]
        elif self.mode == "not_found":
            crs = [{"check_item_id": cid, "outcome": "not_found", "evidence": []} for cid in check_ids]
        else:
            crs = []
            for i, cid in enumerate(check_ids):
                crs.append({
                    "check_item_id": cid, "outcome": "found",
                    "evidence": [{"source_refs": [
                        {"block_id": b, "start_char": None, "end_char": None}
                        for b in self._refs(cid, i, block_ids)
                    ], "relation_status": "matched", "relevance_reason": "固定响应"}],
                })
        return json.dumps({"bundle_id": "w0", "check_results": crs}, ensure_ascii=False)

    def handle(self, **kwargs: Any) -> Any:
        schema, check_ids, block_ids, window_key = self._classify(kwargs)
        primary = check_ids[0] if check_ids else ""
        inject = self.inject_map.get((primary, window_key))
        delay = self.delay_map.get((primary, window_key), 0.0)
        qa_tag = (kwargs.get("extra_headers") or {}).get("X-QA-Tag")
        with self.lock:
            self.seq += 1
            seq = self.seq
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            arrive = time.perf_counter()
        try:
            if inject == "timeout":
                time.sleep(min(delay, 0.05))
                raise RuntimeError("QA injected transient timeout")
            if delay > 0:
                time.sleep(delay)
            content = self._response(schema, check_ids, block_ids)
            return NS(choices=[NS(message=NS(content=content), finish_reason="stop")])
        finally:
            with self.lock:
                self.inflight -= 1
                leave = time.perf_counter()
                self.records.append({
                    "seq": seq, "schema_name": schema,
                    "check_item_ids": check_ids, "window_key": window_key,
                    "block_count": len(block_ids), "qa_tag": qa_tag,
                    "arrive_perf": arrive, "leave_perf": leave,
                    "inject": inject, "delay_ms": round(delay * 1000, 1),
                })

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "request_count_total": self.seq,
                "peak_inflight": self.peak,
                "text_search_request_count": sum(
                    1 for r in self.records if r["schema_name"] == "text_search_output"
                ),
                "records": sorted(self.records, key=lambda r: r["seq"]),
            }


def _fake(mock: FixedMock):
    def create(_completions_self: Any, **kwargs: Any) -> Any:
        return mock.handle(**kwargs)
    return create


_ORIGINAL_CREATE = Completions.create


def _run_case(label: str, *, check_ids: list[str], x: int, mock: FixedMock,
              texts: list[str] | None = None, real_ocr: str | None = None,
              max_chars: int | None = None, overlap: int | None = None,
              accept_all: bool = False) -> dict[str, Any]:
    if real_ocr:
        task_id, file_id = _create_realocr(label, real_ocr)
        block_ids: list[str] = []
    else:
        task_id, file_id, block_ids = _create_synthetic(label, texts or SYNTH_TEXTS)
    run_id = _create_run(task_id, file_id, check_ids)
    orig_x = settings.CHECKS_PER_REQUEST
    orig_max = settings.LLM_WINDOW_CHARACTERS
    orig_overlap = settings.LLM_WINDOW_OVERLAP_CHARACTERS
    error: str | None = None
    try:
        Completions.create = _fake(mock)
        settings.CHECKS_PER_REQUEST = x
        if max_chars is not None:
            settings.LLM_WINDOW_CHARACTERS = max_chars
        if overlap is not None:
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = overlap
        pipeline_mod.run_pipeline.func(str(run_id))
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        Completions.create = _ORIGINAL_CREATE
        settings.CHECKS_PER_REQUEST = orig_x
        settings.LLM_WINDOW_CHARACTERS = orig_max
        settings.LLM_WINDOW_OVERLAP_CHARACTERS = orig_overlap
    if accept_all:
        _accept_all(task_id, run_id)
    return {
        "label": label, "task_id": str(task_id), "run_id": str(run_id),
        "input_revision": 0, "x": x, "real_ocr": bool(real_ocr),
        "block_ids": block_ids, "pipeline_exception": error,
        "facts": _read_facts(task_id, run_id), "mock": mock.snapshot(),
    }


def _direct_run(label: str, *, state: str, coverage_complete: bool,
                with_incomplete: bool) -> dict[str, Any]:
    """直接造 READY/FAILED run（不走 pipeline），供 G2 三条 HTTP 断言。"""
    task_id, file_id, _ = _create_synthetic(label, SYNTH_TEXTS)
    run_id = _create_run(task_id, file_id, C1, state=state,
                         coverage_complete=coverage_complete)
    with Session(engine) as s:
        run = s.get(ProcessingRun, run_id)
        run.stage = "done" if state == "READY" else "search"
        run.error_code = "SEARCH_FAILED:RuntimeError" if state == "FAILED" else None
        run.finished_at = datetime.now(UTC)
        s.add(run)
        s.flush()
        visible = Result(task_id=task_id, run_id=run_id,
                         check_item_id=C1[0], kind="text",
                         text=SYNTH_TEXTS[0], relation_status="matched",
                         rank=0, fingerprint=_sha("t03-direct-content"))
        s.add(visible)
        s.flush()
        s.add(Decision(result_id=visible.id, task_id=task_id, decision="accepted",
                       reject_reason=None, version=1, updated_at=datetime.now(UTC)))
        if with_incomplete:
            s.add(Result(task_id=task_id, run_id=run_id,
                         check_item_id="charter.approval_body", kind="not_found",
                         not_found_reason="coverage_incomplete", rank=0))
        s.add(RunStep(task_id=task_id, run_id=run_id,
                      step_key=f"check:{C1[0]}", input_hash=_sha(f"check:{C1[0]}"),
                      state="SUCCEEDED", attempt=0,
                      started_at=datetime.now(UTC), finished_at=datetime.now(UTC)))
        s.commit()
        task = s.get(Task, task_id)
        task.state = "REVIEWING" if state == "READY" else "PROCESSING"
        s.add(task)
        s.commit()
    return {"label": label, "task_id": str(task_id), "run_id": str(run_id),
            "input_revision": 0, "state": state,
            "coverage_complete": coverage_complete}


def _result_set(facts: dict[str, Any]) -> list[tuple[Any, ...]]:
    """跨 run 比对键：text_sha256 + source_page_number + 页内稳定序号(rank)，不用 fingerprint。"""
    return sorted(
        (
            r["check_item_id"], r["kind"], r["text_sha256"],
            tuple(r["source_page_numbers"]), r["rank"],
        )
        for r in facts["results"]
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--evidence-out", default="/tmp/t03_pipeline_evidence.json")
    p.add_argument("--setup-out", default="/tmp/t03_setup.json")
    p.add_argument("--ocr-json", default="/tmp/t03_ocr.json")
    args = p.parse_args()

    ev: dict[str, Any] = {
        "selftest": "T03-三组验收-容器内主脚本",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_model_calls": 0,
        "external_ocr_calls": 0,
        "injection_point": "openai.resources.chat.completions.Completions.create (monkeypatch)",
        "config_observed": {
            "CHECKS_PER_REQUEST": settings.CHECKS_PER_REQUEST,
            "LLM_MAX_IN_FLIGHT": settings.LLM_MAX_IN_FLIGHT,
            "LLM_MAX_CONCURRENCY": settings.LLM_MAX_CONCURRENCY,
            "PIPELINE_CONFIG_VERSION": settings.PIPELINE_CONFIG_VERSION,
            "LLM_REQUEST_TIMEOUT_SECONDS": settings.LLM_REQUEST_TIMEOUT_SECONDS,
        },
        "protected_tasks_before": _protected_snapshot(),
        "cases": {},
        "assertions": {},
    }
    created: list[tuple[str, uuid.UUID]] = []

    def record(case: dict[str, Any]) -> dict[str, Any]:
        created.append((case["label"], uuid.UUID(case["task_id"])))
        ev["cases"][case["label"]] = case
        return case

    try:
        # ---- A：4 请求 / C=2 / 打乱返回顺序 --------------------------------
        tid_a, fid_a, b_a = _create_synthetic("A-concurrency", SYNTH_TEXTS)
        created.append(("A-concurrency", tid_a))
        run_a = _create_run(tid_a, fid_a, C2)
        mock_a = FixedMock(
            mode="found", ref_policy="first_last",
            ref_by_check={"charter.business_scope": "first", "charter.approval_body": "last"},
            delay_map={
                ("charter.business_scope", b_a[0]): 0.40,  # U0 慢
                ("charter.business_scope", b_a[1]): 0.02,  # U1 快（w1 首块=b1）
                ("charter.approval_body", b_a[0]): 0.02,   # U2 快
                ("charter.approval_body", b_a[1]): 0.06,   # U3 中
            },
        )
        orig_x, orig_max, orig_ov = (settings.CHECKS_PER_REQUEST,
                                    settings.LLM_WINDOW_CHARACTERS,
                                    settings.LLM_WINDOW_OVERLAP_CHARACTERS)
        a_error = None
        try:
            Completions.create = _fake(mock_a)
            settings.CHECKS_PER_REQUEST = 1
            settings.LLM_WINDOW_CHARACTERS = 45
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = 10
            pipeline_mod.run_pipeline.func(str(run_a))
        except Exception as exc:  # noqa: BLE001
            a_error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            Completions.create = _ORIGINAL_CREATE
            settings.CHECKS_PER_REQUEST = orig_x
            settings.LLM_WINDOW_CHARACTERS = orig_max
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = orig_ov
        facts_a = _read_facts(tid_a, run_a)
        # JSONL（逐请求 t_submit / t_http_start）
        trace_path = Path("/data/perf_traces") / f"{run_a}.jsonl"
        traces = []
        if trace_path.is_file():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    traces.append(json.loads(line))
        recs = [r for r in mock_a.snapshot()["records"] if r["schema_name"] == "text_search_output"]
        slow = next((r for r in recs if r["delay_ms"] >= 400), None)
        fast = next((r for r in recs if r["delay_ms"] <= 20), None)
        refill_while_slow = 0
        if slow and fast:
            refill_while_slow = sum(
                1 for r in recs
                if r["seq"] != slow["seq"] and r["seq"] != fast["seq"]
                and fast["leave_perf"] < r["arrive_perf"] < slow["leave_perf"]
            )
        ev["A"] = {
            "task_id": str(tid_a), "run_id": str(run_a), "input_revision": 0,
            "C": settings.LLM_MAX_IN_FLIGHT, "X": 1,
            "mock": mock_a.snapshot(), "facts": facts_a,
            "trace_jsonl_path": str(trace_path),
            "trace_rows": len(traces),
            # QA A3/A4 断言入口字段（逐请求 JSONL）
            "trace_qa_required_fields": [
                "trace_id", "run_id", "window_id", "window_index", "batch_id",
                "check_ids", "check_item_id", "t_submit", "t_http_start",
                "t_http_end", "state", "error_code", "finish_reason",
                "messages_sha256", "user_sha256", "window_text_sha256",
            ],
            "trace_fields_present": all(
                all(k in t for k in (
                    "trace_id", "run_id", "window_id", "window_index", "batch_id",
                    "check_ids", "check_item_id", "t_submit", "t_http_start",
                    "t_http_end", "state", "error_code", "finish_reason",
                    "messages_sha256", "user_sha256", "window_text_sha256",
                )) for t in traces
            ),
            "trace_http_start_not_null": all(t.get("t_http_start") is not None for t in traces),
            "trace_submit_le_http_start": all(
                t.get("t_http_start") is None or t.get("t_submit") is None
                or t["t_http_start"] >= t["t_submit"] for t in traces
            ),
            "slow_request": slow, "fast_request": fast,
            "refill_while_slow_inflight": refill_while_slow,
            "qa_tag_values": sorted({str(r.get("qa_tag")) for r in recs}),
            "pipeline_exception": a_error,
        }
        ev["assertions"]["A_peak_inflight_eq_C"] = mock_a.snapshot()["peak_inflight"] == 2
        ev["assertions"]["A_four_search_units"] = len(recs) == 4
        ev["assertions"]["A_refill_before_slow_finishes"] = refill_while_slow >= 1
        ev["assertions"]["A_unit_steps_are_u_keys"] = len(
            [st for st in facts_a["steps"] if st["step_key"].startswith("u:")]
        ) == 4
        ev["assertions"]["A_no_cross_run_writes"] = all(
            r["run_id"] == str(run_a) and r["task_id"] == str(tid_a)
            for r in facts_a["results"]
        ) and all(
            st["run_id"] == str(run_a) for st in facts_a["steps"]
        )
        ev["assertions"]["A_each_check_has_result"] = set(
            r["check_item_id"] for r in facts_a["results"]
        ) >= set(C2)
        ev["assertions"]["A_trace_has_submit_and_http_start"] = (
            ev["A"]["trace_rows"] >= 4 and ev["A"]["trace_fields_present"]
            and ev["A"]["trace_http_start_not_null"]
            and ev["A"]["trace_submit_le_http_start"]
        )
        ev["assertions"]["A_run_READY_coverage_true"] = (
            facts_a["run_state"] == "READY" and facts_a["coverage_complete"] is True
        )
        ev["assertions"]["A_trace_qa_required_fields"] = (
            ev["A"]["trace_rows"] >= 4 and ev["A"]["trace_fields_present"]
        )
        ev["assertions"]["A_qa_tag_matches_run_id"] = (
            bool(recs) and all(r.get("qa_tag") == str(run_a) for r in recs)
        )

        # ---- B1：真实 15 页 OCR，X=1 vs X=3 请求数 + 摘录集合 ---------------
        b1_x1 = record(_run_case("B-real-x1", check_ids=C3, x=1,
                                 mock=FixedMock(mode="found", ref_policy="first_last"),
                                 real_ocr=args.ocr_json))
        b1_x3 = record(_run_case("B-real-x3", check_ids=C3, x=3,
                                 mock=FixedMock(mode="found", ref_policy="first_last"),
                                 real_ocr=args.ocr_json))
        ev["B_real_ocr"] = {
            "ocr_json": args.ocr_json, "sha256": OCR_SHA,
            "x1": {"request_count": b1_x1["mock"]["text_search_request_count"],
                   "run_config_units_total": (b1_x1["facts"]["run_config"] or {}).get("units_total"),
                   "run_config_batch_status": (b1_x1["facts"]["run_config"] or {}).get("batch", {}).get("status"),
                   "batches": (b1_x1["facts"]["run_config"] or {}).get("batch", {}).get("batches")},
            "x3": {"request_count": b1_x3["mock"]["text_search_request_count"],
                   "run_config_units_total": (b1_x3["facts"]["run_config"] or {}).get("units_total"),
                   "run_config_batch_status": (b1_x3["facts"]["run_config"] or {}).get("batch", {}).get("status"),
                   "batches": (b1_x3["facts"]["run_config"] or {}).get("batch", {}).get("batches")},
            "result_sets_equal": _result_set(b1_x1["facts"]) == _result_set(b1_x3["facts"]),
        }
        ev["assertions"]["B_x1_request_count_6"] = b1_x1["mock"]["text_search_request_count"] == 6
        ev["assertions"]["B_x3_request_count_2"] = b1_x3["mock"]["text_search_request_count"] == 2
        ev["assertions"]["B_x3_fewer_requests_than_x1"] = (
            b1_x3["mock"]["text_search_request_count"] < b1_x1["mock"]["text_search_request_count"]
        )
        ev["assertions"]["B_result_sets_equal"] = ev["B_real_ocr"]["result_sets_equal"]
        ev["assertions"]["B_run_config_records_X_and_batches"] = (
            (b1_x1["facts"]["run_config"] or {}).get("checks_per_request") == 1
            and (b1_x3["facts"]["run_config"] or {}).get("checks_per_request") == 3
            and bool(b1_x3["facts"]["run_config"]["batch"]["batches"])
        )

        # ---- B2：合成块去重样本（D1-D4），X=1 vs X=3 ------------------------
        b2_x1 = record(_run_case("B-dedup-x1", check_ids=C3, x=1,
                                 texts=SYNTH_TEXTS_DEDUP,
                                 mock=FixedMock(mode="found", ref_policy="first_last"),
                                 max_chars=45, overlap=10))
        b2_x3 = record(_run_case("B-dedup-x3", check_ids=C3, x=3,
                                 texts=SYNTH_TEXTS_DEDUP,
                                 mock=FixedMock(mode="found", ref_policy="first_last"),
                                 max_chars=45, overlap=10))
        def _text_rows(facts):
            return [r for r in facts["results"] if r["kind"] == "text"]
        rows_x1 = _text_rows(b2_x1["facts"])
        # 每个检查项：b0(ordinal0) / b1(ordinal1,同文) / b2(ordinal2) → 3 条；
        # b1 跨 w0/w1 重复引用只存 1 条；3 个检查项共 9 条。
        per_check_counts = {
            cid: len([r for r in rows_x1 if r["check_item_id"] == cid]) for cid in C3
        }
        dup_texts_kept = len({r["text_sha256"] for r in rows_x1}) >= 1
        ev["B_dedup"] = {
            "x1_text_rows": len(rows_x1),
            "x3_text_rows": len(_text_rows(b2_x3["facts"])),
            "per_check_counts_x1": per_check_counts,
            "cross_window_duplicate_dedup_to_single": all(v == 3 for v in per_check_counts.values()),
            "same_text_different_source_kept": dup_texts_kept,
            "same_block_multi_check_preserved": all(v >= 1 for v in per_check_counts.values()),
            "x1_x3_result_sets_equal": _result_set(b2_x1["facts"]) == _result_set(b2_x3["facts"]),
            "text_sha256_distinct_count": len({r["text_sha256"] for r in rows_x1}),
        }
        ev["assertions"]["B_dedup_rows_per_check_eq_3"] = all(v == 3 for v in per_check_counts.values())
        ev["assertions"]["B_dedup_x1_x3_equal"] = ev["B_dedup"]["x1_x3_result_sets_equal"]
        ev["assertions"]["B_dedup_fingerprint_is_64hex"] = all(
            bool(re.fullmatch(r"[0-9a-f]{64}", r["fingerprint"] or "")) for r in rows_x1
        )

        # ---- C：窗口0 成功、窗口1 超时耗尽 ---------------------------------
        tid_c, fid_c, b_c = _create_synthetic("C-partial", SYNTH_TEXTS)
        created.append(("C-partial", tid_c))
        run_c = _create_run(tid_c, fid_c, C1)
        mock_c = FixedMock(mode="found", ref_policy="first_last",
                           inject_map={("charter.business_scope", b_c[1]): "timeout"})
        _x, _m, _o = (settings.CHECKS_PER_REQUEST, settings.LLM_WINDOW_CHARACTERS,
                      settings.LLM_WINDOW_OVERLAP_CHARACTERS)
        c_error = None
        try:
            Completions.create = _fake(mock_c)
            settings.CHECKS_PER_REQUEST = 1
            settings.LLM_WINDOW_CHARACTERS = 45
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = 10
            pipeline_mod.run_pipeline.func(str(run_c))
        except Exception as exc:  # noqa: BLE001
            c_error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            Completions.create = _ORIGINAL_CREATE
            settings.CHECKS_PER_REQUEST = _x
            settings.LLM_WINDOW_CHARACTERS = _m
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = _o
        facts_c = _read_facts(tid_c, run_c)
        hit_rows = [r for r in facts_c["results"] if r["kind"] == "text"]
        short_codes = [st["last_error_code"] for st in facts_c["steps"]
                       if st["step_key"].startswith("u:") and st["last_error_code"]]
        ev["C"] = {
            "partial": {"task_id": str(tid_c), "run_id": str(run_c),
                        "input_revision": 0, "facts": facts_c,
                        "mock": mock_c.snapshot(), "pipeline_exception": c_error,
                        "hit_rows": len(hit_rows),
                        "hit_text_preserved": all(bool(r["text"]) for r in hit_rows),
                        "coverage_incomplete_reasons": sorted({
                            r["not_found_reason"] for r in facts_c["results"]
                            if r["not_found_reason"] == "coverage_incomplete"}),
                        "unit_short_codes": short_codes},
        }
        ev["assertions"]["C_hit_excerpts_preserved"] = bool(hit_rows) and ev["C"]["partial"]["hit_text_preserved"]
        ev["assertions"]["C_coverage_incomplete_marked"] = (
            ev["C"]["partial"]["coverage_incomplete_reasons"] == ["coverage_incomplete"]
        )
        ev["assertions"]["C_run_coverage_false"] = facts_c["coverage_complete"] is False
        ev["assertions"]["C_run_READY"] = facts_c["run_state"] == "READY"
        ev["assertions"]["C_BATCH_TIMEOUT_shortcode"] = any(
            "BATCH_TIMEOUT" in (c or "") for c in short_codes
        )
        ev["assertions"]["C_no_PARTIAL_COVERAGE_shortcode"] = all(
            "PARTIAL_COVERAGE" not in (c or "") for c in short_codes
        )
        # 正常样本：全窗口成功 → coverage_complete=true，补 Decision 供 HTTP 200
        c_ok = record(_run_case("C-ok", check_ids=C1, x=1,
                                mock=FixedMock(mode="found", ref_policy="first_last"),
                                max_chars=45, overlap=10, accept_all=True))
        ev["C"]["ok"] = {"task_id": c_ok["task_id"], "run_id": c_ok["run_id"],
                         "input_revision": 0,
                         "coverage_complete": c_ok["facts"]["coverage_complete"]}
        ev["assertions"]["C_ok_coverage_true"] = c_ok["facts"]["coverage_complete"] is True

        # ---- F1：X=1 空响应 / 非法 ID 顶替 / 明确 not_found -----------------
        f1_empty = record(_run_case("F1-empty", check_ids=C1, x=1,
                                    mock=FixedMock(mode="empty"),
                                    max_chars=45, overlap=10))
        f1_invalid = record(_run_case("F1-invalid-id", check_ids=C1, x=1,
                                      mock=FixedMock(mode="invalid_id_only"),
                                      max_chars=45, overlap=10))
        f1_notfound = record(_run_case("F1-not-found", check_ids=C1, x=1,
                                       mock=FixedMock(mode="not_found"),
                                       max_chars=45, overlap=10))
        def _f1_summary(case):
            f = case["facts"]
            reasons = sorted({r["not_found_reason"] for r in f["results"] if r["not_found_reason"]})
            codes = sorted({c for st in f["steps"] if st["step_key"].startswith("u:")
                            for c in (st["last_error_code"] or "").split(",") if c})
            return {"run_state": f["run_state"], "coverage_complete": f["coverage_complete"],
                    "not_found_reasons": reasons, "unit_short_codes": codes}
        ev["F1"] = {
            "empty_check_results": _f1_summary(f1_empty),
            "invalid_id_only": _f1_summary(f1_invalid),
            "explicit_not_found": _f1_summary(f1_notfound),
        }
        ev["assertions"]["F1_empty_uncovered"] = (
            ev["F1"]["empty_check_results"]["coverage_complete"] is False
            and "coverage_incomplete" in ev["F1"]["empty_check_results"]["not_found_reasons"]
            and "BATCH_MISSING_CHECK" in ev["F1"]["empty_check_results"]["unit_short_codes"]
        )
        ev["assertions"]["F1_invalid_id_uncovered"] = (
            ev["F1"]["invalid_id_only"]["coverage_complete"] is False
            and "INVALID_CHECK_ID" in ev["F1"]["invalid_id_only"]["unit_short_codes"]
            and "BATCH_MISSING_CHECK" in ev["F1"]["invalid_id_only"]["unit_short_codes"]
        )
        ev["assertions"]["F1_not_found_covered"] = (
            ev["F1"]["explicit_not_found"]["coverage_complete"] is True
            and ev["F1"]["explicit_not_found"]["not_found_reasons"] == ["no_matching_evidence"]
        )

        # ---- G2 直接造数（HTTP 断言对象） ----------------------------------
        g2_failed = _direct_run("G2-failed", state="FAILED", coverage_complete=False,
                                with_incomplete=False)
        g2_false = _direct_run("G2-ready-false", state="READY", coverage_complete=False,
                               with_incomplete=True)
        g2_true = _direct_run("G2-ready-true", state="READY", coverage_complete=True,
                              with_incomplete=False)
        for g in (g2_failed, g2_false, g2_true):
            created.append((g["label"], uuid.UUID(g["task_id"])))
        # 历史 REVIEWING 任务同构副本：无 u:/check: 步、coverage_complete=true、有决策
        hist = _create_synthetic("HIST-reviewing-clone", SYNTH_TEXTS)
        created.append(("HIST-reviewing-clone", hist[0]))
        run_hist = _create_run(hist[0], hist[1], C1, state="READY", coverage_complete=True)
        with Session(engine) as s:
            run = s.get(ProcessingRun, run_hist)
            run.stage = "done"
            run.finished_at = datetime.now(UTC)
            s.add(run)
            s.flush()
            r = Result(task_id=hist[0], run_id=run_hist, check_item_id=C1[0],
                       kind="text", text=SYNTH_TEXTS[0], relation_status="matched",
                       rank=0, fingerprint=_sha("t03-hist-content"))
            s.add(r)
            s.flush()
            s.add(Decision(result_id=r.id, task_id=hist[0], decision="accepted",
                           reject_reason=None, version=1, updated_at=datetime.now(UTC)))
            s.commit()
            t = s.get(Task, hist[0])
            t.state = "REVIEWING"
            s.add(t)
            s.commit()
        setup = {
            "protected_tasks": PROTECTED,
            # 软删推迟到 HTTP 断言完成后：get_owned_task 过滤 deleted_at，
            # 提前软删会让 complete_task 返回 404 而非预期的 409/200。
            "soft_delete_candidates": [str(tid) for _, tid in created],
            "A": {"task_id": ev["A"]["task_id"], "run_id": ev["A"]["run_id"], "input_revision": 0},
            "B_x1": {"task_id": b1_x1["task_id"], "run_id": b1_x1["run_id"], "input_revision": 0},
            "B_x3": {"task_id": b1_x3["task_id"], "run_id": b1_x3["run_id"], "input_revision": 0},
            "C_partial": {"task_id": str(tid_c), "run_id": str(run_c), "input_revision": 0},
            "C_ok": {"task_id": c_ok["task_id"], "run_id": c_ok["run_id"], "input_revision": 0},
            "F1_empty": {"task_id": f1_empty["task_id"], "run_id": f1_empty["run_id"], "input_revision": 0},
            "F1_invalid": {"task_id": f1_invalid["task_id"], "run_id": f1_invalid["run_id"], "input_revision": 0},
            "F1_notfound": {"task_id": f1_notfound["task_id"], "run_id": f1_notfound["run_id"], "input_revision": 0},
            "G2_failed": g2_failed, "G2_ready_false": g2_false,
            "G2_ready_true": g2_true,
            "HIST_reviewing_clone": {"task_id": str(hist[0]), "run_id": str(run_hist),
                                     "input_revision": 0},
            "historical_real_task": {
                "task_id": PROTECTED[0],
                "note": "只读核对；硬边界禁止改写真实任务，完成动作在同构隔离副本上实测",
            },
        }
        _emit(setup, args.setup_out)
        ev["setup_path"] = args.setup_out
    except Exception as exc:  # noqa: BLE001
        import traceback
        ev["status"] = "error"
        ev["error"] = f"{type(exc).__name__}: {exc}"[:800]
        ev["traceback"] = traceback.format_exc()[-2500:]
    finally:
        ev["isolated_task_count"] = len(created)
        ev["soft_delete_deferred_to_after_http"] = True
        ev["protected_tasks_after"] = _protected_snapshot()
        ev["protected_tasks_untouched"] = (
            ev["protected_tasks_before"] == ev["protected_tasks_after"]
        )

    ev.setdefault("status", "pass" if all(ev["assertions"].values()) and ev["assertions"] else "fail")
    ev["assertions_failed"] = [k for k, v in ev["assertions"].items() if not v]
    _emit(ev, args.evidence_out)
    return 0 if ev["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
