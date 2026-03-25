import type { DragEvent } from "react"

import type { ColumnDef, ColumnId, DragPayload, PipelineKanbanItem } from "@/features/pipelines/components/kanban/types"
import type { PipelineTaskStatus } from "@/features/pipelines/types"

export const COLUMN_DEFS: ColumnDef[] = [
  { id: "backlog", name: "Backlog", tone: "text-slate-500" },
  { id: "current", name: "Task Queue", tone: "text-sky-500" },
  { id: "running", name: "Running", tone: "text-emerald-500" },
  { id: "complete", name: "Complete", tone: "text-emerald-600" },
]

export const statusTone = (status: PipelineTaskStatus | "backlog") => {
  if (status === "running") return { color: "success", variant: "outline" } as const
  if (status === "complete") return { color: "success", variant: "filled" } as const
  if (status === "current") return { color: "info", variant: "outline" } as const
  return { color: "grey", variant: "outline" } as const
}

export const canDropInColumn = (item: PipelineKanbanItem, target: ColumnId) => {
  if (item.kind === "backlog") {
    return !item.tracked && target === "current"
  }

  if (item.status === "current") {
    return target === "current" || target === "backlog"
  }

  return false
}

export const parseDragPayload = (event: DragEvent<HTMLElement>) => {
  try {
    const raw = event.dataTransfer.getData("application/pipeline")
    if (!raw) return null
    const payload = JSON.parse(raw) as DragPayload
    if (!payload?.itemId) return null
    return payload
  } catch {
    return null
  }
}
