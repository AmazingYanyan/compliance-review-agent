# QA 独立实跑最终证据（本目录 = 验收结论来源）

**本目录是 QA（qa-perf）独立实跑三组验收 + Chrome 真实页面的最终落盘证据，2026-11-13。**
所有数字来自真实实跑（容器内 HTTP 模拟服务 + 宿主机真实 8080 + `QA_REAL_UI=1` 真实前端），
零真实模型、零外部 OCR。

> **最终镜像全量重跑（2026-11-12 18:18 UTC）**：因 dev-backend 在首次实跑信号后二次重建镜像并 `docker cp` 替换前端产物，
> QA 按团长要求用**最终镜像 / 最终前端产物**全量重跑三组 + Chrome，结论与首次一致：**12 PASS / 0 FAIL / 1 沿用**、
> Chrome **11 PASS / 0 FAIL / 2 PENDING**。**本目录的 `quick_acceptance.json` 与各 `*_results/stats` 均为最终重跑版**；
> 首次结论另存 `quick_acceptance.first_pass.json` 与 `chrome/coverage_incomplete.skeleton.first_pass.json` 留档，未采信旧数字。
> 镜像/产物 provenance 见 `quick_acceptance_run/image_provenance.json`：api `StartedAt=2026-11-12T17:43:53.941Z`、
> worker `17:43:54.010Z`（后端镜像两次实跑期间未再变），前端首页唯一产物 **`index-CiFoDBwL.js`**（旧 `index-MxNLwRYA.js` 已不在首页），
> 差异只在前端产物替换。最终重跑据此把断言收紧为：A3 双验（`X-QA-Tag` 旁证 + JSONL 主口径）、A4 逐条额度等待、
> B2 归一化键不含 `window_index`、B4 静态字段归一化、C13/C14 `data-testid` + exact 文本。

## ⚠️ 与开发侧样例的区分（不要把样例当验收结果）

| 目录 | 性质 | 用途 |
|---|---|---|
| **`qa_measured/`（本目录）** | **QA 独立实测**，最终验收结论 | 汇编交付、外部复核前内部结论的依据 |
| `../qa_acceptance/` | **开发侧（dev-backend）自测的格式样例** | 仅供对照 `RESULT_SPEC` / `STATS_SPEC` / `COMPLETE_SPEC` 字段格式；其 B 组是「15 页 OCR + 3 检查项」，与 QA fixture 的「4 候选」口径不同，**不是验收结果** |
| `../qa_assets/` | QA 静态准备资产副本 + T02 skeleton 17/0/4 留档 | 便于复跑、保留历史数字 |

两套证据**并列**存在，不得混成一套数字：
- 开发侧自测：`t03_pipeline_evidence.json` 28/28 + `t03_http_evidence.json` 12/12 + `t03_list_results_evidence.json` 6/6 = **46/46**。
- QA 独立实跑：`quick_acceptance.json` **12 PASS / 0 FAIL / 0 未跑 / 0 无法取得 / 1 沿用** + Chrome **11 PASS / 0 FAIL / 2 PENDING**。

## 结论数字（实测）

- **A（最终重跑实测）**：4 请求 / C=2；fast **26.443ms**、slow **401.522ms**；补发 seq3 `18:18:06.846033`、seq4 `06.954618` 均落在 fast 响应后、slow 响应前（慢请求仍在途）；`first_last_arrival_gap_ms=139.1`；`peak_inflight=2`；barrier `release_order_actual=[2,1]` 生效；JSONL 4 行单一 run_id、`(window_id,batch_index)` 4 组、落库摘录 4 条无串写；`t_submit/t_http_start/t_http_end` 齐全，逐条额度等待 `t_http_start - t_submit` = **[0.137, 31.786, 139.532, 0.208] ms** 全部 ≥0；模拟服务 `stats.by_tag` 单值（= run_id）作旁证。
  - 首次实跑（留档）：fast 31.7ms / slow 402.5ms、`first_last_arrival_gap_ms=147.045`、补发 seq3 `00.111278` / seq4 `00.221765`。两套数字均为实测，按不同镜像/产物轮次分别引用，**不混算**。
- **B**：实发 **X=1 6 / X=3 2**（2 窗口 × 3 检查项，按比例断言，未硬编码 3/1）；结果集合按 `text_sha256 + source_page_number + 稳定 rank` 相等；三类去重 X=1 与 X=3 各 **9 条 text 行、每检查项 3 条**；两次 `run_config` 差异仅 `batch` / `checks_per_request` / `units_total` 三个 X 派生字段，其余全等；**B0 沿用 T02 24/24**（本轮未改分窗排序）。
- **C**：保留 **1 条**成功摘录 + `coverage_incomplete` + `run.coverage_complete=false` + 短码 `BATCH_TIMEOUT`；完成接口 **409 `COVERAGE_INCOMPLETE` 严格相等 + 零写入** + `task_id_filtered=true`；正常样本 **200 `COMPLETED`**；`list_results` 实测 `coverage_complete=false` / `coverage_affected_check_ids=["charter.business_scope"]` / `editable=true`。
- **Chrome**（`QA_REAL_UI=1`，透明代理转真实 8080）：`data-testid=coverage-banner` 命中 1 处、完整串「识别覆盖不完整，暂不能完成核对」、受影响检查项 chip 1 个；完成按钮 `disabled=true` + 说明命中；unselected 三按钮可用、点「接受」发出命中该 result_id 的 PATCH（覆盖不全 ≠ 整体只读）；刷新后提示仍在；C9c 绕过 UI 带 CSRF 直 POST `/complete` → 409 + 零写入。

## 与 dev-backend 自测的两处差异（均非源码缺陷，如实并列）

1. **C 组保留摘录条数**：开发侧自测 **2 条**、QA 独立实跑 **1 条**。原因：固定响应引用块数不同（QA 引用窗口首块 1 个，开发侧 `first_last` 引用 2 个）；「成功摘录保留」两侧都成立。
2. **`X-QA-Tag`**：**请求头 `X-QA-Tag` 与 JSONL 归属双口径均落地**（`llm_client.py:176` 二次重建后生效，QA 实测 `stats.by_tag` 有值 = run_id）。QA 主口径走 JSONL，tag 作旁证。早前「未落地」是二次重建**之前**的核实结论，已过时，不作准。
3. C17 首跑 FAIL（「拒绝按钮=0」）是 **QA 测试脚本顺序问题**（先点「接受」把 decision 切成 accepted、前端切为单个重置按钮），QA 已自修为「点击前取三按钮状态 + 点击后可重置」，重跑 11/0/2，**无需改业务代码**。

**智能路由判定：`NoOne`** —— 未发现业务源码缺陷，无需返工。

## 文件清单与来源（复制自 QA 原路径，QA 原文件未改）

| 归档路径 | 来源 | 内容 |
|---|---|---|
| `quick_acceptance.json` | `backend/tests/perf/evidence/quick_acceptance.json` | 统一断言证据 `mode=measured`，**最终镜像重跑版** 12/0/1 |
| `quick_acceptance.first_pass.json` | 同名 | **首次实跑** 12/0/1 留档（旧前端产物轮次） |
| `quick_acceptance_validate_fixtures.json` | 同名 | fixture 自检（最终末次 36 JSON / 23 模板 / 0 错误） |
| `quick_acceptance_run/`（**19 个**） | `backend/tests/perf/evidence/quick_acceptance_run/` | `a_*` / `b_dedup_*` / `b_x1_*` / `b_x3_*` / `c_*` / `protected_snapshot` / `runtime_configs` / `setup` 全部原始证据 + **`image_provenance.json`**（镜像 StartedAt / Image sha256 / 前端产物 / 两轮实跑时间戳） |
| `chrome/coverage_incomplete.skeleton.json` | `frontend/tests/perf/evidence/` 同名 | Chrome **最终镜像**实跑 11/0/2 |
| `chrome/coverage_incomplete.skeleton.first_pass.json` | 同名 | Chrome 首次实跑 11/0/2 留档 |
| `chrome/coverage_incomplete.skeleton.t02_baseline.json` | 同名 | T02 封版 **17/0/4** 留档（实跑覆盖前先存） |
| `chrome/quick_acceptance_chrome_evidence.json` | 同名 | Chrome 结论 11/0/2（`all_pass`） |
| `assets/run_quick_acceptance.py` | `backend/tests/perf/` | 容器内实跑驱动 |
| `assets/run_complete_http.py` | 同上 | 宿主机完成接口实跑 |
| `assets/verify_quick_acceptance.py` | 同上 | 统一离线断言器 |
| `assets/mock_config.a_c2_refill_4.json` | 同上 | A 组模拟服务配置（4 请求 / C=2 / 打乱放行 / 20ms 与 400ms） |
| `assets/fixtures/quick_acceptance.json` | `backend/tests/perf/fixtures/` | 三组固定响应 fixture |
| `assets/coverage_incomplete.verify.mjs` | `frontend/tests/perf/` | Chrome 用例（含 `QA_REAL_UI=1`） |
| `assets/README_qa_perf.md` | `backend/tests/perf/README.md` | QA README（**§10.11 最终结论**，§10.10 已标为首次实跑） |

## 复跑

见 `assets/README_qa_perf.md` **§10.11（最终结论）**（§10.10 为首次实跑）与本交接文档「可复跑命令」。
关键前置：`C/X` 改 `.env` 后须 `docker compose up -d --force-recreate api worker`
（`restart` 沿用旧 env 无效），跑完改回 `CHECKS_PER_REQUEST=1` / `LLM_MAX_IN_FLIGHT=2` 再 recreate 一次。

## 遗留待验（标「待测」，不写推算值）

性能矩阵、长章程、全文模式、配置面板、**真实模型耗时（待测）**；Chrome C15/C16；
跨 run 隔离 U5；T03-F1 三项（空 `check_results` / 非法 ID 顶替 / 明确 `not_found`）未纳入三组最小集
（开发侧自测已覆盖）。**不得宣称覆盖不全已 100% 闭环**（S5 幻引局限仍在）。
