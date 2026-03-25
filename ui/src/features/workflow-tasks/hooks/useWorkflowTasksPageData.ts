import { useCallback, useEffect, useMemo, useState } from "react"

import { toast } from "sonner"

import { useWorkflowTasksStore } from "@/features/workflow-tasks/store/useWorkflowTasksStore"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"
import { sortWorkflowTasksForTable } from "@/features/workflow-tasks/hooks/useWorkflowTasksSortedTickets"
import type {
  JiraUser,
  WorkflowTasksConfigResponse,
  WorkflowTasksFetchHistoryItem,
  WorkflowTasksFetchResponse,
  WorkflowTasksFetchSnapshotPayload,
  WorkflowSpecTask,
  WorkflowSpecTasksResponse,
} from "@/features/workflow-tasks/types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) return path
  return `${API_BASE_URL}${path}`
}

export const useWorkflowTasksPageData = () => {
  const primaryWorkspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)
  const [config, setConfig] = useState<WorkflowTasksConfigResponse | null>(null)
  const [isLoadingConfig, setIsLoadingConfig] = useState(true)
  const [isLoadingSpecTasks, setIsLoadingSpecTasks] = useState(true)
  const [isFetching, setIsFetching] = useState(false)
  const [isFetchingUsers, setIsFetchingUsers] = useState(false)
  const [specTasks, setSpecTasks] = useState<WorkflowSpecTask[]>([])

  const projectKey = useWorkflowTasksStore((state) => state.projectKey)
  const boardNumber = useWorkflowTasksStore((state) => state.boardNumber)
  const assigneeFilter = useWorkflowTasksStore((state) => state.assigneeFilter)
  const jiraUsers = useWorkflowTasksStore((state) => state.jiraUsers)
  const tickets = useWorkflowTasksStore((state) => state.tickets)
  const currentSprint = useWorkflowTasksStore((state) => state.currentSprint)
  const kanbanColumns = useWorkflowTasksStore((state) => state.kanbanColumns)
  const server = useWorkflowTasksStore((state) => state.server)
  const tool = useWorkflowTasksStore((state) => state.tool)
  const fetchedAt = useWorkflowTasksStore((state) => state.fetchedAt)
  const savedAt = useWorkflowTasksStore((state) => state.savedAt)
  const dbId = useWorkflowTasksStore((state) => state.dbId)
  const setProjectKey = useWorkflowTasksStore((state) => state.setProjectKey)
  const setBoardNumber = useWorkflowTasksStore((state) => state.setBoardNumber)
  const setAssigneeFilter = useWorkflowTasksStore((state) => state.setAssigneeFilter)
  const setJiraUsers = useWorkflowTasksStore((state) => state.setJiraUsers)
  const setFetchSnapshot = useWorkflowTasksStore((state) => state.setFetchSnapshot)
  const setFromConfig = useWorkflowTasksStore((state) => state.setFromConfig)
  const setWarning = useWorkflowTasksStore((state) => state.setWarning)
  const clearFetchSnapshot = useWorkflowTasksStore((state) => state.clearFetchSnapshot)

  const jiraBaseUrl = config?.jira_base_url || ""

  const issueBaseUrl = useMemo(() => {
    if (!jiraBaseUrl) return ""
    return `${jiraBaseUrl.replace(/\/$/, "")}/browse/`
  }, [jiraBaseUrl])

  const canFetch = Boolean(projectKey.trim() && boardNumber.trim())

  const applyFetchState = useCallback(
    (payload: WorkflowTasksFetchSnapshotPayload) => {
      const hasCurrentSprint =
        !!payload.current_sprint && Object.keys(payload.current_sprint).length > 0
      setFetchSnapshot({
        ...payload,
        tickets: sortWorkflowTasksForTable(payload.tickets || []),
        current_sprint: hasCurrentSprint && payload.current_sprint
          ? {
              ...payload.current_sprint,
              tickets: sortWorkflowTasksForTable(payload.current_sprint.tickets || []),
            }
          : null,
      })
    },
    [setFetchSnapshot]
  )

  const saveJiraConfig = useCallback(
    async (nextProjectKey: string, nextBoardNumber: string) => {
      try {
        await fetch(buildApiUrl("/api/jira/config"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_key: nextProjectKey.trim().toUpperCase() || null,
            board_id: nextBoardNumber.trim() || null,
          }),
        })
      } catch {
        // Non-blocking — local state already updated.
      }
    },
    []
  )

  const saveAssigneeFilter = useCallback(
    async (nextFilter: string) => {
      setAssigneeFilter(nextFilter)

      try {
        await fetch(buildApiUrl("/api/jira/config"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ assignee_filter: nextFilter }),
        })
      } catch {
        // Non-blocking — local state already updated.
      }
    },
    [setAssigneeFilter]
  )

  const fetchJiraUsers = useCallback(async () => {
    setIsFetchingUsers(true)

    try {
      const response = await fetch(buildApiUrl("/api/jira/users"))

      if (!response.ok) {
        let detail = `Failed to fetch Jira users (${response.status})`

        try {
          const errorPayload = (await response.json()) as { detail?: string }
          if (errorPayload?.detail) detail = errorPayload.detail
        } catch {
          // Ignore JSON parse failures.
        }

        throw new Error(detail)
      }

      const payload = (await response.json()) as { users: JiraUser[] }
      const users = Array.isArray(payload.users) ? payload.users : []
      setJiraUsers(users)
      toast.success(`Loaded ${users.length} Jira user${users.length === 1 ? '' : 's'}.`)
    } catch (err) {
      toast.error('Couldn\'t load Jira users.', {
        description: err instanceof Error ? err.message : 'An unexpected error occurred.',
      })
    } finally {
      setIsFetchingUsers(false)
    }
  }, [setJiraUsers])

  const fetchTickets = useCallback(async () => {
    if (!canFetch) return

    setIsFetching(true)
    setWarning("")

    try {
      const response = await fetch(buildApiUrl("/api/jira/tickets/fetch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_key: projectKey.trim().toUpperCase(),
          board_id: boardNumber.trim(),
        }),
      })

      if (!response.ok) {
        let detail = `Failed to fetch Jira tasks (${response.status})`

        try {
          const errorPayload = (await response.json()) as { detail?: string }

          if (errorPayload?.detail) {
            detail = errorPayload.detail
          }
        } catch {
          // Ignore JSON parse failures and keep fallback detail.
        }

        throw new Error(detail)
      }

      const payload = (await response.json()) as WorkflowTasksFetchResponse

      applyFetchState(payload)

      const warnings = payload.warnings || []
      const ticketCount = (payload.tickets || []).length

      if (warnings.length > 0) {
        toast.warning(warnings[0])
      } else {
        toast.success(`Fetched ${ticketCount} ticket${ticketCount === 1 ? '' : 's'} from Jira.`)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to fetch Jira tasks"
      toast.error(message, {
        description: 'Check your Project key and Board number, then try again.',
      })
      clearFetchSnapshot()
    } finally {
      setIsFetching(false)
    }
  }, [applyFetchState, boardNumber, canFetch, clearFetchSnapshot, projectKey, setWarning])

  const loadSpecTasks = useCallback(async () => {
    setIsLoadingSpecTasks(true)
    try {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      const params = new URLSearchParams()

      if (trimmedWorkspace) {
        params.set("workspace_path", trimmedWorkspace)
      }

      const query = params.toString()
      const endpoint = query ? `/api/spec-tasks?${query}` : "/api/spec-tasks"
      const response = await fetch(buildApiUrl(endpoint))
      if (!response.ok) {
        let detail = `Failed to load spec tasks (${response.status})`
        try {
          const payload = (await response.json()) as { detail?: string }
          if (payload?.detail) {
            detail = payload.detail
          }
        } catch {
          // Ignore JSON parse failures and keep fallback detail.
        }
        throw new Error(detail)
      }
      const payload = (await response.json()) as WorkflowSpecTasksResponse
      setSpecTasks(Array.isArray(payload.spec_tasks) ? payload.spec_tasks : [])
    } catch (err) {
      setSpecTasks([])
      toast.error('Couldn\'t load spec tasks.', {
        description: err instanceof Error ? err.message : 'An unexpected error occurred.',
      })
    } finally {
      setIsLoadingSpecTasks(false)
    }
  }, [primaryWorkspacePath])

  useEffect(() => {
    let isMounted = true
    const load = async () => {
      setIsLoadingConfig(true)
      try {
        const [configResponse, latestResponse] = await Promise.all([
          fetch(buildApiUrl("/api/jira/config")),
          fetch(buildApiUrl("/api/jira/fetches?limit=1&include_raw=true")),
        ])

        if (!configResponse.ok) {
          throw new Error("Failed to load workflow tasks config")
        }
        const configPayload = (await configResponse.json()) as WorkflowTasksConfigResponse
        if (!isMounted) return

        setConfig(configPayload)
        setFromConfig(
          configPayload.project_key || "",
          configPayload.board_id || "",
          configPayload.assignee_filter || "",
          configPayload.jira_users || [],
        )

        if (latestResponse.ok) {
          const latestPayload = (await latestResponse.json()) as { fetches?: WorkflowTasksFetchHistoryItem[] }
          const latest = (latestPayload.fetches || [])[0]
          if (latest) {
            applyFetchState({
              tickets: latest.tickets || [],
              current_sprint: latest.current_sprint || null,
              kanban_columns: latest.kanban_columns || [],
              server: latest.server,
              tool: latest.tool,
              fetched_at: latest.created_at,
              saved_at: latest.created_at,
              db_id: latest.id,
              warnings: latest.warnings || [],
            })
          }
        }

      } catch (err) {
        if (!isMounted) return
        toast.error('Couldn\'t load Jira configuration.', {
          description: err instanceof Error ? err.message : 'An unexpected error occurred.',
        })
      } finally {
        if (isMounted) {
          setIsLoadingConfig(false)
        }
      }
    }
    void load()
    return () => {
      isMounted = false
    }
  }, [applyFetchState, setFromConfig])

  useEffect(() => {
    void loadSpecTasks()
  }, [loadSpecTasks])

  return {
    config,
    projectKey,
    boardNumber,
    assigneeFilter,
    jiraUsers,
    setProjectKey,
    setBoardNumber,
    saveJiraConfig,
    saveAssigneeFilter,
    fetchJiraUsers,
    isFetchingUsers,
    canFetch,
    tickets,
    currentSprint,
    kanbanColumns,
    server,
    tool,
    fetchedAt,
    savedAt,
    dbId,
    isLoadingConfig,
    isFetching,
    specTasks,
    isLoadingSpecTasks,
    issueBaseUrl,
    fetchTickets,
    loadSpecTasks,
  }
}
