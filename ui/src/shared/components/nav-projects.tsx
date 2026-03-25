import {
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu.tsx"
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/shared/components/ui/sidebar.tsx"

export interface NavProjectMenuItem {
  type?: "item" | "separator"
  label?: string
  icon?: LucideIcon
  onClick?: () => void
  destructive?: boolean
  items?: NavProjectMenuItem[]
}

function renderProjectMenuItems(menuItems: NavProjectMenuItem[]) {
  return menuItems.map((menuItem, idx) => {
    if (menuItem.type === "separator") {
      return <DropdownMenuSeparator key={`separator-${idx}`} />
    }

    if (menuItem.items?.length) {
      return (
        <DropdownMenuSub key={`${menuItem.label ?? "submenu"}-${idx}`}>
          <DropdownMenuSubTrigger
            className={menuItem.destructive ? "text-destructive focus:text-destructive" : ""}
          >
            {menuItem.icon ? (
              <menuItem.icon className="text-muted-foreground" />
            ) : null}
            <span>{menuItem.label ?? "Submenu"}</span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-48">
            {renderProjectMenuItems(menuItem.items)}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      )
    }

    return (
      <DropdownMenuItem
        key={`${menuItem.label ?? "menu-item"}-${idx}`}
        onClick={menuItem.onClick}
        className={menuItem.destructive ? "text-destructive focus:text-destructive" : ""}
      >
        {menuItem.icon ? <menuItem.icon className="text-muted-foreground" /> : null}
        <span>{menuItem.label ?? "Action"}</span>
      </DropdownMenuItem>
    )
  })
}

export function NavProjects({
  label,
  projects,
  defaultProjectMenuItems,
  showMoreButton = false,
  moreButtonLabel = "More",
  moreButtonIcon: MoreButtonIcon = MoreHorizontal,
  moreButtonOnClick,
  moreButtonMenuItems,
}: {
  label?: string
  projects: {
    name: string
    url: string
    icon: LucideIcon
    onClick?: () => void
    menuItems?: NavProjectMenuItem[]
  }[]
  defaultProjectMenuItems?: NavProjectMenuItem[]
  showMoreButton?: boolean
  moreButtonLabel?: string
  moreButtonIcon?: LucideIcon
  moreButtonOnClick?: () => void
  moreButtonMenuItems?: NavProjectMenuItem[]
}) {
  const { isMobile } = useSidebar()
  const shouldRenderMoreButton = showMoreButton
  const hasMoreButtonMenuItems = (moreButtonMenuItems?.length ?? 0) > 0

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label ?? "Projects"}</SidebarGroupLabel>
      <SidebarMenu>
        {projects.map((item) => {
          const resolvedMenuItems = item.menuItems ?? defaultProjectMenuItems ?? []
          const hasResolvedMenuItems = resolvedMenuItems.length > 0

          return (
            <SidebarMenuItem key={item.name}>
              <SidebarMenuButton asChild>
                {item.onClick || item.url === "#" ? (
                  <a
                    href={item.url}
                    onClick={(event) => {
                      if (!item.onClick) return
                      event.preventDefault()
                      item.onClick()
                    }}
                  >
                    <item.icon />
                    <span>{item.name}</span>
                  </a>
                ) : (
                  <Link to={item.url}>
                    <item.icon />
                    <span>{item.name}</span>
                  </Link>
                )}
              </SidebarMenuButton>

              {hasResolvedMenuItems ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <SidebarMenuAction showOnHover>
                      <MoreHorizontal />
                      <span className="sr-only">More</span>
                    </SidebarMenuAction>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    className="w-48"
                    side={isMobile ? "bottom" : "right"}
                    align={isMobile ? "end" : "start"}
                  >
                    {renderProjectMenuItems(resolvedMenuItems)}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </SidebarMenuItem>
          )
        })}

        {shouldRenderMoreButton ? (
          <SidebarMenuItem>
            {hasMoreButtonMenuItems ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuButton>
                    <MoreButtonIcon />
                    <span>{moreButtonLabel}</span>
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  className="w-48"
                  side={isMobile ? "bottom" : "right"}
                  align={isMobile ? "end" : "start"}
                >
                  {renderProjectMenuItems(moreButtonMenuItems ?? [])}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <SidebarMenuButton onClick={moreButtonOnClick}>
                <MoreButtonIcon />
                <span>{moreButtonLabel}</span>
              </SidebarMenuButton>
            )}
          </SidebarMenuItem>
        ) : null}
      </SidebarMenu>
    </SidebarGroup>
  )
}
