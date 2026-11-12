import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { useState } from "react"

import { createTask, getCapabilities, uploadFile } from "@/api/endpoints"
import type { Capabilities } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useQuery } from "@tanstack/react-query"

export const Route = createFileRoute("/_layout/")({
  component: Home,
  head: () => ({ meta: [{ title: "首页 - 信贷资料核对" }] }),
})

function errMsg(e: unknown, fallback: string): string {
  if (e instanceof AxiosError) {
    const detail = e.response?.data?.detail
    if (detail && typeof detail === "object" && "message" in detail) {
      const msg = (detail as { message?: unknown }).message
      if (typeof msg === "string" && msg) return msg
    }
    if (e.code === "ERR_NETWORK") return "无法连接服务器，请确认服务已启动"
  }
  return fallback
}

function Home() {
  const navigate = useNavigate()
  const [files, setFiles] = useState<File[]>([])
  const [role, setRole] = useState("borrower")
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState("")

  const { data: caps } = useQuery<Capabilities>({
    queryKey: ["capabilities"],
    queryFn: getCapabilities,
  })

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? [])
    setFiles((prev) => [...prev, ...picked])
    e.target.value = ""
  }

  const removeFile = (i: number) => {
    setFiles((prev) => prev.filter((_, idx) => idx !== i))
  }

  const start = async () => {
    if (files.length === 0) {
      setError("请先选择至少一份文件")
      return
    }
    setStarting(true)
    setError("")
    let task
    try {
      task = await createTask(role)
    } catch (e) {
      setError(errMsg(e, "创建任务失败，请重试"))
      setStarting(false)
      return
    }
    try {
      for (const f of files) {
        await uploadFile(task.id, f)
      }
    } catch (e) {
      setError(errMsg(e, "上传文件失败，请重试"))
      setStarting(false)
      return
    }
    navigate({ to: "/tasks/$taskId/review", params: { taskId: task.id } })
    setStarting(false)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">开始资料核对</h1>
        <p className="mt-1 text-muted-foreground">上传材料，选择法人客户类型，随后进入核对工作台。</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="text-sm font-medium">上传本次核对材料</div>
            <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted-foreground/30 p-10 text-center transition hover:border-primary/50">
              <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" className="hidden" onChange={onPick} />
              <span className="text-2xl text-muted-foreground">＋</span>
              <span className="mt-2">点击选择文件，或将文件拖到这里</span>
              <span className="mt-1 text-xs text-muted-foreground">支持 PDF、JPG、PNG，可批量上传</span>
            </label>
            {files.length > 0 && (
              <div className="space-y-2">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                    <span className="truncate">{f.name}</span>
                    <button type="button" className="text-muted-foreground hover:text-red-600" onClick={() => removeFile(i)}>
                      移除
                    </button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="text-sm font-medium">法人客户类型</div>
            <p className="text-xs text-muted-foreground">单选，不同类型使用对应检查清单</p>
            <div className="space-y-2">
              {(caps?.roles ?? []).map((r) => (
                <button
                  key={r.code}
                  type="button"
                  disabled={!r.enabled}
                  onClick={() => setRole(r.code)}
                  className={`flex w-full items-center justify-between rounded-md border px-3 py-2.5 text-left text-sm transition ${
                    !r.enabled
                      ? "cursor-not-allowed border-muted bg-muted/40 text-muted-foreground"
                      : role === r.code
                        ? "border-primary bg-primary/5 text-primary"
                        : "border-border hover:border-primary/50"
                  }`}
                >
                  <span>{r.label}</span>
                  {!r.enabled && <span className="text-xs">{r.disabled_reason}</span>}
                </button>
              ))}
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button className="w-full" disabled={starting} onClick={start}>
              {starting ? "正在创建…" : "开始核对"}
            </Button>
            <p className="text-xs text-muted-foreground">选定类型和文件后，直接进入核对工作台。</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
