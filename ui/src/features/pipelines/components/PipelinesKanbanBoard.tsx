import { useEffect, useMemo, useState, type DragEvent } from 'react'

import PipelineKanbanColumn from '@/features/pipelines/components/kanban/PipelineKanbanColumn'
import { COLUMN_DEFS, canDropInColumn, parseDragPayload } from '@/features/pipelines/components/kanban/kanban-utils'
import type { ColumnId, PipelineKanbanItem } from '@/features/pipelines/components/kanban/types'
import type { PipelineBacklogItem, PipelineTask } from '@/features/pipelines/types'

type CurrentInsertionTarget = {
  beforeTaskId: string | null
}

type PipelinesKanbanBoardProps = {
  backlog: PipelineBacklogItem[]
  currentTasks: PipelineTask[]
  runningTasks: PipelineTask[]
  completeTasks: PipelineTask[]
  trackedKeys: Set<string>
  isMutating: boolean
  onSelectTaskId: (taskId: string | null) => void
  onQueueFromBacklog: (item: PipelineBacklogItem) => Promise<void>
  onReorderCurrentBefore: (movingTaskId: string, beforeTaskId: string) => Promise<void>
  onReorderCurrentToEnd: (movingTaskId: string) => Promise<void>
  onMoveTaskToBacklog: (taskId: string) => Promise<void>
  onReenableTask: (taskId: string) => Promise<void>
  onStopRunningTask: (taskId: string) => Promise<void>
  onAdminForceResetTask: (taskId: string) => Promise<void>
  onAdminForceCompleteTask: (taskId: string) => Promise<void>
  onEditTaskDetails: (task: PipelineTask) => void
  onActionError: (message: string) => void
}

type BacklogParentRelation = {
  isSubtask: boolean
  parentCandidates: string[]
}

const normalizeBacklogKey = (value: unknown) => String(value || '').trim().toUpperCase()

const parseBacklogDependencyKeys = (value: unknown) => {
  const dependencies: string[] = []
  const seen = new Set<string>()
  const rawItems = Array.isArray(value) ? value : []

  for (const rawItem of rawItems) {
    const key = normalizeBacklogKey(rawItem)

    if (!key || seen.has(key)) continue

    seen.add(key)
    dependencies.push(key)
  }

  return dependencies
}

const parseBacklogSubtaskFlag = (value: unknown) => {
  if (value === true) return true

  const normalizedValue = String(value || '').trim().toLowerCase()

  return normalizedValue === '1' || normalizedValue === 'true'
}

const issueTypeText = (value?: string) => String(value || '').trim().toLowerCase()

const isSubtaskIssueType = (value?: string) => {
  const type = issueTypeText(value)

  return type.includes('sub-task') || type.includes('subtask')
}

const getBacklogParentRelation = (item: PipelineBacklogItem): BacklogParentRelation => {
  const payload = item.payload && typeof item.payload === 'object' ? item.payload : {}
  const taskSource = item.task_source === 'spec' ? 'spec' : 'ticket'
  const parentTicketKey = normalizeBacklogKey(payload.parent_key)
  const parentSpecKey = normalizeBacklogKey(payload.parent_spec_name)
  const dependencyMode = String(payload.dependency_mode || '').trim().toLowerCase()
  const dependsOnKeys = parseBacklogDependencyKeys(payload.depends_on)
  const parentCandidates = taskSource === 'spec'
    ? [parentSpecKey, ...dependsOnKeys]
    : [parentTicketKey, parentSpecKey, ...dependsOnKeys]
  const seenParentCandidates = new Set<string>()
  const dedupedParentCandidates: string[] = []
  const isTicketSubtask =
    taskSource !== 'spec'
    && (isSubtaskIssueType(item.issue_type) || parseBacklogSubtaskFlag(payload.is_subtask) || Boolean(parentTicketKey))
  const isSpecSubtask =
    taskSource === 'spec'
    && (dependencyMode === 'subtask' || Boolean(parentSpecKey) || dependsOnKeys.length > 0)

  for (const parentCandidate of parentCandidates) {
    if (!parentCandidate || seenParentCandidates.has(parentCandidate)) continue

    seenParentCandidates.add(parentCandidate)
    dedupedParentCandidates.push(parentCandidate)
  }

  return {
    isSubtask: isTicketSubtask || isSpecSubtask,
    parentCandidates: dedupedParentCandidates,
  }
}

const sortBacklogByParentRelationship = (backlog: PipelineBacklogItem[]) => {
  const relationByKey = new Map<string, BacklogParentRelation>()
  const keyOrder = new Map<string, number>()
  const availableKeys = new Set<string>()
  const roots: PipelineBacklogItem[] = []
  const orphans: PipelineBacklogItem[] = []
  const childrenByParent = new Map<string, PipelineBacklogItem[]>()

  for (const [index, item] of backlog.entries()) {
    const key = normalizeBacklogKey(item.key)

    if (!key || relationByKey.has(key)) continue

    relationByKey.set(key, getBacklogParentRelation(item))
    keyOrder.set(key, index)
    availableKeys.add(key)
  }

  const compareByOriginalOrder = (left: PipelineBacklogItem, right: PipelineBacklogItem) => {
    const leftKey = normalizeBacklogKey(left.key)
    const rightKey = normalizeBacklogKey(right.key)
    const leftOrder = keyOrder.get(leftKey) ?? Number.MAX_SAFE_INTEGER
    const rightOrder = keyOrder.get(rightKey) ?? Number.MAX_SAFE_INTEGER

    if (leftOrder !== rightOrder) return leftOrder - rightOrder

    return leftKey.localeCompare(rightKey)
  }

  for (const item of backlog) {
    const key = normalizeBacklogKey(item.key)
    const relation = relationByKey.get(key)

    if (!key || !relation) continue

    if (!relation.isSubtask) {
      roots.push(item)
      continue
    }

    const parentKey = relation.parentCandidates.find(
      (candidate) => candidate !== key && availableKeys.has(candidate)
    )

    if (!parentKey) {
      orphans.push(item)
      continue
    }

    const bucket = childrenByParent.get(parentKey) || []

    bucket.push(item)
    childrenByParent.set(parentKey, bucket)
  }

  roots.sort(compareByOriginalOrder)
  orphans.sort(compareByOriginalOrder)
  childrenByParent.forEach((bucket) => bucket.sort(compareByOriginalOrder))

  const ordered: PipelineBacklogItem[] = []
  const visitedKeys = new Set<string>()
  const appendTree = (item: PipelineBacklogItem) => {
    const key = normalizeBacklogKey(item.key)

    if (!key || visitedKeys.has(key)) return

    visitedKeys.add(key)
    ordered.push(item)

    const children = childrenByParent.get(key) || []

    for (const child of children) {
      appendTree(child)
    }
  }

  for (const root of roots) {
    appendTree(root)
  }

  for (const orphan of orphans) {
    appendTree(orphan)
  }

  for (const item of backlog) {
    appendTree(item)
  }

  return ordered
}

const reorderCurrentItems = (
  items: PipelineKanbanItem[],
  movingTaskId: string,
  beforeTaskId: string | null
) => {
  const movingItemId = `task:${movingTaskId}`
  const beforeItemId = beforeTaskId ? `task:${beforeTaskId}` : null

  const backlogItems = items.filter((item) => item.column === 'backlog')
  const currentItems = items.filter((item) => item.column === 'current')
  const runningItems = items.filter((item) => item.column === 'running')
  const completeItems = items.filter((item) => item.column === 'complete')

  const fromIndex = currentItems.findIndex((item) => item.id === movingItemId)

  if (fromIndex === -1) {
    return items
  }

  const nextCurrentItems = [...currentItems]
  const [movingItem] = nextCurrentItems.splice(fromIndex, 1)

  if (beforeItemId) {
    const beforeIndex = nextCurrentItems.findIndex((item) => item.id === beforeItemId)

    if (beforeIndex === -1) {
      nextCurrentItems.push(movingItem)
    } else {
      nextCurrentItems.splice(beforeIndex, 0, movingItem)
    }
  } else {
    nextCurrentItems.push(movingItem)
  }

  return [...backlogItems, ...nextCurrentItems, ...runningItems, ...completeItems]
}

export default function PipelinesKanbanBoard({
  backlog,
  currentTasks,
  runningTasks,
  completeTasks,
  trackedKeys,
  isMutating,
  onSelectTaskId,
  onQueueFromBacklog,
  onReorderCurrentBefore,
  onReorderCurrentToEnd,
  onMoveTaskToBacklog,
  onReenableTask,
  onStopRunningTask,
  onAdminForceResetTask,
  onAdminForceCompleteTask,
  onEditTaskDetails,
  onActionError,
}: PipelinesKanbanBoardProps) {
  const sortedBacklog = useMemo(
    () => sortBacklogByParentRelationship(backlog),
    [backlog]
  )

  const baseItems = useMemo<PipelineKanbanItem[]>(
    () => [
      ...sortedBacklog.map((item) => ({
        id: `backlog:${item.key}`,
        name: `${item.key} ${item.title}`,
        column: 'backlog' as const,
        kind: 'backlog' as const,
        tracked: trackedKeys.has(item.key),
        status: 'backlog' as const,
        backlog: item,
      })),

      ...currentTasks.map((task) => ({
        id: `task:${task.id}`,
        name: `${task.jira_key} ${task.title}`,
        column: 'current' as const,
        kind: 'task' as const,
        tracked: true,
        status: task.status,
        task,
      })),

      ...runningTasks.map((task) => ({
        id: `task:${task.id}`,
        name: `${task.jira_key} ${task.title}`,
        column: 'running' as const,
        kind: 'task' as const,
        tracked: true,
        status: task.status,
        task,
      })),

      ...completeTasks.map((task) => ({
        id: `task:${task.id}`,
        name: `${task.jira_key} ${task.title}`,
        column: 'complete' as const,
        kind: 'task' as const,
        tracked: true,
        status: task.status,
        task,
      })),
    ],
    [completeTasks, currentTasks, runningTasks, sortedBacklog, trackedKeys]
  )

  const [items, setItems] = useState<PipelineKanbanItem[]>(baseItems)

  const [draggingCardId, setDraggingCardId] = useState<string | null>(null)

  const [dragOverColumnId, setDragOverColumnId] = useState<ColumnId | null>(null)

  const [currentInsertionTarget, setCurrentInsertionTarget] = useState<CurrentInsertionTarget | null>(null)

  const visibleColumns = useMemo(() => COLUMN_DEFS, [])

  useEffect(() => {
    setItems(baseItems)
  }, [baseItems])

  const activeDragItem = useMemo(
    () => (draggingCardId ? items.find((item) => item.id === draggingCardId) || null : null),
    [draggingCardId, items]
  )

  const applyOptimisticCurrentReorder = (movingTaskId: string, beforeTaskId: string | null) => {
    setItems((previousItems) => reorderCurrentItems(previousItems, movingTaskId, beforeTaskId))
  }

  const runAction = async (fn: () => Promise<void>) => {
    try {
      await fn()

      onActionError('')
    } catch (err) {
      setItems(baseItems)

      onActionError(err instanceof Error ? err.message : 'Pipeline action failed')
    } finally {
      setDragOverColumnId(null)

      setCurrentInsertionTarget(null)
    }
  }

  const getActiveItem = (event?: DragEvent<HTMLElement>) => {
    const payload = event ? parseDragPayload(event) : null

    const itemId = payload?.itemId ?? draggingCardId

    if (!itemId) return null

    return items.find((item) => item.id === itemId) || null
  }

  const onCardDragStart = (event: DragEvent<HTMLElement>, item: PipelineKanbanItem) => {
    if (isMutating) {
      event.preventDefault()

      return
    }

    const draggable = item.kind === 'backlog' ? !item.tracked : item.status === 'current'

    if (!draggable) {
      event.preventDefault()

      return
    }

    setDraggingCardId(item.id)

    event.dataTransfer.effectAllowed = 'move'

    event.dataTransfer.setData('text/plain', item.id)

    event.dataTransfer.setData('application/pipeline', JSON.stringify({ itemId: item.id }))
  }

  const onCardDragEnd = () => {
    setDraggingCardId(null)

    setDragOverColumnId(null)

    setCurrentInsertionTarget(null)
  }

  const onColumnDragOver = (targetColumn: ColumnId) => (event: DragEvent<HTMLElement>) => {
    const activeItem = getActiveItem(event)

    if (!activeItem) return

    if (!canDropInColumn(activeItem, targetColumn)) return

    event.preventDefault()

    event.dataTransfer.dropEffect = 'move'

    if (dragOverColumnId !== targetColumn) {
      setDragOverColumnId(targetColumn)
    }

    if (targetColumn !== 'current') {
      if (currentInsertionTarget) setCurrentInsertionTarget(null)

      return
    }

    if (activeItem.kind === 'task' && activeItem.status === 'current') {
      setCurrentInsertionTarget((prev) => (prev?.beforeTaskId === null ? prev : { beforeTaskId: null }))

      return
    }

    if (currentInsertionTarget) {
      setCurrentInsertionTarget(null)
    }
  }

  const onCurrentInsertionDragOver =
    (beforeTaskId: string | null) => (event: DragEvent<HTMLElement>) => {
      const activeItem = getActiveItem(event)

      if (!activeItem) return

      if (activeItem.kind !== 'task' || activeItem.status !== 'current') return

      if (!canDropInColumn(activeItem, 'current')) return

      event.preventDefault()

      event.stopPropagation()

      event.dataTransfer.dropEffect = 'move'

      if (dragOverColumnId !== 'current') {
        setDragOverColumnId('current')
      }

      setCurrentInsertionTarget((prev) => (prev?.beforeTaskId === beforeTaskId ? prev : { beforeTaskId }))
    }

  const onCurrentInsertionDrop =
    (beforeTaskId: string | null) => (event: DragEvent<HTMLElement>) => {
      const activeItem = getActiveItem(event)

      if (!activeItem) return

      if (activeItem.kind !== 'task' || !activeItem.task || activeItem.status !== 'current') return

      event.preventDefault()

      event.stopPropagation()

      setDragOverColumnId(null)

      setCurrentInsertionTarget(null)

      const activeTask = activeItem.task

      if (beforeTaskId === activeTask.id) return

      applyOptimisticCurrentReorder(activeTask.id, beforeTaskId)

      if (beforeTaskId) {
        void runAction(() => onReorderCurrentBefore(activeTask.id, beforeTaskId))

        return
      }

      void runAction(() => onReorderCurrentToEnd(activeTask.id))
    }

  const onDropAt = (targetColumn: ColumnId, beforeTaskId?: string) => async (event: DragEvent<HTMLElement>) => {
    event.preventDefault()

    const activeItem = getActiveItem(event)

    setDragOverColumnId(null)

    setCurrentInsertionTarget(null)

    if (!activeItem) return

    if (!canDropInColumn(activeItem, targetColumn)) return

    if (activeItem.kind === 'backlog' && targetColumn === 'current' && activeItem.backlog) {
      await runAction(() => onQueueFromBacklog(activeItem.backlog as PipelineBacklogItem))

      return
    }

      if (activeItem.kind === 'task' && activeItem.task && activeItem.status === 'current') {
        const activeTask = activeItem.task

        if (!activeTask) return

      if (targetColumn === 'backlog') {
        await runAction(() => onMoveTaskToBacklog(activeTask.id))

        return
      }

        if (targetColumn === 'current') {
          if (beforeTaskId === activeTask.id) return

          applyOptimisticCurrentReorder(activeTask.id, beforeTaskId || null)

          if (beforeTaskId) {
            void runAction(() => onReorderCurrentBefore(activeTask.id, beforeTaskId))

            return
          }

          void runAction(() => onReorderCurrentToEnd(activeTask.id))
        }
      }
    }

  return (
    <div className='min-h-0 w-auto space-y-4'>
      <div className='flex w-auto gap-4 pb-2'>
        {visibleColumns.map((column) => {
          const columnItems = items.filter((item) => item.column === column.id)

          const isDropTarget = dragOverColumnId === column.id

          return (
            <PipelineKanbanColumn
              key={column.id}
              column={column}
              items={columnItems}
              isMutating={isMutating}
              draggingCardId={draggingCardId}
              activeDragItem={activeDragItem}
              isSortableCurrentDrag={activeDragItem?.kind === 'task' && activeDragItem.status === 'current'}
              isDropTarget={isDropTarget}
              currentInsertionBeforeTaskId={column.id === 'current' ? currentInsertionTarget?.beforeTaskId : undefined}
              onColumnDragOver={onColumnDragOver(column.id)}
              onColumnDrop={(event) => {
                void onDropAt(column.id)(event)
              }}
              onCardDragStart={onCardDragStart}
              onCardDragEnd={onCardDragEnd}
              onCurrentInsertionDragOver={onCurrentInsertionDragOver}
              onCurrentInsertionDrop={(event, beforeTaskId) => {
                void onCurrentInsertionDrop(beforeTaskId)(event)
              }}
              onSelectTaskId={onSelectTaskId}
              onQueueFromBacklog={onQueueFromBacklog}
              onMoveTaskToBacklog={onMoveTaskToBacklog}
              onReenableTask={onReenableTask}
              onStopRunningTask={onStopRunningTask}
              onAdminForceResetTask={onAdminForceResetTask}
              onAdminForceCompleteTask={onAdminForceCompleteTask}
              onEditTaskDetails={onEditTaskDetails}
              onRunAction={(fn) => {
                void runAction(fn)
              }}
            />
          )
        })}
      </div>
    </div>
  )
}
