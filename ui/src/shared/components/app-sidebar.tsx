import * as React from "react"
import { GitBranch, GitCompare, Layers } from "lucide-react"

import { NavMain } from "@/shared/components/nav-main.tsx"
import { NavUser } from "@/shared/components/nav-user.tsx"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/shared/components/ui/sidebar.tsx"
import { useAuth } from "@/shared/hooks/useAuth.ts"

const primaryNavigation = [
  {
    title: "Workspace",
    url: "/workspace",
    icon: Layers,
  },
  {
    title: "Git",
    url: "/git",
    icon: GitBranch,
  },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { user, logout } = useAuth()
  const siteTitle = import.meta.env.VITE_SITE_TITLE ?? "Assist Git"

  const resolvedUser = React.useMemo(() => {
    const profile = (user ?? {}) as Record<string, unknown>
    const resolvedAvatar =
      (typeof profile.picture === "string" && profile.picture) ||
      (typeof profile.avatar_url === "string" && profile.avatar_url) ||
      (typeof profile.photo === "string" && profile.photo) ||
      (typeof profile.image === "string" && profile.image) ||
      ""

    return {
      name: user?.name || "Authenticated User",
      email: user?.email || "No email available",
      avatar: resolvedAvatar,
    }
  }, [user])

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <a href="#">
                <div className="bg-red-to-pink text-sidebar-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg">
                  <GitCompare size={20} />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">{siteTitle}</span>
                </div>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <NavMain label="Navigation" items={primaryNavigation} />
      </SidebarContent>

      <SidebarFooter>
        <NavUser user={resolvedUser} onLogout={logout} />
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
