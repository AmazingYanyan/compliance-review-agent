import axios from "axios"

// 同域 Cookie 认证：不手动携带 token，浏览器自动带 HttpOnly 会话 Cookie。
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  withCredentials: true,
})

// 写请求自动附带 CSRF token（从 /auth/me 获取后缓存）。
let _csrf: string | null = null

export function setCsrf(token: string | null) {
  _csrf = token
}

export function getCsrf() {
  return _csrf
}

api.interceptors.request.use((config) => {
  const method = (config.method ?? "get").toLowerCase()
  if (method !== "get" && _csrf) {
    config.headers.set("X-CSRF-Token", _csrf)
  }
  return config
})
