# 章程核对 · 现行规格（状态表）

本文是 V2「对公信贷资料核对」**章程核对（charter-verification）切片**的现行需求规格。它把阶段 A 的线框评审结果固化为可联调的状态表，并逐条标注结论的证据等级。

- 范围：仅章程材料（`material_type = articles_of_association`）的核对工作台。营业执照、审计财报属后续迁移范围。
- 配套文档：接口契约 [api-contract.md](../architecture/api-contract.md)；落库字典 [data-dictionary.md](../architecture/data-dictionary.md)；V1 复用盘点 [v1-reuse.md](../architecture/v1-reuse.md)；验证口径 [../verification/charter.md](../verification/charter.md)。
- 配套线框：`credit-review-app-v2/prototype/`（`index.html` + `workbench.js` + `workbench.css` + `fixtures/charter.js`）。线框是演示态，**不是**契约；契约以本文与 api-contract.md 为准。

## 零、证据标注约定

| 标注 | 含义 |
|---|---|
| 〔实测〕 | 本轮实际读过 V1 源码并给出 `file:line`，或实际读过的 V2 线框文件并给出**可定位锚点**（元素 id / CSS 类 / fixture 键 / 函数名） |
| 〔沿用〕 | V1 固定提交 `e52520553f3efe8e790fb608e630bf29bab9c1bf` 的既有结论；本轮核对过源码但结论未变 |
| 〔待验〕 | 需阶段 B 实跑或真实样本才能定论 |

V1 的 `file:line` 均为**相对 V1 固定提交**的仓库根相对路径（`credit-review-app/backend/app/...`）。取单文件用 `git show e525205:<path>`。

V2 线框文件在演进中会整体重排行号，因此本文对 `credit-review-app-v2/prototype/` 下的引用一律使用**稳定锚点**而非行号：HTML 用元素 id（如 `#progress`、`#complete-reason`）或类名（如 `.material-tabs`），CSS 用类名（如 `.card--affected`、`.badge--warn`），`fixtures/charter.js` 用导出键（如 `scenarios.invalid.affected`、`notFound`、`pageSize`），`workbench.js` 用函数名（如 `progressText()`、`completionState()`、`cardHtml()`、`locate()`、`isPending()`）。

## 一、布局与交互（现行规格）

系统按清单展示原文与出处。办理人逐条接受或拒绝，拒绝需原因。

| 区域 | 规格 |
|---|---|
| 材料页签 | 章程 / 营业执照 / 审计财报三页签〔实测，`index.html` 的 `.material-tabs`〕。后两者点击后提示「属后续迁移范围，尚未进入本轮核对」〔实测，`workbench.js` 的 `bannerText()`〕 |
| 上方状态与完成动作 | 一行展示任务名、客户角色、输入版本、状态徽章、计数，以及「完成核对」按钮与其原因文案〔实测，`index.html` 的 `#task-name`、`#customer-role`、`#revision`、`#status-badge`、`#progress`、`#complete`、`#complete-reason`；计数与原因文案由 `workbench.js` 的 `progressText()`、`completionState()` 生成〕。计数文案统一为「已确认 N / M · 未找到 1 项待确认」：**M 只计非受影响的摘录项**，「正常未找到」项不进分母、单列显示，且未决定前仍阻塞完成；覆盖不全场景另插入「受影响 K 项（无效出处 / 输出截断）」段〔实测，`workbench.js` 的 `progressText()`、`isPending()`〕 |
| 左栏 | 原件预览，含页码跳转（`#page-prev`、`#page-input`、`#page-next`）、缩放档位（适应宽度 / 100% / 150% / 200%）、页码指示〔实测，`index.html` 的 `#source` 与 `.toolbar`；页码与缩放逻辑见 `workbench.js` 的 `updatePageIndicator()`、`updatePageButtons()`、`jumpToPage()`、`applyZoom()`〕 |
| 右栏 | 摘录卡片列表（`#results`），每张卡含检查项标题、摘录正文、出处入口、决定动作、决定结果行；栏标题旁的计数（`#count`）与顶部计数同源〔实测，`workbench.js` 的 `cardHtml()`、`renderResults()`、`renderHeader()`；`index.html` 的 `#results`、`#count`〕 |
| 两栏各自滚动 | 左栏 `scroll.source`、右栏 `scroll.cards` 独立滚动，互不影响〔实测，`index.html` 的 `#source` 与 `#results`〕 |
| 下一条循环 | 「下一条待办」跳到当前项之后的首个未处理项，跳过已处理项，到末尾回绕〔实测，`workbench.js` 的 `#next` 点击处理与 `isPending()`；阶段 A 浏览器实测序列 e3 → e4 → not-found → 回绕 e3〕 |
| 点出处才驱动原件定位 | 仅「查看出处 · 第 N 页」触发左侧翻页与高亮〔实测，`workbench.js` 的 `locate()` 与 `data-action="locate"` 分支〕 |

## 二、状态表（本轮范围）

六种状态互斥，由后端事实推导，不由前端场景切换决定。**数据来源列给出后端事实来源的表字段**；**联调预期列给出阶段 B 的 HTTP 响应与数据库落库双向预期**。

| 状态 | 数据来源（后端事实） | 界面表现 | 允许操作 | 完成规则 | 联调预期（阶段 B） |
|---|---|---|---|---|---|
| **处理中** | `processing_runs.state ∈ {QUEUED, RUNNING}`；`processing_runs.stage`；`tasks.state = PROCESSING`；`run_steps.state`〔沿用，`runs.py:128`、`:136-137`；`processing_pipeline.py:975`；`models.py:418-419`、`:59-64`〕 | 徽章「处理中」；右栏只显示阶段列表（OCR 完成 → 文本分窗 → 检索摘录），**不出现摘录卡片**；左栏空态「章程处理中，暂无可预览的原件」；「完成核对」禁用 + 原因「无法完成：核对结果尚未就绪」〔实测，`fixtures/charter.js` 的 `scenarios.processing.processing.stages`；`workbench.js` 的 `completionState()`、`renderSource()`、`stateCardHtml()`〕 | 只读：查看任务身份、阶段与进度；不出现接受/拒绝入口；「完成核对」按钮存在但禁用（`aria-disabled="true"`）并显示原因〔实测，`workbench.js` 的 `isActive()`、`editable()`、`renderHeader()`〕 | 不可完成。run 非 `READY` → `POST /complete` 返回 `409 RUN_NOT_READY`〔沿用，`runs.py:495-499`〕 | HTTP `409 RUN_NOT_READY`；数据库 `tasks.state` 仍为 `PROCESSING`，`tasks.completed_at` 为 NULL，`tasks.last_ready_run_id` 为 NULL（**零写入**）〔实测判据沿用 V1 `tests/perf/run_complete_http.py:112-130` 的前后快照法〕 |
| **缺材料** | 本轮所需材料在 `run_files` 快照中缺失；对应检查项落 `results.kind = 'not_found'` 且 `results.not_found_reason = 'material_missing'`；`task_files` 无该材料文件〔沿用，`processing_pipeline.py:712`、`:888` 为写入该字面量的两处调用点〕 | 徽章「缺材料」；右栏显示「缺少『公司章程』」+「补传材料」占位按钮（提示「上传入口在阶段 B 接入」）；左栏空态「『公司章程』尚未上传，暂无可预览的原件」〔实测，`fixtures/charter.js` 的 `scenarios.missing`（含 `missingMaterial`）；`workbench.js` 的 `stateCardHtml()`、`renderSource()`〕 | 补传材料（阶段 B 接上传通道）；其余只读，无决定入口；「完成核对」按钮存在但禁用（`aria-disabled="true"`）并显示原因〔实测，`workbench.js` 的 `isActive()`、`editable()`、`renderHeader()`〕 | **待决策（待产品确认）**，见第三节。线框当前展示的是**候选 A 的界面形态**（完成按钮禁用 + 原因「无法完成：材料缺失，完成规则待决策」），但文案自身标注为「待决策」〔实测，`fixtures/charter.js` 的 `scenarios.missing.completionRule`；`workbench.js` 的 `completionState()`〕——线框不构成对候选的选择 | 待产品决策后冻结。若采候选 A：完成被专门拦截，HTTP 409 + 零写入（错误码待阶段 B 定名）；若采候选 B：沿用 V1 现状，`material_missing` 不阻断覆盖判定，也不自动阻断 `can_complete`，由人工决定后完成，HTTP 200 |
| **正常未找到** | `results.kind = 'not_found'` 且 `results.not_found_reason = 'no_matching_evidence'`；该行无 `result_sources`〔沿用，`processing_pipeline.py:673`、`:916`〕 | 右栏一张「未找到 · 待确认」卡片（正文「本次样本未找到相关原文。」）；该卡**不计入**「已确认 N / M」分母（M 只计非受影响的摘录项），单独显示「未找到 1 项待确认 / 已确认 / 人工核对」〔实测，`fixtures/charter.js` 的 `notFound`；`workbench.js` 的 `progressText()`、`isPending()`〕 | 人工接受或拒绝（该 result 同样是 `results` 行，有 `decisions` 行）；拒绝需填原因 | 该 result 计入 `statistics.total`；已决定（accepted，或 rejected 且原因非空）不阻塞完成；未决定计入 `unselected` → 阻塞完成〔沿用，`decisions.py:34-64`、`runs.py:475-485`〕 | HTTP `200`（仅当它已决定）；数据库 `decisions` 中该 `result_id` 有一行，`decision`/`reject_reason`/`version` 与请求一致，事件表按「首次不写、更新才写」落库〔沿用，`decisions.py:134-171`〕 |
| **覆盖不全** | `processing_runs.coverage_complete = false`（**唯一事实源**，worker 写）；`results.not_found_reason = 'coverage_incomplete'` 派生出受影响检查项；`processing_runs.error_code`（如 `COVERAGE_NO_UNIT_STEPS`）〔沿用，`processing_pipeline.py:160-245`、`runs.py:249-255`〕 | 徽章「覆盖不全」；横幅「识别覆盖不完整，暂不能完成核对。」并列出受影响项标题；受影响卡片带状态竖条（`.card--affected`）与标签「受影响 · 无效出处」/「受影响 · 输出截断」（`.badge--warn`），**仍展示摘录正文与「查看出处 · 第 N 页」入口，但没有任何接受/拒绝按钮**；同一场景内的其余有效摘录仍可接受或拒绝，已作出的决定保留；「完成核对」禁用 + 原因「无法完成：N 个检查项覆盖不全（标题列表）」〔实测，`fixtures/charter.js` 的 `scenarios.invalid.affected` / `scenarios.truncated.affected`，`workbench.css` 的 `.card--affected` / `.badge--warn`，`workbench.js` 的 `cardHtml()`、`bannerText()`、`completionState()`〕 | 受影响项**不提供**决定入口（线框不渲染接受/拒绝按钮），不计入「已确认 N / M」，也不进入「下一条待办」序列；同场景的非受影响项可正常决定，其决定照常保留〔实测，`workbench.js` 的 `cardHtml()`（决定动作仅在 `editable() && !affected` 时渲染）、`isPending()`〕 | 不可完成。完成被覆盖事实 `processing_runs.coverage_complete = false` 阻塞 → `POST /complete` 返回 `409 COVERAGE_INCOMPLETE`，**即使每个可见摘录都已确认也必须拦**（人工决策不替代覆盖事实）〔沿用，`runs.py:506-518` 含明确注释〕 | HTTP `409 COVERAGE_INCOMPLETE`；数据库 `tasks.state`、`tasks.completed_at`、`tasks.last_ready_run_id` 逐字段不变（**零写入**）〔实测判据沿用 V1 `run_complete_http.py:112-130`〕 |
| **正常核对** | `processing_runs.state = 'READY'` 且 `processing_runs.coverage_complete = true`；`results` 行（`kind = text/not_found`）；`decisions` 行；`run_files.effective_material_type` 决定材料归属〔沿用，`runs.py:256-266`、`decisions.py:67-102`〕 | 徽章「正常核对」；右栏卡片含标题、摘录、「查看出处 · 第 N 页」、接受/拒绝；「已确认 N / M」随决定 +1（计数文案统一为「已确认 N / M · 未找到 1 项待确认」，**M 只计非受影响的摘录项**，「正常未找到」项单列且未决定前仍阻塞完成）；全部处理后「完成核对」可用，原因文案「可完成」〔实测，`workbench.js` 的 `progressText()`、`completionState()`〕 | 点标题/摘录＝选中并右栏聚焦（**不移动左栏**）；点「查看出处 · 第 N 页」＝翻页 + 高亮；接受；拒绝（留空或纯空格时「保存拒绝」禁用）；重新选择；下一条待办；完成核对〔实测，`workbench.js` 的 `data-action` 分支（`select` / `locate` / `accept` / `reject` / `reset` / `save-reject`）〕 | `can_complete = (total > 0) AND (unselected = 0) AND (missing_reason = 0)` → `200` + `tasks.state = COMPLETED` + `tasks.last_ready_run_id = run.id` + `tasks.completed_at` 写入〔沿用，`decisions.py:54`、`runs.py:529-534`〕 | HTTP `200 {state, statistics}`；数据库 `tasks.state = 'COMPLETED'`、`tasks.completed_at` 非空、`tasks.last_ready_run_id = 本次 run.id`；`decisions.version` 逐次 +1〔沿用，`runs.py:529-534`、`decisions.py:154`〕 |
| **已完成只读** | `tasks.state = 'COMPLETED'`；`tasks.completed_at`；`tasks.last_ready_run_id`；历史 `decisions` + `decision_events`〔沿用，`runs.py:529-531`〕 | 徽章「已完成」；横幅「核对已完成，可以查看历史决定与拒绝原因。」；展示历史决定（已接受/已拒绝 · 原因）；**无**接受/拒绝/重新选择按钮（按钮数为 0）；「完成核对」按钮存在但禁用（`aria-disabled="true"`）并显示原因「核对已完成，当前为只读视图」；但仍保留「查看出处」定位入口〔实测，`fixtures/charter.js` 的 `scenarios.complete`；`workbench.js` 的 `isCompleteMode()`、`decisionOf()`、`completionState()`、`renderHeader()`〕 | 只读：查看历史决定与拒绝原因、点出处定位；不可写决定、不可再次完成 | 已完成态不再接受写入。对 `PATCH .../decision` → `409 TASK_READ_ONLY`〔沿用，`runs.py:420-424`〕。对 `POST /complete`：V1 **没有** `TASK_READ_ONLY` 分支（`runs.py:488-534` 未判 `task.state`），重复完成会重写 `completed_at`；V2 是否新增该拦截待阶段 B 决定〔实测，见 api-contract.md「与 V1 的差异」〕 | HTTP `409 TASK_READ_ONLY`（写决定路径）；数据库 `decisions` 行、`decision_events` 行**均不新增**；`tasks` 行零写入〔沿用，`runs.py:443-444` 先抛错再 commit〕 |

**计数文案口径**（唯一来源：线框 `workbench.js` 的 `progressText()`）〔实测〕

| 段 | 取值 | 说明 |
|---|---|---|
| 已确认 | 「已确认 N / M」 | **M 只计非受影响的摘录项**（`isAffected()` 为真的项不进分母） |
| 受影响 | 「受影响 K 项（无效出处 / 输出截断）」 | 仅覆盖不全场景出现，插在「已确认 N / M」之后 |
| 未找到 | 「未找到 1 项待确认 / 已确认 / 人工核对」 | 「正常未找到」项**不进分母**、单列显示；它仍是 `results` 行，未决定前仍阻塞完成 |

因此正常核对场景的计数为「已确认 N / M · 未找到 1 项待确认」。

**完成原因文案**（唯一来源：线框 `workbench.js` 的 `completionState()`）〔实测〕

| 触发条件 | 原因文案 |
|---|---|
| run 未就绪（处理中） | 「无法完成：核对结果尚未就绪」 |
| 材料缺失 | 「无法完成：材料缺失，完成规则待决策」 |
| 任务已完成（只读视图） | 「核对已完成，当前为只读视图」 |
| 存在受影响检查项 | 「无法完成：N 个检查项覆盖不全（标题列表）」 |
| 有拒绝项未填原因 | 「无法完成：N 项拒绝未填原因」 |
| 摘录项与未找到项均未确认 | 「无法完成：仍有 X 项摘录未确认、Y 项未找到待确认」 |
| 条件全部满足 | 「可完成」 |

X、Y 任一为 0 时，实现只输出单项的「无法完成：仍有 X 项摘录未确认」或「无法完成：仍有 Y 项未找到待确认」〔实测，`workbench.js` 的 `completionState()`〕。

## 三、缺材料的完成规则（待决策，待产品确认）

**状态：未冻结。** 在产品负责人给出结论前，章程核对切片的完成契约无法完整冻结，涉及 api-contract.md 中 `POST /complete` 的错误码集合与数据字典中 `tasks.state` 的终态写法。

| 候选 | 含义 | 对 `POST /complete` 的影响 | 对数据字典的影响 | 对界面的影响 |
|---|---|---|---|---|
| **候选 A** | 缺材料时**禁止完成**，必须补传后重跑 | 需新增一个专门拦截（建议错误码 `MATERIAL_MISSING`，最终定名待阶段 B）；拦截点必须在 `REVISION_CONFLICT` 之后、覆盖与统计判定之前 | 需在 `tasks` 或 run 上留下「材料不完整」的持久标记（当前 V1 无此列） | 完成按钮禁用，原因「无法完成：缺少『公司章程』，请补传后重新核对」 |
| **候选 B** | 允许对已有材料的部分结果完成，并标记「材料不完整」 | 沿用 V1 现状：`material_missing` 不阻断覆盖判定、也不自动阻断 `can_complete`；由人工决定该检查项后即可完成 | 需在 `tasks` 或 run 上落下「材料不完整」的完成标记（当前 V1 无此列） | 完成按钮可用；完成页/回执显示「材料不完整」徽标 |

补充事实（决定该问题难度的关键）：

- V1 中 `material_missing` **不是** `coverage_incomplete`，因此 `compute_coverage_summary` 不会因缺材料而判定覆盖不全〔沿用，`processing_pipeline.py:188-192`〕。即：候选 B 在 V1 语义下天然可达，候选 A 需要 V2 新写拦截逻辑。
- V1 无「材料不完整」的持久标记字段，候选 A/B 都需要 V2 新增落库位置〔实测，`models.py` 全表无此语义列〕。
- 线框当前展示的是候选 A 的界面形态，但文案写明「待决策（待产品确认：是否允许在缺材料状态下完成核对）」，不构成对候选的选择〔实测，`fixtures/charter.js` 的 `scenarios.missing.completionRule`；`workbench.js` 的 `completionState()`〕。

## 四、原型边界

| 项 | 边界 | 阶段 B 归属 |
|---|---|---|
| 原件渲染 | 第 14、15 页是**公开样本的文字坐标线框**，不是真实 PDF 渲染；页面容器用固定比例占位〔实测，`index.html` 的 `#source`；`workbench.css` 的 `aspect-ratio: 1191 / 1684`（`.sheet` 容器）〕 | 真实 PDF 的 zoom / locate / highlight 精度延后到阶段 B，用本地批准样本验证 |
| 坐标来源 | 线框用样本常量 1191 × 1684 px 与固定 bbox 换算百分比〔实测，`fixtures/charter.js` 的 `pageSize`；`workbench.js` 的 `renderSource()`（摘录坐标换算）、`locate()`（高亮框换算）〕 | 阶段 B 改以 `ocr_pages.width_px / height_px` 为准换算，见 data-dictionary.md「页码与坐标约定」 |
| 决定存储 | 决定与完成态只写浏览器 `localStorage`〔实测，`workbench.js` 的 `save()`〕 | 阶段 B 改为 V2 API + 数据库，接口契约见 api-contract.md |
| 材料范围 | 营业执照、审计财报只显示「后续迁移范围」提示，不具备核对能力〔实测，`workbench.js` 的 `bannerText()`、`renderResults()`〕 | 后续迭代 |
| 阶段与进度 | 「处理中」的阶段列表是线框写死的场景数据〔实测，`fixtures/charter.js` 的 `scenarios.processing.processing.stages`〕 | 阶段 B 由 `processing_runs.stage` 与 `run_steps` 驱动 |
| 场景切换 | 顶部「评审场景」下拉是评审专用控件，正式形态由后端状态推导 | 阶段 B 移除 |

## 五、点击行为分工

| 动作 | 结果 | 不做什么 |
|---|---|---|
| 点击检查项标题（`data-action="select"`） | 选中该卡片，右栏滚动到该卡片并聚焦 | **不**移动左栏、不翻页、不画高亮〔实测，`workbench.js` 的 `selectCard()` 与 `data-action="select"` 分支〕 |
| 点击摘录正文（`data-action="select"`） | 同上（同一动作路径） | 同上〔实测，`workbench.js` 的 `cardHtml()`（摘录正文按钮同样带 `data-action="select"`）、`#results` 的点击委托〕 |
| 点击「查看出处 · 第 N 页」（`data-action="locate"`） | 左侧翻到第 N 页、画出高亮框、右上角显示「已定位第 N 页」 | 不改变决定状态〔实测，`workbench.js` 的 `locate()`、`data-action="locate"` 分支〕 |
| 点击「接受」 | 写入接受决定，计数 +1 | 不移动左栏〔实测，`workbench.js` 的 `data-action="accept"` 分支〕 |
| 点击「拒绝」 | 展开原因输入框并自动聚焦 | 不移动左栏〔实测，`workbench.js` 的 `data-action="reject"` 分支与 `cardHtml()` 的拒绝原因表单〕 |
| 点击「下一条待办」 | 右栏聚焦到下一个未处理项 | 不移动左栏〔实测，`workbench.js` 的 `#next` 点击处理〕 |

**分工原则**：「定位原件」是**唯一**由出处入口驱动的动作；检查项标题与摘录只负责右栏内的选择与聚焦。左栏只在用户显式要求看原件时才动。这样做的原因：右栏是核对主流程，左栏是佐证视图；若点击摘录就抢走左栏焦点，逐条核对时原件会不停跳动，无法与摘录并读。

## 六、待产品确认的开放问题

| # | 问题 | 影响的规格 | 现状 | 阻塞项 |
|---|---|---|---|---|
| 1 | 缺材料时的完成规则（候选 A 禁止完成 / 候选 B 允许部分完成并标记「材料不完整」） | 第二节「缺材料」行、第三节、api-contract.md 的 `POST /complete` 错误码集合、data-dictionary.md 的 `tasks` 完成标记 | 线框展示候选 A 形态，标注待决策 | 契约无法完整冻结 |
| 2 | 「正常未找到」项是否计入「已确认 N / M」 | 第二节「正常未找到」行、第二节计数文案口径、右栏计数文案 | 线框**不计入**分母（M 只计非受影响的摘录项）、单独显示「未找到 1 项待确认」〔实测，`workbench.js` 的 `progressText()`〕，但该项仍需做决定才能完成 | 计数文案与统计口径的表达方式 |
| 3 | 覆盖不全中的受影响项：**接口层是否仍接受针对受影响 result 的决定写入** | 第二节「覆盖不全」行的「允许操作」；api-contract.md 第四节的写决定语义 | 线框**不提供**接受/拒绝入口（受影响卡片只有状态竖条、标签与「查看出处」），受影响项不计入计数、不进入待办序列〔实测，`workbench.js` 的 `cardHtml()`（决定动作仅在 `editable() && !affected` 时渲染）〕；**接口层当前立场是允许写入**（沿用 V1 语义，无此校验），完成判定仍被覆盖事实 `processing_runs.coverage_complete` 拦截〔沿用，`runs.py:506-518`〕 | 是否在接口层禁止写入受影响项 |
| 4 | 已完成任务再次调用 `POST /complete` 的行为 | 第二节「已完成只读」行、api-contract.md | V1 无该拦截分支，重复完成会重写 `completed_at`〔实测，`runs.py:488-534`〕 | 是否新增 `409 TASK_READ_ONLY` |

## 七、尚未验证清单（交给阶段 B）

1. 真实 PDF 的页码定位与高亮精度（当前只有坐标线框）。
2. `source_page_number` 与上传文件物理页号的一致性（V1 从未验证，`mapping_status` 恒 `unverified`）。
3. 缺材料场景下 `POST /complete` 的实际响应体与错误码（待问题 1 决策）。
4. 受影响项的决定写入路径：线框当前**不提供**接受/拒绝入口〔实测〕，接口层是否接受针对受影响 result 的写入待产品确认（见问题 3）。
5. 「正常未找到」项在统计中的最终口径（待问题 2 决策）；线框计数口径已定（M 只计非受影响的摘录项，该项单列显示）。
