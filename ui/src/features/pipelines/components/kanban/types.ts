import type { PipelineBacklogItem, PipelineTask, PipelineTaskStatus } from "@/features/pipelines/types"

export type ColumnId = "backlog" | "current" | "running" | "complete"

export type ColumnDef = { id: ColumnId; name: string; tone: string }

export type PipelineKanbanItem = {
  id: string
  name: string
  column: ColumnId
  kind: "backlog" | "task"
  tracked: boolean
  status: PipelineTaskStatus | "backlog"
  backlog?: PipelineBacklogItem
  task?: PipelineTask
}

export type DragPayload = {
  itemId: string
}
