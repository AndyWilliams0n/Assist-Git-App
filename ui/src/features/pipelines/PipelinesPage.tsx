import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import PipelineHeader from "@/features/pipelines/components/PipelineHeader"
import PipelineGitHandoffsPanel from "@/features/pipelines/components/PipelineGitHandoffsPanel"
import PipelinesPageBoardSection from "@/features/pipelines/components/PipelinesPageBoardSection"
import PipelinesPageStatus from "@/features/pipelines/components/PipelinesPageStatus"
import PipelinesRunningActivityBanner from "@/features/pipelines/components/PipelinesRunningActivityBanner"
import PipelineSettingsPanel from "@/features/pipelines/components/PipelineSettingsPanel"
import type { BacklogWorkflowFilter } from "@/features/pipelines/components/PipelineSettingsPanel"
import PipelineTaskDetailsSheet from "@/features/pipelines/components/PipelineTaskDetailsSheet"
import PipelineTaskSetupDialog from "@/features/pipelines/components/PipelineTaskSetupDialog"
import { usePipelineBoardInteractions } from "@/features/pipelines/hooks/usePipelineBoardInteractions"
import { usePipelinesData } from "@/features/pipelines/hooks/usePipelinesData"
import { usePipelinesStore } from "@/features/pipelines/store/usePipelinesStore"
import { usePipelineSettingsForm } from "@/features/pipelines/hooks/usePipelineSettingsForm"
import { useGitStore } from "@/features/git/store/git-store"
import { isEpicTicket, isSubtaskTicket } from "@/features/workflow-tasks/hooks/useWorkflowTasksSortedTickets"
import type {
  PendingWorkspaceAction,
  PipelineDependencyOption,
  PipelineTask,
  PipelineTaskRelationType,
  PipelineWorkspaceAction,
} from "@/features/pipelines/types"
import { useWorkflowTasksStore } from "@/features/workflow-tasks/store/useWorkflowTasksStore"
import { useWorkspaces } from "@/features/workspace/hooks/useWorkspaces"
import { WorkspaceRequiredState } from "@/shared/components/workspace-required-state"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)
const PIPELINES_JIRA_DESTINATION_PREFERENCE_KEY = "pipelines:jira-complete-column-default"
const issueTypeText = (value?: string) => (value || "").trim().toLowerCase()
const isEpicIssueType = (value?: string) => issueTypeText(value).includes("epic")
const isSubtaskIssueType = (value?: string) => {
  const type = issueTypeText(value)
  return type.includes("sub-task") || type.includes("subtask")
}
const normalizeDependencyKey = (value: string) => String(value || "").trim().toUpperCase()
const isWorkflowTicketCompleted = (status?: string) => {
  const normalizedStatus = String(status || "").trim().toLowerCase()
  return (
    normalizedStatus.includes("done")
    || normalizedStatus.includes("complete")
    || normalizedStatus.includes("closed")
    || normalizedStatus.includes("resolved")
  )
}

export default function PipelinesPage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const workspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)
  const clearStoreError = usePipelinesStore((state) => state.setError)
  const [localError, setLocalError] = useState<string | null>(null)
  const [workspaceSetupOpen, setWorkspaceSetupOpen] = useState(false)
  const [pendingWorkspaceAction, setPendingWorkspaceAction] = useState<PendingWorkspaceAction>(null)
  const [workspaceInput, setWorkspaceInput] = useState("")
  const [jiraCompleteColumnNameInput, setJiraCompleteColumnNameInput] = useState("")
  const [startingGitBranchOverrideInput, setStartingGitBranchOverrideInput] = useState("")
  const [taskRelationInput, setTaskRelationInput] = useState<PipelineTaskRelationType>("task")
  const [dependencyKeyInput, setDependencyKeyInput] = useState("")
  const [preferredJiraCompleteColumnName, setPreferredJiraCompleteColumnName] = useState("")
  const [gitBranchOptions, setGitBranchOptions] = useState<string[]>([])
  const [gitCurrentBranch, setGitCurrentBranch] = useState<string | null>(null)
  const [isLoadingGitBranches, setIsLoadingGitBranches] = useState(false)
  const [gitBranchesError, setGitBranchesError] = useState<string | null>(null)
  const [backlogWorkflowFilter, setBacklogWorkflowFilter] = useState<BacklogWorkflowFilter>("specs")
  const didBootstrapBacklog = useRef(false)
  const didAutoPrefillQueueBranchRef = useRef(false)
  const gitDefaultWorkingBranch = useGitStore((state) => state.workflows.pipeline.settings.defaultBranch)

  const {
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
    resolveTaskHandoff,
    updateSettings,
    setAutomationEnabled,
    triggerHeartbeatSoon,
    triggerNextTaskNow,
    adminForceResetTask,
    adminForceCompleteTask,
  } = usePipelinesData()

  const assigneeFilter = useWorkflowTasksStore((state) => state.assigneeFilter)
  const columns = state?.columns
  const rawBacklog = useMemo(() => state?.backlog ?? [], [state?.backlog])
  const assigneeFilteredBacklog = useMemo(() => {
    if (!assigneeFilter) return rawBacklog

    if (assigneeFilter === '__unassigned__') {
      return rawBacklog.filter((item) => {
        if (item.task_source !== 'jira') return true

        return !item.assignee || item.assignee.trim() === ''
      })
    }

    return rawBacklog.filter((item) => {
      if (item.task_source !== 'jira') return true

      return item.assignee === assigneeFilter
    })
  }, [assigneeFilter, rawBacklog])
  const visibleBacklog = useMemo(() => {
    if (backlogWorkflowFilter === "all") return assigneeFilteredBacklog
    if (backlogWorkflowFilter === "specs") {
      return assigneeFilteredBacklog.filter((item) => item.task_source === "spec")
    }

    return assigneeFilteredBacklog.filter((item) => item.task_source === "jira")
  }, [assigneeFilteredBacklog, backlogWorkflowFilter])
  const currentTasks = useMemo(() => columns?.current ?? [], [columns])
  const runningTasks = useMemo(() => columns?.running ?? [], [columns])
  const completeTasks = useMemo(() => columns?.complete ?? [], [columns])

  const allTasks = useMemo(
    () => [...currentTasks, ...runningTasks, ...completeTasks],
    [completeTasks, currentTasks, runningTasks]
  )

  const trackedKeys = useMemo(
    () => new Set<string>(allTasks.map((task) => task.jira_key)),
    [allTasks]
  )
  const currentPipelineTicketKeys = useMemo(
    () =>
      Array.from(
        new Set(
          currentTasks
            .map((task) => String(task.jira_key || "").trim().toUpperCase())
            .filter(Boolean)
        )
      ),
    [currentTasks]
  )
  const runningActivityLine = useMemo(() => {
    const task = runningTasks[0]
    if (!task) return ""

    const latestRun = task.runs[0]
    const attemptCount = Math.max(0, Number(latestRun?.attempt_count || 0))
    const maxRetries = Math.max(0, Number(latestRun?.max_retries || 0))
    const attemptsFailed = Math.max(0, Number(latestRun?.attempts_failed || 0))
    const attemptsCompleted = Math.max(0, Number(latestRun?.attempts_completed || 0))
    const attemptsRunning = 1
    const retriesUsed = Math.max(0, attemptCount - 1)
    const retryBudget = maxRetries > 0 ? Math.max(0, maxRetries - 1) : 0
    const activity = String(latestRun?.current_activity || task.logs[0]?.message || "Pipeline task in progress.").trim()

    return (
      `${task.jira_key} | Attempt ${attemptCount}/${maxRetries} | `
      + `Retries ${retriesUsed}/${retryBudget} | `
      + `running ${attemptsRunning} completed ${attemptsCompleted} failed ${attemptsFailed} | `
      + activity
    )
  }, [runningTasks])
  const unresolvedHandoffs = useMemo(
    () => state?.handoffs?.unresolved ?? [],
    [state?.handoffs?.unresolved]
  )

  const [debouncedHandoffs, setDebouncedHandoffs] = useState<typeof unresolvedHandoffs>([])
  const debouncedHandoffsRef = useRef<typeof unresolvedHandoffs>([])

  useEffect(() => {
    if (unresolvedHandoffs.length === 0) {
      debouncedHandoffsRef.current = []
      setDebouncedHandoffs([])
      return
    }

    if (debouncedHandoffsRef.current.length > 0) {
      debouncedHandoffsRef.current = unresolvedHandoffs
      setDebouncedHandoffs(unresolvedHandoffs)
      return
    }

    const timer = setTimeout(() => {
      debouncedHandoffsRef.current = unresolvedHandoffs
      setDebouncedHandoffs(unresolvedHandoffs)
    }, 10_000)

    return () => clearTimeout(timer)
  }, [unresolvedHandoffs])

  const sharedWorkflowTickets = useWorkflowTasksStore((state) => state.tickets)
  const sharedWorkflowWarning = useWorkflowTasksStore((state) => state.warning)
  const sharedWorkflowKanbanColumns = useWorkflowTasksStore((state) => state.kanbanColumns)
  const pipelineTaskBranchSuggestionKeys = useMemo(() => {
    const workflowTicketsByKey = new Map(
      sharedWorkflowTickets.map((ticket) => [String(ticket.key || "").trim().toUpperCase(), ticket] as const)
    )
    const seen = new Set<string>()
    const suggestions: string[] = []

    for (const backlogItem of assigneeFilteredBacklog) {
      const jiraKey = String(backlogItem.key || "").trim().toUpperCase()
      if (!jiraKey || seen.has(jiraKey)) continue
      if (isEpicIssueType(backlogItem.issue_type) || isSubtaskIssueType(backlogItem.issue_type)) continue
      seen.add(jiraKey)
      suggestions.push(jiraKey)
    }

    for (const task of allTasks) {
      const jiraKey = String(task.jira_key || "").trim().toUpperCase()
      if (!jiraKey || seen.has(jiraKey)) continue

      const workflowTicket = workflowTicketsByKey.get(jiraKey)
      if (workflowTicket && (isEpicTicket(workflowTicket) || isSubtaskTicket(workflowTicket))) {
        continue
      }

      seen.add(jiraKey)
      suggestions.push(jiraKey)
    }

    return suggestions
  }, [allTasks, assigneeFilteredBacklog, sharedWorkflowTickets])
  const jiraDestinationColumns = useMemo(
    () =>
      Array.from(
        new Set(
          sharedWorkflowKanbanColumns
            .map((column) => (column.name || "").trim())
            .filter(Boolean)
        )
      ),
    [sharedWorkflowKanbanColumns]
  )
  const dependencyOptions = useMemo<PipelineDependencyOption[]>(() => {
    const options: PipelineDependencyOption[] = []
    const seen = new Set<string>()
    const activeTaskKey = normalizeDependencyKey(pendingWorkspaceAction?.jiraKey || "")

    const pushOption = (option: PipelineDependencyOption) => {
      const normalizedKey = normalizeDependencyKey(option.key)
      if (!normalizedKey || normalizedKey === activeTaskKey || seen.has(normalizedKey)) return
      seen.add(normalizedKey)
      options.push({
        key: normalizedKey,
        label: option.label,
        source: option.source,
      })
    }

    for (const backlogItem of assigneeFilteredBacklog) {
      const key = normalizeDependencyKey(backlogItem.key || "")
      const source = backlogItem.task_source === "spec" ? "spec" : "ticket"
      pushOption({
        key,
        label: backlogItem.title || key,
        source,
      })
    }

    for (const task of allTasks) {
      if (task.status === "complete") continue
      pushOption({
        key: normalizeDependencyKey(task.jira_key || ""),
        label: task.title || task.jira_key,
        source: task.task_source === "spec" ? "spec" : "ticket",
      })
    }

    for (const ticket of sharedWorkflowTickets) {
      if (isWorkflowTicketCompleted(ticket.status)) continue
      pushOption({
        key: normalizeDependencyKey(ticket.key || ""),
        label: ticket.summary || ticket.key || "",
        source: issueTypeText(ticket.issue_type).includes("spec") ? "spec" : "ticket",
      })
    }

    return options
  }, [allTasks, assigneeFilteredBacklog, pendingWorkspaceAction?.jiraKey, sharedWorkflowTickets])
  const {
    workspaces,
    isLoading: isLoadingWorkspaces,
    error: workspacesError,
  } = useWorkspaces()
  useEffect(() => {
    setBreadcrumbs([
      { label: "Dashboard", href: "/" },
      { label: "Pipelines" },
    ])
  }, [setBreadcrumbs])

  useEffect(() => {
    if (typeof window === "undefined") return
    const saved = window.localStorage.getItem(PIPELINES_JIRA_DESTINATION_PREFERENCE_KEY)
    setPreferredJiraCompleteColumnName((saved || "").trim())
  }, [])

  const handleJiraCompleteColumnNameChange = useCallback((value: string) => {
    const next = value.trim()
    setJiraCompleteColumnNameInput(next)
    setPreferredJiraCompleteColumnName(next)
    if (typeof window !== "undefined") {
      window.localStorage.setItem(PIPELINES_JIRA_DESTINATION_PREFERENCE_KEY, next)
    }
  }, [])

  const resolveDependencyBranchOverride = useCallback(
    (dependencyKey: string) => {
      const normalizedDependencyKey = normalizeDependencyKey(dependencyKey)
      if (!normalizedDependencyKey) return ""

      const dependencyTask = allTasks.find(
        (task) => normalizeDependencyKey(task.jira_key || "") === normalizedDependencyKey
      )

      if (!dependencyTask) {
        return normalizedDependencyKey
      }

      const dependencyTaskBranch = String(dependencyTask.starting_git_branch_override || "").trim()
      if (dependencyTaskBranch) {
        const normalizedTaskKey = normalizeDependencyKey(dependencyTask.jira_key || "")
        const normalizedTaskBranch = normalizeDependencyKey(dependencyTaskBranch)
        const normalizedDefaultPipelineBranch = normalizeDependencyKey(gitDefaultWorkingBranch || "")
        const isGenericDefaultBranch =
          normalizedTaskBranch === "MAIN"
          || normalizedTaskBranch === "__ACTIVE_WORKSPACE_BRANCH__"
          || (normalizedDefaultPipelineBranch && normalizedTaskBranch === normalizedDefaultPipelineBranch)

        if (!isGenericDefaultBranch) {
          return dependencyTaskBranch
        }

        if (normalizedTaskKey) {
          return normalizedTaskKey
        }
      }

      return normalizeDependencyKey(dependencyTask.jira_key || "") || normalizedDependencyKey
    },
    [allTasks, gitDefaultWorkingBranch]
  )

  const openWorkspacePicker = useCallback(
    (action: PipelineWorkspaceAction) => {
      setPendingWorkspaceAction(action)
      didAutoPrefillQueueBranchRef.current = false
      const preferredPath =
        (action.workspacePath || "").trim() ||
        workspaces.find((workspace) => workspace.is_active === 1)?.path ||
        workspaces[0]?.path ||
        ""
      setWorkspaceInput(preferredPath)
      setJiraCompleteColumnNameInput(
        action.taskSource === "spec"
          ? ""
          : (action.jiraCompleteColumnName || "").trim() || preferredJiraCompleteColumnName
      )
      const nextTaskRelation = action.defaultTaskType === "subtask" ? "subtask" : "task"
      const defaultDependencyKey = normalizeDependencyKey(action.defaultDependencyKey || "")
      let nextStartingGitBranchOverride = String(action.startingGitBranchOverride || "").trim()
      if (action.taskSource === "spec" && nextTaskRelation === "subtask" && defaultDependencyKey) {
        const dependencyBranch = resolveDependencyBranchOverride(defaultDependencyKey)
        if (dependencyBranch) {
          nextStartingGitBranchOverride = dependencyBranch
        }
      }
      setStartingGitBranchOverrideInput(nextStartingGitBranchOverride)
      setTaskRelationInput(nextTaskRelation)
      setDependencyKeyInput(
        nextTaskRelation === "subtask" ? defaultDependencyKey : ""
      )
      setGitBranchOptions([])
      setGitCurrentBranch(null)
      setGitBranchesError(null)
      setWorkspaceSetupOpen(true)
    },
    [preferredJiraCompleteColumnName, resolveDependencyBranchOverride, workspaces]
  )

  const closeWorkspaceSetup = useCallback(() => {
    setWorkspaceSetupOpen(false)
    setPendingWorkspaceAction(null)
    didAutoPrefillQueueBranchRef.current = false
    setJiraCompleteColumnNameInput("")
    setStartingGitBranchOverrideInput("")
    setTaskRelationInput("task")
    setDependencyKeyInput("")
    setGitBranchOptions([])
    setGitCurrentBranch(null)
    setGitBranchesError(null)
  }, [])

  const enforceTaskAfterDependencies = useCallback(
    async (taskId: string) => {
      const latestCurrentTasks = usePipelinesStore.getState().state?.columns?.current ?? []
      const task = latestCurrentTasks.find((t) => t.id === taskId)

      if (!task || !task.dependencies.length) return

      const taskIdx = latestCurrentTasks.indexOf(task)
      const depIds = new Set(task.dependencies.map((d) => d.depends_on_task_id))

      let lastDepIdx = -1

      latestCurrentTasks.forEach((t, i) => {
        if (depIds.has(t.id)) {
          lastDepIdx = Math.max(lastDepIdx, i)
        }
      })

      if (lastDepIdx === -1 || taskIdx > lastDepIdx) return

      const depTask = latestCurrentTasks[lastDepIdx]
      const reordered = latestCurrentTasks.filter((t) => t.id !== taskId)
      const insertIdx = reordered.indexOf(depTask) + 1

      reordered.splice(insertIdx, 0, task)
      await reorderCurrent(reordered.map((t) => t.id))
    },
    [reorderCurrent]
  )

  const commitWorkspaceAction = useCallback(async () => {
    if (!pendingWorkspaceAction) return

    const path = workspaceInput.trim()
    if (!path) return
    const jiraCompleteColumnName =
      pendingWorkspaceAction.taskSource === "spec"
        ? ""
        : jiraCompleteColumnNameInput.trim() || ""
    const activeTaskKey = normalizeDependencyKey(pendingWorkspaceAction.jiraKey || "")
    const normalizedDependencyKey = normalizeDependencyKey(dependencyKeyInput)
    const isSubtask = taskRelationInput === "subtask"
    const effectiveDependencyKey =
      isSubtask && normalizedDependencyKey && normalizedDependencyKey !== activeTaskKey
        ? normalizedDependencyKey
        : ""
    if (isSubtask && !effectiveDependencyKey) {
      throw new Error("Select a dependency before queuing a subtask.")
    }

    const selectedDependency = dependencyOptions.find((option) => option.key === effectiveDependencyKey)
    const effectiveDependencyKeys = effectiveDependencyKey ? [effectiveDependencyKey] : []
    const taskIdByKey = new Map(
      allTasks.map((task) => [normalizeDependencyKey(task.jira_key || ""), task.id] as const)
    )
    const resolvedDependencyTaskIds = Array.from(
      new Set(
        effectiveDependencyKeys
          .map((key) => taskIdByKey.get(key))
          .filter((taskId): taskId is string => Boolean(taskId))
      )
    )
    const specWithNoDeps = pendingWorkspaceAction.taskSource === "spec" && effectiveDependencyKeys.length === 0
    const dependencyTaskIdsForRequest = specWithNoDeps
      ? []
      : resolvedDependencyTaskIds.length > 0
        ? resolvedDependencyTaskIds
        : undefined

    usePipelinesStore.getState().setIsMutating(true)

    try {
      if (pendingWorkspaceAction.taskSource === "spec") {
        const params = new URLSearchParams()
        params.set("workspace_path", path)
        const endpoint = `/api/spec-tasks/${encodeURIComponent(activeTaskKey)}/dependencies`
        const response = await fetch(buildApiUrl(`${endpoint}?${params.toString()}`), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dependency_mode: isSubtask ? "subtask" : "independent",
            parent_spec_name:
              isSubtask && selectedDependency?.source === "spec" && effectiveDependencyKey
                ? effectiveDependencyKey
                : undefined,
            depends_on: effectiveDependencyKeys,
          }),
        })
        const patchPayload = (await response.json().catch(() => ({}))) as { detail?: string }
        if (!response.ok) {
          throw new Error(patchPayload.detail || `Failed to update SPEC dependencies (${response.status})`)
        }
      }

      if (pendingWorkspaceAction.kind === "queue") {
        await queueTask(
          pendingWorkspaceAction.jiraKey,
          path,
          "codex",
          jiraCompleteColumnName,
          startingGitBranchOverrideInput.trim() || "",
          dependencyTaskIdsForRequest,
          taskRelationInput,
          { manageMutating: false }
        )
      } else {
        await moveTask(
          pendingWorkspaceAction.taskId,
          "current",
          path,
          "codex",
          jiraCompleteColumnName,
          startingGitBranchOverrideInput.trim() || "",
          dependencyTaskIdsForRequest,
          taskRelationInput,
          { manageMutating: false }
        )
      }

      if (effectiveDependencyKey) {
        const latestCurrentTasks = usePipelinesStore.getState().state?.columns?.current ?? []
        const activeJiraKey = normalizeDependencyKey(pendingWorkspaceAction.jiraKey)
        const newTask = latestCurrentTasks.find((t) => normalizeDependencyKey(t.jira_key) === activeJiraKey)

        if (newTask) {
          await enforceTaskAfterDependencies(newTask.id)
        }
      }

      closeWorkspaceSetup()
    } catch (err) {
      usePipelinesStore.getState().setError(err instanceof Error ? err.message : "Operation failed")
    } finally {
      usePipelinesStore.getState().setIsMutating(false)
    }
  }, [
    closeWorkspaceSetup,
    enforceTaskAfterDependencies,
    jiraCompleteColumnNameInput,
    moveTask,
    pendingWorkspaceAction,
    queueTask,
    startingGitBranchOverrideInput,
    dependencyKeyInput,
    taskRelationInput,
    dependencyOptions,
    allTasks,
    workspaceInput,
  ])

  useEffect(() => {
    if (!workspaceSetupOpen) return

    const workspacePath = workspaceInput.trim()
    if (!workspacePath) {
      setGitBranchOptions([])
      setGitCurrentBranch(null)
      setGitBranchesError(null)
      setIsLoadingGitBranches(false)
      return
    }

    let cancelled = false
    const controller = new AbortController()

    const loadBranches = async () => {
      setIsLoadingGitBranches(true)
      setGitBranchesError(null)
      try {
        const response = await fetch(
          buildApiUrl(`/api/git/branches?workspace=${encodeURIComponent(workspacePath)}`),
          { signal: controller.signal }
        )
        const payload = (await response.json().catch(() => ({}))) as {
          detail?: string
          current?: string
          local?: string[]
          remote?: string[]
        }
        if (!response.ok) {
          throw new Error(payload?.detail || `Failed to load branches (${response.status})`)
        }
        if (cancelled) return

        const seen = new Set<string>()
        const nextOptions: string[] = []
        const pushBranch = (value: string) => {
          const normalized = value.trim()
          if (!normalized || normalized.includes("->") || seen.has(normalized)) return
          seen.add(normalized)
          nextOptions.push(normalized)
        }

        for (const branch of payload.local || []) pushBranch(String(branch))

        setGitCurrentBranch(String(payload.current || "").trim() || null)
        setGitBranchOptions(nextOptions)
      } catch (err) {
        if (cancelled) return
        const message =
          err instanceof Error && err.name === "AbortError"
            ? null
            : err instanceof Error
              ? err.message
              : "Failed to load branches"
        if (message) {
          setGitBranchOptions([])
          setGitCurrentBranch(null)
          setGitBranchesError(message)
        }
      } finally {
        if (!cancelled) setIsLoadingGitBranches(false)
      }
    }

    void loadBranches()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [workspaceInput, workspaceSetupOpen])

  useEffect(() => {
    if (!workspaceSetupOpen || !pendingWorkspaceAction || pendingWorkspaceAction.kind !== "queue") return
    if (didAutoPrefillQueueBranchRef.current) return

    const preconfiguredBranch = String(pendingWorkspaceAction.startingGitBranchOverride || "").trim()
    if (preconfiguredBranch) {
      didAutoPrefillQueueBranchRef.current = true
      return
    }

    if (startingGitBranchOverrideInput.trim()) {
      didAutoPrefillQueueBranchRef.current = true
      return
    }

    const activeWorkspaceBranch = String(gitCurrentBranch || "").trim()
    if (!activeWorkspaceBranch) return

    didAutoPrefillQueueBranchRef.current = true
    setStartingGitBranchOverrideInput(activeWorkspaceBranch)
  }, [gitCurrentBranch, pendingWorkspaceAction, startingGitBranchOverrideInput, workspaceSetupOpen])

  const {
    selectedTask,
    setSelectedTaskId,
    queueFromBacklog,
    reorderCurrentBefore,
    reorderCurrentToEnd,
  } = usePipelineBoardInteractions({
    currentTasks,
    allTasks,
    reorderCurrent,
    openWorkspacePicker,
  })

  const handleEditTaskDetails = useCallback(
    (task: PipelineTask) => {
      const taskIdById = new Map(allTasks.map((item) => [item.id, item] as const))
      const defaultDependencyTaskId = task.dependencies[0]?.depends_on_task_id
      const defaultDependencyKey = defaultDependencyTaskId
        ? normalizeDependencyKey(taskIdById.get(defaultDependencyTaskId)?.jira_key || "")
        : ""

      openWorkspacePicker({
        kind: "move",
        taskId: task.id,
        jiraKey: task.jira_key,
        taskSource: task.task_source,
        workspacePath: task.workspace_path,
        workflow: task.workflow,
        jiraCompleteColumnName: task.jira_complete_column_name || "",
        startingGitBranchOverride: task.starting_git_branch_override || "",
        defaultTaskType: task.task_relation === "subtask" ? "subtask" : "task",
        defaultDependencyKey,
      })
    },
    [allTasks, openWorkspacePicker]
  )

  const {
    startTime,
    setStartTime,
    endTime,
    setEndTime,
    heartbeatValue,
    setHeartbeatValue,
    heartbeatUnit,
    setHeartbeatUnit,
    maxRetries,
    setMaxRetries,
    handleSaveSettings,
  } = usePipelineSettingsForm({
    settings: state?.settings,
    onSave: updateSettings,
  })

  const handleStartPipelineShortly = useCallback(async () => {
    await triggerHeartbeatSoon(10)
  }, [triggerHeartbeatSoon])

  const handleTriggerNextTaskNow = useCallback(async () => {
    await triggerNextTaskNow()
  }, [triggerNextTaskNow])

  const handleEnableAutomation = useCallback(async () => {
    await setAutomationEnabled(true)
  }, [setAutomationEnabled])

  const handleDisableAutomation = useCallback(async () => {
    await setAutomationEnabled(false)
  }, [setAutomationEnabled])

  useEffect(() => {
    if (didBootstrapBacklog.current) return
    if (isLoading) return

    if (assigneeFilteredBacklog.length > 0) {
      didBootstrapBacklog.current = true
      return
    }

    didBootstrapBacklog.current = true
    void refreshBacklog().catch(() => {
      // Pipeline hook surfaces the error in store state.
    })
  }, [assigneeFilteredBacklog.length, isLoading, refreshBacklog])

  const handleDismissError = useCallback(() => {
    setLocalError(null)
    clearStoreError(null)
  }, [clearStoreError])

  const pageError = localError || error
  const hasSavedWorkspaces = workspaces.length > 0
  const hasCurrentWorkspace = workspacePath.trim().length > 0
  const showWorkspaceRequiredState = !isLoadingWorkspaces && (!hasSavedWorkspaces || !hasCurrentWorkspace)

  return (
    showWorkspaceRequiredState ? (
      <WorkspaceRequiredState
        description="Create a workspace and set it as the current workspace before running or managing pipelines."
      />
    ) : (
      <div className="flex flex-1 min-h-0 w-full">
        <div className="flex flex-1 min-h-0 flex-col gap-4 overflow-y-auto p-6">
            <PipelineHeader
              state={state}
              mode={mode}
              heartbeatCountdown={heartbeatCountdown}
            />

            <PipelineSettingsPanel
              startTime={startTime}
              setStartTime={setStartTime}
              endTime={endTime}
              setEndTime={setEndTime}
              heartbeatValue={heartbeatValue}
              setHeartbeatValue={setHeartbeatValue}
              heartbeatUnit={heartbeatUnit}
              setHeartbeatUnit={setHeartbeatUnit}
              maxRetries={maxRetries}
              setMaxRetries={setMaxRetries}
              automationEnabled={Boolean(state?.settings?.automation_enabled)}
              handleSaveSettings={handleSaveSettings}
              handleStartPipelineShortly={handleStartPipelineShortly}
              handleTriggerNextTaskNow={handleTriggerNextTaskNow}
              handleEnableAutomation={handleEnableAutomation}
              handleDisableAutomation={handleDisableAutomation}
              isMutating={isMutating}
              backlogWorkflowFilter={backlogWorkflowFilter}
              onBacklogWorkflowFilterChange={setBacklogWorkflowFilter}
            />

            <PipelinesPageStatus
              pageError={pageError}
              backlogCount={visibleBacklog.length}
              isLoading={isLoading}
              isMutating={isMutating}
              sharedWorkflowTicketsCount={sharedWorkflowTickets.length}
              sharedWorkflowWarning={sharedWorkflowWarning}
              onDismissError={handleDismissError}
            />

            <PipelinesRunningActivityBanner runningActivityLine={runningActivityLine} />

            <PipelineGitHandoffsPanel
              handoffs={debouncedHandoffs}
              isMutating={isMutating}
              onResolveHandoff={async (taskId, handoffId, reenableTask) => {
                await resolveTaskHandoff(taskId, handoffId, reenableTask)
              }}
              onKeepBlocked={async (taskId) => {
                await setTaskBypass(taskId, true, "Bypass retained while handoff is pending.")
              }}
              onError={setLocalError}
            />

            <PipelinesPageBoardSection
              state={state}
              isLoading={isLoading}
              isMutating={isMutating}
              backlog={visibleBacklog}
              currentTasks={currentTasks}
              runningTasks={runningTasks}
              completeTasks={completeTasks}
              trackedKeys={trackedKeys}
              onSelectTaskId={setSelectedTaskId}
              onQueueFromBacklog={queueFromBacklog}
              onReorderCurrentBefore={reorderCurrentBefore}
              onReorderCurrentToEnd={reorderCurrentToEnd}
              onMoveTaskToBacklog={async (taskId) => {
                await moveTask(taskId, "backlog")
              }}
              onReenableTask={async (taskId) => {
                await moveTask(taskId, "current")
                await enforceTaskAfterDependencies(taskId)
              }}
              onStopRunningTask={async (taskId) => {
                await moveTask(taskId, "stopped")
              }}
              onAdminForceResetTask={async (taskId) => {
                await adminForceResetTask(taskId)
              }}
              onAdminForceCompleteTask={async (taskId) => {
                await adminForceCompleteTask(taskId)
              }}
              onEditTaskDetails={handleEditTaskDetails}
              onActionError={setLocalError}
            />
        </div>

        <PipelineTaskDetailsSheet task={selectedTask} onOpenChange={(open) => !open && setSelectedTaskId(null)} />

        <PipelineTaskSetupDialog
          open={workspaceSetupOpen}
          pendingAction={pendingWorkspaceAction}
          workspacePath={workspaceInput}
          workspaces={workspaces}
          isLoadingWorkspaces={isLoadingWorkspaces}
          workspaceError={workspacesError}
          onWorkspacePathChange={setWorkspaceInput}
          jiraCompleteColumnName={jiraCompleteColumnNameInput}
          jiraDestinationColumns={jiraDestinationColumns}
          onJiraCompleteColumnNameChange={handleJiraCompleteColumnNameChange}
          startingGitBranchOverride={startingGitBranchOverrideInput}
          gitBranchOptions={gitBranchOptions}
          gitDefaultWorkingBranch={gitDefaultWorkingBranch}
          ticketBranchSuggestionKeys={pipelineTaskBranchSuggestionKeys}
          currentPipelineTicketKeys={currentPipelineTicketKeys}
          defaultToCustomBranchMode={
            pendingWorkspaceAction?.kind === "queue"
            && pendingWorkspaceAction?.taskSource === "spec"
            && taskRelationInput === "subtask"
            && Boolean(dependencyKeyInput.trim())
            && Boolean(startingGitBranchOverrideInput.trim())
          }
          gitCurrentBranch={gitCurrentBranch}
          isLoadingGitBranches={isLoadingGitBranches}
          gitBranchesError={gitBranchesError}
          onStartingGitBranchOverrideChange={setStartingGitBranchOverrideInput}
          taskRelation={taskRelationInput}
          onTaskRelationChange={setTaskRelationInput}
          dependencyKey={dependencyKeyInput}
          onDependencyKeyChange={setDependencyKeyInput}
          dependencyOptions={dependencyOptions}
          onClose={closeWorkspaceSetup}
          onConfirm={() => {
            setLocalError(null)
            void commitWorkspaceAction()
          }}
          isMutating={isMutating}
        />
      </div>
    )
  )
}
