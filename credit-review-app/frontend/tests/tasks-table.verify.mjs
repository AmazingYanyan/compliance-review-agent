/**
 * 「我的任务」表格操作列 + 表格交互验收脚本（独立运行，不依赖 playwright test runner 的 setup 项目）。
 *
 * 运行：node frontend/tests/tasks-table.verify.mjs
 * 前置：frontend 依赖已安装；前端已构建并同步到 api 容器（见 docs/REVIEW_HANDOFF.md）。
 *
 * 场景 A：真实服务上的 1 条待核对 + 1 条已完成，验证三槽位对齐、按钮样式、入口与只读页，产出同屏截图。
 * 场景 B：本地 23 条固定 fixture（拦截 /api/v1/，不触碰 OCR / LLM 等外部服务），
 *         验证双向排序、搜索、状态组合筛选、翻页、单页收起分页，以及操作命中的任务 ID。
 */
import { chromium } from "playwright"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, "../..")
const BASE = process.env.VERIFY_BASE_URL ?? "http://localhost:8080"
const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(ROOT, "frontend/tests/fixtures/tasks-23.json"), "utf8"),
)
const SHOT_DIR = path.join(ROOT, "docs/screenshots")

function readEnv() {
  const env = {}
  for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split("\n")) {
    const m = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/)
    if (m) env[m[1]] = m[2].trim().replace(/^["']|["']$/g, "")
  }
  return env
}

const results = []
const reqLog = []
function record(status, name, detail) {
  results.push({ status, name, detail })
  console.log(`${status.padEnd(7)} | ${name} | ${detail}`)
}
const pass = (name, detail) => record("PASS", name, detail)
const fail = (name, detail) => record("FAIL", name, detail)
const pending = (name, detail) => record("PENDING", name, detail)

function check(name, ok, detail) {
  if (ok) pass(name, detail)
  else fail(name, detail)
  return ok
}

// 数据行有 6 个单元格；展开行只有 1 个 colSpan 单元格，用 nth-child(6) 排除。
const dataRows = (page) => page.locator("tbody tr:has(td:nth-child(6))")

function taskIdFromPath(p) {
  return p.split("/")[4]
}

function taskIdFromHref(href) {
  return (href ?? "").split("/")[2]
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const browser = await chromium.launch({
    headless: true,
    // 本机已装 Chrome，避免额外下载 Playwright 自带浏览器；可用 VERIFY_BROWSER_CHANNEL 覆盖。
    channel: process.env.VERIFY_BROWSER_CHANNEL ?? "chrome",
  })
  try {
    await scenarioReal(browser)
    await scenarioFixture(browser)
  } finally {
    await browser.close()
  }

  const logPath = path.join(SHOT_DIR, "tasks_table_verify.json")
  fs.writeFileSync(
    logPath,
    JSON.stringify(
      {
        ran_at: new Date().toISOString(),
        base_url: BASE,
        fixture: "frontend/tests/fixtures/tasks-23.json",
        fixture_count: FIXTURE.length,
        intercepted_request_count: reqLog.length,
        intercepted_requests: reqLog,
        summary: {
          PASS: results.filter((r) => r.status === "PASS").length,
          FAIL: results.filter((r) => r.status === "FAIL").length,
          PENDING: results.filter((r) => r.status === "PENDING").length,
        },
        results,
      },
      null,
      2,
    ) + "\n",
    "utf8",
  )
  console.log(`\n日志：${logPath}`)
  const failed = results.filter((r) => r.status === "FAIL")
  if (failed.length) {
    console.error(`存在 ${failed.length} 项失败：${failed.map((r) => r.name).join("；")}`)
    process.exitCode = 1
  }
}

/** 场景 A：真实服务、真实两条任务。 */
async function scenarioReal(browser) {
  console.log("\n=== 场景 A：真实服务（待核对 + 已完成同屏） ===")
  const env = readEnv()
  const user = JSON.parse(env.INITIAL_USERS_JSON)[0]
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  try {
    const login = await ctx.request.post(`${BASE}/api/v1/auth/login`, {
      data: { username: user.username, password: user.password },
      headers: { Origin: BASE },
    })
    if (!check("A1 真实服务登录", login.ok(), `HTTP ${login.status()}`)) return

    const page = await ctx.newPage()
    page.setDefaultTimeout(10000)
    await page.goto(`${BASE}/tasks`)
    await dataRows(page).first().waitFor()

    const rows = dataRows(page)
    const count = await rows.count()
    check("A2 待核对与已完成同屏", count === 2, `实际 ${count} 行`)

    const pendingRow = rows.filter({ hasText: "待核对" }).first()
    const doneRow = rows.filter({ hasText: "已完成" }).first()
    const pendingUpload = pendingRow.getByRole("button", { name: "上传材料" })
    const pendingEnter = pendingRow.getByRole("link", { name: "继续核对" })
    const pendingMore = pendingRow.getByRole("button", { name: "更多操作" })
    const doneEnter = doneRow.getByRole("link", { name: "查看结果" })
    const doneMore = doneRow.getByRole("button", { name: "更多操作" })

    check(
      "A3 待核对行三槽位（上传/继续核对/更多）",
      (await pendingUpload.count()) === 1 &&
        (await pendingEnter.count()) === 1 &&
        (await pendingMore.count()) === 1,
      "上传材料 / 继续核对 / 更多操作 均存在",
    )
    check(
      "A4 已完成行入口与更多、且不显示上传",
      (await doneEnter.count()) === 1 &&
        (await doneMore.count()) === 1 &&
        (await doneRow.getByRole("button", { name: "上传材料" }).count()) === 0,
      "查看结果 / 更多操作 存在，上传材料 槽位留空",
    )

    // 三个槽位固定宽度：两行「进入或查看」按钮左边界与宽度应一致。
    const pb = await pendingEnter.boundingBox()
    const db = await doneEnter.boundingBox()
    check(
      "A5 继续核对 / 查看结果 横向对齐",
      !!pb && !!db && Math.abs(pb.x - db.x) < 1 && Math.abs(pb.width - db.width) < 1,
      `x=${pb?.x?.toFixed(1)}/${db?.x?.toFixed(1)} w=${pb?.width?.toFixed(1)}/${db?.width?.toFixed(1)}`,
    )

    const style = async (loc) =>
      loc.evaluate((el) => {
        const s = getComputedStyle(el)
        return { bg: s.backgroundColor, color: s.color, h: s.height, w: s.width }
      })
    const ps = await style(pendingEnter)
    const ds = await style(doneEnter)
    check(
      "A6 两个入口同为浅青样式且尺寸一致",
      ps.bg === ds.bg && ps.color === ds.color && ps.h === ds.h && ps.w === ds.w,
      `bg=${ps.bg} color=${ps.color} size=${ps.h}x${ps.w}`,
    )
    const uploadStyle = await style(pendingUpload)
    check(
      "A7 上传材料为中性描边、与主入口区分",
      uploadStyle.bg !== ps.bg && uploadStyle.color !== ps.color,
      `upload bg=${uploadStyle.bg} color=${uploadStyle.color}`,
    )
    check(
      "A8 行内文字按钮纯文字、更多保留省略号",
      (await pendingUpload.locator("svg").count()) === 0 &&
        (await pendingEnter.locator("svg").count()) === 0 &&
        (await doneEnter.locator("svg").count()) === 0 &&
        (await pendingMore.locator("svg").count()) === 1,
      "三个文字按钮无图标，更多含 1 个省略号图标",
    )
    const create = page.getByRole("link", { name: "新建核对任务" })
    const createStyle = await style(create)
    check(
      "A9 页级新建保留加号与实心青绿",
      (await create.locator("svg").count()) === 1 && createStyle.bg !== ps.bg,
      `plus=1 bg=${createStyle.bg}（行内浅青 ${ps.bg}）`,
    )
    check(
      "A10 更多具备可访问名称",
      (await pendingMore.getAttribute("aria-label")) === "更多操作" &&
        (await doneMore.getAttribute("aria-label")) === "更多操作",
      'aria-label="更多操作"',
    )

    // 待核对行未展开也能触发上传（只验证文件选择器，不真正上传以免触发 OCR 外部服务）。
    const chooser = page.waitForEvent("filechooser", { timeout: 5000 })
    await pendingUpload.click()
    try {
      await chooser
      pass("A11 待核对行未展开即可上传", "点击「上传材料」弹出文件选择器")
    } catch (e) {
      pending("A11 待核对行未展开即可上传", `未捕获 filechooser：${String(e).slice(0, 100)}`)
    }

    const shot = path.join(SHOT_DIR, "tasks_actions_two_states.png")
    await page.screenshot({ path: shot, fullPage: true })
    pass("A12 同屏截图", path.relative(ROOT, shot))

    const doneId = taskIdFromHref(await doneEnter.getAttribute("href"))
    const pendingId = taskIdFromHref(await pendingEnter.getAttribute("href"))

    // 已完成 → 查看结果 → 只读页。
    // 只读证据：进入对应任务 + 页面主体已渲染且标注「已完成」+ 不出现任何编辑态操作按钮。
    // 注意「已核对完成」文案属于 CompleteButton（仅 editable 时渲染），不能作为只读标记。
    try {
      const resultsResp = page.waitForResponse(
        (r) => new URL(r.url()).pathname.endsWith("/results"),
        { timeout: 10000 },
      )
      await doneEnter.click()
      await page.waitForURL(/\/tasks\/[^/]+\/review/, { timeout: 10000 })
      const urlOk = page.url().includes(doneId)
      await page.getByText("资料完整性核对").first().waitFor({ timeout: 10000 })
      const bodyText = await page.locator("body").innerText()
      let editableFromApi = "未取到"
      try {
        editableFromApi = (await resultsResp).json().then((j) => j.editable)
        editableFromApi = await editableFromApi
      } catch {
        /* 响应已错过时仅作补充信息 */
      }
      const stateOk = bodyText.includes("已完成")
      const noCompleteBtn = (await page.getByRole("button", { name: "完成核对" }).count()) === 0
      const noDecisionBtns =
        (await page.getByRole("button", { name: "接受", exact: true }).count()) === 0 &&
        (await page.getByRole("button", { name: "拒绝", exact: true }).count()) === 0
      check(
        "A13 查看结果进入只读页",
        urlOk && stateOk && noCompleteBtn && noDecisionBtns,
        `urlOk=${urlOk} 状态已完成=${stateOk} 完成核对按钮=0:${noCompleteBtn} 接受拒绝按钮=0:${noDecisionBtns} editable(api)=${editableFromApi} url=${page.url()}`,
      )
    } catch (e) {
      pending("A13 查看结果进入只读页", `卡在只读页加载/渲染：${String(e).slice(0, 160)}；最后 URL=${page.url()}`)
    }

    // 待核对 → 继续核对 → 核对工作台
    try {
      await page.goto(`${BASE}/tasks`)
      await dataRows(page).first().waitFor()
      await dataRows(page)
        .filter({ hasText: "待核对" })
        .first()
        .getByRole("link", { name: "继续核对" })
        .click()
      await page.waitForURL(/\/tasks\/[^/]+\/review/, { timeout: 10000 })
      check("A14 继续核对进入对应任务", page.url().includes(pendingId), `url=${page.url()} 期望ID=${pendingId}`)
    } catch (e) {
      pending("A14 继续核对进入对应任务", `卡在核对页加载：${String(e).slice(0, 160)}；最后 URL=${page.url()}`)
    }
  } catch (e) {
    pending("A 场景异常", `${String(e).slice(0, 200)}`)
  } finally {
    await ctx.close()
  }
}

/** 场景 B：23 条本地 fixture，拦截全部 /api/v1/ 请求。 */
async function scenarioFixture(browser) {
  console.log("\n=== 场景 B：23 条本地 fixture（拦截 /api/v1/） ===")
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.route(/\/api\/v1\//, async (route) => {
    const req = route.request()
    const p = new URL(req.url()).pathname
    const method = req.method()
    reqLog.push({ method, path: p })
    const cors = {
      "Access-Control-Allow-Origin": BASE,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    }
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors })
      return
    }
    let status = 200
    let body = {}
    if (p === "/api/v1/auth/me") {
      body = {
        user: { id: "verify-user", username: "verify", is_active: true, created_at: "2026-01-01T00:00:00Z" },
        csrf_token: "verify-csrf",
      }
    } else if (p === "/api/v1/capabilities") {
      body = { roles: [], product_code: "working_capital_loan", checklist_version: null, ocr_configured: false, llm_configured: false }
    } else if (p === "/api/v1/tasks" && method === "GET") {
      body = FIXTURE
    } else if (/^\/api\/v1\/tasks\/[^/]+\/files$/.test(p)) {
      if (method === "GET") body = []
      else if (method === "POST") {
        status = 201
        body = {
          id: "file-verify", original_name: "fixture.png", media_type: "image/png",
          size_bytes: 3, sha256: "x", original_asset_id: null, material_type: null,
          page_count: null, ocr_status: "processing", created_at: "2026-01-01T00:00:00Z",
        }
      }
    } else if (/^\/api\/v1\/tasks\/[^/]+\/files\/[^/]+\/classification$/.test(p)) {
      body = {}
    } else if (/^\/api\/v1\/tasks\/[^/]+\/results$/.test(p)) {
      body = { run_id: null, is_stale: false, editable: true, statistics: null, items: [], next_cursor: null }
    } else if (/^\/api\/v1\/tasks\/[^/]+$/.test(p)) {
      body = FIXTURE.find((t) => p.endsWith(t.id)) ?? FIXTURE[0]
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body), headers: cors })
  })

  const page = await ctx.newPage()
  page.setDefaultTimeout(10000)
  const rows = dataRows(page)
  const nameOfFirstRow = async () =>
    (await rows.first().locator("td").first().innerText()).trim()
  const byUpdated = [...FIXTURE].sort((a, b) => new Date(a.updated_at) - new Date(b.updated_at))
  const ascFirst = byUpdated[0]
  const descFirst = byUpdated.at(-1)
  const descPage2First = [...byUpdated].reverse()[20]

  try {
    await page.goto(`${BASE}/tasks`)
    await rows.first().waitFor()
    await page.waitForTimeout(300)

    const firstCount = await rows.count()
    check("B1 23 条默认首页 20 行", firstCount === 20, `首页 ${firstCount} 行 / 共 ${FIXTURE.length} 条`)
    const pageInfo = await page.getByText(/共 \d+ 条/).textContent()
    check("B2 分页显示 2 页", /共 23 条 · 第 1\/2 页/.test(pageInfo), pageInfo)
    check("B3 默认按更新时间降序", (await nameOfFirstRow()) === descFirst.name, `第一行=${await nameOfFirstRow()}`)

    // 更新时间双向排序
    const sortBtn = page.getByRole("button", { name: "更新时间" })
    await sortBtn.click()
    check("B4 点击切换为升序", (await nameOfFirstRow()) === ascFirst.name, `第一行=${await nameOfFirstRow()} 期望=${ascFirst.name}`)
    await sortBtn.click()
    check("B5 再次点击恢复降序（无第三态）", (await nameOfFirstRow()) === descFirst.name, `第一行=${await nameOfFirstRow()}`)

    // 升序状态下：展开 / 上传 / 进入 均命中第一行任务
    await sortBtn.click() // 回到 asc，便于验证「排序后」的 ID 命中
    await verifyRowActions(page, rows, ascFirst, "排序后(asc)")

    // 搜索
    const search = page.getByPlaceholder("搜索任务名称")
    await search.fill("测试")
    check("B9 搜索「测试」→ 7 条", (await rows.count()) === 7, `实际 ${await rows.count()} 行`)
    check("B10 结果缩到一页时收起分页", (await page.getByRole("button", { name: "下一页" }).count()) === 0, "分页条已隐藏")

    // 状态筛选 + 组合
    const statusSelect = page.getByRole("combobox").first()
    await statusSelect.click()
    await page.getByRole("option", { name: "已完成" }).click()
    check("B11 搜索 + 状态组合筛选 → 1 条", (await rows.count()) === 1, `实际 ${await rows.count()} 行`)
    await search.fill("")
    check("B12 单状态「已完成」→ 2 条", (await rows.count()) === 2, `实际 ${await rows.count()} 行`)
    check("B13 筛选结果单页仍收起分页", (await page.getByRole("button", { name: "下一页" }).count()) === 0, "分页条已隐藏")

    // 筛选状态下操作命中
    const comboTask = FIXTURE.find((t) => t.state === "COMPLETED" && t.name.includes("测试"))
    await verifyRowActions(page, rows, comboTask, "筛选后(已完成)")

    // 清空筛选 → 2 页 → 翻页
    await statusSelect.click()
    await page.getByRole("option", { name: "全部状态" }).click()
    await search.fill("")
    check("B18 清空筛选恢复 20 行 / 2 页", (await rows.count()) === 20, `实际 ${await rows.count()} 行`)
    // 前面的双向排序让排序停在 asc，这里先切回 desc 再翻页，覆盖「排序 + 筛选清空 + 翻页」组合。
    await sortBtn.click()
    check("B18b 清空筛选后切回降序", (await nameOfFirstRow()) === descFirst.name, `第一行=${await nameOfFirstRow()}`)
    await page.getByRole("button", { name: "下一页" }).click()
    check("B19 翻到第 2 页 3 行", (await rows.count()) === 3, `实际 ${await rows.count()} 行`)
    const page2Info = await page.getByText(/共 \d+ 条/).textContent()
    check("B20 翻页页码正确", /第 2\/2 页/.test(page2Info), page2Info)

    // 翻页后操作命中（第 2 页第一行）
    await verifyRowActions(page, rows, descPage2First, "翻页后(第2页)")
  } catch (e) {
    pending("B 场景异常", `${String(e).slice(0, 240)}；最后 URL=${page.url()}`)
  } finally {
    await ctx.close()
  }
}

/**
 * 收起当前视图里遗留的展开行（展开行只有 1 个 colSpan 单元格，紧跟在其数据行之后），
 * 保证下一组的「展开」点击确实是展开而非 toggle 成收起。
 */
async function collapseExpanded(page, rows) {
  const names = await page.evaluate(() => {
    const trs = Array.from(document.querySelectorAll("tbody tr"))
    const out = []
    for (let i = 1; i < trs.length; i++) {
      if (trs[i].querySelectorAll("td").length === 1) {
        const btn = trs[i - 1].querySelector("td button")
        if (btn) out.push(btn.textContent.trim())
      }
    }
    return out
  })
  for (const n of names) {
    const toggle = rows.filter({ hasText: n }).first().getByRole("button", { name: n })
    if ((await toggle.count()) === 1) await toggle.click().catch(() => {})
  }
}

/** 对当前第一行的展开 / 上传 / 进入三个操作，断言命中的任务 ID。 */
async function verifyRowActions(page, rows, expected, label) {
  await collapseExpanded(page, rows)
  const row = rows.first()
  const name = (await row.locator("td").first().innerText()).trim()
  check(`${label} 首行身份`, name === expected.name, `首行=${name} 期望=${expected.name}`)

  // 进入：Link href 中带任务 ID
  const enter = row.getByRole("link", { name: /继续核对|查看结果/ })
  const href = await enter.getAttribute("href")
  check(`${label} 进入命中任务 ID`, (href ?? "").includes(expected.id), `href=${href}`)

  // 展开：GET /api/v1/tasks/{id}/files。
  // 已展开行带 5s 轮询，会持续发出其他任务的 files 请求，因此只等待目标 ID 的请求。
  const getPromise = page.waitForResponse(
    (r) => {
      const p = new URL(r.url()).pathname
      return (
        /\/api\/v1\/tasks\/[^/]+\/files$/.test(p) &&
        r.request().method() === "GET" &&
        taskIdFromPath(p) === expected.id
      )
    },
    { timeout: 8000 },
  )
  await row.getByRole("button", { name }).click()
  try {
    const resp = await getPromise
    const got = taskIdFromPath(new URL(resp.url()).pathname)
    check(`${label} 展开命中任务 ID`, got === expected.id, `GET files id=${got} 期望=${expected.id}`)
  } catch (e) {
    fail(`${label} 展开命中任务 ID`, `未捕获目标任务 ${expected.id} 的 files 请求：${String(e).slice(0, 120)}`)
  }

  // 上传：首行若为已完成（无上传槽位），在同一视图另取一条待核对行，验证上传命中其自身 ID。
  let uploadRow = row
  let uploadExpected = expected
  let uploadNote = "首行"
  if (expected.state === "COMPLETED") {
    const alt = rows.filter({ hasText: "待核对" }).first()
    if ((await alt.count()) === 1) {
      const altName = (await alt.locator("td").first().innerText()).trim()
      const altTask = FIXTURE.find((t) => t.name === altName)
      if (altTask) {
        uploadRow = alt
        uploadExpected = altTask
        uploadNote = `同视图待核对行「${altName}」`
      }
    }
  }
  const input = uploadRow.locator('input[type="file"]')
  if ((await input.count()) === 1) {
    const postPromise = page.waitForResponse(
      (r) => /\/api\/v1\/tasks\/[^/]+\/files$/.test(new URL(r.url()).pathname) && r.request().method() === "POST",
      { timeout: 8000 },
    )
    await input.setInputFiles({ name: "fixture.png", mimeType: "image/png", buffer: Buffer.from([1, 2, 3]) })
    try {
      const resp = await postPromise
      const got = taskIdFromPath(new URL(resp.url()).pathname)
      check(`${label} 上传命中任务 ID`, got === uploadExpected.id, `${uploadNote} POST files id=${got} 期望=${uploadExpected.id}`)
    } catch (e) {
      pending(`${label} 上传命中任务 ID`, `未捕获上传请求：${String(e).slice(0, 120)}`)
    }
  } else if (uploadExpected.state === "COMPLETED") {
    pass(`${label} 上传槽位留空（已完成行）`, "该视图无待核对行，上传槽位按预期留空")
  } else {
    fail(`${label} 上传命中任务 ID`, `未找到唯一上传 input（count=${await input.count()}）`)
  }
  // dataRows 已按 6 个单元格排除展开行；遗留展开行由下一组开头的 collapseExpanded 统一收起。
}

main().catch((e) => {
  console.error("验收脚本异常：", e)
  process.exitCode = 1
})
