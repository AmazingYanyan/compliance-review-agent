# V2 使用独立环境

决策：复用 PostgreSQL 18 镜像，使用 V2 专属 Compose 项目名、数据库名、账号与数据卷。API/worker 接入时再挂载 V2 文件卷，并使用独立测试配置。V1 的数据库和文件卷留给 V1。数据库容器仅通过 Compose 网络访问。V2 API 的建议本地端口为 8093，线框静态预览固定用 8092，两者不冲突。

数据库骨架已写入 `credit-review-app-v2/compose.yml`。在有 Docker 的环境从该目录设置仅供 V2 的 `V2_DB_PASSWORD` 后，运行 `docker compose -p credit-review-v2 config --quiet`，再运行 `docker compose -p credit-review-v2 up -d db`。运行迁移及 API 前，核对项目名、数据库名、卷名和连接目标。接下来从 V2 空库执行迁移，只导入固定样本。

> 2026-11-17 更正：上一轮记录的「本次执行环境无 Docker，尚未实际创建容器」已被实测推翻——本机 Docker 29.8.0 与 Compose v5.5.1 可用，`postgres:18` 镜像本地已有，V1 Compose 项目 `credit-review-app` 仍在运行且卷未动。阶段 B 应据此直接建立 V2 独立 Compose 项目并从空库执行迁移。
