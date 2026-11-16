# QA 性能试验测试资产（第一步四项前置 / 第二步 X·C / 第三步短用例矩阵）

> 负责人：QA 工程师「严过关」 · 本轮定位：**与开发并行准备测试资产**，不是最终验收。
> 本目录是**测试资产目录**，不是交接文档；项目唯一交接源仍是 `docs/REVIEW_HANDOFF.md`（本轮未改动）。
> 所有数字来自真实实跑并落在 `evidence/` 下；未跑的用例一律标「待实现后补跑」，不写推算填充值。

---

## 0. 边界与纪律（先读）

| 项 | 本轮执行情况 |
|---|---|
| 业务代码 | **未修改** `backend/app/**`、`frontend/src/**`、配置、迁移、镜像 |
| 真实模型 / 外部 OCR | **未调用**。故障注入在容器内 monkeypatch `OpenAI.chat.completions.create`；Chrome 用例全部 `page.route` 拦截；两次导入只复用本地 15 页 OCR JSON |
| 真实业务任务 | 前后各读一次 DB，`607e6d41-…`(REVIEWING) 与 `ee59108d-…`(COMPLETED) 的 `state` / `deleted_at` / `input_revision` **均未变化**；`git status` 复核亦见 `.DS_Store` 仍为原有 ` M`，未碰、未提交 |
| 隔离数据 | 两次导入对照 2 个 + 故障注入 3 个隔离 Task/File，全部 `deleted_at` 软删，`ocr_*` / `run` / `results` / `run_steps` 保留可追溯 |
| Git | 未 `git commit`、未 `git add -A`；新增文件仅为下面清单 |
| 镜像 | 未重建 api/worker。工程师改 worker 执行路径后须 `docker compose build worker` + `up -d worker`（与 api 是两个独立镜像，见 `沉淀经验.md` 第 1 条） |
| `docker exec` 传 stdin | 必须带 `-i`（见 `沉淀经验.md` 与交接文档） |

---

## 1. 资产清单与状态

路径均相对项目根 `credit-review-app/`。

### 后端 `backend/tests/perf/`

| 资产 | 文件 | 状态 | 说明 |
|---|---|---|---|
| **① 模拟服务** | `mock_llm_server.py` | ✅ 可直接跑（已自测） | 纯标准库独立进程，OpenAI 兼容 `/chat/completions`；可控短延迟、barrier 收齐 N 个再按预设顺序放行、逐请求到达/放行/响应时间与在途峰值、注入 401/429/500/格式失败/截断/超时、机器可读 JSON 统计 |
| ① 配置样例 | `mock_config.example.json` | ✅ 可直接跑 | 基础示例（barrier 关闭）+ 故障注入与 `response_ref` 用法说明 |
| ① 配置样例 | `mock_config.full_concurrency.json` | ✅ 可直接跑 | 「X=1 全量并发」：barrier size 12 / reverse 放行 / expected 12 |
| ① 配置样例 | `mock_config.c2_refill.json` | ✅ 可直接跑 | 「C=2 即时补位」：一快一慢（20ms / 400ms），用于验证快请求结束立即补发 |
| ① 配置样例 | `mock_config.u5_two_runs.json` | ✅ 可直接跑 | 「U5 两 run 同时执行」：`X-QA-Tag` 隔离 + `by_tag` 统计 + 合计在途峰值 / 逐条 run_id 归属断言 |
| ① 自测 | `selftest_mock_server.py` | ✅ 已实跑 | 真实起服务 + 12 并发请求 + 校验统计口径 |
| **② 固定响应 fixture** | `fixtures/fixed_responses.json` | ✅ 静态资产（已自检 + 端到端渲染验证） | X=1/X=3 等价响应对；七类批内异常；X=1 覆盖不全用例；4 条去重预期；`contract_facts` 关键契约 |
| ② 校验工具 | `validate_fixtures.py` | ✅ 已实跑 | JSON 语法 / TextSearchOutput 结构 / 占位符渲染 / `response_ref` 路径解析 |
| **③ 两次导入对照** | `compare_two_imports.py` | ✅ 已实跑（worker 容器） | 同一 15 页 OCR JSON 导入两个隔离任务，导出有序块清单、分窗边界、不含导入 UUID 的内容 hash、应查块全覆盖，输出 diff 结论 |
| **④ 故障注入** | `fault_injection.py` | ✅ 已实跑（worker 容器） | 401 / 格式失败 / 超时三种；断言 run、阶段、检查项状态一致与失败时证据保留；附带 `--check-baseline-only` 静态检查基线脚本退出码 |
| ④ HTTP 层规则 | `fixtures/fault_injection_rules.json` | ⏳ 待实现后补跑 | 工程师实现后用模拟服务从 HTTP 层复验三种注入（与容器内 monkeypatch 版互为对照） |
| **⑥ 本 README** | `README.md` | ✅ | 本文件 |

### 前端 `frontend/tests/perf/`

| 资产 | 文件 | 状态 | 说明 |
|---|---|---|---|
| **⑤ Chrome 骨架** | `coverage_incomplete.verify.mjs` | ⚠️ 骨架已跑通（拦截自测），**真实页面操作待实现后补跑** | Playwright + 系统 Chrome + `page.route`；提示文案 / 已有摘录可接受拒绝 / 点击出处定位 / 刷新 / 完成按钮 409 |
| ⑤ 固定响应 | `fixtures/coverage_incomplete.results.json` | ✅ 静态资产 | 一条覆盖不全任务（1 条命中 + 1 条 `coverage_incomplete` + `run.coverage_complete=false` + 409 错误码） |
| ⑤ 证据 | `evidence/coverage_incomplete.skeleton.json` | ✅ 已产出并 T02 后重跑 | **17 PASS / 0 FAIL / 4 PENDING**（见 §9.14） |

### 证据 `backend/tests/perf/evidence/`

| 文件 | 来源 |
|---|---|
| `selftest_mock_server.json` | ① 模拟服务自测 |
| `validate_fixtures.json` | ② fixture 自检 |
| `compare_two_imports.json` | ③ 两次导入对照（约 222 KB，含两份 176 块有序清单） |
| `fault_injection.json` | ④ 三种故障注入实测 |
| `baseline_exit_contract.json` | ④ 基线脚本退出码静态检查 |

---

## 2. 每个资产怎么跑 / 预期输出

### ① 模拟服务

```bash
cd credit-review-app
python3 backend/tests/perf/mock_llm_server.py \
  --config backend/tests/perf/mock_config.full_concurrency.json \
  --port 18099 \
  --stats-out /tmp/qa_mock_stats.json
```

- 服务只监听本地，`POST */chat/completions`（兼容任意 base_url 前缀）；控制端点 `GET /__health`、`GET /__stats`、`GET /__dump`、`POST /__reset`。
- 退出（SIGINT/SIGTERM）自动把统计写到 `--stats-out`。
- 统计关键字段：`request_count`、`peak_inflight`、`first_arrival_at`、`last_arrival_at`、`first_last_arrival_gap_ms`、`barrier.release_order_actual_arrival_seqs`、`requests[]`（逐请求 `arrived_at` / `released_at` / `responded_at` / `attempt` / `inject` / `status_code`）、`by_tag`。
- **「请求确实发出」**由 `request_count` 与每个请求的 `arrived_at` 证明；**「峰值在途」**由 `peak_inflight` 证明（在途 = 已到达 handler 且尚未写出完整响应，barrier 等待期间同样在途）。
- 「提交时间 vs 实际 HTTP 发起时间」：服务端只给 `arrived_at`；客户端脚本需另记 `submit_at`，两者相减得到排队/调度开销。**服务端不提供提交时间，不要伪造。**

自测（真实起服务 + 12 并发请求）：

```bash
python3 backend/tests/perf/selftest_mock_server.py \
  --config backend/tests/perf/mock_config.full_concurrency.json \
  --port 18099 --requests 12 \
  --out backend/tests/perf/evidence/selftest_mock_server.json
```

故障注入通过配置里的 `inject` 字段切换，取值与后端映射见 §4。

### ② 固定响应 fixture / 自检

```bash
python3 backend/tests/perf/validate_fixtures.py \
  --out backend/tests/perf/evidence/validate_fixtures.json
```

预期输出：`PASS`，并给出 JSON 数 / 响应模板数 / `source_ref` 数 / `response_ref` 数 / 错误数。

在模拟服务里消费 fixture：

```json
{
  "rules": [{
    "name": "from_fixture",
    "when": { "schema_name": "text_search_output", "check_item_id": "charter.business_scope", "window_index": 0 },
    "response_ref": {
      "file": "fixtures/fixed_responses.json",
      "path": ["equivalence_pair", "x1_requests", 0, "response"]
    }
  }]
}
```

`response_ref.file` 相对配置文件所在目录解析；占位符 `{{BLOCK:n}}` 会渲染成**当前请求窗口**里真实的 `block_id`，因此 fixture 不绑定某次导入生成的随机 `OcrBlock UUID`。

### ③ 两次导入稳定分窗对照（worker 容器内）

```bash
cd credit-review-app
OCR_JSON="/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json"

docker cp "$OCR_JSON" credit-review-app-worker-1:/tmp/qa_compare_ocr_slice.json
docker exec -i credit-review-app-worker-1 python - \
  --evidence-out /tmp/qa_compare_two_imports.json \
  < backend/tests/perf/compare_two_imports.py > /tmp/qa_compare_stdout.json
docker cp credit-review-app-worker-1:/tmp/qa_compare_two_imports.json \
  backend/tests/perf/evidence/compare_two_imports.json
```

可选参数：`--ocr-json`、`--evidence-out`、`--keep-task`（默认跑完软删）。

输出 `diff` 含 24 项检查、逐窗口签名差异明细。脚本同时导出两套口径：
- `expected`：按「物理页 → 页内稳定序号 → provider_block_id」重排后调用同一个 `chunk_source_blocks` / `chunk_blocks`，是**修复后应达到**的口径；
- `actual`：直接调现有 `load_source_blocks` / `load_file_blocks` + 分窗函数，是**当前 HEAD 实测**口径。

`content_hash_excluding_import_uuid` 与 `ordered_block_list_sha256` **不含任何 DB UUID**；`window_text_sha256_run_bound` 明确标注为 run 绑定产物，仅作披露，不参与「稳定」判定。

### ④ 故障注入

```bash
# 4a) 宿主机只读静态检查基线脚本退出码契约（不连 DB、不造数据）
python3 backend/tests/perf/fault_injection.py --check-baseline-only \
  --baseline-script scripts/baseline_serial.py \
  --out backend/tests/perf/evidence/baseline_exit_contract.json

# 4b) worker 容器实跑三种注入（造隔离数据，跑完软删）
docker cp "$OCR_JSON" credit-review-app-worker-1:/tmp/qa_fault_ocr_slice.json
docker exec -i credit-review-app-worker-1 python - \
  --run-cases --evidence-out /tmp/qa_fault_injection.json \
  < backend/tests/perf/fault_injection.py > /tmp/qa_fault_stdout.json
docker cp credit-review-app-worker-1:/tmp/qa_fault_injection.json \
  backend/tests/perf/evidence/fault_injection.json
```

`evidence["cases"][case]` 含 `expected`（修复后应达到）、`observed`（真实 DB 读取）、`verdict`（统一「待实现后补跑」）；顶层 `known_gaps_observed` 是**实测驱动**的缺口汇总。

HTTP 层复验（实现后）：把 `fixtures/fault_injection_rules.json` 的 `cases[].mock_rule` 合并进模拟服务配置的 `rules`，并把该次运行 `LLM_API_BASE` 指向模拟服务。

### ⑤ Chrome 覆盖不全骨架

```bash
cd credit-review-app
node frontend/tests/perf/coverage_incomplete.verify.mjs
# 可选：VERIFY_BASE_URL / VERIFY_BROWSER_CHANNEL / QA_COVERAGE_EVIDENCE_OUT
```

- 全部 `/api/v1/` 请求被 `context.route` 拦截，返回 `fixtures/coverage_incomplete.results.json` 的固定响应；**不触碰真实服务、不触发 OCR/LLM**。
- 输出 `frontend/tests/perf/evidence/coverage_incomplete.skeleton.json`。
- C13–C16 是 `PENDING`：任务级 banner、实现后按钮状态、真实服务定向接口回归、正常完成/历史只读，均待工程师实现后补跑。
- ⚠️ 本骨架的 12 项 PASS 是**拦截页面上的 DOM 事实自测**，不是真实业务数据上的 UI 验收，不得当作「四项前置已通过」。

### ⑥ fixture 与证据自检

```bash
python3 backend/tests/perf/validate_fixtures.py
node --check frontend/tests/perf/coverage_incomplete.verify.mjs
python3 -m py_compile backend/tests/perf/*.py   # 会生成 __pycache__，交付前清理
```

---

## 3. T02 后真实实测结果（禁止推算填充；2026-11-12 容器重建后重跑，均来自 evidence/ 落盘）

> 修订前 HEAD 的对照数字（18/6、6 处缺口、15 PASS 等）保留在 §9.14 的历史对照表里，不抹掉实测历史。

### ① 模拟服务自测 — `evidence/selftest_mock_server.json`

`8 PASS / 0 FAIL`。12 个并发请求：
- `stats.request_count = 12`，每个请求都有真实 `arrived_at`；
- `peak_inflight = 12`（12 个请求同时在途）；
- `first_last_arrival_gap_ms` **最终镜像实测 1.741 ms**（历史序列 2.249 → 1.745 → 1.806 → 1.741；以证据文件最新一次为准）；
- barrier `ready = true`，放行顺序 `[12,11,10,9,8,7,6,5,4,3,2,1]`（reverse）。

> 这是**模拟服务自身能力自测**，不是业务链路的并发验收；真实请求数/峰值须等工程师实现后在真实调度器上重跑。

### ② fixture 自检 — `evidence/validate_fixtures.json`

`PASS`：13 个 JSON、23 个响应模板、19 个 `source_ref`、1 个 `response_ref`、**12 个错误码断言字段**、0 错误。
端到端验证：起模拟服务用 `response_ref` 取 `equivalence_pair.x1_requests[0].response`，`{{BLOCK:0}}` 渲染成窗口内真实 `block_id`（`00000000-0000-0000-0000-000000003000`），无残留占位符，规则命中 `window_index=0`。

### ③ 两次导入对照 — `evidence/compare_two_imports.json`（`status=measured`）

固定输入：15 页 OCR JSON，SHA256 `8879c8a2…60b`；`protected_unchanged = true`；两个隔离任务已软删。

| 实测项 | 值 |
|---|---|
| 块数 / 总字符数 | **176 块 / 9570 字符**（A、B 相同） |
| `content_hash_excluding_import_uuid` | A = B = `62290b51d70c6524a582c46556eae53ff4e9825df0ed80ed067d177b9c9d0e09` |
| `content_hash_k2_business_aggregate` | A = B = `606a4e17055a85c87d153a121f10f353789afccdfedc132dc9fc73b1b10293c1` |
| `ordered_block_list_sha256` | A = B = `c6e9613f544599e851253a52f91494dce7da4256803e687de297c7c561b92c6c` |
| `ordering_source` | A = B = `business_order_blocks`（QA 脚本已复用 `source_ordering.order_blocks`） |
| `order_sources_used` | A = B = `['bbox', 'canonical_text_sha256']`（单块页的末级回退属如实记录，不是旧数据异常） |
| `expected` / `actual` 口径 | 均 **2 窗口**：w0 = 133 块 / 7998 字，w1 = 51 块 / 2095 字；**两次导入完全一致**、176/176 全覆盖、窗口内顺序单调 |
| `window_text_sha256_run_bound` | A、B 不同（预期披露，请求 hash 侧 run 绑定产物） |
| 24 项检查 | **24 PASS / 0 FAIL**（修复造数 fixture 后） |

**结论（实测，非推算）**：T02 的 K1 稳定排序已落地，两次独立导入的有序块清单、分窗边界、内容 hash 与业务 K2 内容 hash 全部一致，应查块 100% 覆盖，`protected_unchanged=true`，两个隔离任务已软删。
**过程中的一次造数 bug（QA 侧，非业务代码）**：`_create_isolated` 原本给 A/B 用了不同的 `TaskFile.sha256`，而 `source_ordering` 的 `file_key` 取该值 → K2 内容 hash / `stable_key` 天然不等 → 19/24；工程师定位后改为两份隔离文件共用 `OCR_JSON_SHA256`，重跑即 24/24。详见 §9.14。

### ④ 故障注入 — `evidence/fault_injection.json`（`status=measured`）

三种注入均在 `charter.business_scope` 窗口 1 注入，窗口 0 正常命中。`protected_unchanged = true`，3 个隔离任务已软删。

| case | 实测 run | 实测 step | 实测证据/原因 |
|---|---|---|---|
| `auth_401` | `FAILED` / `error_code=SEARCH_FAILED:RuntimeError` / `coverage_complete=false` | `stage:search = FAILED`（`SEARCH_FAILED:RuntimeError`）、`check:charter.business_scope = FAILED / LLM_FATAL`；**`stage:vision` 记录不存在**（符合架构师「记录不存在」断言） | `target_result_rows=0`，窗口 0 证据未保留（**T02 阶段预期**，`effective_after=T03`）；`_chat` 5 次（含 401 降级重试 1 次） |
| `format_error` | `READY` / `stage=done` / **`coverage_complete=false`** | `check:… = SUCCEEDED`、`last_error_code=None`（最终镜像已移除 `PARTIAL_COVERAGE` 短码），阶段全 SUCCEEDED | **保留 1 条命中**且 `not_found_reasons=['coverage_incomplete']`；`_chat` 15 次（含 `_repair` 1 次） |
| `timeout` | `READY` / `stage=done` / **`coverage_complete=false`** | `check:… = SUCCEEDED`、`last_error_code=None`（最终镜像已移除 `PARTIAL_COVERAGE` 短码），阶段全 SUCCEEDED | **保留 1 条命中**且 `not_found_reasons=['coverage_incomplete']`；窗口 1 重试 **3 次**，`_chat` 16 次 |

**`known_gaps_observed = 0`（T02 阶段全部闭环）**；`t03_pending = 1`（`auth_401` 的 window0 证据保留，待 T03「先回先存」后重跑验证）。

> 断言口径也同步修正：旧版把「auth_401 未标 coverage_incomplete / 窗口 0 证据未保留」算成缺口，实际是架构师定稿的**预期行为**（run FAILED 走 `RUN_NOT_READY`、不标覆盖不全；证据保留属 T03）。按 case 分流后，T02 的修复成果不再被误判为失败。修订前的 6 处缺口清单见 §9.14 历史对照。

### ④ 基线脚本退出码 — `evidence/baseline_exit_contract.json`（修订前定位）+ `evidence/baseline_exit_contract_after_T01.json`（T02 复核）

**修订前**（AST + 正则静态检查）：`main()` 返回 `0 if status in ('measured','probe_only') else 1`，status 只由 `evidence['blockers']` 决定，脚本没有读 `processing_runs.state` → FAILED run 仍标 `measured` 且退出 0，即团长点名要修的问题。

**T02 复核：`verdict = fixed`**。新版已读 run 落库 `state` / `coverage_complete` 与阶段状态矛盾，有显式 `status='failed'` 分支和非 0 退出码，status 不再只由 blockers 决定。**这是源码层静态结论**；实跑基线核对退出码仍属 #7 定向验证范围，待团长下发。

### ⑤ Chrome 骨架 — `evidence/coverage_incomplete.skeleton.json`

**17 PASS / 0 FAIL / 4 PENDING**（T02 容器重建后**真实重跑**，仍为 `page.route` 拦截自测、非真实服务数据）。**C7b**（`list_results` 覆盖字段三方一致）、**C9c-0**（先排除 403）、**C9c**（绕过 UI 直接调完成接口 409 + `COVERAGE_INCOMPLETE` + 零写入）三项均已真实执行并 PASS；`not_executed_cases = []`，修订前证据的 `measured_before_revision` / `pending_rerun_cases` 标注随新证据自然消失（见 §9.14）。C9b 完成动作零状态写入、C17「覆盖不全 ≠ 整体只读」、C11/C12 刷新后提示与摘录仍在，全部 PASS。C13–C16 仍为 `PENDING`（任务级 banner、实现后完成按钮 disabled、真实服务定向接口回归、正常完成/历史只读），**不补假结果**。

---

## 4. 从现有代码读到的关键契约（供架构师 / 工程师对齐）

完整机器可读版在 `fixtures/fixed_responses.json` 的 `contract_facts` 段。

### 数据模型 / 状态

- `ProcessingRun`：`state ∈ QUEUED/RUNNING/READY/FAILED/SUPERSEDED`、`stage`、`coverage_complete(bool, default false)`、`error_code`、`checklist_snapshot`、`model_snapshot`、`input_revision`、`started_at/finished_at`。
- `RunStep` 字段：`id, task_id, run_id, file_id, step_key, input_hash, state, attempt, provider_request_id, result_asset_id, last_error_code, started_at, finished_at`；唯一键 `(run_id, step_key, input_hash)`（`uq_run_steps_key_hash`）。`step_key` 现有取值：`stage:classify` / `stage:search` / `stage:vision` / `check:{check_item_id}`（**窗口级 step 尚未落库**）。⚠️ T01/T02 后 step_key 新格式 `u:w{wi}:b{bi}` 见 §9.10。
- `StepState ∈ QUEUED/RUNNING/SUCCEEDED/FAILED/SUPERSEDED`。
- `Result.kind ∈ text/table/seal/signature/not_found`；`not_found_reason ∈ no_matching_evidence / material_missing / coverage_incomplete`；前端 `NOT_FOUND_REASON_LABEL` 映射为「未找到相关证据 / 未上传该材料 / 识别覆盖不完整，请人工复核」。
- `ResultSource`：`file_id, page_id, block_id, start_char, end_char, source_page_number, bbox, polygon, location_precision`。

### 只读接口

- `GET /api/v1/tasks/{tid}/runs/{rid}/timing` 返回 `{run_id, state, started_at, finished_at, elapsed_seconds, steps[]}`；每个 step `{step_key, state, attempt, started_at, finished_at, elapsed_seconds, last_error_code}`。**没有** `coverage_complete`、没有提交时间/HTTP 发起时间、没有窗口级明细。
- `GET /api/v1/tasks/{tid}/runs/{rid}` 返回 `{id, task_id, input_revision, state, stage, coverage_complete, files[], error_code, created_at, finished_at}`。
- `GET /api/v1/tasks/{tid}/results` 返回 `{run_id, is_stale, editable, statistics, items[], next_cursor}`；`editable = run.state==READY && task.state!=COMPLETED`。

### 完成接口现状

`POST /api/v1/tasks/{tid}/complete`（body `{run_id, input_revision}`）**修订前** 409 错误码只有 `RUN_NOT_READY` / `REVISION_CONFLICT` / `NOT_COMPLETE`；完成条件只看 `statistics.overall.can_complete` 与 `input_revision`。⚠️ T01/T02 已新增独立 409 `COVERAGE_INCOMPLETE`（不混进 `NOT_COMPLETE`），`list_results` 新增 `coverage_complete` / `coverage_affected_check_ids`，`create_run` 响应新增 `run_mode="full_rerun"`，见 §9.10。`_incomplete_items` 只返回 `unselected` / `missing_reason`。

### 管线现状（修订前 HEAD 的三处历史缺口，均已在 T01/T02 修复；最新实测见 §3 / §9.14 / §9.17）

> ⚠️ 以下三条是**修订前 HEAD 的实测记录**，保留作对照，**不是当前现状**：`_complete_run` 已改为按 `compute_coverage_summary(...)` 赋值；`search_check_item` 有摘录且存在未覆盖窗口时改为返回 `PARTIAL_COVERAGE` 作为检查项级 `failed_reason`（不是短码）；致命错误改为 `raise` 后 `stage:vision` RunStep 根本不创建。交付时请以 §3 / §9.14 / §9.17 的 T02 后实测为准。

- `processing_pipeline._complete_run` **无条件** `run.coverage_complete = True`，不感知 `_search_stage` 的 `PARTIAL_COVERAGE`。
- `text_search.search_check_item`：`if found: return found, None`，**只要任一窗口有摘录就丢弃 `uncovered` 计数** → 「窗口1命中、窗口2超时耗尽」被误判覆盖完整。
- `_search_stage` 遇 `LLM_FATAL` 只 `_mark_run_failed(...)` 后 `return`，**不写已采集的 `found` 证据**（实测 `target_result_rows=0`）；且 `run_pipeline` 仍继续执行 `_vision_stage`。

### 去重 / 分窗 / 指纹现状

- `load_source_blocks` / `load_file_blocks` 只 `order_by(OcrBlock.sequence_index)`；176 块仅 25 个不同值 → 同值行按 DB 物理序（本轮实测分窗漂移）。⚠️ T01/T02 已改为复用 `source_ordering.order_blocks`，见 §9.10。
- `_window_text()` 把随机 `OcrBlock UUID` 拼进窗口文本；`_fingerprint(check_item_id, block_id, start, end)` 含随机 `block_id` → `window_text_sha256` / `messages_sha256` / `user_sha256` / `Result.fingerprint` 都是 run 绑定产物，**跨 run 比对必须用 `text_sha256 + source_page_number`**。
- `_fingerprint` 用模型返回的 `start_char/end_char` 算指纹，但摘录正文回取整块原文 → 「同检查项/同出处/同原文、不同偏移」会生成不同指纹而重复落库。
- `_dedup_evidence` 排序键 `(source_page_number, block_id)` 含随机 UUID → 去重后同页内顺序不稳定。

### LLM 客户端 / 错误映射

- `LLMClient` 实例级 `threading.Semaphore(LLM_MAX_CONCURRENCY=2)`，`get_llm_client()` 是模块级单例 → **单进程内共享，跨进程/多 worker 不共享**。⚠️ T01/T02 已改为模块级 `BoundedSemaphore(LLM_MAX_IN_FLIGHT=2)`，见 §9.10。
- `LLM_API_BASE` + OpenAI SDK；`complete_json` 先 `json_schema` 严格模式，`LLMFatalError` 时降级 `json_object` 再发一次 `_chat`；schema 校验失败会 `_repair` 一次；最多 `LLM_MAX_TRANSIENT_RETRIES=2`（即最多 3 次尝试）。
- `401 AuthenticationError → LLMFatalError`；`429 RateLimitError / 5xx / APITimeoutError → LLMTransientError`；非法 JSON / schema 校验失败 → `LLMFormatError`。
- `TextSearchOutput = {bundle_id, check_results[{check_item_id, outcome, evidence[{source_refs[{block_id,start_char,end_char}], relation_status, relevance_reason}]}]}`；`source_refs` 三项均为必填（可为 null）；`block_id` 必须是合法 UUID 且属于当前窗口。
- `core/config.py`：**T01/T02 已实现** `CHECKS_PER_REQUEST=1`（X，校验器限 `{1,2,3,6}`）与 `LLM_MAX_IN_FLIGHT=2`（C，唯一在途上限、模块 import 时固化）；`LLM_MAX_CONCURRENCY` 降为兼容别名；`PIPELINE_CONFIG_VERSION=pipeline-v2`。详见 §9.10。

### 登录 / CSRF（定向接口回归必读，`沉淀经验.md` 第 47 条）

- 账号从 `.env` 的 `INITIAL_USERS_JSON` 取第一个（不要在新文档里再复制明文密码）。
- 写请求必须带 session cookie + `X-CSRF-Token` + `Origin: http://localhost:8080`；`require_csrf` 在路由函数体**之前**执行，缺头会先 403，别误判成业务 bug。
- `AuthSession` 在 PostgreSQL，api 容器重建不会让旧会话失效。

---

## 5. 环境变量与依赖

| 变量 / 依赖 | 用途 | 默认 / 示例 |
|---|---|---|
| `OCR_JSON`（宿主机路径） | 15 页样本 | `…/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json`，SHA256 `8879c8a2…60b` |
| 容器内 JSON 路径 | `compare_two_imports.py` / `fault_injection.py` | `/tmp/qa_compare_ocr_slice.json`、`/tmp/qa_fault_ocr_slice.json` |
| `LLM_API_BASE` | 实现后把后端指向模拟服务 | `http://127.0.0.1:8099/v1` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | **超时用例前置**：必须小于 mock 的 `timeout_hang_seconds`（默认 3.0） | 例如 `1` |
| `LLM_MAX_TRANSIENT_RETRIES` | 窗口级重试次数 | `2`（实测超时 case 触发 3 次尝试） |
| `LLM_MAX_IN_FLIGHT` | `C`（唯一在途上限，T01/T02 新增） | `2`；**模块 import 时固化，必须在 worker 进程启动前设置** |
| `LLM_MAX_CONCURRENCY` | 兼容别名（T01/T02 降级） | `2` |
| `CHECKS_PER_REQUEST` | `X`（T01/T02 已实现） | `1/2/3/6`，默认 `1` |
| `PIPELINE_CONFIG_VERSION` | 管线配置版本（T01/T02） | `pipeline-v2` |
| `LLM_WINDOW_CHARACTERS` / `LLM_WINDOW_OVERLAP_CHARACTERS` | 分窗参数 | `8000` / `500` |
| `VERIFY_BASE_URL` | Chrome 骨架 | `http://localhost:8080` |
| `VERIFY_BROWSER_CHANNEL` | 系统 Chrome | `chrome` |
| `QA_COVERAGE_EVIDENCE_OUT` | 骨架证据输出 | `frontend/tests/perf/evidence/coverage_incomplete.skeleton.json` |
| `BUILDX_CONFIG` | 重建镜像时规避沙箱（沉淀经验第 24 条） | `<repo>/.buildx-config` |
| Python | 模拟服务 / 自检：标准库即可；容器脚本需 `app.*`（worker 容器 Python 3.14） | 宿主机 3.13 / 容器 3.14 |
| 浏览器 | `playwright` + 本机系统 Chrome（与 `tasks-final.verify.mjs` 同口径） | — |

---

## 6. 定向接口回归清单（实现完成后补跑）

```bash
# 登录：从 .env 的 INITIAL_USERS_JSON 取第一个账号，保持 cookie jar
curl -c /tmp/qa.cookies -X POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' -H 'Origin: http://localhost:8080' \
  -d '{"username":"<从 INITIAL_USERS_JSON 读取>","password":"<从 INITIAL_USERS_JSON 读取>"}'
# 从登录响应取 csrf_token；所有写请求带 -b /tmp/qa.cookies -H "X-CSRF-Token: <token>" -H "Origin: http://localhost:8080"

# 只读：run 状态 / timing / 结果集
GET  /api/v1/tasks/{tid}/runs/{rid}
GET  /api/v1/tasks/{tid}/runs/{rid}/timing
GET  /api/v1/tasks/{tid}/results

# 写：完成接口（覆盖不全应 409 + 可断言错误码；覆盖完整应 200）
POST /api/v1/tasks/{tid}/complete   {"run_id":"...","input_revision":0}

# 软删任务后若要复验 timing，先 UPDATE tasks SET deleted_at=NULL WHERE id='<tid>'
```

---

## 7. 待实现后补的断言（明确清单，本轮未跑）

### 第一步四项前置

1. **稳定分窗**：**T02 后已实测 24/24 全 PASS**（见 §9.14）；后续批次继续验证 `window_content_hash` / `Result.fingerprint` 与导入 UUID 解绑。
2. **覆盖不全**：
   - 窗口 1 命中、窗口 2 超时耗尽 → 保留摘录与定位、受影响检查项标 `coverage_incomplete`、`run.coverage_complete=false`、run 记录覆盖不全；
   - 应查窗口均成功且无候选 → 正常 `no_matching_evidence`；
   - API 与工作台状态一致、刷新后仍在（真实服务，非拦截）。
3. **完成接口**：覆盖不全 409 + 可断言错误码（即使可见摘录全确认）；覆盖完整 200；历史已完成只读回看。
4. **摘录去重**：`fixed_responses.json` 的 D1–D4（同项同出处同原文不同偏移只存一次、相同正文不同出处保留、同出处多检查项各项保留、去重后稳定出处顺序）。
5. **失败回传**：**T02 后已实测 `known_gaps_observed=0`**（见 §9.14）；剩 T03 的 window0 证据保留、基线实跑退出码、HTTP 层 `fault_injection_rules.json` 复验待后续批次。

### 第二步 X / C

6. `X` 与 `C` 独立配置；`checks_per_request` 支持 `1/2/3/6` 默认 1；分类后一次提交全部独立搜索任务；快请求结束立即补发；分别记录提交时间与实际 HTTP 发起时间；重试计入同一额度。
7. 两 run 同时执行：合计在途符合共享上限、无跨 run/窗口/检查项串写（需工程师在请求里带可识别 run 标识，例如 `X-QA-Tag` 请求头，模拟服务已支持 `tag` 统计）。
8. 调度按「窗口×批次」、覆盖按「窗口×检查项」；批内漏返/重复/无效引用/截断保留其他有效结果；整批超时耗尽该批当前窗口检查项均未覆盖。

### 第三步短用例矩阵

9. `X=1` 全量并发：真实调度器上重跑 `mock_config.full_concurrency.json`，实测请求数、首末到达时间差、峰值在途（本轮 12 请求 / peak 12 只是**模拟服务自测**，不是业务链路结果）。
10. `C=2` 即时补位：一快一慢，打乱响应顺序后结果/出处/覆盖一致（`mock_config.c2_refill.json`）。
11. `X=1` vs `X=3` 固定响应对照：请求数、摘录/出处/跨检查项引用/去重一致（`equivalence_pair`）。
12. 七类批内异常（`scenarios[0..6]`）与 `x1_window1_hit_window2_timeout`（`scenarios[7]`）逐条断言 `expected`。
13. **真实模型抽测由团长统一安排，本 QA 不跑**（避免争抢账号额度）。

### 前端

14. Chrome C13–C16：任务级覆盖不全 banner、实现后完成按钮状态、真实服务定向接口回归、正常完成/历史只读；把 `EXPECTED_BANNER_TEXT` 与 `expected.complete_409_code` 改成实现后的真实字面量再断言。

---

## 8. 本轮未做的事（避免被误读为已完成）

- 未跑任何真实模型调用、未触发外部 OCR、未改业务代码、未重建镜像、未改 `docs/REVIEW_HANDOFF.md`、未新建交接文档副本。
- 未跑真实服务上的 UI 操作（Chrome 用例仅 `page.route` 拦截自测）；未跑真实服务上的覆盖不全/完成接口/历史只读定向回归。
- 未跑 `X`/`C` 调度、`checks_per_request`、两 run 并发、七类批内异常（均依赖第二步实现）。
- 未 `git commit`、未 `git add -A`；工作树原有 ` M .DS_Store` 原样保留。
- 所有「推测 / 示例口径」数字（如 `12→4` 请求数）都在 fixture 里标注 `measured: false`；**不得**当作实测结果引用。

---

## 9. 契约对齐修订（PM / 架构师输入后追加，与 §1–§8 冲突处以本节为准）

> 触发：`software-product-manager` 与 `software-architect` 在 #5 交付后同步了冻结语义、架构设计与 U1–U5 契约。
> 已把下列 delta **全部落进资产并重新自检**（修订前 HEAD：`15 PASS / 0 FAIL / 4 PENDING`；fixture 自检 `PASS / 12 JSON / 21 模板 / 0 错误`）。⚠️ T01/T02 后又有静态对齐，见 §9.10；容器重建期间脚本曾暂停，**T02 后已全部重跑，见 §9.14**。
> 机器可读版在 `fixtures/fixed_responses.json` 的 `contract_facts` 与 `assertion_index_pending_implementation`。

### 9.1 冻结的语义边界（三档 `not_found_reason` 严格不混用）

- `no_matching_evidence`：**该检查项全部应查窗口均成功完成且均无候选**才显示正常「未找到」。
- `coverage_incomplete`：**任一应查窗口未成功完成**（超时耗尽 / 401 / 格式失败 / 致命错 / 整批超时 / 批内漏返）→ 受影响检查项与 run 标记；**成功窗口的摘录与原文定位仍保留**；API 与工作台同一状态、刷新后提示仍在；不得报 `coverage_complete=true`、不得显示「未找到」、不得允许完成。
- `material_missing`：沿用现有规则不变；**技术失败不得标成 not_found**。
- 已写进 `contract_facts.not_found_reason_semantics`，并新增成对对照场景 **`all_windows_success_no_candidate`**（S9：同样零候选、全窗口成功 → 必须 `no_matching_evidence`）。

### 9.2 完成接口（错误码已定值，不再是「待工程师定义」）

- 架构师定值：**`409 {"code":"COVERAGE_INCOMPLETE", ...}`**（PM 明确「最终以架构师定值为准」）。所有 scenario 的 `complete_task_expected_code` 已从占位改成该定值。
- 必须断言 **409 + `detail.code` 可断言 + 零写入**，**即使可见摘录已全部人工确认**也拦。
- Chrome 骨架新增 **C9b「完成 409 后零写入」**（记录全部 POST/PATCH/PUT/DELETE，核对 409 前后无新增业务写入），并支持 `QA_EXPECTED_COMPLETE_409_CODE` 覆盖错误码。
- PM 验收口径：实现后**「完成核对」按钮应 disabled 且说明「暂不能完成」**，不得只靠后端 409 兜底。骨架已把 C8 改成记录 `disabled` 状态、C14 改成可配置真实断言（注入 `QA_COMPLETE_BLOCKED_LABEL` 即启用）；当前 HEAD 实测 `disabled=false`，故 C14 保持 `PENDING`，不写假结果。
- 任务级覆盖不全 banner 同理：`QA_EXPECTED_BANNER_TEXT` 注入后 C13 自动从 `PENDING` 升级为真实断言。

### 9.3 七类批内异常短码（架构师 §4）

落在 `RunStep.last_error_code` / `perf_trace_jsonl`：`BATCH_MISSING_CHECK`、`BATCH_DUPLICATE_CHECK`、`INVALID_CHECK_ID`、`INVALID_BLOCK_REF`、`OUTPUT_TRUNCATED`、`BATCH_TIMEOUT`（整批超时 → 该批当前窗口所有检查项未覆盖）、`FORMAT_FAILED`。

- `fixed_responses.json` 每个 scenario 的 `expected` 已补 `expected_last_error_codes` + `last_error_code_location`。
- `fixtures/fault_injection_rules.json` 已补 `batch_error_code_mapping`；三种注入分别对应 `LLM_FATAL` / `FORMAT_FAILED` / `BATCH_TIMEOUT`。
- 新增场景 **`invalid_check_id_in_batch`**（S10）覆盖 `INVALID_CHECK_ID`；目前共 **10 个场景**（原 8 + S9 + S10）。
- `TEXT_SEARCH_SCHEMA` 结构不变，`check_results` 已是数组，固定响应按「每检查项有且仅有一个 `check_results` 项」构造，无需改 schema fixture。

### 9.4 逐请求证据与调度契约（架构师 §2/§3，待实现）

- **注入点**：`backend/app/llm_client.py::LLMClient._chat` 里的 `self._client.chat.completions.create(**kwargs)`。模拟服务通过 `LLM_API_BASE` 接管；`fault_injection.py` 在容器内 monkeypatch `Completions.create`（等效，且保留 `_classify` 的真实错误映射）。`complete_json` 会包 `_parse` + Pydantic 校验 + 最多一次 `_repair`。
- **限流只有一层**：`llm_client.py` 信号量提为模块级 `BoundedSemaphore(LLM_MAX_IN_FLIGHT = C)`；调度器 `ThreadPoolExecutor(max_workers=C)` 一次提交全部单元、**不自建第二层信号量**。U1「C=N / N 个请求同时在途」由此成立；mock 端「先收齐再放行」观测真实 HTTP 到达时间。
- **`RunStep` 新格式**：`step_key = u:w{wi}:b{bi}`（窗口×批次单元），`provider_request_id = trace_id`，`started_at = t_http_start`、`finished_at = t_http_end`。当前 HEAD 只有 `stage:*` / `check:*`，窗口级 step 待实现。
- **逐请求明细**：`/data/perf_traces/{run_id}.jsonl`，字段含 `trace_id / 实验组 / run / 窗口 / 批次 / 检查项 / attempt / t_submit（提交到线程池）/ t_http_start（acquire 到额度后、_chat 前）/ t_http_end / 状态 / 错误码 / finish_reason / 内容hash / 请求hash`。
  - **U1/U2/U5 的提交时间与实际 HTTP 发起时间一律取自该 JSONL，不要去 DB 里找时间字段**；`t_http_start - t_submit = 额度等待`。
  - 模拟服务只能观测 `arrived_at`（≈`t_http_start`）/`released_at`/`responded_at`，**不提供 `t_submit`**；配置已加 `_trace_fields_note`。
- **`timing` 新增派生** `progress: {total, succeeded, failed, running, has_stable_denominator}`，分母来自 `run.model_snapshot.run_config.units_total`；无分母只给计数不给百分比。原 `run_timing_response_shape` 仍描述当前 HEAD，新增字段见 `contract_facts.run_timing_progress_after_step2`。
- **U5 两 run 隔离**：新增 `mock_config.u5_two_runs.json`（`X-QA-Tag: run-A/run-B`，`by_tag` 统计 + 逐请求 tag）。断言：合计在途峰值符合共享上限 `C`、逐条核对 trace/落库的 `run_id` / 窗口 / 批次 / 检查项归属**无跨 run 串写**。size=8 为示例口径、标了非实测。
- **U2 打乱响应顺序**：`mock_config.c2_refill.json` 新增 `_scramble_response_order`（把 barrier 置 true + `reverse`/`by_check_item` 即可让响应完成顺序与到达顺序相反，且所有请求仍同时在途），并注明打乱后落库摘录/出处/覆盖必须一致。

### 9.5 比对口径修正（重要，别用旧字段）

- 跨 run 逐条结果比对一律用 **`text_sha256 + source_page_number + 页内稳定序号`**，**不用 `Result.fingerprint`**；本轮 `fingerprint` 语义改为「内容 hash，仅供去重」。
- **内容 hash**（不含 UUID/偏移、跨导入可复算）与**请求 hash**（`user_sha256` / `messages_sha256` / `window_text_sha256`，含随机 OcrBlock UUID 绑定值）**分栏记录、不得混用**。`compare_two_imports.py` 里 `content_hash_excluding_import_uuid` 与 `window_text_sha256_run_bound` 已是两个独立字段，符合 PM 要求。

### 9.6 故障注入断言（架构师特别提醒）

401 必须断言 **run / 阶段 / 检查项三处状态一致**：工程师会改 `run_pipeline:479-481` 的无条件 `stage:search SUCCEEDED` 为「致命错误 raise」→ `run FAILED` + `stage:search FAILED` + **停止派发**（`stage:vision` 不应再执行）。`fault_injection_rules.json` 的 `auth_401.expected_after_fix` 已补 `stage_search_state=FAILED` / `stage_vision_state=不执行` / `stop_further_dispatch=true` / `run_and_stage_and_check_states_consistent=true`。当前 HEAD 实测的不一致（`stage:search SUCCEEDED` 而 `check:… FAILED`、视觉阶段仍跑）正是本用例要闭环的缺口。

### 9.7 造数 / 文件边界复核

- `fault_injection.py --check-baseline-only` 对 `scripts/baseline_serial.py` **只读**（AST/正则），**不写入、不改文件、不 git add**；工程师要改它，文件零冲突。
- 其余与架构师列出的工程师改动文件（`backend/app/**`、`frontend/src/api/*`、`$taskId.review.tsx`、`.env*`）无交集，可全程并行。
- 造数约束复核：隔离任务统一 `deleted_at` 软删不物理删；COMPLETED 隔离任务不走 DELETE、直接 SQL 标软删；`ocr_jobs.state=SUCCEEDED` + `next_poll_at IS NULL`；SQL 直插显式给 `input_revision`；写请求带 `X-CSRF-Token` + `Origin: http://localhost:8080` 先排除 403；2 条真实业务任务前后核对未变；改 worker 执行代码后 `build worker` 并进容器 grep 新代码行号再验收。
- 真实模型抽测由团长统一执行（最多 2 次），**不设计成 worker 自动触发**；本轮不做长章程/真实 C 阶梯/每组三次/全文模式/前端档位。

### 9.8 修订后自检

| 项 | 结果 |
|---|---|
| `validate_fixtures.py` | `PASS`，12 个 JSON、21 个响应模板、19 个 `source_ref`、1 个 `response_ref`、0 错误 |
| `coverage_incomplete.verify.mjs` | `15 PASS / 0 FAIL / 4 PENDING`（当时；**T02 后 17/0/4**，见 §9.14） |
| `node --check` / 全部 JSON 语法 | 通过 |
| 本轮（当时）**未重跑** | `compare_two_imports.py`、`fault_injection.py`、模拟服务自测、Chrome 骨架；⚠️ **T02 后已全部重跑，见 §9.14** |

新增/改动文件：`mock_config.u5_two_runs.json`（新）、`fixtures/fixed_responses.json`、`fixtures/fault_injection_rules.json`、`mock_config.{example,full_concurrency,c2_refill}.json`、`frontend/tests/perf/coverage_incomplete.verify.mjs`、`frontend/tests/perf/fixtures/coverage_incomplete.results.json`、`README.md` 与对应 `evidence/*.json`。

### 9.9 PM 二次确认后的三条边界（已落地）

PM 确认「前端完成按钮 disabled + 页面明确说明暂不能完成」与「后端完成接口 409 `COVERAGE_INCOMPLETE`」是**并列要求、不是二选一**（用户原话「页面明确说明暂不能完成」+「直接调完成接口返回 HTTP 409」；纵深防御见 `沉淀经验.md` 第 50 条与交接文档第九节第 9 条），C14 无需改。另守住三条：

1. **覆盖不全 ≠ 整体只读**：`disabled` 只针对「完成」这一个动作；已有摘录仍可接受/拒绝、出处仍可点击、刷新后提示仍在。历史已完成任务才是全部写操作 `409 TASK_READ_ONLY`，**两种状态不得复用同一套禁用逻辑**。骨架新增 **C17**（刷新后显式断言接受/拒绝与出处定位仍可用）。`C9b/C9c` 的「零写入」只核**完成动作相关的状态写入**；接受/拒绝的正常 `PATCH .../decision` 属允许写入，已在断言 detail 与 fixture 的 `expected.zero_write_assertion_scope` 里写明，不判违规。
2. **「直接调完成接口 409」必须独立于 UI 保留**：原先 C9/C9b 挂在「按钮可点击」分支里，实现后按钮 disabled 会丢掉接口层证据 —— 这是真实缺口，已修正。新增 **C9c**：用 `page.evaluate(fetch POST /complete)` **绕过前端直接打 API**，断言 `409 + detail.code + 零写入`，刻意放在按钮状态分支之外，无论按钮是否 disabled 都执行。fixture 的 `expected.complete_api_assertion_independent_of_ui` 已记录。
3. **注入式升级为 PASS 必须标注驱动来源**（呼应 `沉淀经验.md` 第 53 条「覆盖范围表述要与证据对齐」）：C13/C14 的 PASS detail 已加「预期由注入的 `QA_EXPECTED_BANNER_TEXT` / `QA_COMPLETE_BLOCKED_LABEL` 驱动，非前端文案实测」；`writeEvidence()` 新增 `injected_expectations` 字段逐个记录三个 `QA_EXPECTED_*` 环境变量的实际注入值（未注入记 `null`）。**4 项 PENDING 如实保留，不为好看补结果。**

修订后重跑：`node --check` 通过；Chrome 骨架 **15 PASS / 0 FAIL / 4 PENDING**（新增 C9c、C17，C9b 语义收窄）；`validate_fixtures.py` 仍 `PASS`（全量 14 个 JSON 合法，见 §9.10）。⚠️ 此数字为 T01/T02 前实测；**T02 后重跑结果见 §9.14**。

### 9.10 T01/T02 落地后的静态对齐（容器重建期间）

**纪律**：工程师 `software-engineer` 通知即将 `docker compose build api worker && up -d api worker`（config.py/.env 改了，两个独立镜像都要重建）。重建期间 **全部容器侧操作暂停**：不跑 `docker exec` / `docker cp`、不跑 `compare_two_imports.py` 与 `fault_injection.py --run-cases`（依赖 worker 容器）、不跑 `coverage_incomplete.verify.mjs`（依赖 api 容器 SPA）、不跑 `selftest_mock_server.py` 里的浏览器链。本轮只做**宿主机静态文件读写 + 纯本机语法/结构自检**，未碰任何容器。

**已读源码（宿主机文件，非容器）**：`backend/app/source_ordering.py`（K1 稳定排序 `(file_order, page_key, page_ordinal)`，页内 `bbox(top,left) → sequence_index → provider_block_id → global_block_id → sha256(canonical_text)`；K2 `content_hash = sha256(f"{file_key}|{page_key}|{page_ordinal}|{canonical_text}")[:64]`）、`core/config.py`（`CHECKS_PER_REQUEST=1` 限 `{1,2,3,6}`、`LLM_MAX_IN_FLIGHT=2`、`LLM_MAX_CONCURRENCY` 兼容别名、`PIPELINE_CONFIG_VERSION=pipeline-v2`）、`text_search.py` / `classification.py`（`bundle_id=w{idx}`、`Window.window_text_sha256`、`SearchOutcome`、`PARTIAL_COVERAGE` 修复）、`api/routes/runs.py`（`list_results` 新增 `coverage_complete` / `coverage_affected_check_ids`、`complete_task` 独立 409 `COVERAGE_INCOMPLETE`、`create_run` 新增 `run_mode="full_rerun"`）、`scripts/baseline_serial.py`（退出码已修）。

**基线脚本静态复核：`verdict = fixed`**（新证据 `evidence/baseline_exit_contract_after_T01.json`）。新版已读 run 落库 `state` / `coverage_complete` 与阶段状态矛盾、有显式 `status='failed'` 分支和非 0 退出码，且 status 不再只由 `evidence['blockers']` 决定 —— 团长点名的「失败 run 标 measured、退出码 0」在源码层已修。旧证据 `evidence/baseline_exit_contract.json` 保留为修订前对照；`fault_injection.py::check_baseline_exit_contract` 已增强为 `fixed / still_buggy / inconclusive` 三态判定。**注意这是静态检查，真正闭环仍需实跑基线核对退出码。**

**资产修订（纯宿主机）**：
- `bundle_id` 全局对齐 `w{idx}`：`fixed_responses.json` 22 处、`fault_injection_rules.json` 3 处、`mock_config.example.json` 2 处；`mock_llm_server.py` 的 `{{BUNDLE}}` 渲染改为 `w{window_index}`；fixture 的 `placeholder_rules` 同步。
- `fixed_responses.json` 的 `contract_facts`（42 键）新增 8 个 T01 契约段：`bundle_id_format_after_T01`、`search_check_item_outcome_api`、`llm_chat_return_after_T01`、`source_ordering_api_after_T01`、`list_results_new_fields_after_T01`、`create_run_new_fields_after_T01`、`pipeline_config_version_after_T01`，并把 `checks_per_request_status` / `llm_in_flight_after_step2` / `search_check_item_current_gap` / `complete_task_*` 从「待实现」改为「已实现，待实测」。`complete_task_existing_409_codes` 补 `COVERAGE_INCOMPLETE`。
- **`compare_two_imports.py` 关键修正**：`expected` 口径原先是 QA 自写稳定排序（按 `ocr_page_index / provider_line_index / sequence_index / provider_block_id`），与业务 `source_ordering.order_blocks` 的 K1 键**不一致**，修复后重跑会产生误判。现已改为**直接复用 `order_blocks(rows, page_by_id, file_key_by_id)`**（旧镜像无该模块时回退 QA 独立排序并标 `ordering=qa_independent_fallback`），`stable_key` 改为 `file_key|page_key|page_ordinal|content_hash[:16]`（不含任何 UUID）；新增导出 `content_hash_k2_business_aggregate` / `ordering_source` / `order_sources_used`，并在窗口描述里记录业务侧 `Window.window_text_sha256`。
- Chrome：`fixtures/coverage_incomplete.results.json` 的 `/results` 响应补 `coverage_complete=false` 与 `coverage_affected_check_ids=["charter.approval_body"]`；骨架新增 **C7b**（`/results` 覆盖字段与 `GET run`、工作台提示三方一致）。⚠️ **T02 后 C7b 已真实运行并 PASS**，见 §9.14。
- `fault_injection.py`：注入器补 `_chat` 返回 `(content, finish_reason)` 元组的兼容说明 —— 本脚本 patch 的是更底层 `Completions.create`（返回带 `choices[0].message.content` + `finish_reason` 的响应对象），新 `_chat` 仍从同一位置取 content，不受影响；若改 patch `_chat` 需返回 `(json字符串, "stop")`。
- `fixtures/fault_injection_rules.json` 补 `llm_chat_return_compat_after_T01` 与 `post_T01_status`。
- 配置与 fixture 注明：**`LLM_MAX_IN_FLIGHT` 模块 import 时固化，U1 的 `C=N` 必须在 worker 进程启动前通过环境变量设置，不能运行时改**。

**待工程师/团长确认（不推断）**：
1. `_complete_run` 是否已按全部窗口 `SUCCEEDED` 计算 `run.coverage_complete`（工程师本批未明确列出，fixture 标「待实测确认」，未写成已修复）。
2. U1 `C=N` 的落地方式：`LLM_MAX_IN_FLIGHT` 在模块 import 时固化，是否需要在 worker 容器启动前注入 env / 重启 worker？请在重建时一并明确，否则 U1 峰值断言会不成立。
3. `SearchOutcome`（工程师说「供后续批次」）、`RunStep.step_key=u:w{wi}:b{bi}`、`/data/perf_traces/{run_id}.jsonl`、`timing.progress` 哪些已在 T01/T02 落地、哪些属后续批次？我按「待实测/后续批次」保留断言，未擅自标记已实现。

**重建完成后已重跑（真实数字见 §9.14）**：`compare_two_imports.py`（要求 actual 口径 24 项全 PASS）→ `fault_injection.py --run-cases`（三种注入，6 处实测缺口归零）→ `--check-baseline-only`（静态 fixed 已确认，再看实跑退出码）→ `selftest_mock_server.py` → `coverage_incomplete.verify.mjs`（含 C7b）→ 按 §6 的定向接口回归（login/CSRF、`/results`、`/runs/{rid}`、`/timing`、`/complete`）。

**本轮纯本机自检（当时结果，最新见 §9.12）**：`validate_fixtures.py` PASS（扫 `backend/tests/perf` 下 12 个 JSON / 21 个响应模板 / 0 错误）；全量 backend+frontend 共 **14 个 JSON** 全部合法；5 个 Python 全部通过 AST / `py_compile`；`node --check` 通过。`bundle_id` 的 `window-N` 残留当时仅存在于 `evidence/compare_two_imports.json` 历史实测证据（原样保留、不篡改）；**T02 重跑后该证据已被覆盖为 `w{idx}`，残留消失**，所有活动资产现均为 `w{idx}`（见 §9.14）。

### 9.11 架构师定稿（三处判定 + 两处必改）与 PM 的 CSRF 实操

> 容器重建期间仍暂停，本节全部为**宿主机静态修订**；未跑 Chrome 骨架、未跑任何容器侧脚本。

**⚠️ 两处必改（涉及团长已拍板的错误码语义，已落地）**
- **A. 401 的 `complete_task_code`：`COVERAGE_INCOMPLETE` → `RUN_NOT_READY`**。链路：401 → `LLMFatalError` → 工程师改成 `raise` → `_mark_run_failed` → `run.state=FAILED`；`complete_task` 第一道拦截 `if not run or run.state != READY → 409 RUN_NOT_READY`，**根本走不到** `REVISION_CONFLICT` 之后的 `COVERAGE_INCOMPLETE` 拦截。`format_error` / `timeout` 两个 case 保持 `COVERAGE_INCOMPLETE`（run 正常走完 `_complete_run` → READY，但 `coverage_complete=false`）。已同步 `fault_injection_rules.json` 与 `fault_injection.py::_build_expected`。
- **B. `stage_vision_state: "不执行"` → 「`RunStep` 中不存在 `step_key == 'stage:vision'` 的行」**（`stage_vision_step_absent: true`）。改 `raise` 后 `run_pipeline` 的 except 直接 return，`stage:vision` 的 `_touch_step(RUNNING)` 不会执行 → 记录根本不创建，不是 state 等于某个值。`stage_search_state: "FAILED"` 保持不变。

**三处判定定稿（expected 值不改，补约束与文案）**
1. **S5 `INVALID_BLOCK_REF` 确认**：不算未覆盖 → `no_matching_evidence` / `run_coverage_complete=true` / 200。判别式是「该检查项在该窗口是否有可采信的响应」：幻引里模型给了响应（HTTP 成功 + JSON 合法 + schema 通过）→ 覆盖达成，无效引用只是候选不可采信。补：对应 `RunStep u:*` 的 `state` 仍应为 `SUCCEEDED`（观测短码只在 `last_error_code` / JSONL）、**模型声称 found 但引用无效 → 该检查项零 Result 行落库**（防幻觉核心）、已知局限「系统显示『未找到相关证据』属输出质量异常，需人工复核该检查项」需显式留痕，不得静默降级。
2. **S10 `INVALID_CHECK_ID` 确认**：顶替 → 漏返 → `coverage_incomplete` + 409，短码 `INVALID_CHECK_ID` + `BATCH_MISSING_CHECK`。补两种构造区分，并**新增 S10b 对照场景 `invalid_check_id_extra_only`**（11 个场景）：非法 ID 只是额外多返回一条、本批 N 项全在 → 只记 `INVALID_CHECK_ID`、丢弃多余响应、不记 `BATCH_MISSING_CHECK`、不算未覆盖、200。另补「即使该检查项在其他窗口已有成功摘录，仍要 `coverage_incomplete` + 409」，覆盖判定优先于「有摘录」。
3. **`BATCH_TIMEOUT` 字面量统一、不新增独立短码**（X=1 时批边界与窗口边界重合）。两处定义文案改成粒度无关；S7/S8 notes 补「区分窗口级 vs 整批级不用短码，用 `run_config.X` + `step_key=u:w{wi}:b{bi}` + `coverage_incomplete_check_items` 项数（X=1 为 1 项、X=3 为 N 项）」。并明确 **`PARTIAL_COVERAGE` 是检查项级 `failed_reason`，不是 `RunStep.last_error_code` 短码，不得进 `expected_last_error_codes`**；`FORMAT_FAILED` 与超时不同类。

**时序（防止 #7 定向验证在 T02 刚完成时误判失败）**：`window0_evidence_preserved` 与 `result_sources` 断言统一标 `effective_after: "T03"`。T03 接入「先回先存」后 window0 单元完成即独立短会话写 `Result+ResultSource`；**T02 阶段 `_search_stage` 的 `LLM_FATAL` 分支不写 `found`，window0 证据仍丢**，此阶段只能断言「JSONL trace / 基线脚本 `evidence` 保留观测证据」。三个 case 均已标注。

**交接文档副作用（请工程师原地更新 `REVIEW_HANDOFF.md`，QA 不改交接文档）**：FAILED run 的 `results` 仍会被 `list_results` 查出（`order_by(created_at.desc()).first()` 不看 state），但 `editable=false`（`run.state != READY`），用户只读回看 —— 预期行为，**不需要工程师清理 FAILED run 的结果行**。已记录在 `fault_injection_rules.json::failed_run_results_side_effect`。

**PM 的 CSRF 实操提醒（已落进 C9c）**：`page.evaluate(fetch POST /complete)` 现在带 `X-CSRF-Token` + `Origin` + `credentials: "include"`；token 从 `/auth/me` 响应取（可用 `QA_CSRF_TOKEN` 覆盖），不硬编码；断言顺序先 **C9c-0 排除 403**（`require_csrf` 在路由函数体之前执行，缺头会先 403，别误判成业务 bug，经验 47）再断言 409；零写入 predicate 加目标任务 ID 过滤（经验 41），C9b/C9c 都限定 `/tasks/${TASK_ID}/`。证据 `evidence.csrf` 记录 header 来源与 origin，不记 token 明文。**C9c-0 / C9c / C7b 均未跑**（容器重建中），骨架数字仍是修订前实测的 15 PASS，不写推算值。

**U1–U5 断言字段 → 唯一数据源（架构师提供，钉死「时间字段取自 JSONL」）**

| 用例 | 关键断言字段 | 唯一数据源 |
|---|---|---|
| U1 全量并发 `C=N` | 峰值在途数、首末 HTTP 到达时间差、`t_http_start - t_submit` = 额度等待 | `perf_traces/{run_id}.jsonl` + mock 落盘统计；**不去 DB** |
| U2 `C=2` 即时补位 | 快请求返回后 `t_http_start` 早于慢请求 `t_http_end`；`Result.rank` / 出处 / 覆盖 / 排序与顺序无关 | JSONL + `results` / `result_sources`（按 `text_sha256 + source_page_number + 页内序号` 比对） |
| U3 `X=1` vs `X=3` | 请求数、`run_config.X`、两份 `run_config` 除 X 外全等、跨检查项引用 / 去重一致 | JSONL 请求计数 + `model_snapshot.run_config` + 结果逐条比对 |
| U4 部分失败 | 七类短码落 `RunStep.last_error_code` + JSONL；受影响项 `coverage_incomplete`；`complete_task` 409 code | `run_steps` + JSONL + 409 响应体 |
| U5 两 run 同时 | 合计在途 ≤ `C`、`X-QA-Tag` 分组统计、逐条 `run_id` / 窗口 / 批次 / 检查项归属无串写 | JSONL + mock `by_tag` + `run_steps` / `results` 按 run_id 分组 |

### 9.12 错误码断言入口统一（架构师提醒，已固化为自检）

架构师只读核对后标出一处实操风险：同一个「完成接口错误码」字段曾混用**纯字面量**与**带括注**两种格式，`#7` 若对 `detail.code` 用 `==` 严格相等，带括注值会全部 FAIL。已按「值统一纯字面量、说明移到独立 `*_note`」处理：

- `fixed_responses.json` 5 处 `scenarios.*.expected.complete_task_expected_code`：`"COVERAGE_INCOMPLETE（架构师定值）"` → `"COVERAGE_INCOMPLETE"`，并新增 `complete_task_expected_code_note` 承载来源说明；`contract_facts.complete_task_code_source_note` 写明「断言值一律 `^[A-Z][A-Z0-9_]*$`，来源说明不得拼进值」。
- `fault_injection.py::_build_expected` 的 `expected_complete_task_code` 同样改为纯字面量 + 独立 `complete_task_code_note`。`fault_injection_rules.json` 的 `complete_task_code` 原本就是纯字面量（`RUN_NOT_READY` / `COVERAGE_INCOMPLETE`），不动。
- **说明性字段不受约束**：`complete_task_409_code_decided` / `complete_task_code_note` / `complete_task_expected_code_note` / `complete_task_current_gap` 等保留中文说明，它们不是断言入口。
- **`validate_fixtures.py` 新增字面量自检**：递归检查 `complete_task_code` / `complete_task_expected_code` / `expected_complete_task_code` / `complete_409_code` 四个字段（含 `fault_injection.py` 内的同名字符串），不匹配 `^[A-Z][A-Z0-9_]*$` 即报错；同时把前端 `coverage_incomplete.results.json` 纳入扫描。已做**负向验证**：人为塞回 `"COVERAGE_INCOMPLETE（架构师定值）"` 会被准确抓出，而 `evidence/` 下的历史实测快照（含修订前的旧值）按文件名跳过、**原样保留不篡改**（与当时 `bundle_id` 历史残留的处理原则同理），跳过清单写入 `error_code_check_skipped_evidence_files`。

**修订后纯本机自检（真实）**：`validate_fixtures.py` PASS（13 个 JSON = backend/perf 12 + 前端拦截 fixture 1；21 个响应模板；11 个错误码断言字段；0 错误）；全量 backend+frontend 14 个 JSON 合法；5 个 Python AST 通过；`node --check` 通过。⚠️ **T02 后已全部重跑，最新实测数字见 §9.14。**

### 9.13 证据标注与错误码场景隔离（PM 复核）

**一、15 PASS 数字的覆盖范围显式标注（经验 53；该历史标注已被 §9.14 的 T02 后真实重跑取代）**
- `frontend/tests/perf/evidence/coverage_incomplete.skeleton.json` 新增纯元数据：`measured_before_revision: true`、`pending_rerun_cases: ["C7b", "C9c-0", "C9c"]`、`revision_note`、`pending_rerun_cases_note`、`host_only_checks_after_revision`。写入时用断言校验 `results` / `summary` 前后字节一致 —— **只加标注，未改动任何实测结果**。其中 **C9c 属「同名但内容已修订」**（修订前曾执行过，但 CSRF 头与零写入 predicate 已改），仍需重跑。
- 骨架脚本 `writeEvidence()` 新增 `EXPECTED_CASE_NAMES`（21 个预期用例）与动态 `not_executed_cases` / `coverage_note`：重建后重跑会自动列出本轮**名称未出现**的用例，`summary` 只统计 `results` 里实际执行过的项。该动态字段按名称判断，**无法识别「同名但内容已修订」**，`coverage_note` 已写明这类情况由修订前证据的 `pending_rerun_cases` 人工标注兜底（纯本机用现有证据验证：动态结果为 `["C7b","C9c-0"]`，C9c 由人工标注补齐为三项）。
- README §3 ⑤ 段落曾显著标注「15 PASS 为修订前实测…」；T02 重跑后该标注随新证据自然消失（`not_executed_cases=[]`），见 §9.14。

**二、错误码场景隔离核查（PM 担心 `auth_401` 定稿连带改错 C9c）**

| 场景 | `run.state` | 期望 `complete_task` |
|---|---|---|
| S8 `x1_window1_hit_window2_timeout`、Chrome `C9c` / `C9c-0`、`format_error`、`timeout`、其余覆盖不全场景 | `READY` + `coverage_complete=false` | **409 `COVERAGE_INCOMPLETE`** |
| `fault_injection:auth_401` | `FAILED` | **409 `RUN_NOT_READY`**（第一道拦截即返回，不标覆盖不全） |
| S9 `all_windows_success_no_candidate` | `READY` + 覆盖完整 | 200 |

核查结论：**C9c / S8 未被连带改错** —— `fixed_responses.json` 的 5 个覆盖不全场景、Chrome fixture 的 `complete_409_code`、`fault_injection_rules.json` 的 `format_error` / `timeout` 全部保持 `COVERAGE_INCOMPLETE`，只有 `auth_401` 是 `RUN_NOT_READY`。PM 已向团长提交 PRD §4.0 收窄说明，口径与资产一致。

但两处**说明性字段**原本无限定、容易被读成「所有 409 都用一个码」，已补：`fixed_responses.json::contract_facts.complete_task_409_code_decided` 与 `fault_injection_rules.json::complete_task_code_decided` 均追加适用范围说明，并各新增机器可读 `complete_task_code_scenarios` 对照；S8 的 `expected` 加 `complete_task_expected_code_scope_note` 与 `chrome_c9c_link`；Chrome fixture 加 `complete_409_code_scope_note`。**两个场景分别验、不合并**，否则交付口径「完成接口 409」会指向错误码。

**纯本机自检（真实）**：`validate_fixtures.py` PASS（13 JSON / 21 个响应模板 / 11 个错误码断言字段 / 0 错误）；14 个 JSON 合法；5 个 Python AST；`node --check` 通过。⚠️ **T02 后已全部重跑，见 §9.14。**

---

## 9.14 T02 容器重建后真实重跑闭环（本轮实测，覆盖此前所有「待重跑」状态）

> 触发：工程师通知 `docker compose build api worker && up -d api worker` 完成（api+worker 新镜像、`http://localhost:8080/` → 200），并把我 `compare_two_imports.py` 当兼容回归跑出 **19/24**，定位到根因在 **QA 造数 fixture**（非业务代码）。本节所有数字均为**T02 后真实实跑**，来自 `evidence/` 落盘文件；§9.10–§9.13 里「容器重建期间暂停 / 未产生实测数字」的表述均为当时状态，已被本节取代。

### 9.14.1 修复的两处 QA 侧问题

1. **造数 fixture（工程师定位，QA 修复）**：`_create_isolated(label)` 原本给 A/B 两个隔离 `TaskFile` 用 `_sha256_str(f"qa-compare-slice-{label}")` → A/B `sha256` 不同；而 `source_ordering.load_file_keys` 把 `file_key` 取 `TaskFile.sha256`，K2 `content_hash = sha256(file_key|page_key|page_ordinal|canonical_text)` 与 `stable_key` 前缀因此天然不等，级联导致有序清单、分窗边界 5 项 FAIL。已改为两份隔离文件**共用 `OCR_JSON_SHA256`**（二者导入的是同一份 15 页 OCR JSON，本就该声明为同一份文件内容）。修复后 **24/24**。
2. **断言口径过时（QA 自查，测试代码 bug）**：T02 首次重跑 `fault_injection.py --run-cases` 得到 `known_gaps_observed=2`，但这两条分别是「auth_401 未标 `coverage_incomplete`」与「window0 证据未保留」——按架构师定稿，前者是 run FAILED 走 `RUN_NOT_READY` 的**预期行为**，后者是 `effective_after=T03` 的**预期局限**。已把 `known_gaps_observed` 按 case 分流：`auth_401` 只断言 `run FAILED` / `stage:search FAILED` / `stage:vision` 记录不存在 / 证据保留记入 `t03_pending`；覆盖不全类才断言 `coverage_complete=false` + `coverage_incomplete` + 证据保留。重跑后 **`known_gaps_observed=0`、`t03_pending=1`**。
3. 另在 `compare_two_imports.py` 的 `_collect` 加 `order_sources_note`：单块页的 `order_source=canonical_text_sha256` 是末级回退、这类页只有 1 个块不存在阅读顺序问题，`['bbox','canonical_text_sha256']` 属如实记录，不是旧数据异常（工程师提示）。

### 9.14.2 修订前 HEAD → T02 后 实测对照

| 项 | 修订前 HEAD | 工程师兼容回归 | **T02 后（本轮）** |
|---|---|---|---|
| `compare_two_imports.py` 24 项 | 18 PASS / 6 FAIL（`actual` 分窗漂移） | 19 / 5（QA 造数 `file_key` 不同） | **24 PASS / 0 FAIL** |
| `content_hash_k2_business_aggregate` A/B | 未采集（旧口径） | 不等（`95e8822e…` / `9fee3059…`） | **相等 `606a4e17…`** |
| `ordered_block_list_sha256` A/B | 相等 `f7d9bfdb…`（QA 自写口径） | 不等（`4edf7de5…` / `50ade10d…`） | **相等 `c6e9613f…`**（业务 K1 口径） |
| `fault_injection.py` `known_gaps_observed` | 6 处 | — | **0**（+ `t03_pending=1`） |
| `format_error` / `timeout` | `coverage_complete=true`、未标 `coverage_incomplete` | — | **`coverage_complete=false`、`['coverage_incomplete']`、保留 1 条命中** |
| `auth_401` | `stage:search SUCCEEDED`、`stage:vision SUCCEEDED` | — | **`stage:search FAILED`、无 `stage:vision` 记录、`RUN_NOT_READY`** |
| 基线退出码静态复核 | `still_buggy` | — | **`verdict = fixed`** |
| Chrome 骨架 | 15 PASS / 0 FAIL / 4 PENDING | — | **17 PASS / 0 FAIL / 4 PENDING**，`not_executed_cases=[]` |
| 模拟服务自测 | 8/8，peak 12，gap 2.249 → 1.745 ms | — | 8/8，peak 12，**最终镜像 gap 1.741 ms**（中间一次 1.806 ms） |
| `validate_fixtures.py` | 12 JSON / 21 模板 | — | **13 JSON / 21 模板 / 11 错误码断言字段 / 0 错误** |

### 9.14.3 T02 后关键实测数字

- **稳定分窗**：176 块 / 9570 字符（A=B）；`content_hash_excluding_import_uuid` A=B=`62290b51…e09`；K2 聚合 A=B=`606a4e17…93c1`；有序清单 hash A=B=`c6e9613f…c6c`；`ordering_source=business_order_blocks`；`order_sources_used=['bbox','canonical_text_sha256']`；`expected`/`actual` 均 2 窗口（w0=133 块/7998 字、w1=51 块/2095 字），两次导入完全一致、176/176 全覆盖、窗口内顺序单调；`window_text_sha256_run_bound` A≠B（请求 hash 侧 run 绑定产物，预期披露）。
- **故障注入**：`auth_401` → run `FAILED`/`SEARCH_FAILED:RuntimeError`、`stage:search FAILED`、`check FAILED/LLM_FATAL`、无 `stage:vision` 行、`_chat` 5 次；`format_error` → `_chat` 15 次（含 `_repair` 1 次）；`timeout` → 窗口 1 重试 3 次、`_chat` 16 次。两者均 `run READY`/`coverage_complete=false`、保留 1 条命中、`not_found_reasons=['coverage_incomplete']`；**最终镜像已移除 `PARTIAL_COVERAGE` 短码**，`check` step 的 `last_error_code` 现为 `None`（上一版镜像曾为 `PARTIAL_COVERAGE`，属历史实测）。
- **Chrome**：C7b（`/results` 的 `coverage_complete=false` + `coverage_affected_check_ids=['charter.approval_body']` 与 run 视图、工作台三方一致）、C9c-0（先排除 403）、C9c（绕过 UI 直接 POST `/complete` → 409 `COVERAGE_INCOMPLETE` + 零写入）三项**真实执行并 PASS**；C9b 完成动作零状态写入、C17 覆盖不全≠整体只读、C11/C12 刷新后提示与摘录仍在均 PASS。`injected_expectations` 三个注入值仍为 `null`，4 项 PENDING 如实保留。

### 9.14.4 边界与仍待 #7 的事项

本轮实跑：造数全部用隔离任务并 `deleted_at` 软删（`compare` 2 个 + `fault_injection` 3 个，共 5 个；`protected_unchanged=true`，2 条真实业务任务 `state`/`deleted_at` 前后一致）；**未调用任何真实模型 / 外部 OCR**（故障注入走容器内 monkeypatch、Chrome 走 `page.route`、模拟服务纯本地）；未改业务代码、未改 `docs/REVIEW_HANDOFF.md`、未 commit / 未 git add、`.DS_Store` 原样。

**仍待团长下发 #7 定向验证**（本轮未跑，不写推算值）：
1. 真实服务定向接口回归（§6）：登录取 CSRF、`/results`、`/runs/{rid}`、`/timing`、`/complete`（覆盖不全 409 零写入 / 覆盖完整 200 / 历史只读）。
2. Chrome C13（任务级 banner）、C14（完成按钮 disabled + 「暂不能完成」）、C15/C16（真实页面操作、正常完成与历史只读）。
3. T03「先回先存」后的 `auth_401` window0 证据保留；基线脚本**实跑退出码**（当前仅静态 `fixed`）。
4. HTTP 层 `fixtures/fault_injection_rules.json` 三种注入复验。
5. 第二步 X/C 实现后的 U1–U5 短用例矩阵（`CHECKS_PER_REQUEST` / `LLM_MAX_IN_FLIGHT` 调度、trace JSONL、两 run 隔离、七类批内异常逐场景断言）；真实模型抽测由团长统一安排。

### 9.15 动态用例清单的一致性加固（PM 可选建议，已落地）

PM 提出：重建后重跑时 `writeEvidence()` 的动态 `not_executed_cases` 仍按名称判断，可能与人工 `pending_rerun_cases` 给出不一致信号（「自动清单说 C9c 已执行」vs「人工清单说待重跑」），交付文档里两份清单打架正是经验 53 最怕的情形；建议 ① 用例加内容版本标记、② 重跑时做一致性比对，或交付说明以人工清单为准。

**先澄清实况**：T02 后真实重跑时，新证据完全由 `writeEvidence()` 生成，**不含** `measured_before_revision` / `pending_rerun_cases`（脚本不输出这两个历史标注字段），它们随证据覆盖自然消失；同时 `not_executed_cases = []`（21 个预期用例全部执行）。因此本次交付**两份清单并未打架**，PM 担心的场景没有出现。

**仍做了轻量加固（不引入需人工清空的待办状态）**：
- `coverage_incomplete.verify.mjs` 新增 `CASE_CONTENT_VERSIONS`（未列出的用例默认 `v1`；被修订过的 `C7b` / `C9c-0` / `C9c` / `C9b` / `C17` 各有语义化版本，如 `C9c = v2-csrf-header-plus-task-id-zero-write`）。
- `writeEvidence()` 输出 `case_content_versions`（21 项）、`prior_evidence_path`，并**读取上一份证据**的版本表做比对，输出 `case_version_diffs_vs_prior`；非空即须显式复核。`revision_check_note` 写明「版本变化的用例即使名称出现过也需重跑，交付说明以人工标注为准并注明原因」，`coverage_note` 保持纯粹的动态未跑清单语义。
- **负向验证（纯本机）**：伪造上一份证据把 `C9c` 标为 `v1-no-csrf`，比对准确检出 `[{"case":"C9c","prior":"v1-no-csrf","current":"v2-csrf-header-plus-task-id-zero-write"}]`。
- **本次实跑**：17 PASS / 0 FAIL / 4 PENDING 不变；`not_executed_cases=[]`、`case_content_versions` 21 项、`case_version_diffs_vs_prior=[]`（上一份证据尚无版本字段，按「无基线」处理，符合首次引入版本标记的预期）。

这样既覆盖了 PM 的方案 ①（版本标记让动态算法可按内容版本判断）与方案 ②（与上一份证据自动比对并显式记录差异），又不依赖一份容易忘记清空的人工清单。

### 9.16 两次导入独立性核查（PM 严谨性确认，已固化为自动检查）

PM 提出：A/B 改为共用 `OCR_JSON_SHA256` 后，24 PASS 里「内容 hash 跨两次导入相等」是否仍在**两个独立 run/task** 上比对，没有退化成同一次数据的自比对；`content_hash_excluding_import_uuid` 排除的应是导入时生成的随机 UUID（`OcrBlock.id` / `TaskFile.id`），而不是文件 sha256。这关系第一步①「与导入 UUID 无关」是否真被验到。**核查结论：是，确实在两个独立数据集上比对，未退化。**

**真实证据（`evidence/compare_two_imports.json`）**
- A `task_id=f98f7013…72bf494561dc`、B `task_id=e414029b…7e2408641e`；A `file_id=70b937a7…a5ad7dcc9703`、B `file_id=f5774043…487137597c26` → **两个独立 Task / TaskFile**（`_create_isolated` 每次由 `default_factory=uuid4` 生成）。
- 两次 `import_ocr_json` 分别调用（A 0.075s / B 0.033s），各自生成随机 `OcrBlock` / `OcrPage` / `OcrJob` UUID，跑完分别软删。
- **决定性反证**：`window_text_sha256_run_bound`（请求 hash 侧，`_window_text` 内含 `block_id=<UUID>`）A=`['0dd3bba2…','b2b7b893…']`、B=`['d7fb3356…','cf1b27da…']`，**A ≠ B**；24 项检查里的「（披露）现有 `_window_text` 跨导入不同」`ok=True`。若退化成同一次数据自比对，这里必然相等。
- 在此前提下 `content_hash_excluding_import_uuid`、`content_hash_k2_business_aggregate`、`ordered_block_list_sha256` 三者 A == B，确为在两个独立数据集上分别计算后比对。

**hash 口径分栏（回答「排除的到底是什么」）**

| 口径 | 构成 | 含导入随机 UUID | 含文件 sha256 |
|---|---|---|---|
| `content_hash_excluding_import_uuid`（QA 独立内容 hash） | `page｜page_inner_seq｜provider_block_id｜sequence_index｜text_sha256｜table_hash` | 否 | **否** |
| 业务 K1/K2（`stable_key`、`content_hash_k2_business_aggregate`、`ordered_block_list_sha256`） | `file_key(=TaskFile.sha256)｜page_key｜page_ordinal｜canonical_text` | 否 | **是**（稳定内容标识，非随机 UUID） |
| `window_text_sha256_run_bound`（请求 hash） | `_window_text`（含 `block_id=<UUID>`） | **是** | 否 |

共用 `OCR_JSON_SHA256` 是「同一份文件内容」的稳定标识（K1 的 `file_key`），**不是导入时生成的随机 UUID**；两份隔离数据导入同一份 OCR JSON 本就该共用它，这正是 PM 认可的前提。`content_hash_excluding_import_uuid` 本身连文件 sha256 都不含，只由页序 + 原文构成。三者分栏记录、不混用（架构师口径）。

**已固化为自动检查**：`validate_fixtures.py::_check_two_import_independence` 每次自检校验 6 项（`distinct_task_ids` / `distinct_file_ids` / `request_hash_differs_between_imports` / `content_hash_equal_across_imports` / `k2_aggregate_equal_across_imports` / `ordered_list_equal_across_imports`），结果写入 `two_import_independence_check`。本次自检 `status=checked`、0 错误；**负向验证**伪造「B 复用 A 的 task/file id 与请求 hash」时准确抓到 3 项失败，证明检查不是摆设。

**结论**：第一步①「与导入 UUID 无关」的断言**确实验到了**，24/24 不是自比对造成的假通过。

---

## 9.17 最终镜像（第二次重建）回归与落地清单精确化

> 触发：工程师执行 `docker compose build api worker && docker compose up -d api worker`（api+worker 均 Recreate/Up，8080=200），新镜像比上一版多了架构师定稿的一处修正；他自测六组全 pass（stable 8/8、pipeline 18/18、llm_client 12/12、http 15/15、baseline 11/11、K9 6/6）。**`up -d` 会重建容器并清空 `/tmp`** —— 已重新 `docker cp` 两份 OCR JSON 到 `/tmp/qa_compare_ocr_slice.json` 与 `/tmp/qa_fault_ocr_slice.json`；模拟服务是宿主机独立进程，从未在容器 `/tmp` staged 配置。

### 9.17.1 工程师三点答复 → 资产改判

1. **`_complete_run` 已修复**（我原先标「待实测确认」，现改判）：`processing_pipeline.py:121 compute_coverage_summary(...)` 按检查项聚合 —— `check:{id}` RunStep 全部 `SUCCEEDED` 且无 `Result.not_found_reason == "coverage_incomplete"` → `coverage_complete=True`；`_complete_run` 删掉无条件 `True`，改赋 `summary.coverage_complete`。工程师实测 coverage 用例（窗口1有摘录、窗口2超时）→ `false`，no_match 用例 → `true`。**兼容分支**：历史 5 条真实 run 都没有任何 `check:` RunStep → 按持久化 `run.coverage_complete` 回退，避免误拦 REVIEWING 任务 `607e6d41…`。
2. **C 的注入方式（写进配置与断言清单）**：`llm_client.py:117 _IN_FLIGHT = BoundedSemaphore(settings.LLM_MAX_IN_FLIGHT)` 在模块 import 时固化。改 `.env` 的 `LLM_MAX_IN_FLIGHT=N`（代码不变、**不需 build**）后必须 ``docker compose up -d --force-recreate api worker`` 才会重读 `env_file`；`docker compose restart worker` 沿用旧 env **无效**，进程内改 `settings` **无效**。**U1 跑完必须把 `.env` 改回 2 并再 recreate 一次**。工程师实测现状 `C=2 X=1 VER=pipeline-v2 ALIAS=2 TIMEOUT=180`。
3. **已落地 / 未落地清单**已写入 `fixed_responses.json::contract_facts.t02_landed_vs_pending`，并据此重建 `assertion_index_pending_implementation`（去重为 15 条）：
   - **T01/T02 已落地**：`SearchOutcome` 类与 `search_check_item_outcome()`（但 `_search_stage` 仍调兼容 wrapper 的 2-tuple，结构化 outcome **T03 接口预留**）、`RequestTrace` 数据类 + `complete_json`/`_chat` **内存**字段 + `to_dict()`、`run.model_snapshot.run_config`、`coverage_complete` / `coverage_affected_check_ids` / 409 `COVERAGE_INCOMPLETE` / `run_mode`、K1/K2/K3 / `w{idx}` / `source_ordering.order_blocks` / `prompt_registry`、`compute_coverage_summary` / `_touch_step(input_hash_extra)` / `_write_run_config`、基线失败三态、`CHECKS_PER_REQUEST` 与 `LLM_MAX_IN_FLIGHT` 配置项 + 模块级信号量。
   - **T03/T04 未落地（不得写成已实现）**：`RunStep.step_key = u:w{wi}:b{bi}`（本批**没有任何 `u:` 键**）、`/data/perf_traces/{run_id}.jsonl`（**本批完全没写**，`RequestTrace` 只在内存、未写 `provider_request_id=trace_id`）、`timing.progress`、七类批次短码落 `last_error_code`（本批短码位只有 `LLM_FATAL` 与 `SEARCH_FAILED:...`）、X 批量分组 / 并发调度 / `merge_outcomes` / 前端、`CheckExecution.coverage` JSONB。
   - 关键更正：`CHECKS_PER_REQUEST` **仅配置项**落地，X 批量分组与并发调度未落地；`ThreadPoolExecutor 一次提交全部单元 / 先回先处理 / 即时补位` 的调度器未落地（本批只有模块级 `BoundedSemaphore` 限流）。
4. **`PARTIAL_COVERAGE` 不是短码**：工程师据此移除 `_search_stage` 写 `last_error_code="PARTIAL_COVERAGE"`，`compute_coverage_summary` 改为只依赖 `RunStep.state + Result.not_found_reason`；`LLM_FATAL` 仍写短码位；401 致命分支后 `stage:vision` RunStep 根本不创建。他的三条断言（`partial_coverage_not_a_shortcode` / `llm_fatal_keeps_shortcode` / `fatal401_no_vision_step`）已在最终镜像实跑通过。
5. `order_blocks(rows, page_by_id, file_key_by_id)` 签名**确认为稳定公开 API**，配套 `load_file_keys(session, file_ids)` / `load_page_map(session, task_id, file_ids)` 亦稳定；返回 `list[OrderedBlock]`。我旧镜像 `ImportError` 回退 QA 独立排序的设计保留。
6. **超时注入**：推荐 `inject=429` → `RateLimitError` → `LLMTransientError` 重试耗尽（`LLM_MAX_TRANSIENT_RETRIES=2` 即 3 次尝试后未覆盖）复现同一覆盖口径；本批故障注入都在 `complete_json`/`_chat` 层直接抛业务异常、绕过 HTTP。若必须测真实 `APITimeoutError`，需 recreate 容器把 `LLM_REQUEST_TIMEOUT_SECONDS` 调到 < `timeout_hang_seconds`(3s)。
7. 工程师末尾的 **fixture 造数提醒与上一条消息交叉**：该问题已在 §9.14.1 修复（两份隔离文件共用 `OCR_JSON_SHA256`），最终镜像重跑仍 24/24。

### 9.17.2 最终镜像全量重跑（真实实测，覆盖上一版证据）

| 项 | 结果 |
|---|---|
| `compare_two_imports.py` | **24 PASS / 0 FAIL**，A/B K2 聚合相等、176/176 覆盖、`protected_unchanged=true` |
| `fault_injection.py --run-cases` | **`known_gaps_observed=0`**、`t03_pending=1`；3 个 case 的 `check` step `last_error_code` **均无 `PARTIAL_COVERAGE`**（与工程师答复一致）；`auth_401` 无 `stage:vision` 记录 |
| `format_error` / `timeout` | `run READY` / `coverage_complete=false` / `coverage_incomplete` / 保留 1 条命中 |
| `coverage_incomplete.verify.mjs` | **17 PASS / 0 FAIL / 4 PENDING**，`not_executed_cases=[]`、`case_version_diffs_vs_prior=[]` |
| `selftest_mock_server.py` | **8/8**，`peak_inflight=12`，首末到达差 **1.741 ms** |
| `fault_injection.py --check-baseline-only` | **`verdict=fixed`** |
| `validate_fixtures.py` | **PASS**（13 JSON / 23 响应模板 / 12 错误码断言字段 / 两次导入独立性 `checked` / 0 错误；新增 T03 占位场景后，见 §9.18） |

### 9.17.3 边界与仍待 #7

本轮实跑：造数 5 个隔离任务全部软删、`protected_unchanged=true`、2 条真实业务任务未触碰；未调用真实模型 / 外部 OCR；未改业务代码、未改 `REVIEW_HANDOFF.md`、未 commit / 未 git add、` .DS_Store` 原样。**#7 的真实服务定向接口回归仍等团长下发**，本轮未跑。T03/T04 落地后才可跑 U1–U5 中依赖 `perf_traces` JSONL / `u:` step_key / 七类短码的断言。

---

## 9.18 架构师裁决 A：X=1 空 `check_results` 的 T03 占位断言

> 裁决：**T02 不补该校验、不再重建镜像**，用工程师刚通知的最终镜像重跑全套即可，不会有第二次暂停。资产里只加**一条占位断言 + notes**，不动现有场景预期。

**新增占位场景**：`backend/tests/perf/fixtures/fixed_responses.json::scenarios[-1]` → `x1_empty_check_results_t03_placeholder`（`X=1`）。
- 复用 `effective_after` 标注机制（与 `fault_injection.py` 的 `evidence_preservation_effective_after` 同族）：`effective_after: "T03"`、`status: "待实测 / 后续批次"`、`synthetic_placeholder: true`。**当前只登记预期，不判 PASS/FAIL**。
- 两个固定响应变体：`t03.x1.empty_check_results` → `check_results: []`；`t03.x1.invalid_id_only` → 只含一个不属于本检查项的非法 ID。
- `expected_after_T03`：该 (窗口, 检查项) **未覆盖** → `BATCH_MISSING_CHECK`（非法 ID 变体再加 `INVALID_CHECK_ID`）→ `coverage_incomplete`、`run_coverage_complete=false`、`complete_task` 409 `COVERAGE_INCOMPLETE`。
- `current_t02_behavior`：`no_matching_evidence` + 完成放行（200）—— **已知缺口，不是回归失败，#7 不得判 FAIL**。

**关键语义区分（写进 `semantic_notes` 与 `contract_facts.check_results_coverage_discriminator`）**
- `check_results=[]` = 模型**没回答**该检查项 / 违反「每个请求中的检查项必须有且仅有一个响应」契约 → **未覆盖**；
- `check_results=[{outcome:"not_found"}]` = 模型**明确回答**本窗口无候选 → **覆盖达成** → `no_matching_evidence`（S9 不变）；
- `outcome=found` 但 `block_id` 幻引 = 有响应、只是引用不可验证 → **覆盖达成**（S5 不变）；
- `X=1` 视为**批大小 1 的特例**，契约不按 X 分支；与 `BATCH_TIMEOUT` 粒度无关、`INVALID_CHECK_ID` 两变体同源（S10 / S10b）。
- **现有 S5 / S9 / S10 / S10b / S7 / S8 预期均未改动**，只新增这一条占位。

同步落地：`contract_facts.check_results_coverage_discriminator`（三条判别式 + X=1 说明 + T02 已知缺口）、`t02_landed_vs_pending.not_landed_T03_T04` 追加该判定、`assertion_index_pending_implementation` 追加「T03 占位，当前不判 PASS/FAIL」。

**顺带闭环架构师上一条「纯字面量 vs 带括注」提醒**：该问题**已在 §9.12 处理完毕** —— 5 处 fixture 断言 + `fault_injection.py` 统一为纯字面量、说明移到独立 `*_note` 字段，`validate_fixtures.py` 新增字面量自检（含负向验证）；本次新增占位场景的 `complete_task_expected_code` 也是纯字面量 `COVERAGE_INCOMPLETE`，已被自检覆盖。**#7 断言入口已统一**，无需再处理。

**自检（纯本机，真实）**：`validate_fixtures.py` PASS（13 JSON / **23 个响应模板** / **12 个错误码断言字段** / 两次导入独立性 `checked` / 0 错误）；14 个 JSON 合法、5 个 Python AST、`node --check` 通过。§9.x 里更早的「21 模板 / 11 字段」均为当时快照，最新数字以本节为准。

边界不变：未改业务代码、未改 `REVIEW_HANDOFF.md`、未提交；**未再重建镜像、未再暂停容器**（按裁决 A 用最终镜像）。#7 真实服务定向接口回归仍等团长下发，本轮未跑。

---

## 9.19 工程师终版交叉验证与 docstring-only 镜像同步

> 本轮**未改业务代码、未重跑**（工程师明确说明 15:56 的证据在第三次镜像后仍有效）；只做文档对齐。

### 9.19.1 K2 内容 hash 的独立交叉验证（最强复验）

工程师自测的 `content_hash_list_sha256` 与 QA `compare_two_imports.py` 的 `content_hash_k2_business_aggregate` **完全一致：`606a4e17…93c1`**。两套**独立脚本、两个独立造数**，共用同一个 `source_ordering.order_blocks` 实现，逐块内容 hash 拼接后得到同一摘要 —— 这是 K2「内容 hash 与导入 UUID 无关」目前最强的独立复验。另两套一致：w0 = 133 块 / 7998 字、w1 = 51 块 / 2095 字、176/176 全覆盖。`c6e9613f…`（QA `_export_ordered_blocks` 的 JSON sha）与 `b7617b12…`（工程师 `ordered` 列表 JSON sha）属口径差异，不冲突。

### 9.19.2 `PARTIAL_COVERAGE` 措辞澄清（避免交付误读）

工程师查 DB 给出证据：`run_steps.last_error_code='PARTIAL_COVERAGE'` 共 **24 行**，全部是**旧镜像残留**（earliest `15:33:05` / latest `15:53:06`），归属 「T02-ENG-管线-{coverage,format,timeout}」第一版自测、「QA-PERF-故障注入-{format_error,timeout}」15:44–15:45 旧镜像两次跑、以及工程师造数 fixture 手工插的 step；**15:56 之后（最终镜像）新建的 `check:` 步 `last_error_code` 全部为空**。

- **QA 文档已正确**：§3 ④ 表格（两条）写明 `last_error_code=None（最终镜像已移除 PARTIAL_COVERAGE 短码）`；§9.14.3 写明「最终镜像已移除、`last_error_code` 现为 `None`，上一版镜像曾出现属历史实测」；§9.17.2 写明「3 个 case 的 `check` step 均无 `PARTIAL_COVERAGE`」。`fixed_responses.json::contract_facts.partial_coverage_not_a_shortcode_final_mirror` 与 `fault_injection_rules.json::t02_final_mirror_notes` 也一致。
- **需澄清的是消息措辞**：我早前一条给工程师的消息里把 `check step last_error_code=PARTIAL_COVERAGE` 列为「T02 后实测现状」，用的是**上一版镜像 15:44–15:45 的数字**；最终镜像重跑后的消息与 README 均已更正。不是与架构师定稿冲突，也不是新镜像回归。
- 另给 §4「管线现状」小节加了**修订前 HEAD 历史标注**（三条缺口均已在 T01/T02 修复，不是当前现状），避免交付时被断章取义。
- **#7 定向回归按「不为短码」断言**：`PARTIAL_COVERAGE` 是检查项级 `failed_reason`，不得出现在 `RunStep.last_error_code` / `expected_last_error_codes`；本批短码位只有 `LLM_FATAL` 与 `SEARCH_FAILED:...`。

### 9.19.3 第三次镜像同步（仅 docstring，证据仍有效）

工程师发现 `processing_pipeline.py:129` docstring 残留「事实源：`RunStep` 的 `check:{id}` 状态 / `last_error_code` 与 `Result.not_found_reason`」的过时表述，改为「`RunStep` 状态 + `Result.not_found_reason`，二者都不含 `PARTIAL_COVERAGE` 短码」，随后 `docker compose build api worker && up -d api worker`（api+worker Recreate、8080=200）。
- **零可执行代码变化**：与第二次镜像逐字相同，仅注释/文档字符串差异 → **QA 15:56 的全部证据仍然有效，不需要因这次重建重跑**。本轮遵守不重跑。
- 行号因 docstring 多 1 行整体 +1：`raise RuntimeError("LLM_FATAL…")` 由 `:506` 变 **`:507`**；交付文档若引用旧行号以 `:507` 为准。
- 工程师在该终版镜像上六组自测全 pass（stable 8/8、pipeline 18/18、llm_client 12/12、http 15/15、baseline 11/11、K9 6/6），两容器 `compileall` + import-all 通过。
- 容器 `/tmp` 第三次被清空：工程师已重新 cp 自己的 OCR JSON / baseline 副本；**QA 若再用容器 `/tmp` 的 staged 文件须重新 cp**（模拟服务仍是宿主机独立进程，不受影响）。
- `compare_two_imports.json` 已覆盖为新版、`window-N` 残留消失一事工程师已知悉，历史实测数值未被他改动。

### 9.19.4 边界

本轮只改 README（§4 标注 + 本节），未改任何 fixture / 脚本 / 业务代码，未重跑容器侧脚本，未提交。`evidence/` 中 15:56 的 T02 终版实测仍是当前有效结论：`compare 24/24`、`fault gaps=0 / t03_pending=1`、Chrome `17/0/4`、模拟服务 `8/8`、基线静态 `fixed`。#7 真实服务定向接口回归仍等团长下发。

---

## 9.20 裁决 A 精确口径收口（交付版镜像 + 「不得宣称 100% 闭环」）

> 工程师转达 Bob 裁决 **A**：T02 不补 `check_results` 存在性校验、**不再重建镜像**；**当前第 3 次 docstring 同步版就是交付版**，15:56 起的全绿证据全部有效，**不用再重跑**。§9.18 是初版占位，本节为精确口径收口版。本轮不重跑容器侧脚本。

### 9.20.1 占位断言 `x1_empty_check_results_t03_placeholder` 收口

- **T02 现状（已知、允许，#7 不得判 FAIL）**：`search_check_item_outcome` 只做 `TextSearchOutput.model_validate` 通过即 `covered_windows += 1` → 判覆盖达成 → `no_matching_evidence` → `run.coverage_complete=true` → **完成接口放行（200）**。
- **T03 期望**：`validate_batch_response` / `merge_outcomes` 按批校验「本批每个检查项恰好一项」→ 缺失记 `BATCH_MISSING_CHECK`（**X=1 也用这个短码，批 = 单检查项，契约不按 X 分支**；非法 ID 顶替再加 `INVALID_CHECK_ID`）→ 未覆盖 → `coverage_incomplete` + 409 `COVERAGE_INCOMPLETE`。
- 仍标 `effective_after: "T03"`、`status: 待实测 / 后续批次`、`synthetic_placeholder: true`，当前只登记预期、不判 PASS/FAIL。两个固定响应变体（`check_results=[]` / 仅含非法 ID）不变。
- **语义别混（写进 `semantic_notes`）**：`check_results=[]` = 模型**没回答** / 契约违反 → 未覆盖（T03）；`check_results=[{outcome:"not_found"}]` = 模型**明确回答**本窗口无候选 → 覆盖达成 → `no_matching_evidence`，**T02 就已正确处理，不是缺口，不要一起标成缺口**（S9 不变）；`outcome=found` + 幻引 = 有响应、引用不可验证 → 覆盖达成（S5 不变）。X=1 是批大小 1 特例，与 `BATCH_TIMEOUT` 粒度无关、`INVALID_CHECK_ID` 两变体同源。S5 / S9 / S10 / S10b / S7 / S8 预期仍未改动。

### 9.20.2 ⚠️ 交付口径：不得宣称覆盖不全已 100% 闭环

**这是本批必须如实保留的已知缺口**：X=1 且 `check_results=[]` 时，T02 仍会给出 `no_matching_evidence` 并放行完成。与 S5 的 `known_limitation`（「有响应但引用不可验证」）同类但**更严重 —— 连响应都没有**。已写进占位场景 `delivery_caveat`、`contract_facts.check_results_coverage_discriminator.delivery_caveat` 与 `assertion_index_pending_implementation`。

`docs/REVIEW_HANDOFF.md` 按边界本批不动；**T05 由工程师落笔时会把这条缺口与 T03-F1~F4 一并列进去**，QA 不新增/修改交接文档。

### 9.20.3 T03 mandatory followups（对照工程师 `/tmp/t02_evidence/INDEX.json`）

已写入 `contract_facts.t03_mandatory_followups`，供解锁 U 系列断言时对照：

| 编号 | 内容 |
|---|---|
| T03-F1 | `check_results` 存在性校验 / 按批校验「本批每个检查项恰好一项」→ `BATCH_MISSING_CHECK`（对应本占位场景） |
| T03-F2 | api `complete_task`（`runs.py:502`）当前**实时反推覆盖并与持久化字段 AND**，属实现偏离；T03 收敛成单条 `if not run.coverage_complete: 409 COVERAGE_INCOMPLETE`（唯一事实源 = `ProcessingRun.coverage_complete`） |
| T03-F3 | `compute_coverage_summary` 的 legacy 回退分支，引入 `u:*` step_key 后需复核命名耦合 |
| T03-F4 | `list_results` 的展示调用，引入 `u:*` step_key 后需复核命名耦合 |

F2/F3/F4 是**收敛项、不是当前缺陷**。`assertion_index_pending_implementation` 现为 19 条（新增交付口径 + F2 + F3/F4 三条）。

### 9.20.4 自检与边界

纯本机 `validate_fixtures.py` 实跑 PASS（13 JSON / 23 个响应模板 / 12 个错误码断言字段 / 两次导入独立性 `checked` / 0 错误）。本轮只改 `fixed_responses.json` 与 README，**未改业务代码、未重跑容器侧脚本、未提交**；`evidence/` 中 T02 终版结论仍是当前有效结果（`compare 24/24`、`fault gaps=0 / t03_pending=1`、Chrome `17/0/4`、模拟服务 `8/8`、基线静态 `fixed`）。#7 真实服务定向接口回归仍等团长下发。

---

## 10. 本轮三组快速验收（用户收窄范围 · 静态准备）

> 触发：团长收窄本轮范围，新 QA（`qa-perf`）接手失效的 `software-qa-engineer` 会话。
> 本节**全部为宿主机静态准备**：配置 / 固定响应 / 断言脚本 / README / 纯本机自检。
> **未跑容器、未跑真实模型、未跑 OCR 跑批、未跑 Chrome 真实页面**。实跑统一等团长下发「镜像已重建、可以实跑」信号。
> 边界：只改 `backend/tests/perf/` 与 `frontend/tests/perf/`；未改业务代码 / 配置 / 迁移 / 前端源码 / `docs/REVIEW_HANDOFF.md` / `docs/perf_2026-11-13/`；未 `git commit`、未 `git add -A`；工作树原有 ` M .DS_Store` 原样保留；未触碰 2 条真实业务任务。与开发 Agent（`dev-backend`）并行期间的写冲突：本阶段不跑任何容器侧脚本（`docker exec` / `docker cp` / `compare_two_imports.py` / `fault_injection.py --run-cases` / Chrome 真实页面 / 模拟服务浏览器链）。

### 10.1 范围（用户收窄口径）

| 本轮做（三组最小集） | 待测（后续，本轮不设计用例、不跑、不写数字） |
|---|---|
| A｜并发和结果归属（4 请求 / C=2 / 打乱返回顺序） | 性能矩阵、长章程、全文模式、配置面板、真实模型耗时 |
| B｜批量、稳定分窗和去重（同一 15 页 OCR JSON，X=1 vs X=3） | 真实模型短抽测（团长统一安排）、HTTP 层故障注入复验 |
| C｜部分失败与完成（一窗口成功一窗口超时 → 409 + 零写入；正常样本 200） | T03「先回先存」window0 证据保留、基线脚本实跑退出码 |
| 模拟 HTTP / 固定响应，**不跑真实模型、不等 OCR 跑批** | 七类批内异常逐场景、两份 run 同时执行 U5 |

### 10.2 新增与改动资产（本轮差额，均在两个 `tests/perf/` 目录内）

| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/tests/perf/mock_config.a_c2_refill_4.json` | 新增配置 | A 组：4 请求、barrier 显式 `[2,1]` 打乱放行、一快一慢（20ms / 400ms）、`expected_request_count=4`、`_trace_fields_note` 标 `t_submit` 无法取得、C 生效前置条件 |
| `backend/tests/perf/fixtures/quick_acceptance.json` | 新增 fixture | B 组三类去重/引用情形的 X=1（3 请求）与 X=3（1 请求）等价响应对 + `expected`；C 组复用既有 S8/S9 的引用与断言清单；A 组断言声明；`evidence_provenance` 沿用/未跑/待实跑标注；末尾 `rules` 带 4 条 `response_ref` 供实跑合并进模拟服务配置 |
| `backend/tests/perf/verify_quick_acceptance.py` | 新增断言脚本 | 统一离线断言器（纯标准库）：消费实跑落盘证据，A/B/C 三段逐条断言；无输入逐组标「未跑」、④ 标「无法取得」及原因、分窗标「沿用」；`--self-test` 合成自测（非实测、不写正式证据） |
| `backend/tests/perf/evidence/quick_acceptance.json` | 新增证据 | 静态准备状态证据：`mode=static_preparation`，三组均未跑 |
| `backend/tests/perf/evidence/quick_acceptance_validate_fixtures.json` | 新增证据 | 本轮 fixture 自检独立输出（**未覆盖** T02 封版的 `evidence/validate_fixtures.json`） |
| `frontend/tests/perf/coverage_incomplete.verify.mjs` | 改动脚本 | C 组：C9c 的 csrf token 改为显式 GET `/auth/me` 从响应体取（不硬编码，保留 env / fixture 回退）；零写入 predicate 的任务 ID 过滤保留并强化注释（避 5s 轮询串扰）；新增 `QA_REAL_UI=1` 把 C13/C14（及按钮禁用分支）接成对真实前端 DOM 的可实跑断言，`CASE_CONTENT_VERSIONS` 同步更新（C9c→v3、C13/C14→v2）。**默认关闭，静态准备阶段不跑，T02 封版 `17/0/4` 证据原样保留** |
| `backend/tests/perf/README.md` | 改动文档 | 本节（§10） |

> 既有 T01/T02 资产一律**复用不重做、不重跑、不改写其证据**：`fixed_responses.json` 的 `equivalence_pair` / `scenarios[7]` S8 / `scenarios[8]` S9 / `dedup_expectations` D1–D3 / `contract_facts`、`compare_two_imports.py` 24/24、`fault_injection.py`、Chrome `C7b/C9c-0/C9c/C9b/C17/C11/C12`、模拟服务自测 8/8、基线静态 `fixed`。

### 10.3 三组验收：怎么跑 / 断言入口 / 预期值 / 数字来源

> 三条命令均为**「镜像重建 + 团长实跑信号」之后**才执行；本轮静态准备阶段一条都不跑。
> 断言统一入口 `backend/tests/perf/verify_quick_acceptance.py`，证据统一落 `backend/tests/perf/evidence/quick_acceptance.json`（实跑时覆盖静态准备版）。

#### A｜并发和结果归属

```bash
# 前置（见 §10.4）：确认 .env LLM_MAX_IN_FLIGHT=2 已 force-recreate 生效
python3 backend/tests/perf/mock_llm_server.py \
  --config backend/tests/perf/mock_config.a_c2_refill_4.json \
  --port 18099 --stats-out /tmp/qa_mock_a_c2_refill_4.json
# 由真实调度器跑 4 个单元（X=1 / C=2），导出落库结果 RESULT_SPEC 与可选 trace JSONL
python3 backend/tests/perf/verify_quick_acceptance.py --group A \
  --stats /tmp/qa_mock_a_c2_refill_4.json \
  --results /tmp/qa_a_results.json --trace /tmp/qa_a_trace.jsonl \
  --out backend/tests/perf/evidence/quick_acceptance.json
```

| 断言 | 入口字段 | 预期值 | 数字来源 |
|---|---|---|---|
| A1 快请求结束后下一条立即发出（慢请求仍在途） | `stats.requests[].arrived_at` / `responded_at` / `matched_rule` | 存在补发请求 `fast.responded_at ≤ arrived_at < slow.responded_at` | **未跑**；实跑取落盘真实时间戳，不写推算值 |
| A2 峰值在途 = 2 | `stats.peak_inflight` | `2`（C=2 口径定值，`measured:false`） | **未跑**；实跑取落盘 |
| A3 每条响应写入正确的 run_id / 窗口 / 检查项，无串写 | `stats.requests[].tag/check_item_id/window_index` + 落库 `rows` | tag 集合 ≤1、无跨 run、无「不属于任何实际单元」的 row | **未跑**；实跑取落盘导出 |
| A4 提交到线程池时间 vs 实际 HTTP 发起时间 | `/data/perf_traces/{run_id}.jsonl` 的 `t_submit` / `t_http_start` | `t_http_start - t_submit = 额度等待` | **无法取得**（模拟服务只给 `arrived_at`≈`t_http_start`，不提供 `t_submit`）；无 trace 时如实标注原因，不伪造 |

#### B｜批量、稳定分窗和去重

```bash
# 同一 15 页 OCR JSON（SHA256 8879c8a2…60b）+ 同一组固定返回，分别以 X=1 / X=3 跑两次
python3 backend/tests/perf/verify_quick_acceptance.py --group B \
  --x1-stats /tmp/qa_b_x1_stats.json --x3-stats /tmp/qa_b_x3_stats.json \
  --x1-results /tmp/qa_b_x1_results.json --x3-results /tmp/qa_b_x3_results.json \
  [--windowing-recheck /tmp/qa_windowing_recheck.json] \
  --out backend/tests/perf/evidence/quick_acceptance.json
```

| 断言 | 入口字段 | 预期值 | 数字来源 |
|---|---|---|---|
| B0 稳定分窗 | `evidence/compare_two_imports.json` | 24/24 | **沿用 T02**（两次导入窗口一致、内容 hash 与导入 UUID 无关，`window_text_sha256_run_bound` A≠B 已排除自比对）。仅当开发 Agent 本轮改动分窗排序才传 `--windowing-recheck` 补一次快速核对 |
| B1 X=1 / X=3 实际请求数 | `x1-stats.request_count` / `x3-stats.request_count` | X=3 < X=1（fixture 口径 3→1 标 `measured:false`） | **未跑**；实跑取落盘统计，不引用示例数字 |
| B2 保存摘录与出处等价 | 两份 `results.rows` 按 `text_sha256 + source_page_number + 页内稳定序号` 归一化 | 集合相等 | **未跑**；不用 `Result.fingerprint` / 请求 hash |
| B3 三类去重/引用 | 两份 `results.rows` 逐检查项计数 | 重复引用（同项/同出处/同原文不同偏移）→1 条；不同出处同文→2 条；同块多检查项→各项均保留（总 4 条） | **未跑**（预期值读 `quick_acceptance.json::expected_kept_rows`） |
| B4 两次 `run_config` 除 X 外全等 | `run.model_snapshot.run_config` | 除 X 全等、X 值 1≠3 | **未跑** |

#### C｜部分失败与完成

```bash
# 固定响应复用 fixed_responses.json::scenarios[7] S8（窗口0命中、窗口1超时耗尽）与 scenarios[8] S9（正常未找到）
# 完成接口响应 + 落库状态导出为 COMPLETE_SPEC（含 task_id_filtered 零写入判定）
python3 backend/tests/perf/verify_quick_acceptance.py --group C \
  --complete /tmp/qa_c_complete.json --results /tmp/qa_c_results.json \
  --out backend/tests/perf/evidence/quick_acceptance.json
# Chrome 一条部分失败任务（实跑信号后开启 QA_REAL_UI）：
QA_REAL_UI=1 node frontend/tests/perf/coverage_incomplete.verify.mjs
```

| 断言 | 入口字段 | 预期值 | 数字来源 |
|---|---|---|---|
| C1 成功摘录保留 / `coverage_incomplete` / `run.coverage_complete=false` | COMPLETE_SPEC.partial_failure | 摘录≥1、`not_found_reason=coverage_incomplete`、`coverage_complete=false` | **未跑** |
| C2 完成接口 409 + 零写入 | `status` / `detail.code` / `zero_write` / `task_id_filtered` | 409 + `COVERAGE_INCOMPLETE`（`==` 严格相等纯字面量）+ 零写入（predicate 加目标任务 ID 过滤，避 5s 轮询串扰） | **未跑** |
| C3 正常样本完成成功 | COMPLETE_SPEC.normal_complete | 200 + `coverage_complete=true` + `no_matching_evidence` | **未跑** |
| C4 Chrome 一条部分失败任务 | `QA_REAL_UI=1` 下 C13/C14 真实 DOM 断言 | 覆盖提示、已有摘录可确认（接受/拒绝/出处点击仍可用，不整体只读）、完成按钮 disabled +「暂不能完成核对」说明、刷新后提示仍在 | **未跑**（真实页面操作）；`C7b/C9c-0/C9c/C17/C11/C12` **沿用 T02 已 PASS**，`C15/C16` 本轮不需要、保持 PENDING |

> 两档错误码分别验：`auth_401`（run FAILED）走 `409 RUN_NOT_READY`，不合并进 `COVERAGE_INCOMPLETE`；`PARTIAL_COVERAGE` 是检查项级 `failed_reason`，不是 `RunStep.last_error_code` 短码；`check_results=[]`（未回答/契约违反 → 未覆盖）≠ `[{outcome:"not_found"}]`（明确回答无候选 → 覆盖达成），X=1 视为批大小 1 特例。

### 10.4 A 组 C 生效复跑前置条件（必读）

`LLM_MAX_IN_FLIGHT` 在 `llm_client.py` 模块 import 时固化（`_IN_FLIGHT` 已构造）：

1. 改 `credit-review-app/.env` 的 `LLM_MAX_IN_FLIGHT=2`（代码不变、**不需 build**）；
2. 必须 `docker compose up -d --force-recreate api worker` 让容器重新创建才会重读 `env_file`；
3. **`docker compose restart worker` 沿用旧 env 无效**；进程内改 `settings` 无效；
4. 本组跑完若改过 `.env`，必须改回 2 并再 recreate 一次，否则后续用例一直用非 2 的值。

B 组 `X=1` / `X=3` 同理：`CHECKS_PER_REQUEST` 亦在配置读取时固化，两次运行须分别确认 `run.model_snapshot.run_config.X` 为 1 与 3（B4 断言）。

### 10.5 数字来源标注纪律

| 标注 | 含义 | 本节出现处 |
|---|---|---|
| **沿用** | 来自 T02 封版证据，本轮不重跑、不当作新跑结果 | B0 分窗 24/24、Chrome `17/0/4`、模拟服务自测 8/8、基线静态 `fixed`、`fault gaps=0/t03_pending=1` |
| **未跑** | 本轮静态准备阶段未实跑，不写任何数字 | A1–A3、B1–B4、C1–C4 全部业务链路断言 |
| **无法取得** | 调用端/模拟服务端取不到的字段，写明原因、不伪造 | A4 的 `t_submit` / `t_http_start`（模拟服务只给 `arrived_at`，精确值须由客户端 `perf_traces` JSONL 提供） |
| **实测** | 实跑信号后由落盘证据给出 | 本轮**没有任何业务链路实测数字** |
| 纯本机自检数字 | 语法/结构/断言逻辑合成自测，不是业务验收结果 | 见 §10.7 |

**§10.7 的数字全部是纯本机自检（语法、JSON、fixture 结构、断言脚本合成自测），不是三组验收的实跑结果**；三组验收的实跑数字一律等 §10.6 的前置满足后再产生。`fixture` 里所有 `measured:false` /「未跑」示例口径不得当实测引用。

### 10.6 「实现完成后才可实跑」用例清单及依赖

| 用例 | 依赖 | 谁负责 / 何时 |
|---|---|---|
| A1–A3（并发补位、峰值=2、无串写） | 开发 Agent 的 `_search_stage` 线程池并发（一次提交全部单元、C 可配、`as_completed` 先回先收、短事务落库）落地 + **api/worker 镜像重建** + **X=1/C=2 生效（§10.4 force-recreate）** | 团长下发实跑信号后 |
| A4（提交 vs HTTP 发起时间） | 上述 + `/data/perf_traces/{run_id}.jsonl` 落盘（开发 Agent 本轮实现，只存 hash/时间戳/状态/短码）；缺 trace 即维持「无法取得」 | 同上 |
| B1–B4（X=1 vs X=3 请求数、摘录/出处、去重） | `checks_per_request` 批量分组 + 批内响应校验落地 + **镜像重建** + **X=1/X=3 分别生效** | 团长下发实跑信号后 |
| B0 条件补跑（分窗） | **仅当**开发 Agent 本轮改动了分窗排序（`source_ordering` / chunk 逻辑）才跑 `compare_two_imports.py`，否则沿用 T02 24/24 | 需开发 Agent 回传是否改动 |
| C1–C3（部分失败 / 409 / 200） | `complete_task` 收敛为单条 `if not run.coverage_complete`、`compute_coverage_summary`、T03-F1 修正落地 + **镜像重建** | 团长下发实跑信号后 |
| C4（Chrome 一条部分失败任务） | 前端 `review.tsx` 持久覆盖提示条 + 完成按钮 disabled 实现 + **前端 `docker cp` 同步** + `QA_REAL_UI=1` | 团长下发实跑信号后 |
| C15/C16（真实服务定向回归、正常完成/历史只读） | 本轮范围外，保持 PENDING | 后续 |

**容器重建期间一律不跑**：`docker exec` / `docker cp` / `compare_two_imports.py` / `fault_injection.py --run-cases` / Chrome 真实页面 / 模拟服务浏览器链。本阶段只做宿主机静态准备。

### 10.7 本轮纯本机自检（真实实跑数字，2026-11-13）

| 命令 | 真实结果 |
|---|---|
| `validate_fixtures.py --out evidence/quick_acceptance_validate_fixtures.json` | **PASS**：16 个 JSON、23 个响应模板、19 个 `source_ref`、5 个 `response_ref`、13 个错误码断言字段、两次导入独立性 `checked`、**0 错误**（独立输出，未覆盖 T02 封版 `evidence/validate_fixtures.json`） |
| `node --check frontend/tests/perf/coverage_incomplete.verify.mjs` | **OK** |
| Python AST `ast.parse`（`backend/tests/perf/*.py`） | **6 个 .py 全部通过** |
| Python 字节码 `compile()`（等价 `py_compile` 编译阶段，不生成 `__pycache__`） | **6 个 .py 全部通过** |
| 全量 JSON 合法性（backend + frontend 两个 `tests/perf/` 下所有 `*.json`） | **18 个文件全部合法**（backend 16 + frontend 2） |
| `verify_quick_acceptance.py --self-test` | **FAIL=0**（合成自测、非实测、不写正式证据）：A 4 PASS / B 4 PASS + 1 沿用 / C 3 PASS + 1 未跑；新 fixture **4 个响应模板占位符渲染 0 问题**（全部可渲染、`block_id` 合法） |
| `verify_quick_acceptance.py`（默认模式，无任何实跑输入） | 产出 `evidence/quick_acceptance.json`：`mode=static_preparation`、`any_measured=false`、**PASS=0 / FAIL=0 / 未跑=11 / 无法取得=1 / 沿用=1**（如实反映三组均未实跑，不写推算值） |

### 10.8 需复制到 `docs/perf_2026-11-13/` 的文件清单（QA 不碰该目录，由开发 Agent 复制）

**本轮已产出、可直接复制**
- `backend/tests/perf/evidence/quick_acceptance.json`（三组验收静态准备证据；实跑后覆盖为实测版再复制更新）
- `backend/tests/perf/evidence/quick_acceptance_validate_fixtures.json`（本轮 fixture 自检）

**实跑信号后才会产出（暂不复制）**
- `backend/tests/perf/evidence/quick_acceptance_a_stats.json`（由 `/tmp/qa_mock_a_c2_refill_4.json` 归档）
- `backend/tests/perf/evidence/quick_acceptance_b_x1_stats.json` / `quick_acceptance_b_x3_stats.json`
- `backend/tests/perf/evidence/quick_acceptance_b_x1_results.json` / `quick_acceptance_b_x3_results.json`
- `backend/tests/perf/evidence/quick_acceptance_c_complete.json`
- `frontend/tests/perf/evidence/coverage_incomplete.skeleton.json`（`QA_REAL_UI=1` 实跑后覆盖；T02 封版 `17/0/4` 版本请先留档）

**资产文件（建议一并归档，便于复跑）**
- `backend/tests/perf/fixtures/quick_acceptance.json`
- `backend/tests/perf/mock_config.a_c2_refill_4.json`
- `backend/tests/perf/verify_quick_acceptance.py`
- `frontend/tests/perf/coverage_incomplete.verify.mjs`
- 本节 `backend/tests/perf/README.md`（§10）

### 10.9 需要开发 Agent 配合的接口 / 字段（QA 写断言的依赖）

1. **A3 归属核对**：并发调度发请求时带可识别 run 标识（`X-QA-Tag`），或由 `/data/perf_traces/{run_id}.jsonl` 提供逐请求 `run / 窗口 / 批次 / 检查项` 归属；模拟服务已记录 `stats.requests[].matched_rule / tag / check_item_id / window_index`。
2. **A4 时间字段**：`perf_traces/{run_id}.jsonl` 需含 `t_submit`（提交到线程池）、`t_http_start`、`t_http_end`（脚本已兼容 `submit_at` / `http_start` 别名）；字段名若不同请回传，我适配。缺 trace 时维持「无法取得」。
3. **B 组导出**：两次运行的 `run.model_snapshot.run_config`（除 X 外全等）可读取；落库 `Result` / `ResultSource` 导出需含 `check_item_id / text_sha256 / source_page_number / page_inner_seq / run_id / window_index`；实际请求数由 mock stats 或 trace JSONL 给出。
4. **C 组**：`complete_task` 409 `COVERAGE_INCOMPLETE` + 零写入；`run.coverage_complete` / `coverage_affected_check_ids` 可读；前端 `review.tsx` 持久覆盖提示条与完成按钮 disabled 的**实际文案/DOM**——用户口径「暂不能完成核对」，fixture 默认「暂不能完成」，脚本 `QA_REAL_UI` 已用正则 `/暂不能完成/` 兜底，确认前端字面量后可收紧为精确断言。
5. **分窗**：若本轮改动了 `source_ordering` / chunk 排序，请告知，以便补一次快速两次导入核对（`--windowing-recheck`）；否则沿用 T02 24/24。

