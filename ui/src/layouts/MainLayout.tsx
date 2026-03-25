import { Outlet } from "react-router-dom"

import { AppSidebar } from "../shared/components/app-sidebar.tsx"
import { SiteHeader } from "../shared/components/site-header.tsx"
import { SidebarInset, SidebarProvider } from "@/shared/components/ui/sidebar"

export default function MainLayout() {
  return (
    <SidebarProvider>
      <AppSidebar collapsible="icon" />

      <SidebarInset className="h-svh overflow-hidden">
        <SiteHeader />

        <div className="flex flex-1 min-h-0 flex-col -mt-16 pt-16 transition-[margin,padding] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:-mt-12 group-has-data-[collapsible=icon]/sidebar-wrapper:pt-12">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
