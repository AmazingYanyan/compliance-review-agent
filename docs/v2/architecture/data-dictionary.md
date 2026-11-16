# 核心数据字典 · V1 源码盘点及 V2 草案

核对源为 [V1 models.py](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/models.py) 和 [Alembic](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/alembic/versions/)。下表写业务关系；数据库物理外键、索引和唯一约束以对应迁移为准。V2 迁移尚待实现。

| 实体或 V1 表 | 核心字段／关系 | V2 交付关注 |
|---|---|---|
| `tasks` | `id`，所有者字段，`state`，`input_revision` | 权属、输入变更版本、完成的 run |
| `task_files` | 文件身份对应任务，分类、资产引用 | 补传、替换及删除的生效边界 |
| `ocr_jobs / ocr_pages / ocr_blocks` | 作业、原文页和 OCR 文本块，物理页码与 bbox | 原文件位置可复现，页序和坐标约定 |
| `processing_runs / run_files / run_steps` | 运行按任务及输入版本归属，记录材料快照、状态、覆盖及步骤 | 避免补跑覆盖其他 run；覆盖需能追溯到检查项及窗口 |
| `results / result_sources` | 摘录绑定 run 和检查项，来源带文件、页码及 bbox | 保留有效摘录与出处，区分无匹配、缺材料、覆盖不全 |
| `decisions / decision_events` | 按结果保存人工决定、拒绝原因及事件 | 记录决定归属；任务输入已变更时避免写入旧结果 |
| `users / auth_sessions` | 账户和会话 | 验证任务及文件跨账号隔离 |

首轮迁移补齐落地字段的类型、空值与默认值、约束、状态流转、敏感级别，保留可从空库执行的迁移。新增良好数据和故障测试时，再补对应字典行。
