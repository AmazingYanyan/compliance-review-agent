# 当前状态

分支 `v2/workbench`，V1 基线 `e52520553f3efe8e790fb608e630bf29bab9c1bf`（历史沿用）。

## 本阶段进展（阶段 A 已交付）

- 章程核对工作台线框已改造并在真实 Chrome 中逐项验收：六种评审场景、受影响项标记、完成入口原因、点击分工、左栏翻页与缩放、已完成只读态、共用样式令牌。
- 规格与契约已冻结或更新：状态表、接口契约、落库数据字典、V1 复用评估、验证口径。
- **V2 后端、数据库迁移与接口尚未实现**，本轮不涉及。

## 最新实测结果（本轮实测，2026-11-16 ~ 2026-11-17）

- **浏览器（chrome-devtools MCP，Chrome，1440×900）**：六种场景逐项读 DOM 核对 —— 正常核对「已确认 0 / 4 · 未找到 1 项待确认」、处理中（阶段 OCR 完成 → 文本分窗 → 检索摘录（进行中），页码控件禁用）、缺材料（缺少「公司章程」）、覆盖不全·无效出处（受影响 = 担保规模限制）、覆盖不全·输出截断（受影响 = 担保事项批准权 + 对外担保例外）、已完成只读（已确认 4 / 4 · 未找到 1 项人工核对，只剩「查看出处」与选中动作）。
- **完整路径**：下一条待办 → 聚焦 e1 且左栏未动 → 查看出处 → 「已定位第 14 页」并画出高亮 → 点 e3 正文只选中 e3、左栏滚动位置不变 → 拒绝（输入框自动聚焦，空白与纯空格时「保存拒绝」禁用，填写后可保存「已拒绝 · …」）→ 全部确认后计数「已确认 4 / 4」、原因「可完成」、下一条待办禁用 → 完成 → 只读 → 刷新后历史决定与拒绝原因仍在、接受/拒绝按钮数为 0。
- **语法检查**：`node --check` 通过 `workbench.js` 与 `fixtures/charter.js`。
- **控制台**：整轮仅存在 favicon 404，已加 `<link rel="icon" href="data:,">` 消除。
- **环境**（本轮实测，推翻上一轮记录）：Docker 29.8.0 + Compose v5.5.1 可用，`postgres:18` 镜像本地已有；V1 compose 项目 `credit-review-app` 仍在运行，其卷保持不动；Figma Desktop 在运行但 Dev Mode MCP 端口未监听、且本环境未注册 Figma MCP 工具，**读选中 Frame 的检查未能执行**，本轮改用浏览器线框；git 到 github.com 的传输曾因 DNS 多址部分不可达失败，本地绕过命令见[开发索引 · 故障定位](DEVELOPMENT_INDEX.md)。

## 待办

- 阶段 B 落地：V2 独立 Compose 项目 → 空库迁移 → 三个端点 → 四个验收用例。
- 真实 PDF 的缩放、定位与高亮精度用本地批准样本验证（当前只是文字坐标线框）。
- 产品确认两个开放问题：①「正常未找到」是否计入「已确认 N / M」；②缺材料时的完成规则（禁止完成 / 允许部分完成并标记「材料不完整」）。
- V1 `task.input_revision` 从不自增，V2 需自行实现补传/替换/删除时的 +1 与 stale 判定。

## 阻塞

- 缺材料完成规则未决 → `POST /complete` 的错误码集合与完成标记的落库位置无法冻结（见[章程规格 · 第三节](v2/requirements/charter.md)）。
- Figma 选中 Frame 读取不可用，评审结论只覆盖浏览器表现。
- V1 侧待确认：`carried_from_result_id`、`SUPERSEDED`、孤儿表（`check_executions` / `view_states`）均无写入路径，V2 需自行实现。

## 接手第一步（阶段 B）

1. 起 V2 独立 Compose 项目：`credit-review-app-v2/compose.yml`，项目名 `credit-review-v2`，独立库名与卷；**不碰** V1 的 `credit-review-app` 项目与卷。
2. 从空库执行四个迁移（任务/文件/资产 → OCR 表 → run/result 表 → decisions 表）。
3. 实现三个端点：`GET /api/v2/tasks/{task_id}/workbench`、`PATCH /api/v2/tasks/{task_id}/results/{result_id}/decision`、`POST /api/v2/tasks/{task_id}/complete`。
4. 跑四个验收用例（正常完成、非法出处、输出截断、原件定位），每例取三条独立证据：前端按钮禁用、实际 HTTP 响应、数据库写入状态。

## 相关文档

- 本轮记录：[2026-11-16-02-phase-a.md](v2/sessions/2026-11/2026-11-16-02-phase-a.md) · 上轮记录：[2026-11-16-01-design.md](v2/sessions/2026-11/2026-11-16-01-design.md)
- 规格与契约：[状态表](v2/requirements/charter.md) · [接口契约](v2/architecture/api-contract.md) · [数据字典](v2/architecture/data-dictionary.md) · [V1 复用评估](v2/architecture/v1-reuse.md)
- 验证与复跑：[验证口径](v2/verification/charter.md) · [开发索引](DEVELOPMENT_INDEX.md) · [隔离部署决策](v2/decisions/001-isolate-v2-data.md)
