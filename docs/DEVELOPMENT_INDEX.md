# 开发索引

| 模块 | 入口 | 如何运行或验证 |
|---|---|---|
| V2 前端线框 | [prototype/index.html](../credit-review-app-v2/prototype/index.html) | 静态预览命令见第一节；按[设计验收](v2/verification/charter.md)复跑 |
| V2 后端 / 数据库 | 尚未实现（阶段 B） | [compose.yml](../credit-review-app-v2/compose.yml) 目前只是 `db` 服务骨架，只核对不改动；命令与隔离条件见[部署决策](v2/decisions/001-isolate-v2-data.md) |
| V1 前端 | [frontend](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/frontend/) | 旧工作台、任务管理、Playwright |
| V1 API / worker | [backend/app](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/) | `api/routes/runs.py` 管任务运行及完成；`ocr_pipeline.py`、`processing_pipeline.py` 管 OCR 与搜索 |
| V1 数据定义 | [models.py](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/models.py)、[Alembic](https://github.com/AmazingYanyan/compliance-review-agent/tree/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/backend/app/alembic/versions/) | 表关系及采用范围见[数据字典](v2/architecture/data-dictionary.md) |
| V1 部署、复验 | [Compose](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/compose.yml)、[T03](https://github.com/AmazingYanyan/compliance-review-agent/blob/e52520553f3efe8e790fb608e630bf29bab9c1bf/credit-review-app/docs/REVIEW_HANDOFF.md) | 在 V1 固定提交运行；旧实验输入按[历史索引](legacy/INDEX.md)取得 |

## 一、线框入口与启动命令

```bash
python3 -m http.server 8092 --bind 127.0.0.1 --directory credit-review-app-v2/prototype
```

浏览器打开 <http://127.0.0.1:8092>。**无构建步骤、无 npm 依赖**。端口占用时换端口，命令里的 `--directory credit-review-app-v2/prototype` 保持不变。

语法检查（改完线框执行，浏览器以 ES module 加载 `.js`，故先改名为 `.mjs` 再检查）：

```bash
cp credit-review-app-v2/prototype/workbench.js /tmp/wb.mjs && node --check /tmp/wb.mjs
cp credit-review-app-v2/prototype/fixtures/charter.js /tmp/charter.mjs && node --check /tmp/charter.mjs
```

〔本轮实测〕两条命令均通过。完整复跑流程见[验收 Skill](#六可复用验收-skill)与[验证口径](v2/verification/charter.md)。

## 二、模块职责与源码入口

| 文件 | 职责 | 不放什么 |
|---|---|---|
| [prototype/index.html](../credit-review-app-v2/prototype/index.html) | 页面骨架与全部 id 容器（顶部任务条、材料页签、横幅、左右两栏、页脚声明） | 不放场景数据与业务判断 |
| [prototype/workbench.js](../credit-review-app-v2/prototype/workbench.js) | 渲染与交互：状态映射、卡片渲染、点击与决定动作、翻页与缩放、只读态 | 不放样本文案与场景元数据 |
| [prototype/workbench.css](../credit-review-app-v2/prototype/workbench.css) | 共用样式令牌：字号阶梯、间距阶梯、状态色、按钮层级与密度；派生色用 `color-mix` | `:root` 之外不写裸字号与裸色值 |
| [prototype/fixtures/charter.js](../credit-review-app-v2/prototype/fixtures/charter.js) | 固定样本：摘录与 bbox、页尺寸、任务身份、**六种场景与受影响项元数据** | 不放交互逻辑 |
| [compose.yml](../credit-review-app-v2/compose.yml) | 阶段 B 的 V2 独立数据库骨架（当前只有 `db` 服务与卷） | 不含 api / worker 服务，无迁移文件 |

## 三、关键元素 id 速查

| 区域 | id / 选择器 | 用途 |
|---|---|---|
| 顶部任务条 | `#task-name` `#customer-role` `#revision` | 任务名、客户角色、输入版本 |
| 顶部状态 | `#status-badge` `#progress` | 状态徽章；计数「已确认 N / M · 未找到 1 项…」 |
| 完成入口 | `#complete` `#complete-reason` | 「完成核对」按钮（用 `aria-disabled` + `title` 表达禁用）与其旁可见原因文案 |
| 评审控件 | `#scenario` | 六种评审场景下拉（正式形态阶段 B 由后端状态推导后移除） |
| 横幅 | `#banner` | 场景横幅、阶段列表、缺材料与受影响项清单 |
| 左栏原件 | `#source` `#page-number` `#page-prev` `#page-next` `#page-input` `.zoom-btn` | 坐标线框、页码指示、上一页/下一页、页码输入、缩放档位（`data-zoom="fit\|1\|1.5\|2"`） |
| 右栏摘录 | `#results` `#count` `#next` | 卡片列表容器、计数、「下一条待办」 |
| 卡片动作 | `data-action` 取值 `select` / `locate` / `accept` / `reject` / `reset` / `save-reject` / `upload` | 选中卡片、定位出处、接受、拒绝、重新选择、保存拒绝、补传材料占位 |
| 其他 | `#prototype-note` `#upload-hint` | 原型边界说明；补传材料提示 |

〔本轮实测〕`select` 只在右栏内选中并聚焦，**不移动左栏**；只有 `locate` 驱动左栏翻页与高亮。

## 四、故障定位入口

| 现象 | 定位与处理 |
|---|---|
| 预览端口 8092 被占用 | 换端口，例如 `python3 -m http.server 8093 --bind 127.0.0.1 --directory credit-review-app-v2/prototype`。阶段 B 的 V2 API 建议端口也是 8092，联调前先停静态预览（见[部署决策](v2/decisions/001-isolate-v2-data.md)） |
| 决定状态看起来没变 | 决定写在浏览器 localStorage，key `charter-wireframe`；清空：`localStorage.removeItem('charter-wireframe')` 后刷新页面 |
| 控制台出现 favicon 404 | `index.html` 已声明 `<link rel="icon" href="data:,">`；若再出现请确认该行未被删 |
| Figma 读不到选中 Frame | Figma Desktop 在运行，但 Dev Mode MCP 端口未监听且本环境未注册 Figma MCP 工具，**该项检查本轮未能执行**，改用浏览器线框评审。详见[本轮记录](v2/sessions/2026-11/2026-11-16-02-phase-a.md) |
| git fetch/push 到 github.com 超时 | DNS 多址中部分地址不可达；本地绕过：`git config http.curloptResolve "github.com:443:<可用IP>"` 与 `git config http.version HTTP/1.1`。只写本地 `.git/config`、不进提交；**IP 随 DNS 轮转变化，固定 IP 会过期**。〔本轮实测〕收尾时 `20.247.166.64` 已恢复可达，已 `git config --local --unset http.curloptResolve` 撤销固定 IP，恢复默认解析。下次失败时先用 `dig +short github.com` 与 `curl -s -o /dev/null -w "%{remote_ip}" https://github.com/` 找到当下可达的 IP 再决定是否固定 |
| 找不到 V2 后端入口 | V2 后端、迁移与接口**尚未实现**（阶段 B），仓库内只有 `compose.yml` 的 `db` 骨架 |

## 五、复用记录（V1 → V2）

| # | 候选 | 采用方式 | 一句话原因 | 复验方式 |
|---|---|---|---|---|
| 1 | OCR 规范化 | 抽取后复用 | 字段映射是纯结构解析、与 provider 无关；但页栅格图在 V1 根本不存在 | AC-R1：同一份固定 OCR JSONL 分别喂 V1 `parse_page` 与 V2 解析器，diff 输出字段集 |
| 2 | 页码与坐标约定 | 抽取后复用 + 1 处约定变更 | 字段形状（1-based 页码、二值坐标系、bbox 四元组）可沿用；但 `source_page_number` 需从「provider 顺序 + 1」升级为物理页号 | AC-R2：断言页码等于物理页号、`mapping_status = verified`、bbox 落在页尺寸内 |
| 3 | 稳定分窗 | 抽取后复用（本轮只抽排序键与覆盖口径） | 排序契约无 UUID、可复算；阶段 B 的章程切片用固定摘录、不重跑 LLM | AC-R3：两次导入窗口序列与 `content_hash` 完全一致 |
| 4 | 并发派发 | 本轮不迁 | V1 队列是为「跑 OCR、跑 LLM」设计的，阶段 B 无后台长任务 | 无（阶段 B 无队列用例）；「处理中」先用 `run.state` 表达 |
| 5 | 证据去重 | 抽取后复用 | 去重键与排序键是纯内容算术，与 provider、DB、队列解耦 | AC-R5：同一摘录被两个检查项引用时互不吞并，`rank` 稳定 |
| 6 | 任务与文件管理 | 版本语义重做 + 上传/去重/资产流抽取后复用 | `task.input_revision` 在 V1 全代码里从不自增，V1 的 `REVISION_CONFLICT` 不可达，V2 必须自己实现 | AC-R6：补传后 `input_revision` +1、`/complete` 返回 409 且 `tasks` 行零写入 |
| 7 | 固定测试样本 | 抽取后复用（须脱敏重建） | 模拟服务与断言器是零凭据、零 DB 的离线资产；真实凭据与客户数据不可搬 | AC-R7：模拟服务自检通过、断言器 `--self-test` 通过、脱敏扫描零命中 |

完整评估、逐项证据与不迁移清单见 [V1 复用评估](v2/architecture/v1-reuse.md)。

## 六、可复用验收 Skill

`.trae/skills/charter-workbench-acceptance/SKILL.md` —— 章程核对工作台的浏览器验收流程，内含启动命令、样本路径与八步预期结果。

**何时使用**：评审线框布局、复跑阶段 A 的浏览器验收（六种状态、「找待办 → 查看出处 → 接受或拒绝 → 下一条 → 完成」完整路径）、核对完成入口原因与原件控件。**不适用**：阶段 B 的接口与数据库验收——那部分按[验证口径](v2/verification/charter.md)第二节执行。

## 七、阶段 B 尚未实现的部分

- V2 后端 API、数据库迁移与数据**本轮都还没有**。仓库内只有 [compose.yml](../credit-review-app-v2/compose.yml) 的 `db` 服务骨架与卷定义。
- `compose.yml` **只核对不改动**：接入 API 前按[部署决策](v2/decisions/001-isolate-v2-data.md)核对项目名（`credit-review-v2`）、库名与卷名、连接目标；不碰 V1 的 `credit-review-app` 项目与卷。
- 三个端点、错误码与检查顺序以[接口契约](v2/architecture/api-contract.md)为准；落库范围以[数据字典](v2/architecture/data-dictionary.md)为准。
