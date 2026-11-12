import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { useState } from "react"

import { login } from "@/api/endpoints"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PasswordInput } from "@/components/ui/password-input"

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    // 已登录则直接回首页
    try {
      await import("@/api/endpoints").then((m) => m.me())
      throw redirect({ to: "/" })
    } catch (e) {
      if (e && typeof e === "object" && "to" in (e as object)) throw e
    }
  },
  head: () => ({ meta: [{ title: "登录 - 信贷资料核对" }] }),
})

function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) {
      setError("请输入用户名和密码")
      return
    }
    setLoading(true)
    setError("")
    try {
      await login(username, password)
      navigate({ to: "/" })
    } catch {
      setError("用户名或密码错误")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm rounded-xl border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-md bg-primary text-lg font-bold text-primary-foreground">
            信
          </div>
          <span className="text-lg font-semibold">信贷资料核对</span>
        </div>
        <h1 className="mb-6 text-xl font-bold">欢迎登录</h1>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium">用户名</label>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">密码</label>
            <PasswordInput
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "登录中…" : "登录"}
          </Button>
        </form>
      </div>
    </div>
  )
}
