import * as React from 'react'
import {
  Columns3,
  FileText,
  FolderUp,
  PanelLeft,
  PanelRight,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import FileFolderDialog from '@/shared/components/file-folder-dialog'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Textarea } from '@/shared/components/ui/textarea'
import { WorkspaceRequiredState } from '@/shared/components/workspace-required-state'
import useFileFolderDialog from '@/shared/hooks/useFileFolderDialog'
import useAgentsStatus from '@/shared/hooks/useAgentsStatus'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import {
  AddSpecTaskDialog,
  PromptsPageColumns,
  PromptsPageHeader,
  type ColumnToggleOption,
  type PromptsColumnKey,
} from '@/features/prompts/components/PromptsPageSections'
import { usePromptsStore } from '@/features/prompts/store/prompts-store'
import { useSpecGenerationPoller } from '@/features/prompts/hooks/useSpecGenerationPoller'
import type { WorkspaceReferenceContextItem } from '@/features/prompts/utils/workspace-references'
import type {
  FileTreeSnapshot,
  PromptHistoryEntry,
  SaveState,
  SpecBundlePayload,
  SpecContentState,
} from '@/features/prompts/types'
import type { WorkflowSpecTask } from '@/features/workflow-tasks/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)
const TRACKED_SDD_AGENT_ROLES = ['planner', 'sdd_spec', 'code_builder', 'code_review'] as const

const INITIAL_SPEC_CONTENT: SpecContentState = {
  'requirements.md': '',
  'design.md': '',
  'tasks.md': '',
}

const initialSaveState: SaveState = {
  status: 'idle',
  message: 'Ready',
}

type PromptMode = 'create' | 'edit'

type SDDPlanResponse = {
  spec_name: string
  requirements: string
  design: string
  tasks: string
  history: PromptHistoryEntry[]
}

type SDDSaveResponse = {
  success: boolean
  file_path: string
  error?: string | null
}

type SDDSpecDeleteResponse = {
  success: boolean
  spec_name: string
  deleted_path: string
  error?: string | null
}

type SDDGenerateAsyncResponse = {
  spec_name: string
  spec_task_id: string
  status: 'generating'
}

type SpecTaskListResponse = {
  spec_tasks: WorkflowSpecTask[]
}

const SPEC_NAME_PATTERN = /^[A-Z0-9-]+$/

const COLUMN_ORDER: PromptsColumnKey[] = ['left', 'center', 'right']

const COLUMN_TOGGLE_OPTIONS: ColumnToggleOption[] = [
  { key: 'left', label: 'Output', icon: PanelLeft },
  { key: 'center', label: 'Editor', icon: Columns3 },
  { key: 'right', label: 'Agent', icon: PanelRight },
]

const nowIso = () => new Date().toISOString()

const isErrorLikeRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const asReadableErrorText = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const trimmed = value.trim()

    if (!trimmed) return null
    if (trimmed === '[object Object]' || trimmed === '[object Array]') return null

    return trimmed
  }

  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }

  if (Array.isArray(value)) {
    const messages = value
      .map((item) => asReadableErrorText(item))
      .filter((item): item is string => Boolean(item))

    if (messages.length === 0) return null

    return messages.join('; ')
  }

  if (isErrorLikeRecord(value)) {
    const msg = asReadableErrorText(value.msg)
    const loc = Array.isArray(value.loc)
      ? value.loc.map((segment) => String(segment)).filter(Boolean).join('.')
      : ''

    if (msg && loc) {
      return `${loc}: ${msg}`
    }

    if (msg) {
      return msg
    }

    const detail = asReadableErrorText(value.detail)

    if (detail) {
      return detail
    }

    const message = asReadableErrorText(value.message)

    if (message) {
      return message
    }

    const error = asReadableErrorText(value.error)

    if (error) {
      return error
    }

    try {
      const serialized = JSON.stringify(value)

      if (!serialized || serialized === '{}') return null

      return serialized
    } catch {
      return null
    }
  }

  return null
}

const resolveApiErrorMessage = (
  payload: { detail?: unknown; error?: unknown },
  fallback: string
) => {
  const detail = asReadableErrorText(payload.detail)

  if (detail) return detail

  const error = asReadableErrorText(payload.error)

  if (error) return error

  return fallback
}

const resolveUnknownErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error) {
    const message = asReadableErrorText(error.message)

    if (message) return message
  }

  const rawMessage = asReadableErrorText(error)

  if (rawMessage) return rawMessage

  return fallback
}

const historyEntry = (message: string, type: PromptHistoryEntry['type']): PromptHistoryEntry => ({
  id: `${type}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
  timestamp: nowIso(),
  message: asReadableErrorText(message) || '',
  type,
})

const normalizeHistoryEntries = (entries: PromptHistoryEntry[], existingIds?: Set<string>) => {
  const usedIds = new Set(existingIds || [])

  return entries.map((entry) => {
    const nextType: PromptHistoryEntry['type'] = entry.type === 'user' ? 'user' : 'system'
    const nextTimestamp = String(entry.timestamp || '').trim() || nowIso()
    const nextMessage = asReadableErrorText(entry.message) || ''
    const baseId = String(entry.id || '').trim() || `${nextType}-${nextTimestamp}`
    let resolvedId = baseId
    let suffix = 1

    while (usedIds.has(resolvedId)) {
      resolvedId = `${baseId}-${suffix}`
      suffix += 1
    }

    usedIds.add(resolvedId)

    return {
      id: resolvedId,
      timestamp: nextTimestamp,
      message: nextMessage,
      type: nextType,
    } satisfies PromptHistoryEntry
  })
}

const deriveSpecTaskSummary = (nextSpecName: string, nextSpecContent: SpecContentState) => {
  const normalizedSpecName = nextSpecName.trim()
  const fallback = normalizedSpecName ? `SDD spec task for ${normalizedSpecName}` : 'SDD spec task'
  const contentValues = [nextSpecContent['requirements.md'], nextSpecContent['design.md'], nextSpecContent['tasks.md']]

  for (const content of contentValues) {
    const lines = String(content || '').split('\n')

    for (const line of lines) {
      const trimmedLine = String(line || '').trim()

      if (!trimmedLine) continue

      if (trimmedLine.startsWith('#')) continue

      const normalizedLine = trimmedLine
        .replace(/^[-*]\s*\[[xX ]\]\s*/, '')
        .replace(/^[-*]\s*/, '')
        .trim()

      if (!normalizedLine) continue

      return normalizedLine.slice(0, 280)
    }
  }

  return fallback
}

export default function PromptsPage() {
  const navigate = useNavigate()
  const { specId } = useParams()
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const primaryWorkspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)
  const secondaryWorkspacePath = useDashboardSettingsStore((state) => state.secondaryWorkspacePath)
  const setSecondaryWorkspacePath = useDashboardSettingsStore((state) => state.setSecondaryWorkspacePath)
  const currentSpecId = usePromptsStore((state) => state.currentSpecId)
  const setCurrentSpecId = usePromptsStore((state) => state.setCurrentSpecId)
  const clearCurrentSpecId = usePromptsStore((state) => state.clearCurrentSpecId)
  const activeTab = usePromptsStore((state) => state.activeTab)
  const setActiveTab = usePromptsStore((state) => state.setActiveTab)
  const { agents, mode: agentsMode, isLoading: isAgentsLoading, error: agentsError } = useAgentsStatus()

  const [specName, setSpecName] = React.useState('')
  const [specContent, setSpecContent] = React.useState<SpecContentState>(INITIAL_SPEC_CONTENT)
  const [specTasks, setSpecTasks] = React.useState<WorkflowSpecTask[]>([])
  const [history, setHistory] = React.useState<PromptHistoryEntry[]>([])
  const [specNameError, setSpecNameError] = React.useState<string | null>(null)
  const [isHistoryVisible, setIsHistoryVisible] = React.useState(false)
  const [isAgentActivityVisible, setIsAgentActivityVisible] = React.useState(false)
  const [isLoadingSpecTasks, setIsLoadingSpecTasks] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isLoadingSpec, setIsLoadingSpec] = React.useState(false)
  const [isAddingSpecTask, setIsAddingSpecTask] = React.useState(false)
  const [isAddTaskDialogOpen, setIsAddTaskDialogOpen] = React.useState(false)
  const [specTaskSummary, setSpecTaskSummary] = React.useState('')
  const [deletingSpecName, setDeletingSpecName] = React.useState<string | null>(null)
  const [saveState, setSaveState] = React.useState<SaveState>(initialSaveState)
  const [specTasksError, setSpecTasksError] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [columnVisibility, setColumnVisibility] = React.useState<Record<PromptsColumnKey, boolean>>({
    left: true,
    center: true,
    right: true,
  })
  const [fileTreeSnapshot, setFileTreeSnapshot] = React.useState<FileTreeSnapshot>({
    root: null,
    expandedPaths: [],
  })
  const [secondaryFileTreeSnapshot, setSecondaryFileTreeSnapshot] = React.useState<FileTreeSnapshot>({
    root: null,
    expandedPaths: [],
  })
  const [isSecondaryWorkspaceDialogOpen, setIsSecondaryWorkspaceDialogOpen] = React.useState(false)
  const [isImportBundleDialogOpen, setIsImportBundleDialogOpen] = React.useState(false)
  const [isImportBundlePickerOpen, setIsImportBundlePickerOpen] = React.useState(false)
  const [isImportingBundle, setIsImportingBundle] = React.useState(false)
  const [importBundlePath, setImportBundlePath] = React.useState('')
  const [importSpecName, setImportSpecName] = React.useState('')
  const [importSummary, setImportSummary] = React.useState('')
  const [importBundleError, setImportBundleError] = React.useState<string | null>(null)

  const latestRouteSpecIdRef = React.useRef<string | null>(specId || null)
  const lastLoadedSpecIdRef = React.useRef<string | null>(null)
  const activeLoadRequestIdRef = React.useRef(0)
  const activeLoadAbortRef = React.useRef<AbortController | null>(null)

  const {
    columns: secondaryWorkspaceColumns,
    locations: secondaryWorkspaceLocations,
    selectedPath: selectedSecondaryWorkspacePath,
    activeDirectoryPath: activeSecondaryDirectoryPath,
    selectedByColumnPath: selectedSecondaryByColumnPath,
    showHidden: secondaryWorkspaceShowHidden,
    isLoading: isSecondaryWorkspaceLoading,
    isCreatingFolder: isSecondaryWorkspaceCreatingFolder,
    isRenamingEntry: isSecondaryWorkspaceRenamingEntry,
    error: secondaryWorkspaceError,
    openAtPath: openSecondaryWorkspaceAtPath,
    setShowHidden: setSecondaryWorkspaceShowHidden,
    selectLocation: selectSecondaryWorkspaceLocation,
    selectEntry: selectSecondaryWorkspaceEntry,
    createFolder: createSecondaryWorkspaceFolder,
    renameEntry: renameSecondaryWorkspaceEntry,
    deleteEntry: deleteSecondaryWorkspaceEntry,
  } = useFileFolderDialog({ mode: 'folder-only' })

  const {
    columns: importBundleColumns,
    locations: importBundleLocations,
    selectedPath: selectedImportBundlePath,
    activeDirectoryPath: activeImportDirectoryPath,
    selectedByColumnPath: selectedImportByColumnPath,
    showHidden: importBundleShowHidden,
    isLoading: isImportBundleLoading,
    isCreatingFolder: isImportBundleCreatingFolder,
    isRenamingEntry: isImportBundleRenamingEntry,
    error: importBundlePickerError,
    openAtPath: openImportBundleAtPath,
    setShowHidden: setImportBundleShowHidden,
    selectLocation: selectImportBundleLocation,
    selectEntry: selectImportBundleEntry,
    createFolder: createImportBundleFolder,
    renameEntry: renameImportBundleEntry,
    deleteEntry: deleteImportBundleEntry,
  } = useFileFolderDialog({ mode: 'folder-only' })

  React.useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Create A Spec', href: '/prompt' },
    ])
  }, [setBreadcrumbs])

  React.useEffect(() => {
    if (secondaryWorkspacePath?.trim()) return

    setSecondaryFileTreeSnapshot({
      root: null,
      expandedPaths: [],
    })
  }, [secondaryWorkspacePath])

  React.useEffect(() => {
    if (!isSecondaryWorkspaceDialogOpen) return

    const preferredPath = secondaryWorkspacePath?.trim() || primaryWorkspacePath.trim() || ''
    void openSecondaryWorkspaceAtPath(preferredPath)
  }, [
    isSecondaryWorkspaceDialogOpen,
    openSecondaryWorkspaceAtPath,
    primaryWorkspacePath,
    secondaryWorkspacePath,
  ])

  React.useEffect(() => {
    if (!isImportBundlePickerOpen) return

    const preferredPath = importBundlePath.trim() || primaryWorkspacePath.trim() || ''
    void openImportBundleAtPath(preferredPath)
  }, [importBundlePath, isImportBundlePickerOpen, openImportBundleAtPath, primaryWorkspacePath])

  React.useEffect(() => {
    latestRouteSpecIdRef.current = specId || null

    if (!specId) {
      lastLoadedSpecIdRef.current = null
    }
  }, [specId])

  React.useEffect(() => {
    return () => {
      if (!activeLoadAbortRef.current) return

      activeLoadAbortRef.current.abort()
      activeLoadAbortRef.current = null
    }
  }, [])

  React.useEffect(() => {
    if (!specId) {
      if (currentSpecId) {
        clearCurrentSpecId()
      }

      return
    }

    if (specId === currentSpecId) return

    setCurrentSpecId(specId)
  }, [clearCurrentSpecId, currentSpecId, setCurrentSpecId, specId])

  const resetDraft = React.useCallback(() => {
    if (activeLoadAbortRef.current) {
      activeLoadAbortRef.current.abort()
      activeLoadAbortRef.current = null
    }

    lastLoadedSpecIdRef.current = null
    setActiveTab('requirements.md')
    setSpecName('')
    setSpecContent(INITIAL_SPEC_CONTENT)
    setHistory([])
    setSaveState(initialSaveState)
    setError(null)
  }, [setActiveTab])

  const trackedAgents = React.useMemo(() => {
    const byRole = new Map(agents.map((agent) => [String(agent.role || '').toLowerCase(), agent]))

    return TRACKED_SDD_AGENT_ROLES
      .map((role) => byRole.get(role))
      .filter((agent): agent is NonNullable<typeof agent> => Boolean(agent))
  }, [agents])

  const loadSpecTasks = React.useCallback(async () => {
    const trimmedWorkspace = primaryWorkspacePath.trim()

    if (!trimmedWorkspace) {
      setSpecTasks([])
      setSpecTasksError(null)
      return
    }

    setIsLoadingSpecTasks(true)

    try {
      const params = new URLSearchParams()
      params.set('workspace_path', trimmedWorkspace)
      const response = await fetch(buildApiUrl(`/api/spec-tasks?${params.toString()}`))
      const payload = (await response.json().catch(() => ({}))) as Partial<SpecTaskListResponse> & {
        detail?: unknown
        error?: unknown
      }

      if (!response.ok) {
        throw new Error(resolveApiErrorMessage(payload, `Failed to load spec tasks (${response.status})`))
      }

      setSpecTasks(Array.isArray(payload.spec_tasks) ? payload.spec_tasks : [])
      setSpecTasksError(null)
    } catch (err) {
      setSpecTasks([])
      setSpecTasksError(resolveUnknownErrorMessage(err, 'Failed to load spec tasks'))
    } finally {
      setIsLoadingSpecTasks(false)
    }
  }, [primaryWorkspacePath])

  const loadSpecBundle = React.useCallback(
    async (nextSpecId: string) => {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      if (!trimmedWorkspace) return

      const requestId = activeLoadRequestIdRef.current + 1
      activeLoadRequestIdRef.current = requestId

      if (activeLoadAbortRef.current) {
        activeLoadAbortRef.current.abort()
      }

      const controller = new AbortController()
      activeLoadAbortRef.current = controller

      const isOutdatedRequest = () => {
        if (requestId !== activeLoadRequestIdRef.current) return true

        return latestRouteSpecIdRef.current !== nextSpecId
      }

      setIsLoadingSpec(true)
      setError(null)

      try {
        const params = new URLSearchParams()
        params.set('workspace_path', trimmedWorkspace)
        const response = await fetch(
          buildApiUrl(`/api/sdd/specs/${encodeURIComponent(nextSpecId)}?${params.toString()}`),
          { signal: controller.signal }
        )
        const payload = (await response.json().catch(() => ({}))) as Partial<SpecBundlePayload> & {
          detail?: unknown
          error?: unknown
        }

        if (isOutdatedRequest()) return

        if (!response.ok) {
          throw new Error(resolveApiErrorMessage(payload, `Failed to load spec bundle (${response.status})`))
        }

        const resolvedSpecName = String(payload.spec_name || nextSpecId).trim()
        lastLoadedSpecIdRef.current = nextSpecId
        setActiveTab('requirements.md')
        setSpecName(resolvedSpecName)
        setSpecContent({
          'requirements.md': String(payload.requirements || ''),
          'design.md': String(payload.design || ''),
          'tasks.md': String(payload.tasks || ''),
        })
        setHistory(normalizeHistoryEntries(Array.isArray(payload.history) ? payload.history : []))
        setSaveState(initialSaveState)
      } catch (err) {
        const errorName =
          typeof err === 'object' && err !== null && 'name' in err
            ? String((err as { name?: unknown }).name || '')
            : ''

        if (errorName === 'AbortError') return

        if (isOutdatedRequest()) return

        const message = resolveUnknownErrorMessage(err, 'Failed to load spec bundle')
        setError(message)
      } finally {
        const isActiveRequest = activeLoadRequestIdRef.current === requestId

        if (isActiveRequest) {
          if (activeLoadAbortRef.current === controller) {
            activeLoadAbortRef.current = null
          }

          setIsLoadingSpec(false)
        }
      }
    },
    [primaryWorkspacePath, setActiveTab]
  )

  React.useEffect(() => {
    void loadSpecTasks()
  }, [loadSpecTasks])

  // Derived from specTasks — spec names that are pending or complete (in workflow tasks)
  const workflowSpecNames = React.useMemo(
    () =>
      new Set(
        specTasks
          .filter((t) => t.status === 'pending' || t.status === 'complete')
          .map((t) => t.spec_name)
      ),
    [specTasks]
  )

  const currentSpecTask = React.useMemo(
    () => specTasks.find((t) => t.spec_name === specId) ?? null,
    [specId, specTasks]
  )

  const isCurrentSpecGenerating = currentSpecTask?.status === 'generating'

  React.useEffect(() => {
    const trimmedWorkspace = primaryWorkspacePath.trim()

    if (!trimmedWorkspace) {
      resetDraft()
      return
    }

    if (!specId) {
      resetDraft()
      return
    }

    // While generating, don't load the bundle — show spinner in center panel
    if (isCurrentSpecGenerating) {
      setSpecName(specId)
      setIsLoadingSpec(false)
      setError(null)
      return
    }

    const hasBundle = specTasks.some(
      (t) => t.spec_name === specId && t.spec_path && t.spec_path.trim()
    )

    if (hasBundle) {
      setSpecName(specId)
      const isAlreadyLoaded = lastLoadedSpecIdRef.current === specId

      if (!isAlreadyLoaded) {
        void loadSpecBundle(specId)
      } else {
        setIsLoadingSpec(false)
        setError(null)
      }

      return
    }

    lastLoadedSpecIdRef.current = null
    setIsLoadingSpec(false)
    setError(null)
    setSpecName(specId)
  }, [isCurrentSpecGenerating, loadSpecBundle, resetDraft, specTasks, specId, primaryWorkspacePath])

  // Derived: are any specs currently generating?
  const hasAnyGeneratingSpec = React.useMemo(
    () => specTasks.some((t) => t.status === 'generating'),
    [specTasks]
  )

  // Poll all generating specs by refreshing the full task list every 3s
  React.useEffect(() => {
    if (!hasAnyGeneratingSpec) return

    const interval = window.setInterval(() => {
      void loadSpecTasks()
    }, 3000)

    return () => window.clearInterval(interval)
  }, [hasAnyGeneratingSpec, loadSpecTasks])

  // Also poll the current spec individually to trigger bundle load on completion
  useSpecGenerationPoller(specId ?? null, primaryWorkspacePath, {
    enabled: Boolean(isCurrentSpecGenerating),
    onGenerated: () => {
      void loadSpecTasks()

      if (specId) {
        void loadSpecBundle(specId)
      }
    },
    onError: (failedSpecName) => {
      setSpecTasks((current) =>
        current.map((t) =>
          t.spec_name === failedSpecName ? { ...t, status: 'failed' } : t
        )
      )
      setError(`Spec generation failed for "${failedSpecName}". You can try again.`)
    },
  })

  const hasSelectedSpecBundle = React.useMemo(
    () =>
      Boolean(
        specId &&
          specTasks.some(
            (t) => t.spec_name === specId && t.spec_path && t.spec_path.trim()
          )
      ),
    [specTasks, specId]
  )

  const hasGeneratedSpecContent = React.useMemo(
    () => Object.values(specContent).some((value) => value.trim().length > 0),
    [specContent]
  )

  const promptMode = React.useMemo<PromptMode>(
    () => (hasSelectedSpecBundle || hasGeneratedSpecContent ? 'edit' : 'create'),
    [hasGeneratedSpecContent, hasSelectedSpecBundle]
  )

  const isGeneratingSpec = Boolean(isCurrentSpecGenerating)

  const isLoadingSelectedSpec = React.useMemo(
    () => isLoadingSpec && !isGeneratingSpec,
    [isGeneratingSpec, isLoadingSpec]
  )

  const appendHistory = React.useCallback((entries: PromptHistoryEntry[]) => {
    if (entries.length === 0) return

    setHistory((current) => {
      const existingIds = new Set(current.map((entry) => entry.id))
      const normalizedEntries = normalizeHistoryEntries(entries, existingIds)

      return [...current, ...normalizedEntries]
    })
  }, [])

  const handleSubmitPrompt = React.useCallback(
    async ({
      prompt,
      rawPrompt,
      context,
    }: {
      prompt: string
      rawPrompt: string
      context: WorkspaceReferenceContextItem[]
    }) => {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      if (!trimmedWorkspace) return false

      const nextSpecName = specName.trim()

      if (!nextSpecName) {
        setSpecNameError('Spec folder name is required')
        return false
      }

      if (!SPEC_NAME_PATTERN.test(nextSpecName)) {
        setSpecNameError('Use letters, numbers and hyphens only — e.g. SPEC-1')
        return false
      }

      const hasBundleToEdit = Object.values(specContent).some((value) => value.trim().length > 0)
      const shouldUseEditMode = promptMode === 'edit' && hasBundleToEdit

      if (!shouldUseEditMode) {
        const existingTask = specTasks.find((t) => t.spec_name === nextSpecName)
        const isDuplicate = existingTask && existingTask.status !== 'failed'

        if (isDuplicate) {
          setSpecNameError('A spec with this name already exists')
          return false
        }
      }

      setError(null)
      setSaveState(initialSaveState)
      setIsHistoryVisible(true)
      appendHistory([historyEntry(rawPrompt, 'user')])
      setSpecName(nextSpecName)

      if (!shouldUseEditMode) {
        // Navigate immediately so URL reflects the spec before generation completes
        const immediateUrl = `/prompt/${encodeURIComponent(nextSpecName)}`
        const currentUrl = specId ? `/prompt/${encodeURIComponent(specId)}` : '/prompt'

        if (immediateUrl !== currentUrl) {
          navigate(immediateUrl, { replace: false })
        }

        try {
          const response = await fetch(buildApiUrl('/api/sdd/generate-async'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt,
              raw_prompt: rawPrompt,
              prompt_context: context,
              workspace_path: trimmedWorkspace,
              file_tree: fileTreeSnapshot,
              secondary_workspace_path: secondaryWorkspacePath?.trim() || null,
              secondary_file_tree: secondaryWorkspacePath?.trim() ? secondaryFileTreeSnapshot : null,
              spec_name: nextSpecName,
              mode: 'create',
            }),
          })

          const payload = (await response.json().catch(() => ({}))) as Partial<SDDGenerateAsyncResponse> & {
            detail?: unknown
            error?: unknown
          }

          if (!response.ok) {
            throw new Error(resolveApiErrorMessage(payload, `Failed to start spec generation (${response.status})`))
          }

          // Optimistically add a 'generating' task to local state so spinner shows immediately
          setSpecTasks((current) => {
            const exists = current.some((t) => t.spec_name === nextSpecName)

            if (exists) {
              return current.map((t) =>
                t.spec_name === nextSpecName ? { ...t, status: 'generating' } : t
              )
            }

            const now = new Date().toISOString()

            return [
              ...current,
              {
                id: payload.spec_task_id ?? `temp-${nextSpecName}`,
                spec_name: nextSpecName,
                workspace_path: trimmedWorkspace,
                spec_path: '',
                requirements_path: '',
                design_path: '',
                tasks_path: '',
                summary: '',
                status: 'generating',
                created_at: now,
                updated_at: now,
              } satisfies WorkflowSpecTask,
            ]
          })
        } catch (err) {
          const message = resolveUnknownErrorMessage(err, 'Failed to start spec generation')
          setError(message)
          appendHistory([historyEntry(message, 'system')])
        }

        return
      }

      // Edit mode — synchronous call to /api/sdd/plan
      try {
        const response = await fetch(buildApiUrl('/api/sdd/plan'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt,
            raw_prompt: rawPrompt,
            prompt_context: context,
            workspace_path: trimmedWorkspace,
            file_tree: fileTreeSnapshot,
            secondary_workspace_path: secondaryWorkspacePath?.trim() || null,
            secondary_file_tree: secondaryWorkspacePath?.trim() ? secondaryFileTreeSnapshot : null,
            spec_name: nextSpecName,
            mode: 'edit',
            current_bundle: {
              requirements: specContent['requirements.md'],
              design: specContent['design.md'],
              tasks: specContent['tasks.md'],
            },
          }),
        })

        const payload = (await response.json().catch(() => ({}))) as Partial<SDDPlanResponse> & {
          detail?: unknown
          error?: unknown
        }

        if (!response.ok) {
          throw new Error(resolveApiErrorMessage(payload, `Failed to update SDD spec (${response.status})`))
        }

        const resolvedSpecName = String(payload.spec_name || nextSpecName).trim()
        const loadedSpecName = resolvedSpecName || nextSpecName
        lastLoadedSpecIdRef.current = loadedSpecName || null

        if (resolvedSpecName) {
          setSpecName(resolvedSpecName)
        } else {
          setSpecName(nextSpecName)
        }

        setSpecContent({
          'requirements.md': String(payload.requirements || ''),
          'design.md': String(payload.design || ''),
          'tasks.md': String(payload.tasks || ''),
        })
        appendHistory(Array.isArray(payload.history) ? payload.history : [])

        if (resolvedSpecName) {
          const nextUrl = `/prompt/${encodeURIComponent(resolvedSpecName)}`
          const baseUrl = specId ? `/prompt/${encodeURIComponent(specId)}` : '/prompt'

          if (nextUrl !== baseUrl) {
            navigate(nextUrl, { replace: false })
          }
        }

        void loadSpecTasks()
      } catch (err) {
        const message = resolveUnknownErrorMessage(err, 'Failed to update SDD spec')
        setError(message)
        appendHistory([historyEntry(message, 'system')])
      }
    },
    [
      appendHistory,
      fileTreeSnapshot,
      secondaryFileTreeSnapshot,
      loadSpecTasks,
      navigate,
      promptMode,
      specTasks,
      specId,
      specContent,
      specName,
      primaryWorkspacePath,
      secondaryWorkspacePath,
    ]
  )

  const handleSpecNameChange = React.useCallback(
    (nextSpecName: string) => {
      const sanitized = nextSpecName.toUpperCase().replace(/[^A-Z0-9-]/g, '')
      setSpecName(sanitized)

      if (!sanitized) {
        setSpecNameError('Spec folder name is required')
        return
      }

      if (!SPEC_NAME_PATTERN.test(sanitized)) {
        setSpecNameError('Use letters, numbers and hyphens only — e.g. SPEC-1')
        return
      }

      const existingTask = specTasks.find((t) => t.spec_name === sanitized)
      const isDuplicate = existingTask && existingTask.status !== 'failed'

      if (isDuplicate) {
        setSpecNameError('A spec with this name already exists')
        return
      }

      setSpecNameError(null)
    },
    [specTasks]
  )

  const closeSecondaryWorkspaceDialog = React.useCallback(() => {
    setIsSecondaryWorkspaceDialogOpen(false)
  }, [])

  const confirmSecondaryWorkspaceSelection = React.useCallback(() => {
    const path = selectedSecondaryWorkspacePath.trim()

    if (!path || path === primaryWorkspacePath.trim()) {
      setSecondaryWorkspacePath(null)
      setIsSecondaryWorkspaceDialogOpen(false)
      return
    }

    setSecondaryWorkspacePath(path)
    setIsSecondaryWorkspaceDialogOpen(false)
  }, [primaryWorkspacePath, selectedSecondaryWorkspacePath, setSecondaryWorkspacePath])

  const handleSave = React.useCallback(async () => {
    const trimmedWorkspace = primaryWorkspacePath.trim()
    if (!trimmedWorkspace) return

    if (!specName.trim()) {
      setSaveState({ status: 'error', message: 'Generate a spec before saving.' })
      return
    }

    setIsSaving(true)
    setError(null)
    setSaveState({ status: 'idle', message: 'Saving...' })

    try {
      const response = await fetch(buildApiUrl('/api/sdd/save'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          spec_name: specName,
          file_name: activeTab,
          content: specContent[activeTab],
          workspace_path: trimmedWorkspace,
        }),
      })

      const payload = (await response.json().catch(() => ({}))) as Partial<SDDSaveResponse> & {
        detail?: unknown
        error?: unknown
      }

      if (!response.ok || payload.success === false) {
        throw new Error(resolveApiErrorMessage(payload, `Failed to save spec file (${response.status})`))
      }

      setSaveState({ status: 'success', message: `Saved ${activeTab}` })
      appendHistory([historyEntry(`Saved ${activeTab}`, 'system')])
      void loadSpecTasks()
    } catch (err) {
      const message = resolveUnknownErrorMessage(err, 'Save failed')
      setSaveState({ status: 'error', message })
      setError(message)
      appendHistory([historyEntry(`Save failed: ${message}`, 'system')])
    } finally {
      setIsSaving(false)
    }
  }, [activeTab, appendHistory, loadSpecTasks, specContent, specName, primaryWorkspacePath])

  const handleAddSpecTask = React.useCallback(
    async (summaryOverride: string) => {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      const trimmedSpecName = specName.trim()
      const trimmedSummary = summaryOverride.trim()

      if (!trimmedWorkspace || !trimmedSpecName || !trimmedSummary) return

      setIsAddingSpecTask(true)
      setError(null)

      try {
        const response = await fetch(buildApiUrl('/api/spec-tasks'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            spec_name: trimmedSpecName,
            workspace_path: trimmedWorkspace,
            summary: trimmedSummary,
          }),
        })
        const payload = (await response.json().catch(() => ({}))) as Partial<WorkflowSpecTask> & {
          detail?: unknown
          error?: unknown
        }

        if (!response.ok) {
          throw new Error(resolveApiErrorMessage(payload, `Failed to add spec task (${response.status})`))
        }

        appendHistory([historyEntry(`Added spec task: ${trimmedSpecName}`, 'system')])
        setSaveState({ status: 'success', message: `Added ${trimmedSpecName} to tasks` })
        setIsAddTaskDialogOpen(false)
        void loadSpecTasks()

        try {
          await fetch(buildApiUrl('/api/pipelines/backlog/refresh'), { method: 'POST' })
        } catch {
          // Backlog sync can be refreshed later from Pipelines page.
        }
      } catch (err) {
        const message = resolveUnknownErrorMessage(err, 'Failed to add spec task')
        setError(message)
        appendHistory([historyEntry(`Add to tasks failed: ${message}`, 'system')])
      } finally {
        setIsAddingSpecTask(false)
      }
    },
    [appendHistory, loadSpecTasks, primaryWorkspacePath, specName]
  )

  const openAddTaskDialog = React.useCallback(() => {
    const trimmedSpecName = specName.trim()
    if (!trimmedSpecName) return

    setSpecTaskSummary(deriveSpecTaskSummary(trimmedSpecName, specContent))
    setIsAddTaskDialogOpen(true)
  }, [specContent, specName])

  const submitAddTaskDialog = React.useCallback(() => {
    if (isAddingSpecTask) return

    void handleAddSpecTask(specTaskSummary)
  }, [handleAddSpecTask, isAddingSpecTask, specTaskSummary])

  const openWorkflowSpecsTab = React.useCallback(() => {
    navigate('/workflow-tasks?tab=specs')
  }, [navigate])

  const handleSelectSpecBundle = React.useCallback(
    (nextSpecName: string) => {
      const trimmedSpecName = nextSpecName.trim()
      if (!trimmedSpecName) return

      navigate(`/prompt/${encodeURIComponent(trimmedSpecName)}`)
    },
    [navigate]
  )

  const handleNewPrompt = React.useCallback(() => {
    navigate('/new-prompt')
  }, [navigate])

  const openImportBundleDialog = React.useCallback(() => {
    setImportBundleError(null)
    setImportBundlePath('')
    setImportSpecName('')
    setImportSummary('')
    setIsImportBundlePickerOpen(false)
    setIsImportBundleDialogOpen(true)
  }, [])

  const closeImportBundleDialog = React.useCallback(() => {
    if (isImportingBundle) return
    setIsImportBundleDialogOpen(false)
    setIsImportBundlePickerOpen(false)
    setImportBundleError(null)
  }, [isImportingBundle])

  const openImportBundlePicker = React.useCallback(() => {
    setIsImportBundleDialogOpen(false)
    setIsImportBundlePickerOpen(true)
  }, [])

  const closeImportBundlePicker = React.useCallback(() => {
    setIsImportBundlePickerOpen(false)
    setIsImportBundleDialogOpen(true)
  }, [])

  const handleImportSpecNameChange = React.useCallback((value: string) => {
    const sanitized = value.toUpperCase().replace(/[^A-Z0-9-]/g, '')
    setImportSpecName(sanitized)
  }, [])

  const confirmImportBundleSelection = React.useCallback(() => {
    const path = selectedImportBundlePath.trim()
    if (path) {
      setImportBundlePath(path)
    }
    setIsImportBundlePickerOpen(false)
    setIsImportBundleDialogOpen(true)
  }, [selectedImportBundlePath])

  const submitImportBundle = React.useCallback(async () => {
    const trimmedWorkspace = primaryWorkspacePath.trim()
    const trimmedBundlePath = importBundlePath.trim()
    const trimmedSpecName = importSpecName.trim()
    const trimmedSummary = importSummary.trim()

    if (!trimmedWorkspace) {
      setImportBundleError('Select a workspace before importing a bundle.')
      return
    }

    if (!trimmedBundlePath) {
      setImportBundleError('Bundle location is required.')
      return
    }

    if (!trimmedSpecName) {
      setImportBundleError('SPEC Name / ID is required.')
      return
    }

    if (!SPEC_NAME_PATTERN.test(trimmedSpecName)) {
      setImportBundleError('Use letters, numbers and hyphens only — e.g. SPEC-1')
      return
    }

    const existingTask = specTasks.find((task) => task.spec_name === trimmedSpecName)
    if (existingTask && existingTask.status !== 'failed') {
      setImportBundleError('A spec with this name already exists.')
      return
    }

    setImportBundleError(null)
    setIsImportingBundle(true)
    setError(null)

    try {
      const response = await fetch(buildApiUrl('/api/sdd/import-bundle'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bundle_path: trimmedBundlePath,
          spec_name: trimmedSpecName,
          workspace_path: trimmedWorkspace,
          summary: trimmedSummary || null,
        }),
      })
      const payload = (await response.json().catch(() => ({}))) as Partial<WorkflowSpecTask> & {
        detail?: unknown
        error?: unknown
      }

      if (!response.ok) {
        throw new Error(resolveApiErrorMessage(payload, `Failed to import bundle (${response.status})`))
      }

      appendHistory([historyEntry(`Imported spec bundle: ${trimmedSpecName}`, 'system')])
      setSaveState({ status: 'success', message: `Imported ${trimmedSpecName} and added to tasks` })
      setIsImportBundleDialogOpen(false)
      setIsImportBundlePickerOpen(false)
      setImportBundlePath('')
      setImportSpecName('')
      setImportSummary('')
      void loadSpecTasks()
      navigate(`/prompt/${encodeURIComponent(trimmedSpecName)}`)
    } catch (err) {
      const message = resolveUnknownErrorMessage(err, 'Failed to import bundle')
      setImportBundleError(message)
      appendHistory([historyEntry(`Import failed: ${message}`, 'system')])
    } finally {
      setIsImportingBundle(false)
    }
  }, [
    appendHistory,
    importBundlePath,
    importSpecName,
    importSummary,
    loadSpecTasks,
    navigate,
    primaryWorkspacePath,
    specTasks,
  ])

  const handleDeleteSpecBundle = React.useCallback(
    async (
      nextSpecName: string,
      options?: { force?: boolean }
    ): Promise<boolean> => {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      const trimmedSpecName = nextSpecName.trim()
      const shouldForceDelete = Boolean(options?.force)

      if (!trimmedWorkspace || !trimmedSpecName) return false

      setError(null)
      setDeletingSpecName(trimmedSpecName)

      try {
        const params = new URLSearchParams()
        params.set('workspace_path', trimmedWorkspace)
        const hasTask = specTasks.some((task) => task.spec_name === trimmedSpecName)

        const deleteSpecTaskRow = async () => {
          const taskParams = new URLSearchParams()
          taskParams.set('workspace_path', trimmedWorkspace)

          const taskDeleteResponse = await fetch(
            buildApiUrl(`/api/spec-tasks/${encodeURIComponent(trimmedSpecName)}?${taskParams.toString()}`),
            { method: 'DELETE' }
          )
          const taskDeletePayload = (await taskDeleteResponse.json().catch(() => ({}))) as {
            detail?: unknown
            error?: unknown
          }

          if (!taskDeleteResponse.ok && taskDeleteResponse.status !== 404) {
            throw new Error(
              resolveApiErrorMessage(taskDeletePayload, `Failed to delete spec task (${taskDeleteResponse.status})`)
            )
          }
        }

        if (shouldForceDelete && hasTask) {
          await deleteSpecTaskRow()
        }

        // Delete spec files
        const fileDeleteResponse = await fetch(
          buildApiUrl(`/api/sdd/specs/${encodeURIComponent(trimmedSpecName)}?${params.toString()}`),
          { method: 'DELETE' }
        )
        const fileDeletePayload = (await fileDeleteResponse.json().catch(() => ({}))) as Partial<SDDSpecDeleteResponse> & {
          detail?: unknown
          error?: unknown
        }
        const ignoreMissingSpecFolder = shouldForceDelete && fileDeleteResponse.status === 404

        if ((!fileDeleteResponse.ok && !ignoreMissingSpecFolder) || fileDeletePayload.success === false) {
          throw new Error(
            resolveApiErrorMessage(fileDeletePayload, `Failed to delete spec bundle (${fileDeleteResponse.status})`)
          )
        }

        if (!shouldForceDelete && hasTask) {
          await deleteSpecTaskRow()
        }

        setSpecTasks((current) => current.filter((task) => task.spec_name !== trimmedSpecName))
        appendHistory([
          historyEntry(
            `${shouldForceDelete ? 'Force deleted' : 'Deleted'} spec bundle: ${trimmedSpecName}`,
            'system'
          ),
        ])

        if (currentSpecId === trimmedSpecName || specName.trim() === trimmedSpecName || specId === trimmedSpecName) {
          clearCurrentSpecId()
          resetDraft()
          navigate('/prompt')
        }

        void loadSpecTasks()

        return true
      } catch (err) {
        const message = resolveUnknownErrorMessage(
          err,
          shouldForceDelete ? 'Failed to force delete spec bundle' : 'Failed to delete spec bundle'
        )
        setError(message)
        appendHistory([historyEntry(`${shouldForceDelete ? 'Force delete' : 'Delete'} failed: ${message}`, 'system')])

        return false
      } finally {
        setDeletingSpecName(null)
      }
    },
    [
      appendHistory,
      clearCurrentSpecId,
      currentSpecId,
      loadSpecTasks,
      navigate,
      resetDraft,
      specId,
      specName,
      specTasks,
      primaryWorkspacePath,
    ]
  )

  const handleFetchSpecBundle = React.useCallback(
    async (nextSpecName: string): Promise<string | null> => {
      const trimmedWorkspace = primaryWorkspacePath.trim()
      const trimmedSpecName = nextSpecName.trim()

      if (!trimmedWorkspace || !trimmedSpecName) return null

      try {
        const params = new URLSearchParams()
        params.set('workspace_path', trimmedWorkspace)
        const response = await fetch(
          buildApiUrl(`/api/sdd/specs/${encodeURIComponent(trimmedSpecName)}?${params.toString()}`)
        )

        if (!response.ok) return null

        const payload = (await response.json().catch(() => ({}))) as Partial<SpecBundlePayload>
        const parts: string[] = []

        if (payload.requirements?.trim()) {
          parts.push(`## Requirements\n\n${payload.requirements.trim()}`)
        }

        if (payload.design?.trim()) {
          parts.push(`## Design\n\n${payload.design.trim()}`)
        }

        if (payload.tasks?.trim()) {
          parts.push(`## Tasks\n\n${payload.tasks.trim()}`)
        }

        return parts.length > 0 ? `# Spec: ${trimmedSpecName}\n\n${parts.join('\n\n---\n\n')}` : null
      } catch {
        return null
      }
    },
    [primaryWorkspacePath]
  )

  const visibleColumns = React.useMemo(
    () => COLUMN_ORDER.filter((column) => columnVisibility[column]),
    [columnVisibility]
  )

  const gridTemplateColumns = React.useMemo(() => {
    const hasLeft = columnVisibility.left
    const hasCenter = columnVisibility.center
    const hasRight = columnVisibility.right

    if (hasCenter) {
      const leftWidth = hasLeft ? 30 : 0
      const rightWidth = hasRight ? 30 : 0
      const centerWidth = 100 - leftWidth - rightWidth
      const widths: number[] = []

      if (hasLeft) {
        widths.push(leftWidth)
      }

      widths.push(centerWidth)

      if (hasRight) {
        widths.push(rightWidth)
      }

      return widths.map((width) => `${width}%`).join(' ')
    }

    if (visibleColumns.length === 0) return '1fr'

    return visibleColumns.map(() => `${100 / visibleColumns.length}%`).join(' ')
  }, [columnVisibility, visibleColumns])

  const isLastVisibleColumn = React.useCallback(
    (column: PromptsColumnKey) => visibleColumns[visibleColumns.length - 1] === column,
    [visibleColumns]
  )

  const toggleColumnVisibility = React.useCallback((column: PromptsColumnKey) => {
    setColumnVisibility((current) => {
      const visibleColumnCount = Object.values(current).filter(Boolean).length
      const isCurrentColumnVisible = current[column]

      if (isCurrentColumnVisible && visibleColumnCount === 1) {
        return current
      }

      return {
        ...current,
        [column]: !isCurrentColumnVisible,
      }
    })
  }, [])

  const shouldShowCenterEmptyState = React.useMemo(() => {
    if (isLoadingSpec) return false
    if (isGeneratingSpec) return false
    if (hasSelectedSpecBundle) return false

    return !Object.values(specContent).some((value) => value.trim().length > 0)
  }, [hasSelectedSpecBundle, isGeneratingSpec, isLoadingSpec, specContent])

  const isEditorGenerating = isLoadingSpec || isGeneratingSpec

  const canAddSpecToTasks = React.useMemo(
    () => Boolean(specName.trim()) && (hasSelectedSpecBundle || hasGeneratedSpecContent),
    [hasGeneratedSpecContent, hasSelectedSpecBundle, specName]
  )

  const isSpecInWorkflowTasks = React.useMemo(() => {
    const trimmedSpecName = specName.trim()
    if (!trimmedSpecName) return false

    return workflowSpecNames.has(trimmedSpecName)
  }, [specName, workflowSpecNames])

  const shouldShowAddToTasksButton = canAddSpecToTasks && !isSpecInWorkflowTasks && !isGeneratingSpec

  const canSubmitSpecTaskSummary = specTaskSummary.trim().length > 0

  const editorLoadingMessage = React.useMemo(
    () => (isGeneratingSpec ? 'Generating spec content...' : 'Loading selected spec...'),
    [isGeneratingSpec]
  )

  const handleEditorContentChange = React.useCallback(
    (nextValue: string) => {
      setSpecContent((current) => ({
        ...current,
        [activeTab]: nextValue,
      }))

      if (saveState.status !== 'idle') {
        setSaveState(initialSaveState)
      }
    },
    [activeTab, saveState.status]
  )

  const handleAddTaskDialogOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (isAddingSpecTask) return

      setIsAddTaskDialogOpen(nextOpen)
    },
    [isAddingSpecTask]
  )

  if (!primaryWorkspacePath.trim()) {
    return (
      <WorkspaceRequiredState
        title='Select a workspace to use Create A Spec'
        description='Set an active workspace first, then generate and edit requirements.md, design.md, and tasks.md.'
        icon={FileText}
      />
    )
  }

  return (
    <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
      <PromptsPageHeader
        promptMode={promptMode}
        columnToggleOptions={COLUMN_TOGGLE_OPTIONS}
        columnVisibility={columnVisibility}
        visibleColumns={visibleColumns}
        specName={specName}
        secondaryWorkspacePath={secondaryWorkspacePath}
        isSpecInWorkflowTasks={isSpecInWorkflowTasks}
        shouldShowAddToTasksButton={shouldShowAddToTasksButton}
        isAddingSpecTask={isAddingSpecTask}
        onToggleColumnVisibility={toggleColumnVisibility}
        onOpenSecondaryWorkspaceDialog={() => {
          setIsSecondaryWorkspaceDialogOpen(true)
        }}
        onClearSecondaryWorkspace={() => {
          setSecondaryWorkspacePath(null)
        }}
        onOpenImportBundleDialog={openImportBundleDialog}
        onNewSpec={handleNewPrompt}
        onOpenWorkflowSpecsTab={openWorkflowSpecsTab}
        onOpenAddTaskDialog={openAddTaskDialog}
      />

      <PromptsPageColumns
        columnVisibility={columnVisibility}
        gridTemplateColumns={gridTemplateColumns}
        isLastVisibleColumn={isLastVisibleColumn}
        primaryWorkspacePath={primaryWorkspacePath}
        secondaryWorkspacePath={secondaryWorkspacePath}
        activeTab={activeTab}
        specContent={specContent}
        isEditorGenerating={isEditorGenerating}
        editorLoadingMessage={editorLoadingMessage}
        isSaving={isSaving}
        saveState={saveState}
        shouldShowCenterEmptyState={shouldShowCenterEmptyState}
        history={history}
        specName={specName}
        specNameError={specNameError}
        promptMode={promptMode}
        specTasks={specTasks}
        workflowSpecNames={workflowSpecNames}
        isLoadingSpecBundles={isLoadingSpecTasks}
        specBundlesError={specTasksError}
        isGeneratingSpec={isGeneratingSpec}
        isLoadingSelectedSpec={isLoadingSelectedSpec}
        deletingSpecName={deletingSpecName}
        trackedAgents={trackedAgents}
        agentsMode={agentsMode}
        isAgentsLoading={isAgentsLoading}
        agentsError={agentsError}
        error={error}
        isHistoryVisible={isHistoryVisible}
        isAgentActivityVisible={isAgentActivityVisible}
        onPrimaryTreeSnapshotChange={setFileTreeSnapshot}
        onSecondaryTreeSnapshotChange={setSecondaryFileTreeSnapshot}
        onTabChange={setActiveTab}
        onEditorContentChange={handleEditorContentChange}
        onSave={() => {
          void handleSave()
        }}
        onSpecNameChange={handleSpecNameChange}
        onSelectSpecBundle={handleSelectSpecBundle}
        onDeleteSpecBundle={handleDeleteSpecBundle}
        onFetchSpecBundle={handleFetchSpecBundle}
        onToggleHistoryVisibility={() => {
          setIsHistoryVisible((current) => !current)
        }}
        onToggleAgentActivityVisibility={() => {
          setIsAgentActivityVisible((current) => !current)
        }}
        onSubmitPrompt={handleSubmitPrompt}
      />

      <AddSpecTaskDialog
        isOpen={isAddTaskDialogOpen}
        isAddingSpecTask={isAddingSpecTask}
        specName={specName}
        specTaskSummary={specTaskSummary}
        canSubmitSpecTaskSummary={canSubmitSpecTaskSummary}
        onOpenChange={handleAddTaskDialogOpenChange}
        onSpecTaskSummaryChange={setSpecTaskSummary}
        onCancel={() => {
          setIsAddTaskDialogOpen(false)
        }}
        onConfirm={submitAddTaskDialog}
      />

      <Dialog
        open={isImportBundleDialogOpen}
        onOpenChange={(nextOpen) => {
          if (isImportingBundle) return
          if (!nextOpen) {
            closeImportBundleDialog()
          }
        }}
      >
        <DialogContent className='sm:max-w-2xl'>
          <DialogHeader>
            <DialogTitle>Import Spec Bundle</DialogTitle>
            <DialogDescription>
              Select a folder that contains <code>requirements.md</code>, <code>design.md</code>, and <code>tasks.md</code>.
            </DialogDescription>
          </DialogHeader>

          <div className='space-y-4'>
            <div className='space-y-2'>
              <Label className='text-muted-foreground text-xs'>Bundle Location</Label>

              <div className='flex items-center gap-2'>
                <Input
                  value={importBundlePath}
                  readOnly
                  placeholder='Choose the bundle folder...'
                />

                <Button
                  type='button'
                  variant='outline'
                  size='icon'
                  disabled={isImportingBundle}
                  onClick={openImportBundlePicker}
                  title='Browse for bundle folder'
                >
                  <FolderUp className='size-4' />
                </Button>
              </div>
            </div>

            <div className='space-y-2'>
              <Label className='text-muted-foreground text-xs'>SPEC Name / ID</Label>

              <Input
                value={importSpecName}
                placeholder='SPEC-1'
                onChange={(event) => {
                  handleImportSpecNameChange(event.target.value)
                }}
                disabled={isImportingBundle}
              />
            </div>

            <div className='space-y-2'>
              <Label className='text-muted-foreground text-xs'>Summary</Label>

              <Textarea
                value={importSummary}
                placeholder='One-line summary for workflow tasks...'
                onChange={(event) => {
                  setImportSummary(event.target.value)
                }}
                disabled={isImportingBundle}
              />
            </div>

            {importBundleError ? <p className='text-sm text-rose-600'>{importBundleError}</p> : null}
          </div>

          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              disabled={isImportingBundle}
              onClick={closeImportBundleDialog}
            >
              Cancel
            </Button>

            <Button
              type='button'
              disabled={isImportingBundle}
              onClick={() => {
                void submitImportBundle()
              }}
            >
              {isImportingBundle ? 'Importing...' : 'Import'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <FileFolderDialog
        open={isImportBundlePickerOpen}
        onClose={closeImportBundlePicker}
        title='Select Bundle Folder'
        mode='folder-only'
        locations={importBundleLocations}
        columns={importBundleColumns}
        selectedByColumnPath={selectedImportByColumnPath}
        selectedPath={selectedImportBundlePath}
        activeDirectoryPath={activeImportDirectoryPath}
        isLoading={isImportBundleLoading}
        isCreatingFolder={isImportBundleCreatingFolder}
        isRenamingEntry={isImportBundleRenamingEntry}
        error={importBundlePickerError}
        showHidden={importBundleShowHidden}
        onShowHiddenChange={(value) => {
          void setImportBundleShowHidden(value)
        }}
        onSelectLocation={(path) => {
          void selectImportBundleLocation(path)
        }}
        onSelectEntry={(columnIndex, entry) => {
          void selectImportBundleEntry(columnIndex, entry)
        }}
        onCreateFolder={createImportBundleFolder}
        onRenameEntry={renameImportBundleEntry}
        onDeleteEntry={deleteImportBundleEntry}
        onConfirm={confirmImportBundleSelection}
      />

      <FileFolderDialog
        open={isSecondaryWorkspaceDialogOpen}
        onClose={closeSecondaryWorkspaceDialog}
        title='Select Reference Workspace'
        mode='folder-only'
        locations={secondaryWorkspaceLocations}
        columns={secondaryWorkspaceColumns}
        selectedByColumnPath={selectedSecondaryByColumnPath}
        selectedPath={selectedSecondaryWorkspacePath}
        activeDirectoryPath={activeSecondaryDirectoryPath}
        isLoading={isSecondaryWorkspaceLoading}
        isCreatingFolder={isSecondaryWorkspaceCreatingFolder}
        isRenamingEntry={isSecondaryWorkspaceRenamingEntry}
        error={secondaryWorkspaceError}
        showHidden={secondaryWorkspaceShowHidden}
        onShowHiddenChange={(value) => {
          void setSecondaryWorkspaceShowHidden(value)
        }}
        onSelectLocation={(path) => {
          void selectSecondaryWorkspaceLocation(path)
        }}
        onSelectEntry={(columnIndex, entry) => {
          void selectSecondaryWorkspaceEntry(columnIndex, entry)
        }}
        onCreateFolder={createSecondaryWorkspaceFolder}
        onRenameEntry={renameSecondaryWorkspaceEntry}
        onDeleteEntry={deleteSecondaryWorkspaceEntry}
        onConfirm={confirmSecondaryWorkspaceSelection}
      />
    </div>
  )
}
