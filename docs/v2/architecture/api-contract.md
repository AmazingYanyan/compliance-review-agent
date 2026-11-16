# V2 章程核对 · 接口契约（草案）

> **本文是契约草案，尚未实现。** 本轮（阶段 A）只冻结语义，不写代码。阶段 B 必须**精确实现**本文描述的行为；任何与本文不一致的实现都算偏差，需要回改本文而不是默默改代码。
> 关联文档：状态表 [../requirements/charter.md](../requirements/charter.md)；落库字典 [data-dictionary.md](data-dictionary.md)；V1 复用盘点 [v1-reuse.md](v1-reuse.md)。
> V1 参照基线：固定提交 `e52520553f3efe8e790fb608e630bf29bab9c1bf`，路径 `credit-review-app/backend/app/...`。文中 `file:line` 均相对该提交。

## 一、通用约定

| 项 | 约定 |
|---|---|
| Base path | `/api/v2` |
| 编码 | UTF-8；请求与响应均为 `application/json` |
| 标识符 | `task_id` / `run_id` / `result_id` / `file_id` / `page_id` / `block_id` 均为 UUID 字符串 |
| 时间 | ISO-8601 带时区偏移（数据库为 `TIMESTAMPTZ`，UTC 存储） |
| 错误响应 | 统一 `{"code": "<SCREAMING_SNAKE>", "message": "<中文可读文案>"}`；`NOT_COMPLETE` 额外携带 `incomplete` 对象 |
| 认证 | 阶段 B 之前**无登录**（见 data-dictionary.md「阶段 B 之后」条目）；阶段 B 引入后所有写接口需 CSRF 头 |
| 幂等 | 章程切片无幂等写入需求，`idempotency_keys` 不建（V1 有表，V2 不迁） |
| 分页 | 本切片一次性返回当前 run 的全部摘录，不分页；`next_cursor` 恒为 `null`（沿用 V1 `runs.py:260`） |

### 1.1 与 V1 路径的关系

V1 的路径是 `/tasks/{task_id}/...`（`credit-review-app/backend/app/api/routes/runs.py`）。V2 统一加 `/api/v2` 前缀，且把 V1 的「结果集查询 + 决策 + 完成」三件事收敛为一个工作台读接口 + 两个写接口。

## 二、覆盖事实源规则（先于端点定义）

这是本契约最硬的一条规则，其余端点都依赖它。

| 编号 | 规则 | 依据 |
|---|---|---|
| R-1 | **覆盖状态的唯一事实源是 `processing_runs.coverage_complete`**（布尔列，NOT NULL，默认 false）。它由 worker 在 run 结束时写入。 | 沿用 V1 `processing_pipeline.py:160-245` 的 `compute_coverage_summary` 与 `_complete_run` |
| R-2 | **API 层永不重新推导覆盖。** API 不得从 `results.not_found_reason`、`run_steps.step_key`、`check_executions` 等任何来源反推 `coverage_complete`，也不得用「AND 多个来源」的逻辑。 | 沿用 V1 `runs.py:506-509` 注释：「删除 api 侧实时反推（原 `or not coverage.coverage_complete` 双事实源 AND）——删的是反推，不是覆盖拦截本身；worker `_complete_run` 是唯一写库事实源」 |
| R-3 | **人工决策永不替代覆盖事实。** 即使每个可见摘录都已被接受，`coverage_complete = false` 时 `POST /complete` 仍必须返回 `409 COVERAGE_INCOMPLETE`。 | 沿用 V1 `runs.py:510` 注释：「即使『可见摘录全部确认』也必须拦（人工决策不替代覆盖事实）」 |
| R-4 | `coverage_affected_check_ids` 是**展示用派生列表**，来源是 `results.not_found_reason = 'coverage_incomplete'` 的检查项集合；它**不参与**完成判定，只用于前端标注受影响卡片。 | 沿用 V1 `runs.py:249-255` |
| R-5 | 覆盖语义（worker 侧判定口径，API 只消费结果）：①文本检查项集合 = 清单快照中 `result_mode ∉ {seal, signature}` 的叶子项（印章/签名无「应查窗口」，排除在窗口覆盖外）；②受影响 = 该 run 中 `not_found_reason = 'coverage_incomplete'` 的检查项；③覆盖达成 = 该检查项在本次 run 有 `results` 行 且 不在受影响集合；④本次 run 无任何单元步（`run_steps.step_key` 以 `u:` 或 `check:` 开头）→ `coverage_complete = false` 且 `processing_runs.error_code = 'COVERAGE_NO_UNIT_STEPS'`；⑤清单中无文本检查项 → `coverage_complete = (存在单元步)`。 | 沿用 V1 `processing_pipeline.py:174-245` |

## 三、端点一：读取工作台

### `GET /api/v2/tasks/{task_id}/workbench`

一次返回工作台所需的全部事实：任务身份、材料页签、当前 run、当前 run 的摘录清单与出处、每条摘录的决定状态、统计、完成可行性。

**成功响应：`200`**

```json
{
  "task": {
    "id": "0f5c...-...",
    "name": "示例对公客户 · 流动资金贷款",
    "customer_role": "borrower",
    "state": "REVIEWING",
    "input_revision": 0
  },
  "materials": [
    {
      "type": "articles_of_association",
      "label": "公司章程",
      "file_count": 1,
      "status": "ready"
    }
  ],
  "run": {
    "id": "9a1e...-...",
    "state": "READY",
    "stage": "search",
    "coverage_complete": false,
    "coverage_affected_check_ids": ["charter.guarantee_scale"]
  },
  "checklist": [
    {
      "material_type": "articles_of_association",
      "items": [
        {
          "check_item_id": "charter.guarantee_scale",
          "check_label": "担保规模限制",
          "group_label": null,
          "excerpts": [
            {
              "id": "3d70...-...",
              "check_item_id": "charter.guarantee_scale",
              "kind": "text",
              "text": "（一）本行及本行控股子公司（子银行）的对外担保总额……",
              "not_found_reason": null,
              "relation_status": "matched",
              "rank": 0,
              "sources": [
                {
                  "file_id": "7c22...-...",
                  "source_page_number": 15,
                  "page_id": "b810...-...",
                  "block_id": "d0e4...-...",
                  "bbox": [108, 1304, 1054, 1380],
                  "polygon": null,
                  "coordinate_space": "ocr_input_image_pixels",
                  "page_width_px": 1191,
                  "page_height_px": 1684,
                  "location_precision": "region",
                  "start_char": null,
                  "end_char": null
                }
              ],
              "decision": {
                "decision": "unselected",
                "reject_reason": null,
                "version": 0,
                "updated_at": null,
                "carried_from_result_id": null
              }
            }
          ]
        }
      ]
    }
  ],
  "statistics": {
    "overall": {
      "total": 5, "unselected": 5, "accepted": 0, "rejected": 0,
      "missing_reason": 0, "accept_rate": null, "reject_rate": null,
      "can_complete": false
    },
    "materials": [
      {
        "material_type": "articles_of_association",
        "statistics": { "total": 5, "unselected": 5, "accepted": 0, "rejected": 0,
                        "missing_reason": 0, "accept_rate": null, "reject_rate": null,
                        "can_complete": false }
      }
    ]
  },
  "completion": {
    "can_complete": false,
    "reason_code": "COVERAGE_INCOMPLETE",
    "reason_text": "识别覆盖不完整，暂不能完成核对",
    "incomplete": {
      "unselected": [],
      "missing_reason": []
    }
  }
}
```

**字段定义**

| 路径 | 类型 | 可空 | 含义与来源 |
|---|---|---|---|
| `task.id` | uuid | 否 | `tasks.id` |
| `task.name` | string | 否 | `tasks.name` |
| `task.customer_role` | string | 否 | `tasks.customer_role`，取值 `borrower` / `guarantor` / `pledgor` |
| `task.state` | string | 否 | `tasks.state`，取值 `DRAFT` / `PROCESSING` / `REVIEWING` / `FAILED` / `COMPLETED` |
| `task.input_revision` | int | 否 | `tasks.input_revision`，当前输入版本号 |
| `materials[].type` | string | 否 | 材料类型，`articles_of_association` / `business_license` / `audited_financials` |
| `materials[].label` | string | 否 | 材料显示名（章程 / 营业执照 / 审计财报） |
| `materials[].file_count` | int | 否 | 该材料下未删除的 `task_files` 行数 |
| `materials[].status` | string | 否 | `missing`（无文件）/ `processing`（OCR 未完成）/ `ready` / `failed` / `out_of_scope`（后续迁移范围） |
| `run.id` | uuid | 否 | `processing_runs.id`；无 run 时为 `null` 且 `run.state = null` |
| `run.state` | string | 是 | `processing_runs.state`，取值 `QUEUED` / `RUNNING` / `READY` / `FAILED` / `SUPERSEDED` |
| `run.stage` | string | 是 | `processing_runs.stage`，当前阶段标识 |
| `run.coverage_complete` | bool | 否 | **只读** `processing_runs.coverage_complete`（规则 R-1/R-2） |
| `run.coverage_affected_check_ids` | string[] | 否 | 受覆盖影响的检查项 ID（规则 R-4） |
| `checklist[].material_type` | string | 否 | 该组摘录所属材料 |
| `checklist[].items[].check_item_id` | string | 否 | 检查项 ID |
| `checklist[].items[].check_label` | string | 否 | 检查项中文名（取自 `processing_runs.checklist_snapshot`） |
| `checklist[].items[].group_label` | string | 是 | 检查项分组名 |
| `checklist[].items[].excerpts[].id` | uuid | 否 | **等于 `results.id`**（result_id），是决定写入与完成统计的键 |
| `checklist[].items[].excerpts[].kind` | string | 否 | `results.kind`：`text` / `table` / `seal` / `signature` / `not_found` |
| `checklist[].items[].excerpts[].text` | string | 是 | `results.text`；`not_found` 行为 `null` |
| `checklist[].items[].excerpts[].not_found_reason` | string | 是 | `results.not_found_reason`：`coverage_incomplete` / `no_matching_evidence` / `material_missing` / `null` |
| `checklist[].items[].excerpts[].relation_status` | string | 是 | `results.relation_status`：`matched` / `needs_review` / `null` |
| `checklist[].items[].excerpts[].rank` | int | 否 | `results.rank`，同一检查项内从 0 起的稳定排序 |
| `checklist[].items[].excerpts[].sources[]` | array | 否 | 该摘录的出处列表，来自 `result_sources` |
| `…sources[].source_page_number` | int | 是 | 展示页码（1-based）；页码约定见 data-dictionary.md |
| `…sources[].bbox` | int[4] | 是 | `[x1, y1, x2, y2]`，页像素，原点左上 |
| `…sources[].polygon` | int[][] | 是 | 多边形点集 `[[x, y], …]` |
| `…sources[].coordinate_space` | string | 否 | `ocr_input_image_pixels` / `unknown` |
| `…sources[].page_width_px` / `page_height_px` | int | 是 | 所在页的像素尺寸，来自 `ocr_pages.width_px` / `height_px` |
| `…sources[].location_precision` | string | 否 | `region` / `page` / `none` |
| `…sources[].start_char` / `end_char` | int | 是 | 字符偏移。**V1 恒为 `null`**（`text_search.py:433-434`、`:587-588` 显式置 `None`），V2 保持 `null` |
| `…excerpts[].decision.decision` | string | 否 | `unselected` / `accepted` / `rejected`；无决定行时为 `unselected` |
| `…excerpts[].decision.reject_reason` | string | 是 | 非 `rejected` 时恒为 `null` |
| `…excerpts[].decision.version` | int | 否 | `decisions.version`；无决定行时为 `0` |
| `…excerpts[].decision.carried_from_result_id` | uuid | 是 | 该决定结转自上一轮 run 的哪个 result；V1 恒为 `null`（从未写入），V2 用于「来自上一批次」标注 |
| `statistics.overall` | object | 否 | 全量统计，见下 |
| `statistics.materials[]` | array | 否 | 按材料分组统计，`material_type` 缺省为 `unknown` |
| `completion.can_complete` | bool | 否 | `statistics.overall.can_complete` 的镜像，供前端直接判断按钮可用性 |
| `completion.reason_code` | string | 是 | 不可完成时的机器码，取值见第五节；可完成时为 `null` |
| `completion.reason_text` | string | 是 | 不可完成时的中文原因；可完成时为 `"可完成"` |
| `completion.incomplete.unselected[]` | array | 否 | `{check_item_id, check_label}`，未确认项 |
| `completion.incomplete.missing_reason[]` | array | 否 | `{check_item_id, check_label}`，已拒绝但原因为空的项 |

**统计口径（与 V1 完全一致）**

`total` = 本次 run 的 `results` 行数；`unselected` = 无决定行或 `decision = unselected` 的行数；`accepted` / `rejected` 同理；`missing_reason` = `rejected` 且 `reject_reason.strip()` 为空的行数；`accept_rate` = `accepted / total`（`total = 0` 时为 `null`）；`reject_rate` 同理；
`can_complete = (total > 0) AND (unselected = 0) AND (missing_reason = 0)`。
〔沿用 V1 `decisions.py:34-64`〕

**错误**

| HTTP | code | 触发条件 |
|---|---|---|
| `409` | `RUN_NOT_READY` | 任务下没有状态为 `READY` 的 run（即 run 处于 `QUEUED` / `RUNNING` / `FAILED` / `SUPERSEDED`，或根本没有 run） |
| `404` | `RESOURCE_NOT_FOUND` | `task_id` 不存在或不属于当前用户 |

> 说明：V1 的 `GET /tasks/{id}/results` 在没有 run 时返回 200 + 空结果集（`runs.py:210-215`）。V2 工作台读接口改为 `409 RUN_NOT_READY`，因为「处理中」在本契约里是**独立状态**，需要与「无数据」区分开——前端据此渲染阶段列表而不是空列表。〔V2 变更，原因：状态表要求「处理中」有确定的界面表现〕

### 3.1 上一批次结果的表达（重跑场景）

`checklist` 只包含**当前 run** 的结果。重跑后旧 run 置 `SUPERSEDED`，旧结果与旧决定保留在旧 run 上，界面需标注「来自上一批次」。该标注的数据来源是：

| 路径 | 类型 | 含义 |
|---|---|---|
| `carried[]` | array | 可选块；仅当存在上一批次结果时返回 |
| `carried[].from_run_id` | uuid | 旧 run 的 ID |
| `carried[].from_run_state` | string | 旧 run 状态，本场景恒为 `SUPERSEDED` |
| `carried[].from_input_revision` | int | 旧 run 绑定的输入版本 |
| `carried[].items[]` | array | 形状与 `checklist[].items[]` 相同，`excerpts[].id` 为旧 `results.id` |
| `carried[].items[].excerpts[].decision.carried_from_result_id` | uuid | 指向**当前** run 中对应的 result（结转关系）；无对应新 result 时为 `null` |

旧批次结果**不计入** `statistics` 与 `completion` 的任何计数。

## 四、端点二：写入人工决定

### `PATCH /api/v2/tasks/{task_id}/results/{result_id}/decision`

**请求体**

```json
{ "run_id": "9a1e...-...", "decision": "accepted", "reject_reason": null }
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `run_id` | uuid | 是 | 必须是本次决定所属的 run |
| `decision` | string | 是 | `unselected` / `accepted` / `rejected` |
| `reject_reason` | string | 否 | 仅 `decision = rejected` 时可携带；长度 ≤ 4000 字符；`decision ≠ rejected` 时携带**非空**原因 → `422` |

**成功响应：`200`**

```json
{
  "decision": {
    "result_id": "3d70...-...",
    "decision": "accepted",
    "reject_reason": null,
    "version": 1,
    "updated_at": "2026-11-16T10:20:30+00:00",
    "carried_from_result_id": null
  },
  "statistics": { "overall": { … }, "materials": [ { … } ] }
}
```

`statistics` 结构与读接口完全一致，前端可用它就地刷新计数，无需二次请求。

**写入语义**（沿用 V1 `decisions.py:110-173`，逐条照抄）：

1. `decision` 不在 `unselected` / `accepted` / `rejected` 之内 → `422 INVALID_DECISION`，message「非法 decision 值」。
2. `decision ≠ rejected` 且携带了**非空** `reject_reason` → `422 INVALID_DECISION`，message「仅拒绝时需要填写原因」。
3. `reject_reason` 长度 > 4000 → `422 INVALID_DECISION`，message「拒绝原因超长（上限 4000 字符）」。
4. 写入时 `reject_reason` 在 `decision ≠ rejected` 的情况下被置为 `null`。
5. **首次写入**：`version = 1`，**不产生 `decision_events` 行**。
6. **更新写入**：`version = existing.version + 1`，并写一条 `decision_events`：`event_type = 'update'`，`before` = `{decision, reject_reason, version}`（旧值），`after` = `{decision, reject_reason, version}`（新值）。
7. `rejected` 且原因为空**允许**保存（草稿态），但会阻塞完成（计入 `missing_reason`）。
8. 每个 result 一条决定，以 `result_id` 为键。

> **受影响检查项（`coverage_incomplete`）**：本接口**不**因 `run.coverage_affected_check_ids` 而拒绝写入（沿用 V1 语义，无此校验）；写入决定也**不改变**完成判定——`coverage_complete = false` 时 `POST /complete` 仍返回 `409 COVERAGE_INCOMPLETE`（规则 R-1/R-3/R-4）。界面不提供受影响项的决定入口，属**前端策略**〔实测，线框不渲染受影响项的接受/拒绝按钮〕。是否在接口层禁止写入受影响项，待产品确认（charter.md 开放问题 3）。

**错误**

| HTTP | code | 触发条件 | 数据库写入 |
|---|---|---|---|
| `409` | `RUN_NOT_READY` | run 不存在或 `run.state ≠ READY` | 无 |
| `409` | `TASK_READ_ONLY` | `tasks.state = COMPLETED` | 无 |
| `404` | `RESOURCE_NOT_FOUND` | `result_id` 不存在，或不属于该 task，或不属于该 `run_id` | 无 |
| `422` | `INVALID_DECISION` | 上述三条校验任一不通过 | 无 |

**校验顺序**（与 V1 `runs.py:410-444` 一致，必须照此实现）：`RUN_NOT_READY` → `TASK_READ_ONLY` → `RESOURCE_NOT_FOUND` → `INVALID_DECISION`。顺序不可调换：任务只读时不再校验 result 是否存在。

> **V1 无 revision 校验**：V1 的决定写入接口请求体只有 `{run_id, decision, reject_reason}`，**不携带 `input_revision`**，因此对已过期的 run 依然可以写决定〔实测，`runs.py:52-56`、`:402-444`〕。V2 契约按此保持：补传后旧 run 的决定仍可写入（绑定旧 `result_id`，天然不计入新 run 统计），只有 `POST /complete` 会对旧 revision 返回 `409 REVISION_CONFLICT`。〔V2 保持 V1 语义，理由见 data-dictionary.md「归属与展示规则」〕

## 五、端点三：完成核对

### `POST /api/v2/tasks/{task_id}/complete`

**请求体**

```json
{ "run_id": "9a1e...-...", "input_revision": 0 }
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `run_id` | uuid | 是 | 要完成的 run |
| `input_revision` | int | 是 | 必须等于 `tasks.input_revision`；不等 → `409 REVISION_CONFLICT` |

**成功响应：`200`**

```json
{ "state": "COMPLETED", "statistics": { "overall": { … }, "materials": [ { … } ] } }
```

**检查顺序（严格照此实现，顺序即语义）**

| 序 | 检查 | 失败响应 | 依据 |
|---|---|---|---|
| 1 | run 存在且 `run.state = READY` | `409 RUN_NOT_READY`「核对结果尚未就绪」 | 沿用 V1 `runs.py:495-499` |
| 2 | `body.input_revision == tasks.input_revision` | `409 REVISION_CONFLICT`「资料已变更，请刷新后重新核对」 | 沿用 V1 `runs.py:500-504` |
| 3 | `run.coverage_complete == true` | `409 COVERAGE_INCOMPLETE`「识别覆盖不完整，暂不能完成核对」 | 沿用 V1 `runs.py:506-518`；规则 R-1/R-3 |
| 4 | `statistics.overall.can_complete == true` | `409 NOT_COMPLETE`「仍有未确认项或拒绝未填原因，无法完成」，并携带 `incomplete` | 沿用 V1 `runs.py:520-527` |

**成功时的写入**（沿用 V1 `runs.py:529-534`）：

- `tasks.state = 'COMPLETED'`
- `tasks.completed_at = now(UTC)`
- `tasks.last_ready_run_id = run.id`

三者在**同一事务**内提交。三者中任何一个失败 → 整体回滚，`tasks` 行零变化。

**`incomplete` 结构**

```json
{
  "unselected":     [ { "check_item_id": "charter.guarantee_scale", "check_label": "担保规模限制" } ],
  "missing_reason": [ { "check_item_id": "charter.approval_body",  "check_label": "担保事项批准权" } ]
}
```

`unselected` = 决定为 `unselected` 或无决定行的结果；`missing_reason` = `rejected` 但 `reject_reason.strip()` 为空的结果。〔沿用 V1 `runs.py:456-485`〕

**错误**

| HTTP | code | 触发条件 | 数据库写入 |
|---|---|---|---|
| `409` | `RUN_NOT_READY` | run 非 `READY` 或不存在 | 无 |
| `409` | `REVISION_CONFLICT` | `input_revision` 与任务当前值不等 | 无 |
| `409` | `COVERAGE_INCOMPLETE` | `processing_runs.coverage_complete = false` | 无 |
| `409` | `NOT_COMPLETE` | `can_complete = false`（有未确认项或拒绝缺原因） | 无 |
| `404` | `RESOURCE_NOT_FOUND` | `task_id` 不存在 | 无 |

## 六、错误码总表

| code | HTTP | 触发条件 | 响应体 | 前端表现 | 是否写入完成状态 |
|---|---|---|---|---|---|
| `RUN_NOT_READY` | 409 | run 不存在或 `state ≠ READY` | `{"code","message"}` | 完成按钮禁用 + 文案「核对结果尚未就绪」；写决定入口禁用 | **否**（`tasks.state` / `completed_at` / `last_ready_run_id` 均不变） |
| `TASK_READ_ONLY` | 409 | `tasks.state = COMPLETED`（仅写决定路径） | `{"code","message"}` | 隐藏/禁用接受与拒绝，提示「任务已完成，不可修改」 | **否** |
| `REVISION_CONFLICT` | 409 | `input_revision` 与 `tasks.input_revision` 不等 | `{"code","message"}` | 提示「资料已变更，请刷新后重新核对」，并禁用完成 | **否** |
| `COVERAGE_INCOMPLETE` | 409 | `processing_runs.coverage_complete = false` | `{"code","message"}` | 完成按钮禁用 + 列出受影响检查项 | **否** |
| `NOT_COMPLETE` | 409 | `statistics.overall.can_complete = false` | `{"code","message","incomplete":{unselected[],missing_reason[]}}` | 完成按钮禁用 + 分别列出未确认项与拒绝缺原因项 | **否** |
| `INVALID_DECISION` | 422 | 决定值非法 / 非 rejected 携带原因 / 原因超 4000 字符 | `{"code","message"}` | 原地提示，**不**改动列表与计数 | **否**（`decisions` / `decision_events` 均不新增行） |
| `RESOURCE_NOT_FOUND` | 404 | 任务 / 结果 / run 不存在或不属于当前用户 | `{"code","message"}` | 提示并刷新列表 | **否** |

**硬性要求**：所有 `409`（以及 `422`、`404`）在返回错误时**必须零写入**——不写 `tasks` 的任何完成相关字段，不写 `decisions`，不写 `decision_events`。判定方法沿用 V1 `tests/perf/run_complete_http.py:112-130`：出错前后读取 `tasks` 同一行的快照，逐字段比对。

## 七、前端与服务端的权威关系

| 层次 | 职责 |
|---|---|
| 前端 | 可以根据 `GET /workbench` 的 `completion.can_complete` 与 `completion.reason_code` **预置**「完成核对」按钮的禁用态与原因文案，减少无效点击。这只是**提示**。 |
| 服务端 | **权威**。是否可完成、能否写决定，一律由服务端按第二节规则判定。前端禁用态与服务端判定不一致时，以服务端为准，且必须由服务端返回的错误码决定最终呈现。 |

> **计数与完成原因文案的两层口径**：接口给出的是结构化数值与 `reason_code`（`statistics`、`completion`）；线框自己渲染计数与完成原因文案，两者**语义一致但文案不同源**——线框计数固定为「已确认 N / M · 未找到 1 项待确认」（**M 只计非受影响的摘录项**，「正常未找到」项单列显示且未决定前仍阻塞完成），线框的完成原因文案清单见 charter.md「完成原因文案」表〔实测，线框 `workbench.js` 的 `progressText()`、`completionState()`〕。E-1 的判定标准是**语义一致**，不是逐字相同。

**阶段 B 必须同时取得三条互相独立的证据**（缺一条不算验收通过）：

| # | 证据 | 判定方式 |
|---|---|---|
| E-1 | **按钮禁用** | 在「覆盖不全」「未确认」「拒绝缺原因」「资料已变更」四种情形下，界面上的「完成核对」呈禁用态，且禁用原因文案与 `completion.reason_text` / 错误码语义一致。 |
| E-2 | **实际 HTTP 响应** | 用同一 run 真实发起 `POST /api/v2/tasks/{task_id}/complete`，得到对应 `409` 与本文第六节的错误码；不得用「构造响应」或 mock 代替。 |
| E-3 | **数据库写入状态** | 完成前后读取 `tasks` 同一行的完整快照，逐字段比对，确认零写入；并确认 `decisions` / `decision_events` 无新增行（对 `INVALID_DECISION` 用例）。 |

三条证据必须指向**同一个 run、同一批数据**，避免「按钮禁用了但接口其实能通」这类假通过。

## 八、与 V1 的差异

| # | 差异 | V1 事实 | V2 契约 | 原因 |
|---|---|---|---|---|
| D-1 | 路径前缀 | `/tasks/{task_id}/...` | `/api/v2/tasks/{task_id}/...` | 版本隔离 |
| D-2 | 读接口 | `GET /tasks/{id}/results` 返回结果集与统计；无 run 时返回 200 + 空集 | `GET /api/v2/tasks/{id}/workbench` 返回任务/材料/run/摘录/统计/完成判定；无 READY run 时 `409 RUN_NOT_READY` | 「处理中」是独立状态，需与「无数据」区分 |
| D-3 | 读接口不再自算覆盖 | V1 已只读 `run.coverage_complete`（`runs.py:264`） | 同左，并额外返回 `coverage_affected_check_ids` | R-1/R-2 |
| D-4 | 覆盖受影响项 | V1 `list_results` 返回 `coverage_affected_check_ids`（`runs.py:255`） | 同左，位置在 `run` 块内 | 归并到 run 语义下 |
| D-5 | 统计分组 | V1 按 `checklist_snapshot` 的 `material_type` 分组，缺省 `unknown`（`decisions.py:90-101`） | 同左 | 一致 |
| D-6 | 决定写入不含 revision 校验 | V1 请求体无 `input_revision` | 同左 | 保持 V1 语义；旧 run 的决定写入不污染新 run 统计 |
| D-7 | 完成接口无 `TASK_READ_ONLY` 分支 | V1 `complete_task` 未判 `task.state`（`runs.py:488-534`），重复完成会重写 `completed_at` | 本契约**不新增**该分支（保持 V1 行为），待产品确认是否需要（见 charter.md 开放问题 4） | 不自行扩大范围 |
| D-8 | 缺材料完成规则 | V1 无「材料不完整」拦截，`material_missing` 不阻断覆盖判定 | **待决策**，契约无法在产品定案前冻结完整错误码集合 | 见 charter.md 第三节 |
| D-9 | `carried_from_result_id` | V1 定义了列但**从不写入**（`decisions.py:183-185` 只读） | V2 用于「来自上一批次」标注 | V1 无跨 run 结转语义 |
| D-10 | 无 `idempotency_keys` | V1 有表 | V2 不建 | 本切片无幂等写入需求 |

## 九、尚未冻结 / 尚未验证

| 项 | 状态 | 阻塞于 |
|---|---|---|
| 缺材料完成规则与对应错误码 | 待决策 | 产品确认（charter.md 开放问题 1） |
| 「正常未找到」项是否计入「已确认 N / M」 | 待决策 | 产品确认（开放问题 2）；线框计数口径已定：计数文案为「已确认 N / M · 未找到 1 项待确认」，**M 只计非受影响的摘录项**，该 result 单列显示、不进分母〔实测，线框 `workbench.js` 的 `progressText()`〕；接口层的 `statistics` 口径已按 V1 固定（计入 `total`），两者如何并置展示待定 |
| 覆盖不全的受影响项：**接口层是否仍接受针对受影响 result 的决定写入** | 待决策 | 产品确认（开放问题 3）；当前契约立场：写决定接口**不**因 `run.coverage_affected_check_ids` 而拦截（沿用 V1 语义，允许写入），完成判定仍被覆盖事实 `processing_runs.coverage_complete` 拦截（`409 COVERAGE_INCOMPLETE`）；界面不提供入口（线框不渲染受影响项的接受/拒绝按钮）〔实测〕 |
| 已完成任务重复 `POST /complete` 的响应 | 待决策 | 产品确认（开放问题 4） |
| 真实 PDF 的 `source_page_number` / bbox 精度 | 尚未验证 | 阶段 B 用本地批准样本验证（data-dictionary.md「页码与坐标约定」） |
| `POST /complete` 在「只有 material_missing 结果」时的实际响应 | 尚未验证 | 依赖开放问题 1 |
