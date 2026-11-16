#!/usr/bin/env python3
"""QA 性能试验 · 失败回传故障注入（资产 4）。

覆盖三种注入
------------
* ``auth_401``    —— OpenAI AuthenticationError -> LLMFatalError
* ``format_error``—— 合法 JSON 但 schema 校验失败 -> 触发 _repair 一次 -> LLMFormatError
* ``timeout``     —— OpenAI APITimeoutError -> LLMTransientError -> 窗口级重试耗尽

注入点：仅 ``text_search_output`` 的 ``charter.business_scope`` 窗口 1；
窗口 0 返回正常命中，用于验证「失败时保留已采集证据」。
分类与视觉阶段返回固定正常响应，**不调用任何真实模型 / 外部 OCR**。

断言口径
--------
每个 case 跑一个隔离 run（同步 ``run_pipeline.func``，不经队列），然后读真实 DB：
``processing_runs`` 状态 / ``run_steps`` 阶段与检查项状态 / ``results`` 与
``result_sources`` 是否保留窗口 0 的摘录。脚本把 **实测值** 写进 ``observed``，
把「修复后应达到」写进 ``expected``，``verdict`` 统一标注「待实现后补跑」——
当前 HEAD 的已知缺口会被如实暴露，但不当成最终验收结论。

附带静态检查
------------
``--check-baseline-only`` 在**宿主机**只读检查 ``scripts/baseline_serial.py``：
其 ``status`` 判定只看脚本层 ``evidence['blockers']``，没有读
``processing_runs.state``；当 run 业务落库为 FAILED 而 ``run_pipeline.func``
正常返回时，脚本仍会标 ``measured`` 且退出码 0。这是团长点名要修的问题。

用法
----
    # 1) 宿主机：只读静态检查（不连 DB、不造数据）
    python3 backend/tests/perf/fault_injection.py --check-baseline-only \
        --baseline-script scripts/baseline_serial.py \
        --out backend/tests/perf/evidence/baseline_exit_contract.json

    # 2) worker 容器：实跑三种注入（造隔离数据，跑完软删）
    docker cp "<15页OCR JSON>" credit-review-app-worker-1:/tmp/qa_fault_ocr_slice.json
    docker exec -i credit-review-app-worker-1 python - \
        --run-cases --evidence-out /tmp/qa_fault_injection.json \
        < backend/tests/perf/fault_injection.py > /tmp/qa_fault_stdout.json
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BLOCK_ID_RE = re.compile(
    r"block_id=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
CHECK_ID_RE = re.compile(r"检查项：.*?（id=([A-Za-z0-9_.\-]+)")
OCR_JSON_SHA256 = "8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b"
OCR_JSON_PAGE_COUNT = 15
PROTECTED_TASK_IDS = [
    "607e6d41-4d47-4582-a5ad-07313b6c17bd",
    "ee59108d-e4f1-4aa8-bf2e-afe07d457384",
]
TARGET_CHECK_ID = "charter.business_scope"
CASES = ("auth_401", "format_error", "timeout")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_str(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _emit(evidence: dict[str, Any], out_path: str | None,
          container_out: str | None = None) -> None:
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n"
    if container_out:
        try:
            p = Path(container_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[fault] 容器内落盘失败: {exc}\n")
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 模式 A：宿主机只读静态检查 baseline_serial.py 的退出码契约
# ---------------------------------------------------------------------------


def check_baseline_exit_contract(script_path: str) -> dict[str, Any]:
    """静态检查（AST + 文本），不执行基线、不连 DB、不造数据。"""
    path = Path(script_path)
    if not path.is_file():
        return {
            "status": "file_not_found",
            "script_path": str(path),
            "note": "未找到脚本，未做任何推断；请在项目根目录传 --baseline-script",
        }
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    findings: list[dict[str, Any]] = []

    def add(name: str, found: bool, detail: str) -> None:
        findings.append({"name": name, "found": found, "detail": detail})

    # 1) 找 main() 的 return 语句
    returns: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    returns.append(ast.unparse(sub.value))
    add("main() 的退出码表达式", bool(returns), f"returns={returns}")

    # 2) status 赋值是否依赖 processing_runs.state
    status_assignments = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name)
            and t.value.id == "evidence"
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == "status"
            for t in n.targets
        )
    ]
    add("status 赋值语句", bool(status_assignments),
        f"assignments={status_assignments}")

    reads_run_state = bool(re.search(
        r"(ProcessingRun|run_view|run_read).{0,80}\bstate\b|"
        r"\[\s*[\"']state[\"']\s*\]\s*(==|!=|in\b)",
        source,
    ))
    add("脚本读取 run 落库 state 用于 status/退出码判定",
        reads_run_state,
        "找到 run state 读取" if reads_run_state else "未找到对 processing_runs.state 的判定")

    blockers_only = bool(re.search(r"not\s+evidence\[[\"']blockers[\"']\]", source))
    add("status 只由 evidence['blockers'] 决定", blockers_only,
        "status = 'measured' if not evidence['blockers'] else ..." if blockers_only
        else "未匹配到该模式")

    return_zero_on_measured = any(
        "measured" in r and ("probe_only" in r or "0" in r) for r in returns
    )
    add("measured 状态返回 0", return_zero_on_measured,
        "退出码表达式包含 measured -> 0" if return_zero_on_measured
        else "未匹配到")

    has_failed_status = bool(re.search(
        r"evidence\[[\"']status[\"']\]\s*=\s*[\"']failed[\"']", source
    ))
    add("存在 status='failed' 分支", has_failed_status,
        "失败 run 会被显式标 failed" if has_failed_status else "未匹配到")
    nonzero_return_exists = any(r.strip() == "1" or "return 1" in r for r in returns)
    add("存在非 0 退出码", nonzero_return_exists,
        f"returns={returns}")

    if blockers_only and not reads_run_state and return_zero_on_measured:
        verdict = "still_buggy"
        conclusion = (
            "确认：baseline_serial.py 的 status 判定只看脚本层 blockers（run_pipeline.func 是否抛异常），"
            "没有读 processing_runs.state。当 _search_stage 因 LLM_FATAL 走 return（不抛异常）把 run "
            "业务落库为 FAILED 时，脚本仍会标 measured 且退出码 0 —— 即团长点名的「失败 run 标 measured、退出码 0」问题。"
        )
    elif reads_run_state and has_failed_status and nonzero_return_exists and not blockers_only:
        verdict = "fixed"
        conclusion = (
            "静态复核：新版 baseline_serial.py 已读取 run 落库 state / coverage_complete 与阶段状态矛盾，"
            "存在显式 status='failed' 分支和非 0 退出码，且 status 不再只由 evidence['blockers'] 决定。"
            "团长点名的「失败 run 标 measured、退出码 0」问题在源码层已修复。"
            "注意：这只是静态检查，真正闭环仍需实现后在隔离 run 上实跑基线并核对退出码。"
        )
    else:
        verdict = "inconclusive"
        conclusion = (
            "未同时匹配到「仍有问题」或「已修复」的特征组合；本检查不做推断结论，请人工复核脚本。"
            f" reads_run_state={reads_run_state} has_failed_status={has_failed_status} "
            f"nonzero_return_exists={nonzero_return_exists} blockers_only={blockers_only}"
        )
    return {
        "status": "checked",
        "method": "AST + 正则静态检查，未执行基线、未连 DB、未造数据、未触发外部服务",
        "script_path": str(path),
        "script_sha256": _sha256_str(source),
        "verdict": verdict,
        "findings": findings,
        "conclusion": conclusion,
        "expected_fix": (
            "基线脚本应在跑批后读 processing_runs.state；state != READY 时把 status 标 failed "
            "并返回非 0 退出码，同时保留已落库的 results / run_steps 供追溯。"
        ),
    }


# ---------------------------------------------------------------------------
# 模式 B：worker 容器内实跑三种注入
# ---------------------------------------------------------------------------


def _build_expected(case: str) -> dict[str, Any]:
    base = {
        "verdict": "待实现后补跑（当前 HEAD 存在已知缺口，observed 为实测值，非验收结论）",
        "failure_must_preserve_window0_evidence": True,
        # 架构师时序提醒：T02（第一步四项前置）阶段 _search_stage 的 LLM_FATAL 分支
        # 不写 found，window0 证据仍丢；T03 接入「先回先存」后才成立。
        "evidence_preservation_effective_after": "T03",
        "evidence_preservation_note": (
            "T02 阶段只能断言「JSONL trace / 基线脚本 evidence 保留观测证据」；"
            "T03 接入先回先存后，window0 单元完成即独立短会话写 Result+ResultSource，断言才落到 results/result_sources。"
        ),
        "failure_must_not_be_labeled": ["no_matching_evidence"],
        "stage_and_check_step_states_consistent": True,
        "retries_counted_in_same_quota": True,
    }
    if case == "auth_401":
        base.update({
            "expected_run_state": "FAILED",
            "expected_run_error_code_contains": "SEARCH_FAILED",
            "expected_stage_search_state": "FAILED",
            # 改 raise 后 stage:vision 的 _touch_step(RUNNING) 根本不执行，
            # 断言形式应为「RunStep 中不存在该 step_key 行」，不是 state 字符串。
            "expected_stage_vision_step_absent": True,
            "expected_check_step_state": "FAILED",
            "expected_check_step_last_error_code": "LLM_FATAL",
            "expected_complete_task_status": 409,
            # 架构师定稿：run FAILED 时 complete_task 第一道拦截就返回 RUN_NOT_READY，
            # 根本走不到 COVERAGE_INCOMPLETE 那道；不可写成 COVERAGE_INCOMPLETE。
            "expected_complete_task_code": "RUN_NOT_READY",
            "complete_task_code_note": (
                "致命失败（run FAILED）优先于覆盖判定；COVERAGE_INCOMPLETE 仅在 "
                "run READY 且 coverage_complete=false 时出现。"
            ),
            "note": "致命错误应立即停止该检查项后续派发；已采集的窗口 0 证据仍需保留。",
        })
    else:
        base.update({
            "expected_run_state": "READY",
            "expected_run_coverage_complete": False,
            "expected_run_record_coverage_incomplete": True,
            "expected_affected_check_reason": "coverage_incomplete",
            "expected_stage_search_state": "SUCCEEDED（但 run 覆盖不全，需有独立标识）",
            "expected_check_step_state": "需记录未覆盖窗口，不得与全成功同态",
            "expected_complete_task_status": 409,
            # 断言值统一为纯字面量，供 #7 用 == 严格相等；来源说明放独立 note 字段
            "expected_complete_task_code": "COVERAGE_INCOMPLETE",
            "complete_task_code_note": (
                "COVERAGE_INCOMPLETE 由架构师定值（PM 明确以架构师定值为准）；"
                "仅在 run READY 且 coverage_complete=false 时出现。"
            ),
            "note": (
                "格式失败 / 超时耗尽属于「技术失败导致窗口未覆盖」，"
                "不得写成正常「未找到」；只要存在未覆盖窗口，run.coverage_complete 必须为 false。"
            ),
        })
    return base


def run_cases(ocr_json_path: str, evidence_out: str | None,
              keep_task: bool) -> dict[str, Any]:
    """在 worker 容器内执行；业务 import 全部延迟到本函数内部。"""
    # -- 延迟 import：保证宿主机 --check-baseline-only 不需要业务依赖 ---------
    import httpx
    import openai
    from openai.resources.chat.completions import Completions
    from sqlmodel import Session, select
    from types import SimpleNamespace

    from app.checklist import checklist_hash, get_checklist
    from app.cli import import_ocr_json
    from app.core.db import engine
    from app.models import (
        ProcessingRun, Result, ResultSource, RunFile, RunStep, Task, TaskFile, User,
    )
    from app.processing_pipeline import run_pipeline

    evidence: dict[str, Any] = {
        "schema_version": "qa-fault-injection-1",
        "ran_at": _now_iso(),
        "status": "running",
        "scope": (
            "401 / 格式失败 / 超时三种注入；全部 LLM 调用由本地 monkeypatch 接管，"
            "未调用真实模型、未调用外部 OCR、未改业务代码"
        ),
        "protected_real_tasks": PROTECTED_TASK_IDS,
        "cases": {},
        "blockers": [],
    }

    def read_protected() -> dict[str, Any]:
        with Session(engine) as s:
            out = {}
            for tid in PROTECTED_TASK_IDS:
                row = s.get(Task, uuid.UUID(tid))
                out[tid] = {
                    "state": row.state if row else None,
                    "deleted_at": row.deleted_at.isoformat()
                    if row and row.deleted_at else None,
                }
            return out

    evidence["protected_before"] = read_protected()

    raw = Path(ocr_json_path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != OCR_JSON_SHA256:
        raise RuntimeError(f"OCR JSON SHA256 不匹配：{digest}")
    pages = json.loads(raw.decode("utf-8"))
    if len(pages) != OCR_JSON_PAGE_COUNT:
        raise RuntimeError("OCR JSON 不是 15 页")
    evidence["ocr_json"] = {
        "container_path": ocr_json_path,
        "sha256": digest,
        "page_count": len(pages),
    }

    # -- 观测器：逐次 _chat 记录（含重试），用于「重试计入同一额度」 ---------
    call_log: list[dict[str, Any]] = []
    # window_index 按 (schema_name, check_item_id) 分组从 0 编号；
    # 否则分类的两个窗口会挤占搜索窗口序号，注入点 window_index==1 永不命中。
    window_index_by_key: dict[str, int] = {}
    group_window_count: dict[str, int] = {}
    active_case = {"name": ""}

    def classify_request(kwargs: dict[str, Any]) -> tuple[str, str | None, int, list[str]]:
        rf = kwargs.get("response_format") or {}
        schema = "unknown"
        if isinstance(rf, dict):
            js = rf.get("json_schema")
            if isinstance(js, dict) and js.get("name"):
                schema = str(js["name"])
            elif rf.get("type"):
                schema = str(rf["type"])
        user = ""
        for m in kwargs.get("messages") or []:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                user = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        ids = BLOCK_ID_RE.findall(user)
        wh = _sha256_str("\n".join(ids))
        m = CHECK_ID_RE.search(user)
        check_id = m.group(1) if m else None
        group_key = f"{schema}|{check_id or '-'}"
        key = f"{group_key}|{wh}"
        if key not in window_index_by_key:
            idx = group_window_count.get(group_key, 0)
            window_index_by_key[key] = idx
            group_window_count[group_key] = idx + 1
        return schema, check_id, window_index_by_key[key], ids

    def ok_response(content: str) -> Any:
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop"
            )]
        )

    def classification_response() -> Any:
        return ok_response(json.dumps({
            "bundle_id": "merged",
            "material_type": "articles_of_association",
            "mixed": False,
            "confidence": 0.9,
            "reason": "QA 故障注入：固定分类响应",
            "source_block_ids": [],
        }, ensure_ascii=False))

    def normal_search_response(check_id: str, block_ids: list[str],
                               found: bool) -> Any:
        results = []
        if found and block_ids:
            results = [{
                "check_item_id": check_id,
                "outcome": "found",
                "evidence": [{
                    "source_refs": [{
                        "block_id": block_ids[0],
                        "start_char": None, "end_char": None,
                    }],
                    "relation_status": "matched",
                    "relevance_reason": "QA 故障注入：窗口 0 正常命中，用于验证证据保留",
                }],
            }]
        else:
            results = [{
                "check_item_id": check_id,
                "outcome": "not_found",
                "evidence": [],
            }]
        return ok_response(json.dumps({
            "bundle_id": "window-0", "check_results": results,
        }, ensure_ascii=False))

    request = httpx.Request("POST", "http://qa-mock-local/chat/completions")
    original_create = Completions.create

    def raise_401() -> None:
        resp = httpx.Response(
            401, request=request,
            json={"error": {"message": "QA injection 401",
                            "type": "invalid_request_error",
                            "code": "invalid_api_key"}},
        )
        raise openai.AuthenticationError(
            "QA injection 401", response=resp, body=None
        )

    # 注入点说明（T01/T02 后）：
    # 真实 HTTP 请求点是 LLMClient._chat 里的 self._client.chat.completions.create(**kwargs)。
    # 新版 _chat 返回 (content, finish_reason) 元组、complete_json 兼容只返回 str 的旧包装器；
    # 本脚本 patch 的是更底层的 Completions.create，返回带
    # choices[0].message.content + finish_reason 的响应对象，新 _chat 仍从同一位置取 content，
    # 因此签名/返回值变化不影响本注入器；若改 patch _chat，需返回 (json字符串, "stop")。
    def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        schema, check_id, window_index, block_ids = classify_request(kwargs)
        case = active_case["name"]
        seq = len(call_log) + 1
        entry: dict[str, Any] = {
            "seq": seq,
            "case": case,
            "schema_name": schema,
            "check_item_id": check_id,
            "window_index": window_index,
            "block_id_count": len(block_ids),
            "result": "ok",
        }
        call_log.append(entry)
        try:
            # LLMClient.complete_json 在 LLMFatalError 时会降级 json_object 再发一次；
            # 真实 401 服务端对该降级请求同样返回 401，这里必须一并注入，
            # 否则致命错误会被 mock 意外「修好」，掩盖真实行为。
            if active_case.get("pending_401_downgrade"):
                active_case["pending_401_downgrade"] = False
                entry["result"] = "injected_401_downgrade"
                raise_401()
            if schema == "classification_output":
                return classification_response()
            if schema == "vision_match_output":
                return ok_response(json.dumps({
                    "bundle_id": "window-0",
                    "check_item_id": check_id or "unknown",
                    "matches": [],
                }, ensure_ascii=False))
            if schema in ("json_object", "unknown"):
                # json_schema 降级或格式修复请求：按 case 决定
                if case == "format_error":
                    entry["result"] = "format_error_repair"
                    return ok_response('{"bad": "shape"}')
                return normal_search_response(check_id or TARGET_CHECK_ID, block_ids, False)

            is_target = (
                schema == "text_search_output"
                and check_id == TARGET_CHECK_ID
                and window_index == 1
            )
            if is_target and case == "auth_401":
                entry["result"] = "injected_401"
                active_case["pending_401_downgrade"] = True
                raise_401()
            if is_target and case == "timeout":
                entry["result"] = "injected_timeout"
                raise openai.APITimeoutError(request=request)
            if is_target and case == "format_error":
                entry["result"] = "injected_format_error"
                return ok_response('{"bad": "shape"}')
            # 其余：窗口 0 命中，其他检查项/窗口正常未找到
            found = (check_id == TARGET_CHECK_ID and window_index == 0)
            return normal_search_response(check_id or TARGET_CHECK_ID, block_ids, found)
        except (openai.AuthenticationError, openai.APITimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001
            entry["result"] = f"unexpected:{type(exc).__name__}"
            raise

    created_tasks: list[uuid.UUID] = []
    try:
        Completions.create = patched_create
        for case in CASES:
            active_case.clear()
            active_case["name"] = case
            call_log.clear()
            window_index_by_key.clear()
            group_window_count.clear()

            # 造隔离数据
            with Session(engine) as s:
                owner = s.exec(select(User).where(User.is_active == True)).first()  # noqa: E712
                task = Task(
                    owner_user_id=owner.id,
                    name=f"QA-PERF-故障注入-{case}",
                    product_code="working_capital_loan",
                    customer_role="borrower",
                    checklist_version="borrower-wcl-v1",
                    state="PROCESSING",
                    input_revision=0,
                )
                s.add(task)
                s.flush()
                task_id = task.id
                f = TaskFile(
                    task_id=task_id,
                    original_name="《北京银行股份有限公司章程》 切分15页.PDF",
                    media_type="application/pdf",
                    size_bytes=0,
                    sha256=_sha256_str(f"qa-fault-{case}"),
                    source_page_count=OCR_JSON_PAGE_COUNT,
                )
                s.add(f)
                s.flush()
                file_id = f.id
                checklist = get_checklist("borrower-wcl-v1")
                run = ProcessingRun(
                    task_id=task_id,
                    input_revision=0,
                    checklist_snapshot=checklist,
                    checklist_hash=checklist_hash("borrower-wcl-v1"),
                    model_snapshot={"text_model": "qa-mock", "vision_model": "qa-mock"},
                    state="QUEUED",
                )
                s.add(run)
                s.flush()
                run_id = run.id
                s.add(RunFile(run_id=run_id, file_id=file_id, task_id=task_id))
                s.commit()
            created_tasks.append(task_id)

            with contextlib.redirect_stdout(sys.stderr):
                import_ocr_json(str(file_id), ocr_json_path)

            t0 = time.perf_counter()
            pipeline_error: str | None = None
            try:
                run_pipeline.func(str(run_id))
            except Exception as exc:  # noqa: BLE001
                pipeline_error = f"{type(exc).__name__}: {exc}"[:400]
            elapsed = round(time.perf_counter() - t0, 3)

            # 读真实 DB 事实
            with Session(engine) as s:
                run_row = s.get(ProcessingRun, run_id)
                steps = s.exec(
                    select(RunStep).where(
                        RunStep.run_id == run_id, RunStep.task_id == task_id
                    ).order_by(RunStep.started_at, RunStep.step_key)
                ).all()
                results = s.exec(
                    select(Result).where(
                        Result.run_id == run_id, Result.task_id == task_id
                    ).order_by(Result.check_item_id, Result.rank)
                ).all()
                result_rows = []
                for r in results:
                    srcs = s.exec(
                        select(ResultSource).where(
                            ResultSource.result_id == r.id,
                            ResultSource.task_id == task_id,
                        )
                    ).all()
                    result_rows.append({
                        "check_item_id": r.check_item_id,
                        "kind": r.kind,
                        "not_found_reason": r.not_found_reason,
                        "rank": r.rank,
                        "text_length": len(r.text or ""),
                        "text_sha256": _sha256_str(r.text or "") if r.text else None,
                        "sources": [{
                            "source_page_number": x.source_page_number,
                            "location_precision": x.location_precision,
                            "block_id": str(x.block_id) if x.block_id else None,
                        } for x in srcs],
                    })

            target_rows = [x for x in result_rows
                           if x["check_item_id"] == TARGET_CHECK_ID]
            hit_rows = [x for x in target_rows if x["kind"] != "not_found"]
            observed = {
                "task_id": str(task_id),
                "file_id": str(file_id),
                "run_id": str(run_id),
                "pipeline_elapsed_seconds": elapsed,
                "pipeline_raised": pipeline_error,
                "run": {
                    "state": run_row.state if run_row else None,
                    "stage": run_row.stage if run_row else None,
                    "coverage_complete": run_row.coverage_complete if run_row else None,
                    "error_code": run_row.error_code if run_row else None,
                },
                "run_steps": [{
                    "step_key": st.step_key,
                    "state": st.state,
                    "attempt": st.attempt,
                    "last_error_code": st.last_error_code,
                    "elapsed_seconds": (
                        round((st.finished_at - st.started_at).total_seconds(), 3)
                        if st.started_at and st.finished_at else None
                    ),
                } for st in steps],
                "target_check_result_rows": target_rows,
                "target_hit_row_count": len(hit_rows),
                "window0_evidence_preserved": len(hit_rows) > 0,
                "target_not_found_reasons": [
                    x["not_found_reason"] for x in target_rows
                    if x["not_found_reason"]
                ],
                "total_result_rows": len(result_rows),
                "chat_call_log": [dict(x) for x in call_log],
                "chat_call_count": len(call_log),
                "retry_call_count": sum(
                    1 for x in call_log
                    if x["case"] == case
                    and x["check_item_id"] == TARGET_CHECK_ID
                    and x["window_index"] == 1
                ),
            }
            evidence["cases"][case] = {
                "injection": case,
                "expected": _build_expected(case),
                "observed": observed,
                "verdict": "待实现后补跑",
            }
        # 实测驱动的缺口汇总：只依据上面读到的真实 DB 值，不做推算
        # 断言口径按架构师定稿分流（T02 实跑后修订）：
        # * auth_401（致命失败，run FAILED）走 RUN_NOT_READY、不标覆盖不全，
        #   stage:vision 记录应不存在；窗口 0 证据保留属 T03「先回先存」后才成立。
        # * format_error / timeout（run READY）才是覆盖不全口径：
        #   coverage_complete=false + coverage_incomplete + 保留已成功窗口摘录。
        # 旧版把「auth_401 未标 coverage_incomplete / 证据未保留」误算成缺口，
        # 实际是定稿的预期行为，会把修复成果误判为失败。
        gaps: list[dict[str, Any]] = []
        t03_pending: list[dict[str, Any]] = []
        for case, block in evidence["cases"].items():
            o = block["observed"]
            step_keys = [s["step_key"] for s in o["run_steps"]]
            if case == "auth_401":
                if o["run"]["state"] != "FAILED":
                    gaps.append({
                        "case": case,
                        "gap": "致命错误未把 run 标为 FAILED",
                        "evidence": f"run.state={o['run']['state']}, "
                                    f"error_code={o['run']['error_code']}",
                    })
                if "stage:vision" in step_keys:
                    gaps.append({
                        "case": case,
                        "gap": "致命错误后仍创建了 stage:vision RunStep（应不存在）",
                        "evidence": f"run_steps={step_keys}",
                    })
                if "stage:search" in step_keys:
                    st = next(s for s in o["run_steps"] if s["step_key"] == "stage:search")
                    if st["state"] != "FAILED":
                        gaps.append({
                            "case": case,
                            "gap": "stage:search 未标 FAILED",
                            "evidence": f"state={st['state']}, error={st['last_error_code']}",
                        })
                if not o["window0_evidence_preserved"]:
                    t03_pending.append({
                        "case": case,
                        "item": "window0 已采集证据保留（T03 先回先存后才成立）",
                        "effective_after": "T03",
                        "evidence": f"target_result_rows={len(o['target_check_result_rows'])}, "
                                    f"run.state={o['run']['state']}",
                    })
                continue
            # 覆盖不全类
            if o["run"]["state"] != "READY":
                gaps.append({
                    "case": case,
                    "gap": "覆盖不全类不应把 run 标 FAILED",
                    "evidence": f"run.state={o['run']['state']}",
                })
            if o["run"]["coverage_complete"] is not False:
                gaps.append({
                    "case": case,
                    "gap": "存在未覆盖窗口但 run.coverage_complete 不为 False",
                    "evidence": f"run.state={o['run']['state']}, "
                                f"coverage_complete={o['run']['coverage_complete']}",
                })
            if "coverage_incomplete" not in o["target_not_found_reasons"]:
                gaps.append({
                    "case": case,
                    "gap": "受影响检查项未标记 coverage_incomplete",
                    "evidence": f"not_found_reasons={o['target_not_found_reasons']}, "
                                f"target_hit_rows={o['target_hit_row_count']}",
                })
            if not o["window0_evidence_preserved"]:
                gaps.append({
                    "case": case,
                    "gap": "失败时窗口 0 已采集的证据未被保留",
                    "evidence": f"target_result_rows={len(o['target_check_result_rows'])}",
                })
        evidence["known_gaps_observed"] = {
            "status": "以下均由本次实跑的真实 DB 读取得出，非推算；按架构师定稿分流断言口径",
            "count": len(gaps),
            "gaps": gaps,
        }
        evidence["t03_pending"] = {
            "status": "T02 阶段的预期局限，不计入缺口；T03 接入先回先存后需重跑闭环",
            "count": len(t03_pending),
            "items": t03_pending,
        }
        evidence["status"] = "measured"
    except Exception as exc:  # noqa: BLE001
        evidence["status"] = "blocked"
        evidence["blockers"].append(
            f"{type(exc).__name__}: {exc}"[:800]
        )
    finally:
        Completions.create = original_create
        if not keep_task:
            deleted: dict[str, str | None] = {}
            with Session(engine) as s:
                for tid in created_tasks:
                    row = s.get(Task, tid)
                    if row:
                        row.deleted_at = datetime.now(UTC)
                        s.add(row)
                        deleted[str(tid)] = row.deleted_at.isoformat()
                s.commit()
            evidence["soft_deleted_at"] = deleted
        evidence["protected_after"] = read_protected()
        evidence["protected_unchanged"] = (
            evidence["protected_before"] == evidence["protected_after"]
        )
    return evidence


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="失败回传故障注入用例")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-baseline-only", action="store_true",
                      help="宿主机只读静态检查基线脚本退出码契约")
    mode.add_argument("--run-cases", action="store_true",
                      help="worker 容器内实跑三种注入")
    parser.add_argument("--baseline-script", default="scripts/baseline_serial.py")
    parser.add_argument("--ocr-json", default="/tmp/qa_fault_ocr_slice.json")
    parser.add_argument("--evidence-out", default=None,
                        help="容器内证据落盘路径（--run-cases）")
    parser.add_argument("--out", default=None,
                        help="宿主机证据输出路径（--check-baseline-only）")
    parser.add_argument("--keep-task", action="store_true")
    args = parser.parse_args()

    if args.check_baseline_only:
        out = args.out or "backend/tests/perf/evidence/baseline_exit_contract.json"
        evidence = {
            "schema_version": "qa-baseline-exit-contract-1",
            "ran_at": _now_iso(),
            "baseline_contract": check_baseline_exit_contract(args.baseline_script),
        }
        _emit(evidence, out)
        return 0

    evidence = run_cases(args.ocr_json, args.evidence_out, args.keep_task)
    _emit(evidence, None, args.evidence_out)
    return 0 if evidence.get("status") == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
