import { createFileRoute, Outlet } from "@tanstack/react-router"

// /tasks 的布局路由：仅作为子路由（列表 / 核对工作台 / 材料管理）的容器，
// 不渲染任何自身内容，子路由通过 <Outlet /> 渲染。
export const Route = createFileRoute("/_layout/tasks")({
  component: () => <Outlet />,
})
