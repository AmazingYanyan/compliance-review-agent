import { createFileRoute, Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Fragment, useCallback, useMemo, useRef, useState } from "react"
import {
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  flexRender,
  stockFeatures,
  tableFeatures,
  useTable,
  type ColumnFiltersState,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table"
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  ChevronsUpDown,
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
} from "lucide-react"

import {
  deleteFile,
  deleteTask,
  listFiles,
  listTasks,
  setFileClassification,
  uploadFile,
} from "@/api/endpoints"
import {
  CUSTOMER_ROLE_LABEL,
  OCR_STATUS_LABEL,
  TASK_STATE_LABEL,
  type Task,
  type TaskFile,
} from "@/api/types"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export const Route = createFileRoute("/_layout/tasks/")({
  component: Tasks,
  head: () => ({ meta: [{ title: "我的任务 - 信贷资料核对" }] }),
  validateSearch: (search: Record<string, unknown>) => ({
    expand: (search.expand as string) ?? undefined,
  }),
})

// 模块级 features：stock 全量 feature + 排序/过滤/分页三个 row model 工厂
const features = tableFeatures({
  ...stockFeatures,
  sortedRowModel: createSortedRowModel(),
  filteredRowModel: createFilteredRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
})

type Features = typeof features
const columnHelper = createColumnHelper<Features, Task>()

const EMPTY_TASKS: Task[] = []

// 行内操作列固定三槽位：上传材料 / 进入或查看 / 更多。
// 槽位宽度固定，让待核对的「继续核对」与已完成的「查看结果」横向对齐；
// 已完成行没有上传动作时，槽位 1 仍保留布局空间，不把入口按钮推向右边。
const ACTION_SLOT_CLASS = "flex h-8 w-[88px] shrink-0 items-center justify-end"
const ACTION_MORE_SLOT_CLASS = "flex h-8 w-8 shrink-0 items-center justify-end"
// 行内主入口统一浅青底 + 深青绿文字，与页级实心深青绿主操作区分。
// 深青绿 #0B4F52 与原 --primary 同色系，仅降低明度：普通字号文字对比度 ≥ 4.5:1。
const ACTION_PRIMARY_CLASS =
  "bg-primary/10 text-[#0B4F52] hover:bg-primary/20 hover:text-[#0B4F52]"
// 页级主操作底色同步加深，保持「页级实心 > 行内浅青 > 上传中性描边」的层级。
const PAGE_PRIMARY_CLASS = "bg-[#0B4F52] hover:bg-[#093E40]"

const STATE_DOT: Record<string, string> = {
  DRAFT: "bg-gray-400",
  PROCESSING: "bg-blue-500",
  REVIEWING: "bg-amber-500",
  FAILED: "bg-red-500",
  COMPLETED: "bg-green-500",
}

// 状态文字统一用 700 档深一档色：12px 普通文字对白底对比度 ≥ 4.5:1，
// 仍保持「颜色圆点 + 文字」的表达方式与原有层级。
const STATE_TEXT: Record<string, string> = {
  DRAFT: "text-muted-foreground",
  PROCESSING: "text-blue-700",
  REVIEWING: "text-amber-700",
  FAILED: "text-red-700",
  COMPLETED: "text-green-700",
}

const STATE_OPTIONS = ["DRAFT", "PROCESSING", "REVIEWING", "FAILED", "COMPLETED"]

const MATERIAL_OPTIONS = [
  { value: "", label: "未分类" },
  { value: "business_license", label: "营业执照" },
  { value: "articles_of_association", label: "公司章程" },
  { value: "audited_financials", label: "已审计财报" },
]

function StateBadge({ state }: { state: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={`size-1.5 rounded-full ${STATE_DOT[state] ?? "bg-gray-400"}`} />
      <span className={STATE_TEXT[state] ?? "text-muted-foreground"}>
        {TASK_STATE_LABEL[state] ?? state}
      </span>
    </span>
  )
}

function progressText(t: Task): string {
  if (t.file_count === 0) return "未上传材料"
  const done = t.ocr_done_count
  const total = t.file_count
  if (t.ocr_processing_count > 0) return `识别中 ${done}/${total}`
  if (t.ocr_failed_count > 0) return `已识别 ${done}/${total} · ${t.ocr_failed_count} 份失败`
  return `已识别 ${done}/${total}`
}

function Tasks() {
  const queryClient = useQueryClient()
  const { expand } = Route.useSearch()
  const { data: tasks, isLoading } = useQuery<Task[]>({
    queryKey: ["tasks"],
    queryFn: listTasks,
    refetchInterval: 5000,
  })

  const [expanded, setExpanded] = useState<string | null>(expand ?? null)
  const [deleteTarget, setDeleteTarget] = useState<Task | null>(null)

  // 搜索 + 状态筛选 → columnFilters（完全由外部派生）
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<string>("all")
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }])
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 20 })

  const columnFilters = useMemo<ColumnFiltersState>(() => {
    const f: ColumnFiltersState = []
    if (search.trim()) f.push({ id: "name", value: search.trim() })
    if (statusFilter !== "all") f.push({ id: "state", value: statusFilter })
    return f
  }, [search, statusFilter])

  const onDelete = useCallback((t: Task) => setDeleteTarget(t), [])

  const columns = useMemo(
    () =>
      columnHelper.columns([
      columnHelper.accessor("name", {
        id: "name",
        header: "任务名称",
        filterFn: (row, _columnId, value) =>
          row.original.name.toLowerCase().includes(String(value).toLowerCase()),
        cell: ({ row }) => {
          const task = row.original
          const isOpen = expanded === task.id
          return (
            <button
              type="button"
              className="flex items-center gap-1 text-left font-medium hover:underline"
              onClick={() => setExpanded(isOpen ? null : task.id)}
            >
              {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
              {task.name}
            </button>
          )
        },
      }),
      columnHelper.accessor("customer_role", {
        id: "customer_role",
        header: "客户类型",
        cell: ({ getValue }) => CUSTOMER_ROLE_LABEL[getValue()] ?? getValue(),
      }),
      columnHelper.accessor("state", {
        id: "state",
        header: "状态",
        filterFn: (row, _columnId, value) => row.original.state === value,
        cell: ({ getValue }) => <StateBadge state={getValue()} />,
      }),
      columnHelper.display({
        id: "progress",
        header: "识别进度",
        cell: ({ row }) => (
          <span className="text-muted-foreground">{progressText(row.original)}</span>
        ),
      }),
      columnHelper.accessor("updated_at", {
        id: "updated_at",
        header: ({ column }) => (
          <button
            type="button"
            className="inline-flex items-center gap-1 hover:text-foreground"
            onClick={column.getToggleSortingHandler()}
          >
            更新时间
            {column.getIsSorted() === "asc" ? (
              <ChevronUp className="size-3.5" />
            ) : column.getIsSorted() === "desc" ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronsUpDown className="size-3.5 opacity-50" />
            )}
          </button>
        ),
        sortFn: (rowA, rowB, columnId) => {
          const a = new Date(rowA.getValue(columnId) as string).getTime()
          const b = new Date(rowB.getValue(columnId) as string).getTime()
          return a - b
        },
        cell: ({ getValue }) => (
          <span className="text-muted-foreground">
            {new Date(getValue()).toLocaleString("zh-CN")}
          </span>
        ),
      }),
      columnHelper.display({
        id: "actions",
        header: () => <div className="text-right">操作</div>,
        cell: ({ row }) => {
          const task = row.original
          const isCompleted = task.state === "COMPLETED"
          return (
            <div className="flex items-center justify-end gap-1">
              {/* 槽位 1：上传材料。待核对行未展开时同样可用；已完成行留空占位。 */}
              <div className={ACTION_SLOT_CLASS}>
                {!isCompleted && (
                  <UploadTaskButton taskId={task.id} onUploaded={() => setExpanded(task.id)} />
                )}
              </div>
              {/* 槽位 2：进入或查看。两种状态共用一个入口位置，指向同一只读/核对页。 */}
              <div className={ACTION_SLOT_CLASS}>
                <Button asChild size="sm" variant="ghost" className={ACTION_PRIMARY_CLASS}>
                  <Link to="/tasks/$taskId/review" params={{ taskId: task.id }}>
                    {isCompleted ? "查看结果" : "继续核对"}
                  </Link>
                </Button>
              </div>
              {/* 槽位 3：更多。保留省略号与可访问名称。 */}
              <div className={ACTION_MORE_SLOT_CLASS}>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="text-muted-foreground"
                      aria-label="更多操作"
                      title="更多操作"
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {/* 已完成任务遵循只读规则：不提供任何写操作，仅保留槽位与可访问名称。 */}
                    {isCompleted ? (
                      <DropdownMenuItem disabled>已完成任务不可修改</DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem onClick={() => onDelete(task)}>删除任务</DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          )
        },
      }),
      ]),
    [expanded, onDelete],
  )

  const table = useTable({
    features,
    data: tasks ?? EMPTY_TASKS,
    columns,
    getRowId: (row) => row.id,
    enableSortingRemoval: false,
    state: {
      sorting,
      columnFilters,
      pagination,
    },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
  })

  const removeTask = useMutation({
    mutationFn: (id: string) => deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      setDeleteTarget(null)
    },
  })

  const pageCount = table.getPageCount()
  const rowCount = table.getRowModel().rows.length
  const hasTasks = !!tasks && tasks.length > 0

  const totalFiltered = table.getFilteredRowModel().rows.length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">我的任务</h1>
          <p className="mt-1 text-muted-foreground">
            展开任务可查看并确认材料类型、补充上传材料。
          </p>
        </div>
        <Button asChild className={PAGE_PRIMARY_CLASS}>
          <Link to="/">
            <Plus className="size-4" /> 新建核对任务
          </Link>
        </Button>
      </div>

      {/* 搜索 + 状态筛选 */}
      <div className="flex items-center gap-2">
        <div className="relative">
          <Search className="absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPagination((prev) => ({ ...prev, pageIndex: 0 }))
            }}
            placeholder="搜索任务名称"
            className="w-64 pl-8"
          />
        </div>
        <Select
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v)
            setPagination((prev) => ({ ...prev, pageIndex: 0 }))
          }}
        >
          <SelectTrigger size="sm" className="w-36">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {STATE_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {TASK_STATE_LABEL[s] ?? s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">加载中…</div>
      ) : !hasTasks ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          暂无任务，点击右上角新建核对任务。
        </div>
      ) : rowCount === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          无匹配任务，请调整搜索或筛选条件。
        </div>
      ) : (
        <>
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => {
                const isOpen = expanded === row.original.id
                return (
                  <Fragment key={row.id}>
                    <TableRow className={isOpen ? "border-b-0" : ""}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={columns.length} className="bg-muted/20 px-6 py-3">
                          <TaskFiles
                            taskId={row.original.id}
                            readOnly={row.original.state === "COMPLETED"}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>

          {/* 超过一页才显示分页 */}
          {pageCount > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                共 {totalFiltered} 条 · 第 {pagination.pageIndex + 1}/{pageCount} 页
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!table.getCanPreviousPage()}
                  onClick={() => table.previousPage()}
                >
                  上一页
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!table.getCanNextPage()}
                  onClick={() => table.nextPage()}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除任务</DialogTitle>
            <DialogDescription>
              确定删除「{deleteTarget?.name}」吗？任务及其材料、核对结果将被软删除（数据保留可追溯）。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={removeTask.isPending}
              onClick={() => deleteTarget && removeTask.mutate(deleteTarget.id)}
            >
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function UploadTaskButton({
  taskId,
  onUploaded,
}: {
  taskId: string
  onUploaded?: () => void
}) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (file: File) => uploadFile(taskId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files", taskId] })
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      onUploaded?.()
    },
  })

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.jpg,.jpeg,.png"
        className="hidden"
        onChange={(e) => {
          for (const f of Array.from(e.target.files ?? [])) upload.mutate(f)
          e.target.value = ""
        }}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={upload.isPending}
        onClick={() => inputRef.current?.click()}
      >
        上传材料
      </Button>
    </>
  )
}

function TaskFiles({ taskId, readOnly }: { taskId: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const { data: files } = useQuery<TaskFile[]>({
    queryKey: ["files", taskId],
    queryFn: () => listFiles(taskId),
    refetchInterval: 5000,
  })

  const removeFile = useMutation({
    mutationFn: (fileId: string) => deleteFile(taskId, fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files", taskId] })
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
    },
  })

  const classify = useMutation({
    mutationFn: ({ fileId, type }: { fileId: string; type: string | null }) =>
      setFileClassification(taskId, fileId, type),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["files", taskId] }),
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          材料文件
          {readOnly && (
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">· 只读</span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">
          {files ? `${files.length} 份文件` : ""}
        </span>
      </div>

      {!files || files.length === 0 ? (
        <div className="rounded-md border border-dashed px-3 py-6 text-center text-xs text-muted-foreground">
          {readOnly ? "暂无文件（任务已完成，只读）" : "暂无文件，点击上方「上传材料」补充。"}
        </div>
      ) : (
        <div className="space-y-1.5">
          {files.map((f) => (
            <div key={f.id} className="flex items-center gap-3 rounded-md border bg-background px-3 py-2">
              <span className="flex-1 truncate text-sm">{f.original_name}</span>
              <span
                className={`shrink-0 rounded px-2 py-0.5 text-xs ${
                  f.ocr_status === "done"
                    ? "bg-green-100 text-green-700"
                    : f.ocr_status === "failed"
                      ? "bg-red-100 text-red-700"
                      : f.ocr_status === "processing"
                        ? "bg-blue-100 text-blue-700"
                        : "bg-muted text-muted-foreground"
                }`}
              >
                {f.ocr_status ? OCR_STATUS_LABEL[f.ocr_status] ?? f.ocr_status : "待识别"}
              </span>
              <Select
                value={f.material_type ?? ""}
                onValueChange={(v) => classify.mutate({ fileId: f.id, type: v || null })}
                disabled={readOnly}
              >
                <SelectTrigger size="sm" className="w-28">
                  <SelectValue placeholder="类型" />
                </SelectTrigger>
                <SelectContent>
                  {MATERIAL_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-muted-foreground"
                onClick={() => removeFile.mutate(f.id)}
                disabled={readOnly}
                title="删除文件"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
