import { useEffect, useMemo, useRef, useState } from "react"

import { Loader2 } from 'lucide-react'

import { Button } from "@/shared/components/ui/button"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { formatGitDefaultBranchLabel } from "@/features/git/constants"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/components/ui/select"
import type {
  PendingWorkspaceAction,
  PipelineDependencyOption,
  PipelineTaskRelationType,
} from "@/features/pipelines/types"
import type { Workspace } from "@/features/workspace/types"
import { Chip } from "@/shared/components/chip"

const JIRA_DESTINATION_NONE_VALUE = "__jira_destination_none__"
const STARTING_BRANCH_INHERIT_VALUE = "__starting_branch_inherit__"
const STARTING_BRANCH_CUSTOM_VALUE = "__starting_branch_custom__"
const DEPENDENCY_NONE_VALUE = "__dependency_none__"

type PipelineTaskSetupDialogProps = {
  open: boolean
  pendingAction: PendingWorkspaceAction
  workspacePath: string
  jiraCompleteColumnName: string
  startingGitBranchOverride: string
  taskRelation: PipelineTaskRelationType
  dependencyKey: string
  dependencyOptions: PipelineDependencyOption[]
  jiraDestinationColumns: string[]
  gitBranchOptions: string[]
  gitDefaultWorkingBranch?: string
  ticketBranchSuggestionKeys?: string[]
  currentPipelineTicketKeys?: string[]
  defaultToCustomBranchMode?: boolean
  gitCurrentBranch?: string | null
  workspaces: Workspace[]
  isLoadingWorkspaces?: boolean
  isLoadingGitBranches?: boolean
  workspaceError?: string | null
  gitBranchesError?: string | null
  onWorkspacePathChange: (workspacePath: string) => void
  onJiraCompleteColumnNameChange: (value: string) => void
  onStartingGitBranchOverrideChange: (value: string) => void
  onTaskRelationChange: (value: PipelineTaskRelationType) => void
  onDependencyKeyChange: (value: string) => void
  onClose: () => void
  onConfirm: () => void
  isMutating?: boolean
}

export default function PipelineTaskSetupDialog({
  open,
  pendingAction,
  workspacePath,
  jiraCompleteColumnName,
  startingGitBranchOverride,
  taskRelation,
  dependencyKey,
  dependencyOptions,
  jiraDestinationColumns,
  gitBranchOptions,
  gitDefaultWorkingBranch = "main",
  ticketBranchSuggestionKeys = [],
  currentPipelineTicketKeys = [],
  defaultToCustomBranchMode = false,
  gitCurrentBranch = null,
  workspaces,
  isLoadingWorkspaces = false,
  isLoadingGitBranches = false,
  workspaceError = null,
  gitBranchesError = null,
  onWorkspacePathChange,
  onJiraCompleteColumnNameChange,
  onStartingGitBranchOverrideChange,
  onTaskRelationChange,
  onDependencyKeyChange,
  onClose,
  onConfirm,
  isMutating = false,
}: PipelineTaskSetupDialogProps) {
  const jiraKey =
    pendingAction?.kind === "queue"
      ? pendingAction.jiraKey
      : pendingAction?.jiraKey || pendingAction?.taskId || ""
  const taskSource = pendingAction?.taskSource === "spec" ? "spec" : "jira"
  const taskLabel = taskSource === "spec" ? "Spec task" : "Ticket"
  const normalizedJiraKey = jiraKey.trim().toUpperCase()
  const normalizedGitDefaultWorkingBranch = formatGitDefaultBranchLabel(gitDefaultWorkingBranch, gitCurrentBranch)

  const hasWorkspaces = workspaces.length > 0
  const hasValidWorkspaceSelection = workspaces.some((workspace) => workspace.path === workspacePath)
  const normalizedDependencyKey = dependencyKey.trim().toUpperCase()
  const requiresDependencySelection = taskSource === "spec" && taskRelation === "subtask"
  const hasValidDependencySelection = !requiresDependencySelection || Boolean(normalizedDependencyKey)
  const canConfirm = hasValidWorkspaceSelection && !isMutating && hasValidDependencySelection
  const normalizedLocalGitBranches = useMemo(() => {
    const seen = new Set<string>()
    const branches: string[] = []
    for (const branch of gitBranchOptions) {
      const name = branch.trim()
      if (!name || seen.has(name)) continue
      seen.add(name)
      branches.push(name)
    }
    return branches
  }, [gitBranchOptions])
  const normalizedStartingBranchOverride = startingGitBranchOverride.trim()
  const matchesLocalBranch = normalizedLocalGitBranches.includes(normalizedStartingBranchOverride)
  const didApplyDefaultCustomBranchModeRef = useRef(false)
  const [customBranchMode, setCustomBranchMode] = useState(
    Boolean(normalizedStartingBranchOverride) && !matchesLocalBranch
  )

  useEffect(() => {
    if (!open) return
    if (defaultToCustomBranchMode && didApplyDefaultCustomBranchModeRef.current) return
    setCustomBranchMode(Boolean(normalizedStartingBranchOverride) && !matchesLocalBranch)
  }, [defaultToCustomBranchMode, matchesLocalBranch, normalizedStartingBranchOverride, open])

  useEffect(() => {
    if (!open) {
      didApplyDefaultCustomBranchModeRef.current = false
      return
    }
    if (!defaultToCustomBranchMode) return
    if (didApplyDefaultCustomBranchModeRef.current) return
    didApplyDefaultCustomBranchModeRef.current = true
    setCustomBranchMode(true)
  }, [defaultToCustomBranchMode, open])

  const startingBranchSelectValue = customBranchMode
    ? STARTING_BRANCH_CUSTOM_VALUE
    : normalizedStartingBranchOverride || STARTING_BRANCH_INHERIT_VALUE
  const availableTicketBranchSuggestions = useMemo(() => {
    const seen = new Set<string>()
    const keys: string[] = []
    for (const ticketKey of ticketBranchSuggestionKeys) {
      const normalized = ticketKey.trim().toUpperCase()
      if (!normalized || normalized === normalizedJiraKey || seen.has(normalized)) continue
      seen.add(normalized)
      keys.push(normalized)
    }
    return keys
  }, [normalizedJiraKey, ticketBranchSuggestionKeys])
  const currentPipelineTicketKeySet = useMemo(
    () =>
      new Set(
        currentPipelineTicketKeys
          .map((ticketKey) => ticketKey.trim().toUpperCase())
          .filter(Boolean)
      ),
    [currentPipelineTicketKeys]
  )
  const availableDependencyOptions = useMemo(
    () =>
      dependencyOptions
        .map((option) => ({
          ...option,
          key: option.key.trim().toUpperCase(),
        }))
        .filter((option) => option.key && option.key !== normalizedJiraKey),
    [dependencyOptions, normalizedJiraKey]
  )

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-2xl rounded-lg border p-5 shadow-lg">
        <h3 className="text-base font-semibold">Move {taskLabel} to Task Queue</h3>
        <div className="mt-4 space-y-5 text-sm">
          <p className="text-muted-foreground">{taskLabel}: {jiraKey || "n/a"}</p>

          <div className="space-y-1">
            <Label className="text-muted-foreground text-xs">Workspace</Label>
            {isLoadingWorkspaces ? (
              <p className="text-muted-foreground">Loading workspaces...</p>
            ) : hasWorkspaces ? (
              <>
                <Select
                  value={hasValidWorkspaceSelection ? workspacePath : undefined}
                  onValueChange={onWorkspacePathChange}
                  disabled={isMutating}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a workspace..." />
                  </SelectTrigger>
                  <SelectContent className="z-[80]">
                    {workspaces.map((workspace) => (
                      <SelectItem key={workspace.id} value={workspace.path}>
                        {workspace.name} ({workspace.path})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground break-all text-xs">{workspacePath || "No workspace selected"}</p>
                {!hasValidWorkspaceSelection && workspacePath ? (
                  <p className="text-amber-700 text-xs">
                    Selected path is not one of your saved Workspaces. Choose a Workspace from the list.
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-muted-foreground">No workspaces found. Create one in Workspaces first.</p>
            )}
            {workspaceError ? (
              <p className="text-rose-700 text-xs">{workspaceError}</p>
            ) : null}
          </div>

          {taskSource !== "spec" ? (
            <div className="space-y-1">
              <Label className="text-muted-foreground text-xs">Jira Column Destination (on completion)</Label>
              {jiraDestinationColumns.length > 0 ? (
                <>
                  <Select
                    value={jiraCompleteColumnName || JIRA_DESTINATION_NONE_VALUE}
                    onValueChange={(value) =>
                      onJiraCompleteColumnNameChange(
                        value === JIRA_DESTINATION_NONE_VALUE ? "" : value
                      )
                    }
                    disabled={isMutating}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="No destination selected" />
                    </SelectTrigger>
                    <SelectContent className="z-[80]">
                      <SelectItem value={JIRA_DESTINATION_NONE_VALUE}>No destination selected</SelectItem>
                      {jiraDestinationColumns.map((columnName) => (
                        <SelectItem key={columnName} value={columnName}>
                          {columnName}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-muted-foreground text-xs">
                    Stored on the pipeline task and can be used later when moving the Jira ticket after pipeline completion.
                  </p>
                </>
              ) : (
                <p className="text-muted-foreground text-xs">
                  No Jira board columns found yet. Fetch Workflow Tasks first to load board columns.
                </p>
              )}
            </div>
          ) : null}

          <div className="space-y-1">
            <Label className="text-muted-foreground text-xs">Starting Git Branch (per-task override)</Label>
            <Select
              value={startingBranchSelectValue}
              onValueChange={(value) => {
                if (value === STARTING_BRANCH_INHERIT_VALUE) {
                  setCustomBranchMode(false)
                  onStartingGitBranchOverrideChange("")
                  return
                }
                if (value === STARTING_BRANCH_CUSTOM_VALUE) {
                  setCustomBranchMode(true)
                  if (!normalizedStartingBranchOverride || matchesLocalBranch) {
                    onStartingGitBranchOverrideChange("")
                  }
                  return
                }
                setCustomBranchMode(false)
                onStartingGitBranchOverrideChange(value)
              }}
              disabled={isMutating || !hasValidWorkspaceSelection}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    hasValidWorkspaceSelection
                      ? isLoadingGitBranches
                        ? "Loading branches..."
                        : "Use Git action / global default"
                      : "Select a workspace first"
                  }
                />
              </SelectTrigger>
              <SelectContent className="z-[80]">
                <SelectItem value={STARTING_BRANCH_INHERIT_VALUE}>
                  Git Actions Default ({normalizedGitDefaultWorkingBranch})
                </SelectItem>
                {normalizedLocalGitBranches.map((branchName) => (
                  <SelectItem key={branchName} value={branchName}>
                    {branchName}
                  </SelectItem>
                ))}
                <SelectItem value={STARTING_BRANCH_CUSTOM_VALUE}>Custom</SelectItem>
              </SelectContent>
            </Select>
            {customBranchMode ? (
              <div className="space-y-2 pt-1">
                <div className="space-y-1">
                  <Label htmlFor="pipeline-task-custom-working-branch" className="text-muted-foreground text-xs">
                    Working Branch Override
                  </Label>
                  <Input
                    id="pipeline-task-custom-working-branch"
                    value={startingGitBranchOverride}
                    onChange={(event) => {
                      setCustomBranchMode(true)
                      onStartingGitBranchOverrideChange(event.target.value)
                    }}
                    placeholder={`Add dependent working branch: e.g ${normalizedJiraKey || "TASK-1"}`}
                    disabled={isMutating || !hasValidWorkspaceSelection}
                  />
                </div>
                {availableTicketBranchSuggestions.length > 0 ? (
                  <div className="space-y-1">
                    <p className="text-muted-foreground text-xs">Use an existing pipeline ticket branch:</p>
                    <div className="flex flex-wrap gap-1.5">
                      {availableTicketBranchSuggestions.map((ticketKey) => {
                        const isSelected = normalizedStartingBranchOverride === ticketKey
                        const isCurrentPipelineTicket = currentPipelineTicketKeySet.has(ticketKey)
                        const chipColor = isSelected || isCurrentPipelineTicket ? "info" : "grey"
                        const chipVariant = isSelected ? "filled" : "outline"

                        return (
                          <button
                            key={ticketKey}
                            type="button"
                            onClick={() => {
                              setCustomBranchMode(true)
                              onStartingGitBranchOverrideChange(ticketKey)
                            }}
                            disabled={isMutating || !hasValidWorkspaceSelection}
                            className="cursor-pointer disabled:cursor-not-allowed"
                          >
                            <Chip color={chipColor} variant={chipVariant}>
                              {ticketKey}
                            </Chip>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            <p className="text-muted-foreground text-xs">
              Priority: task override, then Git action target branch, then Git page default working branch.
              {gitCurrentBranch ? ` Current workspace branch: ${gitCurrentBranch}.` : ""}
            </p>
            {gitBranchesError ? (
              <p className="text-rose-700 text-xs">{gitBranchesError}</p>
            ) : null}
          </div>

          <div className="space-y-4 border-t pt-5">
            <div className="space-y-2">
              <Label className="text-muted-foreground text-xs">Task Type</Label>

              <Select
                value={taskRelation}
                onValueChange={(value) => {
                  if (value === "task" || value === "subtask") {
                    onTaskRelationChange(value)
                    if (value === "task") {
                      onDependencyKeyChange("")
                    }
                  }
                }}
                disabled={isMutating}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select task type" />
                </SelectTrigger>

                <SelectContent className="z-[80]">
                  <SelectItem value="task">Task</SelectItem>
                  <SelectItem value="subtask">Subtask</SelectItem>
                </SelectContent>
              </Select>

              <p className="text-muted-foreground text-xs">
                {taskSource === "spec"
                  ? "New SPECs default to Task. Choose Subtask only when this SPEC depends on another open task."
                  : "Determines which Git action hooks run for this ticket during pipeline execution."}
              </p>
            </div>

            {taskSource === "spec" && taskRelation === "subtask" ? (
              <div className="space-y-2 rounded-md border bg-muted/10 p-3">
                <Label className="text-muted-foreground text-xs">Depends On (Required)</Label>

                <Select
                  value={normalizedDependencyKey || DEPENDENCY_NONE_VALUE}
                  onValueChange={(value) => {
                    onDependencyKeyChange(value === DEPENDENCY_NONE_VALUE ? "" : value)
                  }}
                  disabled={isMutating}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select task or SPEC dependency" />
                  </SelectTrigger>

                  <SelectContent className="z-[90]">
                    <SelectItem value={DEPENDENCY_NONE_VALUE}>Select dependency</SelectItem>

                    {availableDependencyOptions.map((option) => (
                      <SelectItem key={`dependency-option-${option.key}`} value={option.key}>
                        {option.key} · {option.source === "spec" ? "SPEC" : "TICKET"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {availableDependencyOptions.length === 0 ? (
                  <p className="text-muted-foreground text-xs">No open SPECs/tickets available.</p>
                ) : null}

                {normalizedDependencyKey ? (
                  <div className="flex flex-wrap gap-1">
                    {availableDependencyOptions
                      .filter((option) => option.key === normalizedDependencyKey)
                      .map((option) => (
                        <Chip key={`dependency-chip-${option.key}`} color={option.source === "spec" ? "info" : "grey"} variant="outline">
                          {option.key}
                        </Chip>
                      ))}
                  </div>
                ) : (
                  <p className="text-amber-700 text-xs">Select one dependency to continue.</p>
                )}
              </div>
            ) : null}
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!canConfirm} onClick={onConfirm}>
            {isMutating ? <Loader2 className="animate-spin" /> : null}
            Move to Task Queue
          </Button>
        </div>
      </div>
    </div>
  )
}
