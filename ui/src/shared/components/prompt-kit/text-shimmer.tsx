"use client"

import { cn } from "@/shared/utils/utils.ts"

export type TextShimmerProps = {
  as?: string
  duration?: number
  spread?: number
  active?: boolean
  children: React.ReactNode
} & React.HTMLAttributes<HTMLElement>

export function TextShimmer({
  as = "span",
  className,
  duration = 20,
  spread = 20,
  active = true,
  children,
  ...props
}: TextShimmerProps) {
  const dynamicSpread = Math.min(Math.max(spread, 5), 45)
  const Component = as as React.ElementType

  return (
    <Component
      className={cn(
        "font-medium",
        active
          ? "bg-size-[200%_auto] bg-clip-text text-transparent animate-[shimmer_4s_infinite_linear]"
          : "text-foreground",
        className
      )}
      style={{
        backgroundImage: active
          ? `linear-gradient(to right, var(--muted-foreground) ${50 - dynamicSpread}%, var(--foreground) 50%, var(--muted-foreground) ${50 + dynamicSpread}%)`
          : undefined,
        animationDuration: active ? `${duration}s` : undefined,
      }}
      {...props}
    >
      {children}
    </Component>
  )
}
