# 开发索引

| 模块 | 入口 | 如何运行或验证 |
|---|---|---|
| V2 前端线框 | [prototype/index.html](../credit-review-app-v2/prototype/index.html) | 使用根 README 的本地 HTTP 命令；按[设计验收](v2/verification/charter.md)复跑 |
| V2 本地数据库准备 | [compose.yml](../credit-review-app-v2/compose.yml) | 命令及隔离条件见[部署决策](v2/decisions/001-isolate-v2-data.md) |
| V1 前端 | [frontend](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/frontend/) | 旧工作台、任务管理、Playwright |
| V1 API / worker | [backend/app](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/) | `api/routes/runs.py` 管任务运行及完成；`ocr_pipeline.py`、`processing_pipeline.py` 管 OCR 与搜索 |
| V1 数据定义 | [models.py](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/models.py)、[Alembic](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/alembic/versions/) | 表关系及采用范围见[数据字典](v2/architecture/data-dictionary.md) |
| V1 部署、复验 | [Compose](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/compose.yml)、[T03](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/docs/REVIEW_HANDOFF.md) | 在 V1 固定提交运行；旧实验输入按[历史索引](legacy/INDEX.md)取得 |
