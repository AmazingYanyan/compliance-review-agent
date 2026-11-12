# 来源、依赖基线与尚待联调项

核验日期：2026-11-05。来源提供技术依据，不表示本包已经安装或运行了这些项目。

## 1. 用户确认的业务基线

原《对公信贷合规审查智能体_一期需求说明.md》V0.4为页面与核对规则来源，本轮升V0.5：最多5人同时使用；允许优化Figma；只启用借款人，其余两个角色灰色不可点；完成前可增删换文件/纠正分类；本地.env维护账号与服务配置。Figma仍是历史演示，不作为后端真值。

用户OCR调用案例用于异步提交/轮询/下载协议；12页法律尽调及新营业执照OCR快照用于结构分析。附件快照不能证明真实接口在线、配额足够或图片永久有效。包内样本已移除远程签名URL，没有修改原上传文件。

## 2. 工程底座核验

仓库：[fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)。固定核验提交：`aabb90126964a164e02aff39e7c385bb0598236d`，作者时间2026-11-03。

已读取该分支后固定提交的backend Dockerfile与compose，以及核验时backend/pyproject.toml、frontend/package.json；依赖以指定提交文件为最终基线，P0再核对，防止分支读取与提交读取之间发生更新。该版本后端要求Python>=3.14；Dockerfile采用Python3.14、Bun构建前端、uv0.9.26；前端为React/TypeScript/Vite/Tailwind/shadcn。Compose采用PostgreSQL18，数据库卷挂在/var/lib/postgresql。以上不是“任选一个较熟悉的旧版本”。

复用模板认证/哈希、ORM/迁移、前端框架和测试；本期去掉邮箱登录业务、注册/找回页面及路由、默认Item、SMTP/Adminer/Traefik等。模板同域提供已构建SPA可保留。模板MIT；修改后保留原版权许可，并在实施记录注明修改。

## 3. 成熟库与依据

| 能力 | 来源 | 采用方式 |
| --- | --- | --- |
| 官方底座 | [固定提交](https://github.com/fastapi/full-stack-fastapi-template/tree/aabb90126964a164e02aff39e7c385bb0598236d) | 按该提交起步并锁依赖 |
| 组件 | [shadcn/ui](https://ui.shadcn.com/docs/components) | 沿用模板风格；不是多套UI叠加 |
| PDF查看 | [wojtekmaj/react-pdf](https://github.com/wojtekmaj/react-pdf) | MIT；查看已有PDF及PDF.js viewport，业务写来源层 |
| 后台任务 | [Procrastinate 3.10.0](https://github.com/procrastinate-org/procrastinate/releases/tag/3.10.0) | MIT；PostgreSQL队列，需本地验证运行时组合 |
| 同事务入队 | [external connection](https://procrastinate.readthedocs.io/en/stable/howto/production/external_connection.html) | 连接类型、回滚和SQLModel桥接必须P0验证 |
| 停滞恢复 | [retry stalled jobs](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html) | 需要显式配置恢复，不声称自动恰好一次 |
| OCR托管SDK | [官方Python SDK](https://www.paddleocr.ai/main/en/version3.x/inference_deployment/serving/paddleocr_official_api/python.html) | 可用同步/异步client；依赖适配与job恢复实测后再选，默认HTTPX薄适配已知REST |
| OCR结果结构 | [PaddleOCR-VL部署说明](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL.html) | Base64/URL两类图片、prunedResult等；以实际服务响应验证 |
| LLM客户端 | [openai-python](https://github.com/openai/openai-python) | 官方SDK；自定义base_url，业务管理输出和重试 |
| 阿里云兼容协议 | [Model Studio Chat Completions](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions) | 验证实际模型ID、视觉及结构化支持 |
| HTML清理 | [DOMPurify](https://github.com/cure53/DOMPurify) | 双许可Apache-2.0或MPL-2.0，安装时明确采用的许可路径并保留声明 |
| 拖拽上传 | [react-dropzone](https://github.com/react-dropzone/react-dropzone) | 复用文件选择/拖拽，不把它当服务端上传实现 |
| 多行输入 | [react-textarea-autosize](https://github.com/Andarist/react-textarea-autosize) | 初始一行，自动增长 |
| 分栏拖宽 | [react-resizable-panels](https://github.com/bvaughn/react-resizable-panels) | 用于双栏/侧栏尺寸，实际版本接口需核对 |

表中依赖来源不等于最终软件成分清单。实现时从锁文件生成直接/传递依赖版本、SPDX和许可证文本清单；本包没有把尚未安装的软件冒充已核验可商用。暂不引入PyMuPDF，避免在单纯预览需求下额外引入不同许可及部署负担；PDF页数检查可使用pypdf，具体版本许可同样入清单。

## 4. 重要取舍记录

| 决定 | 原因 | 将来何时重新评估 |
| --- | --- | --- |
| Python而非新增Java后端 | 当前无既有工程，目标是OCR/LLM闭环，用户不以Java学习为优先 | 接入已有行内Java统一服务平台时 |
| PostgreSQL而非NoSQL主库 | 任务归属、证据引用、确认与完成需要事务和关系约束 | 数据模型/规模发生明确变化时 |
| 现成全栈模板+单套UI | 减少登录、路由、组件、部署重复建设，用户允许优化原型 | 模板约束明显妨碍业务且有实测证据时 |
| PostgreSQL任务库、无Redis | 已有DB且只有5用户；需要任务持久化，不需要另起broker | 多worker、高吞吐或更严格配额调度时 |
| 完整结果一次发布 | 避免局部未找到和混批统计，简化人工确认一致性 | 用户明确需要边识别边核对且定义增量语义时 |
| 只借款人启用 | 另外两套清单缺失，用户已选择禁用入口 | 清单定稿、版本化并验收后 |

这些是本次真实取舍的记录，不建设额外架构审批流程。

## 5. 未闭合项及处理方式

| 项目 | 当前处理 | 阻塞什么 |
| --- | --- | --- |
| 真实OCR/LLM凭据 | 本地.env填入；包中不保留 | 真实外网联调，不阻塞纯业务开发 |
| 可用文字/视觉模型ID、配额 | 配置化，diagnose与小样本验证 | 真实模型验收 |
| 签名裁剪专项样本 | 实现通用候选与保守逻辑，签名验收单列 | 签名识别能力，不能标整体签名已通过 |
| 远程图片尺寸/过期重取/来源变换 | 归档读取尺寸；不能验证则降级 | 区域定位及持久回看验收 |
| 多页重组真实来源 | 保留provider group与sources，不能造映射 | 跨页高亮完整验收 |
| 后两种角色清单 | 灰色禁用；配置结构已预留 | 后两角色正式启用 |
| “最近一年”目标年度 | 本期仅摘录报告年度，不自动判断时效合规；目标年度规则后续明确 | 自动判断，不阻塞原文核对 |
| 同类多文件重复/排序 | 上传顺序，源文件保留，证据去重但保留独立出处 | 后续高级版本优选，不阻塞本期 |
| 具体硬件与并发性能 | 配置初值+5用户验证，记录实测 | 性能承诺不能提前宣称 |

本轮已具备实施文档条件，无需为未知模型名称反复暂停整个工程。实现Agent应区分可独立推进的代码工作与必须拿真实服务验证的部分。
