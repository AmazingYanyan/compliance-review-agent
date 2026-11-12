import { ClipboardList, Home, PanelLeft, SearchCheck } from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { listTasks } from "@/api/endpoints"
import type { UserPublic } from "@/api/types"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { Main, type Item } from "./Main"
import { User } from "./User"

export function AppSidebar({ user }: { user: UserPublic }) {
  const { data: tasks } = useQuery({ queryKey: ["tasks"], queryFn: listTasks })
  const { toggleSidebar } = useSidebar()
  const latest = tasks?.[0]

  const items: Item[] = [
    { icon: Home, title: "首页", to: "/" },
    { icon: ClipboardList, title: "我的任务", to: "/tasks" },
  ]
  if (latest) {
    items.push({
      icon: SearchCheck,
      title: "资料核对",
      to: "/tasks/$taskId/review",
      params: { taskId: latest.id },
      activeWhen: "/review",
    })
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="收起侧栏" onClick={toggleSidebar}>
              <PanelLeft />
              <span>收起侧栏</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <User user={user} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
