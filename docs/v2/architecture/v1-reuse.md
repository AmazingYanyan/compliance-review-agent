# V1 复用评估 · V2「对公信贷资料核对」

本轮目的：为 V2 阶段 A 判定 V1（冻结于 `e52520553f3efe8e790fb608e630bf29bab9c1bf`）的七个候选实现能否迁入 V2、迁到什么程度、怎样复验。阶段 A 只做设计评审与契约冻结，不改 `credit-review-app-v2/`，不改 `data-dictionary.md`。

## 零、证据标注约定

| 标注 | 含义 |
|---|---|
| 本轮实测 | 本轮实际读过 V1 源码并给出 `file:line`，或实际在仓库里执行过命令核对 |
| 历史沿用 | V1 既有的结论或既有文档记载，本轮未重新验证 |
| 尚未验证 | 需要阶段 B 实跑或真实样本才能定论 |

全部 `file:line` 均为**相对 V1 固定提交**的路径与行号（仓库根相对）。取值方式见文末「与 V1 固定提交的引用方式」。

## 一、结论速览

| # | 候选 | 采用方式 | 一句话理由 | 阶段 B 复验方式 |
|---|---|---|---|---|
| 1 | OCR 规范化 | **抽取后复用** | `parse_page` 的字段映射（page_meta/blocks/crops）是纯结构解析、与 provider 无关，可整段抽成 V2 解析器；但 provider 的 `inputImage`/`outputImages` 从未被解析，**页栅格图在 V1 根本不存在** | AC-R1：同一份固定 OCR JSONL 分别喂 V1 `parse_page` 与 V2 解析器，diff 输出字段集 |
| 2 | 页码与坐标约定 | **抽取后复用 + 1 处约定变更** | 字段形状（`source_page_number` 1-based、`coordinate_space` 二值、bbox `[x1,y1,x2,y2]`）可直接沿用；但 V1 的 `source_page_number` 只是「provider 返回顺序 + 1」，`mapping_status` 永远是 `unverified`，**没有物理页码校验**，而 V2 章程切片要求「第 15 页」能对上左侧原件 | AC-R2：V2 跑固定样本后断言 `source_page_number` == 上传文件物理页号、`mapping_status` 为 `verified`、bbox 落在 `[0,w_px]×[0,h_px]` |
| 3 | 稳定分窗 | **抽取后复用（本轮只抽排序键与覆盖口径）** | `order_blocks` 的 `(file_order, page_key, page_ordinal)` 与 K2 内容 hash 是「无 UUID、可复算」的排序契约，值得直接继承；但阶段 B 的章程切片用固定摘录、不重跑 LLM，**本轮不需要真正的分窗与批处理** | AC-R3：同一固定 OCR 输入两次导入，窗口 `bundle_id` 序列与 `content_hash` 完全一致 |
| 4 | 并发派发 | **本轮不迁** | V1 队列（procrastinate + PG 持久化 + worker concurrency=3 + 任务内线程池 C）是为「跑 OCR、跑 LLM」设计的；阶段 B 验收（两条 409 + 一个 200）没有后台长任务，迁队列等于给隔离库多加一套 procrastinate 表 | 无（阶段 B 无队列用例）；「处理中」场景先用同步状态字段表达 |
| 5 | 证据去重 | **抽取后复用** | `_dedup_evidence` 的键 `(check_item_id, content_hash)` + 排序键 `(source_page_number, page_ordinal, content_hash)` 是纯内容算术，与 provider、DB、队列都解耦，机制可整体搬运；但 V2 固定样本只有 4 条摘录，去重收益极小，**机制先备而不必先实现** | AC-R5：同一摘录被两个检查项引用 → 落两条 Result、各自 rank 稳定且互不吞并 |
| 6 | 任务与文件管理 | **重做（版本语义）+ 抽取后复用（上传/去重/资产流）** | 上传/SHA256 去重/资产创建/DRAFT→PROCESSING 可直接抽；但 **`task.input_revision` 在 V1 全代码里从不自增**（只有创建时置 0、run 创建时拷贝），所以 V1 没有「补传使旧结果失效」这回事，V2 必须自己实现 | AC-R6：补传/替换后 `task.input_revision` +1，旧 run 变 stale，`POST /complete` 返回 409 `REVISION_CONFLICT` 且零写入 |
| 7 | 固定测试样本 | **抽取后复用（并须脱敏重建）** | `mock_llm_server.py` 是纯标准库、零 DB、零凭据的 OpenAI 兼容服务，固定响应规则完备；`run_quick_acceptance.py` 的 `_fixed_non_search` / `_dynamic_search` / `_create_synthetic` 是现成的「固定模型响应 + 固定任务造数」夹具；但真实 15 页 OCR JSON、V1 账号口令、`.env` 凭据、两个真实任务 UUID 不可搬 | AC-R7：`mock_llm_server` 与 `verify_quick_acceptance.py --self-test` 在 V2 仓库内自检通过；固定样本进 V2 仓库前过脱敏检查 |

---

## 二、逐项评估

### 2.1 OCR 规范化（候选 1）

**V1 实现**（本轮实测）

- 入口 `parse_jsonl(jsonl_bytes)` — `credit-review-app/backend/app/ocr_normalize.py:11-28`：逐行 JSON 解析 provider JSONL，每行形如 `{"logId":…,"result":{"layoutParsingResults":[page,…]}}`，产出 `[{line_index, item_index, page}]`。注意 `:22-24` 对 `JSONDecodeError` **静默跳过**该行，既不计数也不报错。
- 入口 `parse_page(page)` — `ocr_normalize.py:48-95`，返回 `(page_meta, blocks, crops)`：
  - `page_meta`（`:54-61`）：`width_px` / `height_px` 取 `prunedResult.width/height`，且**仅当 `isinstance(width, int)` 才保留**，否则置 `None`；`coordinate_space` = `"ocr_input_image_pixels"`（有宽高时）否则 `"unknown"`；`transform_metadata` = `prunedResult.doc_preprocessor_res`。
  - `blocks`（`:66-83`）：`provider_block_id` / `group_id` / `global_block_id` / `global_group_id` / `sequence_index`（取 `block_order`，缺失则用枚举序号）/ `label` / `canonical_text`（`BeautifulSoup.get_text("\n")` 后 `strip()`，`ocr_normalize.py:31-35`）/ `table_html`（`label=="table"` 或正文含 `<table` 时保留**原始 HTML**）/ `bbox` = `block_bbox` / `polygon` = `block_polygon_points`。
  - `crops`（`:84-94`）：块内每个 `<img src>` 生成一条独立 crop，`kind` 由 `_kind_from_label` 映射为 `seal|signature|image|unknown`（`:38-45`），`image_url` 取 `markdown.images[src]`，`recognized_text` 直接复用块内可见文字（注释「印章文字来自块内可见文字」），bbox/polygon 复制自所属块。
- 落库 `_ingest()` — `credit-review-app/backend/app/ocr_pipeline.py:252-311`：逐页写 `OcrPage`（`:259-272`）、逐块写 `OcrBlock`（`:276-279`）、逐 crop 写 `Crop`（`:282-308`）并下载裁剪图归档到 `ocr/{task_id}/{file_id}/{ocr_job_id}/crops/{crop.id}.jpg`，同时建 `Asset(kind="crop")` 并回填 `crop.image_asset_id` / `image_status`（`:296-308`）。
- 离线导入旁路 `import_ocr_json()` — `credit-review-app/backend/app/cli.py:114-211`：直接读 PaddleOCR-VL 导出的「每页一个对象」JSON 数组，复用同一个 `parse_page`（`cli.py:175`），但**不下载图片**（`cli.py:195` 注释：「外部结果图片（带签名 URL）不下载，仅记录元数据」）。

**规范化了什么 / 保留了什么 / 丢了什么**（本轮实测）

| 维度 | 结论 | 证据 |
|---|---|---|
| 保留 | 页像素宽高 | `ocr_normalize.py:54-58` → `ocr_pipeline.py:268-269` |
| 保留 | `coordinate_space` 字符串 | `ocr_normalize.py:59` → `ocr_pipeline.py:270` |
| 保留 | 块 bbox / polygon（原样 JSONB） | `ocr_normalize.py:80-81`；模型列 `models.py:352-353` |
| 保留 | provider 块标识（4 个 id） | `ocr_normalize.py:72-75`；`models.py:344-347` |
| 保留 | provider 行/项序号 | `ocr_pipeline.py:263-264` → `models.py:311-312` |
| 保留 | 表格原始 HTML | `ocr_normalize.py:79` |
| 丢失 | **页栅格图**：provider JSON 的 `inputImage` / `outputImages` 从未被 `parse_page` 读取 | `ocr_normalize.py:48-95` 全文无引用；`cli.py:117` 明说输入 JSON 含 `inputImage`/`outputImages` |
| 丢失 | 裁剪图的**签名 URL**：`Crop` 模型没有 `image_url` 列 | `models.py:372-401`；`cli.py:196-209` 只落 bbox/polygon/状态 |
| 丢失 | 块原始 HTML（除表格外只留剥离后的纯文本） | `ocr_normalize.py:78-79`；`OcrBlock.raw_content_ref`（`models.py:354`）**全库无写入方** |
| 丢失 | provider 页序 → 物理页的映射证据 | `models.py:315` `mapping_status` 恒为 `unverified`（见 2.2） |
| 风险 | JSONL 坏行静默丢弃 | `ocr_normalize.py:22-24` |

**判定：抽取后复用。**
WHY：`parse_page` 是纯函数（输入 provider 页对象 → 三个 Python 字典），不含 DB、不含网络、不含 provider SDK，字段映射规则清晰。V2 只要把 `ocr_normalize.py` 与 `ocr_pipeline._ingest` 的**落库部分**拆开，就得到一个可独立测试的「V2 OCR 解析器」。但**不能整文件照抄**：V1 的 `_ingest` 与 `ocr_jobs` 状态机、`Asset` 落盘路径强耦合 V1 表结构；V2 的 `ocr_*` 表是新建的（见 `docs/v2/architecture/data-dictionary.md`）。

**V2 需要补的一处（本轮实测推出的缺口）**：V1 从未产出页栅格图，`OcrPage.raster_asset_id`（`models.py:316`）与 `AssetKind.page_raster`（`models.py:47`）只有定义、没有写入方（全库检索 `raster` 仅命中模型、迁移与 `runs.py:358` 的响应字段）。V2 章程切片左侧要显示「原件页 + 高亮」，**必须有页栅格或 PDF 渲染坐标映射**，这是 V1 没有的、V2 必须新做的部分。

**怎样复验**：阶段 B 验收用例 **AC-R1**：取一份脱敏后的固定 OCR JSONL，同一份输入分别喂 V1 `parse_page`（从 `e525205` 取回的只读副本）与 V2 解析器，断言两者的 `page_meta` / `blocks` / `crops` 字段名集合与取值逐项一致（允许 V2 增字段不减字段）。同时断言：JSONL 中坏行不静默消失（V2 需显式记 `bad_lines` 或失败码）。

### 2.2 页码与坐标约定（候选 2）

**V1 的事实**（本轮实测）

`OcrPage`（`models.py:304-334`）：

| 字段 | V1 取值 | 证据 |
|---|---|---|
| `provider_line_index` | 该页出现在 provider JSONL 的第几行 | `ocr_pipeline.py:263`；`cli.py:180` |
| `provider_item_index` | 该页在 `layoutParsingResults` 数组中的下标 | `ocr_pipeline.py:264`；`cli.py:181` |
| `ocr_page_index` | 0-based 的 provider 页序 | `ocr_pipeline.py:265`；`cli.py:182` |
| `source_page_number` | **`ocr_page_index + 1`**（1-based） | `ocr_pipeline.py:266`；`cli.py:183` |
| `mapping_status` | 恒为 `"unverified"` | `ocr_pipeline.py:267`；`cli.py:184`；`PageMappingStatus.verified`（`models.py:264-266`）**无任何写入方** |
| `width_px` / `height_px` | provider 输入图像像素 | `ocr_pipeline.py:268-269` |
| `coordinate_space` | `"ocr_input_image_pixels"` \| `"unknown"` | `ocr_normalize.py:59`；`models.py:319` 默认 `"unknown"` |
| `transform_metadata` | `doc_preprocessor_res` 原样 | `ocr_normalize.py:60` |
| `raster_asset_id` | **从不赋值** | `models.py:316`；全库无写入 |

关键推论：`source_page_number` **不是**从上传文件的物理页码读出来的，而是「provider 返回顺序 + 1」。V1 从未把它与真实 PDF 页核对过，`mapping_status` 永远停在 `unverified`（本轮实测：全库 6 处 `mapping_status` 命中全部写死 `"unverified"`）。

**bbox 形状 `[x1,y1,x2,y2]`**（本轮实测，三处独立印证）：

- `source_ordering._bbox_top_left()` — `credit-review-app/backend/app/source_ordering.py:62-89`：`bbox[0]` 取作 left(x)、`bbox[1]` 取作 top(y)，`len>=4` 才认；另兼容 dict 形式（`top/left`、`y/x`、`y1/x1`）。
- 前端 `ImagePreview` — `credit-review-app/frontend/src/routes/_layout/tasks/$taskId.review.tsx:756-784`：`left = bbox[0]/pageWidth*100`、`top = bbox[1]/pageHeight*100`、`width = (bbox[2]-bbox[0])/pageWidth*100`、`height = (bbox[3]-bbox[1])/pageHeight*100`。
- 造数夹具 — `credit-review-app/backend/tests/perf/run_quick_acceptance.py:176`：`bbox=[100, 100+idx*200, 900, 180+idx*200]`。
- V2 现有原型固定样本同形 — `credit-review-app-v2/prototype/fixtures/charter.js` 的 `evidence[0].bbox`：`bbox: [105,107,1047,276]`。

**页栅格怎么定位**（本轮实测）：V1 根本没有页栅格。左侧「原件」是**直接渲染上传的原始文件**：
- PDF：`react-pdf` 的 `<Document file={assetUrl}><Page pageNumber={pageNumber}/>`（`review.tsx:743-744`），`pageNumber` 来自 `src.source_page_number`（`review.tsx:1135-1151`，赋值在 `:1149`）；**PDF 分支不画高亮框**（`PdfViewer` 无 overlay）。
- 图片：`<img src={assetUrl}>` + 按 bbox/页尺寸百分比画的绝对定位高亮框（`review.tsx:756-784`）。
- 资产下载走 `assets.py:14-44`：先校验任务归属（否则 404），再查资产、落 `FileResponse`。

**判定：抽取后复用 + 1 处约定变更。**
WHY：字段与形状可以逐字沿用（`_dedup_evidence` 与前端高亮都依赖它，V2 换形状会同时打断去重排序与高亮）。**必须变更的一处**：`source_page_number` 的语义要从「provider 顺序 + 1」升级为「上传文件的 1-based 物理页码」，并补一条「页映射验证」步骤把 `mapping_status` 从 `unverified` 推到 `verified`；否则 V2 章程切片的「第 15 页」在多文件或 provider 乱序时可能指错页。

**V2 需要补的第二处**：`bbox` 的坐标空间是 **OCR 输入图像像素**，与前端渲染的 PDF 页像素尺度不同（PDF 渲染由 react-pdf 自行缩放）。V1 对 PDF 干脆不画高亮，等于回避了这个问题；V2 若要「点出处 → 左侧高亮」，必须二选一：①按 OCR 输入分辨率渲染页栅格并用 `raster_asset_id` 关联；②在 `transform_metadata` 里记录尺度变换并在前端换算。这条无法从 V1 复用。

**怎样复验**：**AC-R2** —— 用固定样本（V2 自带的、已确认是脱敏/合成或已获授权的章程页）跑 V2 导入后断言：①`source_page_number` 等于该页在上传 PDF 中的物理页号；②`mapping_status == "verified"`；③每个块的 bbox 满足 `0 ≤ x1 < x2 ≤ width_px`、`0 ≤ y1 < y2 ≤ height_px`；④`coordinate_space` 只取 `ocr_input_image_pixels`；⑤点「第 15 页」出处，左侧能定位到同一页并画出框。**当前样本的真实 OCR 输入宽高尚未验证**——`ocr15.json` 不在仓库内（`tests/perf/fixtures/` 仅有 `fault_injection_rules.json`、`fixed_responses.json`、`quick_acceptance.json` 三个文件），只能从原型 bbox 反推页宽 ≥ 1057（`charter.js:30-36`）。

### 2.3 稳定分窗（候选 3）

**V1 实现**（本轮实测）

- 运行配置 `build_run_config()` — `credit-review-app/backend/app/processing_pipeline.py:94-122`。其中分窗策略冻结为 `window_strategy`（`:102-108`）：
  - `max_chars = settings.LLM_WINDOW_CHARACTERS`（默认 8000，`config.py:82`）
  - `overlap_chars = settings.LLM_WINDOW_OVERLAP_CHARACTERS`（默认 500，`config.py:83`）
  - `stable_sort_key = "(file_order, page_key, page_ordinal)"`
  - `bundle_id = "w{idx}"`
  - `content_hash = "sha256(file_key|page_key|page_ordinal|canonical_text)[:64]"`
- 分窗实现 `chunk_source_blocks()` — `credit-review-app/backend/app/text_search.py:147-163`：贪心装填；超预算就封窗，然后 `_recede()`（`:166-174`）从尾部回退保留若干块直到累计 ≥ `overlap_chars`；窗口号 `w0,w1,…` 按出现顺序，**稳定**。
  - 已知口径差异（本轮实测）：字符预算只按 `len(block.text)` 计（`text_search.py:155`），**不含**表格 HTML、也不含 `_window_text()` 给每块加的 `block_id=… 文本="…"` 外壳（`text_search.py:135-144`），所以实际 prompt 体积显著大于 `max_chars`。V1 如此，V2 若沿用需在契约里写明。
- 排序稳定性的真正来源 `order_blocks()` — `source_ordering.py:161-229`：
  - `file_order` = 按 `str(file_id)` 字典序的 0-based 序号（`:199-200`）——**含 UUID，不跨导入稳定**；
  - `file_key` = `TaskFile.sha256`（内容稳定，无 UUID），缺失回退 `file-order-{n}`（`:213`）——**跨导入稳定**；
  - `page_key` = `source_page_number`，为 `None` 时回退 `ocr_page_index`（`:175-177`）；
  - 页内阅读顺序 = 复合键 `(bbox top-left, sequence_index, provider_block_id, global_block_id, sha256(canonical_text))`（`:145-158`），并用 `_choose_order_source()`（`:129-142`）记录**实际由哪一级决定**（`bbox` / `sequence_index` / `provider_block_id` / `global_block_id` / `canonical_text_sha256`，常量见 `:32-36`）；全部回退时挂 `ORDER_FALLBACK_NOTE = "旧数据回退、阅读顺序不保证"`（`:37`）。
  - `page_ordinal` = 页内排序后的 0-based 序号（`:212`）；`content_hash` = `sha256(file_key|page_key|page_ordinal|canonical_text)[:64]`（`:214` + `content_hash()` `:56-59`）。
- step_key 方案（`processing_pipeline.py`）：
  - 单元步 `u:w{wi}:b{bi}` — `_write_unit_step()`（`:634-645`，键串在 `:640`）
  - 检查项步 `check:{check_item_id}` — `_direct_check_result()`（`:656`）与 `_flush_check()`（`:677`）
  - 阶段步 `stage:classify|search|vision` — `:987`、`:1002`、`:1017`
  - `input_hash` = `sha256(step_key|extra)[:64]`（`_step_key_hash` `:257-259`），`extra` 用无 UUID 的稳定内容 hash（`_stable_leaf_hash` `:262-265`）
- 覆盖口径单一事实源 `compute_coverage_summary()` — `:160-245`：`coverage_affected_check_ids` **直接读 `Result.not_found_reason == "coverage_incomplete"`**（`:188-192`），不依赖 step_key 前缀；「单元步」= 前缀为 `u:` 或 `check:` 的步（`:198-202`）；本 run 无任何单元步 → 保守 `coverage_complete=False` + `error_code="COVERAGE_NO_UNIT_STEPS"`（`:213-222`）。

**判定：抽取后复用（本轮只抽排序键 + 覆盖口径，暂不实现分窗器）。**
WHY：`source_ordering` 的「无 UUID、可复算」排序契约是 V1 最值得继承的部分，它同时服务于去重键、结果 rank 与前端可复现性。**但阶段 B 的章程切片不重跑 LLM**：V2 用的是 4 条固定摘录（`credit-review-app-v2/prototype/fixtures/charter.js` 的 `evidence` 固定样本），验收目标是「两条 409 + 一个 200」，不是「窗口覆盖率」。V2 此刻真正需要从这段借的是：①`Result.not_found_reason == "coverage_incomplete"` 这个**覆盖事实在结果行里、而不是在步骤表里**的口径（V2 的 `COVERAGE_INCOMPLETE` 拦截要落在同一处）；②`check:` / `u:` step_key 不参与展示判定这条经验（`:169-171`）。

**怎样复验**：**AC-R3** —— 对同一份固定 OCR 输入做两次独立导入，断言两次的窗口 `bundle_id` 序列、每窗块序列、每块 `content_hash` 完全一致；并断言跨导入后 `Result.rank` 不变（`text_search.py:254-263` 的排序键不含随机 block_id）。**AC-R3b** —— 阶段 B 覆盖判定断言：V2 的 `COVERAGE_INCOMPLETE` 必须来自结果行的 `not_found_reason`，不是来自 step_key 前缀扫描（防止重演 V1 早期双事实源问题，见 `processing_pipeline.py:168-171` 的注释）。

**可直接搬走的分窗基线（本轮实测自 `tests/perf/README.md:216`，属**历史沿用**）**：V1 在同一份 15 页章程样本上实测得「均 **2 窗口**：w0 = 133 块 / 7998 字，w1 = 51 块 / 2095 字；两次导入完全一致、176/176 全覆盖、窗口内顺序单调」。V2 阶段 B 若沿用同一份样本与 `LLM_WINDOW_CHARACTERS=8000`，这两个窗口的块数/字数就是现成的**期望值基线**，可直接做回归比对。

### 2.4 并发派发（候选 4）

**V1 实现**（本轮实测）

- 队列 `credit-review-app/backend/app/queue.py`：
  - `app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_dsn()))`（`:20-22`），`_dsn()` 把 `postgresql+psycopg://` 改写成 `postgresql://`（`:12-17`）。
  - `enqueue(task, **task_kwargs)`（`:25-31`）：`with app.open(): task.configure(task_kwargs=…).defer()` —— **独立事务**，用于 API 进程。
  - `enqueue_in_session(session, task, **task_kwargs)`（`:34-41`）：取 `session.connection().connection.dbapi_connection` 作为 `connection` 传入 `defer()` → **与业务写入同一事务**，业务回滚则不入队。`runs.py:142` 的 `enqueue_in_session(session, run_pipeline, run_id=…)` 就是「run 创建 + 入队」原子提交的用法。
- Worker `credit-review-app/backend/app/worker.py:13-16`：`app.run_worker(concurrency=3)` —— 3 个并发任务槽；两个队列名：`ocr`（`ocr_pipeline.py:34/128/210`）与 `processing`（`processing_pipeline.py:965`）。
- **任务内**还有第二层并发：`_search_stage()` — `processing_pipeline.py:685-848`。
  - 单元 = （窗口 × 检查项批次）；批次按材料分组、清单顺序切 X（`:731-742`，`X = settings.CHECKS_PER_REQUEST`，取值只能 1/2/3/6，见 `config.py:96-100`）；请求数 = `ceil(检查项数/X) × 窗口数`。
  - 全部单元一次性 `pool.submit` 到 `ThreadPoolExecutor(max_workers=settings.LLM_MAX_IN_FLIGHT)`（`:777-784`），`as_completed` 先回先收（`:786`）；**模型线程只调 LLM 不写库**，收集端用短事务归并（`_flush_check` `:662-682`）。
  - 全局唯一在途上限是 `llm_client` 的模块级 `BoundedSemaphore`（`credit-review-app/backend/app/llm_client.py:117`，`config.py:74-75` 说明「改值必须重启容器」），`complete_json` 首次请求与格式修复**分别** acquire（`llm_client.py:257-263`、`:362-364`，因 BoundedSemaphore 不可重入）。
  - 致命错误（鉴权/参数）→ `LLM_FATAL` → 立即把该批检查项落 FAILED 并 `raise` → run 标 FAILED（`:838-846`、`:923-929`）。
  - 单元观测步 `u:w{wi}:b{bi}` + 七类批内短码（`FORMAT_FAILED`/`OUTPUT_TRUNCATED`/`BATCH_MISSING_CHECK`/`BATCH_DUPLICATE_CHECK`/`INVALID_CHECK_ID`/`INVALID_BLOCK_REF`/`BATCH_TIMEOUT`，见 `text_search.py:491-595`）。

**判定：本轮不迁。**
WHY：阶段 B 的三条验收用例（两个 409、一个正常 200）**不产生任何后台长任务**：V2 的章程样本是固定摘录，「处理中」场景在原型里是浏览器模拟。若现在引入 procrastinate，等于给 V2 的隔离库再加一套 procrastinate 表、又一个 worker 容器、又要处理「同事务入队」这些与 V2 契约无关的复杂度。V1 队列是「跑 OCR + 跑 LLM」的实现细节，不是业务契约。

**怎样复验**：阶段 B **无队列验收用例**。建议在契约里显式写明「V2 阶段 B 同步处理」，并把「处理中」写成由 `run.state`（`models.py:51-56` 的 `QUEUED/RUNNING/READY/FAILED/SUPERSEDED`）表达的前端状态，而不是由队列 worker 表达。若阶段 B 之后要上真 OCR/LLM，再单列一轮迁移评估（届时需要复核 `enqueue_in_session` 的同事务语义与 `LLM_MAX_IN_FLIGHT` 的模块级固化问题）。

### 2.5 证据去重（候选 5）

**V1 实现**（本轮实测）

- `Result.fingerprint` — `models.py:525`（`str | None`，max 64）。语义**本轮已被改过一次**：V1 内部把它从「含随机 OcrBlock UUID + 字符偏移」改成 **K2 内容 hash**（`text_search.py:8-11`、`:230-238`、`:280-286`；写入处 `processing_pipeline.py:367` 注释「语义本轮改为 K2 内容 hash」）。
- 内容 hash 定义 `content_hash(file_key, page_key, page_ordinal, canonical_text)` — `source_ordering.py:56-59`：`sha256(f"{file_key}|{page_key}|{page_ordinal}|{canonical_text}")[:64]`，**不含 UUID、不含字符偏移**，跨导入可复算。
- 去重 `_dedup_evidence(evidence, check_item_id)` — `text_search.py:241-266`：
  - 去重键 `(check_item_id, content_hash)`；
  - 排序键 `(source_page_number or 0, page_ordinal, content_hash)` — **不含随机 block_id**，所以 `Result.rank` 与响应到达顺序无关（语义注释 `:249`，代码 `:254-263`）。
  - 语义边界（同文件 `:243-249` 注释 + 实测代码）：同检查项同出处同原文 → 只留 1 条（跨窗口重叠引用被吃掉）；同文不同出处 → `page_ordinal` 不同 → hash 不同 → **全部保留**；同出处支持多个检查项 → 键含 `check_item_id` → **互不干扰**。
- 跨窗口去重在收集端：`_search_stage` 里 `agg.evidence.setdefault(ev.content_hash, ev)`（`processing_pipeline.py:826`），落库前再过一次 `_dedup_evidence(list(agg.evidence.values()), cid)`（`processing_pipeline.py:665`）。
- 窗口内去重：`validate_batch_response` 里 `seen_in_window` 按 `block.content_hash`（`text_search.py:558-568`）——同一块在同一窗口内只产一条证据。
- 跨检查项保留：`validate_batch_response` 的 `per_check` 按 `cid` 独立构造（`text_search.py:547-594`），同一块可被多个检查项各引用一次。

**判定：抽取后复用。**
WHY：整套去重是**纯内容算术**，不碰 provider、不碰 DB、不碰队列，机制可整体搬运到 V2 的新表上。但 V2 阶段 B 的固定样本只有 4 条摘录、4 个检查项，去重的实际收益很小，因此本轮建议**机制备好、实现排在验收用例之后**；真正需要立刻保证的是「同一摘录被两个检查项引用时互不吞并」与「rank 稳定」这两条语义。

**已知风险（要带进 V2）**：`content_hash` 含 `page_ordinal`，而 `page_ordinal` 取决于阅读顺序的判定级别；若 `order_source` 回退到 `canonical_text_sha256`（`source_ordering.py:142`）则顺序可能随导入变化，hash 随之变化 → 去重键失效。V1 靠 `compare_two_imports.py` 专门验证「两次导入 24/24 一致」（`tests/perf/README.md` 记载，本轮未重跑，属**历史沿用**）。V2 应把这条做成常态化验收。

**V1 踩过的坑（对 V2 有直接约束力，本轮实测自 `tests/perf/README.md:221`、`:564`）**：V1 造数时给两个「隔离任务」的两份文件设了**不同的 `TaskFile.sha256`**，而 `source_ordering.file_key` 取的就是 `TaskFile.sha256` → K2 `content_hash = sha256(file_key|page_key|page_ordinal|canonical_text)` 天然不等 → 分窗边界、有序清单 5 项 FAIL（19/24）。修法是「两份文件声明同一份内容就必须共用同一个内容 SHA256」。
→ V2 的硬约束：**`file_key` 必须取文件内容的 SHA256，不得取任何任务内合成值、不得取 UUID**。这条不是风格建议，是去重键与分窗稳定性的地基。

**怎样复验**：**AC-R5** —— 固定样本里让同一摘录（如 `charter.guarantee_restrictions` 与 `charter.approval_body`）指向同一块，断言落两条 Result（各 `check_item_id` 一条）、`rank` 均为 0、互不吞并；再让两个不同页的同文摘录指向不同 `page_ordinal`，断言**两条都保留**（对应 `text_search.py:245-248` 的语义）。

### 2.6 任务与文件管理（候选 6）

**V1 实现**（本轮实测）

- 上传 `upload_file()` — `credit-review-app/backend/app/api/routes/files.py:147-200`：
  - 类型判定用**魔数嗅探**而非客户端声明（`_sniff_media` `:42-46`），允许 `application/pdf` / `image/jpeg` / `image/png`（`:27-37`）；不匹配 → 415 `INVALID_FILE`（`:109-113`）。
  - 限额：单任务文件数（`UPLOAD_MAX_FILES_PER_TASK=50`）、单文件字节（50MiB）、单任务总字节（300MiB）（`config.py:42-44`，`files.py:152-162`）→ 413 `UPLOAD_LIMIT_EXCEEDED`。
  - `_save_upload()`（`:104-144`）流式落临时文件后 `write_bytes(storage_key, tmp_path.read_bytes())`（`:140`）——**又整份读回内存**，V2 应改成流式直写。
  - **SHA256 去重**（`:166-169`）：同任务内若已有文件 sha256 相同 → **直接返回既有文件的 201 响应**，不新建、不触发 OCR。
  - 资产创建（`:179-189`，存储键模板在 `:116`）：`Asset(kind="original", storage_key="originals/{task_id}/{file_id}/original.bin", sha256, media_type, size_bytes)`，回填 `TaskFile.original_asset_id`。
  - 首个文件上传后 `DRAFT → PROCESSING`（`:194-196`）。
  - OCR 入队 `enqueue(ocr_submit, file_id=…)`（`:198-199`），仅在 `settings.ocr_configured` 时；**注意这里用的是独立事务的 `enqueue` 而非同事务的 `enqueue_in_session`** → 「文件已提交但 OCR 未入队」存在窗口。
- 任务展示态 `_effective_state()` — `credit-review-app/backend/app/api/routes/tasks.py:27-39`：`COMPLETED`/`FAILED` 是持久态；否则按文件 OCR 进度推导（无文件→`DRAFT`，有识别中→`PROCESSING`，识别完→`REVIEWING`）。进度统计 `_task_progress()`（`:53-71`）。创建任务只允许 borrower（否则 409 `ROLE_DISABLED`）与 `working_capital_loan`（否则 422）（`:80-102`）。删除是软删（`deleted_at`）且 `COMPLETED` 拒绝（409 `TASK_READ_ONLY`）（`:121-135`）。
- 资产读取 `assets.py:14-44`：先校验任务归属（不属 → 404），再校验资产属于该任务，再 `FileResponse`。
- **`task.input_revision` 的真实行为**（本轮实测，重要）：全库检索 `input_revision` 只有两处**赋值**：
  - `credit-review-app/backend/app/crud.py:85` —— 建任务时 `input_revision=0`；
  - `credit-review-app/backend/app/api/routes/runs.py:119` —— 建 run 时 `input_revision=task.input_revision`（把当时的值**拷贝**进 run 快照）。

  **没有任何代码让它自增。** 由此推出 V1 的三条事实：
  1. 补传文件（`files.py:147-200`）、替换、删除文件（`files.py:203-214`，只软删 `deleted_at`）**都不会**让旧结果失效；
  2. `GET /tasks/{id}/results` 的 `is_stale` 字段（`runs.py:258`：`run.input_revision != task.input_revision`）**恒为 false**；
  3. `POST /tasks/{id}/complete` 的 `REVISION_CONFLICT` 拦截（`runs.py:500-504`）**永远不会触发**——它是一个已写好但无触发条件的分支。
  - V1 的替代做法是「每次补跑都新建 run」（`runs.py:103-113` 只在有未完成 run 时拒绝 409 `RUN_IN_PROGRESS`；`runs.py:146-154` 如实标注 `run_mode="full_rerun"`），`list_results` 取 `created_at` 最新的 run（`runs.py:205-209`）。旧 run 与其结果**保留可查**。

**判定：版本语义 = 重做；上传/去重/资产流 = 抽取后复用。**
WHY：V1 的 SHA256 同任务去重、魔数嗅探、资产创建、`DRAFT→PROCESSING` 迁移都是与 provider/队列无关的纯业务逻辑，可直接抽。但「补传使旧结果失效」在 V1 **没有实现**，无代码可抄，V2 必须自己写，而且这是 V2 章程切片的硬需求：docs/v2/requirements/charter.md 要求「缺材料 → 补传」，docs/v2/verification/charter.md 第 4 条要求「联调后对两类故障分别实测后端 409 且任务未写完成」。若 V2 沿用 V1「补传后旧 run 仍可用」，则「补传 → 旧结果仍可完成」会直接违反章程切片的完成语义。

**V2 需要自己写清的三条**（本轮实测推出的缺口）：
1. `task.input_revision` 的**自增触发点**：新增文件、删除文件、替换文件（建议三者都 +1）。
2. **stale 判定的事实源**：`run.input_revision != task.input_revision` → run 变 stale → 拒绝对其写决定/完成（`runs.py:500` 的 `REVISION_CONFLICT` 是现成可抄的分支形状）。
3. **「拒绝时零写入」的验证方式**：V1 的 `run_complete_http.py:112-130` 用「完成前后读同一行 `tasks` 快照」来判定零写入，这是可抄的验收手法（见 2.7）。

**怎样复验**：**AC-R6** —— ①在一个已 READY 的任务上补传一个文件，断言 `tasks.input_revision` 由 0 变 1；②断言 `GET /tasks/{id}/results` 的 `is_stale` 为 true；③断言 `POST /tasks/{id}/complete` 返回 409 `REVISION_CONFLICT`，且 `tasks` 行前后快照逐字段相同（零写入，照抄 `run_complete_http.py:112-130` 的判定法）；④删除文件同样触发 +1。

### 2.7 固定测试样本（候选 7）

**V1 现有资产清单**（本轮实测）

| 文件 | 内容 | 可复用性 |
|---|---|---|
| `backend/tests/conftest.py` | 只有一行注释，无夹具（`:1`） | 无可复用内容 |
| `backend/tests/test_p1.py` | 5 个测试 + 2 个夹具 + 1 个登录助手（`:10-24`）：登录、登录失败、写操作 CSRF、角色禁用、任务/文件跨账号隔离 | 断言形状可抄；**账号口令不可抄**（见下） |
| `backend/tests/perf/mock_llm_server.py` | 859 行纯标准库 OpenAI 兼容服务 | **高可复用**（详见下） |
| `backend/tests/perf/run_quick_acceptance.py` | 736 行容器内实跑主脚本 | **高可复用**（夹具生成器） |
| `backend/tests/perf/run_complete_http.py` | 270 行完成接口 HTTP 实跑 | 逻辑可复用，DB 耦合必须改 |
| `backend/tests/perf/verify_quick_acceptance.py` | 843 行离线断言器（A/B/C 三组 + `--self-test`） | **高可复用** |
| `backend/tests/perf/selftest_mock_server.py` | 226 行模拟服务自检 | 可复用 |
| `backend/tests/perf/compare_two_imports.py` / `fault_injection.py` / `validate_fixtures.py` | 两次导入比对、故障注入、夹具校验 | 概念可复用，代码与 V1 表结构强耦合 |
| `backend/tests/perf/fixtures/*.json` | 3 个静态 fixture（`fault_injection_rules.json` / `fixed_responses.json` / `quick_acceptance.json`） | 见「不可复制」一节 |
| `backend/tests/perf/mock_config.*.json`（5 个） | 模拟服务配置模板：`example` / `a_c2_refill_4` / `c2_refill` / `full_concurrency` / `u5_two_runs` | **可复用**（配置结构与响应规则可抄），但其中的规则需按 V2 检查项 ID 改写 |
| `backend/tests/perf/README.md` | V1 性能验收的完整证据文档（分组口径、实跑数据、踩坑记录） | **重要参考**：V2 阶段 B 可沿用其「分组 + 证据落盘 + 未跑不写数字」的写法 |
| `backend/tests/perf/evidence/**` | V1 实跑留痕 | **不复制**（运行产物） |
| `frontend/tests/perf/fixtures/coverage_incomplete.results.json` | 结果契约样例 | 可抄契约形状 |

**可复用夹具生成器（逐个点名）**

1. `mock_llm_server.Classifier.classify()` — `mock_llm_server.py:168-236`：从请求体抽 `schema_name`（`response_format.json_schema.name`）、`block_ids`（正则 `BLOCK_ID_RE`，`:67`）、`check_item_id`（`CHECK_ID_RE`，`:68`）、批次检查项（`BATCH_CHECK_RE`，`:69`）。**最关键的一条**：窗口序号按 `(schema_name, check_item_id)` 分组独立编号（`:205-214`，注释解释了「否则只注入窗口 1 的规则永远匹配不上」）。
2. `mock_llm_server._match_rule()` — `:530-550`：规则条件 `schema_name` / `check_item_id` / `window_index` / `attempt` / `tag` / `batch_size` / `check_item_id_in` / `any_of_check_item_ids`。
3. `mock_llm_server._build_context()` — `:553-567`：模板变量 `{{BUNDLE}}`(= `w{window_index}`) / `{{CHECK_ID}}` / `{{WINDOW_INDEX}}` / `{{SEQ}}` / `{{ATTEMPT}}` / `{{INVALID_BLOCK}}` / `{{BLOCK:LAST}}` / `{{BLOCK_COUNT}}` / `{{BLOCK:i}}`。
4. `mock_llm_server._pick_response()` — `:570-588`：规则内联 `response` 或 `response_ref {file, path}` 指向 JSON 夹具；未命中时按 schema 返回默认（`DEFAULT_RESPONSES` `:72-90`，其中 text_search 会按请求里的真实检查项清单回 `not_found`，`:582-587`）。
5. 故障注入：`inject` ∈ `401/429/500/format_error/truncated/timeout`（`_inject_error_response` `:591-617`；`truncated` 按 `truncate_ratio` 截断并置 `finish_reason="length"` `:752-767`；`timeout` 挂起 `timeout_hang_seconds` `:738-740`）。
6. `Barrier` — `:260-350`：`release_order` ∈ `as_arrived|reverse|by_check_item`，用于「先收齐 N 个再按序放行」，证明请求**确实发出**。
7. 控制端点 `__health` / `__stats` / `__dump` / `__reset`（`:665-691`）；`ServerState.snapshot()` 机器可读统计（`:450-502`）。
8. `run_quick_acceptance._fixed_non_search(name)` — `:345-358`：classification / vision / 兜底 search 的**固定响应**。
9. `run_quick_acceptance._dynamic_search(ids, block_ids, policy)` — `:361-381`：按请求里**真实**的 `check_item_id` 清单与**真实**的 `block_id` 动态构造合法 `text_search_output`（`policy` ∈ `first|all|first_last`）——这是让 X=1 与 X=3 结果可比的关键。
10. `run_quick_acceptance._patched_create()` — `:384-397`：monkeypatch `Completions.create`，**保留真实 HTTP** 打模拟服务再替换响应体（既拿到真实到达时间，又拿到动态响应）。
11. `run_quick_acceptance._create_synthetic(label, texts)` — `:137-183`：**合成任务造数器**（Task / TaskFile / OcrJob(SUCCEEDED) / OcrPage(width 1000、height 1400、`coordinate_space="ocr_input_image_pixels"`、`source_page_number=7`) / OcrBlock(bbox=[100,100+i*200,900,180+i*200])）。**纯合成、无客户数据，是 V2 最该直接继承的固定样本。**
12. `run_quick_acceptance._create_realocr(label, ocr_json)` — `:186-213`：真实 15 页 OCR 导入路径（走 `app.cli.import_ocr_json`）——**依赖外部文件，V2 需自带或重造**。
13. `run_quick_acceptance._create_run()` / `_snapshot()` / `_accept_all()` / `_export()` / `_result_set()` / `_dedup_summary()` — `:227-241` / `:216-224` / `:244-256` / `:263-301` / `:304-309` / `:528-565`：建 run、裁剪清单、批量接受决定、导出结果与步、三元组比对、三类去重断言（`_dedup_summary` 的 `cross_window_duplicate_dedup_to_single` / `same_text_different_source_kept` / `same_block_multi_check_preserved` 三个布尔正是 V2 要保留的语义）。
14. `run_quick_acceptance._cfg_barrier_off(label, delay_ms)` — `:403-436`：生成一份「屏障关闭 + 固定延迟」的模拟服务配置模板。
15. `run_quick_acceptance.MockService` — `:439-463`：在进程内起模拟服务并热切配置（V2 单测里很有用）。
16. `verify_quick_acceptance.run_group_A / run_group_B / run_group_C` — `verify_quick_acceptance.py:162-322 / :325-458 / :460-586`，以及 `self_test()`（`:587-748`）：**纯离线、纯标准库**的断言器，状态枚举 `PASS / FAIL / 未跑 / 无法取得 / 沿用`（`:76`）——「未跑不写数字」的纪律值得原样继承。

**不可复制清单（必须重造或脱敏）**（本轮实测）

| 项 | 位置 | 问题 |
|---|---|---|
| 真实凭据 | `credit-review-app/.env:3,10-11,16,25,39` | 含 `SECRET_KEY`、`POSTGRES_PASSWORD`/`DATABASE_URL`、真实 `OCR_ACCESS_TOKEN`、真实 `LLM_API_KEY`、`INITIAL_USERS_JSON` 明文口令。`.env` 已被 `.gitignore:2` 忽略，但**绝不能进 V2 仓库或提交** |
| 测试账号口令 | `backend/tests/test_p1.py:10-24` | 硬编码两个 reviewer 测试账号及其**弱口令（明文写在 `:10-24`）**；且这些测试直接跑在**真实库**上（`app.core.db.engine`，`:5`）。V2 改用 V2 自有种子账号 + 随机口令 |
| 真实业务任务 UUID | `backend/tests/perf/run_quick_acceptance.py:71-74` | `PROTECTED` 两个真实任务 ID，属 V1 运行数据 |
| 真实客户文件与 OCR 结果 | `run_quick_acceptance.py:75`（`OCR_SHA`）、`:186-213`、`:197`（真实银行客户文件名与 15 页切分 PDF） | 真实客户材料；`ocr15.json` **不在仓库内**（`tests/perf/fixtures/` 无此文件），须宿主机 `docker cp` 提供 |
| 签名图片 URL | `credit-review-app/backend/app/cli.py:195` 注释明说「外部结果图片（带签名 URL）」 | provider 返回的 `markdown.images` 是**带签名的临时 URL**，落库或入仓即泄露访问凭据 |
| 真实 OCR job / 资产键 | `run_quick_acceptance.py:153-159`（`provider_job_id="qa-perf-imported"`）、`cli.py:159`（`provider_job_id="imported"`）、`cli.py:170`（`ocr/{task_id}/{fid}/{job_id}/imported.json`） | 含 V1 运行态标识 |
| 环境绝对路径含客户文件名 | `backend/tests/perf/fixtures/quick_acceptance.json:80` | 写死了本机绝对路径，路径里**带真实客户文件名**（真实银行客户章程 + OCR 导出文件名） |
| V1 运行留痕 | `backend/tests/perf/evidence/**` | 含真实 task_id / run_id / block_id 与本地路径（`c_http_raw.json`、`setup.json`、`a_results.json` 等），属运行产物 |
| V1 运行卷 | Docker 卷 `credit-review-app_pg_data`、`credit-review-app_app_files` | 必须保持不动，V2 用自己的 compose 项目名与卷（`credit-review-app-v2/compose.yml:1` 已是 `name: credit-review-v2`，卷定义 `:16-18`） |
| V1 DB 直连写法 | `run_complete_http.py:52-58` | 硬编码容器 `credit-review-app-db-1`、用户 `postgres`、库 `app` → V2 必须改指向自己的隔离库 |
| V1 凭据读取写法 | `run_complete_http.py:42-49` | 直接读 `credit-review-app/.env` 的 `INITIAL_USERS_JSON` → V2 必须读自己的环境变量 |
| **V2 侧已有同类风险（本轮实测，供阶段 B 决策）** | `credit-review-app-v2/prototype/fixtures/charter.js` 的 `evidence[].text` | V2 现有原型固定样本**已内嵌真实银行章程原文**（「本行股权出质…」「第四十七条 本行下列对外担保行为…」）。它不是 V1 的一部分、故不在本轮迁移范围，但 V2 固定样本若要进正式仓库或对外交付，需先做脱敏评估。该文件本轮由线框实现 Agent 重写过，原文摘录内容未改动 |

**判定：抽取后复用（并须脱敏重建）。**
WHY：模拟服务与断言器是「零凭据、零客户数据、零 DB」的纯离线资产，价值极高、迁移成本低；但三处强绑定 V1 环境（`.env` 凭据、真实库直连、真实 15 页 OCR 文件）必须替换成 V2 自己的版本。

**怎样复验**：**AC-R7** —— ①把 `mock_llm_server.py`（或其裁剪版）放入 V2 仓库后跑 `python3 mock_llm_server.py --config <cfg> --stats-out /tmp/s.json`，再 `curl /__stats` 断言 `proves_requests_actually_sent=true`；②`verify_quick_acceptance.py --self-test` 在 V2 仓库内通过（该自检不连容器/DB，`verify_quick_acceptance.py:11`）；③V2 自带的固定样本仓库做一次脱敏扫描：把 V1 `.env` 中的**口令/密钥实际值**（数据库口令、OCR token、LLM key、初始用户口令）作为模式全仓 grep，命中数必须为 0；同时禁止出现 `test_p1.py` 的测试账号口令、两个受保护任务 UUID、以及真实银行客户文件名与章程原文片段。扫描用词表本身属于敏感信息，**只在本地执行、不入库、不落盘**。

---

## 三、不迁移清单（V1 留在 V1）

| V1 部件 | 位置 | 不迁原因 |
|---|---|---|
| `credit-review-app/` 整个目录 | 仓库根 | 已在 `.gitignore:10` 排除；V2 发布树不得包含 V1 应用与运行数据（见 `docs/v2/sessions/2026-11/2026-11-16-02-phase-a.md` 的接手核对表） |
| `.env` / `.env.local` | 仓库根 `.gitignore:2-3` | 真实凭据；V2 用自己的环境变量（`compose.yml:8` 的 `V2_DB_PASSWORD`） |
| procrastinate 队列 + worker | `queue.py`、`worker.py` | 阶段 B 无后台长任务（见 2.4） |
| OCR 作业状态机（提交/轮询/重排/下载） | `ocr_pipeline.py:35-249`（`ocr_submit` / `ocr_poll` / `_reschedule_poll` / `ocr_download`） | 阶段 B 用固定 OCR 样本导入，不需要向 provider 提交与轮询；`_ingest`（`:252-311`）那部分反而是要复用的（见 2.1） |
| 印章/签名视觉匹配 | `vision_match.py` | 章程切片是文本摘录；V1 清单里的 `financial.audit_seal` / `financial.cpa_signature` 不在 V2 章程范围 |
| V1 的 5 个 Alembic 迁移 | `backend/app/alembic/versions/`（5 个文件） | V2 是新建库、新建表（`docs/v2/architecture/data-dictionary.md`），从空库执行自己的迁移，不继承 V1 历史 |
| V1 的 borrow-wcl-v1 清单全量（3 材料 18 项） | `backend/app/data/checklist_borrower_wcl_v1.json` | V2 章程切片只用 `charter.*` 系列；营业执照/财报项不进 V2 |
| V1 前端（`frontend/`，React + react-pdf + shadcn） | `credit-review-app/frontend/` | V2 有自己的前端形态；只借用**契约形状**（坐标字段、结果项结构），不搬代码 |
| `compare_two_imports.py` / `fault_injection.py` / `validate_fixtures.py` | `tests/perf/` | 与 V1 表结构、真实 DB、真实容器名强耦合；V2 需要时按 V2 表结构重写 |
| `tests/perf/evidence/**` | `tests/perf/evidence/` | V1 实跑留痕（真实 id / 本地路径），属运行产物 |
| V1 的 compose 项目与卷 | `credit-review-app/compose.yml`；卷 `credit-review-app_pg_data` / `credit-review-app_app_files` | 必须保持不动，供旧版本继续运行；V2 用 `name: credit-review-v2` 与自己的卷（`credit-review-app-v2/compose.yml:1`、`:16-18`） |
| `node_modules/`、`.buildx-config/`、`.DS_Store` | `credit-review-app/` 内 | 本地构建产物 |

---

## 四、与 V1 固定提交的引用方式

- V1 基线提交：`e52520553f3efe8e790fb608e630bf29bab9c1bf`（`docs/STATUS.md:3`；远端 `origin/main` 同 SHA，见 `docs/v2/sessions/2026-11/2026-11-16-02-phase-a.md` 的接手核对表）。
- 本轮读到的 `credit-review-app/` 是**从该提交取回的工作树副本**（`git archive e525205 credit-review-app | tar -x`，与 `docs/v2/sessions/2026-11/2026-11-16-02-phase-a.md:13` 的接手核对一致），在 git 中未跟踪、被 `.gitignore:10` 排除 —— 这是预期状态，V2 发布树不得包含它。
- 取单文件：`git show e525205:credit-review-app/backend/app/ocr_normalize.py`
- 取目录树：`git archive e525205 credit-review-app | tar -x -C /tmp/v1`
- 比对工作树与固定提交是否漂移：`git diff --no-index /tmp/v1/credit-review-app <工作树>/credit-review-app`（工作树未纳入 git，无法用 `git diff` 直接比）
- 本文档所有 `file:line` 均以该提交下的文件为准；若工作树被改动，行号可能漂移，**复核时请以 `git show` 取回的版本为准**。

---

## 五、阶段 B 验收用例清单（本轮给出，供阶段 B 引用）

| 用例 | 目标 | 对应候选 | 判定要点 |
|---|---|---|---|
| AC-R1 | OCR 规范化一致性 | 1 | V1 `parse_page` 与 V2 解析器对同一固定 JSONL 输出字段集逐项一致；坏行不静默丢弃 |
| AC-R2 | 页码与坐标 | 2 | `source_page_number` == 物理页号；`mapping_status == "verified"`；bbox 在页尺寸内；点出处能在左侧定位并高亮 |
| AC-R3 | 分窗稳定性 | 3 | 两次导入窗口序列与 `content_hash` 一致；`Result.rank` 不随到达顺序变 |
| AC-R3b | 覆盖事实源唯一 | 3 | `COVERAGE_INCOMPLETE` 来自结果行 `not_found_reason`，非 step_key 前缀扫描 |
| AC-R4 | （无）并发派发 | 4 | 阶段 B 不涉及；「处理中」用 `run.state` 表达 |
| AC-R5 | 证据去重语义 | 5 | 同块多检查项互不吞并；同文不同出处都保留；rank 稳定 |
| AC-R6 | 输入版本与失效 | 6 | 补传/替换/删除 → `input_revision` +1 → 旧 run stale → `/complete` 409 `REVISION_CONFLICT` 且 `tasks` 行零写入 |
| AC-R7 | 固定样本可用 | 7 | 模拟服务 `__stats` 可证请求发出；断言器 `--self-test` 通过；仓库脱敏扫描零命中 |
| （章程既有） | 阶段 B 三条主用例 | — | 两条 409（覆盖不全 / 覆盖不全变体）与一个正常 200 完成，零写入判定沿用 `run_complete_http.py:112-130` 的前后快照法 |

---

## 六、尚未验证清单（交给阶段 B 或真实样本）

1. 真实 15 页样本的 **OCR 输入像素尺寸**（`width_px`/`height_px`）与 `coordinate_space` 实际取值 —— 样本文件不在仓库内，仅能从 `charter.js` 的 bbox 反推页宽 ≥ 1057。
2. 真实样本上 `source_page_number` 是否真的等于物理页号（V1 从未验证，只写死 `unverified`）。
3. 「两次导入分窗完全一致」在 V2 表结构下是否仍成立（V1 结论属**历史沿用**，本轮未重跑 `compare_two_imports.py`）。
4. V1 `mock_config.*.json` 的规则语义在 V2 的检查项 ID 体系下是否需要重写（V1 用 `charter.business_scope` 等 ID，V2 沿用同一命名可省事）。
5. V2 章程切片的「缺材料」完成规则尚未由产品确认（`docs/v2/sessions/2026-11/2026-11-16-02-phase-a.md` 待产品确认第 1 条），会影响 AC-R6 之外的完成语义。
