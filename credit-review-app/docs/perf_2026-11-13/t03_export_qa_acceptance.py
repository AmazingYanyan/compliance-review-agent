#!/usr/bin/env python3
"""产出 QA 统一离线断言器 verify_quick_acceptance.py 的输入格式样例。

**定位**：开发侧**真实实跑**的格式样例 + 字段契约，供 QA 写自己的导出脚本时对照；
QA 实跑时用自己 fixture（quick_acceptance.json / 模拟服务 stats）的导出覆盖这些文件。
本脚本所有数字来自 t03_* 落盘证据与 DB 查询，绝不编造。

注意：本开发侧 B 组输入是「同一 15 页 OCR + 3 个 charter 检查项」，与 QA fixture
的「4 候选」口径不同，故 QA 断言器的 B3 expected_kept_rows 不适用于本样例；
B1/B2/B4 的字段与结构完全对齐 RESULT_SPEC / STATS_SPEC。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "docs/perf_2026-11-13"
OUT = D / "qa_acceptance"
OUT.mkdir(parents=True, exist_ok=True)
DB = "credit-review-app-db-1"
SETUP = json.loads((D / "t03_setup.json").read_text(encoding="utf-8"))
PE = json.loads((D / "t03_pipeline_evidence.json").read_text(encoding="utf-8"))
HE = json.loads((D / "t03_http_evidence.json").read_text(encoding="utf-8"))


def _psql_json(sql: str) -> Any:
    out = subprocess.run(
        ["docker", "exec", DB, "psql", "-U", "postgres", "-d", "app", "-t", "-A", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip() or "[]")


def _rows(run_id: str, x: int) -> list[dict[str, Any]]:
    sql = (
        "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM ("
        "SELECT r.check_item_id, r.text, rs.source_page_number, "
        "COALESCE(ob.sequence_index,-1) AS page_inner_seq, "
        "rs.block_id::text AS block_id "
        "FROM results r JOIN result_sources rs ON rs.result_id=r.id "
        "LEFT JOIN ocr_blocks ob ON ob.id=rs.block_id "
        f"WHERE r.run_id='{run_id}' AND r.kind='text'"
        ") t;"
    )
    raw = _psql_json(sql)
    rows = []
    for rec in raw:
        rows.append({
            "check_item_id": rec["check_item_id"],
            "text_sha256": hashlib.sha256((rec.get("text") or "").encode("utf-8")).hexdigest(),
            "source_page_number": rec["source_page_number"],
            # 页内稳定序号：OcrBlock.sequence_index（真实 OCR 导入/合成造数时写入）
            "page_inner_seq": rec["page_inner_seq"],
            "run_id": run_id,
            # B2 归一化键不含 window_index；A3 的 unit_pairs 来自 QA 自己的模拟服务
            # stats，QA 实跑时按 stats.requests[].window_index 与窗口归属填精确值。
            "window_index": 0,
            "x": x,
        })
    return rows


def _static_run_config(case_key: str) -> dict[str, Any]:
    rc = PE["cases"][case_key]["facts"]["run_config"] or {}
    return {
        "C": rc.get("llm_max_in_flight"),
        "version": rc.get("pipeline_config_version"),
        "search_prompt_version": rc.get("search_prompt_version"),
        "checklist_hash": rc.get("checklist_hash"),
        "text_model": rc.get("text_model"),
        "window_strategy": rc.get("window_strategy"),
        "note": "静态配置：X=1 与 X=3 两次运行除 X 外全等（QA B4 断言口径）",
    }


def _request_count(case_key: str) -> int:
    # 实际搜索请求数：取自主脚本落盘的 mock 统计（真实实跑）
    return PE["cases"][case_key]["mock"]["text_search_request_count"]


def main() -> int:
    out_files: dict[str, Any] = {}
    # B 组：X=1 / X=3 的 stats 与 results（run_config 除 X 外全等）
    for key, x in (("B-real-x1", 1), ("B-real-x3", 3)):
        c = SETUP["B_x1" if x == 1 else "B_x3"]
        stats = {"request_count": _request_count(key), "x": x,
                 "source": "t03_pipeline_evidence.json mock.text_search_request_count（真事实跑）"}
        results = {
            "run_id": c["run_id"],
            "rows": _rows(c["run_id"], x),
            "run_config": {"X": x, **_static_run_config(key)},
        }
        tag = "x1" if x == 1 else "x3"
        (OUT / f"quick_acceptance_b_{tag}_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUT / f"quick_acceptance_b_{tag}_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out_files[f"b_{tag}"] = {"stats": stats, "result_rows": len(results["rows"]),
                                 "run_config": results["run_config"]}

    # A 组：落库结果导出（RESULT_SPEC）+ trace JSONL（A3/A4 入口）
    a = SETUP["A"]
    a_results = {
        "run_id": a["run_id"],
        "tag": a["run_id"],  # 与 X-QA-Tag 请求头一致
        "rows": _rows(a["run_id"], 1),
        "run_config": {},
    }
    # A 的静态 run_config 从 A.facts 取（A 不在 cases 里）
    arc = PE["A"]["facts"]["run_config"] or {}
    a_results["run_config"] = {
        "X": 1, "C": arc.get("llm_max_in_flight"),
        "version": arc.get("pipeline_config_version"),
        "search_prompt_version": arc.get("search_prompt_version"),
        "checklist_hash": arc.get("checklist_hash"),
        "text_model": arc.get("text_model"),
        "window_strategy": arc.get("window_strategy"),
        "note": "静态配置：X=1 与 X=3 两次运行除 X 外全等（QA B4 断言口径）",
    }
    (OUT / "quick_acceptance_a_results.json").write_text(
        json.dumps(a_results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "quick_acceptance_a_trace.jsonl").write_text(
        (D / "t03_trace_A.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    out_files["a"] = {"result_rows": len(a_results["rows"]), "trace_rows": PE["A"]["trace_rows"]}

    # C 组：COMPLETE_SPEC（来自 HTTP 实跑证据）
    cp, co = HE["results"]["C_partial"], HE["results"]["C_ok"]
    complete = {
        "partial_failure": {
            "status": cp["status"], "detail_code": cp["code"],
            "zero_write": cp["zero_writes"], "task_id_filtered": True,
            "kept_candidates": PE["C"]["partial"]["hit_rows"],
            "not_found_reason": "coverage_incomplete",
            "run_coverage_complete": PE["C"]["partial"]["facts"]["coverage_complete"],
        },
        "normal_complete": {
            "status": co["status"],
            "run_coverage_complete": PE["C"]["ok"]["coverage_complete"],
            "not_found_reason": "no_matching_evidence",
        },
    }
    (OUT / "quick_acceptance_c_complete.json").write_text(
        json.dumps(complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_files["c"] = complete

    readme = """# QA 断言器输入样例（开发侧真实实跑）

本目录由 `docs/perf_2026-11-13/t03_export_qa_acceptance.py` 生成，数字来自
`t03_pipeline_evidence.json` / `t03_http_evidence.json` / DB 查询，**无编造**。

## 用途
给 QA 写「实跑落盘导出」时对照字段格式；QA 实跑请用自己 fixture
（`backend/tests/perf/fixtures/quick_acceptance.json`）与模拟服务 stats 的导出
**覆盖这些文件**后再跑 `verify_quick_acceptance.py`。

## 已知差异（不要误用）
开发侧 B 组输入是「同一 15 页 OCR + 3 个 charter 检查项」，X=1 6 请求 / X=3 2 请求，
与 QA fixture 的「X=1 3 请求 / X=3 1 请求、4 候选」口径不同，因此 QA 断言器的
B3 `expected_kept_rows`（4 条）不适用于本样例。B1（request_count）、B2（归一化集合相等）、
B4（run_config 除 X 外全等）的**字段与结构**完全对齐。

## 字段契约
* JSONL（`quick_acceptance_a_trace.jsonl`，源 `/data/perf_traces/{run_id}.jsonl`）：
  `trace_id / run_id / window_id / window_index / batch_id / check_ids / check_item_id /
  t_submit / t_http_start / t_http_end / state / error_code / finish_reason /
  messages_sha256 / user_sha256 / window_text_sha256`（+ request_id / batch_index /
  check_item_ids / attempt / unit_state / unit_error_code）。`t_submit` 是主线程提交
  ThreadPoolExecutor 时的 `time.perf_counter()`，非伪造；`t_http_start` 是 acquire
  `_IN_FLIGHT` 额度后真正发起 HTTP 的时刻。
* A3 归属：请求头 `X-QA-Tag: <run_id>`（同时 JSONL 逐请求带 run/窗口/批次/检查项）。
* RESULT_SPEC.rows：`check_item_id / text_sha256 / source_page_number / page_inner_seq /
  run_id / window_index`；`page_inner_seq` 取 `ocr_blocks.sequence_index`（页内稳定序号），
  `text_sha256 = sha256(result.text)`，不用 fingerprint / 请求 hash。
  样例里 `window_index` 统一 0（B2 归一化键不含它）；QA 实跑请按 stats.requests[].window_index
  与窗口归属填精确值。
* run_config：静态字段 `C / version / search_prompt_version / checklist_hash / text_model /
  window_strategy` 两次运行除 `X` 外全等；原始 `run.model_snapshot.run_config` 还完整记录
  `batch.batches`（每批检查项 ID）/ `units_total` 等**动态派生**信息，导出时按 RESULT_SPEC
  归一化为 `{X, C, version, ...}` 即可。
* COMPLETE_SPEC：部分失败 409 `COVERAGE_INCOMPLETE` + 零写入；正常 200。
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps({"status": "pass", "files": sorted(p.name for p in OUT.iterdir()),
                      "summary": out_files}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
