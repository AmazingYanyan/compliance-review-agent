import {
  evidence,
  notFound,
  pages,
  pageSize,
  task,
  otherMaterials,
  scenarios,
  statusText,
  completedFallbackDecisions,
} from "./fixtures/charter.js"

const $ = (id) => document.getElementById(id)
const STORAGE_KEY = "charter-wireframe"

const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}")
const decisions = stored.decisions || {}
let scenario = stored.complete ? "complete" : "normal"
let material = "charter"
let cursor = null
let mark = null
let editing = null
let selected = null
let currentPage = null
let locatedPage = null
let zoom = "fit"

const conf = () => scenarios[scenario]
const scoped = () => (scenario === "normal" || scenario === "complete") ? [...evidence, notFound] : evidence
const affectedItems = () => scoped().filter((item) => (conf().affected || []).includes(item.id))
const isAffected = (item) => (conf().affected || []).includes(item.id)
const isApprox = () => conf().affectedReason === "无效出处"
const isCompleteMode = () => scenario === "complete"
const isActive = () => material === "charter" && scenario !== "processing" && scenario !== "missing"
const editable = () => isActive() && !isCompleteMode()
const decisionOf = (item) => {
  if (isCompleteMode()) {
    if (item.id === notFound.id) return decisions[item.id] || null
    return decisions[item.id] ?? completedFallbackDecisions[item.id] ?? { value: "接受" }
  }
  return decisions[item.id]
}
const isPending = (item) => editable() && !isAffected(item) && !decisionOf(item)
const save = (complete = isCompleteMode()) => localStorage.setItem(STORAGE_KEY, JSON.stringify({ decisions, complete }))
const esc = (value) => String(value).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))

function progressText() {
  if (scenario === "processing") return "识别中 · 结果未就绪"
  if (scenario === "missing") return "待补传材料 · 无可核对项"
  const items = scoped()
  const notFoundItem = items.find((item) => item.id === notFound.id)
  const checkable = items.filter((item) => item.id !== notFound.id && !isAffected(item))
  const confirmed = checkable.filter((item) => decisionOf(item)).length
  const parts = [`已确认 ${confirmed} / ${checkable.length}`]
  const affected = affectedItems()
  if (affected.length) parts.push(`受影响 ${affected.length} 项（${conf().affectedReason}）`)
  if (notFoundItem) {
    const state = isCompleteMode() ? "人工核对" : decisionOf(notFoundItem) ? "已确认" : "待确认"
    parts.push(`未找到 1 项${state}`)
  }
  return parts.join(" · ")
}

function completionState() {
  if (scenario === "processing") return { blocked: true, reason: "无法完成：核对结果尚未就绪" }
  if (scenario === "missing") return { blocked: true, reason: "无法完成：材料缺失，完成规则待决策" }
  if (isCompleteMode()) return { blocked: true, reason: "核对已完成，当前为只读视图" }
  if (!isActive()) return { blocked: true, reason: "无法完成：当前材料不属于本轮核对范围" }
  const affected = affectedItems()
  if (affected.length) {
    return { blocked: true, reason: `无法完成：${affected.length} 个检查项覆盖不全（${affected.map((i) => i.title).join("、")}）` }
  }
  const blankReason = scoped().filter((item) => decisionOf(item)?.value === "拒绝" && !String(decisionOf(item).reason || "").trim())
  if (blankReason.length) return { blocked: true, reason: `无法完成：${blankReason.length} 项拒绝未填原因` }
  const pendingExcerpt = scoped().filter((item) => item.id !== notFound.id && isPending(item)).length
  const pendingMissing = scoped().filter((item) => item.id === notFound.id && isPending(item)).length
  if (pendingExcerpt && pendingMissing) {
    return { blocked: true, reason: `无法完成：仍有 ${pendingExcerpt} 项摘录未确认、${pendingMissing} 项未找到待确认` }
  }
  if (pendingExcerpt) return { blocked: true, reason: `无法完成：仍有 ${pendingExcerpt} 项摘录未确认` }
  if (pendingMissing) return { blocked: true, reason: `无法完成：仍有 ${pendingMissing} 项未找到待确认` }
  return { blocked: false, reason: "可完成" }
}

function bannerText() {
  if (material !== "charter") return `${otherMaterials[material]}属于后续迁移范围，尚未进入本轮核对。`
  const c = conf()
  let text = c.banner
  const affected = affectedItems()
  if (affected.length) text += ` 受影响项：${affected.map((item) => item.title).join("、")}（${c.affectedReason}）。`
  if (c.processing) text += ` 当前阶段：${c.processing.stages.map((s) => s.name).join(" → ")}（进行中）。`
  if (c.missingMaterial) text += ` 缺少材料：${c.missingMaterial.material}。`
  return text
}

function bannerTone() {
  if (material !== "charter") return "processing"
  return { ready: "", processing: "processing", missing: "missing", warn: "warn", done: "ready" }[conf().status] || ""
}

function scrollPaneTo(pane, element, offset = 8) {
  const paneRect = pane.getBoundingClientRect()
  const rect = element.getBoundingClientRect()
  pane.scrollTop += rect.top - paneRect.top - offset
}

function applyZoom() {
  const source = $("source")
  const base = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sheet-base-w")) || 760
  const scale = zoom === "fit" ? Math.max(0.35, (source.clientWidth - 24) / base) : parseFloat(zoom)
  source.style.setProperty("--sheet-scale", String(scale))
  document.querySelectorAll(".zoom-btn").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.zoom === zoom))
  })
}

function updatePageIndicator() {
  if (!isActive()) {
    $("page-number").textContent = ""
    return
  }
  if (locatedPage) {
    $("page-number").textContent = `已定位第 ${locatedPage} 页${mark?.classList.contains("mark--approx") ? "（近似坐标）" : ""}`
    return
  }
  $("page-number").textContent = currentPage ? `第 ${currentPage} 页 · 坐标线框` : `第 ${pages[0]}–${pages[pages.length - 1]} 页 · 坐标线框`
}

function updatePageButtons() {
  const navPage = currentPage ?? pages[0]
  $("page-prev").disabled = !isActive() || navPage <= pages[0]
  $("page-next").disabled = !isActive() || navPage >= pages[pages.length - 1]
  $("page-input").disabled = !isActive()
  $("page-input").value = String(navPage)
}

function jumpToPage(page) {
  const target = Math.min(pages[pages.length - 1], Math.max(pages[0], page))
  currentPage = target
  locatedPage = null
  $("page-input").value = String(target)
  const sheet = $(`page-${target}`)
  if (sheet) scrollPaneTo($("source"), sheet, 12)
  updatePageIndicator()
  updatePageButtons()
}

function renderSource() {
  const source = $("source")
  if (!isActive()) {
    const note = document.createElement("p")
    note.className = "empty-note"
    note.textContent = scenario === "processing"
      ? "章程处理中，暂无可预览的原件。"
      : scenario === "missing"
        ? "「公司章程」尚未上传，暂无可预览的原件。"
        : "当前场景暂无原件可预览。"
    source.innerHTML = ""
    source.append(note)
    updatePageIndicator()
    updatePageButtons()
    return
  }
  source.innerHTML = pages.map((page) => `<div class="sheet" id="page-${page}"><strong>章程摘录线框 · 样本第 ${page} 页</strong></div>`).join("")
  for (const item of evidence) {
    const [left, top, right] = item.bbox
    const paragraph = document.createElement("p")
    paragraph.textContent = item.text
    paragraph.style.cssText = `left:${left / pageSize.width * 100}%;top:${top / pageSize.height * 100}%;width:${(right - left) / pageSize.width * 100}%`
    $(`page-${item.page}`).append(paragraph)
  }
  applyZoom()
  updatePageIndicator()
  updatePageButtons()
}

function locate(item) {
  mark?.remove()
  const [left, top, right, bottom] = item.bbox
  mark = document.createElement("span")
  mark.className = isAffected(item) && isApprox() ? "mark mark--approx" : "mark"
  mark.style.cssText = `left:${left / pageSize.width * 100}%;top:${top / pageSize.height * 100}%;width:${(right - left) / pageSize.width * 100}%;height:${(bottom - top) / pageSize.height * 100}%`
  $(`page-${item.page}`).append(mark)
  currentPage = item.page
  locatedPage = item.page
  scrollPaneTo($("source"), mark, 60)
  updatePageIndicator()
  updatePageButtons()
}

function decisionLine(item) {
  if (item.id === notFound.id) {
    if (isCompleteMode()) return `<p class="decision">未找到对应原文，已转人工核对。</p>`
    const done = decisionOf(item)
    if (!done) return ""
    return done.value === "拒绝"
      ? `<p class="decision decision--reject">已拒绝 · ${esc(String(done.reason || "").trim() || "未填写原因")}</p>`
      : `<p class="decision decision--accept">已${esc(done.value)}</p>`
  }
  const done = decisionOf(item)
  if (!done) return ""
  if (done.value === "拒绝") {
    const reason = String(done.reason || "").trim()
    return `<p class="decision decision--reject">已拒绝 · ${esc(reason || "未填写原因")}</p>`
  }
  return `<p class="decision decision--accept">已${esc(done.value)}</p>`
}

function cardHtml(item) {
  const affected = isAffected(item)
  const isMissingItem = item.id === notFound.id
  const done = isMissingItem && isCompleteMode() ? null : decisionOf(item)
  const badges = []
  if (affected) badges.push(`<span class="badge badge--warn">${esc(conf().affectedLabel)}</span>`)
  if (isMissingItem) {
    const state = isCompleteMode() ? "人工核对" : done ? "已确认" : "待确认"
    badges.push(`<span class="badge badge--muted">未找到 · ${state}</span>`)
  }
  const actions = []
  if (item.page) actions.push(`<button class="btn btn-secondary" type="button" data-action="locate">查看出处 · 第 ${item.page} 页</button>`)
  if (editable() && !affected) {
    if (!done) {
      actions.push(`<button class="btn btn-primary" type="button" data-action="accept">接受</button>`)
      actions.push(`<button class="btn btn-danger" type="button" data-action="reject">拒绝</button>`)
    } else {
      actions.push(`<button class="btn btn-secondary" type="button" data-action="reset">重新选择</button>`)
    }
  }
  const rejectForm = editable() && !affected && editing === item.id
    ? `<div class="reject-form">
        <label>拒绝原因（必填）<textarea required></textarea></label>
        <button class="btn btn-danger" type="button" data-action="save-reject" disabled>保存拒绝</button>
      </div>`
    : ""
  return `<article class="card${affected ? " card--affected" : ""}${selected === item.id ? " is-selected" : ""}" id="${item.id}" tabindex="-1">
    <div class="card-head">
      <h3><button class="card-title" type="button" data-action="select">${esc(item.title)}</button></h3>
      ${item.page ? `<span class="badge badge--info">第 ${item.page} 页</span>` : ""}
      ${badges.join(" ")}
    </div>
    <button class="excerpt${isMissingItem ? " excerpt--missing" : ""}" type="button" data-action="select">${esc(item.text)}</button>
    ${affected ? `<p class="card-hint">${esc(conf().affectedHint)}</p>` : ""}
    ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}
    ${decisionLine(item)}
    ${rejectForm}
  </article>`
}

function stateCardHtml() {
  if (scenario === "processing") {
    const stages = conf().processing.stages
      .map((stage) => `<li class="row stage" data-state="${stage.state}">${esc(stage.name)}</li>`)
      .join("")
    return `<div class="state-card">
      <h3>章程识别进行中</h3>
      <ol class="stage-list">${stages}</ol>
      <p class="hint">${esc(conf().processing.hint)}</p>
      <p class="card-hint">结果就绪后才会出现可核对的摘录与「完成核对」入口。</p>
    </div>`
  }
  return `<div class="state-card">
    <h3>缺少「${esc(conf().missingMaterial.material)}」</h3>
    <p>本轮核对所需的章程文件尚未上传，暂无可核对内容。</p>
    <div class="actions">
      <button class="btn btn-secondary" type="button" data-action="upload" aria-describedby="upload-hint">补传材料</button>
      <span class="hint" id="upload-hint" role="status" aria-live="polite" hidden>${esc(conf().missingMaterial.hint)}</span>
    </div>
    <p class="hint">占位按钮：上传通道在阶段 B 接入。</p>
    <p class="rule-note">完成规则：${esc(conf().completionRule)}</p>
  </div>`
}

function renderResults() {
  const panel = $("results")
  if (scenario === "processing" || scenario === "missing") {
    panel.innerHTML = stateCardHtml()
    return
  }
  if (!isActive()) {
    panel.innerHTML = `<p class="empty-note">${esc(otherMaterials[material])}属于后续迁移范围，尚未进入本轮核对。</p>`
    return
  }
  panel.innerHTML = scoped().map(cardHtml).join("")
  for (const item of scoped()) {
    const card = $(item.id)
    if (!card) continue
    card.querySelector("textarea")?.addEventListener("input", (event) => {
      card.querySelector('[data-action="save-reject"]').disabled = !event.target.value.trim()
    })
  }
}

function renderHeader() {
  const status = conf().status
  $("status-badge").textContent = statusText[status]
  $("status-badge").className = `badge badge--${{ ready: "ready", processing: "info", missing: "missing", warn: "warn", done: "ready" }[status]}`
  $("progress").textContent = progressText()
  $("count").textContent = progressText()
  $("next").disabled = !editable() || !scoped().some((item) => isPending(item))
  const state = completionState()
  $("complete").setAttribute("aria-disabled", String(state.blocked))
  $("complete").title = state.reason
  $("complete-reason").textContent = state.reason
  $("complete-reason").dataset.state = state.blocked ? "blocked" : "ready"
}

function render() {
  $("scenario").value = scenario
  $("banner").textContent = bannerText()
  $("banner").dataset.tone = bannerTone()
  renderHeader()
  renderSource()
  renderResults()
}

function selectCard(item) {
  selected = item.id
  document.querySelectorAll("#results .card").forEach((card) => card.classList.toggle("is-selected", card.id === item.id))
  const card = $(item.id)
  if (!card) return
  scrollPaneTo($("results"), card, 8)
  card.focus({ preventScroll: true })
}

$("scenario").addEventListener("change", (event) => {
  scenario = event.target.value
  cursor = editing = selected = null
  locatedPage = currentPage = null
  save(scenario === "complete")
  render()
})

document.querySelector(".material-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]")
  if (!button) return
  material = button.dataset.tab
  document.querySelectorAll(".material-tabs button").forEach((tab) => {
    tab.setAttribute("aria-pressed", String(tab.dataset.tab === material))
  })
  render()
})

$("results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]")
  if (!button) return
  const action = button.dataset.action
  if (action === "upload") {
    const hint = $("upload-hint")
    if (hint) hint.hidden = false
    return
  }
  const card = button.closest(".card")
  if (!card) return
  const item = scoped().find(({ id }) => id === card.id)
  if (!item) return
  if (action === "select") {
    selectCard(item)
    return
  }
  cursor = item.id
  if (action === "locate") {
    locate(item)
    return
  }
  if (action === "reject") editing = item.id
  if (action === "accept") decisions[item.id] = { value: "接受" }
  if (action === "reset") delete decisions[item.id]
  if (action === "save-reject") {
    const reason = card.querySelector("textarea").value.trim()
    if (!reason) return
    decisions[item.id] = { value: "拒绝", reason }
    editing = null
  }
  save()
  renderResults()
  renderHeader()
  if (editing === item.id) $(item.id)?.querySelector("textarea")?.focus()
  else $(item.id)?.querySelector(".card-title")?.focus({ preventScroll: true })
})

$("next").addEventListener("click", () => {
  const all = scoped()
  const start = all.findIndex(({ id }) => id === cursor) + 1
  const next = [...all.slice(start), ...all.slice(0, start)].find((item) => isPending(item))
  if (!next) return
  cursor = next.id
  selectCard(next)
})

$("complete").addEventListener("click", () => {
  if (completionState().blocked) return
  scenario = "complete"
  save(true)
  render()
})

$("page-prev").addEventListener("click", () => jumpToPage((currentPage ?? pages[0]) - 1))
$("page-next").addEventListener("click", () => jumpToPage((currentPage ?? pages[0]) + 1))
$("page-input").addEventListener("change", (event) => {
  const value = parseInt(event.target.value, 10)
  jumpToPage(Number.isFinite(value) ? value : (currentPage ?? pages[0]))
})

document.querySelectorAll(".zoom-btn").forEach((button) => {
  button.addEventListener("click", () => {
    zoom = button.dataset.zoom
    applyZoom()
  })
})

window.addEventListener("resize", () => {
  if (zoom === "fit") applyZoom()
})

$("task-name").textContent = task.name
$("customer-role").textContent = `客户角色：${task.customerRole}`
$("revision").textContent = task.revision

render()
