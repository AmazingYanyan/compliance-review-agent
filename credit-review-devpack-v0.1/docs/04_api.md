# API契约与错误处理

基地址 `/api/v1`，同域Cookie认证。JSON字段统一snake_case，时间RFC3339/UTC，ID为UUID字符串。`contracts/openapi.json`描述路由及核心字段；以下事务、权限和错误语义同样是契约。

## 1. 通用规则

请求返回`X-Request-ID`；错误格式`{code,message,request_id,details}`，details不得包含SQL、Key、完整远程URL。所有资源路由都验证task.owner_user_id与当前用户；跨账号或不在该任务的嵌套ID均404。鉴权失败401；CSRF失败403。

写请求（登录除外）带`X-CSRF-Token`。任务输入变更及开始/重试带`If-Match: "<input_revision>"`；确认写带`If-Match: "<decision.version>"`。缺少需要的版本头返回428，过期返回412并附当前版本。任务详情响应含`ETag: "<input_revision>"`；结果详情包含decision.version，避免两种版本混用。

开始、显式重试、完成带`Idempotency-Key`（UUID）；同一用户、任务、操作24小时去重。upload依靠文件hash去重，replace保留旧文件并创建新fileId。分页使用opaque cursor，默认20、上限100，响应`items,next_cursor`；不得把taskId当全局授权过滤器。

## 2. 路由

| 方法与路径 | 行为与关键返回 |
| --- | --- |
| POST /auth/login | JSON username/password；成功200设置HttpOnly会话Cookie，返回用户与csrf_token；失败统一INVALID_CREDENTIALS |
| GET /auth/me | 当前用户及csrf_token；每次读取验证sid及账号启用状态 |
| POST /auth/logout | 撤销当前sid，清Cookie；204；后台既有任务不因退出而取消 |
| GET /capabilities | 登录后读取客户类型、清单版本、文件限制及服务配置是否完整；不返回密钥 |
| GET /tasks | 仅当前用户任务；cursor、limit、state可选；包含name、role、state、stage、更新时间 |
| POST /tasks | 创建DRAFT；body name可省略，customer_role必须borrower，product_code固定；201 |
| GET /tasks/{task_id} | 元信息、input_revision、当前/上次READY批次、文件摘要、statistics、可用操作 |
| PATCH /tasks/{task_id} | 只改名称，不改角色/产品；带If-Match，成功返回任务。名称变更不增加输入修订，仍验证当前修订 |
| GET /tasks/{task_id}/files | 包括每文件上传/OCR/分类状态、页数、有效分类；默认不列已删除历史文件 |
| POST /tasks/{task_id}/files | multipart字段file，一请求一文件，多文件由前端有界并发上传；If-Match；201含file与input_revision、run_id nullable |
| DELETE /tasks/{task_id}/files/{file_id} | 软移除当前输入；If-Match；200含input_revision与新run_id nullable；历史证据文件不立刻物理删除 |
| POST /tasks/{task_id}/files/{file_id}/replacement | multipart file；原子移除旧文件并新增；201含new_file_id/input_revision/run_id；不覆盖磁盘原件 |
| PATCH /tasks/{task_id}/files/{file_id}/classification | body material_type为三种有效类别或null（恢复自动）；If-Match；冻结下一轮输入，200返回修订/run_id |
| POST /tasks/{task_id}/runs | 首次开始或当前失败后重试，body retry_failed_only默认true；202含run；不强制重跑已成功OCR |
| GET /tasks/{task_id}/runs/{run_id} | 当前阶段、文件级进度、错误代码、是否被替代；外部jobId仅供内部诊断不必显示页面 |
| GET /tasks/{task_id}/results | run_id可省略取当前；material_type必填三选一；cursor分页；包含按check_item_id分组所需字段和sources/crop asset引用 |
| GET /tasks/{task_id}/results/{result_id} | 完整文字/表格、crop鉴权URL、出处、decision及version；旧批次只读 |
| PATCH /tasks/{task_id}/results/{result_id}/decision | body run_id、decision、reject_reason；decision If-Match；返回更新decision与全局/材料统计 |
| POST /tasks/{task_id}/complete | body run_id、input_revision；Idempotency-Key；200返回COMPLETED；409返回具体未完成统计 |
| GET /tasks/{task_id}/view-state | 当前用户各材料阅读状态，不修改业务结果 |
| PUT /tasks/{task_id}/view-state | 替换一类材料阅读状态；无须输入If-Match，校验fileId属于任务；旧文件时返回409 |
| GET /tasks/{task_id}/assets/{asset_id} | 鉴权流式返回原件/图片；支持PDF Range与If-Range，返回正确Content-Type；不重定向外部签名URL |
| GET /health/live | 无鉴权，仅存活；不访问外网 |
| GET /health/ready | DB及迁移状态；不返回凭据，不验证真实模型费用接口 |

## 3. 上传竞争与结果展示

一个批量上传中的每个请求串行使用最新input_revision；或由前端统一队列避免同任务版本竞争。不同用户上传可并行，不锁全局任务表。遇到412重新读取文件列表，提示用户当前变化，不能无条件重放“删除/更换”覆盖其他标签的操作。

文件名后缀、MIME和实际字节头联合验证；仅PDF、JPEG、PNG，拒绝损坏/加密不可读取的PDF（422），大小超限413，类型不支持415。流式限制大小，不能先无界读入内存。文件先写临时文件，验证/计算hash后原子移动；DB失败清理临时工件，业务文件以UUID路径保存。

处理期间GET results可以显式读取last_ready_run供只读参考，但响应`is_stale=true,editable=false`，当前statistics为null；不使用旧结果数显示新进度。新READY后只发布新批次及继承的有效确认。

TaskDetail.editable表示任务材料/元信息尚未因完成而锁定，不代表此刻允许确认；ResultView/ResultPage.editable只有当前READY且任务REVIEWING时才可为true。完成后的阅读状态仍可保存，因为它不改变材料、证据或人工确认。具体写接口始终按服务端状态检查，不只相信前端editable。

结果正文可较长，表格保留HTML但经过白名单清理；crop字段包含image_asset_id和站内URL，不携带Base64或外部签名。not_found结果sources为空，不提供伪造定位按钮。

## 4. 错误代码

| HTTP/代码 | 行为 |
| --- | --- |
| 401 INVALID_CREDENTIALS / SESSION_EXPIRED | 登录失败统一提示；会话失效清当前用户缓存并回登录 |
| 403 CSRF_FAILED | 阻止写请求；重新获取有效会话，不自动重放敏感变更 |
| 404 RESOURCE_NOT_FOUND | 不泄露另一用户资源是否存在 |
| 409 ROLE_DISABLED / CHECKLIST_UNCONFIGURED | 类型不可用或没有有效清单；不产生空结果任务 |
| 409 TASK_READ_ONLY / TASK_NOT_READY | 完成后或处理中禁止确认、文件变更按状态规范处理 |
| 409 INCOMPLETE_REVIEW | details含unselected/missing_reason/processing_failures；可给首条待处理result_id |
| 409 IDEMPOTENCY_CONFLICT | 同key不同请求；不得当成功 |
| 412 REVISION_CONFLICT / DECISION_CONFLICT | 返回最新修订或decision版本，前端刷新并说明；不静默覆盖 |
| 413 UPLOAD_LIMIT_EXCEEDED | 指明数量/字节/页数哪项超限 |
| 422 INVALID_FILE / INVALID_REQUEST | 格式/内容校验失败 |
| 428 PRECONDITION_REQUIRED | 缺If-Match |
| 429 RATE_LIMITED | 登录或服务本地限流，给Retry-After；不无限重试 |
| 503 SERVICE_NOT_CONFIGURED | .env缺配置；可登录和查看旧任务，新处理不可开始 |

外部OCR/LLM错误通过run状态异步回报，如OCR_AUTH_FAILED、OCR_RATE_LIMITED、OCR_SUBMISSION_UNKNOWN、OCR_RESULT_INVALID、ASSET_DOWNLOAD_FAILED、CLASSIFICATION_REQUIRED、LLM_TIMEOUT、LLM_OUTPUT_INVALID、EVIDENCE_INVALID、CONTEXT_LIMIT。模型技术失败不使用not_found业务结果替代。

## 5. 账号与日志

初始化账号用CLI，不开放create-user/register/password-recovery公共接口。维护命令可新增/停用/重置密码，重置密码撤销该用户既有会话。普通账号之间不允许共享或转交task。请求日志不包含密码、token、OCR全文、图片或带签名查询参数。
