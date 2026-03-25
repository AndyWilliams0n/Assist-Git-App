import { Fragment, type DragEvent, useMemo } from "react"
import { Circle } from "lucide-react"

import PipelineKanbanCard from "@/features/pipelines/components/kanban/PipelineKanbanCard"
import { canDropInColumn } from "@/features/pipelines/components/kanban/kanban-utils"
import type { ColumnDef, PipelineKanbanItem } from "@/features/pipelines/components/kanban/types"
import type { PipelineBacklogItem, PipelineTask } from "@/features/pipelines/types"
import { cn } from "@/shared/utils/utils.ts"
import { Chip } from "@/shared/components/chip"

type PipelineKanbanColumnProps = {
  column: ColumnDef
  items: PipelineKanbanItem[]
  isMutating: boolean
  draggingCardId: string | null
  activeDragItem: PipelineKanbanItem | null
  isSortableCurrentDrag: boolean
  isDropTarget: boolean
  currentInsertionBeforeTaskId?: string | null
  onColumnDragOver: (event: DragEvent<HTMLElement>) => void
  onColumnDrop: (event: DragEvent<HTMLElement>) => void
  onCardDragStart: (event: DragEvent<HTMLElement>, item: PipelineKanbanItem) => void
  onCardDragEnd: () => void
  onCurrentInsertionDragOver: (beforeTaskId: string | null) => (event: DragEvent<HTMLElement>) => void
  onCurrentInsertionDrop: (event: DragEvent<HTMLElement>, beforeTaskId: string | null) => void
  onSelectTaskId: (taskId: string | null) => void
  onQueueFromBacklog: (item: PipelineBacklogItem) => Promise<void>
  onMoveTaskToBacklog: (taskId: string) => Promise<void>
  onReenableTask: (taskId: string) => Promise<void>
  onStopRunningTask: (taskId: string) => Promise<void>
  onAdminForceResetTask: (taskId: string) => Promise<void>
  onAdminForceCompleteTask: (taskId: string) => Promise<void>
  onEditTaskDetails: (task: PipelineTask) => void
  onRunAction: (fn: () => Promise<void>) => void
}

export default function PipelineKanbanColumn({
  column,
  items,
  isMutating,
  draggingCardId,
  activeDragItem,
  isSortableCurrentDrag,
  isDropTarget,
  currentInsertionBeforeTaskId,
  onColumnDragOver,
  onColumnDrop,
  onCardDragStart,
  onCardDragEnd,
  onCurrentInsertionDragOver,
  onCurrentInsertionDrop,
  onSelectTaskId,
  onQueueFromBacklog,
  onMoveTaskToBacklog,
  onReenableTask,
  onStopRunningTask,
  onAdminForceResetTask,
  onAdminForceCompleteTask,
  onEditTaskDetails,
  onRunAction,
}: PipelineKanbanColumnProps) {
  const isCurrentColumn = column.id === "current"
  const canAcceptActiveDrag = activeDragItem ? canDropInColumn(activeDragItem, column.id) : false
  const showDropBanner = !isCurrentColumn && isDropTarget && canAcceptActiveDrag
  const showCurrentSortSlots = isCurrentColumn && isSortableCurrentDrag
  const currentCount = isCurrentColumn ? items.length : 0
  const dependencyOrderWarningByTaskId = useMemo(() => {
    const warnings = new Map<string, string>()
    if (!isCurrentColumn) return warnings

    const currentTasks: PipelineTask[] = items
      .filter((item) => item.kind === "task" && Boolean(item.task))
      .map((item) => item.task as PipelineTask)
    const orderByTaskId = new Map<string, number>()
    const taskKeyById = new Map<string, string>()

    currentTasks.forEach((task, index) => {
      orderByTaskId.set(task.id, index)
      taskKeyById.set(task.id, String(task.jira_key || "").trim() || task.id)
    })

    for (const task of currentTasks) {
      const taskOrder = orderByTaskId.get(task.id)
      if (taskOrder == null) continue

      const dependencyIds = Array.from(
        new Set(
          (task.dependencies || [])
            .map((dependency) => String(dependency.depends_on_task_id || "").trim())
            .filter(Boolean)
        )
      )
      for (const dependencyId of dependencyIds) {
        const dependencyOrder = orderByTaskId.get(dependencyId)
        if (dependencyOrder == null) continue
        if (taskOrder < dependencyOrder) {
          warnings.set(task.id, taskKeyById.get(dependencyId) || dependencyId)
          break
        }
      }
      if (warnings.has(task.id)) continue

      const normalizedReason = `${String(task.dependency_block_reason || "")} ${String(task.failure_reason || "")}`
        .trim()
        .toUpperCase()
      if (!normalizedReason) continue

      for (const [candidateTaskId, candidateTaskKey] of taskKeyById.entries()) {
        if (candidateTaskId === task.id) continue
        if (!candidateTaskKey) continue
        if (!normalizedReason.includes(candidateTaskKey.toUpperCase())) continue

        const candidateOrder = orderByTaskId.get(candidateTaskId)
        if (candidateOrder == null) continue
        if (taskOrder < candidateOrder) {
          warnings.set(task.id, candidateTaskKey)
          break
        }
      }
    }

    return warnings
  }, [isCurrentColumn, items])

  const renderCurrentDropSlot = (beforeTaskId: string | null, displayPosition: number) => {
    if (!showCurrentSortSlots) return null

    const isActive = currentInsertionBeforeTaskId === beforeTaskId
    const isEndSlot = beforeTaskId === null
    const label = isEndSlot
      ? `Drop to place at end (${Math.max(1, displayPosition - 1)})`
      : `Drop to make #${displayPosition}`

    return (
      <div
        aria-hidden="true"
        className={cn(
          "group/drop relative -my-1 flex items-center justify-center rounded-md border border-dashed px-2 duration-150 overflow-hidden",
          "h-3 border-zinc-300/40 bg-zinc-50/30 opacity-0",
          showCurrentSortSlots && "opacity-70",
          isActive && "h-12 border-sky-400 bg-sky-100/70 opacity-100 shadow-sm",
          !isActive && "hover:h-8 hover:opacity-100"
        )}
        onDragOver={onCurrentInsertionDragOver(beforeTaskId)}
        onDrop={(event) => onCurrentInsertionDrop(event, beforeTaskId)}
      >
        <div
          className={cn(
            "pointer-events-none absolute inset-x-2 top-1/2 -translate-y-1/2 border-t border-dashed transition-colors",
            isActive ? "border-sky-400" : "border-zinc-400/50"
          )}
        />
        <span
          className={cn(
            "pointer-events-none rounded-full border px-2 py-0.5 text-[11px] font-medium",
            "translate-y-1 opacity-0",
            isActive && "translate-y-0 border-sky-300 bg-white/90 text-sky-700 opacity-100",
            !isActive &&
              "group-hover/drop:translate-y-0 group-hover/drop:border-zinc-300 group-hover/drop:bg-white/90 group-hover/drop:text-zinc-600 group-hover/drop:opacity-100"
          )}
        >
          {label}
        </span>
      </div>
    )
  }

  const dropBannerText =
    column.id === "backlog"
      ? "Drop to return the task to Backlog"
      : "Drop here"

  return (
    <section
      className={cn(
        // "flex flex-1 flex-col h-[calc(100vh-440px)] min-w-0 rounded-xl border bg-card shadow-sm duration-150 overflow-hidden",
        "flex flex-1 flex-col h-[2000px] min-w-0 rounded-xl border bg-card shadow-sm duration-150 overflow-hidden",
        showDropBanner && "border-sky-400 bg-sky-50/35 shadow-[0_0_0_1px_rgba(14,165,233,0.15)]"
      )}
      onDragOver={onColumnDragOver}
      onDrop={onColumnDrop}
    >
      <header className="border-b p-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Circle className={cn("size-3 fill-current stroke-current", column.tone)} strokeWidth={1.5} />
              <span className="font-semibold text-sm">{column.name}</span>
              {isCurrentColumn ? (
                <Chip color="info" variant="outline" size="sm">
                  Top → Bottom
                </Chip>
              ) : null}
            </div>
            {isCurrentColumn ? (
              <p className="text-muted-foreground mt-1 text-xs">
                The top ticket executes first. Drag queue cards to reorder pipeline execution.
              </p>
            ) : column.id === "backlog" ? (
              <p className="text-muted-foreground mt-1 text-xs">
                Drag untracked backlog tickets into Task Queue to queue them.
              </p>
            ) : null}
          </div>
          <Chip color="grey" variant="outline">
            {items.length}
          </Chip>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {showDropBanner ? (
          <div
            aria-hidden="true"
            className={cn(
              "pointer-events-none sticky top-0 z-10 rounded-md border border-dashed border-sky-300 bg-white/85 px-2 py-1 text-[11px] font-medium text-sky-700 shadow-sm backdrop-blur-sm",
              isDropTarget && "animate-pulse"
            )}
          >
            {dropBannerText}
          </div>
        ) : null}

        {showCurrentSortSlots && currentCount === 0 ? renderCurrentDropSlot(null, 1) : null}

        {items.map((item, index) => {
          const queuePosition = isCurrentColumn && item.kind === "task" ? index + 1 : undefined
          const beforeTaskId = item.kind === "task" ? item.task?.id ?? null : null

          return (
            <Fragment key={item.id}>
              {showCurrentSortSlots ? renderCurrentDropSlot(beforeTaskId, index + 1) : null}
              <PipelineKanbanCard
                item={item}
                columnId={column.id}
                isMutating={isMutating}
                isDragging={draggingCardId === item.id}
                isDropBeforeTarget={
                  isCurrentColumn &&
                  item.kind === "task" &&
                  currentInsertionBeforeTaskId != null &&
                  currentInsertionBeforeTaskId === item.task?.id
                }
                queuePosition={queuePosition}
                queueTotal={isCurrentColumn ? currentCount : undefined}
                dependencyOrderWarningTaskKey={
                  isCurrentColumn && item.kind === "task" && item.task
                    ? dependencyOrderWarningByTaskId.get(item.task.id)
                    : undefined
                }
                onSelectTaskId={onSelectTaskId}
                onCardDragStart={onCardDragStart}
                onCardDragEnd={onCardDragEnd}
                onCurrentInsertionDragOver={(event, beforeId) => onCurrentInsertionDragOver(beforeId)(event)}
                onCurrentInsertionDrop={onCurrentInsertionDrop}
                onQueueFromBacklog={onQueueFromBacklog}
                onMoveTaskToBacklog={onMoveTaskToBacklog}
                onReenableTask={onReenableTask}
                onStopRunningTask={onStopRunningTask}
                onAdminForceResetTask={onAdminForceResetTask}
                onAdminForceCompleteTask={onAdminForceCompleteTask}
                onEditTaskDetails={onEditTaskDetails}
                onRunAction={onRunAction}
              />
            </Fragment>
          )
        })}

        {showCurrentSortSlots && currentCount > 0 ? renderCurrentDropSlot(null, currentCount + 1) : null}
      </div>
    </section>
  )
}
