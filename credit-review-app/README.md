# 信贷资料核对

对公信贷合规审查智能体——一期：资料核对网站。业务人员上传营业执照、公司章程、最近一年已审计财报，
系统调用 OCR 与 LLM 做材料分类与原文/表格/签章证据摘录，业务人员在双栏工作区逐条接受/拒绝并填写原因。

> 本期（P0+P1）交付：底座兼容验证 + 真实登录/任务/文件持久化与多账号隔离。
> OCR/LLM/核对工作区/增量更新/并发等后续阶段尚未接入，详见 `IMPLEMENTATION_NOTES.md`。

## 技术栈

FastAPI + React/TypeScript/shadcn + PostgreSQL 18 + Procrastinate（后台队列），Docker Compose 一键启动。

## 前置条件

- Mac + Docker Desktop（含 Docker Compose）
- 构建时如遇 `~/.docker/buildx` 权限报错，先执行 `export BUILDX_CONFIG="$(pwd)/.buildx-config"`

## 首次启动

```bash
# 1. 复制配置并填入真实密钥/密码
cp .env.example .env
# 编辑 .env：SECRET_KEY（随机长串）、POSTGRES_PASSWORD、INITIAL_USERS_JSON、OCR/LLM 凭据

# 2. 构建并启动数据库
docker compose build
docker compose up -d db

# 3. 执行迁移与初始化账号
docker compose run --rm api python -m app.cli migrate
docker compose run --rm api python -m app.cli seed-users

# 4. 启动服务
docker compose up -d api worker
```

浏览器访问 <http://localhost:8080>（默认仅本机；局域网多人访问见 `.env` 的 `BIND_HOST`/`PUBLIC_ORIGIN`）。

## 常用命令

```bash
docker compose ps                 # 查看状态
docker compose logs --tail 100 api worker
docker compose stop               # 停止
docker compose start              # 再次启动
docker compose down               # 停止并移除容器（保留数据卷）
```

## 账号维护

```bash
# 重置某账号密码并撤销其既有会话
docker compose run --rm api python -m app.cli reset-password --username <name> --password <pw>
```

账号通过 `.env` 的 `INITIAL_USERS_JSON` 维护，`seed-users` 只创建不存在的账号，不静默覆盖已有密码。
系统不提供注册、找回密码、用户管理页面。

## 运行测试

```bash
docker compose run --rm -v "$PWD/backend/tests":/app/backend/tests api pytest -v
```

## 关键约束

- 本期仅启用「借款人」；保证人、抵（质）押人置灰且后端拒绝创建。
- 多账号数据隔离覆盖任务/文件/资产/预览；不共享任务。
- 结果是「原文/表格/签章证据」或「未找到」，不输出合规判断。
- 凭据仅从本地 `.env` 读取，不提交 Git。

## 备份与恢复

备份/恢复命令（`python -m app.cli backup/restore`）属后续阶段交付，尚未实现。
如需迁移，保留 `pg_data` 与 `app_files` 两个数据卷即可。
