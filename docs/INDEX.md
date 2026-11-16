# 文档索引

| 文档 | 适用阶段 | 概要 | 读完可获得 |
|---|---|---|---|
| [当前状态](STATUS.md) | V2 当前 | 本轮进展、实测结果、待办与接手第一步 | 交付阶段和接续动作 |
| [开发索引](DEVELOPMENT_INDEX.md) | V1 与 V2 | 线框入口与命令、模块职责、元素 id 速查、故障定位 | 工程入口、数据库和复跑路径 |
| [章程核对规格](v2/requirements/charter.md) | 阶段 A 已更新 | 六种状态表、点击分工、原型边界、开放问题 | 交互、状态与预期完成条件 |
| [接口契约](v2/architecture/api-contract.md) | 阶段 B 实现依据 | 三个端点、覆盖事实源规则、错误码总表、检查顺序 | 阶段 B 写接口时可直接对照的字段、判定顺序与零写入要求 |
| [数据字典](v2/architecture/data-dictionary.md) | 阶段 A 已更新 | V2 落库范围、表结构、归属规则、覆盖与坐标口径 | V2 落库范围与归属规则 |
| [V1 复用评估](v2/architecture/v1-reuse.md) | 阶段 A 盘点 | 七个复用候选的采用方式、缺口与阶段 B 复验口径 | 哪些 V1 实现可迁、迁到什么程度、怎样复验 |
| [隔离部署决策](v2/decisions/001-isolate-v2-data.md) | 阶段 B | 端口、卷、迁移和验收边界 | V2 独立环境的边界与启动条件 |
| [章程验证](v2/verification/charter.md) | 阶段 A 已验 / 阶段 B 待验 | 浏览器验收逐条实测结果、阶段 B 四类用例与三条独立证据 | 在浏览器复验设计，以及联调验收口径 |
| [会话记录](v2/sessions/2026-11/README.md) | V2 | 按月查看开发会话及证据 | 按月查看开发会话及证据 |
| [旧版资料索引](legacy/INDEX.md) | V1 历史 | 原路径与固定提交取法 | 原路径、迁移路径与旧提交 |

本轮（2026-11-16 第二轮）新增[接口契约](v2/architecture/api-contract.md)、[V1 复用评估](v2/architecture/v1-reuse.md)；更新[章程核对规格](v2/requirements/charter.md)（状态表）、[数据字典](v2/architecture/data-dictionary.md)（V2 落库范围与归属规则）、[章程验证](v2/verification/charter.md)（阶段 A 实测与阶段 B 待验）。单轮记录见 [2026-11-16-02-phase-a.md](v2/sessions/2026-11/2026-11-16-02-phase-a.md)。

**证据标注约定**：本文所链接文档中的结论统一标注〔本轮实测〕/〔历史沿用〕/〔尚未验证〕，并附命令或证据路径；标注含义见[V1 复用评估](v2/architecture/v1-reuse.md)第零节与[章程核对规格](v2/requirements/charter.md)第零节（后者写作〔实测〕/〔沿用〕/〔待验〕，含义一一对应）。
