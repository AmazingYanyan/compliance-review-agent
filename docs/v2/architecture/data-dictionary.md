# V2 章程核对 · 落库数据字典

本文是 V2「对公信贷资料核对」**章程核对（charter-verification）切片**的落库数据字典。范围限定为该切片实际需要的表，不做全量业务建模。

- V1 基线：固定提交 `e52520553f3efe8e790fb608e630bf29bab9c1bf`。V1 表定义在 `credit-review-app/backend/app/models.py`，迁移在 `credit-review-app/backend/app/alembic/versions/`。
- 取 V1 单文件：`git show e525205:credit-review-app/backend/app/models.py`；取目录：`git archive e525205 credit-review-app | tar -x -C /tmp/v1`。
- V2 库隔离：见 [../decisions/001-isolate-v2-data.md](../decisions/001-isolate-v2-data.md)（V2 独立 Compose 项目、独立库名与卷，不继承 V1 的 `alembic_version`）。
- 接口契约：[api-contract.md](api-contract.md)；状态表：[../requirements/charter.md](../requirements/charter.md)。

## 零、全局约定

| 项 | 约定 | 依据 |
|---|---|---|
| 主键 | 全部为 `uuid`，应用层 `uuid4` 生成 | 沿用 V1 `models.py` 各表 `id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)` |
| 命名 | 复数下划线表名；列名小写下划线 | 沿用 V1 |
| 时间 | `TIMESTAMPTZ`，一律 UTC 存储；应用层 `datetime.now(UTC)` | 沿用 V1 `models.py:11-12` |
| 布尔 | `BOOLEAN NOT NULL` + 显式默认值 | 沿用 V1 `processing_runs.coverage_complete`（`models.py:421`） |
| JSONB | 快照、bbox、polygon、事件前后值等半结构化字段用 `JSONB` | 沿用 V1 |
| 跨表归属 | 采用**复合外键 + 复合唯一**模式：被引用表建 `UNIQUE (task_id, id)`，引用表用 `FOREIGN KEY (task_id, <id>)` | 沿用 V1 `uq_runs_task_id_id` + `fk_results_run` 等 |
| **枚举约束** | **V1 的 5 个迁移中没有任何 `CheckConstraint`**（已全量检索 `CheckConstraint` / `check_constraint`，零命中），状态取值只靠应用层保证 | **V2 变更：为状态列加 `CHECK` 约束**。理由：V2 是新库、从空库执行，加约束没有兼容成本；V1 遗留的「枚举只靠应用层」是历史包袱，不应继承 |
| 软删除 | `task_files.deleted_at` / `tasks.deleted_at` 软删，不物理删除 | 沿用 V1 `models.py:171`、`:150` |
| 物理删除 | 本切片**不做任何物理删除**，包括文件替换 | 见第七节 |

### 0.1 V1 → V2 变更总览

| # | 变更 | 依据 |
|---|---|---|
| C-1 | `tasks.input_revision` 在 V1 **从不自增**（只有建任务时置 0、建 run 时拷贝），因此 V1 的 `REVISION_CONFLICT` 是一个永不触发的分支。V2 在**补传 / 替换 / 删除文件**时 `+1`。 | 沿用 `v1-reuse.md` §2.6 与 `crud.py:85`、`runs.py:119` |
| C-2 | `processing_runs.state = SUPERSEDED` 与 `run_steps.state = SUPERSEDED` 在 V1 **从不写入**（枚举有、写入无）。V2 在重跑时把旧 run 置 `SUPERSEDED`。 | 沿用 `models.py:56`、`:63`（枚举定义）+ 全库无写入方 |
| C-3 | `decisions.carried_from_result_id` 在 V1 **从不写入**。V2 用于跨 run 结转与「来自上一批次」标注。 | 沿用 `models.py:589`、`decisions.py:183-185`（只读） |
| C-4 | `tasks.current_run_id` 在 V1 **从不写入**（只在初始迁移里存在）。V2 写入「当前展示的 run」。 | 沿用 `models.py:145`、`4764cf6b25c6...py:69` |
| C-5 | `check_executions` 与 `view_states` 两表在 V1 **有 schema、无任何写入路径**。V2 开始写入。 | 沿用 `v1-reuse.md` §2.3 与全库检索 |
| C-6 | `ocr_pages.source_page_number` 语义从「provider 返回顺序 + 1」升级为「上传文件的 1-based 物理页码」；`mapping_status` 从恒 `unverified` 改为需校验后写 `verified`。 | 沿用 `ocr_pipeline.py:266`（`source_page_number = page_index + 1`）、`models.py:315` |
| C-7 | `ocr_pages.raster_asset_id` 与 `assets.kind = 'page_raster'` 在 V1 **从不写入**（无页栅格）。V2 必须写入，否则「点出处 → 左侧高亮」无坐标载体。 | 沿用 `v1-reuse.md` §2.1、§2.2 |
| C-8 | `results.crop_id` 在 V1 有指向 `crops` 的外键。V2 章程切片**不建 `crops` 表**（本切片只有文本摘录），故该列保留为可空 UUID 但**不建外键**。 | 表清单不含 `crops`；印章/签名不在章程切片范围 |
| C-9 | `result_sources.start_char` / `end_char` 在 V1 **恒为 `null`**（模型返回的字符偏移不可靠，代码显式置 `None`）。V2 保持 `null`，契约中标为保留字段。 | 沿用 `text_search.py:433-434`、`:587-588` |
| C-10 | V2 **不建** `crops`、`idempotency_keys`；`users` / `auth_sessions` 阶段 B 之后才建。 | 见 0.2 |

### 0.2 阶段 B 之后才需要的表

| 表 | 是否在本轮建 | 将来加入时的隔离要求 |
|---|---|---|
| `users` | **否** | 加入后：`tasks.owner_user_id`、`decisions.actor_user_id`、`decision_events.actor_user_id` 必须回填并建外键 + 索引；本轮这三列建为**可空且无外键**，加入时补 `FOREIGN KEY (owner_user_id) REFERENCES users(id)` 与回填脚本，保证不同用户的任务、文件、结果、决定互不可见 |
| `auth_sessions` | **否** | 加入后：会话与 CSRF 只属于 API 层；写接口需 CSRF 头（V1 用 `require_csrf` 依赖） |
| `crops` | **否** | 阶段 B 之后引入视觉匹配时再建，届时给 `results.crop_id` 补外键 `FOREIGN KEY (task_id, crop_id) REFERENCES crops(task_id, id)`，并回填已存在的 `crop_id` 值 |
| `idempotency_keys` | **否** | 本切片无幂等写入需求；将来若对完成接口做幂等，再单独建表并写 `uq_idem_user_task_key_op` 唯一约束 |

## 一、迁移路径与执行顺序

V2 从**空库**执行自己的迁移，不继承 V1 的任何迁移历史（见 `docs/v2/decisions/001-isolate-v2-data.md`）。迁移文件建议置于 `credit-review-app-v2/backend/app/alembic/versions/`，Alembic `alembic_version` 表与 V1 完全隔离。

| 序 | 迁移文件 | 建表 | 依赖 | 说明 |
|---|---|---|---|---|
| 1 | `0001_tasks_files_assets.py` | `tasks`、`task_files`、`assets`、`view_states` | 无 | 任务与文件底座；`view_states` 只依赖 `tasks` |
| 2 | `0002_ocr_tables.py` | `ocr_jobs`、`ocr_pages`、`ocr_blocks` | 1 | 依赖 `task_files` |
| 3 | `0003_run_result_tables.py` | `processing_runs`、`run_files`、`run_steps`、`check_executions`、`results`、`result_sources` | 1、2 | 依赖 `tasks`、`task_files`、`ocr_*` |
| 4 | `0004_decision_tables.py` | `decisions`、`decision_events` | 3 | 依赖 `results` |

**执行顺序要求**：

1. 四个迁移必须能**从空库按序执行成功**（`alembic upgrade head` 一次跑通，且 `downgrade base` 能完整回滚）。
2. `downgrade` 必须按**逆序**删表：`0004` → `0003` → `0002` → `0001`。
3. 迁移中**不得**包含任何真实客户数据、真实凭据或真实文件路径；样本只能是固定、已脱敏或已获授权的公开样本。
4. 每个迁移的 `upgrade()` 需自带 `CHECK` 约束（见第 0 节的枚举约定），避免「建完表再补约束」的第二遍迁移。

## 二、逐表规格

### 2.1 `tasks`

**用途**：一次核对任务的身份、状态、输入版本与完成归属。

**沿用 V1 固定提交 e525205 的 `tasks` 表**（`credit-review-app/backend/app/models.py:134-155`，迁移 `4764cf6b25c6_initial_credit_review_schema.py:60-78`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `owner_user_id` | `uuid` | **是** | `NULL` | 所有者。V1 为 `NOT NULL` + FK `users.id` | **V2：可空、无 FK**（本轮无登录）；阶段 B 补 FK 并回填 |
| `name` | `varchar(120)` | 否 | — | 任务名 | — |
| `product_code` | `varchar(64)` | 否 | — | 产品代码，V1 取值 `working_capital_loan` | — |
| `customer_role` | `varchar(32)` | 否 | — | `borrower` / `guarantor` / `pledgor` | 加 `CHECK` |
| `checklist_version` | `varchar(64)` | 是 | `NULL` | 清单版本号 | — |
| `state` | `varchar(20)` | 否 | `'DRAFT'` | 任务状态 | 加 `CHECK` |
| `input_revision` | `integer` | 否 | `0` | 输入版本号 | 语义变更（C-1）：文件集变化时 `+1` |
| `current_run_id` | `uuid` | 是 | `NULL` | 当前展示的 run | **V2 写入**（C-4）；V1 从不写 |
| `last_ready_run_id` | `uuid` | 是 | `NULL` | 完成时对应的 run | — |
| `created_at` | `timestamptz` | 否 | `now()` | 创建时间 | — |
| `updated_at` | `timestamptz` | 否 | `now()` | 更新时间 | — |
| `completed_at` | `timestamptz` | 是 | `NULL` | 完成时间；完成接口写入 | — |
| `deleted_at` | `timestamptz` | 是 | `NULL` | 软删标记（V1 由 `607b61c473bc` 追加） | — |

**主键**：`id`。
**外键**：V1 有 `owner_user_id → users.id`；V2 本轮**不建**该外键。
**唯一约束**：无。
**索引**：V1 `ix_tasks_owner_updated (owner_user_id, updated_at, id)`、`ix_tasks_owner_deleted (owner_user_id, deleted_at)`、`ix_tasks_owner_user_id`；V2 保留 `ix_tasks_owner_updated`、`ix_tasks_owner_deleted`，并新增 `ix_tasks_state (state)` 供列表按状态过滤。

**状态取值含义**

| 值 | 含义 |
|---|---|
| `DRAFT` | 已建任务，尚未上传任何文件（V1：首个文件上传后转 `PROCESSING`，`files.py:193-195`） |
| `PROCESSING` | 资料处理中（OCR 或核对 run 未完成） |
| `REVIEWING` | 结果已就绪，等待人工核对 |
| `FAILED` | 处理失败 |
| `COMPLETED` | 核对完成，写入 `completed_at` 与 `last_ready_run_id`；此后**只读** |

**业务归属规则 vs 数据库实际约束**

| 业务归属（规格要求，代码保证） | 数据库实际约束 |
|---|---|
| 任务的输入版本号必须与当前文件集一致 | `input_revision` 只是整数列，**数据库不校验**它与 `task_files` 的关系 |
| 完成只能由 `POST /complete` 触发 | **数据库无约束**阻止任何路径写 `state = 'COMPLETED'` |
| `current_run_id` 必须指向本任务的 run | V2 应建外键 `FOREIGN KEY (task_id, current_run_id) REFERENCES processing_runs(task_id, id)`；注意该外键**跨迁移**，故放在 `0003` 中追加（`op.create_foreign_key`），不能写在 `0001` 里 |
| `last_ready_run_id` 必须指向本任务的 READY run | 同上，在 `0003` 追加 |

### 2.2 `task_files`

**用途**：任务上传的每个文件一行的身份记录（原名、类型、字节、sha256），支撑补传、替换与去重。

**沿用 V1 固定提交 e525205 的 `task_files` 表**（`models.py:158-176`，迁移 `4764cf6b25c6...py:79-95`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务，FK `tasks.id` | — |
| `original_name` | `varchar(512)` | 否 | — | 上传文件名 | — |
| `media_type` | `varchar(128)` | 否 | — | `application/pdf` / `image/jpeg` / `image/png`（V1 用魔数嗅探判定，不信客户端声明，`files.py:42-46`） | — |
| `size_bytes` | `bigint` | 否 | — | 字节数 | — |
| `sha256` | `varchar(64)` | 否 | — | 内容哈希；**同时是 `source_ordering.file_key` 的来源**，禁止改成 UUID 或任务内合成值 | — |
| `original_asset_id` | `uuid` | 是 | `NULL` | 指向 `assets.id`（原件） | — |
| `source_page_count` | `integer` | 是 | `NULL` | 源文件页数 | — |
| `manual_material_type` | `varchar(64)` | 是 | `NULL` | 人工指定的材料类型 | 加 `CHECK`（同 `MaterialType` 取值） |
| `created_at` | `timestamptz` | 否 | `now()` | 上传时间 | — |
| `deleted_at` | `timestamptz` | 是 | `NULL` | 软删标记；删除只置位，**不物理删除**（V1 `files.py:203-214`） | — |

**主键**：`id`。
**外键**：`task_id → tasks.id`。
**唯一约束**：`uq_task_files_task_id_id (task_id, id)` —— 供 `assets` / `ocr_*` 的复合外键引用。
**索引**：`ix_task_files_task_id`、`ix_task_files_task_deleted (task_id, deleted_at)`。

**状态取值含义**：`deleted_at IS NULL` = 生效中；`deleted_at IS NOT NULL` = 已移除（不参与新 run 的文件快照）。
**业务归属 vs 约束**：业务上「同任务内同 sha256 只保留一份生效文件」——V1 在上传路径做去重，命中时直接返回既有 `file_id`（`files.py:166-169`）；**数据库没有该约束**。因此「替换文件」在数据层等价于「上传一份内容不同的新文件 + 旧行软删」；上传**相同内容**会按 V1 规则返回既有 `file_id`，不会新建版本行。

### 2.3 `assets`

**用途**：文件内容的物理载体（原件、OCR 原始结果、页栅格、裁剪图）。

**沿用 V1 固定提交 e525205 的 `assets` 表**（`models.py:179-201`，迁移 `4764cf6b25c6...py:111-127`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `file_id` | `uuid` | 是 | `NULL` | 所属文件 | — |
| `kind` | `varchar(32)` | 否 | — | `original` / `ocr_raw` / `page_raster` / `crop` | 加 `CHECK`；**V2 必须写 `page_raster`**（C-7） |
| `storage_key` | `varchar(512)` | 否 | — | 存储键。V1 原件模板 `originals/{task_id}/{file_id}/original.bin`（`files.py:116`） | — |
| `sha256` | `varchar(64)` | 是 | `NULL` | 内容哈希 | — |
| `media_type` | `varchar(128)` | 是 | `NULL` | MIME | — |
| `size_bytes` | `bigint` | 是 | `NULL` | 字节数 | — |
| `width_px` | `integer` | 是 | `NULL` | 像素宽（页栅格用） | — |
| `height_px` | `integer` | 是 | `NULL` | 像素高（页栅格用） | — |
| `created_at` | `timestamptz` | 否 | `now()` | 创建时间 | — |

**主键**：`id`。
**外键**：`fk_assets_task_file FOREIGN KEY (task_id, file_id) REFERENCES task_files(task_id, id)`（复合 FK）。
**唯一约束**：`uq_assets_task_id_id (task_id, id)`。
**索引**：`ix_assets_task_id`。

**状态取值含义**：`kind = original` = 上传原件；`ocr_raw` = provider 原始 JSON；`page_raster` = 页栅格图（章程切片左栏高亮的载体，V1 从不写）；`crop` = 块内裁剪图（章程切片不用）。
**业务归属 vs 约束**：业务上「资产必须属于本任务」由应用层 `assets.py:14-44` 的归属校验保证；**数据库只保证 `(task_id, file_id)` 的复合一致**，`file_id` 本身可空（原件资产在 V1 里是回填 `task_files.original_asset_id` 的方向）。

### 2.4 `ocr_jobs`

**用途**：一次文件识别作业的状态与 provider 关联。

**沿用 V1 固定提交 e525205 的 `ocr_jobs` 表**（`models.py:274-301`，迁移 `a9d28dad6567_add_ocr_tables.py`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `file_id` | `uuid` | 是 | `NULL` | 所属文件 | — |
| `request_config_hash` | `varchar(64)` | 否 | — | 请求配置哈希 | — |
| `provider_job_id` | `varchar(128)` | 是 | `NULL` | provider 作业号 | — |
| `state` | `varchar(32)` | 否 | `'NOT_SUBMITTED'` | 作业状态 | 加 `CHECK` |
| `attempt` | `integer` | 否 | `0` | 尝试次数 | — |
| `submitted_at` / `next_poll_at` / `deadline_at` | `timestamptz` | 是 | `NULL` | 提交、下一轮轮询、截止时间 | — |
| `result_asset_id` | `uuid` | 是 | `NULL` | 结果资产 | — |
| `last_error_code` | `varchar(64)` | 是 | `NULL` | 失败短码 | — |
| `provider_metadata` | `jsonb` | 是 | `NULL` | provider 元数据（V1 会写入 `jsonl_key`，`ocr_pipeline.py:247`） | — |
| `created_at` / `updated_at` | `timestamptz` | 否 | `now()` | 时间戳 | — |

**主键**：`id`。
**外键**：`fk_ocr_jobs_task_file FOREIGN KEY (task_id, file_id) REFERENCES task_files(task_id, id)`。
**唯一约束**：`uq_ocr_jobs_task_id_id (task_id, id)`。
**索引**：`ix_ocr_jobs_task_id`、`ix_ocr_jobs_state_next_poll (state, next_poll_at)`。

**状态取值含义**：`NOT_SUBMITTED` 未提交 / `SUBMITTED` 已提交 / `RUNNING` 识别中 / `DOWNLOADING` 下载结果 / `SUCCEEDED` 成功 / `FAILED` 失败 / `SUBMISSION_UNKNOWN` 提交结果未知。
**V2 使用范围**：章程切片走**固定样本导入**，不向 provider 提交与轮询（见 `v1-reuse.md` §2.4、§2.7），因此实际只会出现 `SUCCEEDED`；其余取值保留定义但不使用。

### 2.5 `ocr_pages`

**用途**：识别结果的一页，承载页序、页码映射与页尺寸/坐标系。

**沿用 V1 固定提交 e525205 的 `ocr_pages` 表**（`models.py:304-334`，迁移 `a9d28dad6567...py`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `file_id` | `uuid` | 是 | `NULL` | 所属文件 | — |
| `ocr_job_id` | `uuid` | 是 | `NULL` | 所属识别作业 | — |
| `provider_line_index` | `integer` | 否 | `0` | 该页在 provider JSONL 的行号 | — |
| `provider_item_index` | `integer` | 否 | `0` | 该页在 `layoutParsingResults` 的下标 | — |
| `ocr_page_index` | `integer` | 否 | `0` | provider 页序（0-based） | — |
| `source_page_number` | `integer` | 是 | `NULL` | **对外展示页码，1-based** | **语义变更（C-6）**：V1 = `ocr_page_index + 1`；V2 = 上传文件的物理页号 |
| `mapping_status` | `varchar(16)` | 否 | `'unverified'` | 页码映射是否已校验 | **V2 语义变更（C-6）**：校验通过写 `'verified'`；加 `CHECK` |
| `raster_asset_id` | `uuid` | 是 | `NULL` | 页栅格资产 | **V2 必须写**（C-7）；V1 从不写 |
| `width_px` | `integer` | 是 | `NULL` | 页像素宽（OCR 输入图像） | — |
| `height_px` | `integer` | 是 | `NULL` | 页像素高 | — |
| `coordinate_space` | `varchar(32)` | 否 | `'unknown'` | 坐标系标识 | 加 `CHECK`（`ocr_input_image_pixels` / `unknown`） |
| `transform_metadata` | `jsonb` | 是 | `NULL` | provider 预处理参数（V1 原样存 `doc_preprocessor_res`） | — |

**主键**：`id`。
**外键**：`fk_ocr_pages_task_file (task_id, file_id) → task_files(task_id, id)`；`fk_ocr_pages_task_job (task_id, ocr_job_id) → ocr_jobs(task_id, id)`。
**唯一约束**：`uq_ocr_pages_task_id_id (task_id, id)`。
**索引**：`ix_ocr_pages_task_id`、`ix_ocr_pages_file_id`。

**状态取值含义**：`mapping_status = verified` 表示 `source_page_number` 已与上传文件的物理页号核对一致；`unverified` 表示未核对或核对不一致。
**业务归属 vs 约束**：业务上「同一文件内的页不得重复」——**数据库无约束**，需在导入时按 `(file_id, source_page_number)` 自行去重。

### 2.6 `ocr_blocks`

**用途**：页内的文本/表格块，承载原文、bbox 与多边形。

**沿用 V1 固定提交 e525205 的 `ocr_blocks` 表**（`models.py:337-369`，迁移 `a9d28dad6567...py`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `file_id` | `uuid` | 是 | `NULL` | 所属文件 | — |
| `page_id` | `uuid` | 是 | `NULL` | 所属页 | — |
| `provider_block_id` / `group_id` / `global_block_id` / `global_group_id` | `varchar(128)` | 是 | `NULL` | provider 侧块/组标识 | — |
| `sequence_index` | `integer` | 否 | `0` | 页内顺序（取 `block_order`） | — |
| `label` | `varchar(32)` | 是 | `NULL` | 块类型标签（如 `text` / `table`） | — |
| `canonical_text` | `text` | 否 | `''` | 剥离 HTML 后的纯文本 | — |
| `table_html` | `text` | 是 | `NULL` | 表格原始 HTML | — |
| `bbox` | `jsonb` | 是 | `NULL` | 块矩形 `[x1,y1,x2,y2]`（页像素） | — |
| `polygon` | `jsonb` | 是 | `NULL` | 块多边形点集 | — |
| `raw_content_ref` | `varchar(512)` | 是 | `NULL` | 原始内容引用 | **V1 从不写入**；V2 保持不写 |
| `crop_id` | `uuid` | 是 | `NULL` | 关联裁剪图 | 章程切片不用 |

**主键**：`id`。
**外键**：`fk_ocr_blocks_task_file (task_id, file_id) → task_files(task_id, id)`；`fk_ocr_blocks_task_page (task_id, page_id) → ocr_pages(task_id, id)`。
**唯一约束**：`uq_ocr_blocks_task_id_id (task_id, id)`。
**索引**：`ix_ocr_blocks_task_id`、`ix_ocr_blocks_file_id`、`ix_ocr_blocks_page_id`。

**业务归属 vs 约束**：业务上「块的坐标必须在所属页的尺寸内」（`0 ≤ x1 < x2 ≤ width_px`）——**数据库无约束**，属导入期校验（`v1-reuse.md` AC-R2）。

### 2.7 `processing_runs`

**用途**：一次核对运行：清单快照、输入版本、状态、**覆盖事实**。

**沿用 V1 固定提交 e525205 的 `processing_runs` 表**（`models.py:409-430`，迁移 `2549094dcd38_add_processing_run_tables.py:22-41`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务，FK `tasks.id` | — |
| `input_revision` | `integer` | 否 | `0` | 本次 run 绑定的输入版本快照 | 建 run 时取 `tasks.input_revision` 的值（V1 `runs.py:119`），**不自增** |
| `checklist_snapshot` | `jsonb` | 是 | `NULL` | 清单快照（材料 + 检查项） | — |
| `checklist_hash` | `varchar(64)` | 否 | — | 清单哈希 | — |
| `model_snapshot` | `jsonb` | 是 | `NULL` | 模型与运行配置快照 | — |
| `state` | `varchar(20)` | 否 | `'QUEUED'` | run 状态 | 加 `CHECK`；**V2 写入 `SUPERSEDED`**（C-2） |
| `stage` | `varchar(64)` | 是 | `NULL` | 当前阶段 | — |
| `input_manifest_hash` | `varchar(64)` | 是 | `NULL` | 输入清单哈希 | — |
| `coverage_complete` | `boolean` | 否 | `false` | **覆盖状态的唯一事实源** | 语义不变（见第七节） |
| `error_code` | `varchar(64)` | 是 | `NULL` | 失败/异常短码，如 `COVERAGE_NO_UNIT_STEPS` | — |
| `created_at` / `started_at` / `finished_at` | `timestamptz` | 否/是 | `now()` / `NULL` | 时间戳 | — |

**主键**：`id`。
**外键**：`task_id → tasks.id`。
**唯一约束**：`uq_runs_task_id_id (task_id, id)`（供 `run_files` / `run_steps` / `results` 的复合外键引用）。
**索引**：`ix_runs_task_revision (task_id, input_revision)`、`ix_runs_task_id`。

**状态取值含义**

| 值 | 含义 |
|---|---|
| `QUEUED` | 已创建、待 worker 领取 |
| `RUNNING` | 处理中 |
| `READY` | 结果就绪，可写决定、可完成（**唯一允许写决定的 run 状态**） |
| `FAILED` | 处理失败 |
| `SUPERSEDED` | 已被更新的 run 取代；**只读、不可写决定、不可完成**（V2 新增实际写入，C-2） |

**业务归属 vs 约束**：业务上「run 的 `input_revision` 必须等于建 run 时刻的 `tasks.input_revision`」——**数据库无约束**，由建 run 的代码保证；stale 判定 = `run.input_revision != tasks.input_revision`（V1 `runs.py:258` 已有 `is_stale` 字段，本轮沿用）。

### 2.8 `run_files`

**用途**：run 绑定的文件快照与该文件在本轮生效的材料类别。

**沿用 V1 固定提交 e525205 的 `run_files` 表**（`models.py:433-455`，迁移 `2549094dcd38...py:59-70`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `run_id` | `uuid` | 否 | — | 复合主键之一 | — |
| `file_id` | `uuid` | 否 | — | 复合主键之一 | — |
| `task_id` | `uuid` | 否 | — | 冗余任务列，供复合外键使用 | — |
| `effective_material_type` | `varchar(64)` | 是 | `NULL` | 本轮生效材料类别 | 加 `CHECK`（`MaterialType` 取值） |
| `classification_source` | `varchar(32)` | 是 | `NULL` | 分类来源 | — |
| `classification_reason` | `text` | 是 | `NULL` | 分类理由 | — |
| `ocr_job_id` | `uuid` | 是 | `NULL` | 使用的识别作业 | — |

**主键**：复合 `(run_id, file_id)`。
**外键**：`fk_run_files_run (task_id, run_id) → processing_runs(task_id, id)`；`fk_run_files_task_file (task_id, file_id) → task_files(task_id, id)`。
**唯一约束**：主键本身即 `(run_id, file_id)` 唯一。
**索引**：`ix_run_files_task_id`。

**状态取值含义**：`effective_material_type IS NULL` = 尚未分类（分类阶段未产出）；非空 = 本轮生效类别。
**业务归属 vs 约束**：业务上「run 的文件集 = 建 run 时刻的生效文件集」——**数据库无约束**；`run_files` 是唯一的**快照事实**，后续文件增删不影响旧 run。

### 2.9 `run_steps`

**用途**：run 内的一个可观测执行单元（阶段步 / 窗口批次步 / 检查项步），记录耗时与失败短码。

**沿用 V1 固定提交 e525205 的 `run_steps` 表**（`models.py:458-483`，迁移 `2549094dcd38...py:72-89`，`b7e4c9d1a2f3_add_run_step_timing.py` 加了 `started_at` / `finished_at`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `run_id` | `uuid` | 否 | — | 所属 run | — |
| `file_id` | `uuid` | 是 | `NULL` | 关联文件 | — |
| `step_key` | `varchar(64)` | 否 | — | 单元键：`stage:classify\|search\|vision`、`u:w{wi}:b{bi}`、`check:{check_item_id}` | — |
| `input_hash` | `varchar(64)` | 否 | — | `sha256(step_key\|extra)[:64]`，保证可复算 | — |
| `state` | `varchar(20)` | 否 | `'QUEUED'` | 步骤状态 | 加 `CHECK` |
| `attempt` | `integer` | 否 | `0` | 尝试次数 | — |
| `provider_request_id` | `varchar(128)` | 是 | `NULL` | provider 请求号 | — |
| `result_asset_id` | `uuid` | 是 | `NULL` | 结果资产 | — |
| `last_error_code` | `varchar(64)` | 是 | `NULL` | 失败短码 | — |
| `started_at` / `finished_at` | `timestamptz` | 是 | `NULL` | 起止时间（V1 由 `b7e4c9d1a2f3` 追加） | — |

**主键**：`id`。
**外键**：`fk_run_steps_run (task_id, run_id) → processing_runs(task_id, id)`。
**唯一约束**：`uq_run_steps_task_id_id (task_id, id)`；**`uq_run_steps_key_hash (run_id, step_key, input_hash)`** —— 同一 run 内同键同输入只允许一行，支撑 upsert。
**索引**：`ix_run_steps_task_id`、`ix_run_steps_run_id`。

**状态取值含义**：`QUEUED` 待执行 / `RUNNING` 执行中 / `SUCCEEDED` 成功 / `FAILED` 失败 / `SUPERSEDED` 被新 run 取代。
**业务归属 vs 约束**：业务上「`step_key` 以 `u:` 或 `check:` 开头的行才是**单元步**，是覆盖判定的一个输入」——但**覆盖判定不由本表推导**（见第七节，V1 明确废弃了按 `step_key` 前缀扫描的做法，改为读结果行）。`run_steps` 在本切片只作**过程证据**，不作判定源。

### 2.10 `check_executions`

**用途**：run 内一个检查项的执行记录：搜索命中与否、以及**哪些窗口覆盖了它**。

**沿用 V1 固定提交 e525205 的 `check_executions` 表的 schema**（`models.py:486-506`，迁移 `2549094dcd38...py:43-57`）。
**V1 从未写入本表**（全库检索 `CheckExecution` 仅命中模型定义）；**V2 开始写入**（C-5）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `run_id` | `uuid` | 否 | — | 所属 run | — |
| `check_item_id` | `varchar(128)` | 否 | — | 检查项 ID | — |
| `dependency_hash` | `varchar(64)` | 否 | — | 清单叶子的稳定内容 hash（V1 `_stable_leaf_hash`，`processing_pipeline.py:262-265`） | — |
| `search_status` | `varchar(16)` | 否 | `'not_found'` | `found` / `not_found` | 加 `CHECK` |
| `coverage` | `jsonb` | 是 | `NULL` | **窗口覆盖明细**（见下） | **V2 约定内容**（V1 从不写） |
| `completed_at` | `timestamptz` | 是 | `NULL` | 完成时间 | — |

**`coverage` JSONB 的 V2 内容约定**

```json
{
  "windows": ["w0", "w1"],
  "window_count": 2,
  "covered": true,
  "not_found_reason": null,
  "covered_blocks": ["<ocr_block_id>", "..."]
}
```

| 键 | 类型 | 含义 |
|---|---|---|
| `windows` | string[] | 覆盖该检查项的窗口 bundle 标识（`w0`、`w1`…，对应 `run_steps.step_key` 中的 `u:w{wi}:b{bi}`） |
| `window_count` | int | 窗口数 |
| `covered` | bool | 该检查项是否达成窗口覆盖（与第七节口径一致） |
| `not_found_reason` | string | 未覆盖时的原因：`coverage_incomplete` / `no_matching_evidence` / `material_missing` / `null` |
| `covered_blocks` | uuid[] | 支撑该检查项的块 ID 列表（可为空） |

**主键**：`id`。
**外键**：`fk_check_exec_run (task_id, run_id) → processing_runs(task_id, id)`。
**唯一约束**：`uq_check_exec_task_id_id (task_id, id)`；**`uq_check_exec_run_item (run_id, check_item_id)`** —— 每个 run 内每个检查项至多一行。
**索引**：`ix_check_executions_task_id`、`ix_check_executions_run_id`。

**业务归属 vs 约束**：业务上「本表只是过程证据，**不参与** `coverage_complete` 的判定」——**数据库层面无法表达**，需在代码与评审中守住（V1 正是在这里踩过双事实源的坑，见第七节）。

### 2.11 `results`

**用途**：一个检查项在一次 run 中的一条摘录（文本 / 表格 / 印章 / 签名 / 未找到）。

**沿用 V1 固定提交 e525205 的 `results` 表**（`models.py:509-541`，迁移 `2549094dcd38...py:91-113`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键；**决定写入以它为键** | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `run_id` | `uuid` | 否 | — | 所属 run | — |
| `check_execution_id` | `uuid` | 是 | `NULL` | 关联 `check_executions.id` | — |
| `check_item_id` | `varchar(128)` | 否 | — | 检查项 ID | — |
| `kind` | `varchar(16)` | 否 | — | `text` / `table` / `seal` / `signature` / `not_found` | 加 `CHECK` |
| `text` | `text` | 是 | `NULL` | 摘录正文 | — |
| `table_html` | `text` | 是 | `NULL` | 表格 HTML | — |
| `crop_id` | `uuid` | 是 | `NULL` | 关联裁剪图 | **V2：不建外键**（无 `crops` 表，C-8） |
| `recognition_source` | `varchar(16)` | 是 | `NULL` | `ocr` / `vision` | 加 `CHECK` |
| `relation_status` | `varchar(16)` | 是 | `NULL` | `matched` / `needs_review` | 加 `CHECK` |
| `not_found_reason` | `varchar(64)` | 是 | `NULL` | `coverage_incomplete` / `no_matching_evidence` / `material_missing` | 加 `CHECK`（可空） |
| `rank` | `integer` | 否 | `0` | 同一检查项内的稳定排序（0 起） | — |
| `fingerprint` | `varchar(64)` | 是 | `NULL` | V1 语义 = K2 内容 hash `sha256(file_key\|page_key\|page_ordinal\|canonical_text)[:64]` | — |

**主键**：`id`。
**外键**：`fk_results_run (task_id, run_id) → processing_runs(task_id, id)`。
**唯一约束**：`uq_results_task_id_id (task_id, id)`（供 `decisions` / `result_sources` 的复合外键引用）。
**索引**：`ix_results_run_item_rank (run_id, check_item_id, rank, id)`、`ix_results_task_id`、`ix_results_run_id`。

**状态取值含义**

| 列 | 取值 | 含义 |
|---|---|---|
| `kind` | `text` | 文本摘录 |
| | `table` | 表格摘录 |
| | `seal` / `signature` | 视觉匹配结果（章程切片不产生） |
| | `not_found` | 未找到（`text` / `table_html` 为 `null`） |
| `not_found_reason` | `coverage_incomplete` | 该检查项因覆盖不全而未完成 → **计入受影响项** |
| | `no_matching_evidence` | 窗口已覆盖但无匹配证据 → **「正常未找到」** |
| | `material_missing` | 该检查项所需材料未上传 → **「缺材料」**（V1 两处写入：`_direct_check_result` 调用点 `processing_pipeline.py:712`、批处理路径 `:888`） |
| `relation_status` | `matched` | 关系匹配 |
| | `needs_review` | 需人工复核 |

**业务归属 vs 约束**：业务上「`not_found_reason` 只在 `kind = 'not_found'` 时有值」——**数据库无约束**；另「同一检查项可有多条 result（rank 0..n）」是**允许**的，不是违规。

### 2.12 `result_sources`

**用途**：一条摘录的出处：哪个文件、哪一页、哪个块、什么坐标。

**沿用 V1 固定提交 e525205 的 `result_sources` 表**（`models.py:543-572`，迁移 `2549094dcd38...py:115-...`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `result_id` | `uuid` | 否 | — | 所属摘录 | — |
| `file_id` | `uuid` | 是 | `NULL` | 出处文件 | — |
| `page_id` | `uuid` | 是 | `NULL` | 出处页（`ocr_pages.id`） | — |
| `block_id` | `uuid` | 是 | `NULL` | 出处块（`ocr_blocks.id`） | — |
| `start_char` | `integer` | 是 | `NULL` | 字符起偏移 | **V2 恒为 `null`**（C-9，V1 `text_search.py:433-434`、`:587-588` 显式置 `None`，因模型字符偏移不可靠） |
| `end_char` | `integer` | 是 | `NULL` | 字符止偏移 | 同上 |
| `source_page_number` | `integer` | 是 | `NULL` | 展示页码（1-based） | 与 `ocr_pages.source_page_number` 语义一致（C-6） |
| `bbox` | `jsonb` | 是 | `NULL` | `[x1,y1,x2,y2]` 页像素矩形 | — |
| `polygon` | `jsonb` | 是 | `NULL` | 多边形点集 | — |
| `location_precision` | `varchar(16)` | 否 | `'none'` | `region` / `page` / `none` | 加 `CHECK` |

**主键**：`id`。
**外键**：`fk_result_sources_result (task_id, result_id) → results(task_id, id)`；`fk_result_sources_block (task_id, block_id) → ocr_blocks(task_id, id)`。
**唯一约束**：`uq_result_sources_task_id_id (task_id, id)`。
**索引**：`ix_result_sources_task_id`、`ix_result_sources_result_id`。

**状态取值含义**：`region` = 有 bbox/polygon，可画高亮（V1 `_location_precision`，`processing_pipeline.py:389-394`）；`page` = 只能定位到页；`none` = 无可用定位。
**业务归属 vs 约束**：业务上「`bbox` 与 `page_width_px/page_height_px` 同一坐标系且在页内」——**数据库无约束**，由导入期校验保证。

### 2.13 `decisions`

**用途**：人工核对结论：每个摘录一条（接受 / 拒绝 / 未选择 + 拒绝原因 + 版本 + 结转来源）。

**沿用 V1 固定提交 e525205 的 `decisions` 表**（`models.py:579-597`，迁移 `607b61c473bc_add_task_soft_delete_and_decisions.py:36-48`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `result_id` | `uuid` | 否 | — | **主键**；每个 result 至多一条决定 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `decision` | `varchar(16)` | 否 | `'unselected'` | `unselected` / `accepted` / `rejected` | 加 `CHECK` |
| `reject_reason` | `text` | 是 | `NULL` | 拒绝原因；非 `rejected` 时恒 `null`；上限 4000 字符（应用层校验） | — |
| `version` | `integer` | 否 | `0` | 版本号；首次写入 = 1，之后每次更新 +1 | — |
| `actor_user_id` | `uuid` | 是 | `NULL` | 操作人 | **V2：可空、无 FK**（本轮无登录）；阶段 B 补 FK 并回填 |
| `updated_at` | `timestamptz` | 是 | `NULL` | 最近更新时间 | — |
| `carried_from_result_id` | `uuid` | 是 | `NULL` | 结转来源（上一轮 run 的 result） | **V2 写入**（C-3）；V1 从不写 |

**主键**：`result_id`。
**外键**：`fk_decisions_result FOREIGN KEY (task_id, result_id) REFERENCES results(task_id, id)`。
**唯一约束**：主键即唯一。
**索引**：`ix_decisions_task_id`。

**状态取值含义**：`unselected` 未选择（默认，等同无决定行）；`accepted` 已接受；`rejected` 已拒绝（原因可为空 = 草稿态，**会阻塞完成**）。
**业务归属 vs 约束**：业务上「决定只能写在 `READY` 的 run 的 result 上、且任务未完成」——**数据库无约束**，由接口校验（api-contract.md 第四节）；业务上「`reject_reason` 非空 ⟺ `decision = rejected`」——**数据库无约束**，由写入逻辑保证（V1 `decisions.py:140`、`:153`）。

### 2.14 `decision_events`

**用途**：决定变更的审计流水（前后快照）。

**沿用 V1 固定提交 e525205 的 `decision_events` 表**（`models.py:600-614`，迁移 `607b61c473bc...py:22-35`）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `id` | `uuid` | 否 | `uuid4()` | 主键 | — |
| `task_id` | `uuid` | 否 | — | 所属任务 | — |
| `result_id` | `uuid` | 否 | — | 所属摘录 | — |
| `actor_user_id` | `uuid` | 是 | `NULL` | 操作人 | V2：可空、无 FK（同上） |
| `event_type` | `varchar(32)` | 否 | — | 事件类型；**V1 唯一取值 `'update'`** | 加 `CHECK`（V2 沿用 `'update'`） |
| `before` | `jsonb` | 是 | `NULL` | 变更前快照 `{decision, reject_reason, version}` | — |
| `after` | `jsonb` | 是 | `NULL` | 变更后快照 `{decision, reject_reason, version}` | — |
| `created_at` | `timestamptz` | 否 | `now()` | 事件时间 | — |

**主键**：`id`。
**外键**：V1 **无外键**（只有索引）；V2 建议补 `FOREIGN KEY (task_id, result_id) REFERENCES results(task_id, id)`。
**唯一约束**：`uq_decision_events_task_id_id (task_id, id)`。
**索引**：`ix_decision_events_task_id`、`ix_decision_events_result_id`。

**状态取值含义**：`event_type = 'update'` 表示一次决定更新。**首次写入决定不产生事件**（V1 `decisions.py:134-145`：新建分支只 `session.add(existing)`，不写事件）。
**业务归属 vs 约束**：业务上「事件里的 `before.version` + 1 = `after.version`」——**数据库无约束**，由写入逻辑保证。

### 2.15 `view_states`

**用途**：每个（用户 × 任务 × 材料）的双栏视图状态：左栏页码与缩放、左右两栏滚动锚点。

**沿用 V1 固定提交 e525205 的 `view_states` 表的语义**（`models.py:204-215`，迁移 `4764cf6b25c6...py:97-110`）。
**V1 从未写入本表**（全库检索仅命中模型定义）；**V2 开始写入**（C-5）。

| 列 | 类型 | 可空 | 默认 | 说明 | V2 变更 |
|---|---|---|---|---|---|
| `user_id` | `uuid` | **是** | `NULL` | 用户 | **V2：可空、无 FK**（本轮无登录）；阶段 B 后纳入主键并补 FK |
| `task_id` | `uuid` | 否 | — | 任务 | — |
| `material_type` | `varchar(64)` | 否 | — | 材料 | — |
| `file_id` | `uuid` | 是 | `NULL` | 当前定位的文件 | — |
| `page_number` | `integer` | 是 | `NULL` | 左栏当前页码 | — |
| `zoom` | `double precision` | 是 | `NULL` | 缩放档位（`fit` / `1` / `1.5` / `2`） | — |
| `left_anchor` | `jsonb` | 是 | `NULL` | 左栏滚动锚点 | — |
| `right_anchor` | `jsonb` | 是 | `NULL` | 右栏滚动锚点 | — |
| `updated_at` | `timestamptz` | 否 | `now()` | 更新时间 | — |

**主键**：V1 为 `(user_id, task_id, material_type)`。**V2 变更**：本轮单操作员、无登录，若照搬 V1 主键则 `user_id` 只能塞占位值。故 **V2 主键改为 `(task_id, material_type)`**，`user_id` 降为可空列；阶段 B 引入多用户后，用一条迁移把主键改回 `(user_id, task_id, material_type)` 并回填 `user_id`。
**外键**：V1 有 `user_id → users.id`、`task_id → tasks.id`；V2 本轮只建 `task_id → tasks.id`。
**唯一约束**：主键。
**索引**：无额外索引（V1 无）。

**业务归属 vs 约束**：业务上「视图状态属于单个用户，不得互相污染」——**本轮无用户，故用 `(task_id, material_type)` 隔离；阶段 B 必须补用户维度**，否则多用户共用账号会互相覆盖页码。

## 三、页码与坐标约定

### 3.1 三种页号

| 名称 | 落库位置 | 定义 | V1 事实 |
|---|---|---|---|
| **物理页序**（physical page index） | 不单独存列 | 上传文件内 1-based 的真实页号 | V1 无此概念 |
| **provider 页序** | `ocr_pages.ocr_page_index`（0-based）、`provider_line_index`（JSONL 行号）、`provider_item_index`（`layoutParsingResults` 下标） | OCR provider 返回的页顺序 | 沿用 V1 `ocr_pipeline.py:263-265` |
| **展示页码** | `ocr_pages.source_page_number`、`result_sources.source_page_number`（1-based） | 界面上的「第 N 页」 | **V1 = `ocr_page_index + 1`**（`ocr_pipeline.py:266`），即「provider 顺序 + 1」，**不是**物理页号 |

**V2 变更（C-6）**：`source_page_number` 必须等于上传文件的物理页号。导入时把 provider 页序与物理页序对齐；无法确认时 `mapping_status` 保持 `'unverified'`，且该 run 不得进入 `READY`（拦截点待阶段 B 确认）。

**回退规则**（沿用 V1 `source_ordering.py:175-177`）：排序键取 `source_page_number`，为 `None` 时回退 `ocr_page_index`。

### 3.2 坐标系

| 项 | 约定 |
|---|---|
| `coordinate_space` | `ocr_input_image_pixels`（OCR 输入图像像素，原点左上、x 向右、y 向下）；未知时 `unknown` |
| `bbox` | 页像素 `[x1, y1, x2, y2]`，原点左上；**契约统一为 4 元数组**（V1 存储层兼容 list 与 dict 两种形态，`source_ordering.py:62-89`；V2 契约只输出数组） |
| `polygon` | 多边形点集 `[[x, y], …]`，同一坐标系 |
| `page_width_px` / `page_height_px` | 所在页的像素尺寸，取 `ocr_pages.width_px` / `height_px` |
| `location_precision` | `region`（有 bbox/polygon）/ `page`（只能定位到页）/ `none` |

### 3.3 UI 换算

bbox → 界面百分比（前端口径，V1 前端与 V2 线框一致）：

```
left   = x1 / page_width_px  * 100%
top    = y1 / page_height_px * 100%
width  = (x2 - x1) / page_width_px  * 100%
height = (y2 - y1) / page_height_px * 100%
```

〔沿用 V1 前端 `credit-review-app/frontend/src/routes/_layout/tasks/$taskId.review.tsx:756-784`；V2 线框同口径 `credit-review-app-v2/prototype/workbench.js` 的 `renderSource()`（摘录坐标换算）与 `locate()`（高亮框换算）〕

### 3.4 1191 × 1684 章程页如何映射到 UI

| 事实 | 依据 |
|---|---|
| 1191 × 1684 是 **V2 线框样本常量**，写在 `credit-review-app-v2/prototype/fixtures/charter.js` 的 `pageSize`（`export const pageSize = { width: 1191, height: 1684 }`），并被 `credit-review-app-v2/prototype/workbench.css` 的 `.sheet` 规则中 `aspect-ratio: 1191 / 1684` 用作页面容器比例 | 〔实测〕 |
| 它**不是** V1 真实 OCR 样本的输入分辨率。V1 真实 15 页样本的 `width_px` / `height_px` **无法从仓库核实**（样本文件不在仓库内，`v1-reuse.md` §六第 1 条），V1 代码只保证写 provider 返回的宽高（`ocr_normalize.py:54-58`） | 〔实测 + 尚未验证〕 |
| 因此：**阶段 B 的换算必须以 `ocr_pages.width_px` / `height_px` 为准**，用 `page_width_px` / `page_height_px` 从接口取，禁止把 1191 / 1684 写死进前端 | 〔结论〕 |

映射链路：

```
上传 PDF 的物理页 P
  → ocr_pages.source_page_number = P（V2 语义，mapping_status = verified）
  → result_sources.source_page_number = P，bbox 为该页像素坐标
  → 接口下发 page_width_px / page_height_px（= ocr_pages.width_px / height_px）
  → 前端按 3.3 的公式换算成百分比
  → 叠加缩放档位（fit / 100% / 150% / 200%）与左栏滚动定位
```

左栏渲染有两条可选实现（阶段 B 定）：①按 OCR 输入分辨率渲染页栅格并用 `ocr_pages.raster_asset_id` 关联（V2 新增，C-7）；②保留原始 PDF，由前端按 `transform_metadata` 做尺度变换换算。**V1 两条都没有**（V1 的 PDF 分支干脆不画高亮，等于回避了这个问题）。

## 四、归属与展示规则

### 4.1 重跑（同一任务新 run）

| 项 | 规则 |
|---|---|
| 触发 | 同一任务上重新发起核对（V1 每次都新建 `run_id`，如实标注「整次重跑」，`runs.py:146-154`） |
| 新 run | `processing_runs.input_revision = tasks.input_revision`（快照，不自增）；`run_files` 绑定当前生效文件集 |
| 旧 run | `state` → `SUPERSEDED`（**V2 新增实际写入**，C-2）；旧 `results` / `decisions` / `decision_events` **全部保留**，仍挂旧 `run_id` / 旧 `result_id` |
| 统计 | 旧 run 的结果与决定**不计入**新 run 的 `statistics` 与 `completion`（统计口径按 `run_id` 过滤，V1 `decisions.py:74-77`） |
| 界面 | 旧批次内容标注「来自上一批次」。数据来源：接口 `carried[]` 块（api-contract.md §3.1），以及 `decisions.carried_from_result_id` 表达的结转关系（C-3） |
| 写入 | 旧 run 状态为 `SUPERSEDED`，不满足 `READY`，因此**不可写决定、不可完成**（接口按 run 状态拦截） |

### 4.2 补传（新增材料文件）

| 项 | 规则 |
|---|---|
| 触发 | 任务已 `DRAFT`/`PROCESSING`/`REVIEWING` 时上传新文件（V1：`files.py:147-200`；已完成任务上传 → `409 TASK_READ_ONLY`） |
| 版本 | `tasks.input_revision` **+1**（**V2 新增**，C-1；V1 从不自增） |
| 新 run | 绑定新的 `input_revision` 快照；`run_files` 含新文件 |
| 旧决定 | **保留**在旧 `result_id` 上，**标记过期**：判据 = 旧 run 的 `input_revision != tasks.input_revision`（V1 已有 `is_stale` 字段，`runs.py:258`） |
| 完成 | 对旧 revision 调用 `POST /complete` → `409 REVISION_CONFLICT`，message「资料已变更，请刷新后重新核对」（V1 `runs.py:500-504` 的分支形状照抄，V2 让它可触发） |
| 界面 | 提示「资料已变更，请刷新后重新核对」；旧批次内容标注「来自上一批次」，不计入新 run 计数 |
| 写决定 | 旧 run 的决定**仍可写**（V1 语义，`PATCH` 请求体不含 `input_revision`）；因其绑定旧 `result_id`，天然不进入新 run 的统计 |

### 4.3 替换文件

| 项 | 规则 |
|---|---|
| 触发 | 上传一份**内容不同**的新文件（V1 同任务内同 sha256 直接返回既有 `file_id`，`files.py:166-169`；V2 保留该去重规则） |
| 新增 | 新 `task_files` 行 + 新 `assets` 行（`kind = original`）+ 新 `ocr_jobs` / `ocr_pages` / `ocr_blocks`（新 `file_id`） |
| 旧行 | 旧 `task_files.deleted_at` 置值（软删）；**旧 OCR 结果仍绑定旧 `file_id`，不物理删除、不迁移** |
| 版本 | `tasks.input_revision` **+1**（同补传） |
| 新 run | `run_files` 只含新的 `file_id`；旧 run 的 `run_files` 保持不变 |
| 决定 | 旧决定保留在旧 `result_id` 上，标记过期（同补传） |

### 4.4 三种情况的对照

| | 重跑 | 补传 | 替换文件 |
|---|---|---|---|
| `tasks.input_revision` | 不变 | +1 | +1 |
| 新 run | 是 | 是（须重跑才有新结果） | 是（须重跑才有新结果） |
| 旧 run 状态 | `SUPERSEDED` | 保留原状态（`READY` 但 stale） | 保留原状态（`READY` 但 stale） |
| 旧结果 / 旧决定 | 保留在旧 run | 保留在旧 run | 保留在旧 run |
| 计入新 run 统计 | 否 | 否 | 否 |
| 旧 run 能否完成 | 否（非 `READY`） | 否（`409 REVISION_CONFLICT`） | 否（`409 REVISION_CONFLICT`） |
| 界面标注 | 「来自上一批次」 | 「来自上一批次」+「资料已变更，请刷新后重新核对」 | 同补传 |

## 五、覆盖与窗口覆盖

### 5.1 唯一事实源

`processing_runs.coverage_complete`（`BOOLEAN NOT NULL DEFAULT false`）是覆盖状态的**唯一事实源**：

| 角色 | 谁 | 说明 |
|---|---|---|
| **写** | worker（跑 run 的进程） | 判定后写 `processing_runs.coverage_complete`；无单元步时同时写 `processing_runs.error_code = 'COVERAGE_NO_UNIT_STEPS'` |
| **读** | API 层 | **只读**，永不重新推导 |
| **人工决定** | 办理人 | **永不替代**覆盖事实 |

V1 明确删除过 API 侧的反推逻辑（原 `or not coverage.coverage_complete` 的双事实源 AND 写法），并留下注释说明「删的是反推，不是覆盖拦截本身」〔沿用 `runs.py:506-509`〕。V2 继承这一收敛。

**受影响项的决定**：受影响检查项的 `results` 行**仍可能带 `decisions` 行**（接口层当前不拦截，沿用 V1 语义），但写入决定**不改变** `processing_runs.coverage_complete`，因此 `POST /complete` 仍返回 `409 COVERAGE_INCOMPLETE`〔沿用，`runs.py:506-518`〕。线框当前**不提供**受影响项的接受/拒绝入口〔实测〕，接口层是否禁止写入受影响项待产品确认（charter.md 开放问题 3）。

### 5.2 判定口径（worker 侧）

| # | 规则 | 依据 |
|---|---|---|
| 1 | 文本检查项集合 = 清单快照中 `result_mode ∉ {seal, signature}` 的叶子项。**印章/签名走视觉匹配，没有「应查窗口」，排除在窗口覆盖之外** | `processing_pipeline.py:180-184` |
| 2 | 受影响集合 = 该 run 中 `results.not_found_reason = 'coverage_incomplete'` 的检查项 | `processing_pipeline.py:188-192` |
| 3 | 单元步 = `run_steps.step_key` 以 `u:` 或 `check:` 开头的行 | `processing_pipeline.py:198-202` |
| 4 | 覆盖达成 = 该检查项在本次 run **有 `results` 行** 且 **不在受影响集合**（无结果行 = 未处理 = 未覆盖） | `processing_pipeline.py:226-233` |
| 5 | 无任何单元步 → `coverage_complete = false` + `error_code = 'COVERAGE_NO_UNIT_STEPS'`（保守判定，**不回退持久化值**，避免循环依赖） | `processing_pipeline.py:213-222` |
| 6 | 清单中无文本检查项（仅视觉匹配）→ `coverage_complete = (存在单元步)` | `processing_pipeline.py:204-211` |
| 7 | 完整覆盖 → `coverage_complete = true` | `processing_pipeline.py:231-245` |

### 5.3 窗口覆盖怎么记录

| 层级 | 记录位置 | 内容 | V2 状态 |
|---|---|---|---|
| 窗口批次 | `run_steps` | `step_key = 'u:w{wi}:b{bi}'`（`w` 序号 + `b` 批序号），`input_hash = sha256(step_key\|extra)[:64]`，唯一约束 `uq_run_steps_key_hash` 保证同键同输入 upsert | **V2 沿用 V1 键格式**（`processing_pipeline.py:640`） |
| 阶段 | `run_steps` | `step_key = 'stage:classify\|search\|vision'` | 沿用（`processing_pipeline.py:987`、`:1002`、`:1017`） |
| 检查项 | `run_steps` | `step_key = 'check:{check_item_id}'` | 沿用（`processing_pipeline.py:656`） |
| **检查项 × 窗口** | `check_executions.coverage`（JSONB） | `windows` / `window_count` / `covered` / `not_found_reason` / `covered_blocks`，见 §2.10 | **V2 新增写入**（V1 有表无数据，C-5） |

**分工**：`run_steps` 记录「跑了哪些窗口批次」；`check_executions.coverage` 记录「哪个检查项被哪些窗口覆盖」；`processing_runs.coverage_complete` 记录「整体覆盖是否达成」。**只有最后一个是判定依据**，前两者是过程证据。

**禁止事项**（V1 踩过的坑）：不得用「扫描 `run_steps.step_key` 前缀」来判定某个检查项是否被覆盖。V1 早期按前缀扫描，后改为直接读结果行的 `not_found_reason`（`processing_pipeline.py:168-171` 注释）。V2 的 `check_executions.coverage` 是**记录**窗口归属，不是**判定**覆盖与否。

## 六、状态枚举取值全表

| 列 | 取值 | 含义 | 来源 |
|---|---|---|---|
| `tasks.state` | `DRAFT` / `PROCESSING` / `REVIEWING` / `FAILED` / `COMPLETED` | 任务状态 | V1 `models.py:36-41` |
| `tasks.customer_role` | `borrower` / `guarantor` / `pledgor` | 客户角色 | V1 `models.py:20-23` |
| `tasks.product_code` | `working_capital_loan` | 产品代码 | V1 `models.py:26-27` |
| `processing_runs.state` | `QUEUED` / `RUNNING` / `READY` / `FAILED` / `SUPERSEDED` | run 状态 | V1 `models.py:51-56` |
| `run_steps.state` | `QUEUED` / `RUNNING` / `SUCCEEDED` / `FAILED` / `SUPERSEDED` | 步骤状态 | V1 `models.py:59-64` |
| `run_files.effective_material_type` / `task_files.manual_material_type` | `business_license` / `articles_of_association` / `audited_financials` | 材料类型；章程 = `articles_of_association` | V1 `models.py:30-33` |
| `ocr_jobs.state` | `NOT_SUBMITTED` / `SUBMITTED` / `RUNNING` / `DOWNLOADING` / `SUCCEEDED` / `FAILED` / `SUBMISSION_UNKNOWN` | 识别作业状态 | V1 `models.py:241-248` |
| `ocr_pages.mapping_status` | `verified` / `unverified` | 页码映射是否已校验 | V1 `models.py:264-266`（语义 V2 变更 C-6） |
| `ocr_pages.coordinate_space` | `ocr_input_image_pixels` / `unknown` | 坐标系 | V1 `ocr_normalize.py:59` |
| `assets.kind` | `original` / `ocr_raw` / `page_raster` / `crop` | 资产类型 | V1 `models.py:44-48` |
| `results.kind` | `text` / `table` / `seal` / `signature` / `not_found` | 摘录类型 | V1 `models.py:72-77` |
| `results.not_found_reason` | `coverage_incomplete` / `no_matching_evidence` / `material_missing` | 未找到的三档原因 | V1 `processing_pipeline.py:671`、`:673`、`:888` |
| `results.recognition_source` | `ocr` / `vision` | 识别来源 | V1 `models.py:80-82` |
| `results.relation_status` | `matched` / `needs_review` | 关系状态 | V1 `models.py:85-87` |
| `check_executions.search_status` | `found` / `not_found` | 搜索命中 | V1 `models.py:67-69` |
| `result_sources.location_precision` | `region` / `page` / `none` | 定位精度 | V1 `models.py:90-93` |
| `decisions.decision` | `unselected` / `accepted` / `rejected` | 人工决定 | V1 `models.py:96-99` |
| `decision_events.event_type` | `update` | 事件类型（V1 唯一取值） | V1 `decisions.py:163` |

## 七、尚未验证清单

| # | 项 | 现状 | 阶段 B 验证方式 |
|---|---|---|---|
| 1 | 真实 15 页章程样本的 OCR 输入像素尺寸与 `coordinate_space` 实际取值 | 样本文件不在仓库内，只能从线框 bbox 反推 | 用本地批准样本导入后读 `ocr_pages.width_px` / `height_px` |
| 2 | `source_page_number` 是否真等于物理页号 | V1 从不验证（`mapping_status` 恒 `unverified`）；V2 语义已改为物理页号但未跑过 | 导入后断言 `source_page_number` == 物理页号且 `mapping_status = 'verified'` |
| 3 | 页栅格写入路径（C-7） | V1 从不写 `raster_asset_id`；V2 方案未定（栅格渲染 or PDF 渲染换算） | 导入后 `ocr_pages.raster_asset_id` 非空，或 `transform_metadata` 足以换算 |
| 4 | `check_executions.coverage` 的 JSONB 结构 | **V2 约定，V1 无先例**，未被任何代码消费过 | 导入后断言每个文本检查项一行、JSONB 键齐全且与 `results` 一致 |
| 5 | `tasks.input_revision` 自增的三个触发点（补传 / 替换 / 删除） | V1 从不自增（C-1） | 补传/替换/删除各一次，断言 `input_revision` +1、旧 run 变 stale、`POST /complete` 返回 `409 REVISION_CONFLICT` 且 `tasks` 行零写入 |
| 6 | 旧 run 置 `SUPERSEDED`（C-2） | V1 从不写该值 | 重跑后断言旧 run `state = 'SUPERSEDED'`、旧结果与旧决定仍在旧 run 上 |
| 7 | 缺材料完成规则 | 待产品决策 | 见 charter.md 第三节；未定则该场景的完成契约无法冻结 |
| 8 | `view_states` 主键改为 `(task_id, material_type)` 的阶段 B 改回方案 | V2 新设计 | 阶段 B 加 `users` 时验证回填脚本与主键迁移 |
