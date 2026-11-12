import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"
import { ArrowRight, Check, ChevronDown, ChevronRight, ChevronUp, FileText, LocateFixed, Upload, X } from "lucide-react"
import { Document, Page, pdfjs } from "react-pdf"
import "react-pdf/dist/Page/AnnotationLayer.css"
import "react-pdf/dist/Page/TextLayer.css"

import {
  completeTask,
  getTask,
  listFiles,
  listResults,
  listTasks,
  updateDecision,
} from "@/api/endpoints"
import {
  CUSTOMER_ROLE_LABEL,
  MATERIAL_LABEL,
  NOT_FOUND_REASON_LABEL,
  TASK_STATE_LABEL,
  type Result,
  type ResultList,
  type Statistics,
  type Task,
  type TaskFile,
} from "@/api/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString()

export const Route = createFileRoute("/_layout/tasks/$taskId/review")({
  component: Review,
})

const MATERIAL_ORDER = ["business_license", "articles_of_association", "audited_financials"]

function materialRank(m: string | null | undefined): number {
  const i = MATERIAL_ORDER.indexOf(m ?? "")
  return i < 0 ? MATERIAL_ORDER.length : i
}

/** 稳定排序：材料页签 → 检查项 → 摘录 rank → id */
function compareResult(a: Result, b: Result): number {
  const m = materialRank(a.material_type) - materialRank(b.material_type)
  if (m !== 0) return m
  const c = (a.check_item_id ?? "").localeCompare(b.check_item_id ?? "")
  if (c !== 0) return c
  const r = (a.rank ?? 0) - (b.rank ?? 0)
  if (r !== 0) return r
  return a.id.localeCompare(b.id)
}

/** 待处理 = 未选择 或 拒绝但原因未填（同一条只计一次） */
function isTodoItem(r: Result): boolean {
  const d = r.decision.decision
  if (d === "unselected") return true
  return d === "rejected" && !(r.decision.reject_reason ?? "").trim()
}

/** 从当前材料第一个待办开始；当前材料无待办则回到全局第一个待办 */
function firstTodoIndex(ordered: Result[], todoIds: Set<string>, material: string): number {
  const inMaterial = ordered.findIndex((i) => i.material_type === material && todoIds.has(i.id))
  if (inMaterial >= 0) return inMaterial
  const any = ordered.findIndex((i) => todoIds.has(i.id))
  return any >= 0 ? any : 0
}

interface Location {
  fileId: string
  pageNumber: number
  bbox: number[] | null
  pageWidth: number | null
  pageHeight: number | null
  coordinateSpace: string | null
}

function Review() {
  const { taskId } = Route.useParams()
  const navigate = useNavigate()

  const { data: task } = useQuery({ queryKey: ["task", taskId], queryFn: () => getTask(taskId) })
  const { data: tasks } = useQuery({ queryKey: ["tasks"], queryFn: listTasks })
  const { data: files } = useQuery<TaskFile[]>({
    queryKey: ["files", taskId],
    queryFn: () => listFiles(taskId),
    refetchInterval: 5000,
  })
  const { data: results } = useQuery<ResultList>({
    queryKey: ["results", taskId],
    queryFn: () => listResults(taskId),
  })

  const [activeMaterial, setActiveMaterial] = useState<string>("")
  const [location, setLocation] = useState<Location | null>(null)
  const [focusResultId, setFocusResultId] = useState<string | null>(null)
  const [todoFilter, setTodoFilter] = useState<null | "unchecked" | "missing">(null)
  const [anchorId, setAnchorId] = useState<string | null>(null)

  const materials = MATERIAL_ORDER.filter((m) =>
    results?.items.some((i) => i.material_type === m),
  )
  const currentMaterial = activeMaterial && materials.includes(activeMaterial)
    ? activeMaterial
    : materials[0] ?? ""

  const currentItems = (results?.items ?? []).filter(
    (i) => i.material_type === currentMaterial,
  )
  // 整类材料未上传：该材料所有条目均为 material_missing
  const isCurrentMaterialMissing =
    currentItems.length > 0 &&
    currentItems.every((i) => i.not_found_reason === "material_missing")
  const stat = results?.statistics?.overall
  const editable = results?.editable === true && task?.state !== "COMPLETED"

  const switchTask = (id: string) => {
    if (id !== taskId) {
      navigate({ to: "/tasks/$taskId/review", params: { taskId: id } })
    }
  }

  // 全量条目稳定排序 + 待办队列（待办 = 未选择 或 拒绝缺原因，同一条只计一次）
  const orderedItems = useMemo(
    () => [...(results?.items ?? [])].sort(compareResult),
    [results],
  )
  const todoQueue = useMemo(
    () => orderedItems.filter(isTodoItem),
    [orderedItems],
  )

  // 切换任务 / 刷新时重建锚点
  useEffect(() => {
    setAnchorId(null)
    setFocusResultId(null)
    setActiveMaterial("")
    setLocation(null)
  }, [taskId])

  const jumpToResult = (resultId: string) => {
    const item = results?.items.find((i) => i.id === resultId)
    if (!item) return
    setActiveMaterial(item.material_type ?? "")
    setFocusResultId(resultId)
    // 清单焦点与原件高亮分离：切换条目即清除旧高亮，定位原文另行显式触发
    setLocation(null)
    if (isTodoItem(item)) setAnchorId(resultId)
  }

  const jumpNext = () => {
    if (todoQueue.length === 0 || orderedItems.length === 0) return
    const todoIds = new Set(todoQueue.map((i) => i.id))

    let startIdx: number
    if (anchorId) {
      const idx = orderedItems.findIndex((i) => i.id === anchorId)
      if (idx >= 0) {
        startIdx = idx + 1 // 从锚点之后向后走（保存后锚点仍在全量列表中，自然跳过已处理项）
      } else {
        startIdx = firstTodoIndex(orderedItems, todoIds, currentMaterial)
      }
    } else {
      startIdx = firstTodoIndex(orderedItems, todoIds, currentMaterial)
    }

    let target: Result | null = null
    for (let k = 0; k < orderedItems.length; k++) {
      const idx = (startIdx + k) % orderedItems.length
      if (todoIds.has(orderedItems[idx].id)) {
        target = orderedItems[idx]
        break
      }
    }
    if (!target) return
    setAnchorId(target.id)
    jumpToResult(target.id)
  }

  const jumpToRejected = () => {
    const rejected = (results?.items ?? []).filter((i) => i.decision.decision === "rejected")
    if (rejected.length === 0) return
    jumpToResult(rejected[0].id)
  }

  // 定位后滚动到目标条目（缺材料面板展开后由其自身滚动兜底）
  useEffect(() => {
    if (!focusResultId) return
    const el = document.getElementById(`evidence-${focusResultId}`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [focusResultId, currentMaterial])

  const todoList = (results?.items ?? []).filter((i) => {
    if (todoFilter === "unchecked") return i.decision.decision === "unselected"
    if (todoFilter === "missing") return i.decision.decision === "rejected" && !i.decision.reject_reason
    return false
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 标题行：任务名 + 切换 + 完成核对 */}
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold">资料完整性核对</h1>
          <p className="truncate text-xs text-muted-foreground">
            {task
              ? `${task.name} · ${CUSTOMER_ROLE_LABEL[task.customer_role]} · ${TASK_STATE_LABEL[task.state]}`
              : "加载中…"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Select value={taskId} onValueChange={switchTask}>
            <SelectTrigger size="sm" className="w-48">
              <SelectValue placeholder="切换任务" />
            </SelectTrigger>
            <SelectContent>
              {(tasks ?? []).map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {editable && <CompleteButton taskId={taskId} task={task} results={results} />}
        </div>
      </div>

      {/* 统计条 */}
      {stat && (
        <StatBar
          stat={stat}
          editable={editable}
          onNext={jumpNext}
          onJumpRejected={jumpToRejected}
          onOpenTodo={setTodoFilter}
        />
      )}

      {/* 材料 Tab 左对齐，单独一行 */}
      <Tabs value={currentMaterial} onValueChange={setActiveMaterial} className="mt-3">
        <TabsList>
          {materials.map((m) => (
            <TabsTrigger key={m} value={m}>
              {MATERIAL_LABEL[m] ?? m}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* 内容区：整类材料未上传用单一缺失面板，否则左 60% 右 40% */}
      {isCurrentMaterialMissing ? (
        <MissingMaterialPanel
          material={currentMaterial}
          items={currentItems}
          taskId={taskId}
          runId={results?.run_id ?? ""}
          editable={editable}
          onLocate={setLocation}
          focusResultId={focusResultId}
        />
      ) : (
        <div className="mt-3 flex min-h-0 flex-1 gap-4">
          <MaterialPreview
            material={currentMaterial}
            files={files ?? []}
            results={results}
            taskId={taskId}
            location={location}
            editable={editable}
          />
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardContent className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
              <div className="mb-1 text-sm font-medium">检查项与摘录</div>
              <div className="mb-3 text-xs text-muted-foreground">
                仅展示原文 · 不生成分析结论
                {currentItems.some((i) => i.not_found_reason === "material_missing") &&
                  " · 接受仅确认本次缺失记录"}
              </div>
              {currentItems.length === 0 ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  {results?.run_id ? "该材料暂无检查结果。" : "尚未开始核对。"}
                </div>
              ) : (
                <div className="space-y-3">
                  {groupByCheck(currentItems).map(([checkId, items]) => (
                    <CheckItemCard
                      key={checkId}
                      checkId={checkId}
                      items={items}
                      taskId={taskId}
                      runId={results!.run_id!}
                      editable={editable}
                      onLocate={setLocation}
                      focusResultId={focusResultId}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* 待办面板 */}
      {todoFilter && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/20 pt-20"
          onClick={() => setTodoFilter(null)}
        >
          <div
            className="max-h-[70vh] w-[480px] overflow-y-auto rounded-lg border bg-background p-4 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">
                {todoFilter === "unchecked" ? "未核对条目" : "拒绝原因待填条目"}
              </span>
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground"
                onClick={() => setTodoFilter(null)}
              >
                ✕
              </button>
            </div>
            {todoList.length === 0 ? (
              <div className="py-6 text-center text-sm text-muted-foreground">无待处理条目</div>
            ) : (
              <div className="space-y-1">
                {groupByMaterial(todoList).map(([mat, items]) => (
                  <TodoMaterialGroup
                    key={mat}
                    mat={mat}
                    items={items}
                    onJump={(id) => {
                      jumpToResult(id)
                      setTodoFilter(null)
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function groupByCheck(items: Result[]): [string, Result[]][] {
  const map = new Map<string, Result[]>()
  for (const r of items) {
    if (!map.has(r.check_item_id)) map.set(r.check_item_id, [])
    map.get(r.check_item_id)!.push(r)
  }
  return [...map.entries()]
}

function groupByMaterial(items: Result[]): [string, Result[]][] {
  const map = new Map<string, Result[]>()
  for (const r of items) {
    const m = r.material_type ?? "unknown"
    if (!map.has(m)) map.set(m, [])
    map.get(m)!.push(r)
  }
  return [...map.entries()]
}

function shortText(r: Result): string {
  if (r.kind === "not_found") {
    return NOT_FOUND_REASON_LABEL[r.not_found_reason ?? ""] ?? r.not_found_reason ?? "未找到"
  }
  return (r.text ?? "").replace(/\s+/g, " ").slice(0, 30)
}

function TodoMaterialGroup({
  mat,
  items,
  onJump,
}: {
  mat: string
  items: Result[]
  onJump: (id: string) => void
}) {
  const label = MATERIAL_LABEL[mat] ?? mat
  // 整组均为缺材料时合并为一个缺失组，按需展开
  const allMissing = items.every((i) => i.not_found_reason === "material_missing")
  const [open, setOpen] = useState(false)

  if (!allMissing) {
    return (
      <div>
        <div className="mt-2 text-xs font-medium text-muted-foreground">{label}</div>
        {items.map((i) => (
          <TodoRow key={i.id} i={i} onJump={onJump} />
        ))}
      </div>
    )
  }

  return (
    <div>
      <button
        type="button"
        className="mt-2 flex w-full items-center gap-1 rounded px-2 py-1.5 text-left text-xs hover:bg-muted"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="font-medium">未上传{label}</span>
        <span className="text-muted-foreground">· {items.length} 项缺失</span>
        <span className="ml-auto text-muted-foreground">
          {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
        </span>
      </button>
      {open && (
        <div className="pl-3">
          {items.map((i) => (
            <TodoRow key={i.id} i={i} onJump={onJump} />
          ))}
        </div>
      )}
    </div>
  )
}

function TodoRow({ i, onJump }: { i: Result; onJump: (id: string) => void }) {
  return (
    <button
      type="button"
      className="block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-muted"
      onClick={() => onJump(i.id)}
    >
      <span className="font-medium">{i.check_label}</span>
      <span className="text-muted-foreground"> · {shortText(i)}</span>
    </button>
  )
}

function StatBar({
  stat,
  editable,
  onNext,
  onJumpRejected,
  onOpenTodo,
}: {
  stat: Statistics
  editable: boolean
  onNext: () => void
  onJumpRejected: () => void
  onOpenTodo: (kind: "unchecked" | "missing") => void
}) {
  const todo = stat.unselected + stat.missing_reason
  const confirmed = stat.accepted + (stat.rejected - stat.missing_reason)

  if (!editable) {
    return (
      <div className="mt-3 flex items-center gap-3 rounded-md border px-3 py-2">
        <span className="text-sm font-medium">
          已核对 <span className="text-base font-bold">{stat.total}/{stat.total}</span>
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
          已接受 {stat.accepted}
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700 hover:underline"
          onClick={onJumpRejected}
        >
          已拒绝 {stat.rejected} →
        </button>
      </div>
    )
  }

  return (
    <div className="mt-3 flex items-center gap-3 rounded-md border px-3 py-2">
      <span className="text-sm font-medium">
        待处理 <span className="text-base font-bold">{todo}</span> 条
      </span>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground hover:underline"
        onClick={() => onOpenTodo("unchecked")}
      >
        未核对 {stat.unselected}
      </button>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700 hover:underline"
        onClick={() => onOpenTodo("missing")}
      >
        待补原因 {stat.missing_reason}
      </button>
      <span className="ml-auto text-xs text-muted-foreground">
        已核对 {confirmed}/{stat.total}
      </span>
      {todo > 0 && (
        <Button size="sm" onClick={onNext}>
          下一条待处理 <ArrowRight className="size-3" />
        </Button>
      )}
    </div>
  )
}

function CompleteButton({
  taskId,
  task,
  results,
}: {
  taskId: string
  task: Task | undefined
  results: ResultList | undefined
}) {
  const queryClient = useQueryClient()
  const [blockMsg, setBlockMsg] = useState("")

  const complete = useMutation({
    mutationFn: () => completeTask(taskId, results!.run_id!, task!.input_revision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", taskId] })
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["results", taskId] })
    },
    onError: (err: unknown) => {
      const detail = (err as {
        response?: {
          data?: {
            detail?: {
              message?: string
              incomplete?: { unselected?: { check_label: string }[]; missing_reason?: { check_label: string }[] }
            }
          }
        }
      }).response?.data?.detail
      const inc = detail?.incomplete
      if (inc) {
        const parts: string[] = []
        if (inc.unselected?.length) parts.push(`未确认：${inc.unselected.map((x) => x.check_label).join("、")}`)
        if (inc.missing_reason?.length) parts.push(`拒绝待填原因：${inc.missing_reason.map((x) => x.check_label).join("、")}`)
        setBlockMsg(parts.join("；"))
      } else {
        setBlockMsg(detail?.message ?? "无法完成核对")
      }
    },
  })

  if (task?.state === "COMPLETED") {
    return <span className="text-xs text-green-600">已核对完成</span>
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button size="sm" onClick={() => { setBlockMsg(""); complete.mutate() }} disabled={complete.isPending}>
        完成核对
      </Button>
      {blockMsg && <span className="max-w-[320px] text-right text-xs text-red-600">{blockMsg}</span>}
    </div>
  )
}

function MaterialPreview({
  material,
  files,
  results,
  taskId,
  location,
  editable,
}: {
  material: string
  files: TaskFile[]
  results: ResultList | undefined
  taskId: string
  location: Location | null
  editable: boolean
}) {
  const navigate = useNavigate()
  const materialFileIds = new Set<string>()
  if (results) {
    for (const i of results.items) {
      if (i.material_type === material) {
        for (const s of i.sources) if (s.file_id) materialFileIds.add(s.file_id)
      }
    }
  }
  const materialFiles = files.filter((f) => materialFileIds.has(f.id))

  const targetFileId = location?.fileId && materialFileIds.has(location.fileId)
    ? location.fileId
    : materialFiles[0]?.id
  const targetFile = files.find((f) => f.id === targetFileId)

  if (!targetFile) {
    return (
      <Card className="flex min-h-0 w-[60%] flex-col overflow-hidden">
        <CardContent className="flex flex-1 flex-col items-center justify-center gap-3 p-4">
          <FileText className="size-10 text-muted-foreground" />
          <div className="text-sm text-muted-foreground">
            {material ? `未上传${MATERIAL_LABEL[material] ?? material}` : "请选择材料"}
          </div>
          {editable ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate({ to: "/tasks", search: { expand: taskId } })}
            >
              <Upload className="size-4" /> 补传材料
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">该材料缺失（任务已完成，只读）</span>
          )}
        </CardContent>
      </Card>
    )
  }

  const assetUrl = `/api/v1/tasks/${taskId}/assets/${targetFile.original_asset_id}`
  const isPdf = targetFile.media_type === "application/pdf"
  const pageNumber = location?.pageNumber ?? 1
  const fileStatus = materialFiles.some((f) => f.ocr_status === "processing")
    ? "processing"
    : materialFiles.every((f) => f.ocr_status === "failed")
      ? "failed"
      : "done"

  return (
    <Card className="flex min-h-0 w-[60%] flex-col overflow-hidden">
      <CardContent className="flex min-h-0 flex-1 flex-col p-3">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="flex items-center gap-1.5 font-medium">
            <FileText className="size-4 text-muted-foreground" />
            {targetFile.original_name}
          </span>
          <span className="text-xs text-muted-foreground">
            {isPdf ? `第 ${pageNumber} 页` : `${MATERIAL_LABEL[material] ?? material}`}
          </span>
        </div>
        <div className="relative flex-1 overflow-auto rounded-md border bg-muted/30">
          {fileStatus === "processing" && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/70">
              <span className="text-sm text-muted-foreground">识别中…</span>
            </div>
          )}
          {fileStatus === "failed" && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/70">
              <span className="text-sm text-red-600">识别失败，请重新上传</span>
            </div>
          )}
          {isPdf ? (
            <PdfViewer file={assetUrl} pageNumber={pageNumber} location={location} />
          ) : (
            <ImagePreview src={assetUrl} location={location} />
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function PdfViewer({
  file,
  pageNumber,
  location,
}: {
  file: string
  pageNumber: number
  location: Location | null
}) {
  const [numPages, setNumPages] = useState(0)
  const pageOnly = location?.bbox && location.coordinateSpace !== "ocr_input_image_pixels"
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-auto">
        <Document file={file} onLoadSuccess={({ numPages }) => setNumPages(numPages)}>
          <Page pageNumber={pageNumber} />
        </Document>
      </div>
      <div className="border-t px-3 py-1.5 text-center text-xs text-muted-foreground">
        {pageOnly
          ? "仅定位到页（该出处坐标不可靠，未绘制高亮框）"
          : `第 ${pageNumber} / ${numPages} 页`}
      </div>
    </div>
  )
}

function ImagePreview({ src, location }: { src: string; location: Location | null }) {
  const highlight =
    location?.bbox && location.pageWidth && location.pageHeight
      ? {
          left: (location.bbox[0] / location.pageWidth) * 100,
          top: (location.bbox[1] / location.pageHeight) * 100,
          width: ((location.bbox[2] - location.bbox[0]) / location.pageWidth) * 100,
          height: ((location.bbox[3] - location.bbox[1]) / location.pageHeight) * 100,
        }
      : null
  return (
    <div className="relative h-full overflow-auto">
      <div className="relative inline-block min-w-full">
        <img src={src} alt="材料预览" className="block max-w-none" />
        {highlight && (
          <div
            className="absolute rounded-sm border-2 border-blue-500 bg-blue-400/20"
            style={{
              left: `${highlight.left}%`,
              top: `${highlight.top}%`,
              width: `${highlight.width}%`,
              height: `${highlight.height}%`,
            }}
          />
        )}
      </div>
    </div>
  )
}

function MissingMaterialPanel({
  material,
  items,
  taskId,
  runId,
  editable,
  onLocate,
  focusResultId,
}: {
  material: string
  items: Result[]
  taskId: string
  runId: string
  editable: boolean
  onLocate: (loc: Location) => void
  focusResultId: string | null
}) {
  const navigate = useNavigate()
  const [showAffected, setShowAffected] = useState(false)

  const focusedHere = !!focusResultId && items.some((i) => i.id === focusResultId)

  // 跳转到本面板内的缺失条目时自动展开详情
  useEffect(() => {
    if (focusedHere) setShowAffected(true)
  }, [focusedHere])

  // 展开后滚动到聚焦条目
  useEffect(() => {
    if (showAffected && focusedHere && focusResultId) {
      const el = document.getElementById(`evidence-${focusResultId}`)
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [showAffected, focusedHere, focusResultId])

  const label = MATERIAL_LABEL[material] ?? material

  return (
    <div className="mt-3 flex min-h-0 flex-1 flex-col overflow-y-auto rounded-md border px-4 py-3">
      <div className="flex items-center gap-2">
        <FileText className="size-4 text-muted-foreground" />
        <span className="text-sm font-medium">未上传{label}</span>
        <span className="text-xs text-muted-foreground">{items.length} 项受影响</span>
        <div className="ml-auto flex items-center gap-3">
          {editable ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate({ to: "/tasks", search: { expand: taskId } })}
            >
              <Upload className="size-3" /> 补传材料
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">该材料缺失 · 已完成核对（只读）</span>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-0.5 text-xs text-blue-600 hover:underline"
            onClick={() => setShowAffected((v) => !v)}
          >
            {showAffected ? (
              <>
                收起受影响项 <ChevronDown className="size-3" />
              </>
            ) : (
              <>
                查看受影响的 {items.length} 项 <ChevronRight className="size-3" />
              </>
            )}
          </button>
        </div>
      </div>

      {showAffected && (
        <div className="mt-3 space-y-3">
          {groupByCheck(items).map(([checkId, rs]) => (
            <CheckItemCard
              key={checkId}
              checkId={checkId}
              items={rs}
              taskId={taskId}
              runId={runId}
              editable={editable}
              onLocate={onLocate}
              focusResultId={focusResultId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CheckItemCard({
  checkId,
  items,
  taskId,
  runId,
  editable,
  onLocate,
  focusResultId,
}: {
  checkId: string
  items: Result[]
  taskId: string
  runId: string
  editable: boolean
  onLocate: (loc: Location) => void
  focusResultId: string | null
}) {
  const label = items[0].check_label || checkId
  const group = items[0].group_label
  // 摘录计数只取真实原文摘录（not_found 无原文，不计入）
  const excerptCount = items.filter((i) => i.kind !== "not_found").length
  return (
    <div className="rounded-md border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{label}</span>
        {group && <span className="text-xs text-muted-foreground">（{group}）</span>}
        {excerptCount > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">{excerptCount} 条摘录</span>
        )}
      </div>
      <div className="mt-1.5 space-y-2">
        {items.map((r) => (
          <EvidenceItem
            key={r.id}
            r={r}
            taskId={taskId}
            runId={runId}
            editable={editable}
            onLocate={onLocate}
            focused={focusResultId === r.id}
          />
        ))}
      </div>
    </div>
  )
}

function EvidenceItem({
  r,
  taskId,
  runId,
  editable,
  onLocate,
  focused,
}: {
  r: Result
  taskId: string
  runId: string
  editable: boolean
  onLocate: (loc: Location) => void
  focused: boolean
}) {
  const queryClient = useQueryClient()
  const decision = r.decision.decision
  const [rejectReason, setRejectReason] = useState("")
  const [showReason, setShowReason] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const decide = useMutation({
    mutationFn: (body: { decision: string; reject_reason: string | null }) =>
      updateDecision(taskId, r.id, { run_id: runId, ...body }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["results", taskId] })
      if (vars.decision === "rejected" && !vars.reject_reason) {
        setShowReason(true)
      } else {
        setShowReason(false)
      }
      setRejectReason("")
    },
  })

  const decisionBadge =
    decision === "accepted" ? (
      <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-[10px] text-green-700">已接受</span>
    ) : decision === "rejected" ? (
      <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[10px] text-red-700">已拒绝</span>
    ) : (
      <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">未核对</span>
    )

  const isLong = (r.text?.length ?? 0) > 120

  // 点击正文切换展开/收起；有选中文本时不切换（避免干扰复制）
  const toggleExpand = () => {
    const sel = window.getSelection()
    if (sel && sel.toString().length > 0) return
    setExpanded((v) => !v)
  }

  const body = (() => {
    if (r.kind === "not_found") {
      const reasonLabel =
        NOT_FOUND_REASON_LABEL[r.not_found_reason ?? ""] ?? r.not_found_reason ?? "未找到"
      const isMissing = r.not_found_reason === "material_missing"
      return (
        <div className={`flex-1 rounded px-2 py-1 text-xs ${isMissing ? "bg-muted text-muted-foreground" : "bg-amber-50 text-amber-700"}`}>
          {reasonLabel}
        </div>
      )
    }
    if (r.kind === "table" && r.table_html) {
      return (
        <div
          className="min-w-0 flex-1 overflow-x-auto text-xs [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:px-2 [&_td]:py-1"
          dangerouslySetInnerHTML={{ __html: r.table_html }}
        />
      )
    }
    if (!r.text) return <div className="flex-1" />
    if (!isLong) {
      return (
        <div className="min-w-0 flex-1">
          <div className="whitespace-pre-wrap">{r.text}</div>
          {r.relation_status === "needs_review" && (
            <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 text-amber-700">待复核</span>
          )}
        </div>
      )
    }
    return (
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-1">
          <div
            className={cn(
              "min-w-0 flex-1 cursor-pointer whitespace-pre-wrap",
              expanded ? "" : "line-clamp-3",
            )}
            onClick={toggleExpand}
            title={expanded ? "点击收起" : "点击展开全文"}
          >
            {r.text}
          </div>
          <button
            type="button"
            className="shrink-0 rounded p-0.5 text-blue-600 hover:bg-blue-50"
            aria-expanded={expanded}
            aria-label={expanded ? "收起原文" : "展开原文"}
            title={expanded ? "收起原文" : "展开原文"}
            onClick={toggleExpand}
          >
            {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
        </div>
        {r.relation_status === "needs_review" && (
          <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 text-amber-700">待复核</span>
        )}
      </div>
    )
  })()

  return (
    <div
      id={`evidence-${r.id}`}
      className={`rounded border-l-2 bg-muted/50 px-2 py-1.5 text-xs ${
        focused ? "border-l-blue-500 ring-1 ring-blue-300" : "border-l-transparent"
      }`}
    >
      <div className="flex items-start gap-2">
        {body}
        {!editable && decisionBadge}
      </div>
      <SourceLine r={r} onLocate={onLocate} />

      {editable && (
        <div className="mt-1 flex items-center gap-2">
          {decision === "accepted" ? (
            <Button
              size="sm"
              className="h-6 bg-green-600 px-2 text-xs hover:bg-green-700"
              onClick={() => decide.mutate({ decision: "unselected", reject_reason: null })}
              title="点击重置"
            >
              <Check className="size-3" /> 已接受
            </Button>
          ) : decision === "rejected" ? (
            <Button
              size="sm"
              className="h-6 bg-red-600 px-2 text-xs hover:bg-red-700"
              onClick={() => decide.mutate({ decision: "unselected", reject_reason: null })}
              title="点击重置并清空原因"
            >
              <X className="size-3" /> 已拒绝
            </Button>
          ) : (
            <>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs text-green-700"
                onClick={() => decide.mutate({ decision: "accepted", reject_reason: null })}
              >
                <Check className="size-3" /> 接受
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs text-red-700"
                onClick={() => decide.mutate({ decision: "rejected", reject_reason: null })}
              >
                <X className="size-3" /> 拒绝
              </Button>
            </>
          )}
        </div>
      )}
      {editable && decision === "rejected" && showReason && (
        <div className="mt-1.5 space-y-1.5">
          <textarea
            className="w-full rounded-md border px-2 py-1.5 text-sm"
            rows={2}
            placeholder="请填写拒绝原因（必填）"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!rejectReason.trim() || decide.isPending}
            onClick={() => decide.mutate({ decision: "rejected", reject_reason: rejectReason })}
          >
            保存原因
          </Button>
        </div>
      )}
      {editable && decision === "rejected" && !showReason && (
        <div className="mt-1 text-xs text-muted-foreground">
          {r.decision.reject_reason ? (
            <span>原因：{r.decision.reject_reason}</span>
          ) : (
            <span className="text-amber-600">待填写拒绝原因</span>
          )}
        </div>
      )}
      {!editable && decision === "rejected" && r.decision.reject_reason && (
        <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-amber-700">
          拒绝原因：{r.decision.reject_reason}
        </div>
      )}
    </div>
  )
}

function SourceLine({ r, onLocate }: { r: Result; onLocate: (loc: Location) => void }) {
  const src = r.sources[0]
  if (!src) return null
  const canLocate = !!src.file_id && src.source_page_number != null
  const pageOnly = !src.bbox || src.coordinate_space !== "ocr_input_image_pixels"
  return (
    <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
      <span>
        出处：{src.file_name} · 第 {src.source_page_number} 页
      </span>
      {canLocate && (
        <button
          type="button"
          className="inline-flex items-center gap-0.5 text-blue-600 hover:underline"
          onClick={() =>
            onLocate({
              fileId: src.file_id!,
              pageNumber: src.source_page_number!,
              bbox: src.bbox,
              pageWidth: src.page_width_px,
              pageHeight: src.page_height_px,
              coordinateSpace: src.coordinate_space,
            })
          }
        >
          <LocateFixed className="size-3" /> {pageOnly ? "仅定位到页" : "定位原文"}
        </button>
      )}
    </div>
  )
}
