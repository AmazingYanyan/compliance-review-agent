# V2 章程核对工作台 · 阶段 A 设计评审与契约冻结 Spec

## Why

仓库 `v2/workbench` 已有章程核对双栏线框、文档索引、开发索引、数据字典草案和独立 Compose 数据库骨架，但线框从未在真实浏览器里被完整操作过：五种状态的界面差异不足、覆盖不全场景无法区分受影响项、顶部没有任务与状态、检查项点击与出处点击行为未定义、共用样式未收敛。同时 V1 已有可复用的决策与完成契约（`409 COVERAGE_INCOMPLETE` / `409 NOT_COMPLETE` / `409 REVISION_CONFLICT`、覆盖唯一事实源 `ProcessingRun.coverage_complete`、拒绝原因完成前必填），但尚未被整理成 V2 可直接实现的接口契约与数据字典。

因此本轮只做阶段 A：把线框改到可评审状态、在浏览器里实测并留证、冻结状态表与接口契约草案、把 V2 落地数据字典收敛到本轮实际范围。真实 API、数据库迁移与端到端验收留给阶段 B。

## What Changes

- **接手核对与运行事实入档**：记录远端 `v2/workbench` 的实际 SHA、本地接续方式、浏览器/Docker/Figma 可达性实测结果，以及 V1 工作树恢复方式。
- **线框功能补齐（非 BREAKING）**：顶部任务与状态条；覆盖不全场景的「受影响项」逐条标记；完成入口禁用原因提示；检查项点击与出处点击行为分工；左栏跳页与缩放控件（线框级）；处理中/缺材料场景的状态信息与补传入口占位；已完成只读态区分未找到项并展示历史决定与拒绝原因。
- **共用样式收敛**：字号、间距、表格密度、状态色、按钮层级抽到一组 CSS 变量与共用类，状态色在横幅、徽标、卡片竖条三处一致。
- **契约冻结**：`docs/v2/requirements/charter.md` 扩为状态表（5 场景 × 数据来源/界面/操作/完成规则/联调预期），缺材料完成规则列为待决策；新增接口契约草案文档（端点、请求响应、错误码）。
- **数据字典收敛**：`docs/v2/architecture/data-dictionary.md` 落到章程核对实际用到的表，区分业务归属与数据库实际约束，写清迁移路径与「重跑/补传/替换文件后旧摘录与人工决定的归属与展示」。
- **V1 复用评估入档**：记录 OCR 规范化、页码坐标约定、稳定分窗、并发派发、证据去重、任务文件管理、固定测试样本各自的采用方式、调整原因与复验方式。
- **文档与交接**：`docs/INDEX.md`、`docs/DEVELOPMENT_INDEX.md`、`docs/STATUS.md`、本轮会话记录、验收说明同步更新；重复的工作台验收流程沉淀为一个可复用 Skill。
- **提交与推送**：本轮工程变更提交并推送到 `v2/workbench`，核对远端 SHA。

不在本轮范围：V2 后端代码、数据库迁移、真实 OCR/模型调用、Docker 起 V2 API、营业执照与财报链路、任务与材料管理界面。

## Impact

- Affected specs: `docs/v2/requirements/charter.md`（状态表与交互规格）、`docs/v2/architecture/data-dictionary.md`（落库范围与归属规则）、新增 `docs/v2/architecture/api-contract.md`（接口契约草案）、`docs/v2/verification/charter.md`（浏览器验收口径）、`docs/INDEX.md`（导航）、`docs/DEVELOPMENT_INDEX.md`（工程入口）、`docs/STATUS.md`（当前快照）
- Affected code: `credit-review-app-v2/prototype/index.html`、`credit-review-app-v2/prototype/workbench.js`、`credit-review-app-v2/prototype/workbench.css`、`credit-review-app-v2/prototype/fixtures/charter.js`、`credit-review-app-v2/compose.yml`（仅核对，不改）、`.gitignore`（排除本地 V1 工作树）
- Affected runtime: 静态预览 `http://127.0.0.1:8092`（`python3 -m http.server 8092 --bind 127.0.0.1 --directory credit-review-app-v2/prototype`）；V1 Compose 项目 `credit-review-app` 保持运行，不做任何改动
- Affected external: 无新外部依赖；不引入 Figma 依赖（Figma MCP 本轮不可达）

## ADDED Requirements

### Requirement: 接手核对与环境事实记录

系统 SHALL 在本轮会话记录中写明接手核对结果，作为后续轮次的接续依据。

#### Scenario: 远端与本地接续一致
- **WHEN** 核对 `origin/v2/workbench` 的 HEAD
- **THEN** 结果为 `d0d1c58a07d954454f7b99797ce1c0ef0a32abde`，与交接给出的 SHA 一致；本地分支 `v2/workbench` 从 `main`（`e52520553f3efe8e790fb608e630bf29bab9c1bf`）切出并跟踪远端同名分支

#### Scenario: 环境能力实测入档
- **WHEN** 记录本轮可用能力
- **THEN** 至少写明：Docker 29.8.0 与 Compose v5.5.1 可用、V1 容器 `credit-review-app-api-1/worker-1/db-1` 运行中保留、`postgres:18` 镜像本地已有；Figma Desktop 126.11.8 在运行但本地 MCP 端口不可达、无法读取选中 Frame；chrome-devtools MCP 可用于浏览器实测；git 传输层曾因 `github.com` DNS 命中不可达地址失败及本地绕过方式

#### Scenario: V1 工作树可继续使用
- **WHEN** 需要查阅或复跑 V1
- **THEN** V1 应用源码可从固定提交 `e525205` 取回，且本地 V1 目录不被 V2 发布树纳入提交

### Requirement: 顶部任务与状态条

工作台 SHALL 在顶部固定区域展示任务身份与当前状态，并作为完成动作的宿主。

#### Scenario: 展示任务与状态
- **WHEN** 打开任一状态
- **THEN** 顶部显示任务名、客户角色、状态徽标（正常核对 / 处理中 / 缺材料 / 覆盖不全 / 已完成）、进度「已确认 N / M」、输入版本号；「完成核对」按钮位于该区域

#### Scenario: 状态色一致
- **WHEN** 状态为覆盖不全或缺材料
- **THEN** 顶部徽标、横幅、卡片竖条使用同一组状态色变量；已完成使用成功色，拒绝使用危险色

### Requirement: 覆盖不全的受影响项标记

覆盖不全场景 SHALL 逐条标记受影响检查项，使业务员知道哪一条不能作为有效摘录。

#### Scenario: 无效出处场景
- **WHEN** 场景为「覆盖不全 · 无效出处」
- **THEN** 受影响检查项卡片出现状态竖条与「受影响 · 无效出处」标签，横幅列出受影响项标题与原因；其余检查项仍按正常摘录展示并可接受或拒绝

#### Scenario: 输出截断场景
- **WHEN** 场景为「覆盖不全 · 输出截断」
- **THEN** 受影响项与「受影响 · 输出截断」标签按固定样本标注，且与无效出处场景的受影响项集合不同

#### Scenario: 覆盖不全仍可处理有效摘录
- **WHEN** 覆盖不全场景中某条摘录有效
- **THEN** 该条仍可接受或拒绝并保留决定，不因整体覆盖不全而不可操作

### Requirement: 完成入口的禁用原因提示

完成入口 SHALL 在不可完成时说明原因，而不只把按钮置灰。

#### Scenario: 覆盖不全导致不可完成
- **WHEN** 当前 run 覆盖不全
- **THEN** 「完成核对」处于禁用态，紧邻位置显示「无法完成：N 个检查项覆盖不全」并列出受影响项标题；禁用态可被辅助技术读取（`aria-disabled` + 说明文本）

#### Scenario: 仍有未确认项
- **WHEN** 仍有检查项未确认，或存在拒绝但未填原因
- **THEN** 提示文案区分「未确认 N 项」与「拒绝未填原因 M 项」，与完成接口的错误口径一致

#### Scenario: 正常完成后只读
- **WHEN** 完成成功
- **THEN** 页面进入只读态：展示历史决定与拒绝原因，隐藏接受/拒绝/重选入口，完成入口不可再次触发

### Requirement: 检查项与出处的交互分工

系统 SHALL 明确区分「点击检查项」与「点击出处」两类行为。

#### Scenario: 点击检查项
- **WHEN** 用户点击检查项标题或摘录正文
- **THEN** 该项进入选中态（左侧竖条与焦点环可见），右栏滚动到该项并聚焦，不改变左侧原件位置

#### Scenario: 点击出处
- **WHEN** 用户点击「查看出处 · 第 N 页」
- **THEN** 左侧原件跳转到该页并高亮对应坐标区域，顶部页码显示已定位页码；这是唯一驱动原件定位的动作

#### Scenario: 下一条待办
- **WHEN** 用户点击「下一条待办」
- **THEN** 从当前项之后开始查找首个未处理项并聚焦之；已处理项跳过；到达末尾后循环回到开头；全部处理完毕后该入口禁用

### Requirement: 原件定位控件（线框级）

原件预览区 SHALL 提供跳页与缩放控件，用于评审定位与缩放交互。

#### Scenario: 跳页与缩放控件可用
- **WHEN** 场景为可预览状态
- **THEN** 左栏顶部提供上一页/下一页、页码输入与缩放档位（适应宽度 / 100% / 150% / 200%），缩放作用于当前文字坐标线框

#### Scenario: 原型边界声明
- **WHEN** 缩放或跳页作用于第 14、15 页文字坐标线框
- **THEN** 界面明确标注「原型边界：文字坐标线框，非真实 PDF 渲染」，真实 PDF 缩放、定位与高亮精度标注为阶段 B 待验证

### Requirement: 状态表与接口契约

`docs/v2/requirements/charter.md` SHALL 给出五场景状态表，`docs/v2/architecture/api-contract.md` SHALL 给出接口契约草案，二者 SHALL 与数据字典互相一致。

#### Scenario: 状态表字段完整
- **WHEN** 查看状态表
- **THEN** 每个场景含：数据来源、界面表现、允许操作、完成规则、联调预期；缺材料场景的完成规则标记为待决策并列出候选口径

#### Scenario: 接口契约覆盖错误码
- **WHEN** 查看接口契约
- **THEN** 至少覆盖：读取工作台、写入决定、完成任务三类端点，并写明 `409 RUN_NOT_READY`、`409 TASK_READ_ONLY`、`409 REVISION_CONFLICT`、`409 COVERAGE_INCOMPLETE`、`409 NOT_COMPLETE`、`422 INVALID_DECISION` 的触发条件与响应结构

#### Scenario: 决定写入约束一致
- **WHEN** 写入非拒绝决定却携带拒绝原因
- **THEN** 契约规定返回 `422 INVALID_DECISION`；拒绝原因为空允许作为草稿，但完成前必须非空，与 V1 现有实现语义一致

### Requirement: V2 落库数据字典范围

数据字典 SHALL 覆盖章程核对实际用到的表，并写明用途、关键字段类型、可空性、默认值、主键、外键与唯一约束、状态含义、迁移路径。

#### Scenario: 核心实体齐备
- **WHEN** 查看数据字典
- **THEN** 覆盖任务与材料、文件与版本（含补传后 `input_revision` 变化）、OCR 作业与原文页与文本块（含页码与坐标约定）、处理批次与材料快照与检查项与窗口覆盖、摘录与有效出处、人工决定、完成状态

#### Scenario: 归属与展示规则明确
- **WHEN** 查看「重跑、补传、替换文件」后的归属说明
- **THEN** 写明旧摘录与旧人工决定归属哪个 run、如何标记为过期、界面如何展示，以及与 `input_revision` 和 `REVISION_CONFLICT` 的关系

#### Scenario: 区分业务归属与数据库约束
- **WHEN** 查看表定义
- **THEN** 每张表分别列出业务归属规则与数据库实际约束（主键、外键、唯一），迁移路径写明是 V2 新建迁移还是复用 V1 迁移思路

### Requirement: V1 复用评估记录

开发索引 SHALL 记录本轮对 V1 模块的采用方式、调整原因与复验方式。

#### Scenario: 复用结论可追溯
- **WHEN** 查看开发索引的复用记录
- **THEN** 至少覆盖 OCR 规范化、页码与坐标约定、稳定分窗、并发派发、证据去重、任务与文件管理、固定测试样本；每项写明采用方式（直接复用 / 抽取后复用 / 重做）、为何调整、怎样复验

### Requirement: 文档索引与状态快照同步

本轮结束时 SHALL 更新文档索引、开发索引、当前状态与本轮会话记录，并标注结论的实测属性。

#### Scenario: 结论标注实测属性
- **WHEN** 查看文档中的验证结论
- **THEN** 明确标注「本轮实测」「历史沿用」或「尚未验证」，并附命令与证据路径

#### Scenario: 状态页给出接手第一步
- **WHEN** 打开 `docs/STATUS.md`
- **THEN** 写明当前阶段进展、最新实测结果、待办、阻塞项与接手第一步，并链接本轮记录

#### Scenario: 可复用验收 Skill
- **WHEN** 重复执行工作台验收
- **THEN** 可按仓库内可复用 Skill 的步骤执行，其中链接实际启动命令、样本路径与预期结果

## MODIFIED Requirements

### Requirement: 工作台线框入口与演示范围

线框 SHALL 在保留现有文件路径与本地启动方式的前提下，覆盖更多可评审状态，且不再把浏览器本地存储当作决定来源的正式实现。

#### Scenario: 启动方式不变
- **WHEN** 按 README 运行 `python3 -m http.server 8092 --bind 127.0.0.1 --directory credit-review-app-v2/prototype`
- **THEN** 浏览器打开 `http://127.0.0.1:8092` 可见新版工作台，无需构建步骤

#### Scenario: 决定来源的定位
- **WHEN** 评审者看到接受/拒绝状态
- **THEN** 界面标注「演示态：决定保存在浏览器本地」，真实决定以阶段 B 的接口与数据库为准

#### Scenario: 材料范围不变
- **WHEN** 切换到营业执照或审计财报页签
- **THEN** 仍显示属于后续迁移范围的提示，不实现上传与核对该材料

### Requirement: 共用样式收敛

线框 SHALL 使用一组共用样式变量与共用类，而不是各元素裸写数值。

#### Scenario: 变量集中
- **WHEN** 查看样式表
- **THEN** 字号、间距、状态色、按钮层级、表格密度均有命名的共用定义；卡片、表格行、按钮、徽标复用同一套类名

#### Scenario: 同窗口尺寸集中对比
- **WHEN** 在同一浏览器窗口尺寸下切换五个场景
- **THEN** 字号、间距、表格密度、状态色与按钮层级保持一致，不随场景跳变

## REMOVED Requirements

### Requirement: 以浏览器本地存储作为决定来源

**Reason**: 本地存储只是阶段 A 的演示手段，无法满足「决定可追溯、可刷新回看、完成后只读、数据库零写入验证」等阶段 B 验收要求；保留会造成口径混淆。

**Migration**: 决定在阶段 B 由 `PATCH .../decision` 写入 V2 数据库，页面读取工作台接口返回的权威状态；线框在阶段 B 前继续以本地存储演示，并在界面标注演示态。

### Requirement: 覆盖不全场景仅靠横幅文案表达

**Reason**: 两个覆盖不全场景的卡片内容完全相同，受影响项无法区分，业务员无法判断哪一条摘录不可用。

**Migration**: 改为逐条「受影响」标记加完成入口原因提示，受影响项集合由固定样本中的固定响应定义，阶段 B 由 run 的覆盖事实驱动。
