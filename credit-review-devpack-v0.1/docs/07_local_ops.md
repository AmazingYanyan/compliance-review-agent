# 本地运行、配置、备份与迁移

本文件定义实现Agent必须交付的运行方式。包内没有应用代码、Dockerfile或已跑通的Compose；以下应用命令是待实现的命令契约，不应现在直接执行。

## 1. 默认部署

Mac安装Docker Desktop或兼容Docker Compose的容器环境。默认容器化db/api/worker，浏览器访问http://localhost:8080。无需在宿主机预装Paddle、OCR模型或GPU；前端构建也在容器完成。模板当前要求Python>=3.14，沿用指定提交的Python/Bun/uv基线，不假设用户既有Python3.11能直接启动。

Compose只对主机映射API端口，默认BIND_HOST=127.0.0.1；DB仅容器网可见，不映射公网5432。最多5人从其他设备访问时，配置BIND_HOST=0.0.0.0、PUBLIC_ORIGIN为实际局域网地址，打开对应主机防火墙端口；不需要负载均衡。可信本地开发HTTP可Secure=false；真实多人访问应配置HTTPS入口并Secure=true，TLS不属于这一版默认搭建的平台功能。不要因只在本机部署而移除鉴权。

API/worker共享上传卷与数据库配置。持久化卷至少分为pg_data和app_files。PostgreSQL18沿用官方镜像正确挂载路径/var/lib/postgresql；不要把旧主版本目录约定未经检查照搬。API一个进程，worker一个实例；migrate作为一次性步骤运行，不由每个worker同时迁移。服务依赖DB健康，不代表数据库迁移已完成。

## 2. 实现后需要支持的命令

```bash
# 首次：复制配置，填真实密钥、模型ID、随机应用秘密及账号密码
cp .env.example .env
docker compose build
docker compose up -d db
docker compose run --rm api python -m app.cli migrate
docker compose run --rm api python -m app.cli seed-users
docker compose up -d api worker

# 常用
docker compose ps
docker compose logs --tail 100 api worker
docker compose stop
docker compose start
```

上述app.cli migrate要串行执行Alembic业务迁移和Procrastinate官方schema迁移；不要杜撰库迁移SQL。seed-users只创建不存在账号，不静默覆盖密码；密码变更用专门reset-password命令并撤销会话。用户写在本地INITIAL_USERS_JSON，模板邮箱参数FIRST_SUPERUSER不能原样当用户名业务。

Windows推荐相同Compose方式，示例文件复制用PowerShell`Copy-Item .env.example .env`。不依赖bash专有路径、宿主绝对目录、Mac Keychain或Windows盘符；主路径使用容器DATA_DIR与命名卷。需要宿主调试时由实现README补uv/Bun启动命令和Vite同域代理。全栈主运行目标只有一个来源端口，避免不必要CORS。

## 3. 配置含义

.env.example的所有键都是实现契约。解析使用pydantic-settings，类型/范围校验；配置只注入后端与worker。前端仅获取capabilities允许的非敏感信息，不使用VITE_*变量暴露Key。

| 配置 | 用途/初值 |
| --- | --- |
| APP_MODE | real或test；交付默认real，缺凭据不回退模拟 |
| BIND_HOST/API_PORT/PUBLIC_ORIGIN | 监听与同域Origin；默认127.0.0.1/8080/http://localhost:8080 |
| SECRET_KEY/SESSION_* | 随机JWT秘密、会话小时、Secure开关；模板占位必须替换 |
| INITIAL_USERS_JSON | 本地初始化用户名与密码，不返回API，不提交Git |
| POSTGRES_PASSWORD/DATABASE_URL | DB容器变量与应用连接，密码一致；不使用公开默认密码 |
| DATA_DIR | 容器共享目录，默认/data |
| OCR_* | 地址、token、模型、轮询/截止/并发、JSONL/图片下载限制、允许图片主机 |
| LLM_API_BASE/API_KEY/TEXT_MODEL/VISION_MODEL | 阿里云兼容接口和模型名；不能从示例型号推定已开通 |
| LLM_*_CONCURRENCY/TIMEOUT/RETRIES | 全机有界请求，SDK重试与业务层去重 |
| UPLOAD_* | 文件个数、单文件/任务字节、PDF页数限制；均为工程初始上限 |
| VISION_* | 分批图片数/派生图长边；须适配模型真实上限 |
| PIPELINE_CONFIG_VERSION | 处理配置版本，进入输入/依赖hash，改变不能静默沿用旧结果 |

常见规模3–10份/20–150页；最大配置50份、单文件50MiB、任务300MiB、单文件500页、任务1000页。图片按1页计；不解压ZIP，不接受Office文件。文件上传后用实际PDF页数检查总页数，不相信浏览器参数。服务配额低于此上限时明确降低配置。

5用户目标是并行浏览、上传和核对，OCR作业默认1、LLM调用2，其他请求排队。技术错误重试有上限，不用无限重试代替容量控制。初始纯业务接口目标是在本机合理硬件和测试样本下p95≤1秒；实际硬件与结果要记录，外部OCR/LLM时延单独统计，不承诺外网总耗时。

## 4. 文件与工件

文件路径用taskId/fileId/assetId管理，不使用用户提供的文件名做目录。原文件、OCR JSONL、规范化原始证据、页面图和裁剪图均持久化；替换文件不覆盖旧字节，软删除保留旧批次溯源。临时/tmp或.tmp目录不作为永久存储。禁止把本地DATA_DIR整个作为StaticFiles公开。

当前版本不自动清理用户任务。未被DB引用的失败临时文件可由维护命令清理，先dry-run；不得删除仍被历史结果引用的文件。存储占用需日志/命令可查，不在这版新增运维大屏。

## 5. 备份与恢复命令契约

实现`python -m app.cli backup --output <dir>`及`restore --input <dir>`，或同等明确工具，README给实际命令。备份要包含PostgreSQL逻辑备份、文件卷及版本清单；仅复制DB不足以恢复来源图片。维护时停止api/worker写入，DB继续运行供pg_dump；获得一致DB与文件快照后再启动。活跃任务的jobId和阶段也应恢复。

目标过程：停止写入→pg_dump→文件归档→记录应用提交/数据库版本/hash→恢复到空目录/空DB验证→重新启动→对照原件与确认。环境密钥独立备份，不放公开代码包；是否保持SECRET_KEY由操作人员决定，换Key使旧会话失效，用户数据不受影响。

迁移到Windows/另一台Mac：安装Compose→获取相同应用与镜像版本→安全复制本地配置→恢复DB和文件→检查DATA_DIR/卷权限/端口/Origin→跑登录、图片、PDF定位、后台恢复冒烟。跨CPU架构重新构建或取对应镜像，不能复制macOS虚拟环境去Windows。

## 6. 日志与诊断

日志包含请求和业务ID、步骤、耗时、外部错误分类，禁止密码/Key、Cookie、图片Base64、预签名URL查询串及默认全文日志。原始响应按鉴权工件保存。live只测进程，ready测DB和schema；外部服务是否配置在capabilities反映，真实可用性由显式diagnose命令测试，不在健康检查循环调用计费服务。

模型/OCR凭据更新通过修改.env并重启api/worker生效；不恢复已完成任务、不改变旧批次记录的模型配置。运行中任务在新配置下继续需创建新的配置版本和显式重试，不能把新参数写成原来请求的结果。
