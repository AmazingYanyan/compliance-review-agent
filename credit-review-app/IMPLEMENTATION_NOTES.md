# 实施检查记录（IMPLEMENTATION NOTES）

日期：2026-11-06。范围：P0 底座兼容验证 + P1 登录/任务/文件/隔离。

## 1. 模板基线

- 来源：`fastapi/full-stack-fastapi-template`
- 固定提交：`aabb90126964a164e02aff39e7c385bb0598236d`（`📝 Update release notes`，作者时间 2026-11-03）
- 运行基线：Python `>=3.14`（镜像 `python:3.14`）、uv `0.9.26`、前端 Bun `1`、PostgreSQL `18`
  （卷挂 `/var/lib/postgresql`）。前端 React 19 / TypeScript / Vite 8 / Tailwind 4 / shadcn（radix）。
- LICENSE：MIT，保留于仓库根。

## 2. 锁文件与依赖

- 宿主机 uv 为 0.12.3；用宿主机 `uv lock` 重新生成锁文件，并在镜像内 `uv sync --frozen`
  （uv 0.9.26）验证通过，锁文件格式向后兼容。
- 新增后端依赖：`procrastinate==3.10.0`、`pypdf`、`openai`、`beautifulsoup4`。
- 移除：`emails`、`email-validator`（显式）、`sentry-sdk`（显式）。
- 说明：`sentry-sdk` / `email-validator` 仍作为 `fastapi[standard]` → `fastapi-cloud-cli`
  的传递依赖存在，但本工程**未初始化 Sentry、未使用 EmailStr**，即“Sentry 接入”已移除。
- 前端待补依赖（P2 使用）：`react-pdf`、`react-dropzone`、`react-textarea-autosize`、
  `react-resizable-panels`、`dompurify`（P1 未引入，后续接入对应功能时再加）。

## 3. 已验证项

| 项 | 结果 |
| --- | --- |
| 模板镜像构建（Python3.14 + Bun + uv） | ✅ `docker compose build api` 成功 |
| uv 锁文件与 uv0.9.26 兼容 | ✅ `uv sync --frozen` 通过 |
| PostgreSQL18 + SQLModel + Alembic | ✅ 初始迁移 autogenerate + `upgrade head` 成功（7 张表） |
| Procrastinate 3.10.0 + Python 3.14 | ✅ schema 应用成功 |
| 同事务入队（external connection） | ✅ 见下 |

同事务入队验证（`scripts/verify_procrastinate_tx.py`）：
- 回滚：业务行=0、任务=0（一起回滚）
- 提交：业务行=1、任务=1（一起提交）

关键点：`PsycopgConnector` 的 `**kwargs` 直传 `psycopg_pool.ConnectionPool`，连接参数名为
`conninfo`（非 `conn_info`）。同事务入队用法：
`task.configure(task_kwargs={...}, connection=raw_psycopg_conn).defer()`，其中
`raw_psycopg_conn` 来自 SQLAlchemy `conn.connection.dbapi_connection`。

## 4. 改造点（相对模板）

- 认证：邮箱登录 → 用户名登录；`OAuth2PasswordBearer`（JSON 返回 token）→ HttpOnly 会话
  Cookie + `auth_sessions` 表 + CSRF token + Origin 校验。
- 移除：注册/找回密码/用户管理/默认 Item/SMTP/Adminer/Traefik/Mailpit/Playwright/Sentry。
- 数据模型：重写为 users / auth_sessions / tasks / task_files / assets / view_states /
  idempotency_keys，含 `UNIQUE(task_id,id)` 与复合外键防跨任务串联。
- 部署：`compose.yml` 改为 db / api / worker 三服务，一次性 `migrate` / `seed-users` 用
  `docker compose run --rm api python -m app.cli ...`。api/worker 同镜像、共享 `app_files` 卷。
- Dockerfile CMD：`fastapi run --workers 4` → 单进程 `fastapi run --host 0.0.0.0 --port 8000`。

## 5. 环境注意

- 本机沙箱会拦截 `~/.docker/buildx/activity` 的写入，构建时需
  `export BUILDX_CONFIG=<repo>/.buildx-config`（已在 .gitignore 忽略）。
- GitHub 直连被沙箱代理（502）与直连超时双重阻断；模板经 `gh-proxy.com` 前缀代理克隆。
- Docker 镜像拉取走本机配置的国内 mirror（docker.1ms.run 等），ghcr.io 可达。

## 6. 待办 / 未验证（后续阶段）

- P4：双栏核对工作区、确认状态机（接受/拒绝 + 必填原因）、增量更新与 412 冲突。
- P5：5 账号并发、失败恢复、备份恢复、Windows 迁移。
- 视觉匹配（印章/签名）框架已实现，待真实财报样本联调（当前无印章/签名裁剪图）。

## 7. P2 已完成（OCR 真实异步闭环）

**模型配置**（实测确定）：
- LLM 文本 `qwen3.8-flash`；LLM 视觉 `qwen3.8-max-0902`（多模态，实测能识图）。
- OCR `PaddleOCR-VL-1.6` token 有效，提交→轮询→下载闭环实测通过。
- 视觉模型注意：`qwen-vl-*` / `qwen3.8-omni-flash` 等免费额度已耗尽；
  realtime 系列走 WebSocket、标准 chat 接口只返回异步状态，不可用。

**新增**：`ocr_jobs/ocr_pages/ocr_blocks/crops` 四表 + 迁移；`ocr_client.py`（HTTPX 提交/查询/下载）；
`ocr_normalize.py`（JSONL→页/块/裁剪图）；`ocr_pipeline.py`（submit→poll→download 三段 Procrastinate 任务）。

**关键踩坑**：
- 实际 OCR 结果图片主机是 `paddleocr-store-5.bj.bcebos.com`（非开发包写的 pplines-online），
  `.env` 的 `OCR_IMAGE_HOSTS` 已改为后缀匹配 `.bj.bcebos.com`。
- `procrastinate apply_schema()` 不幂等（重复 CREATE TYPE），migrate 已改为「已存在则跳过」。
- `import app.ocr_pipeline` 会把 `app` 变量重绑定到包，worker.py 需在之后再 `from app.queue import app`。
- SQLModel `commit()` 会 expire 对象，跨 session 访问触发 `DetachedInstanceError`，需在 session 内提取标量。
- API 进程 Procrastinate 未 open，入队需经 `queue.enqueue()`（内部 `with app.open()`）。

**验证**：真实文件上传→OCR→归档→落库（ocr_pages/ocr_blocks）→ ocr_status=done；
营业执照样本单测正确提取 seal 块文字「北京市朝阳区市场监督管理局」+ 裁剪图关联 + bbox。
真实业务样本（营业执照/章程/财报）待用户提供路径后做最终业务验收。

## 8. P3 已完成（处理管线：分类 → 文本查找 → 视觉匹配 + 结果集）

**新增模块**：
- `llm_client.py`：OpenAI 兼容调用，json_schema 严格输出 + Pydantic 校验 + 最多一次格式修复；
  SDK `max_retries=0`，步骤层管重试；模块级信号量限制并发。
- `llm_schemas.py`：Classification/TextSearch/VisionMatch 三个输出契约（Pydantic + JSON Schema）。
- `classification.py`：材料分类（分窗 + 多窗口合并 + mixed 判定）。
- `text_search.py`：文本/表格证据摘录（分窗查找，按 block_id + start/end_char 截取原文）。
- `vision_match.py`：印章/签名匹配（先文字匹配，视觉模型多图分批兜底，Pillow 缩放长边≤1600）。
- `processing_pipeline.py`：Procrastinate `processing.run` 编排三阶段，失败标记 error_code。
- `runs.py` 路由：POST /runs（同事务入队 `enqueue_in_session`）、GET /runs/{id}、GET /results。

**关键点**：
- 同事务入队：`task.configure(task_kwargs=..., connection=session.connection().connection.dbapi_connection).defer()`，
  run 创建与队列入队原子提交。
- not_found 语义：全覆盖才 `no_matching_evidence`；缺材料 `material_missing`；技术失败不标 not_found。
- 结果集 DTO 对齐 `review_results.example.json`（含 check_label/group_label/material_type/sources/decision 占位）。

**验证**（真实营业执照）：
- 材料分类 → business_license ✅
- 经营范围/营业期限 → text 证据 + 出处（file + 页码 + region 定位）✅
- 登记状态 → not_found(no_matching_evidence) ✅；章程/财报 → material_missing ✅
- run QUEUED→RUNNING→READY（约 47s），任务状态 PROCESSING→REVIEWING ✅
- 前端核对工作台按材料分组展示结果集 ✅

**踩坑**：
- Python 3 `except ... as e` 块退出后清除 `e`，需用块外变量保存首次校验错误（否则 UnboundLocalError）。
- FastAPI 新版 include_router 惰性（`_IncludedRouter`），`app.routes` 计数不代表真实路由数，需以请求实测为准。
- 视觉匹配须显式传 `settings.LLM_VISION_MODEL`，否则 `model=None` 会回退到文本模型。
