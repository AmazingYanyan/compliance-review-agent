# QA 断言器输入样例（开发侧真实实跑）

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
