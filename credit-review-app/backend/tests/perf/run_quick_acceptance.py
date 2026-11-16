#!/usr/bin/env python3
"""qa-perf 三组快速验收 · 容器内独立实跑主脚本（worker 容器执行）。

零真实模型 / 零外部 OCR：
* 在容器内启动 ``mock_llm_server.py`` 的 HTTP 服务（127.0.0.1:8099），
  text_search 请求**真实 HTTP 到达**该服务，产生 arrived_at / peak_inflight /
  barrier 放行顺序等落盘统计（A1/A2 的实测来源）。
* 非 text_search（classification / vision）在进程内固定响应、不发 HTTP，
  避免占用 mock 的 arrival_seq 导致 barrier 与 classification 互相等待。
* ``settings.LLM_API_BASE`` 在**进程内**指向模拟服务；不改 .env、不改任何配置文件。
* 造隔离 Task/File/OcrJob(SUCCEEDED, next_poll_at NULL)，跑真实 ``run_pipeline``。
* X=3 批量响应的正确性由本脚本按请求内真实 ``check_item_id`` 清单动态构造
  （模拟服务模板无法循环生成多个 check_results），HTTP 仍真实发出以计入 stats。

输出（容器内 /tmp/qa_qa_evidence/，由宿主机 docker cp 取回）：
  a_stats.json / a_results.json / a_trace.jsonl / a_units.json
  b_x1_stats.json / b_x1_results.json / b_x3_stats.json / b_x3_results.json
  b_dedup_summary.json / b_dedup_x1_results.json / b_dedup_x3_results.json
  c_partial_results.json / c_ok_results.json
  setup.json / runtime_configs.json / protected_snapshot.json

用法（宿主机）：
  docker cp mock_llm_server.py credit-review-app-worker-1:/tmp/qa_perf/
  docker cp mock_config.a_c2_refill_4.json credit-review-app-worker-1:/tmp/qa_perf/
  docker cp run_quick_acceptance.py credit-review-app-worker-1:/tmp/qa_perf/
  docker cp "<15页OCR.json>" credit-review-app-worker-1:/tmp/qa_perf/ocr15.json
  docker exec credit-review-app-worker-1 python /tmp/qa_perf/run_quick_acceptance.py \
      --config /tmp/qa_perf/mock_config.a_c2_refill_4.json \
      --ocr-json /tmp/qa_perf/ocr15.json --out-dir /tmp/qa_qa_evidence
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MOCK_PORT = 8099
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"
# 必须在 import app 之前设置：pydantic BaseSettings 在模块 import 时读 env
os.environ["LLM_API_BASE"] = MOCK_BASE

import mock_llm_server as M  # noqa: E402
from openai.resources.chat.completions import Completions  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.processing_pipeline as pipeline_mod  # noqa: E402
from app.checklist import checklist_hash, get_checklist  # noqa: E402
from app.cli import import_ocr_json  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.models import (  # noqa: E402
    Decision, OcrBlock, OcrJob, OcrPage, ProcessingRun, Result,
    ResultSource, RunFile, RunStep, Task, TaskFile, User,
)

settings.LLM_API_BASE = MOCK_BASE  # 双保险：LLMClient() 实例化时读取

PROTECTED = [
    "607e6d41-4d47-4582-a5ad-07313b6c17bd",
    "ee59108d-e4f1-4aa8-bf2e-afe07d457384",
]
OCR_SHA = "8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b"
C3 = ["charter.business_scope", "charter.approval_body", "charter.guarantee_restrictions"]
C2 = ["charter.business_scope", "charter.approval_body"]
C1 = ["charter.business_scope"]
# 与 dev-backend 自测同口径的合成块文本（仅造数样本一致，结果独立实跑）
SYNTH_TEXTS = [
    "第一条 公司经营范围包括外汇担保业务。",
    "第二条 股东会为公司的权力机构，依法行使职权。",
    "第三条 对外担保须经出席股东三分之二以上表决权通过。",
]
SYNTH_TEXTS_DEDUP = [
    "第一条 公司经营范围包括外汇担保业务。",
    "第一条 公司经营范围包括外汇担保业务。",
    "第三条 对外担保须经出席股东三分之二以上表决权通过。",
]

# 每个 case 的运行时行为（由 patched create 读取）
CASE: dict[str, Any] = {
    "dynamic_search": False,   # True: 用动态构造的响应覆盖 mock 静态响应
    "refs_policy": "first",    # first / all / first_last
    "timeout_first_block": None,  # 该 block_id 作为窗口首块时注入超时
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# 造数（全部隔离，跑完由宿主机统一软删）
# ---------------------------------------------------------------------------

def _protected() -> dict[str, Any]:
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
    with Session(engine) as s:
        task = Task(
            owner_user_id=_owner(s).id, name=f"QA-PERF-三组验收-{label}",
            product_code="working_capital_loan", customer_role="borrower",
            checklist_version="borrower-wcl-v1", state="PROCESSING", input_revision=0,
        )
        s.add(task)
        s.flush()
        f = TaskFile(
            task_id=task.id, original_name="固定响应章程.pdf",
            media_type="application/pdf", size_bytes=0,
            sha256=_sha(f"qa-perf-synthetic-{label}"), source_page_count=1,
        )
        s.add(f)
        s.flush()
        job = OcrJob(
            task_id=task.id, file_id=f.id,
            request_config_hash=_sha("qa-perf-fixed-request-config"),
            state="SUCCEEDED", next_poll_at=None,
            provider_job_id="qa-perf-imported",
            provider_metadata={"source": "qa-perf-quick-acceptance"},
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
        block_ids = []
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
    with Session(engine) as s:
        task = Task(
            owner_user_id=_owner(s).id, name=f"QA-PERF-三组验收-{label}",
            product_code="working_capital_loan", customer_role="borrower",
            checklist_version="borrower-wcl-v1", state="PROCESSING", input_revision=0,
        )
        s.add(task)
        s.flush()
        f = TaskFile(
            task_id=task.id,
            original_name="《北京银行股份有限公司章程》 切分15页.PDF",
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
            materials.append({"material_type": m["material_type"],
                              "label": m.get("label", ""), "checks": checks})
    return {"version": full["version"], "materials": materials}


def _create_run(task_id: uuid.UUID, file_id: uuid.UUID,
                check_ids: list[str]) -> uuid.UUID:
    with Session(engine) as s:
        run = ProcessingRun(
            task_id=task_id, input_revision=0,
            checklist_snapshot=_snapshot(check_ids),
            checklist_hash=checklist_hash("borrower-wcl-v1"),
            model_snapshot={}, state="QUEUED", stage=None,
            coverage_complete=False, error_code=None, finished_at=None,
        )
        s.add(run)
        s.flush()
        s.add(RunFile(run_id=run.id, file_id=file_id, task_id=task_id))
        s.commit()
        return run.id


def _accept_all(task_id: uuid.UUID, run_id: uuid.UUID) -> None:
    with Session(engine) as s:
        for r in s.exec(select(Result).where(
                Result.run_id == run_id, Result.task_id == task_id)).all():
            d = s.exec(select(Decision).where(Decision.result_id == r.id)).first()
            if d:
                d.decision = "accepted"
                s.add(d)
            else:
                s.add(Decision(result_id=r.id, task_id=task_id,
                               decision="accepted", reject_reason=None,
                               version=1, updated_at=datetime.now(UTC)))
        s.commit()


# ---------------------------------------------------------------------------
# 落库导出
# ---------------------------------------------------------------------------

def _export(task_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any]:
    with Session(engine) as s:
        run = s.get(ProcessingRun, run_id)
        rows = []
        for r in s.exec(select(Result).where(
                Result.run_id == run_id, Result.task_id == task_id)
                .order_by(Result.check_item_id, Result.rank, Result.id)).all():
            srcs = s.exec(select(ResultSource).where(
                ResultSource.result_id == r.id)).all()
            pages = [x.source_page_number for x in srcs]
            rows.append({
                "check_item_id": r.check_item_id,
                "kind": r.kind,
                "not_found_reason": r.not_found_reason,
                "text_sha256": _sha(r.text) if r.text else None,
                "source_page_number": pages[0] if pages else None,
                "page_inner_seq": r.rank,
                "source_block_ids": [str(x.block_id) for x in srcs if x.block_id],
                "run_id": str(r.run_id), "task_id": str(r.task_id),
            })
        steps = [
            {"step_key": st.step_key, "state": st.state,
             "last_error_code": st.last_error_code, "run_id": str(st.run_id)}
            for st in sorted(
                s.exec(select(RunStep).where(
                    RunStep.run_id == run_id, RunStep.task_id == task_id)).all(),
                key=lambda x: x.step_key)
        ]
        task = s.get(Task, task_id)
        return {
            "run_id": str(run_id), "task_id": str(task_id), "tag": None,
            "run_state": run.state if run else None,
            "stage": run.stage if run else None,
            "coverage_complete": run.coverage_complete if run else None,
            "error_code": run.error_code if run else None,
            "run_config": (run.model_snapshot or {}).get("run_config") if run else None,
            "task_state": task.state if task else None,
            "rows": rows, "steps": steps,
        }


def _result_set(res: dict[str, Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (r["check_item_id"], r["kind"], r["text_sha256"],
         r["source_page_number"], r["page_inner_seq"])
        for r in res["rows"]
    )


# ---------------------------------------------------------------------------
# HTTP 模拟服务 + Completions.create 包装
# ---------------------------------------------------------------------------

_ORIG_CREATE = Completions.create


def _extract(kwargs: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    system, user = "", ""
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
    js = rf.get("json_schema") if isinstance(rf, dict) else None
    name = str(js.get("name")) if isinstance(js, dict) and js.get("name") else ""
    block_ids = M.BLOCK_ID_RE.findall(user) or M.BLOCK_ID_RE.findall(system)
    batch = list(dict.fromkeys(M.BATCH_CHECK_RE.findall(user)))
    single = M.CHECK_ID_RE.search(user)
    ids = batch or ([single.group(1)] if single else [])
    return name, ids, block_ids


def _ns(content: str) -> Any:
    return NS(choices=[NS(message=NS(content=content), finish_reason="stop")])


def _fixed_non_search(name: str) -> Any:
    if name == "classification_output":
        content = json.dumps({
            "bundle_id": "merged", "material_type": "articles_of_association",
            "mixed": False, "confidence": 0.9,
            "reason": "qa-perf 固定分类响应", "source_block_ids": [],
        }, ensure_ascii=False)
    elif name == "vision_match_output":
        content = json.dumps({"bundle_id": "w0", "check_item_id": "",
                              "matches": []}, ensure_ascii=False)
    else:
        content = json.dumps({"bundle_id": "w0", "check_results": []},
                             ensure_ascii=False)
    return _ns(content)


def _dynamic_search(ids: list[str], block_ids: list[str], policy: str) -> Any:
    if policy == "all":
        refs = block_ids
    elif policy == "first_last":
        refs = [block_ids[0], block_ids[-1]] if len(block_ids) > 1 else block_ids[:1]
    else:
        refs = block_ids[:1]
    crs = []
    for cid in ids:
        crs.append({
            "check_item_id": cid,
            "outcome": "found",
            "evidence": [{
                "source_refs": [{"block_id": b, "start_char": None,
                                 "end_char": None} for b in refs],
                "relation_status": "matched",
                "relevance_reason": "qa-perf 固定响应（按请求内真实检查项清单构造）",
            }],
        })
    return _ns(json.dumps({"bundle_id": "w0", "check_results": crs},
                          ensure_ascii=False))


def _patched_create(self: Any, **kwargs: Any) -> Any:
    name, ids, block_ids = _extract(kwargs)
    if name != "text_search_output":
        return _fixed_non_search(name)
    # C 组：窗口 1 超时耗尽（与 dev-backend 自测同口径的进程内注入）
    if CASE.get("timeout_first_block") and block_ids \
            and block_ids[0] == CASE["timeout_first_block"]:
        time.sleep(0.02)
        raise RuntimeError("QA injected transient timeout")
    # 真实 HTTP 到达模拟服务：产生 arrived_at / peak_inflight / barrier 放行统计
    resp = _ORIG_CREATE(self, **kwargs)
    if CASE.get("dynamic_search"):
        return _dynamic_search(ids, block_ids, CASE.get("refs_policy", "first"))
    return resp


Completions.create = _patched_create


def _cfg_barrier_off(label: str, delay_ms: int = 5) -> dict[str, Any]:
    return {
        "schema_version": "qa-mock-llm-config-1",
        "group": label,
        "host": "127.0.0.1", "port": MOCK_PORT,
        "stats_out": f"/tmp/qa_mock_{label}.json",
        "tag_header": "X-QA-Tag",
        "default_delay_ms": delay_ms,
        "timeout_hang_seconds": 3.0,
        "truncate_ratio": 0.6,
        "expected_request_count": None,
        "default_inject": None,
        "barrier": {"enabled": False, "size": 0,
                    "release_order": "as_arrived", "release_gap_ms": 0,
                    "wait_timeout_seconds": 30, "check_item_order": []},
        "rules": [{
            "name": f"{label}.text_search",
            "when": {"schema_name": "text_search_output"},
            "delay_ms": delay_ms,
            "response": {
                "bundle_id": "{{BUNDLE}}",
                "check_results": [{
                    "check_item_id": "{{CHECK_ID}}",
                    "outcome": "found",
                    "evidence": [{
                        "source_refs": [{"block_id": "{{BLOCK:0}}",
                                        "start_char": None, "end_char": None}],
                        "relation_status": "matched",
                        "relevance_reason": f"qa-perf {label} 固定响应",
                    }],
                }],
            },
        }],
    }


class MockService:
    def __init__(self) -> None:
        self.state = M.ServerState(_cfg_barrier_off("boot"), None, None, "X-QA-Tag")
        self.server = M.QAServer(("127.0.0.1", MOCK_PORT), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.configs: dict[str, Any] = {}

    def configure(self, label: str, cfg: dict[str, Any]) -> None:
        self.configs[label] = cfg
        self.state = M.ServerState(cfg, None, f"/tmp/qa_mock_{label}.json",
                                   "X-QA-Tag")
        self.server.state = self.state

    def stats(self, label: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = self.state.snapshot()
        snap["case_label"] = label
        if extra:
            snap.update(extra)
        return snap

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------------------
# 跑一个 case
# ---------------------------------------------------------------------------

def _run_case(svc: MockService, label: str, cfg: dict[str, Any], *,
              check_ids: list[str], x: int,
              texts: list[str] | None = None, real_ocr: str | None = None,
              small_window: bool = False,
              case_overrides: dict[str, Any] | None = None,
              accept_all: bool = False) -> dict[str, Any]:
    svc.configure(label, cfg)
    CASE.clear()
    CASE.update({"dynamic_search": False, "refs_policy": "first",
                 "timeout_first_block": None})
    if case_overrides:
        CASE.update(case_overrides)

    if real_ocr:
        task_id, file_id = _create_realocr(label, real_ocr)
        block_ids: list[str] = []
    else:
        task_id, file_id, block_ids = _create_synthetic(label, texts or SYNTH_TEXTS)
    # 超时注入按 w1 首块（overlap 窗口 w1=[b1,b2]）
    if CASE.get("timeout_window") and block_ids:
        CASE["timeout_first_block"] = block_ids[1]

    run_id = _create_run(task_id, file_id, check_ids)
    orig = (settings.CHECKS_PER_REQUEST, settings.LLM_WINDOW_CHARACTERS,
            settings.LLM_WINDOW_OVERLAP_CHARACTERS)
    error = None
    try:
        settings.CHECKS_PER_REQUEST = x
        if small_window:
            settings.LLM_WINDOW_CHARACTERS = 45
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = 10
        pipeline_mod.run_pipeline.func(str(run_id))
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:400]
    finally:
        settings.CHECKS_PER_REQUEST, settings.LLM_WINDOW_CHARACTERS, \
            settings.LLM_WINDOW_OVERLAP_CHARACTERS = orig

    if accept_all:
        _accept_all(task_id, run_id)
    export = _export(task_id, run_id)
    return {
        "label": label, "task_id": str(task_id), "run_id": str(run_id),
        "input_revision": 0, "x": x, "real_ocr": bool(real_ocr),
        "block_ids": block_ids, "pipeline_exception": error,
        "export": export,
        "stats": svc.stats(label, {
            "window_count": ((export["run_config"] or {}).get("batch", {})
                             .get("batches") or [{}])[0].get("window_count"),
            "check_item_count": len(check_ids),
            "checks_per_request": x,
        }),
    }


# ---------------------------------------------------------------------------
# B 组三类去重结构断言（用真实 DB 行计算，不写推算值）
# ---------------------------------------------------------------------------

def _dedup_summary(x1: dict[str, Any], x3: dict[str, Any]) -> dict[str, Any]:
    rows = [r for r in x1["export"]["rows"] if r["kind"] == "text"]
    per_check: dict[str, int] = {}
    for r in rows:
        per_check[r["check_item_id"]] = per_check.get(r["check_item_id"], 0) + 1
    # 同一检查项内，同一出处块只存 1 条（跨窗口重复引用去重）
    per_pair: dict[tuple[str, str], int] = {}
    for r in rows:
        for b in r["source_block_ids"]:
            key = (r["check_item_id"], b)
            per_pair[key] = per_pair.get(key, 0) + 1
    cross_window_dedup = all(v == 1 for v in per_pair.values()) and len(per_pair) > 0
    # 同文不同出处：相同 text_sha256 但不同 source_block_ids 的行 >= 2
    same_text: dict[str, set[str]] = {}
    for r in rows:
        if r["text_sha256"]:
            same_text.setdefault(r["text_sha256"], set()).update(r["source_block_ids"])
    different_source_kept = any(len(v) >= 2 for v in same_text.values())
    # 同块多检查项：同一 block_id 出现在 >= 2 个检查项
    block_checks: dict[str, set[str]] = {}
    for r in rows:
        for b in r["source_block_ids"]:
            block_checks.setdefault(b, set()).add(r["check_item_id"])
    multi_check_preserved = any(len(v) >= 2 for v in block_checks.values())
    return {
        "status": "measured",
        "method": "三类去重/引用情形全部由本脚本读取真实 Result / ResultSource 行计算，非推算",
        "x1_text_rows": len(rows),
        "x3_text_rows": len([r for r in x3["export"]["rows"] if r["kind"] == "text"]),
        "per_check_text_rows_x1": per_check,
        "distinct_check_block_pairs": len(per_pair),
        "cross_window_duplicate_dedup_to_single": bool(cross_window_dedup),
        "same_text_different_source_kept": bool(different_source_kept),
        "same_block_multi_check_preserved": bool(multi_check_preserved),
        "x1_x3_result_sets_equal": _result_set(x1["export"]) == _result_set(x3["export"]),
        "text_sha256_distinct_count": len(same_text),
        "note": "X=1 与 X=3 均引用窗口内全部块；跨窗口重叠块在同一检查项内只存 1 条。",
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(HERE / "mock_config.a_c2_refill_4.json"))
    p.add_argument("--ocr-json", default=str(HERE / "ocr15.json"))
    p.add_argument("--out-dir", default="/tmp/qa_qa_evidence")
    args = p.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    setup: dict[str, Any] = {
        "schema_version": "qa-quick-acceptance-setup-1",
        "ran_at": _now(),
        "scope": "qa-perf 独立实跑：HTTP 模拟服务 + 真实 pipeline，零真实模型/零外部 OCR",
        "protected_tasks": PROTECTED,
        "config_observed": {
            "CHECKS_PER_REQUEST": settings.CHECKS_PER_REQUEST,
            "LLM_MAX_IN_FLIGHT": settings.LLM_MAX_IN_FLIGHT,
            "LLM_API_BASE": settings.LLM_API_BASE,
            "LLM_REQUEST_TIMEOUT_SECONDS": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "note": "LLM_API_BASE 在进程内指向 HTTP 模拟服务；.env 与配置文件均未改动；"
                    "LLM_MAX_IN_FLIGHT 沿用 .env 的 2（模块 import 时固化，未改）",
        },
        "protected_before": _protected(),
        "cases": {},
        "soft_delete_pending": [],
        "blockers": [],
    }
    svc = MockService()
    created: list[tuple[str, uuid.UUID]] = []

    def remember(case: dict[str, Any]) -> dict[str, Any]:
        created.append((case["label"], uuid.UUID(case["task_id"])))
        setup["cases"][case["label"]] = {
            "task_id": case["task_id"], "run_id": case["run_id"],
            "input_revision": case["input_revision"], "x": case["x"],
        }
        return case

    try:
        # ---- A 组：4 请求 / C=2 / 打乱放行 / 一快一慢 ---------------------
        cfg_a = json.loads(Path(args.config).read_text(encoding="utf-8"))
        a = _run_case(svc, "A-concurrency", cfg_a, check_ids=C2, x=1,
                      texts=SYNTH_TEXTS, small_window=True)
        remember(a)
        _write(out / "a_stats.json", a["stats"])
        _write(out / "a_results.json", a["export"])
        _write(out / "a_units.json", {
            "unit_order_expected": ["c1/w0", "c1/w1", "c2/w0", "c2/w1"],
            "block_ids": a["block_ids"],
            "text_search_request_count": sum(
                1 for r in a["stats"]["requests"]
                if r.get("schema_name") == "text_search_output"),
            "pipeline_exception": a["pipeline_exception"],
        })
        trace_a = Path("/data/perf_traces") / f"{a['run_id']}.jsonl"
        (out / "a_trace.jsonl").write_text(
            trace_a.read_text(encoding="utf-8") if trace_a.is_file() else "",
            encoding="utf-8")
        setup["cases"]["A-concurrency"]["trace_jsonl_path"] = str(trace_a)

        # ---- B-req：真实 15 页 OCR，X=1 vs X=3 ----------------------------
        ocr = args.ocr_json
        ocr_meta = {"path": ocr, "exists": Path(ocr).is_file()}
        if ocr_meta["exists"]:
            ocr_meta["sha256"] = hashlib.sha256(
                Path(ocr).read_bytes()).hexdigest()
            ocr_meta["sha256_matches_fixed_constant"] = ocr_meta["sha256"] == OCR_SHA
        b_x1 = _run_case(svc, "B-real-x1", _cfg_barrier_off("b_real_x1"),
                         check_ids=C3, x=1, real_ocr=ocr,
                         case_overrides={"dynamic_search": True,
                                         "refs_policy": "first"})
        remember(b_x1)
        b_x3 = _run_case(svc, "B-real-x3", _cfg_barrier_off("b_real_x3"),
                         check_ids=C3, x=3, real_ocr=ocr,
                         case_overrides={"dynamic_search": True,
                                         "refs_policy": "first"})
        remember(b_x3)
        _write(out / "b_x1_stats.json", b_x1["stats"])
        _write(out / "b_x3_stats.json", b_x3["stats"])
        _write(out / "b_x1_results.json", b_x1["export"])
        _write(out / "b_x3_results.json", b_x3["export"])

        # ---- B-dedup：合成块三类去重样本，X=1 vs X=3 ---------------------
        d_x1 = _run_case(svc, "B-dedup-x1", _cfg_barrier_off("b_dedup_x1"),
                         check_ids=C3, x=1, texts=SYNTH_TEXTS_DEDUP,
                         small_window=True,
                         case_overrides={"dynamic_search": True,
                                         "refs_policy": "all"})
        remember(d_x1)
        d_x3 = _run_case(svc, "B-dedup-x3", _cfg_barrier_off("b_dedup_x3"),
                         check_ids=C3, x=3, texts=SYNTH_TEXTS_DEDUP,
                         small_window=True,
                         case_overrides={"dynamic_search": True,
                                         "refs_policy": "all"})
        remember(d_x3)
        _write(out / "b_dedup_x1_results.json", d_x1["export"])
        _write(out / "b_dedup_x3_results.json", d_x3["export"])
        _write(out / "b_dedup_summary.json", _dedup_summary(d_x1, d_x3))
        setup["ocr_json"] = ocr_meta
        setup["B_real_ocr"] = {
            "x1_request_count": sum(1 for r in b_x1["stats"]["requests"]
                                    if r.get("schema_name") == "text_search_output"),
            "x3_request_count": sum(1 for r in b_x3["stats"]["requests"]
                                    if r.get("schema_name") == "text_search_output"),
            "result_sets_equal": _result_set(b_x1["export"]) == _result_set(b_x3["export"]),
        }

        # ---- C：窗口0 成功、窗口1 超时耗尽 / 正常样本 --------------------
        c_partial = _run_case(svc, "C-partial", _cfg_barrier_off("c_partial"),
                              check_ids=C1, x=1, texts=SYNTH_TEXTS,
                              small_window=True,
                              case_overrides={"timeout_window": True})
        remember(c_partial)
        c_ok = _run_case(svc, "C-ok", _cfg_barrier_off("c_ok"),
                         check_ids=C1, x=1, texts=SYNTH_TEXTS,
                         small_window=True, accept_all=True)
        remember(c_ok)
        _write(out / "c_partial_results.json", c_partial["export"])
        _write(out / "c_ok_results.json", c_ok["export"])
        setup["C_partial"] = {
            "task_id": c_partial["task_id"], "run_id": c_partial["run_id"],
            "input_revision": 0,
        }
        setup["C_ok"] = {
            "task_id": c_ok["task_id"], "run_id": c_ok["run_id"],
            "input_revision": 0,
        }
        setup["status"] = "measured"
    except Exception as exc:  # noqa: BLE001
        import traceback
        setup["status"] = "blocked"
        setup["blockers"].append({
            "error": f"{type(exc).__name__}: {exc}"[:800],
            "traceback": traceback.format_exc()[-2500:],
            "note": "未完成字段保持缺失，不填推算值",
        })
    finally:
        setup["protected_after"] = _protected()
        setup["protected_unchanged"] = (
            setup["protected_before"] == setup["protected_after"])
        setup["soft_delete_pending"] = [str(tid) for _, tid in created]
        setup["soft_delete_note"] = (
            "隔离任务暂不软删：C 组 HTTP 完成接口断言与 Chrome 真实页面需要任务可读；"
            "由宿主机在两者完成后统一 psql 软删（deleted_at），ocr_* / run / results 保留可追溯")
        svc.close()

    _write(out / "setup.json", setup)
    _write(out / "runtime_configs.json", svc.configs)
    _write(out / "protected_snapshot.json", {
        "before": setup["protected_before"], "after": setup["protected_after"],
        "unchanged": setup["protected_unchanged"],
    })
    sys.stdout.write(json.dumps({
        "status": setup["status"],
        "out_dir": str(out),
        "cases": list(setup["cases"]),
        "blockers": setup["blockers"],
        "protected_unchanged": setup["protected_unchanged"],
        "B_real_ocr": setup.get("B_real_ocr"),
    }, ensure_ascii=False, indent=2) + "\n")
    return 0 if setup["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
