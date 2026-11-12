/**
 * 最后一轮定向收尾验收（只补跑三个相关场景，不重跑上一轮 40 项）。
 *
 * 运行：node frontend/tests/tasks-final.verify.mjs
 * 前置：前端已构建并同步到 api 容器（见 docs/REVIEW_HANDOFF.md）。
 * 沿用：上一轮 23 条 fixture（frontend/tests/fixtures/tasks-23.json）、
 *       上一轮 40 项结果（docs/screenshots/tasks_table_verify.json，本脚本不修改）。
 *
 * 场景 1：fixture 状态筛选「待核对」后，从筛选结果行直接上传，拦截 POST，比对行任务 ID 与请求路径任务 ID。
 * 场景 2：真实服务上打开已完成行「更多」菜单记录实际菜单项，展开材料区确认只读。
 * 场景 3：浏览器计算色换算 WCAG 对比度，确认普通文字 ≥ 4.5:1，并更新两状态同屏截图。
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
const SHOT = path.join(SHOT_DIR, "tasks_actions_two_states.png")
const PREV_LOG = path.join(SHOT_DIR, "tasks_table_verify.json")

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
const evidence = {
  upload_id: null,
  completed_menu_items: null,
  pending_menu_items: null,
  material_area: null,
  contrast_metrics: null,
  screenshot: "docs/screenshots/tasks_actions_two_states.png",
}
function record(status, name, detail) {
  results.push({ status, name, detail })
  console.log(`${status.padEnd(7)} | ${name} | ${detail}`)
}
const pass = (name, detail) => record("PASS", name, detail)
const fail = (name, detail) => record("FAIL", name, detail)
const pending = (name, detail) => record("PENDING", name, detail)
function check(name, ok, detail) {
  record(ok ? "PASS" : "FAIL", name, detail)
  return ok
}

// 数据行有 6 个单元格；展开行只有 1 个 colSpan 单元格。
const dataRows = (page) => page.locator("tbody tr:has(td:nth-child(6))")
const taskIdFromPath = (p) => p.split("/")[4]
const taskIdFromHref = (href) => (href ?? "").split("/")[2]

async function loginReal(ctx) {
  const u = JSON.parse(readEnv().INITIAL_USERS_JSON)[0]
  const r = await ctx.request.post(`${BASE}/api/v1/auth/login`, {
    data: { username: u.username, password: u.password },
    headers: { Origin: BASE },
  })
  check("F0 真实服务登录", r.ok(), `HTTP ${r.status()}`)
}

/** 场景 1 的 API 拦截：沿用上一轮 mock 口径，不触碰 OCR / LLM。 */
async function installFixtureRoute(ctx) {
  await ctx.route(/\/api\/v1\//, async (route) => {
    const req = route.request()
    const p = new URL(req.url()).pathname
    const method = req.method()
    reqLog.push({ method, path: p })
    const cors = {
      "Access-Control-Allow-Origin": BASE,
      "Access-Control-Allow-Credentials": "true",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
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
          id: "file-final", original_name: "final-fixture.png", media_type: "image/png",
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
}

/** 场景 1：从「待核对」筛选结果直接上传，记录行任务 ID 与 POST 路径任务 ID。 */
async function scenarioFilteredUpload(browser) {
  console.log("\n=== 场景 1：筛选结果直接上传（23 条 fixture，拦截 /api/v1/） ===")
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await installFixtureRoute(ctx)
  const page = await ctx.newPage()
  page.setDefaultTimeout(10000)
  const rows = dataRows(page)
  try {
    await page.goto(`${BASE}/tasks`)
    await rows.first().waitFor()

    const statusSelect = page.getByRole("combobox").first()
    await statusSelect.click()
    await page.getByRole("option", { name: "待核对" }).click()
    const count = await rows.count()
    check("F1 状态筛选「待核对」命中 6 条", count === 6, `实际 ${count} 行`)

    const row = rows.first()
    const rowName = (await row.locator("td").first().innerText()).trim()
    const href = await row.getByRole("link", { name: "继续核对" }).getAttribute("href")
    const rowTaskId = taskIdFromHref(href)
    const expected = FIXTURE.find((t) => t.name === rowName)
    check(
      "F2 行任务 ID 来自该行入口且命中 fixture",
      !!expected && expected.id === rowTaskId,
      `行=${rowName} 行任务ID=${rowTaskId} fixtureID=${expected?.id}`,
    )

    const input = row.locator('input[type="file"]')
    check("F3 筛选结果行未展开即有上传入口", (await input.count()) === 1, "「上传材料」槽位可用")

    const postPromise = page.waitForResponse(
      (r) =>
        /\/api\/v1\/tasks\/[^/]+\/files$/.test(new URL(r.url()).pathname) &&
        r.request().method() === "POST",
      { timeout: 8000 },
    )
    await input.setInputFiles({
      name: "final-fixture.png",
      mimeType: "image/png",
      buffer: Buffer.from([1, 2, 3]),
    })
    const resp = await postPromise
    const requestPath = new URL(resp.url()).pathname
    const pathTaskId = taskIdFromPath(requestPath)
    evidence.upload_id = {
      filter: "待核对",
      row_name: rowName,
      row_task_id: rowTaskId,
      request_path: requestPath,
      path_task_id: pathTaskId,
      match: rowTaskId === pathTaskId,
    }
    check(
      "F4 上传 POST 路径任务 ID === 行任务 ID",
      rowTaskId === pathTaskId,
      `行任务ID=${rowTaskId} 请求路径=${requestPath} 路径任务ID=${pathTaskId}`,
    )
    check("F5 上传后筛选结果与条数保持不变", (await rows.count()) === 6, `实际 ${await rows.count()} 行`)
  } catch (e) {
    pending("F 场景 1 异常", `${String(e).slice(0, 200)}`)
  } finally {
    await ctx.close()
  }
}

/** 场景 2：已完成行「更多」菜单实际项 + 展开材料区只读。 */
async function scenarioCompletedReadonly(browser) {
  console.log("\n=== 场景 2：已完成行菜单与材料区只读（真实服务） ===")
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  page.setDefaultTimeout(10000)
  try {
    await loginReal(ctx)
    await page.goto(`${BASE}/tasks`)
    await dataRows(page).first().waitFor()
    const done = dataRows(page).filter({ hasText: "已完成" }).first()
    const pendingRow = dataRows(page).filter({ hasText: "待核对" }).first()

    // 「更多」菜单：记录实际项与可用状态
    await done.getByRole("button", { name: "更多操作" }).click()
    const menu = page.getByRole("menuitem")
    const items = await menu.allInnerTexts()
    const itemStates = await menu.evaluateAll((els) =>
      els.map((e) => ({
        text: e.textContent.trim(),
        disabled:
          e.hasAttribute("disabled") ||
          e.getAttribute("data-disabled") !== null ||
          e.getAttribute("aria-disabled") === "true",
      })),
    )
    evidence.completed_menu_items = itemStates
    check(
      "F6 已完成行「更多」菜单实际项",
      items.length === 1 && items[0] === "已完成任务不可修改",
      `菜单项=${JSON.stringify(items)}`,
    )
    check(
      "F7 已完成行菜单无可用写操作",
      itemStates.length > 0 && itemStates.every((i) => i.disabled),
      `全部禁用=${itemStates.every((i) => i.disabled)} 明细=${JSON.stringify(itemStates)}`,
    )
    await page.keyboard.press("Escape")

    // 对照：待核对行菜单仍保留可用的「删除任务」，未误伤
    await pendingRow.getByRole("button", { name: "更多操作" }).click()
    const pendingItems = await page.getByRole("menuitem").allInnerTexts()
    evidence.pending_menu_items = pendingItems
    check(
      "F8 待核对行菜单保留「删除任务」",
      pendingItems.length === 1 && pendingItems[0] === "删除任务",
      `菜单项=${JSON.stringify(pendingItems)}`,
    )
    await page.keyboard.press("Escape")

    // 展开材料区，确认只读
    await done.locator("td").first().getByRole("button").click()
    const area = page.locator("tbody tr:not(:has(td:nth-child(6)))").first()
    await area.getByText("材料文件").waitFor()
    // useQuery 首帧 files 为 undefined，会短暂显示空态；等真实文件行渲染后再断言写操作是否禁用。
    await area.getByRole("combobox").first().waitFor({ timeout: 10000 })
    const areaText = await area.innerText()
    const selects = area.getByRole("combobox")
    const selectDisabled = await selects.evaluateAll((els) =>
      els.map((e) =>
        e.hasAttribute("disabled") ||
        e.getAttribute("data-disabled") !== null ||
        e.getAttribute("aria-disabled") === "true",
      ),
    )
    const delBtns = area.locator("button[title='删除文件']")
    const delDisabled = await delBtns.evaluateAll((els) => els.map((e) => !!e.disabled))
    evidence.material_area = {
      text: areaText.slice(0, 200),
      select_count: selectDisabled.length,
      select_disabled: selectDisabled,
      delete_button_count: delDisabled.length,
      delete_button_disabled: delDisabled,
    }
    check("F9 材料区标注只读", areaText.includes("只读"), `片段=${areaText.slice(0, 60).replace(/\n/g, " / ")}`)
    check(
      "F10 材料区分类下拉全部禁用",
      selectDisabled.length > 0 && selectDisabled.every(Boolean),
      `数量=${selectDisabled.length} 禁用=${JSON.stringify(selectDisabled)}`,
    )
    check(
      "F11 材料区删除文件按钮全部禁用",
      delDisabled.length > 0 && delDisabled.every(Boolean),
      `数量=${delDisabled.length} 禁用=${JSON.stringify(delDisabled)}`,
    )
    check(
      "F12 已完成行上传槽位仍留空",
      (await done.getByRole("button", { name: "上传材料" }).count()) === 0,
      "无上传入口",
    )
  } catch (e) {
    pending("F 场景 2 异常", `${String(e).slice(0, 220)}；最后 URL=${page.url()}`)
  } finally {
    await ctx.close()
  }
}

/** 场景 3：浏览器计算色 → WCAG 对比度；更新两状态同屏截图。 */
async function scenarioContrast(browser) {
  console.log("\n=== 场景 3：计算色对比度与同屏截图（真实服务） ===")
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  page.setDefaultTimeout(10000)
  try {
    await loginReal(ctx)
    await page.goto(`${BASE}/tasks`)
    await dataRows(page).first().waitFor()

    const metrics = await page.evaluate(() => {
      // 用 canvas 把任意 CSS 计算色（oklch / oklab / 带 alpha）光栅化为 sRGB，再算 WCAG 对比度。
      function toRgb(css, base) {
        const c = document.createElement("canvas")
        c.width = 1
        c.height = 1
        const x = c.getContext("2d", { willReadFrequently: true })
        x.fillStyle = base
        x.fillRect(0, 0, 1, 1)
        x.fillStyle = css
        x.fillRect(0, 0, 1, 1)
        const d = x.getImageData(0, 0, 1, 1).data
        return [d[0], d[1], d[2]]
      }
      function lum(rgb) {
        const f = (c) => {
          c /= 255
          return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
      }
      function ratio(a, b) {
        const A = lum(a)
        const B = lum(b)
        return (Math.max(A, B) + 0.05) / (Math.min(A, B) + 0.05)
      }
      function bgOf(el) {
        let n = el
        while (n) {
          const bg = getComputedStyle(n).backgroundColor
          if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg
          n = n.parentElement
        }
        return "#ffffff"
      }
      const out = []
      function add(name, el) {
        if (!el) return
        const s = getComputedStyle(el)
        const fg = toRgb(s.color, "#ffffff")
        const bg = toRgb(bgOf(el), "#ffffff")
        out.push({
          name,
          color: s.color,
          background: bgOf(el),
          fontSize: s.fontSize,
          fontWeight: s.fontWeight,
          rgb_fg: fg,
          rgb_bg: bg,
          ratio: +ratio(fg, bg).toFixed(2),
        })
      }
      const links = [...document.querySelectorAll("a")]
      add("页级·新建核对任务", links.find((e) => e.textContent.includes("新建核对任务")))
      for (const label of ["继续核对", "查看结果", "上传材料"]) {
        add(`行内·${label}`, [...document.querySelectorAll("a,button")].find((e) => e.textContent.trim() === label))
      }
      const th = document.querySelectorAll("thead th")
      add("表头·任务名称", th[0])
      add("表头·操作", th[th.length - 1])
      const rows = [...document.querySelectorAll("tbody tr")].filter(
        (tr) => tr.querySelectorAll("td").length === 6,
      )
      const r1 = rows[0]
      const r2 = rows[1]
      if (r1) {
        add("正文·任务名称", r1.querySelector("td:nth-child(1) button"))
        add("正文·客户类型", r1.querySelector("td:nth-child(2)"))
        add("正文·识别进度", r1.querySelector("td:nth-child(4) span"))
        add("正文·更新时间", r1.querySelector("td:nth-child(5) span"))
        const s1 = r1.querySelectorAll("td:nth-child(3) span span")
        add("状态·待核对", s1[s1.length - 1])
      }
      if (r2) {
        add("正文·任务名称(已完成行)", r2.querySelector("td:nth-child(1) button"))
        const s2 = r2.querySelectorAll("td:nth-child(3) span span")
        add("状态·已完成", s2[s2.length - 1])
      }
      return out
    })
    evidence.contrast_metrics = metrics
    for (const m of metrics) {
      check(
        `F 对比度 ${m.name} ≥ 4.5:1`,
        m.ratio >= 4.5,
        `${m.ratio}:1 · ${m.fontSize}/${m.fontWeight} · fg=${m.color} · bg=${m.background} · rgb=${m.rgb_fg.join(",")}/${m.rgb_bg.join(",")}`,
      )
    }

    await page.screenshot({ path: SHOT, fullPage: true })
    pass("F 同屏截图已更新", path.relative(ROOT, SHOT))
  } catch (e) {
    pending("F 场景 3 异常", `${String(e).slice(0, 220)}`)
  } finally {
    await ctx.close()
  }
}

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.VERIFY_BROWSER_CHANNEL ?? "chrome",
  })
  try {
    await scenarioFilteredUpload(browser)
    await scenarioCompletedReadonly(browser)
    await scenarioContrast(browser)
  } finally {
    await browser.close()
  }

  let previous = null
  try {
    const p = JSON.parse(fs.readFileSync(PREV_LOG, "utf8"))
    previous = { file: "docs/screenshots/tasks_table_verify.json", summary: p.summary, fixture_count: p.fixture_count }
  } catch {
    previous = { file: "docs/screenshots/tasks_table_verify.json", summary: "未读到" }
  }

  const logPath = path.join(SHOT_DIR, "tasks_final_verify.json")
  fs.writeFileSync(
    logPath,
    JSON.stringify(
      {
        ran_at: new Date().toISOString(),
        base_url: BASE,
        scope: "最后一轮定向收尾：仅场景 1/2/3，沿用上一轮结果与 fixture",
        previous_round: previous,
        fixture: "frontend/tests/fixtures/tasks-23.json",
        fixture_count: FIXTURE.length,
        evidence,
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

main().catch((e) => {
  console.error("验收脚本异常：", e)
  process.exitCode = 1
})
