import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import {
  type ColumnDef,
  type ColumnSort,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type VisibilityState,
  useReactTable,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  Ellipsis,
  ExternalLink,
  FileText,
  GitCommitHorizontal,
  Link2,
} from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog"
import { Label } from "@/shared/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/components/ui/select"
import { Tabs } from "@/shared/components/ui/tabs"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"
import {
  WorkflowProjectTab,
  WorkflowTableTab,
  WorkflowTasksHeaderSection,
  WorkflowTasksTabsHeader,
} from "@/features/workflow-tasks/components/WorkflowTasksPageSections"
import { useWorkflowTasksPageData } from "@/features/workflow-tasks/hooks/useWorkflowTasksPageData"
import { isEpicTicket, isSubtaskTicket, sortWorkflowEpicsByPriority } from "@/features/workflow-tasks/hooks/useWorkflowTasksSortedTickets"
import { useWorkflowTasksStore } from "@/features/workflow-tasks/store/useWorkflowTasksStore"
import type { WorkflowSpecTask, WorkflowTask } from "@/features/workflow-tasks/types"
import { Chip } from "@/shared/components/chip"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

const formatDate = (value?: string) => {
  if (!value) return "n/a"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const issueTypeLabelFor = (task: WorkflowTask, isSubtask: boolean, isEpic: boolean) => {
  const issueType = (task.issue_type || "").trim()
  if (issueType) return issueType
  if (isEpic) return "Epic"
  if (isSubtask) return "Subtask"
  return "Issue"
}

const issueUrlFor = (task: WorkflowTask, issueBaseUrl: string) => task.url || (issueBaseUrl ? `${issueBaseUrl}${task.key}` : "")
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)
type SpecBundleFileName = "requirements.md" | "design.md" | "tasks.md"

type SpecBundleFile = {
  fileName: SpecBundleFileName
  label: string
}

type SpecBuildStatus = 'generating' | 'generated' | 'pending' | 'failed' | 'complete'

type SpecTaskType = "task" | "subtask"

type SpecDependencyOption = {
  key: string
  label: string
  source: "spec" | "ticket"
}

type SpecBuildStatusEditable = "pending" | "complete"

const SPEC_BUNDLE_FILES: SpecBundleFile[] = [
  { fileName: "requirements.md", label: "Requirements" },
  { fileName: "design.md", label: "Design" },
  { fileName: "tasks.md", label: "Tasks" },
]

const SPEC_BUILD_STATUS_ORDER: Record<SpecBuildStatus, number> = {
  generating: 0,
  generated: 1,
  pending: 2,
  failed: 3,
  complete: 4,
}
const SPEC_DEPENDENCY_NONE_VALUE = "__spec_dependency_none__"

const specBuildStatusFor = (specTask: WorkflowSpecTask): SpecBuildStatus => {
  const rawStatus = String(specTask.status || '').trim().toLowerCase()

  if (
    rawStatus === 'generating' ||
    rawStatus === 'generated' ||
    rawStatus === 'pending' ||
    rawStatus === 'failed' ||
    rawStatus === 'complete'
  ) {
    return rawStatus
  }

  return 'pending'
}

const specDependencyModeFor = (specTask: WorkflowSpecTask) => {
  const rawMode = String(specTask.dependency_mode || "").trim().toLowerCase()
  if (rawMode === "parent" || rawMode === "subtask" || rawMode === "independent") {
    return rawMode
  }
  return "independent"
}

const specTaskTypeFor = (specTask: WorkflowSpecTask): SpecTaskType => {
  const mode = specDependencyModeFor(specTask)
  return mode === "subtask" ? "subtask" : "task"
}

const specDependsOnFor = (specTask: WorkflowSpecTask) => {
  const rawDependsOn = specTask.depends_on
  if (!Array.isArray(rawDependsOn)) return []
  const deduped: string[] = []
  const seen = new Set<string>()
  for (const item of rawDependsOn) {
    const normalized = String(item || "").trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    deduped.push(normalized)
  }
  return deduped
}

const normalizeDependencyKey = (value: string) => String(value || "").trim().toUpperCase()

const isWorkflowTicketCompleted = (task: WorkflowTask) => {
  const normalizedStatus = String(task.status || "").trim().toLowerCase()
  return (
    normalizedStatus.includes("done")
    || normalizedStatus.includes("complete")
    || normalizedStatus.includes("closed")
    || normalizedStatus.includes("resolved")
  )
}

const specBundleFileUrlFor = (task: WorkflowSpecTask, fileName: SpecBundleFileName) => {
  const trimmedSpecName = String(task.spec_name || "").trim()
  if (!trimmedSpecName) return ""

  const params = new URLSearchParams()
  const trimmedWorkspace = String(task.workspace_path || "").trim()
  if (trimmedWorkspace) {
    params.set("workspace_path", trimmedWorkspace)
  }

  const query = params.toString()
  const endpoint = `/api/sdd/specs/${encodeURIComponent(trimmedSpecName)}/files/${encodeURIComponent(fileName)}`
  return buildApiUrl(query ? `${endpoint}?${query}` : endpoint)
}

export default function WorkflowTasksPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const didAutoFetchRef = useRef(false)
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const {
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
    specTasks,
    isLoadingSpecTasks,
    isLoadingConfig,
    isFetching,
    issueBaseUrl,
    fetchTickets,
    loadSpecTasks,
  } = useWorkflowTasksPageData()

  const [sorting, setSorting] = useState<ColumnSort[]>([])
  const [epicSorting, setEpicSorting] = useState<ColumnSort[]>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [epicColumnVisibility, setEpicColumnVisibility] = useState<VisibilityState>({})
  const [specColumnVisibility, setSpecColumnVisibility] = useState<VisibilityState>({})
  const [globalFilter, setGlobalFilter] = useState("")
  const [epicGlobalFilter, setEpicGlobalFilter] = useState("")
  const [specGlobalFilter, setSpecGlobalFilter] = useState("")
  const [specSorting, setSpecSorting] = useState<ColumnSort[]>([])
  const activeTab = useWorkflowTasksStore((state) => state.activeTab)
  const setActiveTab = useWorkflowTasksStore((state) => state.setActiveTab)
  const [specDependencyTaskPendingEdit, setSpecDependencyTaskPendingEdit] = useState<WorkflowSpecTask | null>(null)
  const [specTaskTypeInput, setSpecTaskTypeInput] = useState<SpecTaskType>("task")
  const [specDependencyDependsOnInput, setSpecDependencyDependsOnInput] = useState("")
  const [specDependencyEditError, setSpecDependencyEditError] = useState<string | null>(null)
  const [isSavingSpecDependencies, setIsSavingSpecDependencies] = useState(false)
  const [specBuildTaskPendingEdit, setSpecBuildTaskPendingEdit] = useState<WorkflowSpecTask | null>(null)
  const [specBuildStatusInput, setSpecBuildStatusInput] = useState<SpecBuildStatusEditable>("pending")
  const [specBuildEditError, setSpecBuildEditError] = useState<string | null>(null)
  const [isSavingSpecBuild, setIsSavingSpecBuild] = useState(false)

  useEffect(() => {
    setBreadcrumbs([
      { label: "Dashboard", href: "/" },
      { label: "Workflow Tasks" },
    ])
  }, [setBreadcrumbs])

  useEffect(() => {
    if (didAutoFetchRef.current) return
    if (isLoadingConfig || isFetching || !canFetch) return

    didAutoFetchRef.current = true
    void fetchTickets().catch(() => {
      // Hook state surfaces the error message.
    })
  }, [canFetch, fetchTickets, isFetching, isLoadingConfig])

  useEffect(() => {
    const searchParams = new URLSearchParams(location.search)
    const requestedTab = searchParams.get("tab")
    if (requestedTab === "project" || requestedTab === "tasks" || requestedTab === "epics" || requestedTab === "specs") {
      setActiveTab(requestedTab)
    }
  }, [location.search, setActiveTab])

  const tasksWithoutEpics = useMemo(() => {
    const nonEpics = tickets.filter((task) => !isEpicTicket(task))

    if (!assigneeFilter) return nonEpics

    if (assigneeFilter === '__unassigned__') {
      return nonEpics.filter((task) => !task.assignee || task.assignee.trim() === '')
    }

    return nonEpics.filter((task) => task.assignee === assigneeFilter)
  }, [assigneeFilter, tickets])
  const epicTasks = useMemo(
    () => sortWorkflowEpicsByPriority(tickets),
    [tickets]
  )
  const sprintTickets = useMemo(
    () => currentSprint?.tickets || [],
    [currentSprint]
  )
  const sprintStatusCounts = useMemo(
    () => currentSprint?.counts_by_status || [],
    [currentSprint]
  )
  const sprintTicketKeys = useMemo(
    () => sprintTickets.map((ticket) => ticket.key).filter(Boolean),
    [sprintTickets]
  )
  const sprintTicketKeyPreview = useMemo(
    () => sprintTicketKeys.slice(0, 3),
    [sprintTicketKeys]
  )
  const sprintTicketKeyOverflowCount = Math.max(0, sprintTicketKeys.length - sprintTicketKeyPreview.length)
  const maxKanbanCount = useMemo(
    () => kanbanColumns.reduce((max, column) => Math.max(max, Number(column.ticket_count) || 0), 0),
    [kanbanColumns]
  )
  const hasExactKanbanConfig = useMemo(
    () => kanbanColumns.some((column) => column.source === "jira_rest_board_configuration"),
    [kanbanColumns]
  )
  const shouldShowWorkflowTaskSummary = activeTab !== "specs"
  const specDependencyOptionsForEdit = useMemo<SpecDependencyOption[]>(() => {
    const options: SpecDependencyOption[] = []
    const seen = new Set<string>()
    const currentSpecKey = normalizeDependencyKey(specDependencyTaskPendingEdit?.spec_name || "")

    for (const specTask of specTasks) {
      if (specBuildStatusFor(specTask) === "complete") continue
      const specKey = normalizeDependencyKey(specTask.spec_name || "")
      if (!specKey || specKey === currentSpecKey || seen.has(specKey)) continue
      seen.add(specKey)
      options.push({
        key: specKey,
        label: specTask.summary || specTask.spec_name || specKey,
        source: "spec",
      })
    }

    for (const ticket of tickets) {
      if (isWorkflowTicketCompleted(ticket)) continue
      const ticketKey = normalizeDependencyKey(ticket.key || "")
      if (!ticketKey || ticketKey === currentSpecKey || seen.has(ticketKey)) continue
      seen.add(ticketKey)
      options.push({
        key: ticketKey,
        label: ticket.summary || ticket.key || ticketKey,
        source: "ticket",
      })
    }

    return options
  }, [specDependencyTaskPendingEdit?.spec_name, specTasks, tickets])
  const openSpecDependencyEditor = useCallback((specTask: WorkflowSpecTask) => {
    const normalizedDependsOn = specDependsOnFor(specTask)
      .map((item) => normalizeDependencyKey(item))
      .filter(Boolean)
    const normalizedParentSpecName = normalizeDependencyKey(specTask.parent_spec_name || "")
    const initialDependency = normalizedDependsOn[0] || normalizedParentSpecName || ""
    setSpecDependencyTaskPendingEdit(specTask)
    setSpecTaskTypeInput(specTaskTypeFor(specTask))
    setSpecDependencyDependsOnInput(initialDependency)
    setSpecDependencyEditError(null)
  }, [])

  const resetSpecDependencyEditor = () => {
    if (isSavingSpecDependencies) return
    setSpecDependencyTaskPendingEdit(null)
    setSpecTaskTypeInput("task")
    setSpecDependencyDependsOnInput("")
    setSpecDependencyEditError(null)
  }

  const saveSpecDependencies = async () => {
    if (!specDependencyTaskPendingEdit || isSavingSpecDependencies) return

    const normalizedSpecName = normalizeDependencyKey(specDependencyTaskPendingEdit.spec_name || "")
    if (!normalizedSpecName) return

    const normalizedDependencyKey = normalizeDependencyKey(specDependencyDependsOnInput)
    const normalizedDependencyMode = specTaskTypeInput === "subtask" ? "subtask" : "independent"
    const effectiveDependencyKey =
      normalizedDependencyMode === "subtask" && normalizedDependencyKey && normalizedDependencyKey !== normalizedSpecName
        ? normalizedDependencyKey
        : ""
    if (normalizedDependencyMode === "subtask" && !effectiveDependencyKey) {
      setSpecDependencyEditError("Select a dependency for this subtask.")
      return
    }

    const selectedDependency = specDependencyOptionsForEdit.find((option) => option.key === effectiveDependencyKey)
    const effectiveParentSpecName = selectedDependency?.source === "spec" ? effectiveDependencyKey : ""
    const effectiveDependencyKeys = effectiveDependencyKey ? [effectiveDependencyKey] : []

    setSpecDependencyEditError(null)
    setIsSavingSpecDependencies(true)
    try {
      const params = new URLSearchParams()
      const workspace = String(specDependencyTaskPendingEdit.workspace_path || "").trim()
      if (workspace) {
        params.set("workspace_path", workspace)
      }
      const query = params.toString()
      const endpoint = `/api/spec-tasks/${encodeURIComponent(normalizedSpecName)}/dependencies`
      const response = await fetch(buildApiUrl(query ? `${endpoint}?${query}` : endpoint), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dependency_mode: normalizedDependencyMode,
          parent_spec_name: effectiveParentSpecName || undefined,
          depends_on: effectiveDependencyKeys,
        }),
      })
      const payload = (await response.json().catch(() => ({}))) as { detail?: string }
      if (!response.ok) {
        throw new Error(payload.detail || `Failed to update dependencies (${response.status})`)
      }

      await loadSpecTasks()
      setSpecDependencyTaskPendingEdit(null)
    } catch (err) {
      setSpecDependencyEditError(err instanceof Error ? err.message : "Failed to update dependencies")
    } finally {
      setIsSavingSpecDependencies(false)
    }
  }

  const openSpecBuildEditor = useCallback((specTask: WorkflowSpecTask) => {
    const currentStatus = specBuildStatusFor(specTask)
    const initialStatus: SpecBuildStatusEditable = currentStatus === "complete" ? "complete" : "pending"
    setSpecBuildTaskPendingEdit(specTask)
    setSpecBuildStatusInput(initialStatus)
    setSpecBuildEditError(null)
  }, [])

  const resetSpecBuildEditor = useCallback(() => {
    if (isSavingSpecBuild) return
    setSpecBuildTaskPendingEdit(null)
    setSpecBuildStatusInput("pending")
    setSpecBuildEditError(null)
  }, [isSavingSpecBuild])

  const saveSpecBuildStatus = useCallback(async () => {
    if (!specBuildTaskPendingEdit || isSavingSpecBuild) return

    const trimmedSpecName = String(specBuildTaskPendingEdit.spec_name || "").trim()
    if (!trimmedSpecName) return

    setSpecBuildEditError(null)
    setIsSavingSpecBuild(true)

    try {
      const params = new URLSearchParams()
      const workspace = String(specBuildTaskPendingEdit.workspace_path || "").trim()
      if (workspace) {
        params.set("workspace_path", workspace)
      }

      const query = params.toString()
      const endpoint = `/api/spec-tasks/${encodeURIComponent(trimmedSpecName)}/status`
      const response = await fetch(buildApiUrl(query ? `${endpoint}?${query}` : endpoint), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: specBuildStatusInput,
        }),
      })
      const payload = (await response.json().catch(() => ({}))) as { detail?: string }

      if (!response.ok) {
        throw new Error(payload.detail || `Failed to update build status (${response.status})`)
      }

      await loadSpecTasks()
      setSpecBuildTaskPendingEdit(null)
    } catch (err) {
      setSpecBuildEditError(err instanceof Error ? err.message : "Failed to update build status")
    } finally {
      setIsSavingSpecBuild(false)
    }
  }, [isSavingSpecBuild, loadSpecTasks, specBuildStatusInput, specBuildTaskPendingEdit])

  const columns = useMemo<ColumnDef<WorkflowTask>[]>(
    () => [
      {
        accessorKey: "key",
        header: "Key",
        cell: ({ row }) => {
          const task = row.original
          const isSubtask = isSubtaskTicket(task)
          return (
            <div className="flex items-center gap-2">
              {isSubtask ? <GitCommitHorizontal className="text-muted-foreground size-3.5" /> : null}
              <span className="font-medium">{task.key}</span>
            </div>
          )
        },
      },
      {
        accessorKey: "summary",
        header: "Summary",
        cell: ({ row }) => <span>{row.original.summary || "n/a"}</span>,
      },
      {
        accessorKey: "status",
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Status
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => row.original.status || "n/a",
      },
      {
        id: "type",
        header: "Type",
        cell: ({ row }) => {
          const task = row.original
          return issueTypeLabelFor(task, isSubtaskTicket(task), isEpicTicket(task))
        },
      },
      {
        accessorKey: "assignee",
        header: "Assignee",
        cell: ({ row }) => row.original.assignee || "n/a",
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => row.original.priority || "n/a",
      },
      {
        accessorKey: "updated",
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Updated
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => formatDate(row.original.updated),
        sortingFn: (rowA, rowB) => {
          const first = Date.parse(rowA.original.updated || "")
          const second = Date.parse(rowB.original.updated || "")
          const a = Number.isNaN(first) ? 0 : first
          const b = Number.isNaN(second) ? 0 : second
          return a - b
        },
      },
      {
        id: "open",
        enableSorting: false,
        enableHiding: false,
        header: () => <div className="text-right">Open</div>,
        cell: ({ row }) => {
          const url = issueUrlFor(row.original, issueBaseUrl)
          return (
            <div
              className="text-right"
              onClick={(event) => {
                event.stopPropagation()
              }}
            >
              {url ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Open ${row.original.key} in Jira`}
                  onClick={() => window.open(url, "_blank")}
                >
                  <ExternalLink className="size-4" />
                </Button>
              ) : null}
            </div>
          )
        },
      },
    ],
    [issueBaseUrl]
  )

  const specColumns = useMemo<ColumnDef<WorkflowSpecTask>[]>(
    () => [
      {
        accessorKey: "spec_name",
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Spec
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => <span className="font-medium">{row.original.spec_name || "n/a"}</span>,
      },
      {
        accessorKey: "summary",
        header: "Summary",
        cell: ({ row }) => <span>{row.original.summary || "n/a"}</span>,
      },
      {
        id: "dependency_mode",
        accessorFn: (row) => specTaskTypeFor(row),
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Type
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => {
          const taskType = specTaskTypeFor(row.original)
          const color = taskType === "subtask" ? "warning" : "grey"
          return (
            <Chip color={color} variant="outline">
              {taskType === "subtask" ? "SUBTASK" : "TASK"}
            </Chip>
          )
        },
      },
      {
        id: "depends_on",
        accessorFn: (row) => specDependsOnFor(row).join(" "),
        header: "Depends On",
        cell: ({ row }) => {
          const dependsOn = specDependsOnFor(row.original)
          return (
            <div
              className="flex max-w-[20rem] flex-col gap-1.5"
              onClick={(event) => {
                event.stopPropagation()
              }}
            >
              <div className="flex flex-wrap gap-1">
                {dependsOn.length === 0 ? (
                  <span className="text-muted-foreground text-xs">n/a</span>
                ) : (
                  dependsOn.slice(0, 1).map((dependencyKey) => (
                    <Chip key={`${row.original.id}-${dependencyKey}`} color="info" variant="outline">
                      {dependencyKey}
                    </Chip>
                  ))
                )}
              </div>
              <Button
                type="button"
                size="xs"
                variant="outline"
                className="w-fit"
                onClick={() => {
                  openSpecDependencyEditor(row.original)
                }}
              >
                <Link2 className="size-3" />
                Configure
              </Button>
            </div>
          )
        },
      },
      {
        id: "build_status",
        accessorFn: (row) => specBuildStatusFor(row),
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Build
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => {
          const buildStatus = specBuildStatusFor(row.original)

          const chipColor = {
            generating: 'info',
            generated: 'grey',
            pending: 'warning',
            failed: 'error',
            complete: 'success',
          }[buildStatus] as 'info' | 'grey' | 'warning' | 'error' | 'success'

          const chipLabel = {
            generating: 'Generating',
            generated: 'Generated',
            pending: 'Pending',
            failed: 'Failed',
            complete: 'Complete',
          }[buildStatus]

          return (
            <Chip
              color={chipColor}
              variant={buildStatus === 'complete' ? 'filled' : 'outline'}
            >
              {chipLabel}
            </Chip>
          )
        },
        sortingFn: (rowA, rowB) => {
          const a = specBuildStatusFor(rowA.original)
          const b = specBuildStatusFor(rowB.original)
          return SPEC_BUILD_STATUS_ORDER[a] - SPEC_BUILD_STATUS_ORDER[b]
        },
      },
      {
        accessorKey: "spec_path",
        header: "Spec Path",
        cell: ({ row }) => {
          const specPath = row.original.spec_path || "n/a"

          return (
            <div className="flex max-w-[30rem] flex-col gap-2">
              <span className="block truncate text-xs opacity-50" title={specPath}>
                {specPath}
              </span>

              <div
                className="flex flex-wrap items-center gap-1.5"
                onClick={(event) => {
                  event.stopPropagation()
                }}
              >
                {SPEC_BUNDLE_FILES.map((bundleFile) => {
                  const fileUrl = specBundleFileUrlFor(row.original, bundleFile.fileName)
                  if (!fileUrl) return null
                  return (
                    <Button
                      key={`${row.original.id}-${bundleFile.fileName}`}
                      type="button"
                      size="xs"
                      variant="warning"
                      className="h-6 rounded-full px-2 text-[11px]"
                      aria-label={`Open ${bundleFile.fileName} for ${row.original.spec_name}`}
                      onClick={() => {
                        window.open(fileUrl, "_blank", "noopener,noreferrer")
                      }}
                    >
                      <FileText className="size-3" />
                      {bundleFile.label}
                    </Button>
                  )
                })}
              </div>
            </div>
          )
        },
      },
      {
        accessorKey: "updated_at",
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Updated
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => formatDate(row.original.updated_at),
        sortingFn: (rowA, rowB) => {
          const first = Date.parse(rowA.original.updated_at || "")
          const second = Date.parse(rowB.original.updated_at || "")
          const a = Number.isNaN(first) ? 0 : first
          const b = Number.isNaN(second) ? 0 : second
          return a - b
        },
      },
      {
        accessorKey: "created_at",
        header: ({ column }) => (
          <Button
            type="button"
            variant="ghost"
            className="h-auto p-0 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Created
            <ArrowUpDown className="ml-2 size-4" />
          </Button>
        ),
        cell: ({ row }) => formatDate(row.original.created_at),
        sortingFn: (rowA, rowB) => {
          const first = Date.parse(rowA.original.created_at || "")
          const second = Date.parse(rowB.original.created_at || "")
          const a = Number.isNaN(first) ? 0 : first
          const b = Number.isNaN(second) ? 0 : second
          return a - b
        },
      },
      {
        id: "actions",
        enableSorting: false,
        enableHiding: false,
        header: () => <div className="text-right">More</div>,
        cell: ({ row }) => (
          <div
            className="flex justify-end"
            onClick={(event) => {
              event.stopPropagation()
            }}
          >
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Open actions for ${row.original.spec_name}`}
                >
                  <Ellipsis className="size-4" />
                </Button>
              </DropdownMenuTrigger>

              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    openSpecBuildEditor(row.original)
                  }}
                >
                  Edit Build
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ),
      },
    ],
    [openSpecBuildEditor, openSpecDependencyEditor]
  )

  const table = useReactTable({
    data: tasksWithoutEpics,
    columns,
    state: {
      sorting,
      columnVisibility,
      globalFilter,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  })

  const epicsTable = useReactTable({
    data: epicTasks,
    columns,
    state: {
      sorting: epicSorting,
      columnVisibility: epicColumnVisibility,
      globalFilter: epicGlobalFilter,
    },
    onSortingChange: setEpicSorting,
    onColumnVisibilityChange: setEpicColumnVisibility,
    onGlobalFilterChange: setEpicGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  })

  const specsTable = useReactTable({
    data: specTasks,
    columns: specColumns,
    state: {
      sorting: specSorting,
      columnVisibility: specColumnVisibility,
      globalFilter: specGlobalFilter,
    },
    onSortingChange: setSpecSorting,
    onColumnVisibilityChange: setSpecColumnVisibility,
    onGlobalFilterChange: setSpecGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  })

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          if (value === "project" || value === "tasks" || value === "epics" || value === "specs") {
            setActiveTab(value)
          }
        }}
        className="flex min-h-0 flex-1 flex-col gap-0"
      >
        <WorkflowTasksTabsHeader activeTab={activeTab} />

        <div className="flex min-h-0 w-full flex-1 overflow-hidden">
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
            <WorkflowTasksHeaderSection
              shouldRender={shouldShowWorkflowTaskSummary}
              projectKey={projectKey}
              boardNumber={boardNumber}
              assigneeFilter={assigneeFilter}
              jiraUsers={jiraUsers}
              onProjectKeyChange={setProjectKey}
              onBoardNumberChange={setBoardNumber}
              onAssigneeFilterChange={(value) => { void saveAssigneeFilter(value) }}
              onFetchUsers={() => { void fetchJiraUsers() }}
              isFetchingUsers={isFetchingUsers}
              onBlurSave={() => {
                void saveJiraConfig(projectKey, boardNumber)
              }}
              canFetch={canFetch}
              isFetching={isFetching}
              isLoadingConfig={isLoadingConfig}
              onFetchTasks={() => {
                void saveJiraConfig(projectKey, boardNumber).then(() => fetchTickets())
              }}
              ticketsCount={tickets.length}
              tasksWithoutEpicsCount={tasksWithoutEpics.length}
              epicsCount={epicTasks.length}
              specsCount={specTasks.length}
              server={server}
              tool={tool}
              fetchedAt={fetchedAt}
              savedAt={savedAt}
              dbId={dbId}
              formatDate={formatDate}
            />

            {isLoadingConfig && tickets.length === 0 ? (
              <p className="text-muted-foreground text-sm">Loading workflow tasks config...</p>
            ) : (
              <>
                <WorkflowProjectTab
                  currentSprint={currentSprint}
                  sprintTicketsCount={sprintTickets.length}
                  sprintStatusCounts={sprintStatusCounts}
                  sprintTicketKeys={sprintTicketKeys}
                  sprintTicketKeyPreview={sprintTicketKeyPreview}
                  sprintTicketKeyOverflowCount={sprintTicketKeyOverflowCount}
                  kanbanColumns={kanbanColumns}
                  maxKanbanCount={maxKanbanCount}
                  hasExactKanbanConfig={hasExactKanbanConfig}
                  formatDate={formatDate}
                />

                <WorkflowTableTab
                  value="tasks"
                  title="Tasks & Subtasks"
                  table={table}
                  onRowClick={(row) => navigate(`/workflow-tasks/${encodeURIComponent(row.key)}`)}
                  emptyMessage="No tasks/subtasks returned yet."
                  searchPlaceholder="Search tasks/subtasks..."
                  globalFilter={globalFilter}
                  onGlobalFilterChange={setGlobalFilter}
                />

                <WorkflowTableTab
                  value="epics"
                  title="Epics"
                  table={epicsTable}
                  onRowClick={(row) => navigate(`/workflow-tasks/${encodeURIComponent(row.key)}`)}
                  emptyMessage="No epics returned yet."
                  searchPlaceholder="Search epics..."
                  globalFilter={epicGlobalFilter}
                  onGlobalFilterChange={setEpicGlobalFilter}
                />

                <WorkflowTableTab
                  value="specs"
                  title="Specs"
                  table={specsTable}
                  onRowClick={(row) => navigate(`/prompt/${encodeURIComponent(row.spec_name)}`)}
                  emptyMessage={isLoadingSpecTasks ? "Loading spec tasks..." : "No spec tasks added yet."}
                  searchPlaceholder="Search specs..."
                  globalFilter={specGlobalFilter}
                  onGlobalFilterChange={setSpecGlobalFilter}
                />
              </>
            )}
          </div>
        </div>
      </Tabs>

      <Dialog
        open={Boolean(specDependencyTaskPendingEdit)}
        onOpenChange={(nextOpen) => {
          if (isSavingSpecDependencies) return
          if (!nextOpen) {
            resetSpecDependencyEditor()
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Configure SPEC Task Type</DialogTitle>
            <DialogDescription>
              Choose whether this SPEC runs as a Task or Subtask. Subtasks must declare one upstream dependency.
            </DialogDescription>
          </DialogHeader>

          {specDependencyTaskPendingEdit ? (
            <div className="space-y-4">
              <div className="rounded-md border bg-muted/20 p-3 text-sm">
                <p className="font-medium">{specDependencyTaskPendingEdit.spec_name}</p>
                <p className="text-muted-foreground text-xs">{specDependencyTaskPendingEdit.summary || "No summary"}</p>
              </div>

              <div className="space-y-2">
                <Label className="text-muted-foreground text-xs">Type</Label>
                <Select
                  value={specTaskTypeInput}
                  onValueChange={(value) => {
                    if (value === "task" || value === "subtask") {
                      setSpecTaskTypeInput(value)
                      if (value === "task") {
                        setSpecDependencyDependsOnInput("")
                      }
                    }
                  }}
                  disabled={isSavingSpecDependencies}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select task type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="task">Task</SelectItem>
                    <SelectItem value="subtask">Subtask</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {specTaskTypeInput === "subtask" ? (
                <div className="space-y-2">
                  <Label className="text-muted-foreground text-xs">Depends On (Required)</Label>
                  <Select
                    value={specDependencyDependsOnInput || SPEC_DEPENDENCY_NONE_VALUE}
                    onValueChange={(value) => {
                      setSpecDependencyDependsOnInput(value === SPEC_DEPENDENCY_NONE_VALUE ? "" : value)
                    }}
                    disabled={isSavingSpecDependencies}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select parent task/spec" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={SPEC_DEPENDENCY_NONE_VALUE}>Select dependency</SelectItem>
                      {specDependencyOptionsForEdit.map((option) => (
                        <SelectItem key={`spec-dependency-option-${option.key}`} value={option.key}>
                          {option.key} · {option.source === "spec" ? "SPEC" : "TICKET"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {specDependencyDependsOnInput ? (
                    <p className="text-muted-foreground text-xs">Selected: {specDependencyDependsOnInput}</p>
                  ) : (
                    <p className="text-muted-foreground text-xs">Choose one open SPEC or ticket to depend on.</p>
                  )}
                </div>
              ) : null}

              {specDependencyEditError ? (
                <p className="text-rose-600 text-sm">{specDependencyEditError}</p>
              ) : null}
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isSavingSpecDependencies}
              onClick={resetSpecDependencyEditor}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={isSavingSpecDependencies || !specDependencyTaskPendingEdit}
              onClick={() => {
                void saveSpecDependencies()
              }}
            >
              {isSavingSpecDependencies ? "Saving..." : "Save Dependencies"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(specBuildTaskPendingEdit)}
        onOpenChange={(nextOpen) => {
          if (isSavingSpecBuild) return
          if (!nextOpen) {
            resetSpecBuildEditor()
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Build Status</DialogTitle>
            <DialogDescription>
              Move a SPEC between build states. Use this to move COMPLETE back to PENDING.
            </DialogDescription>
          </DialogHeader>

          {specBuildTaskPendingEdit ? (
            <div className="space-y-4">
              <div className="rounded-md border bg-muted/20 p-3 text-sm">
                <p className="font-medium">{specBuildTaskPendingEdit.spec_name}</p>
                <p className="text-muted-foreground text-xs">{specBuildTaskPendingEdit.summary || "No summary"}</p>
              </div>

              <div className="space-y-2">
                <Label className="text-muted-foreground text-xs">Build</Label>

                <Select
                  value={specBuildStatusInput}
                  onValueChange={(value) => {
                    if (value === "pending" || value === "complete") {
                      setSpecBuildStatusInput(value)
                    }
                  }}
                  disabled={isSavingSpecBuild}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select build status" />
                  </SelectTrigger>

                  <SelectContent>
                    <SelectItem value="pending">Pending</SelectItem>
                    <SelectItem value="complete">Complete</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {specBuildEditError ? <p className="text-sm text-rose-600">{specBuildEditError}</p> : null}
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isSavingSpecBuild}
              onClick={resetSpecBuildEditor}
            >
              Cancel
            </Button>

            <Button
              type="button"
              disabled={isSavingSpecBuild || !specBuildTaskPendingEdit}
              onClick={() => {
                void saveSpecBuildStatus()
              }}
            >
              {isSavingSpecBuild ? "Saving..." : "Save Build"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
