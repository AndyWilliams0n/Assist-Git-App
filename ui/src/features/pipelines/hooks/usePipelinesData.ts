import { useCallback, useEffect, useMemo, useState } from "react"

import { usePipelinesStore } from "@/features/pipelines/store/usePipelinesStore"
import type {
  PipelineMoveResponse,
  PipelineNextTaskTriggerResponse,
  PipelineQueueResponse,
  PipelineRefreshBacklogResponse,
  PipelineHeartbeatTriggerResponse,
  PipelineSettingsResponse,
  PipelineState,
  PipelineTaskDependenciesResponse,
  PipelineTaskHandoffsResponse,
  PipelineTaskRelationType,
  PipelineWorkflow,
} from "@/features/pipelines/types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) return path
  return `${API_BASE_URL}${path}`
}

export const usePipelinesData = () => {
  const {
    state,
    isLoading,
    isMutating,
    error,
    mode,
    setPipelineState,
    setIsLoading,
    setIsMutating,
    setError,
    setMode,
    applyPipelineState,
  } = usePipelinesStore()

  const [heartbeatCountdown, setHeartbeatCountdown] = useState(0)

  const loadState = useCallback(async () => {
    const response = await fetch(buildApiUrl("/api/pipelines/state"))
    if (!response.ok) {
      throw new Error(`Failed to fetch pipeline state (${response.status})`)
    }
    return response.json() as Promise<PipelineState>
  }, [])

  const refreshBacklog = useCallback(async () => {
    setIsMutating(true)
    try {
      const response = await fetch(buildApiUrl("/api/pipelines/backlog/refresh"), {
        method: "POST",
      })
      if (!response.ok) {
        throw new Error(`Failed to refresh backlog (${response.status})`)
      }
      await (response.json() as Promise<PipelineRefreshBacklogResponse>)
      const latest = await loadState()
      setPipelineState(latest)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh backlog")
      throw err
    } finally {
      setIsMutating(false)
    }
  }, [loadState, setError, setIsMutating, setPipelineState])

  const queueTask = useCallback(
    async (
      jiraKey: string,
      workspacePath: string,
      workflow: PipelineWorkflow,
      jiraCompleteColumnName?: string,
      startingGitBranchOverride?: string,
      dependsOnTaskIds?: string[],
      taskRelation?: PipelineTaskRelationType,
      options?: { manageMutating?: boolean }
    ) => {
      const manageMutating = options?.manageMutating ?? true

      if (manageMutating) setIsMutating(true)

      try {
        const response = await fetch(buildApiUrl("/api/pipelines/tasks/queue"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jira_key: jiraKey,
            workspace_path: workspacePath,
            workflow,
            jira_complete_column_name: jiraCompleteColumnName ?? undefined,
            starting_git_branch_override: startingGitBranchOverride ?? undefined,
            depends_on_task_ids: dependsOnTaskIds ?? undefined,
            task_relation: taskRelation ?? undefined,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to queue task (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineQueueResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to queue task")
        throw err
      } finally {
        if (manageMutating) setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const moveTask = useCallback(
    async (
      taskId: string,
      targetStatus: "current" | "running" | "complete" | "failed" | "stopped" | "backlog",
      workspacePath?: string,
      workflow?: PipelineWorkflow,
      jiraCompleteColumnName?: string,
      startingGitBranchOverride?: string,
      dependsOnTaskIds?: string[],
      taskRelation?: PipelineTaskRelationType,
      options?: { manageMutating?: boolean }
    ) => {
      const manageMutating = options?.manageMutating ?? true

      if (manageMutating) setIsMutating(true)

      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/move`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_status: targetStatus,
            workspace_path: workspacePath || undefined,
            workflow: workflow || undefined,
            jira_complete_column_name: jiraCompleteColumnName ?? undefined,
            starting_git_branch_override: startingGitBranchOverride ?? undefined,
            depends_on_task_ids: dependsOnTaskIds ?? undefined,
            task_relation: taskRelation ?? undefined,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to move task (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineMoveResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to move task")
        throw err
      } finally {
        if (manageMutating) setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const reorderCurrent = useCallback(
    async (orderedTaskIds: string[]) => {
      usePipelinesStore.getState().applyOptimisticReorder(orderedTaskIds)

      try {
        const response = await fetch(buildApiUrl("/api/pipelines/tasks/reorder"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ordered_task_ids: orderedTaskIds }),
        })

        if (!response.ok) {
          throw new Error(`Failed to reorder tasks (${response.status})`)
        }

        setError(null)
      } catch (err) {
        const latest = await loadState()
        setPipelineState(latest)
        setError(err instanceof Error ? err.message : "Failed to reorder tasks")
        throw err
      } finally {
        usePipelinesStore.getState().clearOptimisticReorder()
      }
    },
    [loadState, setError, setPipelineState]
  )

  const setTaskBypass = useCallback(
    async (
      taskId: string,
      bypassed: boolean,
      reason?: string,
      resolveHandoffs?: boolean
    ) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/bypass`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            bypassed,
            reason: reason ?? undefined,
            resolve_handoffs: resolveHandoffs ?? undefined,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to update task bypass (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update task bypass")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const resolveTaskHandoff = useCallback(
    async (
      taskId: string,
      handoffId: string,
      reenableTask?: boolean
    ) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/handoffs/${handoffId}/resolve`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            reenable_task: reenableTask ?? false,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to resolve task handoff (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineTaskHandoffsResponse | { task_id: string }>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to resolve task handoff")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const setTaskDependencies = useCallback(
    async (taskId: string, dependsOnTaskIds: string[]) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/dependencies`), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            depends_on_task_ids: dependsOnTaskIds,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to update task dependencies (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineTaskDependenciesResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update task dependencies")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const updateSettings = useCallback(
    async (
      activeWindowStart: string,
      activeWindowEnd: string,
      heartbeatIntervalMinutes: number,
      maxRetries: number
    ) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl("/api/pipelines/settings"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            active_window_start: activeWindowStart,
            active_window_end: activeWindowEnd,
            heartbeat_interval_minutes: heartbeatIntervalMinutes,
            max_retries: maxRetries,
          }),
        })
        if (!response.ok) {
          let detail = `Failed to update settings (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineSettingsResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update settings")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const setAutomationEnabled = useCallback(
    async (enabled: boolean) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl("/api/pipelines/automation"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: Boolean(enabled),
          }),
        })
        if (!response.ok) {
          let detail = `Failed to toggle automation (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineSettingsResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to toggle automation")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const triggerHeartbeatSoon = useCallback(
    async (delaySeconds = 10) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl("/api/pipelines/heartbeat/trigger"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            delay_seconds: Math.max(0, Math.min(300, Number(delaySeconds || 0))),
          }),
        })
        if (!response.ok) {
          let detail = `Failed to trigger pipeline heartbeat (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineHeartbeatTriggerResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to trigger pipeline heartbeat")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const triggerNextTaskNow = useCallback(
    async () => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl("/api/pipelines/tasks/trigger-next"), {
          method: "POST",
        })
        if (!response.ok) {
          let detail = `Failed to trigger next task (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await (response.json() as Promise<PipelineNextTaskTriggerResponse>)
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to trigger next task")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const adminForceResetTask = useCallback(
    async (taskId: string) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/admin/reset`), {
          method: "POST",
        })
        if (!response.ok) {
          let detail = `Failed to reset task (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await response.json()
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reset task")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  const adminForceCompleteTask = useCallback(
    async (taskId: string) => {
      setIsMutating(true)
      try {
        const response = await fetch(buildApiUrl(`/api/pipelines/tasks/${taskId}/admin/complete`), {
          method: "POST",
        })
        if (!response.ok) {
          let detail = `Failed to mark task complete (${response.status})`
          try {
            const payload = (await response.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            // Ignore JSON parse failures and keep fallback detail.
          }
          throw new Error(detail)
        }
        await response.json()
        const latest = await loadState()
        setPipelineState(latest)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to mark task complete")
        throw err
      } finally {
        setIsMutating(false)
      }
    },
    [loadState, setError, setIsMutating, setPipelineState]
  )

  useEffect(() => {
    let isMounted = true
    let eventSource: EventSource | null = null

    const applyState = (nextState: PipelineState) => {
      if (!isMounted) return
      applyPipelineState(nextState)
    }

    eventSource = new EventSource(buildApiUrl("/api/pipelines/stream"))
    setMode("streaming")

    eventSource.onmessage = (event) => {
      if (!event.data) return
      try {
        const payload = JSON.parse(event.data) as PipelineState
        applyState(payload)
      } catch (err) {
        if (!isMounted) return
        setError(err instanceof Error ? err.message : "Failed to parse pipeline stream")
      }
    }

    eventSource.onerror = () => {
      if (!isMounted) return
      setError("Pipeline stream disconnected")
      setIsLoading(false)
    }

    void loadState()
      .then(applyState)
      .catch((err: unknown) => {
        if (!isMounted) return
        setError(err instanceof Error ? err.message : "Failed to load pipeline state")
        setIsLoading(false)
      })

    return () => {
      isMounted = false
      if (eventSource) {
        eventSource.close()
      }
    }
  }, [applyPipelineState, loadState, setError, setIsLoading, setMode])

  useEffect(() => {
    const next = state?.heartbeat?.countdown_seconds ?? 0
    setHeartbeatCountdown(next)
  }, [state?.heartbeat?.countdown_seconds])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setHeartbeatCountdown((value) => (value > 0 ? value - 1 : 0))
    }, 1000)
    return () => {
      window.clearInterval(timer)
    }
  }, [])

  return useMemo(
    () => ({
      state,
      isLoading,
      isMutating,
      error,
      mode,
      heartbeatCountdown,
      refreshBacklog,
      queueTask,
      moveTask,
      reorderCurrent,
      setTaskBypass,
      setTaskDependencies,
      resolveTaskHandoff,
      updateSettings,
      setAutomationEnabled,
      triggerHeartbeatSoon,
      triggerNextTaskNow,
      adminForceResetTask,
      adminForceCompleteTask,
    }),
    [
      state,
      isLoading,
      isMutating,
      error,
      mode,
      heartbeatCountdown,
      refreshBacklog,
      queueTask,
      moveTask,
      reorderCurrent,
      setTaskBypass,
      setTaskDependencies,
      resolveTaskHandoff,
      updateSettings,
      setAutomationEnabled,
      triggerHeartbeatSoon,
      triggerNextTaskNow,
      adminForceResetTask,
      adminForceCompleteTask,
    ]
  )
}
