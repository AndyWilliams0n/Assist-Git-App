import type { PropsWithChildren } from "react"

import { cn } from "@/shared/utils/utils.ts"

type SiteSubheaderProps = PropsWithChildren<{
  className?: string
}>

export function SiteSubheader({ children, className }: SiteSubheaderProps) {
  return (
    <div
      className={cn(
        "bg-background/80 flex h-16 shrink-0 items-center gap-2 border-b backdrop-blur-md",
        className
      )}
    >
      <div className="flex w-full items-center gap-2 px-4">{children}</div>
    </div>
  )
}
