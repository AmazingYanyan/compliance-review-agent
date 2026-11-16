#!/usr/bin/env python3
"""本轮三组快速验收 · 统一离线断言器（纯本机、纯标准库）。

定位
----
只消费「实跑落盘证据」，对 A / B / C 三组逐条断言，产出机器可读证据 JSON。
**绝不编造/推算任何数字**：所有请求数、峰值、时间戳、错误码一律来自输入证据；
没有输入证据的组/字段一律标「未跑」或「无法取得」并写明原因；沿用 T02 的
证据标「沿用」，不写成本轮新跑结果。

不连数据库、不调用真实模型、不碰容器、不改业务代码。本脚本自身可纯本机自检。

输入证据（均为实跑时由 QA 导出的 JSON，schema 见各 *_SPEC）
---------------------------------------------------------------
* ``--stats``         A 组：mock_llm_server.py --stats-out 落盘的 /__stats 统计
* ``--results``       A 组：落库结果导出（RESULT_SPEC）
* ``--trace``         A 组：/data/perf_traces/{run_id}.jsonl（可选，逐行 JSON）
* ``--x1-stats`` / ``--x3-stats``    B 组：X=1 / X=3 两次运行的 mock 统计
* ``--x1-results`` / ``--x3-results`` B 组：X=1 / X=3 两次运行的落库结果导出
* ``--complete``      C 组：完成接口响应 + 落库状态导出（COMPLETE_SPEC）
* ``--windowing-recheck``  B 组：仅当开发 Agent 本轮改动分窗排序时才传的
                           两次导入核对结论（WINDOWING_SPEC）；不传则分窗标「沿用」

RESULT_SPEC（落库结果导出）
    {"run_id": "<uuid>", "tag": "qa-run-A",
     "rows": [{"check_item_id": "...", "window_index": 0,
               "text_sha256": "...", "source_page_number": 7,
               "page_inner_seq": 0, "run_id": "<uuid>（可选）"}],
     "run_config": {"X": 1, "C": 2, ...}（可选）}

COMPLETE_SPEC（完成接口导出）
    {"partial_failure": {
        "status": 409, "detail_code": "COVERAGE_INCOMPLETE",
        "zero_write": true, "task_id_filtered": true,
        "kept_candidates": 1, "not_found_reason": "coverage_incomplete",
        "run_coverage_complete": false},
     "normal_complete": {
        "status": 200, "run_coverage_complete": true,
        "not_found_reason": "no_matching_evidence"}}
    所有字段值必须是实跑观测值，不得填推算值；缺失字段对应断言标「无法取得」。

WINDOWING_SPEC（可选）
    {"status": "checked", "import_a_b_equal": true, "source": "compare_two_imports.py"}

运行
----
    # 静态准备默认模式（无任何实跑输入）：产出「未跑」证据，不写假数字
    python3 backend/tests/perf/verify_quick_acceptance.py \
        --out backend/tests/perf/evidence/quick_acceptance.json

    # 纯本机合成自测（验证断言逻辑本身，非实测、不写正式证据）
    python3 backend/tests/perf/verify_quick_acceptance.py --self-test

    # 实跑信号下发后（示例）
    python3 backend/tests/perf/verify_quick_acceptance.py --group A \
        --stats /tmp/qa_mock_a_c2_refill_4.json \
        --results /tmp/qa_a_results.json --trace /tmp/qa_a_trace.jsonl \
        --out backend/tests/perf/evidence/quick_acceptance.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURE = HERE / "fixtures" / "quick_acceptance.json"
DEFAULT_OUT = HERE / "evidence" / "quick_acceptance.json"

# 断言状态枚举：实测通过 / 实测未通过 / 未跑 / 无法取得 / 沿用（不算本轮新跑）
PASS, FAIL, NOT_RUN, UNAVAILABLE, REUSED = "PASS", "FAIL", "未跑", "无法取得", "沿用"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _load_jsonl(path: str | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    try:
        rows = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        return rows
    except (OSError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _assertion(aid: str, title: str, status: str, detail: str,
               measured: bool, source: str) -> dict[str, Any]:
    return {
        "id": aid,
        "title": title,
        "status": status,
        "detail": detail,
        "measured": measured,
        "source": source,
    }


def _norm_rows(results: dict[str, Any] | None) -> list[tuple[Any, ...]]:
    """按 (check_item_id, text_sha256, source_page_number, 页内稳定序号) 归一化。"""
    if not results or not isinstance(results.get("rows"), list):
        return []
    out = []
    for row in results["rows"]:
        if not isinstance(row, dict):
            continue
        out.append((
            row.get("check_item_id"),
            row.get("text_sha256"),
            row.get("source_page_number"),
            row.get("page_inner_seq"),
        ))
    return sorted(out, key=lambda t: tuple(str(x) for x in t))


def _group_summary(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "PASS": sum(1 for a in assertions if a["status"] == PASS),
        "FAIL": sum(1 for a in assertions if a["status"] == FAIL),
        "未跑": sum(1 for a in assertions if a["status"] == NOT_RUN),
        "无法取得": sum(1 for a in assertions if a["status"] == UNAVAILABLE),
        "沿用": sum(1 for a in assertions if a["status"] == REUSED),
    }


# ---------------------------------------------------------------------------
# A 组
# ---------------------------------------------------------------------------

def run_group_A(fixture: dict[str, Any], stats: dict[str, Any] | None,
                results: dict[str, Any] | None,
                trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    cfg = fixture["group_A"]
    assertions: list[dict[str, Any]] = []

    # A1：快请求结束后下一条立即发出（慢请求仍在途）——只用真实时间戳
    a1_title = "A1 快请求结束后下一条立即发出（慢请求仍在途）"
    if not stats or not isinstance(stats.get("requests"), list) or not stats["requests"]:
        assertions.append(_assertion(
            "A1", a1_title, NOT_RUN,
            "未跑：缺 --stats 落盘统计（mock_llm_server.py --stats-out）。本轮静态准备不实跑，不写推算时间戳。",
            False, "stats.requests[] 落盘实测"))
    else:
        reqs = sorted(stats["requests"],
                      key=lambda r: float(r.get("arrived_monotonic_ms") or 0))
        # 规则名含 fast / slow 即可：实跑按 _search_stage 真实单元顺序把慢规则
        # 放在 c1 的第二个窗口（a.w1.c1.slow），不硬编码具体规则名。
        fast = next((r for r in reqs
                     if "fast" in str(r.get("matched_rule") or "")), None)
        slow = next((r for r in reqs
                     if "slow" in str(r.get("matched_rule") or "")), None)
        if not fast or not slow:
            assertions.append(_assertion(
                "A1", a1_title, UNAVAILABLE,
                "无法取得：stats 里未找到含 fast / slow 的 matched_rule（规则名缺失或配置未按预期命中）；不猜测哪条是快/慢请求。",
                False, "stats.requests[].matched_rule"))
        else:
            fast_resp = _parse_iso(fast.get("responded_at"))
            slow_resp = _parse_iso(slow.get("responded_at"))
            if not fast_resp or not slow_resp:
                assertions.append(_assertion(
                    "A1", a1_title, UNAVAILABLE,
                    "无法取得： responded_at 非合法 ISO 时间，无法比较；不填推算值。",
                    False, "stats.requests[].responded_at"))
            else:
                refill = [r for r in reqs
                          if r.get("arrival_seq") not in (fast.get("arrival_seq"), slow.get("arrival_seq"))]
                early = []
                for r in refill:
                    arr = _parse_iso(r.get("arrived_at"))
                    if arr and fast_resp <= arr < slow_resp:
                        early.append(r)
                ok = fast_resp < slow_resp and len(early) >= 1
                detail = (
                    f"fast.responded_at={fast.get('responded_at')} "
                    f"slow.responded_at={slow.get('responded_at')} "
                    f"补发且在慢请求仍在途期间到达的请求数={len(early)} "
                    f"seq={[r.get('arrival_seq') for r in early]}；"
                    "全部取自 stats 落盘真实时间戳，未写推算值。"
                )
                assertions.append(_assertion(
                    "A1", a1_title, PASS if ok else FAIL, detail, True,
                    "stats.requests[].arrived_at / responded_at / matched_rule"))

    # A2：峰值在途 = 2
    a2_title = "A2 峰值在途 = 2"
    expected_peak = cfg["expected_values"]["peak_inflight"]
    if not stats or "peak_inflight" not in stats:
        assertions.append(_assertion(
            "A2", a2_title, NOT_RUN,
            "未跑：缺 --stats 落盘统计。本轮静态准备不实跑，不写推算峰值。",
            False, "stats.peak_inflight 落盘实测"))
    else:
        peak = stats.get("peak_inflight")
        ok = peak == expected_peak
        assertions.append(_assertion(
            "A2", a2_title, PASS if ok else FAIL,
            f"stats.peak_inflight={peak}（实测），预期 {expected_peak}（C=2 口径定值）；"
            "模拟服务端不自建限流，该值反映客户端真实同时在途数。",
            True, "stats.peak_inflight"))

    # A3：每条响应写入正确的 run_id / 窗口 / 检查项，无串写
    # 实跑未落地 X-QA-Tag，按团长口径改走 perf_traces JSONL 的
    # run_id + window_id + batch_index + check_item_ids + request_id。
    a3_title = "A3 每条响应写入正确的 run_id / 窗口 / 检查项，无串写（JSONL 口径）"
    if not stats or not results or not isinstance(results.get("rows"), list):
        assertions.append(_assertion(
            "A3", a3_title, NOT_RUN,
            "未跑：缺 --stats 或 --results 落库导出（RESULT_SPEC）。",
            False, "stats.requests[] + 落库结果导出"))
    elif not trace:
        assertions.append(_assertion(
            "A3", a3_title, UNAVAILABLE,
            "无法取得：实跑未落地 X-QA-Tag 请求头，归属核对按团长口径改走 "
            "/data/perf_traces/{run_id}.jsonl；未提供 --trace 时无法核对 run / 窗口 / 检查项归属。",
            False, "/data/perf_traces/{run_id}.jsonl"))
    else:
        search_reqs = [r for r in (stats.get("requests") or [])
                       if r.get("schema_name") == "text_search_output"]
        rows = [r for r in results["rows"] if isinstance(r, dict)]
        trace_run_ids = {t.get("run_id") for t in trace if t.get("run_id")}
        request_ids = [t.get("request_id") for t in trace]
        unit_pairs = {(t.get("window_id"), t.get("batch_index")) for t in trace}
        trace_cids = {c for t in trace for c in (t.get("check_item_ids") or [])}
        stat_cids = {r.get("check_item_id") for r in search_reqs}
        row_run_ids = {r.get("run_id") for r in rows if r.get("run_id")}
        single_run = len(trace_run_ids) == 1
        unique_requests = len(request_ids) == len(set(request_ids)) and all(request_ids)
        db_matches_trace = not row_run_ids or row_run_ids <= trace_run_ids
        cids_match = stat_cids == trace_cids
        ok = (single_run and unique_requests and db_matches_trace
              and cids_match and len(unit_pairs) == len(trace))
        assertions.append(_assertion(
            "A3", a3_title, PASS if ok else FAIL,
            f"JSONL {len(trace)} 行：run_id 集合={sorted(str(x) for x in trace_run_ids)}（单 run）；"
            f"request_id 唯一={unique_requests}；"
            f"(window_id,batch_index) 组合数={len(unit_pairs)}（应={len(trace)}，无串写）；"
            f"check_item_ids 集合={sorted(str(x) for x in trace_cids)} 与 stats 一致={cids_match}；"
            f"落库 rows.run_id 集合={sorted(str(x) for x in row_run_ids)} 属于该 run={db_matches_trace}；"
            f"落库摘录 {len(rows)} 条（实测）。放行顺序打乱后的摘录集合等价另见 B2。",
            True, "perf_traces JSONL + stats.requests[] + 落库结果导出"))

    # A4：提交到线程池时间 vs 实际 HTTP 发起时间
    a4_title = "A4 分别记录「提交到线程池时间」与「实际 HTTP 发起时间」"
    if trace:
        waits = []
        for row in trace:
            t_submit = row.get("t_submit", row.get("submit_at"))
            t_start = row.get("t_http_start", row.get("http_start"))
            if isinstance(t_submit, (int, float)) and isinstance(t_start, (int, float)):
                waits.append(round(t_start - t_submit, 6))
        if waits and all(w >= 0 for w in waits):
            assertions.append(_assertion(
                "A4", a4_title, PASS,
                f"trace JSONL 共 {len(trace)} 行，{len(waits)} 行含数值型 t_submit/t_http_start；"
                f"逐条 t_http_start - t_submit = 额度等待：min={min(waits):.6f}s "
                f"max={max(waits):.6f}s，全部 ≥0 且 t_http_start ≥ t_submit。"
                "模拟服务只提供 arrived_at（≈t_http_start）作交叉旁证；"
                "t_submit 由客户端 trace 提供，不伪造。",
                True, "/data/perf_traces/{run_id}.jsonl"))
        elif waits:
            assertions.append(_assertion(
                "A4", a4_title, FAIL,
                f"trace 有 {len(waits)} 行额度等待，但存在 t_http_start < t_submit：{waits}",
                True, "/data/perf_traces/{run_id}.jsonl"))
        else:
            assertions.append(_assertion(
                "A4", a4_title, UNAVAILABLE,
                "无法取得：trace JSONL 存在但无可用的数值型 t_submit/t_http_start。"
                "原因：模拟服务只观测 arrived_at（≈t_http_start）、released_at、responded_at；"
                "「提交到线程池」发生在调用端进程内，服务端不感知、不记录。",
                False, "/data/perf_traces/{run_id}.jsonl"))
    else:
        assertions.append(_assertion(
            "A4", a4_title, UNAVAILABLE,
            "无法取得：未提供 --trace（/data/perf_traces/{run_id}.jsonl）。"
            + cfg["unavailable_fields"]["t_submit"]
            + " " + cfg["unavailable_fields"]["t_http_start"],
            False, "/data/perf_traces/{run_id}.jsonl（开发 Agent 本轮实现）"))

    return {
        "title": cfg["title"],
        "status": "实测" if any(a["measured"] for a in assertions) else "未跑",
        "assertions": assertions,
        "summary": _group_summary(assertions),
    }


# ---------------------------------------------------------------------------
# B 组
# ---------------------------------------------------------------------------

def run_group_B(fixture: dict[str, Any], x1_stats: dict[str, Any] | None,
                x3_stats: dict[str, Any] | None,
                x1_results: dict[str, Any] | None,
                x3_results: dict[str, Any] | None,
                windowing: dict[str, Any] | None,
                dedup: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = fixture["group_B"]
    exp = cfg["expected"]
    assertions: list[dict[str, Any]] = []

    # 分窗：沿用 T02 证据，不重跑
    if windowing:
        ok = windowing.get("status") == "checked" and windowing.get("import_a_b_equal") is True
        assertions.append(_assertion(
            "B0", "稳定分窗（条件性快速两次导入核对）", PASS if ok else FAIL,
            f"开发 Agent 本轮改动分窗排序，按条件补跑：{windowing}（取自 --windowing-recheck 实跑结论）。",
            True, "compare_two_imports.py 条件补跑"))
    else:
        assertions.append(_assertion(
            "B0", "稳定分窗（沿用 T02 24/24 两次导入证据）", REUSED,
            "沿用：compare_two_imports.py 24/24（A/B 有序块清单、分窗边界、内容 hash 与业务 K2 内容 hash 全部一致、176/176 覆盖），"
            "本轮不重跑；仅当开发 Agent 本轮改动分窗排序时才传 --windowing-recheck 补一次快速核对。不当作本轮新跑结果。",
            False, "evidence/compare_two_imports.json（T02 沿用）"))

    # B1：实际请求数对比（真实值）
    b1_title = "B1 X=1 与 X=3 实际请求数（实测）"
    if not x1_stats or not x3_stats:
        assertions.append(_assertion(
            "B1", b1_title, NOT_RUN,
            "未跑：缺 --x1-stats / --x3-stats 落盘统计。本轮静态准备不实跑；"
            "fixture 里 3→1 是标注 measured:false 的示例口径，不得当实测引用。",
            False, "mock 统计 / trace JSONL 请求计数"))
    else:
        c1, c3 = x1_stats.get("request_count"), x3_stats.get("request_count")
        w, n = x1_stats.get("window_count"), x1_stats.get("check_item_count")
        proportional = isinstance(w, int) and isinstance(n, int) and n > 0
        x1_expected = w * n if proportional else None
        x3_expected = w * math.ceil(n / 3) if proportional else None
        ok = isinstance(c1, int) and isinstance(c3, int) and c3 < c1
        if proportional:
            ok = ok and c1 == x1_expected and c3 == x3_expected
        assertions.append(_assertion(
            "B1", b1_title, PASS if ok else FAIL,
            f"X=1 request_count={c1}（实测），X=3 request_count={c3}（实测）；"
            f"窗口数={w}、检查项数={n}（实测 run_config）；"
            f"比例口径 X=1=窗口数×检查项数={x1_expected}、"
            f"X=3=窗口数×ceil(检查项数/3)={x3_expected}；X=3<X=1={c3 < c1}。"
            "数值全部来自落盘统计；按团长口径不硬断言 3/1（样本窗口数不同），未引用推算值。",
            True, "x1/x3-stats.request_count + window_count/check_item_count"))

    # B2：保存摘录与出处等价（两份 results 归一化集合相等）
    b2_title = "B2 X=1 与 X=3 保存摘录与出处等价"
    if not x1_results or not x3_results:
        assertions.append(_assertion(
            "B2", b2_title, NOT_RUN,
            "未跑：缺 --x1-results / --x3-results 落库结果导出（RESULT_SPEC）。",
            False, "落库结果导出"))
    else:
        n1, n3 = _norm_rows(x1_results), _norm_rows(x3_results)
        ok = n1 == n3
        assertions.append(_assertion(
            "B2", b2_title, PASS if ok else FAIL,
            f"按 (check_item_id, text_sha256, source_page_number, 页内稳定序号) 归一化："
            f"X=1 {len(n1)} 条、X=3 {len(n3)} 条，集合相等={ok}。"
            "不用 Result.fingerprint / window_text_sha256 等含 UUID 的请求 hash。",
            True, "x1-results.rows / x3-results.rows"))

    # B3：三类去重/引用情形（改读实跑结构证据，团长口径不硬编码条数）
    b3_title = "B3 三类去重/引用情形（重复引用只存1条 / 不同出处同文保留多条 / 同块多检查项各项保留）"
    if not dedup:
        assertions.append(_assertion(
            "B3", b3_title, NOT_RUN,
            "未跑：缺 --dedup（b_dedup_summary.json，由 run_quick_acceptance.py 读真实 "
            "Result / ResultSource 行计算三类去重结构）。",
            False, "b_dedup_summary.json"))
    else:
        flags = {
            "跨窗口重复引用只存1条": dedup.get("cross_window_duplicate_dedup_to_single") is True,
            "不同出处同文保留多条": dedup.get("same_text_different_source_kept") is True,
            "同一块多检查项各项保留": dedup.get("same_block_multi_check_preserved") is True,
            "X=1与X=3结果集合相等": dedup.get("x1_x3_result_sets_equal") is True,
        }
        rows1, rows3 = dedup.get("x1_text_rows"), dedup.get("x3_text_rows")
        rows_equal = isinstance(rows1, int) and rows1 == rows3
        ok = all(flags.values()) and rows_equal
        assertions.append(_assertion(
            "B3", b3_title, PASS if ok else FAIL,
            f"实跑落库 text 行：X=1 {rows1} 条 / X=3 {rows3} 条，相等={rows_equal}；"
            f"每检查项条数={dedup.get('per_check_text_rows_x1')}（实测）；"
            f"去重后 (检查项,出处块) 对数={dedup.get('distinct_check_block_pairs')}；"
            f"text_sha256 去重后 {dedup.get('text_sha256_distinct_count')} 种；"
            f"三类结构={flags}。"
            "结构布尔与条数全部来自真实 DB 行计算，未硬编码 3/1 或静态 fixture 的 4 条。",
            True, "b_dedup_summary.json（真实 DB 行计算）"))

    # B4：两份 run_config 除「X 派生字段」外全等
    # 实测差异只在 batch / checks_per_request / units_total 三个由 X 派生的字段，
    # 其余（版本/模型/分窗策略/C 等）全等；不得把派生字段差异误判成配置不一致。
    b4_title = "B4 两次运行 run_config 除 X 派生字段外全等"
    x_derived = {"X", "checks_per_request", "units_total", "batch"}
    r1 = (x1_results or {}).get("run_config")
    r3 = (x3_results or {}).get("run_config")
    if not isinstance(r1, dict) or not isinstance(r3, dict):
        assertions.append(_assertion(
            "B4", b4_title, NOT_RUN,
            "未跑：两份 results 未提供 run_config（可选字段）。",
            False, "run.model_snapshot.run_config"))
    else:
        d1 = {k: v for k, v in r1.items() if k not in x_derived}
        d3 = {k: v for k, v in r3.items() if k not in x_derived}
        x1_x, x3_x = r1.get("checks_per_request"), r3.get("checks_per_request")
        ok = (d1 == d3 and x1_x != x3_x
              and (x1_stats or {}).get("checks_per_request") == x1_x
              and (x3_stats or {}).get("checks_per_request") == x3_x)
        assertions.append(_assertion(
            "B4", b4_title, PASS if ok else FAIL,
            f"除 X 派生字段 {sorted(x_derived)} 外全等={d1 == d3}；"
            f"run_config.checks_per_request：X=1={x1_x} / X=3={x3_x}，"
            f"与 stats.checks_per_request 一致="
            f"{(x1_stats or {}).get('checks_per_request') == x1_x and (x3_stats or {}).get('checks_per_request') == x3_x}；"
            f"units_total：{r1.get('units_total')} / {r3.get('units_total')}（实跑观测）。",
            True, "run.model_snapshot.run_config + x1/x3-stats"))

    return {
        "title": cfg["title"],
        "status": "实测" if any(a["measured"] for a in assertions) else "未跑",
        "assertions": assertions,
        "summary": _group_summary(assertions),
    }


# ---------------------------------------------------------------------------
# C 组
# ---------------------------------------------------------------------------

def run_group_C(fixture: dict[str, Any], complete: dict[str, Any] | None,
                results: dict[str, Any] | None,
                chrome_evidence: dict[str, Any] | None) -> dict[str, Any]:
    cfg = fixture["group_C"]
    pf = cfg["partial_failure"]
    nc = cfg["normal_complete"]
    assertions: list[dict[str, Any]] = []

    want_code = pf["complete_task_expected_code"]
    want_status = pf["expected_complete_status"]

    def _pf() -> dict[str, Any]:
        return (complete or {}).get("partial_failure") or {}

    def _nc() -> dict[str, Any]:
        return (complete or {}).get("normal_complete") or {}

    # C1：成功摘录保留 + coverage_incomplete + run.coverage_complete=false
    c1_title = "C1 部分失败：成功摘录保留 / coverage_incomplete / run.coverage_complete=false"
    if not complete or not _pf():
        assertions.append(_assertion(
            "C1", c1_title, NOT_RUN,
            "未跑：缺 --complete 导出（COMPLETE_SPEC.partial_failure）。本轮静态准备不实跑。",
            False, "完成接口导出 + 落库结果"))
    else:
        p = _pf()
        missing = [k for k in ("kept_candidates", "not_found_reason", "run_coverage_complete")
                   if k not in p]
        if missing:
            assertions.append(_assertion(
                "C1", c1_title, UNAVAILABLE,
                f"无法取得：导出缺字段 {missing}；不填推算值。", False, "COMPLETE_SPEC"))
        else:
            ok = (p.get("kept_candidates", 0) >= 1
                  and p.get("not_found_reason") == "coverage_incomplete"
                  and p.get("run_coverage_complete") is False)
            assertions.append(_assertion(
                "C1", c1_title, PASS if ok else FAIL,
                f"实跑：kept_candidates={p.get('kept_candidates')} "
                f"not_found_reason={p.get('not_found_reason')} "
                f"run.coverage_complete={p.get('run_coverage_complete')}；"
                "三档 not_found_reason 严格不混用，技术失败不得标成 not_found。",
                True, "完成接口导出 + 落库结果"))

    # C2：完成接口 409 + 错误码 + 零写入（任务 ID 过滤）
    c2_title = "C2 完成接口 409 COVERAGE_INCOMPLETE + 零写入（目标任务 ID 过滤）"
    if not complete or not _pf():
        assertions.append(_assertion(
            "C2", c2_title, NOT_RUN,
            "未跑：缺 --complete 导出。本轮静态准备不实跑。",
            False, "完成接口响应导出"))
    else:
        p = _pf()
        missing = [k for k in ("status", "detail_code", "zero_write", "task_id_filtered")
                   if k not in p]
        if missing:
            assertions.append(_assertion(
                "C2", c2_title, UNAVAILABLE,
                f"无法取得：导出缺字段 {missing}；不填推算值。", False, "COMPLETE_SPEC"))
        else:
            ok = (p.get("status") == want_status
                  and p.get("detail_code") == want_code  # == 严格相等，纯字面量
                  and p.get("zero_write") is True
                  and p.get("task_id_filtered") is True)
            assertions.append(_assertion(
                "C2", c2_title, PASS if ok else FAIL,
                f"实跑：status={p.get('status')} detail.code={p.get('detail_code')} "
                f"期望纯字面量={want_code}；zero_write={p.get('zero_write')} "
                f"task_id_filtered={p.get('task_id_filtered')}（避 5s 轮询串扰）。"
                "接受/拒绝的正常 PATCH 属允许写入，不判违规。",
                True, "完成接口响应导出（含 CSRF 与任务 ID 过滤）"))

    # C3：正常样本完成成功 200
    c3_title = "C3 正常样本完成成功（200）"
    if not complete or not _nc():
        assertions.append(_assertion(
            "C3", c3_title, NOT_RUN,
            "未跑：缺 --complete 导出（COMPLETE_SPEC.normal_complete）。",
            False, "完成接口响应导出"))
    else:
        n = _nc()
        missing = [k for k in ("status", "run_coverage_complete", "not_found_reason") if k not in n]
        if missing:
            assertions.append(_assertion(
                "C3", c3_title, UNAVAILABLE,
                f"无法取得：导出缺字段 {missing}；不填推算值。", False, "COMPLETE_SPEC"))
        else:
            # 正常完成样本不唯一：本轮实跑是「全窗口命中 + 全人工确认 → 200」，
            # 并非「应查窗口全成功但无候选 → no_matching_evidence」。核心断言只要求
            # 200 + coverage_complete=true；not_found_reason 如实记录不强求固定值。
            ok = (n.get("status") == nc["expected_complete_status"]
                  and n.get("run_coverage_complete") is True)
            assertions.append(_assertion(
                "C3", c3_title, PASS if ok else FAIL,
                f"实跑：status={n.get('status')} state={n.get('state')} "
                f"run.coverage_complete={n.get('run_coverage_complete')} "
                f"not_found_reason={n.get('not_found_reason')}（如实记录，不强求固定值）；"
                "与部分失败场景分别验，不合并错误码。",
                True, "完成接口响应导出"))

    # C4：Chrome 只走一条部分失败任务（真实页面操作，等实跑信号）
    c4_title = "C4 Chrome 一条部分失败任务：覆盖提示 / 摘录可确认不整体只读 / 完成按钮 disabled / 刷新后仍在"
    if chrome_evidence and chrome_evidence.get("status") == "measured":
        assertions.append(_assertion(
            "C4", c4_title, PASS if chrome_evidence.get("all_pass") else FAIL,
            f"实跑证据：{chrome_evidence.get('detail', '')}", True,
            "frontend/tests/perf/evidence/（实跑）"))
    else:
        assertions.append(_assertion(
            "C4", c4_title, NOT_RUN,
            "未跑：缺 --chrome-evidence（QA_REAL_UI=1 真实页面实跑结论）。"
            "T02 封版 17/0/4 已先留档 t02_baseline；实跑信号后由 QA_REAL_UI 覆盖，"
            "C15/C16 本轮范围外保持 PENDING，不补假结果。",
            False, "frontend/tests/perf/coverage_incomplete.verify.mjs"))

    return {
        "title": cfg["title"],
        "status": "实测" if any(a["measured"] for a in assertions) else "未跑",
        "assertions": assertions,
        "summary": _group_summary(assertions),
    }


# ---------------------------------------------------------------------------
# 合成自测（纯本机，非实测，不写正式证据）
# ---------------------------------------------------------------------------

def self_test(fixture: dict[str, Any]) -> int:
    """用合成输入验证断言逻辑本身；数字明确标注「合成，非实测」。"""
    print("=== --self-test 合成自测（非实测，数字仅验证断言逻辑，不作任何验收结论）===")
    synthetic_stats = {
        "request_count": 4,
        "peak_inflight": 2,
        "requests": [
            {"arrival_seq": 1, "arrived_at": "2026-11-13T10:00:00.000000+00:00",
             "arrived_monotonic_ms": 0.0, "matched_rule": "a.w0.c1.fast",
             "schema_name": "text_search_output", "check_item_id": "charter.business_scope",
             "window_index": 0, "tag": "qa-run-A",
             "responded_at": "2026-11-13T10:00:00.025000+00:00", "elapsed_ms": 25.0},
            {"arrival_seq": 2, "arrived_at": "2026-11-13T10:00:00.001000+00:00",
             "arrived_monotonic_ms": 1.0, "matched_rule": "a.w0.c2.slow",
             "schema_name": "text_search_output", "check_item_id": "charter.approval_body",
             "window_index": 0, "tag": "qa-run-A",
             "responded_at": "2026-11-13T10:00:00.401000+00:00", "elapsed_ms": 400.0},
            {"arrival_seq": 3, "arrived_at": "2026-11-13T10:00:00.030000+00:00",
             "arrived_monotonic_ms": 30.0, "matched_rule": "a.w1.c1.mid",
             "schema_name": "text_search_output", "check_item_id": "charter.business_scope",
             "window_index": 1, "tag": "qa-run-A",
             "responded_at": "2026-11-13T10:00:00.090000+00:00", "elapsed_ms": 60.0},
            {"arrival_seq": 4, "arrived_at": "2026-11-13T10:00:00.402000+00:00",
             "arrived_monotonic_ms": 402.0, "matched_rule": "a.w1.c2.mid",
             "schema_name": "text_search_output", "check_item_id": "charter.approval_body",
             "window_index": 1, "tag": "qa-run-A",
             "responded_at": "2026-11-13T10:00:00.462000+00:00", "elapsed_ms": 60.0},
        ],
    }
    synthetic_rows_a = {
        "run_id": "run-A",
        "tag": "qa-run-A",
        "rows": [
            {"check_item_id": "charter.business_scope", "window_index": 0,
             "text_sha256": "h1", "source_page_number": 7, "page_inner_seq": 0, "run_id": "run-A"},
            {"check_item_id": "charter.approval_body", "window_index": 1,
             "text_sha256": "h2", "source_page_number": 15, "page_inner_seq": 1, "run_id": "run-A"},
        ],
    }
    synthetic_trace = [
        {"t_submit": 100.000, "t_http_start": 100.002, "run_id": "run-A",
         "request_id": "run-A:w0:b0", "window_id": "w0", "batch_index": 0,
         "check_item_ids": ["charter.business_scope"]},
        {"t_submit": 100.001, "t_http_start": 100.003, "run_id": "run-A",
         "request_id": "run-A:w1:b0", "window_id": "w1", "batch_index": 0,
         "check_item_ids": ["charter.business_scope"]},
        {"t_submit": 100.002, "t_http_start": 100.004, "run_id": "run-A",
         "request_id": "run-A:w0:b1", "window_id": "w0", "batch_index": 1,
         "check_item_ids": ["charter.approval_body"]},
        {"t_submit": 100.003, "t_http_start": 100.005, "run_id": "run-A",
         "request_id": "run-A:w1:b1", "window_id": "w1", "batch_index": 1,
         "check_item_ids": ["charter.approval_body"]},
    ]
    gA = run_group_A(fixture, synthetic_stats, synthetic_rows_a, synthetic_trace)

    exp_rows = fixture["group_B"]["expected"]["expected_kept_rows"]
    synthetic_b_rows = {
        "run_id": "run-B",
        "rows": [
            {"check_item_id": "charter.business_scope", "window_index": 0,
             "text_sha256": "t0", "source_page_number": 7, "page_inner_seq": 0},
            {"check_item_id": "charter.approval_body", "window_index": 0,
             "text_sha256": "t1", "source_page_number": 7, "page_inner_seq": 1},
            {"check_item_id": "charter.approval_body", "window_index": 0,
             "text_sha256": "t1", "source_page_number": 14, "page_inner_seq": 0},
            {"check_item_id": "charter.guarantee_restrictions", "window_index": 0,
             "text_sha256": "t0", "source_page_number": 7, "page_inner_seq": 0},
        ],
        "run_config": {"X": 1, "checks_per_request": 1, "units_total": 6,
                       "batch": {}, "C": 2, "version": "pipeline-v2"},
    }
    synthetic_b_rows_x3 = dict(synthetic_b_rows, run_config={
        "X": 3, "checks_per_request": 3, "units_total": 2,
        "batch": {}, "C": 2, "version": "pipeline-v2"})
    synthetic_dedup = {
        "cross_window_duplicate_dedup_to_single": True,
        "same_text_different_source_kept": True,
        "same_block_multi_check_preserved": True,
        "x1_x3_result_sets_equal": True,
        "x1_text_rows": 4, "x3_text_rows": 4,
        "per_check_text_rows_x1": {"charter.business_scope": 1,
                                   "charter.approval_body": 2,
                                   "charter.guarantee_restrictions": 1},
        "distinct_check_block_pairs": 4,
        "text_sha256_distinct_count": 2,
    }
    gB = run_group_B(
        fixture,
        {"request_count": 6, "window_count": 2, "check_item_count": 3,
         "checks_per_request": 1},
        {"request_count": 2, "window_count": 2, "check_item_count": 3,
         "checks_per_request": 3},
        synthetic_b_rows, synthetic_b_rows_x3,
        None, synthetic_dedup,
    )

    synthetic_complete = {
        "partial_failure": {
            "status": 409, "detail_code": "COVERAGE_INCOMPLETE",
            "zero_write": True, "task_id_filtered": True,
            "kept_candidates": 1, "not_found_reason": "coverage_incomplete",
            "run_coverage_complete": False,
        },
        "normal_complete": {
            "status": 200, "run_coverage_complete": True,
            "not_found_reason": "no_matching_evidence",
        },
    }
    gC = run_group_C(fixture, synthetic_complete, None, None)

    for name, group in (("A", gA), ("B", gB), ("C", gC)):
        s = group["summary"]
        print(f"  组 {name}: status={group['status']} "
              f"PASS={s['PASS']} FAIL={s['FAIL']} 未跑={s['未跑']} "
              f"无法取得={s['无法取得']} 沿用={s['沿用']}")
        for a in group["assertions"]:
            print(f"    {a['status']:<6} | {a['id']} | {a['title']}")
    # 新 fixture 响应占位符渲染验证（纯本机，确保模拟服务能正确消费）
    import re
    import uuid
    from mock_llm_server import RequestInfo, _build_context, _walk_render

    fake_info = RequestInfo(
        arrival_seq=1, arrived_at="2026-11-13T00:00:00+00:00", arrived_monotonic_ms=0.0,
        schema_name="text_search_output", check_item_id="charter.business_scope",
        batch_check_ids=["charter.business_scope", "charter.approval_body",
                         "charter.guarantee_restrictions"],
        block_ids=[str(uuid.UUID(int=0x2000 + i)) for i in range(4)],
        window_index=0, attempt=0, tag=None, response_format_type="json_schema",
        model="qa-mock-model", user_chars=100, raw_body_sha256="x",
    )
    ctx = _build_context(fake_info)
    templates = ([(r["key"], r["response"]) for r in fixture["group_B"]["x1_requests"]]
                 + [(r["key"], r["response"]) for r in fixture["group_B"]["x3_requests"]])
    uuid_re = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    render_problems = []
    for key, tpl in templates:
        rendered = _walk_render(tpl, ctx)
        text = json.dumps(rendered, ensure_ascii=False)
        if "{{" in text:
            render_problems.append(f"{key}: 残留占位符")
        for c in rendered.get("check_results", []):
            for ev in c.get("evidence", []):
                for ref in ev.get("source_refs", []):
                    if not uuid_re.match(str(ref.get("block_id", ""))):
                        render_problems.append(f"{key}: block_id 渲染后非法 {ref.get('block_id')}")
    print(f"  新 fixture 响应占位符渲染：{len(templates)} 个模板，问题 {len(render_problems)} 项"
          + ("：" + "；".join(render_problems) if render_problems else "（全部可渲染、block_id 合法）"))

    total_fail = (sum(g["summary"]["FAIL"] for g in (gA, gB, gC))
                  + len(render_problems))
    print(f"=== 合成自测结论：FAIL={total_fail}（0 表示断言逻辑在合成输入上自洽；"
          "以上数字均为合成，非实测，不写入正式证据）===")
    return 0 if total_fail == 0 else 1


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="三组快速验收统一离线断言器")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--group", choices=["A", "B", "C", "all"], default="all")
    parser.add_argument("--stats", default=None, help="A 组 mock __stats 落盘")
    parser.add_argument("--results", default=None, help="A 组落库结果导出")
    parser.add_argument("--trace", default=None, help="A 组 perf_traces JSONL")
    parser.add_argument("--x1-stats", default=None)
    parser.add_argument("--x3-stats", default=None)
    parser.add_argument("--x1-results", default=None)
    parser.add_argument("--x3-results", default=None)
    parser.add_argument("--windowing-recheck", default=None,
                        help="B 组条件性两次导入核对结论（仅改动分窗排序时传）")
    parser.add_argument("--dedup", default=None,
                        help="B 组三类去重结构证据（b_dedup_summary.json，真实 DB 行计算）")
    parser.add_argument("--complete", default=None, help="C 组完成接口导出")
    parser.add_argument("--chrome-evidence", default=None,
                        help="C 组 Chrome 实跑结论（QA_REAL_UI 模式下产出）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--self-test", action="store_true",
                        help="纯本机合成自测：验证断言逻辑，非实测、不写正式证据")
    args = parser.parse_args()

    fixture = _load_json(args.fixture)
    if fixture is None:
        print(f"fixture 无法读取：{args.fixture}", file=sys.stderr)
        return 1

    if args.self_test:
        return self_test(fixture)

    stats = _load_json(args.stats)
    results = _load_json(args.results)
    trace = _load_jsonl(args.trace)
    x1_stats = _load_json(args.x1_stats)
    x3_stats = _load_json(args.x3_stats)
    x1_results = _load_json(args.x1_results)
    x3_results = _load_json(args.x3_results)
    windowing = _load_json(args.windowing_recheck)
    dedup = _load_json(args.dedup)
    complete = _load_json(args.complete)
    chrome_evidence = _load_json(args.chrome_evidence)

    groups: dict[str, Any] = {}
    if args.group in ("A", "all"):
        groups["A"] = run_group_A(fixture, stats, results, trace)
    if args.group in ("B", "all"):
        groups["B"] = run_group_B(fixture, x1_stats, x3_stats,
                                  x1_results, x3_results, windowing, dedup)
    if args.group in ("C", "all"):
        groups["C"] = run_group_C(fixture, complete, results, chrome_evidence)

    any_measured = any(g["status"] == "实测" for g in groups.values())
    overall = {
        "groups_run": sorted(groups),
        "any_measured": any_measured,
        "PASS": sum(g["summary"]["PASS"] for g in groups.values()),
        "FAIL": sum(g["summary"]["FAIL"] for g in groups.values()),
        "未跑": sum(g["summary"]["未跑"] for g in groups.values()),
        "无法取得": sum(g["summary"]["无法取得"] for g in groups.values()),
        "沿用": sum(g["summary"]["沿用"] for g in groups.values()),
    }

    payload = {
        "schema_version": "qa-quick-acceptance-evidence-1",
        "ran_at": _now_iso(),
        "mode": "measured" if any_measured else "static_preparation",
        "status": ("实测（数字全部来自输入证据）" if any_measured
                   else "静态准备 / 未实跑（三组均未跑；沿用 T02 的项标「沿用」，未跑标「未跑」，不写推算值）"),
        "scope": fixture["scope"],
        "range_note": fixture["range_note"],
        "fixture": str(Path(args.fixture).name),
        "groups": groups,
        "overall": overall,
        "reused_from_T02": fixture["evidence_provenance"]["reused_from_T02"],
        "not_run_this_round": fixture["evidence_provenance"]["not_run_this_round"],
        "pending_real_run_dependencies": fixture["evidence_provenance"]["pending_real_run_dependencies"],
        "provenance_note": fixture["evidence_provenance"]["_note"],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"三组快速验收断言证据：{out}")
    print(f"mode={payload['mode']} status={payload['status']}")
    print(f"overall: {overall}")
    for name, g in groups.items():
        print(f"  组 {name}: {g['summary']}")
    return 0 if overall["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
