"use client"

import { ChevronRight, type LucideIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { Chip } from "@/shared/components/chip.tsx"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/shared/components/ui/collapsible.tsx"
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/shared/components/ui/sidebar.tsx"

export function NavMain({
  label,
  items,
}: {
  label?: string
  items: {
    title: string
    url: string
    icon: LucideIcon
    badge?: string
    badgeColor?: React.ComponentProps<typeof Chip>["color"]
    isActive?: boolean
    onClick?: () => void
    items?: {
      title: string
      url: string
      onClick?: () => void
    }[]
  }[]
}) {
  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label ?? "Platform"}</SidebarGroupLabel>
      <SidebarMenu>
        {items.map((item) => (
          <Collapsible key={item.title} asChild defaultOpen={item.isActive}>
            <SidebarMenuItem>
              <SidebarMenuButton asChild tooltip={item.title}>
                <Link to={item.url} onClick={item.onClick}>
                  <item.icon />
                  <span>{item.title}</span>
                  {item.badge ? (
                    <Chip className="ml-auto tracking-wide" color={item.badgeColor ?? "error"} variant="outline" size="sm">
                      {item.badge}
                    </Chip>
                  ) : null}
                </Link>
              </SidebarMenuButton>
              {item.items?.length ? (
                <>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuAction className="data-[state=open]:rotate-90">
                      <ChevronRight />
                      <span className="sr-only">Toggle</span>
                    </SidebarMenuAction>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {item.items?.map((subItem) => (
                        <SidebarMenuSubItem key={subItem.title}>
                          <SidebarMenuSubButton asChild>
                            <Link to={subItem.url} onClick={subItem.onClick}>
                              <span>{subItem.title}</span>
                            </Link>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </>
              ) : null}
            </SidebarMenuItem>
          </Collapsible>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}
