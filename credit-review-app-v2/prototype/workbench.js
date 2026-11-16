import { evidence } from "./fixtures/charter.js"

const $ = (id) => document.getElementById(id)
const scenarios = {
  normal: "请逐条核对摘录和未找到结果。",
  processing: "章程处理中，结果尚未就绪。",
  missing: "公司章程尚未上传，请补传材料。",
  invalid: "识别覆盖不完整，暂不能完成核对。受影响项：担保限制（无效出处）。",
  truncated: "识别覆盖不完整，暂不能完成核对。受影响项：担保批准与限制（输出截断）。",
  complete: "核对已完成，可以查看历史决定与拒绝原因。",
}
const notFound = { id: "not-found", title: "独立担保授权书", text: "本次样本未找到相关原文。" }
const otherMaterials = { license: "营业执照", financial: "审计财报" }
const stored = JSON.parse(localStorage.getItem("charter-wireframe") || "{}")
const decisions = stored.decisions || {}
let scenario = stored.complete ? "complete" : "normal"
let material = "charter"
let cursor = null
let mark = null
let editing = null

const items = () => scenario === "normal" || scenario === "complete" ? [...evidence, notFound] : evidence
const decision = (item) => scenario === "complete" ? decisions[item.id] || { value: "接受" } : decisions[item.id]
const active = () => material === "charter" && !["processing", "missing"].includes(scenario)
const save = (complete = false) => localStorage.setItem("charter-wireframe", JSON.stringify({ decisions, complete }))

function renderSource() {
  const source = $("source")
  if (!active()) {
    source.textContent = "当前场景暂无原件可预览。"
    $("page-number").textContent = ""
    return
  }
  source.innerHTML = [14, 15].map((page) => `<div class="sheet" id="page-${page}">
    <strong>章程摘录线框 · 样本第 ${page} 页</strong>
  </div>`).join("")
  for (const item of evidence) {
    const [left, top, right] = item.bbox
    const paragraph = document.createElement("p")
    paragraph.textContent = item.text
    paragraph.style.cssText = `left:${left / 1191 * 100}%;top:${top / 1684 * 100}%;width:${(right - left) / 1191 * 100}%`
    $(`page-${item.page}`).append(paragraph)
  }
  $("page-number").textContent = "第 14–15 页 · 坐标线框"
}

function locate(item) {
  mark?.remove()
  const [left, top, right, bottom] = item.bbox
  mark = document.createElement("span")
  mark.className = "mark"
  mark.style.cssText = `left:${left / 1191 * 100}%;top:${top / 1684 * 100}%;width:${(right - left) / 1191 * 100}%;height:${(bottom - top) / 1684 * 100}%`
  const sheet = $(`page-${item.page}`)
  sheet.append(mark)
  $("source").scrollTop = sheet.offsetTop - $("source").firstElementChild.offsetTop + mark.offsetTop - 25
  $("page-number").textContent = `已定位第 ${item.page} 页`
}

function renderResults() {
  const visible = active() ? items() : []
  const editable = active() && scenario !== "complete"
  const total = visible.filter(decision).length
  $("count").textContent = visible.length ? `已确认 ${total} / ${visible.length}` : ""
  $("next").disabled = !editable || total === visible.length
  $("complete").disabled = scenario !== "normal" || !active() || total !== visible.length
  $("results").innerHTML = visible.map((item) => {
    const done = decision(item)
    return `<article tabindex="-1" id="${item.id}">
      <h3>${item.title}</h3><blockquote></blockquote>
      <div class="actions">
        ${item.page ? `<button data-action="locate">查看出处 · 第 ${item.page} 页</button>` : ""}
        ${editable && !done ? '<button data-action="accept">接受</button><button data-action="reject">拒绝</button>' : ""}
        ${editable && done ? '<button data-action="reset">重新选择</button>' : ""}
      </div>
      ${done ? '<p class="decision"></p>' : ""}
      ${editable && editing === item.id ? '<label>拒绝原因（必填）<textarea required></textarea></label><button data-action="save-reject" disabled>保存拒绝</button>' : ""}
    </article>`
  }).join("")
  for (const item of visible) {
    const row = $(item.id)
    row.querySelector("blockquote").textContent = item.text
    const done = decision(item)
    if (done) row.querySelector(".decision").textContent = done.reason ? `已拒绝 · ${done.reason}` : `已${done.value}`
    row.querySelector("textarea")?.addEventListener("input", (event) => {
      row.querySelector('[data-action="save-reject"]').disabled = !event.target.value.trim()
    })
  }
}

function render() {
  $("scenario").value = scenario
  $("banner").textContent = material === "charter" ? scenarios[scenario] : `${otherMaterials[material]}属于后续迁移范围。`
  $("banner").dataset.warning = String(["invalid", "truncated"].includes(scenario) && active())
  renderSource()
  renderResults()
}

$("scenario").addEventListener("change", (event) => {
  scenario = event.target.value
  if (scenario === "normal") save()
  cursor = editing = null
  render()
})
document.querySelector("nav").addEventListener("click", (event) => {
  if (!event.target.dataset.tab) return
  material = event.target.dataset.tab
  document.querySelectorAll("nav button").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.tab === material)))
  render()
})
$("results").addEventListener("click", (event) => {
  const action = event.target.dataset.action
  if (!action) return
  const row = event.target.closest("article")
  const item = items().find(({ id }) => id === row.id)
  cursor = item.id
  if (action === "locate") return locate(item)
  if (action === "reject") editing = item.id
  if (action === "accept") decisions[item.id] = { value: "接受" }
  if (action === "reset") delete decisions[item.id]
  if (action === "save-reject") {
    const reason = row.querySelector("textarea").value.trim()
    if (!reason) return
    decisions[item.id] = { value: "拒绝", reason }
    editing = null
  }
  save()
  renderResults()
  $(item.id).querySelector("textarea")?.focus()
})
$("next").addEventListener("click", () => {
  const all = items()
  const start = all.findIndex(({ id }) => id === cursor) + 1
  const next = [...all.slice(start), ...all.slice(0, start)].find((item) => !decision(item))
  cursor = next.id
  $(cursor).focus()
})
$("complete").addEventListener("click", () => {
  scenario = "complete"
  save(true)
  render()
})
render()
