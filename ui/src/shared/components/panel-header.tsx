import * as React from "react"

import { cn } from "@/shared/utils/utils.ts"

type PanelHeaderProps = {
  icon: React.ReactNode
  title: string
  description?: string
  borderTop?: boolean
  borderRight?: boolean
  borderBottom?: boolean
  borderLeft?: boolean
  className?: string
  children?: React.ReactNode
}

export function PanelHeader({
  icon,
  title,
  description,
  borderTop = false,
  borderRight = false,
  borderBottom = false,
  borderLeft = false,
  className,
  children,
}: PanelHeaderProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between px-4 py-3",
        borderTop && "border-t",
        borderRight && "border-r",
        borderBottom && "border-b",
        borderLeft && "border-l",
        className
      )}
    >
      <div className="flex items-center gap-2">
        {icon}

        <div>
          <p className="text-sm font-semibold tracking-tight">{title}</p>

          {description ? <p className="text-muted-foreground text-xs">{description}</p> : null}
        </div>
      </div>

      {children ? <div className="shrink-0">{children}</div> : null}
    </div>
  )
}
