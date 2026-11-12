import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { me } from "@/api/endpoints"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    try {
      const data = await me()
      return { currentUser: data.user }
    } catch {
      throw redirect({ to: "/login" })
    }
  },
})

function Layout() {
  const { currentUser } = Route.useRouteContext()
  return (
    <SidebarProvider>
      <AppSidebar user={currentUser} />
      <SidebarInset>
        <main className="flex min-h-0 flex-1 flex-col">
          <div className="mx-auto flex min-h-0 w-full max-w-[1400px] flex-1 flex-col overflow-y-auto p-6 md:p-8">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
