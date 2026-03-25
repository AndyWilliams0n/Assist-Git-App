import { useCallback, useEffect, useMemo, useState } from "react"

import type {
  PipelineBacklogItem,
  PipelineTask,
  PipelineWorkspaceAction,
} from "@/features/pipelines/types"

type UsePipelineBoardInteractionsArgs = {
  currentTasks: PipelineTask[]
  allTasks: PipelineTask[]
  reorderCurrent: (orderedTaskIds: string[]) => Promise<void>
  openWorkspacePicker: (action: PipelineWorkspaceAction) => void
}

const moveBefore = (items: PipelineTask[], movingId: string, beforeId: string) => {
  const copy = [...items]
  const fromIndex = copy.findIndex((item) => item.id === movingId)
  const toIndex = copy.findIndex((item) => item.id === beforeId)
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return copy

  const [moving] = copy.splice(fromIndex, 1)
  copy.splice(toIndex, 0, moving)
  return copy
}

const moveToEnd = (items: PipelineTask[], movingId: string) => {
  const copy = [...items]
  const fromIndex = copy.findIndex((item) => item.id === movingId)
  if (fromIndex === -1) return copy

  const [moving] = copy.splice(fromIndex, 1)
  copy.push(moving)
  return copy
}

const normalizeDependencyKey = (value: unknown) => String(value || "").trim().toUpperCase()

const payloadRecordFor = (value: unknown): Record<string, unknown> => {
  if (value && typeof value === "object") {
    return value as Record<string, unknown>
  }
  return {}
}

const firstNonEmptyString = (...values: unknown[]) => {
  for (const value of values) {
    const normalized = String(value || "").trim()
    if (!normalized) continue
    return normalized
  }
  return ""
}

const dependencyKeysFromPayload = (payload: Record<string, unknown>) => {
  const deduped: string[] = []
  const seen = new Set<string>()

  const rawDependsOn = payload.depends_on
  if (!Array.isArray(rawDependsOn)) return deduped

  for (const dependency of rawDependsOn) {
    const normalized = normalizeDependencyKey(dependency)
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    deduped.push(normalized)
  }

  return deduped
}

export const usePipelineBoardInteractions = ({
  currentTasks,
  allTasks,
  reorderCurrent,
  openWorkspacePicker,
}: UsePipelineBoardInteractionsArgs) => {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  const selectedTask = useMemo(
    () => allTasks.find((task) => task.id === selectedTaskId) || null,
    [allTasks, selectedTaskId]
  )

  useEffect(() => {
    if (!selectedTaskId) return
    if (!selectedTask) {
      setSelectedTaskId(null)
    }
  }, [selectedTask, selectedTaskId])

  const queueFromBacklog = useCallback(
    async (item: PipelineBacklogItem) => {
      const payload = payloadRecordFor(item.payload)
      const rawDependencyMode = String(payload.dependency_mode || "").trim().toLowerCase()
      const defaultTaskType = rawDependencyMode === "subtask" ? "subtask" : "task"
      const defaultDependencyKeys = dependencyKeysFromPayload(payload)
      const defaultParentSpecName = normalizeDependencyKey(payload.parent_spec_name)
      const defaultDependencyKey = defaultDependencyKeys[0] || defaultParentSpecName || ""
      const defaultWorkspacePath = firstNonEmptyString(payload.workspace_path, payload.workspacePath)
      const defaultStartingGitBranchOverride = firstNonEmptyString(
        payload.starting_git_branch_override,
        payload.startingGitBranchOverride,
        payload.starting_git_branch,
        payload.working_branch,
        payload.active_working_branch,
        payload.branch
      )

      openWorkspacePicker({
        kind: "queue",
        jiraKey: item.key,
        taskSource: item.task_source,
        workspacePath: defaultWorkspacePath,
        workflow: "codex",
        jiraCompleteColumnName: "",
        startingGitBranchOverride: defaultStartingGitBranchOverride,
        defaultTaskType,
        defaultDependencyKey,
      })
    },
    [openWorkspacePicker]
  )

  const reorderCurrentToEnd = useCallback(
    async (taskId: string) => {
      const next = moveToEnd(currentTasks, taskId).map((task) => task.id)
      await reorderCurrent(next)
    },
    [currentTasks, reorderCurrent]
  )

  const reorderCurrentBefore = useCallback(
    async (movingTaskId: string, beforeTaskId: string) => {
      const next = moveBefore(currentTasks, movingTaskId, beforeTaskId).map((task) => task.id)
      await reorderCurrent(next)
    },
    [currentTasks, reorderCurrent]
  )

  return {
    selectedTask,
    selectedTaskId,
    setSelectedTaskId,
    queueFromBacklog,
    reorderCurrentBefore,
    reorderCurrentToEnd,
  }
}
