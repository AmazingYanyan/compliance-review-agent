# Tasks

阶段 A 交付：线框可评审 + 契约冻结 + 文档同步 + 提交推送。

- [x] Task 1: 接手核对与环境事实入档
  - [x] SubTask 1.1: 写接手核对结果：远端 `v2/workbench` SHA 核对、本地从 `main` 切出方式、V1 工作树从固定提交恢复方式、`.gitignore` 排除本地 V1 目录
  - [x] SubTask 1.2: 写环境能力实测：Docker/Compose 版本与 V1 容器状态、postgres:18 镜像、Figma MCP 不可达的探测命令与结果、chrome-devtools 可用、git 传输层故障与本地绕过命令
  - [x] SubTask 1.3: 写浏览器基线实测：五场景切换、「下一条待办」序列（e3→e4→not-found→回绕）、拒绝原因为空时保存禁用、完成后只读与历史决定展示；附已发现的线框缺陷清单

- [x] Task 2: 线框功能补齐与共用样式收敛
  - [x] SubTask 2.1: 建立共用样式变量：字号阶梯、间距阶梯、状态色（正常/处理中/缺材料/覆盖不全/成功/危险）、按钮层级（primary/secondary/ghost/danger）、表格行密度；卡片、表格行、徽标、按钮改用共用类
  - [x] SubTask 2.2: 顶部任务与状态条：任务名、客户角色、状态徽标、进度「已确认 N / M」、输入版本号；「完成核对」迁入该区域
  - [x] SubTask 2.3: 覆盖不全受影响项标记：卡片竖条 + 「受影响 · 无效出处 / 输出截断」标签；横幅列出受影响项；两个场景受影响项集合不同（固定样本中调整）
  - [x] SubTask 2.4: 完成入口禁用原因提示：区分「未确认 N 项」「拒绝未填原因 M 项」「N 个检查项覆盖不全」并列出受影响项标题，按钮 `aria-disabled` + 可读说明
  - [x] SubTask 2.5: 交互分工：点击检查项标题/正文 = 选中 + 右栏聚焦（不动左侧）；点击「查看出处」= 唯一驱动左侧跳页与高亮；实现「下一条待办」向后查找 + 循环 + 跳过已处理项
  - [x] SubTask 2.6: 左栏跳页与缩放控件：上一页/下一页/页码输入 + 缩放档位（适应宽度/100%/150%/200%）；标注「原型边界：文字坐标线框，非真实 PDF 渲染」
  - [x] SubTask 2.7: 处理中与缺材料场景补状态信息：处理中显示阶段与进度说明；缺材料显示缺哪份材料 + 补传入口占位（不实现上传），完成规则标注待决策
  - [x] SubTask 2.8: 已完成只读态：区分「正常未找到」项、展示历史决定与拒绝原因、隐藏决定入口、界面标注演示态（决定存浏览器本地）

- [x] Task 3: 契约与数据字典冻结
  - [x] SubTask 3.1: 扩写 `docs/v2/requirements/charter.md` 为五场景状态表（数据来源/界面表现/允许操作/完成规则/联调预期），缺材料完成规则列为待决策并列候选口径
  - [x] SubTask 3.2: 新增 `docs/v2/architecture/api-contract.md`：读取工作台、写入决定、完成任务三类端点的请求/响应/错误码，覆盖 `RUN_NOT_READY`、`TASK_READ_ONLY`、`REVISION_CONFLICT`、`COVERAGE_INCOMPLETE`、`NOT_COMPLETE`、`INVALID_DECISION`
  - [x] SubTask 3.3: 更新 `docs/v2/architecture/data-dictionary.md`：章程核对实际落库表清单 + 字段类型/可空/默认值/主键/外键/唯一 + 状态含义 + 迁移路径；页码与坐标约定；重跑/补传/替换文件后旧摘录与旧决定的归属与展示
  - [x] SubTask 3.4: 在数据字典与接口契约中写明覆盖唯一事实源为 `processing_runs.coverage_complete`，完成接口只读该字段，不在 API 侧反推

- [x] Task 4: V1 复用评估记录
  - [x] SubTask 4.1: 逐项写明 OCR 规范化、页码与坐标约定、稳定分窗、并发派发、证据去重、任务与文件管理、固定测试样本的采用方式、调整原因、复验方式
  - [x] SubTask 4.2: 标注 V1 固定提交与文件路径引用，注明 V1 容器与数据卷保持不动

- [x] Task 5: 文档与交接
  - [x] SubTask 5.1: 更新 `docs/INDEX.md`（新增接口契约分类与适用阶段、读完可获得）
  - [x] SubTask 5.2: 更新 `docs/DEVELOPMENT_INDEX.md`（线框入口、预览命令、复用记录、故障定位入口）
  - [x] SubTask 5.3: 更新 `docs/STATUS.md`（本阶段进展、最新实测、待办、阻塞、接手第一步）
  - [x] SubTask 5.4: 写本轮会话记录 `docs/v2/sessions/2026-11/2026-11-16-02-phase-a.md` 并登记到当月索引
  - [x] SubTask 5.5: 更新 `docs/v2/verification/charter.md` 验收口径，标注本轮实测项与阶段 B 待验项
  - [x] SubTask 5.6: 沉淀可复用验收 Skill（含启动命令、样本路径、预期结果），并在开发索引中链接

- [x] Task 6: 浏览器复验与提交推送
  - [x] SubTask 6.1: 在真实浏览器重跑六场景与完整路径（找待办 → 查看出处 → 跳页高亮 → 接受或拒绝 → 下一条 → 完成），记录控制台错误；另由独立浏览器会话复验，六项 PASS
  - [x] SubTask 6.2: 检查整个工作树与 staged diff，排除凭据、运行产物、他人改动与未脱敏日志
  - [x] SubTask 6.3: 提交并推送到 `v2/workbench`，核对 GitHub 上远端分支 SHA 与提交信息

# Task Dependencies

- Task 1 → Task 2（先有基线与缺陷清单再改线框）
- Task 2 → Task 3（线框实际交互确定后才冻结契约与字典）
- Task 1 → Task 4（复用评估基于接手核对与 V1 盘点）
- Task 3 → Task 5（文档引用契约与字典）
- Task 4 → Task 5
- Task 2 → Task 6.1（复验改后的线框）
- Task 5 → Task 6.2
- Task 6.1、Task 6.2 → Task 6.3
