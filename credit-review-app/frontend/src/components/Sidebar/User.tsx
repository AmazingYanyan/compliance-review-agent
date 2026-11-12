import { useNavigate } from "@tanstack/react-router"
import { LogOut } from "lucide-react"

import { logout } from "@/api/endpoints"
import type { UserPublic } from "@/api/types"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export function User({ user }: { user: UserPublic }) {
  const navigate = useNavigate()
  const { isMobile, setOpenMobile } = useSidebar()

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      if (isMobile) setOpenMobile(false)
      navigate({ to: "/login" })
    }
  }

  const initial = (user?.username ?? "U").slice(0, 1).toUpperCase()

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg">
              <Avatar className="size-8">
                <AvatarFallback className="bg-primary text-primary-foreground">{initial}</AvatarFallback>
              </Avatar>
              <div className="flex flex-col items-start">
                <span className="text-sm font-medium">{user?.username}</span>
                <span className="text-xs text-muted-foreground">业务人员</span>
              </div>
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" sideOffset={4}>
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col">
                <span className="text-sm font-medium">{user?.username}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
