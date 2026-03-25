import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/shared/utils/utils.ts"

const chipVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md border font-medium",
  {
    variants: {
      color: {
        success: "",
        error: "",
        info: "",
        warning: "",
        purple: "",
        black: "",
        white: "",
        grey: "",
      },
      variant: {
        filled: "",
        outline: "",
      },
      size: {
        sm: "px-2 py-0.5 text-xs",
        default: "px-2 py-0.5 text-xs",
        lg: "px-3 py-1 text-sm",
      },
    },
    compoundVariants: [
      {
        color: "success",
        variant: "filled",
        className: "border-emerald-500 bg-emerald-500 text-white dark:text-zinc-900",
      },
      {
        color: "success",
        variant: "outline",
        className: "border-emerald-500/50 text-emerald-600 dark:text-emerald-400",
      },
      {
        color: "error",
        variant: "filled",
        className: "border-rose-500 bg-rose-500 text-white dark:text-zinc-900",
      },
      {
        color: "error",
        variant: "outline",
        className: "border-rose-500/50 text-rose-600 dark:text-rose-400",
      },
      {
        color: "info",
        variant: "filled",
        className: "border-sky-500 bg-sky-500 text-white dark:text-zinc-900",
      },
      {
        color: "info",
        variant: "outline",
        className: "border-sky-500/50 text-sky-600 dark:text-sky-400",
      },
      {
        color: "warning",
        variant: "filled",
        className: "border-amber-500 bg-amber-500 text-white dark:text-zinc-900",
      },
      {
        color: "warning",
        variant: "outline",
        className: "border-amber-500/50 text-amber-600 dark:text-amber-400",
      },
      {
        color: "purple",
        variant: "filled",
        className: "border-violet-500 bg-violet-500 text-white dark:text-zinc-900",
      },
      {
        color: "purple",
        variant: "outline",
        className: "border-violet-500/50 text-violet-600 dark:text-violet-400",
      },
      {
        color: "black",
        variant: "filled",
        className: "border-zinc-950 bg-zinc-950 text-zinc-50 dark:border-zinc-50 dark:bg-zinc-50 dark:text-zinc-950",
      },
      {
        color: "black",
        variant: "outline",
        className: "border-zinc-900/40 text-zinc-900 dark:border-zinc-100/40 dark:text-zinc-100",
      },
      {
        color: "white",
        variant: "filled",
        className: "border-zinc-200 bg-zinc-50 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-100 dark:text-zinc-900",
      },
      {
        color: "white",
        variant: "outline",
        className: "border-zinc-300 text-zinc-600 dark:border-zinc-600 dark:text-zinc-300",
      },
      {
        color: "grey",
        variant: "filled",
        className: "border-zinc-500 bg-zinc-500 text-zinc-50 dark:text-zinc-900",
      },
      {
        color: "grey",
        variant: "outline",
        className: "border-zinc-400/60 text-zinc-500 dark:text-zinc-400",
      },
    ],
    defaultVariants: {
      color: "grey",
      variant: "outline",
      size: "default",
    },
  }
)

type ChipProps = React.ComponentProps<"span"> & VariantProps<typeof chipVariants>

function Chip({ className, color, variant, size, ...props }: ChipProps) {
  return (
    <span
      data-slot="chip"
      data-color={color}
      data-variant={variant}
      data-size={size}
      className={cn(chipVariants({ color, variant, size }), className)}
      {...props}
    />
  )
}

export { Chip }
