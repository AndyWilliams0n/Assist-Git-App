import { Fragment, useMemo } from "react"
import { Link } from "react-router-dom"
import { Moon, Sun } from "lucide-react"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/components/ui/breadcrumb.tsx"
import { Button } from "@/shared/components/ui/button.tsx"
import { Separator } from "@/shared/components/ui/separator.tsx"
import { SidebarTrigger } from "@/shared/components/ui/sidebar.tsx"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings.ts"

export function SiteHeader() {
  const breadcrumbs = useDashboardSettingsStore((state) => state.breadcrumbs)
  const theme = useDashboardSettingsStore((state) => state.theme)
  const toggleTheme = useDashboardSettingsStore((state) => state.toggleTheme)
  const resolvedBreadcrumbs = useMemo(
    () => (breadcrumbs.length > 0 ? breadcrumbs : [{ label: "Workspace", href: "/workspace" }]),
    [breadcrumbs]
  )

  return (
    <header className="bg-background/80 sticky top-0 z-50 flex h-16 shrink-0 items-center gap-2 border-b backdrop-blur-md transition-[height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-12">
      <div className="flex w-full items-center gap-2 px-4">
        <SidebarTrigger className="-ml-1" />

        <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />

        <Breadcrumb className="hidden sm:block mr-4">
          <BreadcrumbList>
            {resolvedBreadcrumbs.map((breadcrumb, index) => {
              const isLast = index === resolvedBreadcrumbs.length - 1
              const href = breadcrumb.href ?? "#"

              return (
                <Fragment key={`${breadcrumb.label}-${index}`}>
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage>{breadcrumb.label}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink asChild>
                        <Link to={href}>{breadcrumb.label}</Link>
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                  {!isLast ? <BreadcrumbSeparator /> : null}
                </Fragment>
              )
            })}
          </BreadcrumbList>
        </Breadcrumb>

        <div className="w-full sm:ml-auto sm:w-auto"></div>

        <Button
          className="ml-2"
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </div>
    </header>
  )
}
