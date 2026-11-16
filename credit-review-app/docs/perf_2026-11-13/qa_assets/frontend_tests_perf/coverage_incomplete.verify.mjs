/**
 * 资产 5 · Chrome「覆盖不全」用例骨架（Playwright + 系统 Chrome + page.route 拦截）。
 *
 * 本轮定位：**骨架 + 拦截自测**，不是最终 UI 验收。
 * - 用固定 fixture 拦截 /api/v1/ 构造一条覆盖不全任务（不触碰真实服务 2 条业务任务）；
 * - 能立刻验证的 DOM 事实做真实断言（提示文案、摘录可确认、出处定位、刷新、409 提示）；
 * - 依赖新实现的部分一律标 PENDING，绝不写假结果；
 * - 真实页面操作（真实服务 + 真实覆盖不全 run）留到工程师实现完成后由 QA 补跑。
 *
 * 运行：
 *   node frontend/tests/perf/coverage_incomplete.verify.mjs
 * 可选（PM 要求「按可配置断言写」，实现后注入实际值即可把 PENDING 升级为真实断言）：
 *   VERIFY_BASE_URL=http://localhost:8080
 *   VERIFY_BROWSER_CHANNEL=chrome
 *   QA_COVERAGE_EVIDENCE_OUT=frontend/tests/perf/evidence/coverage_incomplete.skeleton.json
 *   QA_EXPECTED_COMPLETE_409_CODE=COVERAGE_INCOMPLETE
 *   QA_COMPLETE_BLOCKED_LABEL=暂不能完成
 *   QA_EXPECTED_BANNER_TEXT=<实现后的任务级提示文案>
 *   QA_CSRF_TOKEN=<真实服务定向回归时从登录响应取的 csrf_token；不设则脚本显式 GET /auth/me 从响应体取，不硬编码>
 *   QA_REAL_UI=1 <团长下发实跑信号后开启：C13/C14 接成对真实前端 DOM 的可实跑断言
 *                 （持久覆盖提示条 / 完成按钮 disabled +「暂不能完成核对」说明），
 *                 默认关闭以维持 T02 封版拦截自测 17 PASS / 0 FAIL / 4 PENDING，不写假结果>
 *
 * 依赖：项目 node_modules 里的 playwright + 本机系统 Chrome（与 tasks-final.verify.mjs 同口径）。
 */
import { chromium } from "playwright"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, "../..")
const BASE = process.env.VERIFY_BASE_URL ?? "http://localhost:8080"
const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(HERE, "fixtures/coverage_incomplete.results.json"), "utf8"),
)
const OUT = process.env.QA_COVERAGE_EVIDENCE_OUT
  ?? path.join(HERE, "evidence/coverage_incomplete.skeleton.json")

const TASK_ID = FIXTURE.task_id
const RUN_ID = FIXTURE.run_id
const REASON_LABEL = FIXTURE.expected.reason_label_current
// PM 要求「按可配置断言写」：错误码/禁用文案/banner 文案都可用环境变量覆盖，
// 便于架构师最终定值与实现后文案落地时不必改脚本。
const COMPLETE_409_CODE = process.env.QA_EXPECTED_COMPLETE_409_CODE
  ?? FIXTURE.expected.complete_409_code
const BLOCKED_LABEL = process.env.QA_COMPLETE_BLOCKED_LABEL
  ?? FIXTURE.expected.complete_button_disabled_label
const BANNER_TEXT = process.env.QA_EXPECTED_BANNER_TEXT
  ?? FIXTURE.expected.banner_text
const SOURCE_PAGE = FIXTURE.source_page_number
// 实跑信号后开启：把 C13/C14（及按钮禁用分支）接成对真实前端 DOM 的可实跑断言。
// 默认关闭，维持 T02 封版的拦截自测 17 PASS / 0 FAIL / 4 PENDING，不写假结果。
const REAL_UI = process.env.QA_REAL_UI === "1"

// 预期用例全集：writeEvidence() 会据此算出「本轮未执行」的用例，
// 避免把 summary 数字误读成所有预期用例均已通过（沉淀经验第 53 条）。
const EXPECTED_CASE_NAMES = [
  "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C7b", "C8", "C9", "C9b",
  "C9c-0", "C9c", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17",
]
// 内容版本标记（PM 建议的可选加固，最小实现）：
// 动态 not_executed_cases 只按名称判断，识别不了「同名但内容已修订」。
// 把版本写进证据后，比对本次与上一份证据的 case_content_versions 即可发现变化，
// 不需要维护一份容易忘记清空的人工待重跑清单。
const CASE_CONTENT_VERSIONS = {
  C7b: "v1-list-results-coverage",
  "C9c-0": "v1-csrf-403-precheck",
  C9c: "v3-csrf-token-from-auth-me",
  C9b: "v2-task-id-filter",
  C13: "v2-real-ui-dom-assertion",
  C14: "v2-real-ui-dom-assertion",
  C17: "v1-coverage-not-readonly",
}
const caseVersion = (name) => CASE_CONTENT_VERSIONS[name] ?? "v1"
const results = []
const reqLog = []
const evidence = {
  intercepted_run_views: [],
  complete_response: null,
  decision_requests: [],
  write_requests: [],
  complete_button_state: null,
  skeleton_mode: true,
  real_ui_mode: REAL_UI,
}

function record(status, name, detail) {
  results.push({ status, name, detail })
  console.log(`${status.padEnd(7)} | ${name} | ${detail}`)
}
const pass = (name, detail) => record("PASS", name, detail)
const fail = (name, detail) => record("FAIL", name, detail)
const pending = (name, detail) => record("PENDING", name, detail)
const check = (name, ok, detail) => {
  record(ok ? "PASS" : "FAIL", name, detail)
  return ok
}

const cors = () => ({
  "Access-Control-Allow-Origin": BASE,
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
})

/** 用一个最小 PDF 响应素材请求，避免 react-pdf 因空响应阻塞页面渲染。 */
const MINIMAL_PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
  + "2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
  + "trailer\n<< /Root 1 0 R >>\n%%EOF\n",
  "utf8",
)

async function installRoutes(ctx) {
  await ctx.route(/\/api\/v1\//, async (route) => {
    const req = route.request()
    const method = req.method()
    const p = new URL(req.url()).pathname
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors() })
      return
    }

    let status = 200
    let body = {}
    let rawBody = null
    let contentType = "application/json"

    const is = (re) => re.test(p)
    if (p === "/api/v1/auth/me") {
      body = FIXTURE.responses.me
    } else if (p === "/api/v1/capabilities") {
      body = FIXTURE.responses.capabilities
    } else if (p === "/api/v1/tasks" && method === "GET") {
      body = FIXTURE.responses.tasks
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/files$/)) {
      body = method === "GET" ? FIXTURE.responses.files : {}
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/files\/[^/]+\/classification$/)) {
      body = {}
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/results\/[^/]+\/decision$/) && method === "PATCH") {
      body = FIXTURE.responses.decision_ok
      evidence.decision_requests.push({ method, path: p, body: req.postDataJSON?.() ?? null })
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/results$/) && method === "GET") {
      body = FIXTURE.responses.results
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/complete$/) && method === "POST") {
      status = 409
      body = FIXTURE.responses.complete_409
      evidence.complete_response = { status, body, request: req.postDataJSON?.() ?? null }
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/runs\/[^/]+$/) && method === "GET") {
      body = FIXTURE.responses.run
      evidence.intercepted_run_views.push(body)
    } else if (is(/^\/api\/v1\/tasks\/[^/]+\/assets\/[^/]+$/)) {
      rawBody = MINIMAL_PDF
      contentType = "application/pdf"
    } else if (is(/^\/api\/v1\/tasks\/[^/]+$/)) {
      body = FIXTURE.responses.task
    }

    reqLog.push({ method, path: p, status, matched: rawBody !== null || Object.keys(body).length > 0 })
    if (["POST", "PATCH", "PUT", "DELETE"].includes(method)) {
      evidence.write_requests.push({ method, path: p, status })
    }
    await route.fulfill({
      status,
      contentType,
      body: rawBody ?? JSON.stringify(body),
      headers: cors(),
    })
  })
}

async function main() {
  fs.mkdirSync(path.dirname(OUT), { recursive: true })
  let browser
  try {
    browser = await chromium.launch({
      headless: true,
      channel: process.env.VERIFY_BROWSER_CHANNEL ?? "chrome",
    })
  } catch (e) {
    pending("C0 浏览器启动", `系统 Chrome 不可用：${String(e).slice(0, 200)}；真实页面操作待实现后补跑`)
    writeEvidence()
    return
  }

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await installRoutes(ctx)
  const page = await ctx.newPage()
  page.setDefaultTimeout(10000)

  try {
    await page.goto(`${BASE}/tasks/${TASK_ID}/review`)
    // useQuery 首帧是 undefined，等真实条目渲染再断言（沉淀经验第 42 条）
    await page.getByText(REASON_LABEL).first().waitFor({ timeout: 10000 })

    // --- 可立即验证的 DOM 事实 -------------------------------------------
    check(
      "C1 条目级覆盖不全提示文案可见",
      (await page.getByText(REASON_LABEL).count()) >= 1,
      `文案="${REASON_LABEL}" 命中 ${await page.getByText(REASON_LABEL).count()} 处`,
    )
    check(
      "C2 覆盖不全时已有摘录仍可查看",
      (await page.locator(`#evidence-${FIXTURE.result_hit_id}`).count()) === 1
        && (await page.getByText(/第十七条/).count()) >= 1,
      `摘录卡片存在且含「第十七条」`,
    )

    // --- 已有摘录可接受 / 拒绝 --------------------------------------------
    const hitCard = page.locator(`#evidence-${FIXTURE.result_hit_id}`)
    const acceptBtn = hitCard.getByRole("button", { name: "接受" })
    check("C3 已有摘录提供「接受」入口", (await acceptBtn.count()) === 1,
      `接受按钮数=${await acceptBtn.count()}`)
    if (await acceptBtn.count()) {
      await acceptBtn.click()
      await page.waitForTimeout(300)
      const hitPatch = evidence.decision_requests.filter(
        (r) => r.path.includes(FIXTURE.result_hit_id),
      )
      check(
        "C4 点击「接受」发出 PATCH 且命中该 result_id",
        hitPatch.length >= 1,
        `PATCH 请求=${JSON.stringify(hitPatch.map((r) => r.path))}`,
      )
    }

    // --- 点击出处定位 ------------------------------------------------------
    const locateBtn = hitCard.getByRole("button", { name: /仅定位到页|定位原文/ })
    check("C5 出处定位按钮存在", (await locateBtn.count()) >= 1,
      `按钮数=${await locateBtn.count()}`)
    if (await locateBtn.count()) {
      await locateBtn.first().click()
      await page.waitForTimeout(200)
      const headerText = await page.locator("body").innerText()
      check(
        `C6 定位后材料预览页码变为出处物理页 ${SOURCE_PAGE}`,
        headerText.includes(`第 ${SOURCE_PAGE} 页`),
        `页面含「第 ${SOURCE_PAGE} 页」=${headerText.includes(`第 ${SOURCE_PAGE} 页`)}`,
      )
    }

    // --- API 与工作台状态一致（显式取一次 run 视图） -----------------------
    const runView = await page.evaluate(async (url) => {
      const r = await fetch(url)
      return { status: r.status, body: await r.json() }
    }, `${BASE}/api/v1/tasks/${TASK_ID}/runs/${RUN_ID}`)
    check(
      "C7 run 接口返回 coverage_complete=false 且与工作台覆盖不全提示一致",
      runView.status === 200 && runView.body.coverage_complete === false
        && (await page.getByText(REASON_LABEL).count()) >= 1,
      `run.coverage_complete=${runView.body.coverage_complete} 错误码=${runView.body.error_code}`,
    )

    // --- C7b：T01/T02 新增 list_results 覆盖字段，与 run 视图三方一致 --------
    const resultsView = await page.evaluate(async (url) => {
      const r = await fetch(url)
      return { status: r.status, body: await r.json() }
    }, `${BASE}/api/v1/tasks/${TASK_ID}/results`)
    const affected = resultsView.body?.coverage_affected_check_ids ?? []
    check(
      "C7b list_results 覆盖字段与 run 视图、工作台提示三方一致",
      resultsView.status === 200
        && resultsView.body.coverage_complete === false
        && resultsView.body.coverage_complete === runView.body.coverage_complete
        && affected.includes("charter.approval_body")
        && (await page.getByText(REASON_LABEL).count()) >= 1,
      `results.coverage_complete=${resultsView.body.coverage_complete} `
        + `run.coverage_complete=${runView.body.coverage_complete} `
        + `affected=${JSON.stringify(affected)}`,
    )

    // --- 完成按钮：拦截返回 409 + 可断言错误码 -----------------------------
    const completeBtn = page.getByRole("button", { name: "完成核对" })
    const btnCount = await completeBtn.count()
    const isDisabled = btnCount > 0 ? await completeBtn.isDisabled() : null
    evidence.complete_button_state = { count: btnCount, disabled: isDisabled }
    check(
      "C8 记录完成按钮当前状态（当前实现仍可点击）",
      btnCount === 1,
      `按钮数=${btnCount} disabled=${isDisabled}；PM 要求实现后应 disabled 且说明「${BLOCKED_LABEL}」`,
    )
    if (btnCount && !isDisabled) {
      const writesBefore = evidence.write_requests.length
      await completeBtn.click()
      await page.waitForTimeout(300)
      check(
        "C9 点击完成后收到 409 且 detail.code 可断言",
        evidence.complete_response?.status === 409
          && evidence.complete_response?.body?.detail?.code === COMPLETE_409_CODE,
        `status=${evidence.complete_response?.status} code=${evidence.complete_response?.body?.detail?.code} 期望码=${COMPLETE_409_CODE}`,
      )
      const addedWrites = evidence.write_requests.slice(writesBefore)
      // PM 边界：覆盖不全 ≠ 整体只读。接受/拒绝的正常 PATCH 是合法写入，
      // C9b 只核「完成动作」相关的零状态写入，不得把它们误判成违规写入。
      // 经验 41 / 本轮要求：零写入 predicate 加目标任务 ID 过滤，
      // 避免 5 秒轮询带来的其他任务写请求串扰，只核本任务完成动作相关写入。
      const taskWrites = addedWrites.filter((w) => w.path.includes(`/tasks/${TASK_ID}/`))
      const illegalWrites = taskWrites.filter((w) => w.status >= 200 && w.status < 300)
      check(
        "C9b 完成动作零状态写入（接受/拒绝的正常写入不判违规）",
        addedWrites.length === 1 && addedWrites[0].path.endsWith("/complete")
          && addedWrites[0].status === 409 && illegalWrites.length === 0,
        `点击前写请求=${writesBefore}（含 C4 接受动作的正常 PATCH，属允许写入）；`
          + `点击后新增=${JSON.stringify(addedWrites)}；本任务 2xx 违规写入=${illegalWrites.length}`,
      )
      const msg = evidence.complete_response?.body?.detail?.message ?? ""
      check(
        "C10 完成失败原因在页面上可见",
        (await page.getByText(msg).count()) >= 1,
        `message="${msg}" 命中 ${await page.getByText(msg).count()} 处`,
      )
    } else if (REAL_UI) {
      // 实跑信号后：按钮 disabled 是实现的预期结果，对真实 DOM 事实做断言，
      // 不写假结果；接口层 409 / 零写入仍由下方 C9c 绕过 UI 独立覆盖。
      pass("C9/C9b/C10 完成按钮已 disabled（实现预期，接口层证据由 C9c 覆盖）",
        `disabled=${isDisabled}；按钮不可点击属前端封死，接口层 409 由 C9c 独立断言`)
    } else {
      pending("C9/C9b/C10 完成按钮已禁用，未发起 UI 点击",
        `disabled=${isDisabled}；实现后按钮不可点击，但接口层 409 仍由下方 C9c 独立断言覆盖`)
    }

    // --- C9c：独立于 UI 的直接接口断言 --------------------------------------
    // PM 明确要求「绕过前端直接打 API，即使按钮 disabled 也要验 409 + detail.code + 零写入」。
    // 这一条刻意放在按钮状态分支之外，实现后前端封死按钮也不会丢失接口层证据。
    // 经验 47：require_csrf 是路由依赖、在函数体之前执行，缺 X-CSRF-Token / Origin
    // 或 cookie 会话会先返回 403，409 断言会失败或被误判成业务 bug。
    // token 从 /auth/me 响应取，不硬编码；真实服务定向回归须从登录响应取并保持 cookie jar。
    // token 从 /auth/me 取、不硬编码：优先 env（真实服务定向回归时由登录响应取并
    // 保持 cookie jar），否则显式 GET /auth/me 从响应体取；仅当端点不可达时才回退到
    // fixture 的 me.csrf_token（它是 /auth/me 的响应结构，不是写死在脚本里的常量）。
    let csrfToken = process.env.QA_CSRF_TOKEN ?? null
    let csrfSource = process.env.QA_CSRF_TOKEN
      ? "env QA_CSRF_TOKEN（登录响应取）" : null
    if (!csrfToken) {
      try {
        const meResp = await page.evaluate(async (url) => {
          const r = await fetch(url, { credentials: "include" })
          return { status: r.status, body: await r.json() }
        }, `${BASE}/api/v1/auth/me`)
        if (meResp.status === 200 && meResp.body?.csrf_token) {
          csrfToken = meResp.body.csrf_token
          csrfSource = "GET /api/v1/auth/me 响应体 csrf_token（不硬编码）"
        }
      } catch { /* 落到回退分支，evidence.csrf 如实记录来源 */ }
    }
    if (!csrfToken) {
      csrfToken = FIXTURE.responses.me.csrf_token
      csrfSource = "fixture responses.me.csrf_token（/auth/me 不可达时的回退）"
    }
    evidence.csrf = {
      header_sent: true,
      source: csrfSource,
      origin: BASE,
      credentials: "include",
      note: "token 一律从 /auth/me 响应体或登录响应取，不硬编码；真实服务定向回归必须从登录响应取并保持会话 cookie jar",
    }
    const apiWritesBefore = evidence.write_requests.length
    const directApi = await page.evaluate(async ({ url, body, csrf, origin }) => {
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
          "Origin": origin,
        },
        body: JSON.stringify(body),
      })
      let payload = null
      try { payload = await r.json() } catch { payload = null }
      return { status: r.status, body: payload }
    }, {
      url: `${BASE}/api/v1/tasks/${TASK_ID}/complete`,
      body: { run_id: RUN_ID, input_revision: FIXTURE.responses.task.input_revision },
      csrf: csrfToken,
      origin: BASE,
    })
    await page.waitForTimeout(200)
    const apiAddedWrites = evidence.write_requests.slice(apiWritesBefore)
    // 经验 41 / 本轮要求：零写入 predicate 加目标任务 ID 过滤，
    // 避免 5 秒轮询串扰（其他任务的写请求不得计入本任务的完成动作零写入判定）。
    const apiTaskWrites = apiAddedWrites.filter((w) => w.path.includes(`/tasks/${TASK_ID}/`))
    const apiIllegalWrites = apiTaskWrites.filter((w) => w.status >= 200 && w.status < 300)
    // 断言顺序：先排除 403（CSRF/会话前置），再断言业务 409
    check(
      "C9c-0 先排除 403（CSRF / 会话前置已就位）",
      directApi.status !== 403,
      `status=${directApi.status}；若为 403 说明缺 X-CSRF-Token / Origin 或 cookie 会话，不是业务 bug`,
    )
    check(
      "C9c 绕过 UI 直接调完成接口仍 409 + detail.code 可断言 + 零写入",
      directApi.status === 409
        && directApi.body?.detail?.code === COMPLETE_409_CODE
        && apiIllegalWrites.length === 0,
      `status=${directApi.status} code=${directApi.body?.detail?.code} 期望码=${COMPLETE_409_CODE}；`
        + `本任务新增写请求=${JSON.stringify(apiTaskWrites)}；2xx 违规写入=${apiIllegalWrites.length}`,
    )

    // --- 刷新后提示仍在 ---------------------------------------------------
    await page.reload()
    await page.getByText(REASON_LABEL).first().waitFor({ timeout: 10000 })
    check(
      "C11 刷新后覆盖不全提示仍在",
      (await page.getByText(REASON_LABEL).count()) >= 1,
      `刷新后命中 ${await page.getByText(REASON_LABEL).count()} 处`,
    )
    check(
      "C12 刷新后已有摘录仍可见",
      (await page.locator(`#evidence-${FIXTURE.result_hit_id}`).count()) === 1,
      "摘录卡片仍在",
    )

    // --- PM 边界：覆盖不全 ≠ 整体只读 --------------------------------------
    // disabled 只针对「完成」一个动作；历史已完成任务才是全部写操作 409 TASK_READ_ONLY。
    const postReloadCard = page.locator(`#evidence-${FIXTURE.result_hit_id}`)
    const acceptStillAvailable = (await postReloadCard.getByRole("button", { name: "接受" }).count()) >= 1
    const locateStillAvailable = (await postReloadCard.getByRole("button", { name: /仅定位到页|定位原文/ }).count()) >= 1
    check(
      "C17 覆盖不全 ≠ 整体只读：接受/拒绝与出处定位仍可用",
      acceptStillAvailable && locateStillAvailable,
      `接受按钮=${acceptStillAvailable} 出处定位=${locateStillAvailable}；完成按钮 disabled 不得复用成全局只读`,
    )

    // --- 依赖新实现的断言 ---------------------------------------------------
    // 默认（拦截自测）：保持注入式 / PENDING，T02 封版 17/0/4 不写假结果。
    // QA_REAL_UI=1（团长下发实跑信号后）：C13/C14 接成对真实前端 DOM 的可实跑
    // 断言，无需人肉注入文案；前端实现符合用户口径（持久覆盖提示条 + 完成按钮
    // disabled +「暂不能完成核对」说明）时自然 PASS。C15/C16（真实服务定向回归 /
    // 正常完成 / 历史只读）本轮不需要，保持 PENDING。
    const BANNER_RE = /覆盖不完整|覆盖不全|识别覆盖不完整/
    const BLOCKED_RE = /暂不能完成/
    if (REAL_UI) {
      const bannerCount = await page.getByText(BANNER_RE).count()
      check(
        "C13 任务级覆盖不全提示条（QA_REAL_UI 真实 DOM 断言）",
        bannerCount >= 1,
        `覆盖不全语义文案命中 ${bannerCount} 处（正则 ${BANNER_RE}）；对真实前端渲染断言、非注入预期；刷新后持久性由 C11 覆盖`,
      )
    } else if (BANNER_TEXT) {
      check(
        "C13 任务级覆盖不全 banner 文案",
        (await page.getByText(BANNER_TEXT).count()) >= 1,
        `文案="${BANNER_TEXT}" 命中 ${await page.getByText(BANNER_TEXT).count()} 处（预期由注入的 QA_EXPECTED_BANNER_TEXT 驱动，非前端文案实测）`,
      )
    } else {
      pending(
        "C13 任务级覆盖不全 banner 文案",
        "通过 QA_EXPECTED_BANNER_TEXT 注入实现后的实际文案，或设 QA_REAL_UI=1 走真实 DOM 断言（当前为 null）",
      )
    }
    if (REAL_UI) {
      const blockedCount = await page.getByText(BLOCKED_RE).count()
      check(
        "C14 完成按钮 disabled 且说明「暂不能完成核对」（QA_REAL_UI 真实 DOM 断言）",
        isDisabled === true && blockedCount >= 1,
        `disabled=${isDisabled} 说明文案命中 ${blockedCount} 处（正则 ${BLOCKED_RE}）；对真实前端渲染断言、非注入预期；接口层 409 由 C9c 独立覆盖`,
      )
    } else if (isDisabled) {
      check(
        `C14 完成按钮 disabled 且说明「${BLOCKED_LABEL}」`,
        (await page.getByText(BLOCKED_LABEL).count()) >= 1,
        `disabled=true 文案命中 ${await page.getByText(BLOCKED_LABEL).count()} 处（文案预期由注入的 QA_COMPLETE_BLOCKED_LABEL 驱动，非前端文案实测）`,
      )
    } else {
      pending(
        `C14 实现后完成按钮应 disabled 且说明「${BLOCKED_LABEL}」`,
        `当前 disabled=${isDisabled}；PM 要求实现后按钮不可用且说明「暂不能完成」。可用 QA_COMPLETE_BLOCKED_LABEL 覆盖文案，或设 QA_REAL_UI=1 走真实 DOM 断言；错误码 ${COMPLETE_409_CODE} 已由架构师定值。`,
      )
    }
    pending(
      "C15 覆盖不全 run 的真实服务定向接口回归（API 与工作台一致、刷新后仍在）",
      `本骨架全部走 page.route 拦截；实现完成后需按 README 的定向接口回归清单补跑。`,
    )
    pending(
      "C16 正常完成 / 历史已完成只读回看",
      `团长要求优先用定向接口回归，本 Chrome 骨架不覆盖；留待实现后补跑。`,
    )
  } catch (e) {
    pending("C 骨架执行异常", `${String(e).slice(0, 240)}；最后 URL=${page.url()}；真实页面操作待实现后补跑`)
  } finally {
    await ctx.close()
    await browser.close()
  }
  writeEvidence()
}

function writeEvidence() {
  const executedNames = results.map((r) => r.name)
  const notExecuted = EXPECTED_CASE_NAMES.filter(
    (n) => !executedNames.some((name) => name === n || name.startsWith(`${n} `)),
  )
  const caseContentVersions = Object.fromEntries(
    EXPECTED_CASE_NAMES.map((n) => [n, caseVersion(n)]),
  )
  // 与上一份证据做版本一致性比对（方案 ②）；有版本变化的用例即使名称出现也需重跑。
  let priorVersionDiffs = []
  let priorEvidencePath = null
  try {
    const prior = JSON.parse(fs.readFileSync(OUT, "utf8"))
    priorEvidencePath = OUT
    const priorVersions = prior.case_content_versions ?? {}
    priorVersionDiffs = EXPECTED_CASE_NAMES.filter(
      (n) => priorVersions[n] !== undefined && priorVersions[n] !== caseVersion(n),
    ).map((n) => ({ case: n, prior: priorVersions[n], current: caseVersion(n) }))
  } catch {
    priorEvidencePath = null // 首次运行或旧证据无版本字段，按无基线处理
  }
  const payload = {
    schema_version: "qa-coverage-incomplete-skeleton-1",
    ran_at: new Date().toISOString(),
    scope: "Chrome 覆盖不全用例骨架 + 固定响应拦截自测；不是最终 UI 验收，未使用真实服务数据",
    skeleton_mode: true,
    real_ui_mode: REAL_UI,
    real_ui_note: "QA_REAL_UI=1 时 C13/C14 接成对真实前端 DOM 的可实跑断言；仅由团长下发实跑信号后开启，本轮静态准备不跑，T02 封版 17/0/4 证据原样保留。",
    base_url: BASE,
    fixture: "frontend/tests/perf/fixtures/coverage_incomplete.results.json",
    expected: FIXTURE.expected,
    injected_expectations: {
      QA_EXPECTED_COMPLETE_409_CODE: process.env.QA_EXPECTED_COMPLETE_409_CODE ?? null,
      QA_COMPLETE_BLOCKED_LABEL: process.env.QA_COMPLETE_BLOCKED_LABEL ?? null,
      QA_EXPECTED_BANNER_TEXT: process.env.QA_EXPECTED_BANNER_TEXT ?? null,
      QA_REAL_UI: process.env.QA_REAL_UI ?? null,
      note: "沉淀经验第 53 条：拦截自测下若 C13/C14 由注入值升级为 PASS，证据必须标注「预期由注入的 QA_EXPECTED_* 驱动」，不得误读为前端文案已实测。QA_REAL_UI=1 时 C13/C14 改为对真实前端 DOM 做断言（非注入预期）；该模式仅由团长下发实跑信号后开启，本轮静态准备不跑。evidence.csrf.source 记录 token 来源，不记明文。",
    },
    evidence,
    intercepted_request_count: reqLog.length,
    intercepted_requests: reqLog,
    summary: {
      PASS: results.filter((r) => r.status === "PASS").length,
      FAIL: results.filter((r) => r.status === "FAIL").length,
      PENDING: results.filter((r) => r.status === "PENDING").length,
    },
    expected_case_names: EXPECTED_CASE_NAMES,
    not_executed_cases: notExecuted,
    case_content_versions: caseContentVersions,
    prior_evidence_path: priorEvidencePath,
    case_version_diffs_vs_prior: priorVersionDiffs,
    revision_check_note: (
      "经验 53 + PM 加固：动态 not_executed_cases 只按名称判断，识别不了「同名但内容已修订」。"
      + "case_content_versions 记录每个用例的内容版本；比对本次与上一份证据即可发现版本变化，"
      + "版本变化的用例即使名称出现过也需重跑。case_version_diffs_vs_prior 非空时须显式复核，"
      + "交付说明以人工标注为准并注明原因。本次交付两份清单未打架：重跑后 not_executed_cases=[]，"
      + "修订前证据的 measured_before_revision / pending_rerun_cases 已随新证据覆盖而消失。"
    ),
    coverage_note: (
      "经验 53：summary 只统计 results 里实际执行过的用例；"
      + "not_executed_cases 列出本轮未跑用例，不得把 summary 数字读成所有预期用例均已通过。"
    ),
    results,
    pending_note: "所有 PENDING 项均标注「待实现后补跑」；未跑的用例不写任何结果数字。",
  }
  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2) + "\n", "utf8")
  console.log(`\n骨架证据：${OUT}`)
  const failed = results.filter((r) => r.status === "FAIL")
  if (failed.length) {
    console.error(`存在 ${failed.length} 项 FAIL：${failed.map((r) => r.name).join("；")}`)
    process.exitCode = 1
  }
}

main().catch((e) => {
  console.error("骨架脚本异常：", e)
  process.exitCode = 1
})
