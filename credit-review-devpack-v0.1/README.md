# 信贷资料核对：本地 Agent 开发包 V0.1

日期：2026-11-05（北京时间）。需求基线：V0.5。本包用于指导本地 Agent 实现网站，包含规范、契约、提示词、测试样本和页面参考；不包含已经实现、联调或部署成功的网站。

## 给使用者

把本目录整体交给本地 Agent，先发送 `START_HERE.md` 中的启动指令。不要只交单份需求，也不要把旧 Figma 演示逻辑当作后端实现。

已定：Mac 优先，最多5人同时使用；多账号数据隔离；Python/FastAPI + React/TypeScript + PostgreSQL；优先改造官方全栈模板，沿用 shadcn/ui；数据库与文件持久化；本期只启用借款人，保证人、抵（质）押人按钮置灰；真实外网 OCR 与阿里云兼容 LLM；任务未完成前支持补传、删除、更换及分类纠正；完成后只读。

Figma 用于理解意图，允许优化外观，功能与数据规则以本包为准。原型入口：[Figma](https://www.figma.com/design/wrLiqzzq4ypXlcKvgPrvjG?node-id=155-1161)。本地 Agent 不需要具备 Figma 权限，`assets/ui/` 已附页面参考。

## 阅读顺序

| 文件 | 用途 |
| --- | --- |
| [START_HERE.md](START_HERE.md) | 可直接复制给本地 Agent 的首条指令 |
| [AGENTS.md](AGENTS.md) | 开发边界、必须保持的约束、交付证据 |
| [CONTEXT.md](CONTEXT.md) | 统一术语 |
| [docs/01_requirements.md](docs/01_requirements.md) | 完整需求 V0.5，含历次已确认核对规则 |
| [docs/02_architecture.md](docs/02_architecture.md) | 选型、模块、部署拓扑、异步流程与重启恢复 |
| [docs/03_data_model.md](docs/03_data_model.md) | 表、字段、关系、索引、事务及版本约束 |
| [docs/04_api.md](docs/04_api.md) | HTTP 行为、错误、文件操作与并发约定 |
| [contracts/openapi.json](contracts/openapi.json) | OpenAPI 3.1 开发契约；实现后与 FastAPI 生成契约核对 |
| [docs/05_ocr_llm.md](docs/05_ocr_llm.md) | 真实 OCR 样本映射、图片归档、证据、长文与模型调用 |
| [prompts/](prompts/) / [contracts/](contracts/) | 提示词、清单和模型输出 Schema |
| [docs/06_frontend.md](docs/06_frontend.md) | 页面、组件复用、状态、定位与响应式 |
| [docs/07_local_ops.md](docs/07_local_ops.md) | 本地启动目标、配置、备份、恢复和跨平台迁移 |
| [docs/08_delivery_plan.md](docs/08_delivery_plan.md) | 分阶段实施及每阶段退出条件 |
| [docs/09_acceptance.md](docs/09_acceptance.md) | 验收矩阵、5用户场景、模型测试与交付清单 |
| [docs/10_sources_and_gaps.md](docs/10_sources_and_gaps.md) | 核验来源、模板基线、尚未联调项与设计决策 |
| [docs/11_validation_record.md](docs/11_validation_record.md) | 本包已经执行的检查，以及尚未运行的网站/服务验收 |
| [.env.example](.env.example) | 无密钥配置样例；字段含义见运维文档 |
| [fixtures/README.md](fixtures/README.md) | 脱敏 OCR 样本与合成契约样例说明 |
| [scripts/validate_pack.py](scripts/validate_pack.py) | 本包本地引用、JSON、契约与样例一致性检查 |
| [scripts/contract_models.py](scripts/contract_models.py) / [scripts/validate_models.py](scripts/validate_models.py) | 可复用Pydantic DTO及Schema/样例一致性校验；需要Pydantic 2 |

## 开发时的裁决顺序

本轮用户确认 > `01_requirements.md` 的 V0.5 说明 > 本包接口/数据/处理规则 > 旧 Figma 和截图。出现契约与文档不一致时必须记录并统一修改，不能自行择一后隐瞒差异。本轮已确认内容已写入需求第13节。

## 交付边界

真实凭据由使用者在本地 `.env` 填写，禁止提交 Git。样本中的远程图片签名 URL 已替换为不可访问的占位地址；图片抓取、尺寸、完整签名识别、模型准确率和实际并发配额仍需真实联调。不得用合成样例替代真实服务验收。

默认值属于可调整的工程初值，不代表外部服务承诺：每任务50个文件、单文件50MiB、任务总量300MiB、任务1000页、单文件500页；同机 OCR 活跃作业1个、LLM请求2个。超过服务配额时按实际能力降低。

常见验证规模：3–10份文件、合计20–150页；压力边界按配置测试。5个用户可同时浏览、上传、核对；外部服务请求可以排队，不要求5个OCR同时执行。

## 版本说明

开发包从 V0.1 起单独版本管理；继承需求从 V0.4 更新至 V0.5。本轮不修改 Figma。截图仍为 V0.4/V0.3 的交互参考，其中可选保证人/抵（质）押人的旧画面已被 V0.5 的置灰规则覆盖。
