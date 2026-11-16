# 核对工作台评审交接

更新日期 2026-11-12（短样本串行基线 + QA 第 1 轮复验后修订；后端删除只读校验；补充用例 3；**下一阶段性能试验已登记，未开工**）  

> ⚠️ **仓库状态（2026-11-12 19:08 核查）**：仓库根为外层 `/Users/eddie/Documents/WorkBuddy/合规审查智能体`（`credit-review-app/.git` 已移除），分支 `main`、HEAD `db8f46e`，remote `https://github.com/AmazingYanyan/compliance-review-agent.git`；下方 `feature/credit-review` 分支与 `6a5b752` 等旧 commit 链属历史记录，**在新仓库中不可回查**。当前分支／HEAD／工作树、前置验收证据与四项门槛状态见「下一阶段性能试验」章节。

**以下为上一仓库的历史记录（提交号在新仓库不可回查，保留供叙事参考）：**

分支 `feature/credit-review`。实际交付 commit：P0 `6a5b752`（feat）+ `e672eec`（docs）；P1 `2d41dd5`（feat）+ `74c163b`（docs）；性能方案 `783c371`（docs）；排序切换修复 `b90910b`；性能观测 Step1 `632f874`；任务操作列收尾与表格验收 `8c05fcc`（feat）+ `ccc2c91`（docs）；最后一轮定向收尾 `7f6b806`（feat）+ `29c18eb`（docs）；后端删除任务只读校验 `5167257`（fix + 测试证据）+ `e2cff93`（docs）；**补充用例 3 只更新证据与交接文档，为分支最新一条提交（无代码改动）**。历史独立复验依据三份交接及八张用户截图；表格验收 40 项见 `docs/screenshots/tasks_table_verify.json`、定向收尾 28 项见 `docs/screenshots/tasks_final_verify.json`；删除接口三个用例（含 `case3_results_consistency`）见 `docs/delete_readonly_verify.json`。

## 结论

第 4 轮主体功能可保留。**待办首尾环绕与表格完整交互已补验通过**（其中发现并修复了更新时间排序切换 bug）。**性能观测 Step 1（耗时记录）已完成**，章程提速仍需后续并发化。**任务操作列三槽位对齐已收尾并通过验收**（上一轮 40 项全通过）。**最后一轮定向收尾 3 个场景 28 项全通过**：补齐「从筛选结果直接上传」记录、封闭已完成行写操作并确认材料区只读、加深两处颜色后普通文字对比度全部 ≥ 4.5:1。**后端删除任务只读校验已补齐并实测通过**：`DELETE /tasks/{id}` 对已完成任务返回 409 `TASK_READ_ONLY` 且任务／材料／核对结果仍可读，待核对任务软删除仍可用。**补充用例 3**：带非空核对结果的已完成任务在 409 前后，`/results` 的 `run_id`、77 条结果条目、77 条人工决定与 statistics 完全一致（整份响应 SHA256 相同）。**短样本串行基线已本轮真实跑批完成**（`run_id=5547804d-da6d-4417-8139-9dc36e3b5e3e`，14 次真实模型请求、600.64s 后处理），证据 `docs/perf_baseline_2026-11-12.json`、脚本 `scripts/baseline_serial.py`；并发收益仍为推算、未经实测。详见「短样本串行基线（2026-11-12）」章节。QA 第 1 轮独立复验后已补充披露 run 绑定产物限制并修正 4 项标签/命令问题（未重跑基线、未改业务代码）。缺材料面板版式、长摘录键盘实测仍待收尾。

| 检查项 | 结论与证据 |
|---|---|
| 待办顺序与跨材料 | ✅ 已补验。17 次「下一条待处理」连续点击：营业期限 → 章程 6 项 → 财报 8 项（跳过已接受的「审计机构」）→「报告年度」→ 回到「营业期限」，**首尾环绕成立**；跨材料自动切换、保存后跳过均实测。单条/零条由 `jumpNext` 空队列提前返回 + `todo>0` 收起按钮保证。 |
| 统计、状态与计数 | 进行中截图的「未核对 14 + 待补原因 1 = 待处理 15」，「已核对 3/18」互补。拒绝待补原因未计入完成数。每条编辑态只有一个决定状态。缺材料及未找到证据的截图不再显示「1 条摘录」。 |
| 缺材料 | 单面板、补传、按需展开和缺失待办分组可见。折叠时面板仍被拉到接近整屏，展开后仍是多层整宽卡片，版式待收尾。逐项接受或拒绝、已完成回看按既有规则执行。 |
| 原文交互 | 用户标注确认点击长正文及箭头均可展开、收起，短摘录无箭头。键盘切换、复制时保持展开状态由实现说明支持，仍需实际操作记录。 |
| 我的任务 | ✅ 已补验并收尾。沿用 23 条固定测试数据（上一轮落为本地 fixture）验证：搜索（「测试」→ 7 条）、状态筛选（「已完成」→ 2 条）、搜索+状态组合（→ 1 条）、双向排序（desc↔asc，修复 `enableSortingRemoval:false`）、分页（23 条 → 20+3 两页）、筛选后单页收起分页、排序/翻页/筛选后任务 ID 命中均实测通过。**操作列三槽位对齐已修复**：真实服务上待核对与已完成两行的「继续核对／查看结果」x 坐标与宽度完全一致，已完成行上传槽位留空但占位。详见下节；上传覆盖范围已在最后一轮定向收尾中补齐（场景 1）。 |
| 原文定位与完成态 | 保留已交接的图片框选、PDF 跳页、已完成回查拒绝原因及写入拦截。PDF 区域框选、缩放后坐标一致性、PDF 连续翻页时右栏位置保持待复验。 |

## 性能观测（Step 1 已完成）

- `RunStep` 增加 `started_at/finished_at`（迁移 `b7e4c9d1a2f3`）；`ProcessingRun` 起止正确落库（修掉旧 `finished_at=None` 冗余）；管线在阶段级（`stage:classify/search/vision`）与检查项级（`check:{check_id}`）写 `RunStep`（`_touch_step` upsert）。
- 新增只读接口 `GET /tasks/{task_id}/runs/{run_id}/timing`，返回 run 起止耗时 + 各步骤耗时明细。
- **实测基线（营业执照单文件 run）**：总耗时约 70 秒；`stage:classify` 15s、`stage:search` 55s、`stage:vision` 0s；检查项中 `license.business_scope` 23s、`license.operating_term` 24s、`license.registration_status` 8s，章程/财报缺材料项均 0s 快速返回。已能定位最慢检查项。
- 章程旧跑批 54 分钟仍是历史参考（旧跑批缺阶段耗时），15 分钟记为并发化试验目标。
- 下方「短样本串行基线」章节的「下一轮待落实的设计」是本节 4 条历史方案的最新可执行细化；本轮已把「先能量出来」用真实跑批落地，并发化仍未实现。

## 短样本串行基线（2026-11-12）

**状态：已实测（本轮新增，未提交）。** 固定同一份 OCR JSON、清单、模型、提示词与窗口参数，真实调用 `qwen3.8-max-0902` 跑了一次完整串行链路。四态严格区分：**已实现**（串行链路、RunStep 起止、只读 timing 接口、窗口级容错分支）、**已实测**（本轮真实跑批的全部耗时/窗口数/调用次数/结果条目）、**待验证**（并发收益、限流与重试、只重试失败段、故障注入下的 `coverage_incomplete`）、**方案阶段**（下一轮 5 项设计，均未落地）。本轮未改业务代码、未改 `models.py`、未加迁移/接口、未重建 worker 镜像、未重新 OCR、未提交。

### 固定输入与指纹

| 固定项 | 值 | 说明 |
|---|---|---|
| OCR JSON | `/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json` | SHA256 `8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b`，143880 B，15 页 |
| 样本范围 | 原《北京银行股份有限公司章程》PDF 物理第 1–15 页，1:1 对应 | 原 PDF 共 62 页；物理页号 ≠ 页内印刷页码 |
| 清单 | `borrower-wcl-v1`，18 叶子（章程 6 项） | `checklist_hash() = 5f0c164276cf0fe8b68a758785cb984226dd4339e790e02e8b9773a036702337` |
| 模型 | `LLM_TEXT_MODEL = LLM_VISION_MODEL = qwen3.8-max-0902` | `APP_MODE=real` |
| 提示词 | `SEARCH_SYSTEM` sha256 `c93878b9…`、`CLASSIFY_SYSTEM` `20729704…`、`VISION_SYSTEM` `ceda71c3…` | 三个 JSON Schema 亦有 sha256，完整值见证据 `fingerprints.prompts` |
| 窗口 | 8000 字符 / 500 字符重叠 | `LLM_WINDOW_CHARACTERS=8000`、`LLM_WINDOW_OVERLAP_CHARACTERS=500`，运行时与常量一致 |
| 超时与重试 | 单次 180s、`LLM_MAX_TRANSIENT_RETRIES=2`、`LLM_MAX_CONCURRENCY=2`、`LLM_MAX_OUTPUT_TOKENS=4096`、`LLM_MAX_FORMAT_REPAIRS=1` | 并发上限本轮串行**未生效** |

导入落库后真实 OCR 文本为 **176 个块 / 9570 字符**（四次导入相同）。上述指纹后续并发对照**必须逐项一致，但只保证输入相同**：窗口边界、逐窗口字符数、窗口文本 hash、`messages_sha256` / `user_sha256` 与 `Result.fingerprint` 均绑定该次导入的 DB 行（含随机 `OcrBlock UUID`），仅凭 OCR JSON SHA256 复现不出，详见「样本局限」的 **run 绑定产物（QA 独立复验后补充披露）**。

### 执行与观测方式

在 `credit-review-app-worker-1` 容器内**同步直接调用 `run_pipeline.func(str(run_id))`**（Procrastinate Task 的原始函数），**不经过队列**：未 `defer`、未入队，队列轮询与调度开销**不计入**本基线；`Result` / `ResultSource` / `RunStep` / `ProcessingRun` 仍由业务代码正常真实落库。`docker exec` 传 stdin 必须带 `-i`。观测全部由脚本层 monkeypatch 完成（`LLMClient._chat`、`complete_json`、`chunk_source_blocks`、`chunk_blocks`、`search_check_item` 与四个阶段函数），不侵入业务代码；窗口数用真实 `chunk_blocks` / `chunk_source_blocks` 对真实 DB 块实测，跑批前 preflight 与跑批中观测**一致**。证据同时写容器内 `/tmp/baseline_evidence.json` 并输出到 stdout，两份 SHA256 均为 `64a9fe44842a11d4ff9c2d6d357187043b42ccc4cf6140d0bc9ed927c2a7ac47`（首次前台执行曾被宿主机侧 SIGTERM 打断导致 stdout 观测丢失，故加落盘兜底；那次 run `4333c31e-…` 完整 READY 但**不作基线数据**，详见证据 `session_notes`）。

### 基线表（全部实测）

| 指标 | 实测值 | 口径 |
|---|---|---|
| run_id | `5547804d-da6d-4417-8139-9dc36e3b5e3e` | DB `processing_runs` 真实存在，`READY / done / coverage_complete=true`，run 起止 600.636s |
| 隔离 task / file | `ddd97b17-8bfe-4954-b7fb-3f4f8386b879` / `9e4d3303-8501-46cc-bf47-a4357dcde09e` | 新建隔离数据，跑完 `deleted_at` 软删；未触碰 2 条真实业务任务 |
| **OCR 识别** | **未执行（复用既有 JSON，非本轮计时对象）** | 未调用外部 OCR 服务，不把复用 JSON 冒充 OCR 耗时 |
| OCR JSON 导入落库 | **0.107s** | `python -m app.cli import-ocr-json` 等价调用，单独计时 |
| 造隔离数据 / 建 run | 0.021s / 0.002s | 单独计时 |
| **后处理（OCR 之后）** | **600.64s** | `run_pipeline.func` 墙钟，含三阶段与 DB 写入 |
| 阶段 classify / search / vision | **44.612s / 555.990s / 0.006s** | `complete_run` 0.005s；DB `run_steps` 落库值 44.615 / 555.992 / 0.007s 与之吻合 |
| 总实测 | 600.78s | 造数据 + 导入 + 建 run + 后处理；不含证据读取与软删 |
| 窗口数（classify） | **2** | 7984 + 2158 字符（该次导入实测，见「样本局限」run 绑定产物披露） |
| 窗口数（6 个章程检查项） | **各 2**，共 12 次窗口调用 | 缺材料 12 项与 seal/signature 2 项实测窗口数 0、不调模型 |
| 模型调用 | **14 次 `_chat` / 14 次 `complete_json`** | 2 classify + 12 search；无 json_schema 降级、无 `_repair`、无视觉调用 |
| 单次请求耗时 | min 9.203 / max 140.537 / 均值 42.880 / 中位 35.951 / P95 68.777 / 求和 600.323s | 全部逐条记录，非仅平均值 |
| 超时 / 瞬时错误 / 窗口级重试 / 致命 / 格式错 / 格式修复 | **0 / 0 / 0 / 0 / 0 / 0** | 14 次全部 `ok=True`；attempt=0 由 `run_steps[].attempt`（19 条全 0）与三个空 detail 推得，非逐次调用直接观测 |
| 结果条目 | **44 行**（30 命中 + 14 not_found） | `no_matching_evidence` 2、`material_missing` 12、`coverage_incomplete` 0 |

**观测口径（QA 独立复验后补充披露）**：P95 采用脚本 `_dist` 的 `ordered[int(round((n-1)*0.95))]` 口径，n=14 → `ordered[12] = 68.777s`；常规线性插值 P95 = 93.893s、nearest-rank = 140.537s，均为不同口径的复算值（推算），外部复算须同口径。

**逐次真实 HTTP 请求（`_chat` 层，逐条记录）**

| # | 阶段 | 检查项 / 窗口 | 耗时(s) | response_format | 结果 |
|---|---|---|---|---|---|
| 1 | classify | 文件窗口 0 | 21.335 | json_schema | ok |
| 2 | classify | 文件窗口 1 | 23.263 | json_schema | ok |
| 3 | search | `charter.business_scope` 窗口 0 | 14.618 | json_schema | ok |
| 4 | search | `charter.business_scope` 窗口 1 | 34.033 | json_schema | ok |
| 5 | search | `charter.approval_body` 窗口 0 | 68.777 | json_schema | ok |
| 6 | search | `charter.approval_body` 窗口 1 | 55.654 | json_schema | ok |
| 7 | search | `charter.voting_ratio` 窗口 0 | 17.790 | json_schema | ok |
| 8 | search | `charter.voting_ratio` 窗口 1 | 26.838 | json_schema | ok |
| 9 | search | `charter.guarantee_restrictions` 窗口 0 | 52.334 | json_schema | ok |
| 10 | search | `charter.guarantee_restrictions` 窗口 1 | 37.869 | json_schema | ok |
| 11 | search | `charter.legal_representative_signature_authority` 窗口 0 | 49.038 | json_schema | ok |
| 12 | search | `charter.legal_representative_signature_authority` 窗口 1 | 9.203 | json_schema | ok |
| 13 | search | `charter.ownership_and_special_terms` 窗口 0 | **140.537** | json_schema | ok |
| 14 | search | `charter.ownership_and_special_terms` 窗口 1 | 49.034 | json_schema | ok |

每条结果的 `kind`、`text` 摘要（200 字）、`fingerprint`、`text_sha256`、`source_page_number` 与命中/未命中原因见证据 `results.by_check_item`；大段原文按指纹 + 短 hash 处理，未整份塞入证据。

### 关键条款命中对照

| 条款 | 物理页 | 目标检查项 | 结论 | 依据（实测） |
|---|---|---|---|---|
| 第十七条业务范围（含「外汇借款」「外汇担保」「提供信用证服务及担保」「贷款」） | 7 | `charter.business_scope` | **命中** | 1 条 text，出处页 7，text 含「第十七条」「外汇借款」 |
| 第二十四条 不以赠与/垫资/担保/补偿/贷款等形式资助购股人 | 8 | `charter.ownership_and_special_terms` | **未命中**（精确短语） | 样本 OCR 页 8 存在；该检查项页 8 有摘录，但 44 条结果无该精确短语，属摘录用词/截断差异，不是技术失败 |
| 第二十五条 增资须经股东大会分别决议 | 8 | `charter.approval_body` | **未命中** | 样本内存在，结果未含该短语 |
| 第四十一条 5% 以上股东质押书面报告 / 控股股东「借款担保」 | 13 | `charter.ownership_and_special_terms` | **未命中** | 样本内存在，结果未含该精确短语 |
| 第四十三条 对股东贷款条件不得优于其他借款人 | 13 | `charter.ownership_and_special_terms` | **命中** | 出处页 13 |
| 第四十四条 授信逾期限制表决权 | 13 | `charter.voting_ratio` | **未命中** | 样本内存在；该检查项整体 `no_matching_evidence`（覆盖完整后的真实「未找到」，非技术失败） |
| 股权出质事前告知 / 借款余额超股权净值不得质押 / 质押达 50% 限制表决权 | 14 | `charter.ownership_and_special_terms` | **部分命中** | 三短语中仅「50%」在结果中命中（页 14），另两个精确短语未出现，摘录不全 |
| 第四十六条 股东大会职权（十二）审议批准第四十七条担保事项、不得授权董事会 | 14–15（跨页） | `charter.approval_body` | **命中** | 3 条（页 14/15/15），页 15 含「审议批准第四十七条规定的担保事项」；`charter.guarantee_restrictions` 亦引用同短语，属证据重叠非误命中 |
| 第四十七条 五类须经股东大会审议的对外担保 | 15 | `charter.guarantee_restrictions` | **命中** | 7 条全部页 15，含「本行下列对外担保行为」「总资产30%」「资产负债率」「对股东」 |
| 法定代表人签字权限 | — | `charter.legal_representative_signature_authority` | **样本外条款，未命中** | 15 页 OCR 仅出现通用词「法定代表人」，无签字权限条款；返回 `no_matching_evidence`，未硬凑命中 |

**「外汇担保」误命中专项：未被误命中。** `charter.approval_body` 3 条（页 14/15/15）与 `charter.guarantee_restrictions` 7 条（全部页 15）均不含「外汇担保」「提供信用证服务及担保」「外汇借款」，且无第 7 页出处；经营范围里的「外汇担保」只出现在 `charter.business_scope` 第 7 页那 1 条里，属正确命中（证据 `clause_matrix.guarantee_vs_business_scope.any_foreign_exchange_guarantee_mis_hit = false`）。

**「未找到」与技术失败区分**：`no_matching_evidence` 2 条、`material_missing` 12 条、`coverage_incomplete` 0 条、`LLM_FATAL` 0 条；`fatal_error_count=0`、`format_error_count=0`、`window_level_retry_count=0`。本样本未触发技术失败分支，因此「严格区分」目前只验证了正常路径，**待故障注入/长样本验证**。系统只输出「证据 / 未找到」，不输出合规判断。

**C6 / C10 标签（QA 独立复验后修正）**：证据 `clause_matrix.matrix` 中 C6 改为「未命中：样本内存在但本次未被模型摘录召回（非技术失败）」、C10 改为「样本外条款：物理 1–15 页无「签字权限」条款，`no_matching_evidence` 符合预期（非技术失败）」；矩阵中不再出现「覆盖不全」字样，避免与 `coverage_incomplete`（本轮 0 条）混淆。C10 的 `present_in_sample_ocr=true` 仅由通用词「法定代表人」命中，已加 `present_in_sample_ocr_note`：本轮 psql 只读复验 176 块中该词 2 块（物理页 5 / 13），「签字」「签署」「签名」「签章」均 0 出现。

### 瓶颈判断（实测）与并发收益上限（推算，非实测）

**实测**：14 次请求耗时求和 600.323s ≈ 后处理 600.64s 的 **99.95%**，耗时几乎全部在模型 HTTP 等待；阶段占比 search **92.566%** / classify **7.427%** / vision **0.001%**。最慢检查项 `charter.ownership_and_special_terms` 189.584s（含单窗口 140.538s）、`charter.approval_body` 124.453s、`charter.guarantee_restrictions` 90.213s；缺材料 12 项与 seal/signature 项约 0.002s 且不产生模型调用。长尾来自单次请求的巨大方差（9.2s ~ 140.5s，P95 68.8s），不是 DB 写入或分窗开销。

**推算（基于串行实测，明确标注「推算，非实测」，待并发实测验证）**：假定并发度取 `LLM_MAX_CONCURRENCY=2`，忽略限流、排队、连接建立、DB 写入、调度开销及多 run 争用。

| 层次 | 串行实测基线 | 推算理想总耗时 | 口径 |
|---|---|---|---|
| 窗口级并发（检查项仍串行） | 555.732s | **371.561s** | 每个检查项耗时取该检查项两窗口最大值，再求和；最慢单检查项 140.538s |
| 检查项级并发（窗口仍串行） | 555.732s | **277.866s** | `max(总和/2, 最慢检查项 189.573s)` |
| 全局两层并发（C=2） | 600.332s（14 次 complete_json） | **300.166s** | `max(总和/2, 最慢单请求 140.538s)` |

以上三行**不是并发实测结果**。当前 `LLM_MAX_CONCURRENCY=2` 在串行链路中未生效（0 个同时在途请求）。

### 样本局限

**能验证**：串行链路完整（classify→search→vision→complete_run 全部真实执行且落库）；计时字段齐全（阶段墙钟、RunStep 起止、逐次请求耗时、OCR 导入与后处理严格分栏）；条款召回与出处页码可核对；超时/重试观测字段可采集（本轮实测为 0，说明链路未触发，不是没观测）；样本外条款走 `no_matching_evidence` 而非硬凑命中；经营范围「外汇担保」未被担保类检查项误引；窗口级容错分支代码可读。

**不能验证**：并发真实收益（本轮 0 个在途请求）；服务端 429 限流与排队；窗口级与检查项级两层上限的相互作用；多 run 并发的全局上限与会话隔离；62 页长章程下的断句、住所串入、去重与总耗时量级；失败窗口只重试的幂等与 `fingerprint` 合并去重。

**run 绑定产物（QA 独立复验后补充披露）**：QA 用 `--probe-only` 独立实跑 2 次，与早期 probe、本次基线共 4 次比对：`source_block_count=176 / source_total_characters=9570` 四次相同，但**窗口边界、逐窗口字符数、窗口文本 sha256 每次都不同**（win0/win1 字符数 7991/2086、7984/2158、7983/2137、7984/2092；hash `eb28ab09…`/`c5702341…`、`0ddb2baa…`/`7bc72b8a…`、`aec6322f…`/`6a6cc477…`、`00cedfdc…`/`5a10ed30…`）。根因是业务侧技术债（非本轮引入）：① `ocr_blocks.sequence_index` 只有 25 个不同值却存 176 块，`load_source_blocks` / `load_file_blocks` 只按 `sequence_index` 排序，同值行顺序由 DB 物理序决定 → 分窗边界漂移；② `_window_text()` 把每次导入新生成的随机 `block_id` 拼进窗口文本；③ `_fingerprint(check_item_id, block_id, start, end)` 同样含随机 `block_id`，基线 run 与中断 run 的同段文本 fingerprint 全部不同（QA SQL JOIN 8/8 为不同）。因此 **窗口文本 hash、逐窗口字符数、`messages_sha256` / `user_sha256`、`Result.fingerprint` 都是该次导入 DB 行的绑定值，仅本次 run 内自洽**；仅凭 OCR JSON SHA256 复现不出这些值。并发对照必须**复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID）**；跨 run 逐条比对改用 `text_sha256 + source_page_number`，**不要用 `fingerprint`**。本轮不修改业务代码，仅如实披露。

**并发收益还需要**：更长样本（完整 62 页章程或窗口数 ≥ 6）产生可并行单位；同时派发多检查项 + 多窗口，制造 ≥ 2 个在途请求；可调并发度 1/2/4/8 与多 run 并发对照，观测 429 / P95 延迟变化；固定项（同一 OCR JSON SHA256 + 同一清单/提示词 hash）**只保证输入相同**，还须复用同一批隔离数据后跑多次取分布；注入超时/格式错/致命错验证有限重试、停止派发、只重试失败段；串行与并发结果按 `(check_item_id, text_sha256, source_page_number)` 逐条比对。

### 完整复现命令

```bash
cd /Users/eddie/Documents/WorkBuddy/合规审查智能体/credit-review-app

OCR_JSON="/Users/eddie/Documents/WorkBuddy/合规审查智能体/《北京银行股份有限公司章程》 切分15页.PDF_by_PaddleOCR-VL-1.6_全参数开启.json"
shasum -a 256 "$OCR_JSON"
# 期望 8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b

docker cp "$OCR_JSON" credit-review-app-worker-1:/tmp/baseline_ocr_slice.json

# -i 必须；约 10 分钟，建议后台托管 docker exec，避免前台被 SIGTERM 打断 stdout
docker exec -i credit-review-app-worker-1 python - --evidence-out /tmp/baseline_evidence.json \
  < scripts/baseline_serial.py > /tmp/baseline_stdout.json

# stdout 管道若断开，用容器内落盘的同份证据兜底
docker cp credit-review-app-worker-1:/tmp/baseline_evidence.json /tmp/baseline_stdout.json

python3 -c "import json,pathlib; d=json.loads(pathlib.Path('/tmp/baseline_stdout.json').read_text()); pathlib.Path('/tmp/baseline_raw.json').write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')"
```

补充命令：`docker exec -i credit-review-app-worker-1 python - --probe-only < scripts/baseline_serial.py`（不调模型，只实测窗口数与指纹）；`docker exec credit-review-app-worker-1 python -m app.cli import-ocr-json --file-id <file_id> --json /tmp/baseline_ocr_slice.json`（仅导入，不触发外部 OCR）；只读 timing 接口 `GET /api/v1/tasks/{task_id}/runs/{run_id}/timing` 需先登录取 session cookie，且隔离任务已软删时需先把 `tasks.deleted_at` 置 NULL。证据 `fingerprints` 给出全部固定项 sha256，`reproduction` 给出同一套命令。**注意（QA 独立复验后补充披露）**：上面格式化命令只生成脚本原始输出到 `/tmp/baseline_raw.json`，**不可覆盖交付证据** `docs/perf_baseline_2026-11-12.json`；交付版另需按证据 `post_processing_notes.what_changed` 补回 5 个人工追加段（`session_notes` / `git_state` / `clause_verdicts_manual` / `post_processing_notes` / `database_verification`）、2 处标签修正与 QA 披露。证据 `reproduction.steps[6]` 的自检命令针对的是**交付版证据**。本次新跑批的自检请改读 `/tmp/baseline_raw.json`（由上面格式化命令产出），两者不可混用（QA 第 2 轮回归后订正）。固定项 sha256 逐项一致只保证输入相同；跨 run 复现窗口级指纹必须复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID），跨 run 结果比对用 `text_sha256 + source_page_number`，不要用 `fingerprint`。

### 未提交状态与改动清单

**本轮未提交**（用户未要求），当前 HEAD `9c1eda1fc65fb132fd6e2a608876340fb8fa8e06`、分支 `feature/credit-review`。不写「本次文档提交号」（自引用必然失效）。新增/修改文件：

| 文件 | 变更 |
|---|---|
| `scripts/baseline_serial.py` | 新增：可复现串行基线脚本（固定项指纹 + monkeypatch 观测 + 容器内证据落盘） |
| `docs/perf_baseline_2026-11-12.json` | 新增：结构化证据（实测字段 + 单独分栏的推算 + 条款矩阵 + 会话/git 记录） |
| `docs/REVIEW_HANDOFF.md` | 原地更新：新增本章节 |

工作树另有 5 张 `docs/screenshots/review_*.png` 的 `D` 删除标记（他人造成）：**未 `git add -A`、未恢复、未提交、未纳入本轮改动**。隔离任务共 5 条（本轮 probe、首次中断跑批、本次跑批 3 条 + QA 第 1 轮独立复验 `--probe-only` 2 条 `20714d03-…` / `a4bc1759-…`）均已 `deleted_at` 软删，run / results / run_steps 保留可追溯。

### 下一轮待落实的设计

以下 **5 项均为方案阶段 / 待验证，本轮未实现**，给出可执行要点：

1. **并发上限（方案阶段）**。`LLM_MAX_CONCURRENCY=2` 当前串行未生效。两层上限不要相乘：设一个**进程/集群级全局信号量总闸**（等于 `LLM_MAX_CONCURRENCY`），检查项级与窗口级只从总闸里申领配额，窗口级并发度 ≤ 该检查项剩余配额；按服务端实测的 429 与 P95 延迟做 1→2→4 阶梯调节，每档记录吞吐、错误率、P95，达限流即回退一档；多 run 并发时必须把上限做成跨 run 的全局（DB 租约 / 分布式信号量），并在 `model_snapshot` 里记录本次生效并发度。本轮推算表不能当作上限设定依据。
2. **前端真实进度（方案阶段）**。当前仅「识别中 / 已识别」二态。前置条件：窗口级 `RunStep` 先落库（本轮只在脚本层观测，未落库）。以 `run_steps` 中窗口级 `SUCCEEDED` 数 / 总窗口数生成进度快照与进度条（本次实测总窗口 = classify 2 + 6×2 = 14；缺材料与 seal/signature 项不计入分母），阶段名与百分比都要有实际来源；轮询 2–5s 自适应、无变化时退避，run 进入 `READY/FAILED` 立即停止；失败窗口单独标红并显示 `last_error_code`，不并入「已完成」。
3. **单段失败如何标识（方案阶段，待故障注入验证）**。窗口级写 `RunStep(step_key=check:{check_id}:window:{i}, input_hash=窗口文本 sha256)`，记录 `state / attempt / last_error_code`；`coverage_incomplete`（存在未覆盖窗口）与 `no_matching_evidence`（所有窗口 SUCCEEDED 且无证据）严格分开，`LLM_FATAL` / `PARTIAL_COVERAGE` / 重试耗尽属技术失败，**不得标成「未找到」**；`run.coverage_complete` 只有在全部窗口 SUCCEEDED 时才置 true。本轮 0 次失败分支，须注入超时/格式错/致命错验证三种状态与文案。
4. **超时与有限重试（方案阶段，待注入验证）**。单次请求沿用 `LLM_REQUEST_TIMEOUT_SECONDS=180`，窗口级 `LLM_MAX_TRANSIENT_RETRIES=2` 加指数退避（如 1s/2s + 抖动），仅对 `LLMTransientError` 重试；`LLMFatalError` 立即停止该检查项后续派发并取消/丢弃在途请求结果；`LLMFormatError` 记未覆盖而非无限修复（现有最多 1 次 `_repair`）；增加 run 级 deadline 与「取消在途」的显式处理，避免致命错误后仍有请求写入结果。本轮 14 次请求 0 超时 0 重试，观测字段已具备，行为需注入验证。
5. **怎样只重试失败段（方案阶段）**。以 `(run_id, step_key, input_hash)` 为幂等键（现有唯一约束 `uq_run_steps_key_hash` 已支持），重跑时只挑 `state=FAILED` 或「无 SUCCEEDED RunStep 的窗口」，复用同一 OCR JSON（同一 SHA256）、同一清单 hash、同一提示词 sha256 与 8000/500 窗口参数，**且必须复用同一批隔离数据（同一 file_id / 同一批 OcrBlock UUID）**；结果按 `fingerprint`（`_fingerprint(check_item_id, block_id, start, end)`）合并去重——**该去重仅在「同一 run / 同一批 OcrBlock UUID 内」有效**（同 run 内去重成立，跨 run 因 `block_id` 随机而不可用），先按 `(run_id, check_item_id)` 清理旧行再插入或以 fingerprint upsert，避免整项重跑与重复写入；验收需比对重试前后结果集合与人工决定不漂移，并验证连续两次执行幂等。

**附：业务侧技术债（QA 独立复验后补充披露，方案阶段 / 待修）**：`ocr_blocks.sequence_index` 非唯一（176 块仅 25 个不同值）导致 `load_source_blocks` / `load_file_blocks` 排序不确定、分窗边界逐次漂移；`_window_text()` 与 `_fingerprint()` 把随机 `block_id` 写入窗口文本与结果指纹，导致 `window_text_sha256` / `messages_sha256` / `user_sha256` / `Result.fingerprint` 跨 run 不可比。下一轮需：给排序加稳定次级键（如 `provider_block_id` / 页序 / 主键）、把 `block_id` 从指纹与窗口文本中剥离或改用「页 + 块序号」稳定标识，并把 `input_hash` 幂等键建立在稳定标识上。本轮不修改业务代码。

## 本轮收尾

### 任务操作列（本轮已收尾）

**状态：已完成并通过验收。** 以当前代码和运行页面为准，上一轮已实现的排序、筛选、分页、只读限制等直接验收；仅修复操作列对齐与按钮样式差距。

**改动文件**（实际提交 `8c05fcc`）：

| 文件 | 变更 |
|---|---|
| `frontend/src/routes/_layout/tasks/index.tsx` | 操作列改为固定三槽位；「继续核对／查看结果」合并到同一槽位并统一浅青样式；「上传材料」改中性描边纯文字；「更多」补 `aria-label`；移除未用的 `Upload` 图标 import。 |
| `frontend/src/routeTree.gen.ts` | 构建时由 TanStack Router 插件自动重新生成，清掉上一轮已删除的 `$taskId.materials` 路由残留引用（HEAD 原文件指向不存在的文件）。 |
| `frontend/tests/fixtures/tasks-23.json` | 新增 23 条固定测试数据：以真实服务上 1 条待核对 + 1 条已完成任务为模板，补 21 条确定性记录。 |
| `frontend/tests/tasks-table.verify.mjs` | 新增独立验收脚本（Playwright + 系统 Chrome）：场景 A 走真实服务两行，场景 B 拦截 `/api/v1/` 用本地 fixture。 |
| `docs/screenshots/tasks_actions_two_states.png` | 待核对与已完成同屏截图。 |
| `docs/screenshots/tasks_table_verify.json` | 40 项验收结果与拦截请求明细。 |

**实现**：操作列从左到右固定「上传材料 / 进入或查看 / 更多」三槽位（前两槽各 88px、更多 32px），空槽位只占布局空间、不渲染内容，因此已完成行的「查看结果」与待核对行的「继续核对」横向对齐。待核对行未展开即可上传（上传成功后才展开材料列表）；已完成任务经「查看结果」进入同一 review 页，由 `editable = results.editable === true && task.state !== "COMPLETED"` 保证只读。复用现有 `Button`：页级「新建核对任务」保留加号与实心底色，行内「继续核对／查看结果」同为 `size="sm"` + ghost 基底叠加浅青底，「上传材料」用中性 `outline` 描边；三个行内文字动作均为纯文字，「更多」保留省略号图标并带 `aria-label="更多操作"`。**颜色与已完成行的写操作入口已在最后一轮定向收尾中调整**（见下节），布局与样式层级保持不变。

**验收**（`node frontend/tests/tasks-table.verify.mjs`，需前端已构建并同步到 api 容器）：**40 项 PASS / 0 FAIL / 0 PENDING**。

- 场景 A（真实服务、2 条真实任务）：三槽位存在性与空槽占位、两行入口 x 坐标与宽度一致（`x=1276.0/1276.0, w=80.0/80.0`）、两个入口计算样式一致（浅青底 + 青绿字、32×80）、上传为中性描边、行内纯文字与更多省略号、页级新建加号与实心青绿、更多可访问名称、未展开即可触发文件选择器、进入只读页（`editable(api)=false`，无「完成核对」及接受／拒绝按钮）、继续核对命中对应任务 ID（此处颜色为上一轮当时色值，最后一轮加深后见下节）。
- 场景 B（23 条 fixture，拦截 `/api/v1/`）：默认 20 行 / 2 页、默认降序、desc↔asc 双向且无第三态、搜索「测试」7 条、状态「已完成」2 条、组合 1 条、结果缩到一页时分页收起、清空筛选恢复 2 页、翻到第 2 页 3 行；在「排序后(asc)」「筛选后(已完成)」「翻页后(第 2 页)」三种状态下核对展开（GET files）与进入（Link href）命中的任务 ID 与所在行一致。**上传 POST 实际只有两笔**，分别来自「排序后(asc) 同视图待核对行 `…0005`」与「翻页后(第 2 页) 首行 `…0003`」，两笔均命中对应行 ID；「筛选后(已完成)」组**仅验证上传槽位留空**（该视图无待核对行），当时未覆盖「从筛选结果直接上传」。该覆盖缺口由最后一轮定向收尾的场景 1 补齐。

![待核对与已完成同屏（三槽位对齐，颜色加深后）](screenshots/tasks_actions_two_states.png)

**通过项**：要求 1（三槽位、对齐、空槽占位、未展开可上传、已完成只读入口）、要求 2（按钮组件复用与色彩／尺寸／纯文字／可访问名称）、要求 3（两状态同屏、21+ 条双向排序／搜索／状态组合筛选／翻页／单页收起分页／操作 ID 命中）全部实测通过；TypeScript 类型检查与 Vite 构建通过；前端产物已同步到运行中的 api 容器（8080）并验证新资源可达。

**待验项 / 范围外**：

- 真实文件上传后的 OCR／LLM 闭环不在本轮范围（会触发外部服务）。上传只验证到文件选择器与拦截到的 POST 请求任务 ID；**本轮未发生外部服务阻塞，无卡点需记录**。只读页使用已有识别结果（`已核对 77/77`），未重新跑批。
- 缺材料面板版式、长摘录键盘实测、PDF 区域框选等沿用上一轮待验项。
- 既有工程提示（非本轮引入，未改）：`biome.json` schema 2.6.3 与本机 CLI 2.6.7 不匹配；`tasks/index.tsx` 的 import 顺序不符合 `organizeImports`（HEAD 原版同样报错）。

**本轮复现**：先构建并同步前端 —— `cd frontend && VITE_API_URL= npx vite build --outDir /tmp/credit-review-fe --emptyOutDir`，再 `docker cp /tmp/credit-review-fe/. credit-review-app-api-1:/app/backend/app/frontend/`（`VITE_API_URL` 置空保证同域 API，构建产物不入库）；然后 `node frontend/tests/tasks-table.verify.mjs`（默认 `http://localhost:8080`，可用 `VERIFY_BASE_URL` 覆盖；浏览器用系统 Chrome，可用 `VERIFY_BROWSER_CHANNEL` 覆盖）。

### 最后一轮定向收尾（3 个场景，28 项全通过）

**状态：已完成并通过验收。** 独立复验确认操作列对齐通过后，只补跑三个相关场景：沿用上一轮 40 项结果与 23 条 fixture，不重跑全流程。本轮脚本 `frontend/tests/tasks-final.verify.mjs`，结果 `docs/screenshots/tasks_final_verify.json`（**28 项 PASS / 0 FAIL / 0 PENDING**），截图位置 `docs/screenshots/tasks_actions_two_states.png`（已覆盖更新，即上节所附图片）。

**改动文件**（实际提交 `7f6b806`）：

| 文件 | 变更 |
|---|---|
| `frontend/src/routes/_layout/tasks/index.tsx` | 已完成行「更多」菜单改为唯一禁用只读项；展开材料区按任务状态禁用分类下拉与删除文件按钮并标注只读、空态文案改只读；行内入口字色与页级新建底色加深为 `#0B4F52`；状态文字 600→700 档。 |
| `frontend/tests/tasks-final.verify.mjs` | 新增只跑三个定向场景的补充验收脚本。 |
| `docs/screenshots/tasks_final_verify.json` | 28 项结果 + 上传 ID 证据 + 菜单/材料区快照 + 逐项对比度明细。 |
| `docs/screenshots/tasks_actions_two_states.png` | 覆盖更新两状态同屏截图。 |

**场景 1 — 筛选结果直接上传（补齐记录）**：用现有 23 条 fixture，状态筛选「待核对」→ 6 条，取首行「资料核对 2026-11-11 09:53」，在**未展开**状态下直接经「上传材料」选入测试文件并拦截 POST。行任务 ID（取自该行「继续核对」href）= `607e6d41-4d47-4582-a5ad-07313b6c17bd`；请求路径 = `/api/v1/tasks/607e6d41-4d47-4582-a5ad-07313b6c17bd/files`；路径任务 ID = 同一值，**两者一致**；上传后筛选状态与 6 条结果保持不变。上一轮该覆盖缺口的表述已在上文同步修正。

**场景 2 — 已完成行「更多」菜单与材料区只读**：

- 修正前实测：菜单实际项 `['删除任务']`（写操作）；展开材料区有 2 份文件、2 个分类下拉 + 2 个删除文件按钮，均可点击，但后端 `files.py`（上传／删文件／分类）、`tasks.py`（PATCH）、`runs.py`（决策）对 `COMPLETED` 均返回 `409 TASK_READ_ONLY`。
- 按既有只读规则修正：已完成行菜单改为唯一禁用项 `['已完成任务不可修改']`，**槽位、省略号图标与 `aria-label` 均保留**（即「菜单无可用项，保留槽位」）；待核对行菜单仍为 `['删除任务']`，未误伤。材料区标注「· 只读」，2 个分类下拉与 2 个删除文件按钮全部 `disabled`，空态文案改为「暂无文件（任务已完成，只读）」，上传槽位仍留空。
- **后端纵深防御（当时缺口，现已补齐）**：`DELETE /tasks/{id}` 软删除当时对 `COMPLETED` 未做 409 拦截（其余写接口均已拦截），前端入口虽已封闭但直接调 API 仍可软删已完成任务。**该缺口已在本轮后端 BugFix 中补齐并实测通过，详见下节。**

**场景 3 — 颜色加深与对比度（浏览器计算色）**：

- 加深：行内「继续核对／查看结果」字色 `text-primary` → `#0B4F52`；页级「新建核对任务」底色 `bg-primary` → `#0B4F52`（hover `#093E40`）。与原 `--primary` 同色系、仅降明度；布局与「页级实心 > 行内浅青 > 上传中性描边」层级不变。为让同页普通文字整体达标，状态文字由 600 档升到 700 档（「颜色圆点 + 文字」表达方式不变）。
- 方法：浏览器 `getComputedStyle` 取计算色，用 canvas 把 `oklch / oklab`（含 alpha）光栅化为 sRGB，再按 WCAG 相对亮度公式计算，不靠肉眼估算。
- 实测（改前 → 改后）：页级新建 3.61 → **8.92:1**；继续核对 3.33 → **8.23:1**；查看结果 3.33 → **8.23:1**；上传材料 19.8:1。其余普通文字全部 ≥ 4.5:1：表头 4.54、任务名称 19.8、客户类型 19.8、识别进度 4.74、更新时间 4.74、状态·待核对 3.20 → **5.03**、状态·已完成 3.22 → **4.95**。逐项明细见 `tasks_final_verify.json` 的 `evidence.contrast_metrics`。

**通过项 / 待验项**：三个场景 28 项全通过；TypeScript 类型检查与 Vite 构建通过；新前端已同步到运行中的 api 容器（8080，`index-mbYLtTGm.js`）。当轮新增的「后端软删除 409 缺口」已由下一节所述后端 BugFix 补齐；本轮未触发 OCR／LLM，无外部服务阻塞。复现：`cd frontend && node tests/tasks-final.verify.mjs`（构建同步命令见上节）。

### 后端删除任务只读校验（BugFix，实测通过）

**状态：已完成并通过验收。** 前端已验收，测试范围限于 `DELETE /tasks/{id}` 删除接口。用隔离测试数据对**运行中的实际后端**（api 容器 8080，已重建镜像加载新代码）先跑两个用例（**40/40 断言 PASS**、14 次请求、脚本 EXIT=0，路由判定 NoOne），本轮再补一条「非空核对结果前后一致」回归（**27/27 断言 PASS**、7 次请求）；合计 **67/67 PASS、21 次请求**。结构化证据 `docs/delete_readonly_verify.json`（token／密码脱敏；补充回归在 `case3_results_consistency` 块，合计口径见 `combined_summary`，原 40 项记录保持不变）。

**改动文件**（实际提交 `5167257`）：

| 文件 | 变更 |
|---|---|
| `backend/app/api/routes/tasks.py` | `delete_task` 在写 `deleted_at` 前新增 `if task.state == "COMPLETED": raise HTTPException(409, {"code": "TASK_READ_ONLY", "message": "任务已完成，不可删除"})`；非完成态路径逐行不变。 |
| `docs/delete_readonly_verify.json` | 原两用例 40 项断言／14 次请求；本轮追加 `case3_results_consistency`（27 项断言、7 次请求、77 条结果条目与人工决定逐条指纹、前后响应 SHA256）与 `combined_summary`。 |

复用同文件 `update_task`（约 112 行）、`files.py` 149／205／224、`runs.py` 76／381 的既有 `TASK_READ_ONLY` 规则；权限仍由 `OwnedTask`（owner + `deleted_at IS NULL`）保证，`require_csrf` 在函数体之前执行；409 分支在写入前返回，零写入。容器内 `/app/backend/app/api/routes/tasks.py` 131 行已核验为新校验。

**用例 1 — 已完成任务（当前用户有权操作）：PASS**

| 项 | 结果 |
|---|---|
| 隔离数据 | `42b0b193-d367-4b23-b4e6-5e348e46531c`「QA 删除只读-已完成」，owner `fdb34c0f-…4999`，持久化与对外 state 均 `COMPLETED`，删除前 `deleted_at=NULL`；挂 1 条材料 `QA-C1-材料.pdf`（1024B）与 1 条 SUCCEEDED OCR job |
| `DELETE /api/v1/tasks/{id}` | **HTTP 409**，响应体 `{"detail": {"code": "TASK_READ_ONLY", "message": "任务已完成，不可删除"}}` |
| 数据可读 | `GET /tasks/{id}` **200**（`state=COMPLETED, file_count=1`）；`GET /tasks/{id}/files` **200**（1 条，含 `original_name/media_type/size_bytes/ocr_status`）；`GET /tasks/{id}/results` **200**（`editable=false, items=[]`，隔离数据未跑核对流程故为空，接口本身可读）；`GET /tasks` **200** 且仍包含该任务 |
| 零写入 | DELETE 后及三个 GET 之后两次查库，`deleted_at` 均为 `NULL`、`state` 仍 `COMPLETED` |

**用例 2 — 待核对任务（当前用户有权操作）：PASS**

| 项 | 结果 |
|---|---|
| 隔离数据 | `7d68995f-b94a-4914-ba2d-da68b0e6bdf8`「QA 删除只读-待核对」，持久化与**对外推导** state 均 `REVIEWING`（挂 1 条 SUCCEEDED OCR job 使 `_effective_state` 推导为 REVIEWING），删除前 `deleted_at=NULL` |
| `DELETE /api/v1/tasks/{id}` | **HTTP 204**，空响应体（现有软删除行为不变） |
| 软删除生效 | 查库 `deleted_at = 2026-11-12 03:12:18.965212+00`、`state` 仍 `REVIEWING`；`GET /tasks/{id}` **404** `{"detail": {"code": "RESOURCE_NOT_FOUND", "message": "任务不存在"}}`；`GET /tasks` **200** 且不再包含该任务 |

**测试与数据边界**：登录 `liyanyan` 取 session cookie + `X-CSRF-Token`，4 个写请求均带 `Origin: http://localhost:8080`，14 次请求无 403 CSRF_FAILED，409／204 均为真实业务响应。**未触发 OCR／LLM**（未调用 files／runs／complete 接口，SQL 造的两条 `ocr_jobs` 为 SUCCEEDED 终态；测试窗口实测新增 active OCR job = 0、processing run = 0）。隔离数据用 `POST /api/v1/tasks` 创建后改库造状态；测试后两条均软删（用例 1 因 COMPLETED 走 SQL 标 `deleted_at`），最终 `GET /tasks` 只剩 2 条真实任务，其 state 与 `deleted_at=NULL` 未变化；未触碰前人「测试任务 T01…」数据。语法检查 `python3 -m compileall` 通过；api 镜像经 `docker compose build api` + `up -d api` 重建重启，8080 健康 200，worker/db 未动、无需迁移。

**补充用例 3 — 带非空核对结果的已完成任务：DELETE 前后 `/results` 完全一致（本轮新增，PASS）**

只补这一条接口回归；前端与待核对任务软删除用例沿用既有结果，未重跑。用现成测试数据克隆，避免触发 OCR／LLM：以真实已完成任务 `ee59108d-e4f1-4aa8-bf2e-afe07d457384` 的最新 READY run `fad721d5-a179-40c3-9203-04822ce84350`（77 条 results、77 条 decisions）为源，SQL 克隆到新建隔离任务 `ee347bb8-ec27-49b6-ba05-7f517f48a129`「QA 删除只读-带非空结果」（`state=COMPLETED`，克隆 run `f65001b7-01c0-4902-836e-4409af5e148e`）。全程只调用 login、`POST /tasks`、GET、DELETE，未调用 files／runs／complete；测试窗口新增 OCR job = 0。

| 步骤 | 结果 |
|---|---|
| 删除前 `GET /results` | **200**，`run_id=f65001b7-01c0-4902-836e-4409af5e148e`、**77 条 items**、`editable=false`、`is_stale=false`；人工决定 **76 accepted / 1 rejected**，拒绝原因「材料识别有误，需人工复核」（`version=3`、`updated_at=2026-11-11T08:43:51.861034Z`）；`statistics.overall = {total:77, accepted:76, rejected:1}` |
| `DELETE /api/v1/tasks/{id}` | **HTTP 409**，`{"detail": {"code": "TASK_READ_ONLY", "message": "任务已完成，不可删除"}}` |
| 删除后重读 `GET /results` | **200**，`run_id` 不变、仍 77 条 items、`editable=false`、statistics 不变 |
| 一致性核对 | `run_id` 相等；**77 条结果条目 id 序列相等**；逐条关键字段（含 `decision`／`reject_reason`／`version`／`updated_at`）相等；statistics 相等；**整份响应 SHA256 前后均为 `d78af252c57715d76f3a55fcf421782b13b2867533a8925d15bc2492155d0d03`**（字节级一致） |
| 零写入 | DELETE 后查库 `deleted_at` 仍为 `NULL` |

证据存放：`docs/delete_readonly_verify.json` 的 `case3_results_consistency`（`before/after` 摘要 + 77 条 `item_fingerprints` + 27 项 `checks` + 7 次 `requests`），合计口径见 `combined_summary`（40+27 = **67 项全通过**、14+7 = 21 次请求）；原 40 项断言与 14 次请求记录保持不变。完整 `/results` 响应各含 77 条 items、原文较长，故以逐条指纹 + 整份响应 SHA256 作为可核验证据。测试后隔离任务用 SQL 标软删（COMPLETED 不能走 DELETE），克隆子行保留以便追溯；最终 `GET /tasks` 只剩 2 条真实任务，其 state 与 `deleted_at=NULL` 未变。

**通过项 / 待验项**：三个用例全部 PASS（合计 67 项断言），「后端软删除 409 缺口」已闭环，且非空核对结果在 409 前后字节级一致。仍待验：缺材料面板版式、长摘录键盘实测、PDF 区域框选等此前条目；`worker` 容器仍为旧镜像（本改动只在 api 路由，不在 worker 执行路径，无影响）。

### 缺材料和待办

- 收起时外框高度随摘要内容，边框在状态、数量和操作区之后结束。展开后用轻量列表显示受影响项，保留逐项接受／拒绝和历史决定。顶部统一解释「接受仅确认本次缺失记录」，每行保留检查项名称和必要操作。缺失材料仍可进入待办，跳转时展开并聚焦具体条目。
- 补一组短的首尾环绕测试，记录最后一条 → 第一条的真实条目 ID，另测单条、零条和保存后跳过。用一条待补原因验证跳转后可直接填写原因，保存后计数才更新，原文高亮对应当前定位条目。
- 长摘录补验 Enter / Space、拖选复制和点击「定位原文」。保留已通过的正文及箭头展开体验。

## 性能下一步

本节为历史方案清单；第 1 条「先能量出来」已由 2026-11-12 短样本串行基线落地实测（见上文章节），第 2–4 条仍未落地。**下一阶段（并发调度 + 批量搜索 + 阶梯/批量/全文对照）的详细任务规格、开工门槛与四项前置缺口，已登记在「下一阶段性能试验」章节；该章节登记时状态为「已登记、未开工」，现已由下文「T03 已开工：并发调度 + 批量搜索落地」章节接续（含本轮两套证据与 QA 独立实跑结论）。**

现有交接记录章程旧跑批 54 分钟，搜索路径约 6 个检查项 × 6 个窗口，约 36 次串行调用。这个数字可作历史参考，旧跑批缺阶段耗时。15 分钟记为试验目标。

1. **先能量出来。** 记录 run 与阶段起止、窗口排队与实际请求耗时、请求次数、超时和重试。阶段进度用已完成检查项或窗口数，阶段与百分比有实际来源。
2. **用同一输入做并发对照。** 固定 OCR JSON、清单、文本模型、提示词和窗口切法，测串行与有上限的并发。优先用单层任务队列调度检查项与窗口。核对上限覆盖实际进程部署和多 run 并发场景，按服务实际返回的限流及延迟逐步调节。独立数据库会话、稳定去重和排序、重复执行幂等都要用结果验证。模型请求设置明确的超时和重试边界，致命错误后停止派发并处理仍在途的请求。
3. **另测减少调用。** 试一个窗口同时查多个检查项，记录调用次数、耗时和关键条款召回。固定模型响应时，串行与并发结果按条目内容、来源和去重结果比对。真模型、批量提示或换模型时，用人工核对过的关键证据、来源正确性及差异清单验收。换模型、并发和批量策略分别记录收益。
4. **补一次实际长章程验收。** 回传基线、改动后耗时和关键条款差异。记录超时或限流下是重试、失败还是覆盖不全，覆盖不全与正常未找到明确区分。同时用新跑批核实断句、住所串入和去重。区域框选与财报印章／签名继续按各自用例验证。

## 下一阶段性能试验（T03 已开工：并发调度 + 批量搜索落地）

**状态：T01+T02 封版后接续，本轮（2026-11-13）已落地并发调度、批量搜索、T03-F1~F4 收敛与前端覆盖提示，并实跑三组验收。** 下方「开工前记录 / 前置验收证据盘点 / 四项前置门槛核查 / 待执行任务规格」均为 **2026-11-12 登记时的历史状态**，保留作对照，不代表当前现状；当前结论以本节「T03 落地记录」与 `docs/perf_2026-11-13/` 的机器可读证据为准。真实模型耗时标「待测」。

### T03 落地记录（2026-11-13，本轮）

#### 从哪里接续

- 基准：`main` 分支，HEAD `00d040699b838c7dd0d7edb35a4d8b66917a6695`（T01+T02 封版，IS_PASS YES）。本轮**从已有工作区继续，未重做、未回滚**上一轮任何成果；工作树原有 ` M .DS_Store` 原样保留、未 add、未 commit。
- **上一轮已完成、直接沿用**：稳定分窗 `source_ordering.py`（K1 排序键 `(file_order,page_key,page_ordinal)`、K2 内容 hash、K3 去重键）、`text_search.SearchOutcome` / `search_check_item_outcome`「有摘录却丢 uncovered」根因修复、`search_check_item` 兼容 wrapper、三档 `not_found_reason`、`_complete_run` 按 `compute_coverage_summary` 赋值、`runs.py` 409 `COVERAGE_INCOMPLETE` 与 `list_results` 覆盖字段、`llm_client` 模块级 `_IN_FLIGHT` + `RequestTrace`、`TEXT_SEARCH_SCHEMA` 的 `check_results` 数组、`build_run_config` / `_write_run_config`、基线脚本失败三态。
- **上一轮只做一半、本轮接续**：`CHECKS_PER_REQUEST` 仅是**配置项**（X 批量分组未落地）；`LLM_MAX_IN_FLIGHT` 仅是模块级信号量（**并发调度器未落地**，`_search_stage` 仍是 `for leaf` 串行）；`RequestTrace` 只在内存（未写 JSONL、未落 `u:` 步）；`SearchOutcome` 是「供后续批次」接口预留；`check_results` 存在性校验（T03-F1）是 T02 **已知缺口**。
- **本轮新做**：`_search_stage` 改为「窗口×检查项批次」单元 + `ThreadPoolExecutor` 全量提交 / `as_completed` 先回先收；`validate_batch_response` 批量校验与七类短码；T03-F2/F3/F4 收敛；前端持久覆盖提示条与完成按钮禁用；三组验收实跑；T05-F1 证据持久化。

#### 本轮改动文件（完整清单）

| 文件 | 改动 |
|---|---|
| `backend/app/processing_pipeline.py` | 重写 `_search_stage`（按 material 分组复用 `load_source_blocks`+`chunk_source_blocks`、按 X 分批、单元 dataclass、`_execute_unit` 模型线程只调用、`_append_traces` JSONL、`_write_unit_step` `u:w{wi}:b{bi}`、`_flush_check` 短事务归并、`_direct_check_result`）；`build_run_config` 的 `batch.status` 改实际生效状态并补 `batches`/`units_total`/提示词版本；`compute_coverage_summary` 收敛（F3 无单元步保守 False + 错误码、F4 affected 纯读 `Result.not_found_reason`、不依赖 `step_key` 前缀）；`_complete_run` 保留调用并记错误码 |
| `backend/app/prompt_registry.py` | `SEARCH_PROMPT_VERSION` 升 `text-search-batch-v2`；新增 `SEARCH_BATCH_SYSTEM_TEMPLATE` 与 `render_search_batch_user`（每批 ID/名称/取证范围/误引边界 + `check_item_id=` 显式清单 + 窗口文本只发一次） |
| `backend/app/text_search.py` | 新增 `validate_batch_response` / `BatchValidation` / `BatchCheckResult`（本批每检查项恰好一项、非法/重复/缺失 ID、幻引零落库但覆盖达成、`OUTPUT_TRUNCATED`、回查 OCR 原文生成摘录）；保留 `SEARCH_SYSTEM` 与 `search_check_item` 兼容 wrapper |
| `backend/app/api/routes/runs.py` | `complete_task` 收敛为单条 `if not run.coverage_complete: 409 COVERAGE_INCOMPLETE`（删 api 侧 `compute_coverage_summary` 反推，位置仍在 `REVISION_CONFLICT` 之后、`compute_statistics` 之前）；`list_results` 的 `coverage_affected_check_ids` 直接从已查出的 `results` 按 `not_found_reason` 计算（零额外查询） |
| `frontend/src/api/types.ts` | `ResultList` 补 `coverage_complete: boolean` / `coverage_affected_check_ids: string[]` |
| `frontend/src/routes/_layout/tasks/$taskId.review.tsx` | 新增 `CoverageBanner`（持久、列出受影响检查项）、`CompleteButton` 在覆盖不全时 disabled + 「识别覆盖不完整，暂不能完成核对」说明；`editable` 判定不变，接受/拒绝/出处定位照常 |
| `docs/REVIEW_HANDOFF.md` | 本文件原地更新（本节） |
| `docs/perf_2026-11-13/` | 新建证据目录（T02 证据副本 + `INDEX.json`、本轮三组验收脚本/日志/证据/JSONL、`INDEX_T03.json`） |

未改：`models.py`、无数据库迁移；未改 `backend/tests/perf/` 与 `frontend/tests/perf/`（QA 资产，零冲突）；`.env` 现值原样保留。

#### 并发和批量怎么启用

- `X = CHECKS_PER_REQUEST`（`1/2/3/6`，默认 `1`），`C = LLM_MAX_IN_FLIGHT`（默认 `2`），二者独立；`LLM_MAX_CONCURRENCY` 是兼容别名、不参与限流。`PIPELINE_CONFIG_VERSION=pipeline-v2`、`LLM_REQUEST_TIMEOUT_SECONDS=180` 本轮未改。
- 改 `.env` 的 `CHECKS_PER_REQUEST` / `LLM_MAX_IN_FLIGHT` 后**代码不需 build，但必须** `docker compose up -d --force-recreate api worker` 才会重读 `env_file`；`docker compose restart worker` 沿用旧 env **无效**；进程内改 `settings` **无效**——`llm_client._IN_FLIGHT = BoundedSemaphore(settings.LLM_MAX_IN_FLIGHT)` 与线程池 `max_workers = settings.LLM_MAX_IN_FLIGHT` 分别在模块 import / run 时固化。
- **QA 实跑前置（`C` / `X` 改 `.env` 生效）**：改 `.env` 后必须 `docker compose up -d --force-recreate api worker` 才会重读 `env_file`（`docker compose restart worker` 沿用旧 env 无效）；`C` / `X` 跑完**必须改回默认** `CHECKS_PER_REQUEST=1` / `LLM_MAX_IN_FLIGHT=2` **并再 force-recreate 一次**，否则后续复跑口径漂移。QA 实跑资产 `backend/tests/perf/mock_config.a_c2_refill_4.json`（4 请求 / C=2 / `release_order=[2,1]` 打乱放行 / 20ms 与 400ms 一快一慢）、`backend/tests/perf/fixtures/quick_acceptance.json`（X=1 3 请求 / X=3 1 请求等价对）、统一离线断言器 `backend/tests/perf/verify_quick_acceptance.py` 均在 QA 目录，本轮**未改**，实现只需能被它们验。
- `X=1` 是「批大小 1」特例，与 `X>1` 共用同一执行器与同一提示词，不按 X 分支写两套逻辑；`C=1` 时 `ThreadPoolExecutor(max_workers=1)` 等价于原有串行入口。
- 改 `backend/app/**` 后必须 `docker compose build api worker && docker compose up -d api worker`（**api 与 worker 是两个独立镜像，都必须重建**），改完进容器 grep 新代码行号确认生效。前端改完需 `VITE_API_URL= npx vite build --outDir /tmp/fe --emptyOutDir` 再 `docker cp /tmp/fe/. credit-review-app-api-1:/app/backend/app/frontend/`（容器内 WORKDIR `/app/backend`，相对 `app/frontend`）；不挂源码卷、产物不入库。
- 本轮验收**不改 `.env`**（现值 X=1 / C=2 / TIMEOUT=180 / VER=pipeline-v2 / ALIAS=2）；`X=3` 由验收脚本在进程内改 `settings.CHECKS_PER_REQUEST` 实测，不是改 `.env`。

#### 三组验收实测结果（两套证据并列，不要混成一套数字）

**本轮有且仅有两套独立证据，必须并列看**：

| 证据集 | 执行方 | 落盘文件（`docs/perf_2026-11-13/` 下） | 结论 |
|---|---|---|---|
| **开发侧自测**（实现后自验） | dev-backend | `t03_pipeline_evidence.json`（28 断言）、`t03_http_evidence.json`（12 断言）、`t03_list_results_evidence.json`（6 断言） | **46/46 断言通过**（28+12+6） |
| **QA 独立实跑**（团长下发实跑信号后） | qa-perf | `qa_measured/quick_acceptance.json`（`mode=measured`）、`qa_measured/chrome/coverage_incomplete.skeleton.json` | 统一断言 **12 PASS / 0 FAIL / 0 未跑 / 0 无法取得 / 1 沿用**（A 4 / B 4+1 沿用 / C 4）+ Chrome **11 PASS / 0 FAIL / 2 PENDING**（C15/C16 本轮范围外） |

开发侧自测用固定响应 + monkeypatch 底层 `openai.resources.chat.completions.Completions.create`（完整走 `complete_json` / `_chat` / `_IN_FLIGHT` 链路）；QA 独立实跑用容器内 HTTP 模拟服务（`settings.LLM_API_BASE` **仅进程内**指向 `127.0.0.1:8099`、未改 `.env`）+ 宿主机真实 8080 完成接口 + `QA_REAL_UI=1` 透明代理转真实前端。**两者均零真实模型 / 零外部 OCR**。

| 组 | 开发侧自测（dev-backend，46/46） | QA 独立实跑（qa-perf，12/0/1） |
|---|---|---|
| **A 并发与归属** | `C=2 / X=1`，4 个搜索单元；峰值在途 **2**；慢请求（400ms）仍在途时已补发 **2** 条新请求（响应完成顺序被打乱）；4 个 `u:w{wi}:b{bi}` 步、4 行 `/data/perf_traces/{run_id}.jsonl`（`t_submit`/`t_http_start`/`t_http_end`/`run_id`/窗口/批次/检查项/attempt/状态），逐条 `t_http_start >= t_submit`；每条结果写入正确 `run_id`/`task_id`/检查项，无串写；run `READY` / `coverage_complete=true` | 4 请求 / C=2；fast **31.7ms**、slow **402.5ms**；补发 seq3 `00.111278`、seq4 `00.221765` **均在 fast 响应后、slow 响应前**（慢请求仍在途）；`first_last_arrival_gap_ms=147.045`；`peak_inflight=2`；barrier `release_order_actual=[2,1]` 生效；JSONL 4 行单一 run_id、`(window_id,batch_index)` 4 组、落库摘录 4 条无串写；`t_submit/t_http_start/t_http_end` 齐全且逐条 `t_http_start - t_submit ≥ 0`；模拟服务 `stats.by_tag` 有值（= run_id） |
| **B 批量、稳定分窗、去重** | 同一 15 页 OCR JSON（SHA256 `8879c8a2…60b`）：`X=1` 实发 **6** 个搜索请求、`X=3` 实发 **2** 个；两者结果集合（`text_sha256 + source_page_number + 稳定 rank`，**不用 fingerprint**）完全相等；`run_config` 记录实际 X / `batches`（X=3 为 1 批 3 个检查项）/ `units_total` / 提示词版本。分窗稳定性**沿用** QA `compare_two_imports.json` 的 24/24 证据——本轮未改 `source_ordering` / `load_source_blocks` / `chunk_source_blocks`，按规格未补跑。合成块去重样本：跨窗口重复引用只存 1 条、同文不同出处保留、同一块被多个检查项引用各项保留；3 个检查项各 **3** 条（共 9 条 text 行），`X=1` 与 `X=3` 相等，fingerprint 均为 64 位 hex 内容 hash | 实发 **X=1 6 / X=3 2**（2 窗口 × 3 检查项，按「窗口数 × 分组数」比例断言，未硬编码 3/1）；结果集合按 `text_sha256 + source_page_number + 稳定 rank` 相等；三类去重 X=1 与 X=3 各 **9 条 text 行、每检查项 3 条**；两次 `run_config` 差异仅 `batch` / `checks_per_request` / `units_total` **三个 X 派生字段**，其余全等；**B0 沿用 T02 24/24**（本轮未改分窗排序） |
| **C 部分失败与完成** | 窗口 0 成功、窗口 1 超时耗尽（重试计入同一额度）：保留 **2 条**成功摘录 + `coverage_incomplete` + `run.coverage_complete=false` + 单元短码 `BATCH_TIMEOUT`（无 `PARTIAL_COVERAGE` 短码）；**直接调完成接口 409 `COVERAGE_INCOMPLETE` 且零写入**；正常样本完成 **200 `COMPLETED`** | 保留 **1 条**成功摘录 + `coverage_incomplete` + `run.coverage_complete=false` + `BATCH_TIMEOUT`；完成接口 **409 `COVERAGE_INCOMPLETE` 严格相等 + 零写入** + `task_id_filtered=true`；正常样本 **200 `COMPLETED`**；`list_results` 实测 `coverage_complete=false` / `coverage_affected_check_ids=["charter.business_scope"]` / `editable=true`。**（保留摘录 2 条 vs 1 条的差异见下节，非源码缺陷）** |
| **T03-F1（从 T02 已知缺口接续修）** | `X=1` 空 `check_results` → 未覆盖 → `BATCH_MISSING_CHECK` + `coverage_incomplete` + 409；仅含非法 ID 顶替 → `INVALID_CHECK_ID` + `BATCH_MISSING_CHECK` + 409；`[{outcome:"not_found"}]` → 覆盖达成 → `no_matching_evidence` →（补人工决策后）200 | 三项**未纳入三组最小集**（由开发侧自测覆盖）；列入 QA 遗留待验清单 |
| **G2 / 历史任务（HTTP 实跑）** | FAILED run → 409 `RUN_NOT_READY`；READY+false → 409 `COVERAGE_INCOMPLETE` + 零写入；READY+true → 200 `COMPLETED`。历史 REVIEWING 任务 `607e6d41-…` **只读核对**（`READY` / `coverage_complete=true` / 无任何 `u:`/`check:` 单元步 / `results` 可 200 回看），完成动作在**同构隔离副本**上实测 200——因硬边界「绝不触碰 2 条真实业务任务」，未对真实任务执行完成写入，故不是「只靠推理」而是「同构实测 + 只读核对」 | 未纳入三组最小集（由开发侧自测覆盖） |

边界：两套证据各自的隔离任务全部 `deleted_at` 软删保留（QA 侧 7 个、开发侧两轮 28 个）；`607e6d41-…`(REVIEWING) 与 `ee59108d-…`(COMPLETED, 77 条结果) 前后 `state`/`deleted_at`/`input_revision` 均未变化。**真实模型耗时：待测**（本轮按边界不跑真实模型 / 外部 OCR）。

#### 外部独立复核前的内部 QA 结论（2026-11-13）

> 本节记录外部独立复验（交付之后、**不在本轮范围**）之前的内部 QA 结论，留后续排期。

- **智能路由判定：`NoOne`**（qa-perf 独立实跑三组验收 + Chrome 真实页面后）。统一断言 12 PASS / 0 FAIL，Chrome 0 FAIL，唯一 FAIL 为 QA 侧测试脚本顺序问题并已自修，**未发现业务源码缺陷、无需返工**。
- **最终镜像全量重跑（2026-11-12 18:18 UTC）**：因 dev-backend 在首次实跑信号后二次重建并替换前端产物，QA 按团长要求以**最终镜像 / 最终前端产物**重跑三组 + HTTP + Chrome，结论与首次一致（12 PASS / 0 FAIL / 1 沿用、Chrome 11/0/2），并收紧断言（A3 双验、A4 逐条额度等待、B2 归一化键不含 `window_index`、B4 静态字段归一化、C13/C14 `data-testid` + exact 文本）。`qa_measured/quick_acceptance.json` 与全部 `*_results/stats` 均为**最终重跑版**；首次结论另存 `*.first_pass.json` 留档，未采信旧数字。镜像/产物 provenance 见 `qa_measured/quick_acceptance_run/image_provenance.json`：api/worker `StartedAt` 均 17:43 UTC（后端镜像两次实跑期间未变），首页唯一前端产物 **`index-CiFoDBwL.js`**（旧 `index-MxNLwRYA.js` 已不在首页），差异只在前端产物替换。最终 A 组实测 fast 26.443ms / slow 401.522ms、补发 seq3/seq4 落在慢请求响应前、`first_last_arrival_gap_ms=139.1`、峰值 2、逐条额度等待 `[0.137, 31.786, 139.532, 0.208]` ms 全部 ≥0；首次实跑的 31.7/402.5ms 与 147.045ms 属旧产物轮次，**两套数字分别引用、不混算**。
- **C17 首跑 FAIL 是 QA 测试脚本顺序问题**：先点「接受」把 decision 切成 `accepted`、前端按 `review.tsx` 逻辑切为单个「已接受（可点击重置）」按钮，导致「拒绝按钮=0」。QA 已自修为「点击前取 unselected 三按钮状态 + 点击后可重置」，重跑 **11 PASS / 0 FAIL / 2 PENDING**。**无需 dev-backend 定向修复**。
- **两处与开发侧自测的差异（如实并列，均非源码缺陷）**：
  1. **C 组保留摘录条数**：开发侧自测 **2 条**、QA 独立实跑 **1 条**。原因：固定响应引用块数不同（QA 引用窗口首块 1 个，开发侧用 `first_last` 引用 2 个）；「成功摘录保留」两侧都成立，不是源码缺陷。
  2. **`X-QA-Tag` 口径**：**请求头 `X-QA-Tag: <run_id>` 与 JSONL 逐请求归属双口径均落地**（`llm_client.py:176` 在二次重建后生效；QA 实测模拟服务 `stats.by_tag` 有值 = run_id，4 请求同一 tag）。QA 主口径走 JSONL、tag 作旁证。早前「未落地」是**二次重建之前**的核实结论，已过时、不作准；本文统一按「双口径均落地」表述。
  3. 补充：QA 正常样本是「全窗口命中 + 全人工确认 → 200」而非「无候选 → `no_matching_evidence`」，断言按 200 + `coverage_complete=true` 判定；B 组 fixture 静态构造为 1 窗口（3/1 请求），实跑按 2 窗口（6/2）适配、不硬断言 3/1。
- **QA 遗留待验**（标「待测」，不写推算值）：性能矩阵、长章程、全文模式、配置面板、**真实模型耗时（待测）**；Chrome C15/C16（本轮范围外）；跨 run 隔离 `(window_id,batch_index)` U5；T03-F1 三项未纳入三组最小集（**开发侧自测已覆盖**）。
- **两套证据不混算**：开发侧 46/46 与 QA 12/0/1 + Chrome 11/0/2 各自独立成表（见上节）；`qa_acceptance/` 是开发侧格式样例、`qa_measured/` 才是 QA 独立实测，**绝不能把样例当验收结果**。

#### QA 实跑字段契约（本轮补充落地）

- **逐请求 JSONL**（`/data/perf_traces/{run_id}.jsonl`，逐行 JSON，只存 hash / 时间戳 / 状态 / 短码，不存窗口全文）：每行含 `trace_id`、`run_id`、`window_id`、`window_index`、`batch_id`、`check_ids`（数组）、`check_item_id`、`t_submit`、`t_http_start`、`t_http_end`、`state`、`error_code`、`finish_reason`、`messages_sha256`、`user_sha256`、`window_text_sha256`，另有 `request_id` / `batch_index` / `check_item_ids` / `attempt` / `unit_state` / `unit_error_code`。`t_submit` = 主线程提交 `ThreadPoolExecutor` 时的 `time.perf_counter()`（**真实采集、非伪造**）；`t_http_start` = acquire 到 `_IN_FLIGHT` 额度后真正发起 HTTP 的时刻；两者差值即「额度等待」。原始证据 `docs/perf_2026-11-13/t03_trace_A.jsonl`（4 行）。
- **A3 无串写归属（两种都落地，QA 二选一即可）**：① 搜索请求带 `X-QA-Tag: <run_id>` 请求头（模拟服务 `stats.requests[].tag` 可记录）；② JSONL 逐请求带 `run_id / window_id / window_index / batch_id / check_ids / check_item_id` 归属。落库侧 `Result.run_id` / `ResultSource` 与 `u:w{wi}:b{bi}` 步同属本 run。开发侧实跑已断言 `qa_tag == run_id` 且 JSONL 必填字段齐全。
- **B4 run_config 除 X 外全等**：`run.model_snapshot.run_config` 可读；静态字段 `C / version(pipeline_config_version) / search_prompt_version / checklist_hash / text_model / window_strategy` 两次运行（X=1 / X=3）除 `X` 外全等；`batch.status` 已改为固定文案、不随 X 变。原始 `run_config` 还完整记录 `batch.batches`（每批检查项 ID）/ `batch.units_total` / `units_total` 等**动态派生**信息（X 的函数）；导出给 QA 断言器时按 `RESULT_SPEC` 归一化为 `{X, C, version, ...}` 即可。样例见 `docs/perf_2026-11-13/qa_acceptance/quick_acceptance_b_x1_results.json` 与 `quick_acceptance_b_x3_results.json`（实测：B1 请求数 6 / 2、B2 归一化集合相等、B4 除 X 外全等）。
- **落库结果导出字段**：`check_item_id` / `text_sha256`（`sha256(result.text)`）/ `source_page_number`（`ResultSource`）/ `page_inner_seq`（`OcrBlock.sequence_index`，页内稳定序号）/ `run_id` / `window_index`；**不用** `Result.fingerprint` 或含 UUID 的请求 hash。样例由 `t03_export_qa_acceptance.py` 从 DB 真实导出。
- **是否改动分窗排序**：**未改** `source_ordering.py` 与 `chunk_source_blocks` / `load_source_blocks` 的排序逻辑（本轮只复用），B0 分窗对照**沿用** T02 `compare_two_imports.json` 24/24，QA 无需补跑 `--windowing-recheck`。
- **前端字面量与 DOM**：持久覆盖提示条 `data-testid="coverage-banner"`，主文案「识别覆盖不完整，暂不能完成核对」，列出 `coverage_affected_check_ids`；完成按钮 `coverage_complete === false` 时 disabled，说明含独立文本节点 `data-testid="complete-blocked-label"` + 精确字面量 **「暂不能完成核对」**（正则 `/暂不能完成/` 与精确断言均可命中）。`editable` 判定不变，接受 / 拒绝 / 出处定位照常。`NOT_FOUND_REASON_LABEL.coverage_incomplete` 文案「识别覆盖不完整，请人工复核」保持不变。

#### 可复跑命令

```bash
cd credit-review-app
# 1) 造数 + A/B/C/F1/G2 的 DB 事实（worker 容器，零真实模型 / 零外部 OCR）
docker cp "<15页章程OCR.json>" credit-review-app-worker-1:/tmp/t03_ocr.json
docker exec -i credit-review-app-worker-1 python - \
  --evidence-out /tmp/t03_pipeline_evidence.json --setup-out /tmp/t03_setup.json \
  --ocr-json /tmp/t03_ocr.json < docs/perf_2026-11-13/t03_verify_pipeline.py
docker cp credit-review-app-worker-1:/tmp/t03_setup.json docs/perf_2026-11-13/t03_setup.json
docker cp credit-review-app-worker-1:/tmp/t03_pipeline_evidence.json \
  docs/perf_2026-11-13/t03_pipeline_evidence.json
# 2) HTTP 层 G2/C/F1/历史断言（宿主机；登录后最后统一软删隔离任务）
python3 docs/perf_2026-11-13/t03_verify_http.py
# 3) list_results 覆盖字段补测（F4 展示面）
python3 docs/perf_2026-11-13/t03_verify_list_results.py
# 4) 导出 QA 断言器输入格式样例（真实实跑数据，供 QA 写导出脚本时对照）
python3 docs/perf_2026-11-13/t03_export_qa_acceptance.py
# 验收前自检
docker exec credit-review-app-api-1 sh -c 'cd /app/backend && python -m compileall -q app'
docker exec credit-review-app-worker-1 sh -c 'cd /app/backend && python -m compileall -q app'
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/

# 5) QA 独立实跑前置（C/X 改 .env 才生效；代码不需 build，但必须 force-recreate）
#    改 .env 的 CHECKS_PER_REQUEST / LLM_MAX_IN_FLIGHT
docker compose up -d --force-recreate api worker
#    QA 用 backend/tests/perf/mock_config.a_c2_refill_4.json、fixtures/quick_acceptance.json
#    等资产实跑并导出 stats / results / complete / trace
#    跑完改回默认 CHECKS_PER_REQUEST=1 / LLM_MAX_IN_FLIGHT=2
docker compose up -d --force-recreate api worker
#    统一离线断言器（QA 资产，本轮未改）：
#    python3 backend/tests/perf/verify_quick_acceptance.py --group A \
#      --stats <a_stats.json> --results <a_results.json> --trace <perf_traces/{run_id}.jsonl>
```

#### 原始证据路径（文档链接一律指向此处）

`credit-review-app/docs/perf_2026-11-13/`：本轮索引 `INDEX_T03.json`、主证据 `t03_pipeline_evidence.json`（28 断言）、HTTP 证据 `t03_http_evidence.json`（12 断言）、`t03_list_results_evidence.json`（6 断言，补测 `list_results` 覆盖字段：`coverage_complete=false`、`coverage_affected_check_ids=["charter.business_scope"]`、`editable=true` 印证「覆盖不全 ≠ 整体只读」）、`t03_setup.json`、`t03_trace_A.jsonl`（逐请求 JSONL，QA A3/A4 断言入口）、可复跑脚本 `t03_verify_pipeline.py` / `t03_verify_http.py` / `t03_verify_list_results.py` / `t03_export_qa_acceptance.py`、原始 stdout/stderr，以及 T02 沿用证据 `INDEX.json` / `pipeline_stdout.json` / `http_results.json` / `compare_two_imports` 相关日志等。
- **`qa_measured/`（QA 独立实测，最终验收结论来源；已同步为最终镜像全量重跑版）**：`quick_acceptance.json`（`mode=measured`，**12 PASS / 0 FAIL / 0 未跑 / 0 无法取得 / 1 沿用**）、`quick_acceptance.first_pass.json`（首次实跑留档）、`quick_acceptance_validate_fixtures.json`、`quick_acceptance_run/`（**19 个原始证据**：`a_*` / `b_dedup_*` / `b_x1_*` / `b_x3_*` / `c_*` / `protected_snapshot` / `runtime_configs` / `setup` + **`image_provenance.json`** 记录 api/worker `StartedAt` 与镜像 sha256、首页唯一前端产物 `index-CiFoDBwL.js`、两轮实跑时间戳）、`chrome/`（`coverage_incomplete.skeleton.json` **11/0/2**、`coverage_incomplete.skeleton.first_pass.json` 首次 11/0/2 留档、`coverage_incomplete.skeleton.t02_baseline.json` T02 封版 **17/0/4** 留档、`quick_acceptance_chrome_evidence.json`）、`assets/`（复跑脚本 `run_quick_acceptance.py` / `run_complete_http.py` / `verify_quick_acceptance.py`、`mock_config.a_c2_refill_4.json`、`fixtures/quick_acceptance.json`、`coverage_incomplete.verify.mjs`、`README_qa_perf.md` 含 **§10.11 最终结论**，§10.10 已标为首次实跑）、以及 `README.md`（明确区分样例与实测、并列两套证据、两处差异、最终镜像 provenance）。共 **34 个文件**。
- **`qa_acceptance/`（开发侧格式样例，不是验收结果）**：dev-backend 自测产出的 `RESULT_SPEC` / `STATS_SPEC` / `COMPLETE_SPEC` 输入格式样例（A/B/C 的 stats/results/complete/trace + `README.md` 字段契约），仅供 QA 写导出脚本时对照；其 B 组是「15 页 OCR + 3 检查项」，与 QA fixture 的「4 候选」口径不同，**不得当作验收结论**。
- `qa_assets/`（T05-F1 归档）：QA 静态资产副本（`backend_tests_perf/` 与 `frontend_tests_perf/`，含 `verify_quick_acceptance.py`、`mock_config.a_c2_refill_4.json`、`fixtures/quick_acceptance.json`、README §10、全部 T02 evidence），以及 **`coverage_incomplete.skeleton.T02_17pass.json`**——T02 封版 **17 PASS / 0 FAIL / 4 PENDING** 骨架证据的留档副本（防 `QA_REAL_UI=1` 实跑覆盖）。QA 的 `backend/tests/perf/` 与 `frontend/tests/perf/` 原路径文件本轮**未改**。

#### 边界与不要误读

- **不得宣称「覆盖不全已 100% 闭环」**：T03-F1 是**从 T02 已知缺口接续修**的（T02 对空 `check_results` 仍给 `no_matching_evidence` 并放行完成），本轮已修并实测 409；但 S5 幻引「有响应但引用不可验证」仍显示 `no_matching_evidence`，属输出质量异常需人工复核的已知局限。真实模型下的批量提示词效果、七类短码全量扩面、两 run 共享额度（U5）、长章程 / 性能矩阵 / 全文模式 / 真实模型抽测均未跑，标「待测」。
- **明确不做**：配置面板、长章程、全文模式、性能矩阵、真实模型抽测、外部独立复验（交付之后）、`models.py` / 迁移、七类短码全量扩面、`timing.progress` 进度接口。
- **两套证据并列、不混算**：开发侧自测 46/46（`t03_*` 证据）与 QA 独立实跑 12/0/1 + Chrome 11/0/2（`qa_measured/`）各自独立；`qa_acceptance/` 只是开发侧格式样例，**不是验收结果**。外部独立复验仍留交付之后排期，本轮内部 QA 路由 `NoOne`（无源码缺陷、无需返工）。
- **双口径归属**：请求头 `X-QA-Tag: <run_id>` 与 JSONL 逐请求归属**均落地**（QA 主口径走 JSONL、tag 作旁证）；早前「未落地」是二次重建前核实、已过时。
- 本轮未 `git commit`、未 `git add -A`；未新增交接文档副本，未写文档自身提交号。Chrome 由 QA 独立实跑一条部分失败任务，本轮只把前端改好并构建同步；收口阶段未改业务代码、未重建镜像。

### 开工前记录（2026-11-12 19:08 实测，非推算；历史状态，保留作对照）

| 项 | 实测值 |
|---|---|
| 项目目录 | `/Users/eddie/Documents/WorkBuddy/合规审查智能体/credit-review-app` |
| **Git 仓库根** | **`/Users/eddie/Documents/WorkBuddy/合规审查智能体`（外层）**；`git rev-parse --show-toplevel` 实测；**`credit-review-app/.git` 已不存在**，内层不再是独立仓库。因此所有 git 路径以 `credit-review-app/` 为前缀（如 `credit-review-app/docs/REVIEW_HANDOFF.md`），后续 `git add` 需用外层相对路径，不要沿用旧的「cd 进 credit-review-app 再 add」习惯 |
| 分支 | **`main`**（已非上一轮的 `feature/credit-review`） |
| HEAD | **`db8f46e38b9b045b5947591a5f75a3060b24752a`**（`Initial commit (include credit-review-app as normal folder)`，2026-11-12 15:40:30 +0800） |
| remote | `https://github.com/AmazingYanyan/compliance-review-agent.git`（`origin/main` 与 HEAD 同指 `db8f46e`） |
| 提交历史 | 仅 2 条 Initial commit（`db8f46e`、`db99235`）；**旧仓库 `feature/credit-review` 分支与 `9c1eda1` / `632f874` / `8c05fcc` / `5167257` 等全部旧提交在本仓库不存在、不可回查**（已用 `git cat-file -t` 逐个确认）；本文头部旧 commit 链属历史记录 |
| 工作树 | **干净**，`git status --short` 为空、`git diff --stat` 为空、无 untracked 文件；**本地未提交改动：无** |
| 上一轮三份交付 | `docs/REVIEW_HANDOFF.md`、`docs/perf_baseline_2026-11-12.json`、`scripts/baseline_serial.py` 均已随 initial commit 入库，不再是未提交文件 |
| 5 张历史截图 | 上一轮的 `docs/screenshots/review_*.png` 删除标记已不复存在；新仓库 `docs/screenshots/` 仅 3 个文件（`tasks_actions_two_states.png`、`tasks_final_verify.json`、`tasks_table_verify.json`） |
| 运行服务 | `credit-review-app-api-1` Up 8h、`db-1` Up 33h(healthy)、`worker-1` Up 10h；`http://localhost:8080/` → **200**（本轮未重建镜像、未触发 OCR/LLM） |
| 输入指纹 | 15 页章程 OCR JSON 实测 SHA256 `8879c8a2d9ba8e702890f1fbf504f8f2ff4f0d08c8bc72366e10365ef0ebe60b`，**与任务给定值一致** |

### 前置验收证据盘点

| 现存证据文件 | 实际覆盖范围 | 是否覆盖四项前置 |
|---|---|---|
| `docs/delete_readonly_verify.json` | 删除接口只读 3 用例 / 67 项断言 / 21 次请求 | ❌ 否 |
| `docs/screenshots/tasks_table_verify.json` | 我的任务表格 40 项 | ❌ 否 |
| `docs/screenshots/tasks_final_verify.json` | 定向收尾 28 项 | ❌ 否 |
| `docs/perf_baseline_2026-11-12.json` | 15 页短样本串行基线 + QA 两轮复验（含 run 绑定产物披露） | ⚠️ 仅佐证「稳定分窗未修复」，非前置验收 |
| `scripts/baseline_serial.py` | 可复现串行基线脚本（含 `--probe-only`） | ⚠️ 仅观测/披露工具，非前置验收 |
| `backend/tests/` | 仅 `conftest.py`(1 行) + `test_p1.py`(98 行)，共 99 行 | ❌ 无分窗/去重/覆盖/完成接口相关单测 |
| `frontend/tests/` | `tasks-table.verify.mjs`、`tasks-final.verify.mjs` 及模板遗留 spec | ❌ 无覆盖不全提示/完成拦截的前端验收脚本 |

**结论：工作区与仓库内不存在任何针对四项前置的独立复验证据或验收脚本。** 上一轮文档（根目录 `交接文档.md` 10.3）曾写「断句/住所串入/去重已有单测，未跑真实 run 复核」，但该单测在重建后的仓库中不存在，属**过时表述**，不能作为前置已通过的凭据。

### 四项前置门槛核查（全部未通过独立复验）

| 前置项 | 代码中可找到的实现 | 独立复验证据 | 缺口 | 判定 |
|---|---|---|---|---|
| **① 稳定分窗** | `backend/app/text_search.py:80` 仍为 `.order_by(OcrBlock.sequence_index)` 单一排序键；`classification.py` 同款 | 上一轮 QA 用 `--probe-only` 实跑 2 次，证据 `sample_limitations.run_bound_artifacts` 记录 4 次导入的窗口块数/字符数/窗口文本 hash 全部漂移 | **未修复**：`ocr_blocks.sequence_index` 仅 25 个不同值却存 176 块，同值行按 DB 物理序，窗口边界不确定；`_window_text()` 与 `_fingerprint()` 含每次新建的随机 OcrBlock UUID，跨 run 窗口 hash 与 fingerprint 不可复现。此项直接破坏本实验「固定窗口、同一输入对照」的口径 | ❌ **未通过**（修复本身未做） |
| **② 覆盖不全提示** | 后端 `processing_pipeline.py:327-329` 有 `PARTIAL_COVERAGE` → `not_found_reason="coverage_incomplete"`；前端 `frontend/src/api/types.ts:169` 有文案「识别覆盖不完整，请人工复核」 | 无。上一轮基线 `coverage_incomplete=0`、19 步全 SUCCEEDED，证据明确写「本样本未触发技术失败分支，`coverage_incomplete` 与 `no_matching_evidence` 的区分仍需故障注入或长样本验证」 | 无故障注入触发记录、无前端展示验收记录；`$taskId.review.tsx` 仅对 `material_missing` 有专门分支，`coverage_incomplete` 只走通用 label 映射，实际提示效果未验 | ❌ **未通过**（仅代码路径存在） |
| **③ 完成接口拦截** | `backend/app/api/routes/runs.py:446-478` `complete_task` 有 `RUN_NOT_READY` / `REVISION_CONFLICT` / `NOT_COMPLETE` 409 拦截；`_incomplete_items`(417-443) 检查未确认项与拒绝缺原因 | 无针对完成接口的独立复验证据（现存 67 项是删除接口） | 拦截口径只覆盖人工决策未完成，**未把 `coverage_incomplete` / `coverage_complete=false` 纳入完成条件**；部分覆盖时能否完成核对未验证；补跑入口未验收 | ❌ **未通过**（基础拦截存在但口径不全、无证据） |
| **④ 摘录去重** | `backend/app/text_search.py:204-219` `_dedup_evidence`（包含关系去重 + 按 `(source_page_number, block_id)` 排序）、`199-201` `_fingerprint` | 无单测、无端到端重跑记录 | 排序键含随机 `block_id` UUID，跨 run 顺序不稳定（与 ① 同源）；「主条款/分项/例外跨块跨页」「同一规则多段限定条件」「超过默认展示条数」三类场景未验；根目录交接文档 10.3 亦标注「摘录边界端到端重跑：待验证」 | ❌ **未通过**（仅函数存在） |

**门槛结论：四项全部未通过独立复验，按用户指令本轮不开始实现。** 其中 ① 是本实验的前置中的前置——不先修稳定分窗，`X=1/C=1` 新基线、窗口内容 hash、串行与并发结果逐条比对都不可信。用户已说明可直接操作 Chrome 浏览器验收前端效果（WorkBuddy Chrome 扩展已安装并开启），该能力留待 ②③ 的前端独立复验阶段使用，本轮未调用。

### 待执行任务规格（登记全文，门槛通过后据此开工）

#### 目标与最终结论要求
用同一份 15 页章程 OCR 验证三件事：**提高并发度能省多少时间**、**一次请求携带多个检查项能省多少请求和时间**、**两者叠加后能否稳定保住关键原文、例外条件和正确出处**。最终结论必须分别回答：并发提升在哪个档位开始收益变小或触发限流；`X` 取多大能稳定保住关键条款；两组都能全量派发时批量组到底省了多少时间和 Token。长章程 **15 分钟目标**留待长样本实测。

#### 一、固定输入与对照口径
1. 使用上述 15 页 OCR JSON（SHA256 `8879c8a2…60b`），隔离任务 + 已取得的 OCR JSON；记录实际块数、字符数、页范围、**文件及块的排序规则**；区分「跨次导入可复算的内容 hash」与「实际发送给模型的窗口 hash」。
2. 用**稳定分窗修复后的代码**重建 `X=1/C=1` 基线；固定模型、清单、窗口、检查项顺序、生成参数、超时策略；每种策略记录实际提示词及版本；同一策略对照并发度时提示词与窗口输入必须一致；批量策略的提示词与响应结构变化点单独记录。
3. 定义 `X` = 每个搜索请求最多携带的检查项数，`C` = 允许同时在途的模型请求上限，**两者独立配置**。以修复后仍有 2 窗口、6 章程检查项为例（**任务书示例口径，非实测**）：`X=1/2/3/6` 分别产生 `12/6/4/2` 个搜索请求，以实际窗口与适用检查项为准；分类、格式修复、重试调用单独计数。
4. 旧的 **600.640 秒**保留为**历史串行参考**；并发与批量收益一律用修复后的新基线计算。每次对照注明计时范围，分别记录分类、搜索、后处理总耗时，以及本次执行是否经过队列、是否计入排队时间。

#### 二、实现独立搜索任务的并发调度
1. 分类完成后**一次生成并提交本次 run 的全部独立搜索任务**；`X=1` 调度单位为「窗口 × 检查项」，启用批量后为「窗口 × 检查项批次」。按可用在途额度派发，**任意请求完成即释放额度并补发下一个**；待发数 ≤ 可用额度时全部立即派发；避免固定分波、避免等同一批最慢请求。
2. 优先复用现有同步模型客户端 + 线程池 + `as_completed`；核对执行器、客户端信号量（`LLM_MAX_CONCURRENCY`，当前 2）与连接池实际限制。`C=12` 时隔离模拟用例须实测 **12 个模型请求同时在途**；**线程池交付时间与 HTTP 真正发起时间分别记录**。
3. **哪个响应先返回就先校验保存哪个**；每个响应保存对应窗口的有效候选与检查项覆盖状态；模型 HTTP 等待期间保持 DB 事务关闭，落库用独立短会话或由收集端串行执行短事务；到达顺序可变，最终摘录顺序、去重、出处须稳定；全部应处理单元结束后再汇总 run 状态与 `coverage_complete`。
4. 复用已验收的超时、有限重试、致命失败、部分覆盖规则；**重试同样计入模型调用额度**；记录每次请求是正常完成／超时／限流／格式修复／最终失败；部分失败时已保存的有效候选继续可用；覆盖提示、完成条件、补跑入口沿用届时已验收的行为。
5. **用两个 run 同时执行验证共享额度**：记录单 run 峰值、两 run 合计峰值、当前 worker 部署方式；若共享同一模型账号/额度，验证调度能否遵守共享限制；若共享限制只在单进程内生效，明确写出适用范围及多 worker/多进程下仍待验证部分。默认并发度由实测决定，`C=12` 是短样本全量并发试验档。

#### 三、实现可切换的多检查项批量搜索
1. 先覆盖**章程文本摘录**；新增后端配置 `checks_per_request`，支持 `1/2/3/6`，**默认保留 1**；并发上限使用独立配置。按稳定清单顺序分组；每次 run 记录实际生效的 `X`、`C`、分窗策略、每批检查项 ID、模型、清单、提示词版本；正常入口能用 `X=1` 回到单检查项搜索。
2. **一个请求只发送一次当前 OCR 窗口**，附该批检查项 ID、名称、取证范围及易误引边界；模型按检查项分别返回；**每个请求中的检查项必须有且仅有一个响应**（该窗口候选出处或「本窗口无候选」）；允许同一 OCR 块支持多个检查项、一条证据引用多个相邻块。
3. 后端校验返回的检查项 ID 与引用块属于当前请求；按 OCR 原文生成摘录，出处页码与定位信息沿用原有数据；按检查项跨窗口合并去重，保持不同检查项的有效引用；验收主条款、分项、例外分布在多块或跨页时能否一起保留并分别定位。
4. 首版可给候选标记「直接依据 / 关联上下文 / 待人工确认」；**候选保留与默认展示分别处理**，合并去重后再应用默认展示条数，其余有效候选仍可查看；每项少于上限时按实际数量返回；测试少于上限、超过上限、同一规则包含多段限定条件三种情况；相关度分数如有采集仅用于离线试验，先保留全部有效候选用于复验；模型输出上限触顶时记录供应商截断信号、受影响项与后续处理。
5. **覆盖按「窗口 × 检查项」记录**：整批超时耗尽则该批当前窗口的检查项均为未覆盖；可解析的部分响应保留已验证检查项与有效候选，对漏项、重复项、无效引用、截断分别记录；整份不可解析时记录受影响批次及重试结果；某检查项已有成功摘录但仍有必查窗口未覆盖时**保留摘录并明确显示覆盖不全**；只有应查窗口均完成且均无候选才适用正常未找到；补跑证据写清实际重试的是窗口、批次还是整个 run。

#### 四、按顺序执行独立验收
1. **模拟服务与固定响应**：① 全量并发——固定 `X=1`（预期 12 请求，以实际为准）、`C=12`，模拟服务先接收再按预设顺序放行，记录真实到达时间与峰值在途数，以首末搜索请求约 1 秒内到达为目标并回传实际时间差；② 空位即时补发——`C=2` 安排一快一慢，快请求返回后先保存结果并发出下一条、慢请求仍在途，打乱响应顺序后摘录/出处/覆盖/排序保持一致；③ 批量正确性——同一 OCR 与等价固定响应对照 `X=1` 与 `X=3`，至少覆盖同块被两项合法引用、一证据引用多块、批内漏返、重复返回、无效块引用、输出截断、整批超时七类；④ 两个 run 额度与隔离——记录合计在途数、补发顺序、归属 run ID 与落库结果，确认一条响应只写入对应 run/窗口/检查项。
2. **真实模型先并发、再批量**：先固定 `X=1` 跑 `C=1/2/4/8/12` 阶梯，记录实际峰值、首末请求发起时间差、429、超时、重试、延迟变化、搜索墙钟；若并发升高后排队/限流增加或总耗时上升，回传档位与证据；最高档未跑完则保留模拟全量并发结果并说明停在哪档。再完成四组核心对照，**每组至少重复 3 次**（阶梯中已有合格记录可纳入统计）：`A X=1/C=1`（修复后串行基线）、`B X=3/C=1`（批量单独收益）、`C X=1/C=2`（并发单独收益）、`D X=3/C=2`（叠加）。最后比较两种全量并发（`X=1` 全部单项请求 vs `X=3` 全部批量请求，按 2 窗口 6 检查项举例为 12 vs 4 个请求全部在途），用实际发起时间与峰值在途数证明；再试 `X=6` 重点观察单请求延迟、输出截断、关键证据漏摘；`X=2` 至少完成配置与请求数验收并视前档表现纳入真实对照。**全文模式单列实验**：输入满足上下文与输出预算时把全文作为一个搜索窗口，分别记录请求数、输入/输出 Token、耗时、输出截断、候选差异，重点核查文档中部与跨页证据，超限记录实际表现与回退方式。
3. **业务质量先冻结预期再逐条核对**：在看各组模型结果前，先从 OCR 原文整理**人工核对过的证据清单**（当前尚未形成文件，属待办），明确检查项、物理页、原文范围与误引边界，至少包括：第 7 页经营范围「外汇担保」是否被误引为对外担保的决议权限或限制；第 14 页 C7 三条独立依据（一般性事前书面告知、借款余额超股权净值时不得质押、质押达 50% 限制表决权；特定股东事前备案另记一项，**不能代替一般告知**）；第 14–15 页担保批准权、正常经营范围内业务例外、对外担保限制条件（分别核对跨页出处与条款限定，单列「法定职权不得转授」摘录情况）；C6 按冻结清单核对「决议通过所需的表决权比例」（授信逾期后的股东表决权限制单列，避免混入本检查项漏召回统计）。逐条回传：模型是否找到候选、保存的原文与页码是否正确、默认视图是否保留或可展开、是否有额外误引；对照人工预期与 `X=1` 基线；若批量组漏掉关键证据或引入关键误引，**保留 `X=1` 为默认**并提交具体差异与复现条件。

#### 五、最终回传与交接
原地更新本文件，链接机器可读的原始结果、复验命令与证据。最终回复须含：① 版本和改动（基准 HEAD、实际分支、改动文件、提交状态、生效配置及默认值、当前并发上限作用范围、开启各试验档的方式）；② 输入和可复现信息（OCR SHA256、窗口数、每窗页范围与块数、窗口内容 hash、每批检查项、清单、模型、提示词版本，并区分两类 hash）；③ 逐请求原始数据（实验组、run、窗口、批次、检查项、尝试序号、入队时间、实际 HTTP 发起时间、响应时间、落库时间、状态码、超时、429、重试、格式修复、输入/输出 Token、截断信号；调用端取不到的字段标明缺失原因）；④ 逐组性能结果（每次运行与组内中位数、搜索实际请求数、其他模型调用数、首末发起时间差、峰值在途数、本地等待、分类/搜索/后处理/端到端耗时，标明模拟与真实模型，高并发档未完成保留失败数据）；⑤ 正确性与待验事项（逐用例预期/实际/断言/证据路径、关键条款差异表、部分覆盖与失败重试结果、两 run 共享额度验证、尚未验证事项）。**前端 Low / Medium / High 或「标准 / 扩展」运行档位，根据上述结果再决定，本轮不预设。**

### 本轮登记未做的事（边界）

- 未实现并发调度、未实现 `checks_per_request` 批量搜索、未改任何业务代码/配置/模型、未跑任何真实或模拟模型实验、未产生新的 run 与请求数据。
- 未做四项前置的独立复验（该项是开工门槛，需单独安排；前端两项可用 WorkBuddy Chrome 扩展直接操作浏览器验收）。
- 未重建镜像、未执行迁移、未新增单测或验收脚本、未新建交接文档副本。
- 本轮改动仅此一份 `credit-review-app/docs/REVIEW_HANDOFF.md`（原地更新，路径为**外层仓库根**视角）：新增本章节 + 头部仓库状态提示 + 「性能下一步」入口指引 + 「依据」两条状态更正；**未 `git commit`**，本次编辑后 `git status --short`（在外层仓库根执行）仅输出 ` M credit-review-app/docs/REVIEW_HANDOFF.md`。

## 单一交接文件约定

后续在项目中只维护 `docs/REVIEW_HANDOFF.md`。先将 P0、P1、性能方案中的仍有效信息并入此文件并提交，再清理同目录下已合并的副本。历史可通过 Git 提交回查，测试证据可链接到对应截图、日志或测试输出。每轮原地更新实际 commit、本轮变更、通过项、待验项和下一步。功能已实现、已实测、待验证与方案阶段使用明确的状态。

## 依据

- 上一轮实测证据（`8c05fcc`）：验收脚本 `frontend/tests/tasks-table.verify.mjs`、本地 fixture `frontend/tests/fixtures/tasks-23.json`、结果日志 `docs/screenshots/tasks_table_verify.json`、同屏截图 `docs/screenshots/tasks_actions_two_states.png`。
- 最后一轮定向收尾证据（`7f6b806`）：`frontend/tests/tasks-final.verify.mjs`、`docs/screenshots/tasks_final_verify.json`（含上传 ID 证据、菜单/材料区快照、逐项对比度）、覆盖更新后的 `docs/screenshots/tasks_actions_two_states.png`。
- 后端删除只读 BugFix 证据（`5167257` / `e2cff93`）：`docs/delete_readonly_verify.json`（原两用例 40 项断言／14 次请求 + 补充用例 3 的 27 项断言／7 次请求、77 条结果条目与人工决定逐条指纹、前后响应 SHA256；合计 67 项全通过）。
- 短样本串行基线（原记录为「未提交」，**仓库重建后已随 `db8f46e` 入库，此处更正**）：脚本 `scripts/baseline_serial.py`、结构化证据 `docs/perf_baseline_2026-11-12.json`（run `5547804d-da6d-4417-8139-9dc36e3b5e3e`，14 次真实模型请求、后处理 600.64s、classify/检查项各 2 窗口、44 条结果）；完整复现命令、瓶颈判断与下一轮 5 项设计见「短样本串行基线（2026-11-12）」章节。
- 下一阶段性能试验（2026-11-12 晚间登记，**未开工**）：登记内容、开工前状态、四项前置缺口与全部待执行规格见「下一阶段性能试验」章节；本轮无新增机器可读证据文件。
- 项目经验参考（工作区根目录，非交接文档）：`沉淀经验.md`、`交接文档.md`。
- [P0 开发交接](https://chatgpt.com/library?file_id=libfile_ee54a80106b88191b01199fc450549c3&account_id=personal)
- [P1 开发交接](https://chatgpt.com/library?file_id=libfile_5242edc5a9688191875bb85b1dd64c09&account_id=personal)
- [性能方案](https://chatgpt.com/library?file_id=libfile_2010869f426c8191b7f29f2a7681cc0a&account_id=personal)
- [任务操作列](https://chatgpt.com/library?file_id=libfile_10b91779b0cc8191bdfb278454430761&account_id=personal)
- [正文与待办导航](https://chatgpt.com/library?file_id=libfile_d22819b414648191844da3d6934f782d&account_id=personal)
- [缺失面板折叠态](https://chatgpt.com/library?file_id=libfile_a0fbaaa07ee081918dfd4c11d81b3ad0&account_id=personal)
- [Python 并发任务与取消语义](https://docs.python.org/3/library/concurrent.futures.html)
- [SQLAlchemy 会话并发模型](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks)
