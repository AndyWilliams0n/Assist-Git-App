import * as React from 'react'
import { AlertCircle, BookOpen, Bot, CheckCircle, Clock3, Eye, GripVertical, Loader2, Trash2, User } from 'lucide-react'

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
import { ScrollArea } from '@/shared/components/ui/scroll-area'
import { cn } from '@/shared/utils/utils.ts'
import { Chip } from '@/shared/components/chip'
import WorkspaceMentionPromptInput from '@/shared/components/workspace-mention-prompt-input'
import type { AgentStatus } from '@/shared/types/agents'
import type { PromptHistoryEntry } from '@/features/prompts/types'
import type { WorkflowSpecTask } from '@/features/workflow-tasks/types'
import {
  SPEC_BUNDLE_DRAG_MIME_TYPE,
  serializeSpecBundleDragPayload,
  type WorkspaceReferenceContextItem,
} from '@/features/prompts/utils/workspace-references'

const formatTimestamp = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

type PromptHistorySectionProps = {
  history: PromptHistoryEntry[]
  specName: string
  isProcessing: boolean
  isLoadingSpec: boolean
  error: string | null
  endRef: React.RefObject<HTMLDivElement | null>
}

export function PromptHistorySection({
  history,
  specName,
  isProcessing,
  isLoadingSpec,
  error,
  endRef,
}: PromptHistorySectionProps) {
  return (
    <div className="min-h-0 flex-1 border-b">
      <ScrollArea className="h-full px-3 py-3">
        <div className="space-y-2 pb-4">
          {history.length === 0 ? (
            isProcessing ? (
              <p className="text-muted-foreground px-1 py-2 text-sm">
                Generating {specName ? <strong>{specName}</strong> : "SDD bundle"}... agent activity and files will update shortly.
              </p>
            ) : isLoadingSpec ? (
              <p className="text-muted-foreground px-1 py-2 text-sm">
                Loading selected spec...
              </p>
            ) : (
              <p className="text-muted-foreground px-1 py-2 text-sm">
                Submit a prompt to start generating an SDD bundle.
              </p>
            )
          ) : (
            history.map((entry) => (
              <div
                key={entry.id}
                className={cn(
                  "rounded-lg border px-3 py-2 text-sm",
                  entry.type === "user"
                    ? "border-primary/30 bg-primary/5"
                    : "border-border bg-muted/30"
                )}
              >
                <div className="text-muted-foreground mb-1 flex items-center justify-between gap-2 text-xs">
                  <span className="inline-flex items-center gap-1.5">
                    {entry.type === "user" ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
                    {entry.type === "user" ? "You" : "System"}
                  </span>

                  <span className="inline-flex items-center gap-1">
                    <Clock3 className="size-3.5" />
                    {formatTimestamp(entry.timestamp)}
                  </span>
                </div>

                <p className="leading-relaxed break-words">{entry.message}</p>
              </div>
            ))
          )}

          {error && !isProcessing ? <p className="px-1 py-1 text-xs text-rose-600">{error}</p> : null}

          <div ref={endRef} />
        </div>
      </ScrollArea>
    </div>
  )
}

type PromptComposerSectionProps = {
  primaryWorkspacePath: string
  secondaryWorkspacePath: string | null
  specName: string
  specNameError: string | null
  promptMode: "create" | "edit"
  isProcessing: boolean
  isLoadingSpec: boolean
  shouldExpandComposer: boolean
  onSpecNameChange: (nextSpecName: string) => void
  onFetchSpecBundle: (specName: string) => Promise<string | null>
  onSubmit: (payload: { prompt: string; rawPrompt: string; context: WorkspaceReferenceContextItem[] }) => Promise<void | false> | void | false
}

export function PromptComposerSection({
  primaryWorkspacePath,
  secondaryWorkspacePath,
  specName,
  specNameError,
  promptMode,
  isProcessing,
  isLoadingSpec,
  shouldExpandComposer,
  onSpecNameChange,
  onFetchSpecBundle,
  onSubmit,
}: PromptComposerSectionProps) {
  const specNameIsValid = !specNameError && specName.trim().length > 0

  return (
    <div className={cn("border-b p-4", shouldExpandComposer && "flex min-h-0 flex-1 flex-col")}>
      <div className="mb-2 shrink-0">
        <label className="mb-1 block text-xs font-medium" htmlFor="sdd-spec-name-input">
          Spec Folder Name
        </label>

        <Input
          id="sdd-spec-name-input"
          value={specName}
          disabled={isLoadingSpec || isProcessing || promptMode === "edit"}
          placeholder="SPEC-1"
          className={cn(
            "h-8",
            specNameError
              ? "border-red-500 focus-visible:ring-red-500"
              : specNameIsValid
                ? "border-green-500 focus-visible:ring-green-500"
                : ""
          )}
          onChange={(event) => {
            onSpecNameChange(event.target.value)
          }}
        />

        <div className="mb-3 mt-1 min-h-[1.1rem]">
          {specNameError ? (
            <p className="flex items-center gap-1 text-xs text-red-500">
              <AlertCircle className="size-3 shrink-0" />
              {specNameError}
            </p>
          ) : specNameIsValid ? (
            <p className="flex items-center gap-1 text-xs text-green-600">
              <CheckCircle className="size-3 shrink-0" />
              Looks good
            </p>
          ) : (
            <p className="text-muted-foreground text-xs">
              Letters, numbers and hyphens only — e.g. SPEC-1
            </p>
          )}
        </div>

        <div className="mb-1 flex items-center justify-between gap-2">
          <p className="text-sm font-medium">
            {promptMode === "edit" ? "Edit current SDD bundle" : "Ask the SDD planner"}
          </p>

          <Chip
            color={promptMode === "edit" ? "warning" : "info"}
            variant="outline"
            className="rounded-full px-2 py-0.5 text-[10px]"
          >
            {promptMode === "edit" ? "Edit Mode" : "Create Mode"}
          </Chip>
        </div>

        <p className="text-muted-foreground text-xs">
          {promptMode === "edit"
            ? "Edits target requirements.md, design.md, and tasks.md as one bundle."
            : "Drag files/folders in, type @ for workspace paths, paste code, or attach images."}
        </p>
      </div>

      <WorkspaceMentionPromptInput
        primaryWorkspacePath={primaryWorkspacePath}
        secondaryWorkspacePath={secondaryWorkspacePath || undefined}
        onSubmit={onSubmit}
        onFetchSpecBundle={onFetchSpecBundle}
        isProcessing={isLoadingSpec || isProcessing}
        mode={promptMode}
        className={cn(shouldExpandComposer && "min-h-0 flex-1")}
      />
    </div>
  )
}

type AgentActivitySectionProps = {
  agentStatuses: AgentStatus[]
  agentsMode: "streaming" | "polling"
  isAgentsLoading: boolean
  agentsError: string | null
}

export function AgentActivitySection({
  agentStatuses,
  agentsMode,
  isAgentsLoading,
  agentsError,
}: AgentActivitySectionProps) {
  return (
    <div className="border-b px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Agent Activity</p>

        <p className="text-muted-foreground text-xs">
          {agentsMode === "streaming" ? "SSE live" : "Polling fallback"}
        </p>
      </div>

      {agentsError ? (
        <p className="text-xs text-rose-600">{agentsError}</p>
      ) : isAgentsLoading && agentStatuses.length === 0 ? (
        <p className="text-muted-foreground text-xs">Loading agent activity...</p>
      ) : agentStatuses.length === 0 ? (
        <p className="text-muted-foreground text-xs">No tracked SDD agents found.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {agentStatuses.map((agent) => {
            const isActive = Boolean(agent.is_active) || Number(agent.in_flight || 0) > 0
            const health = String(agent.health || "").toLowerCase()
            const color = health === "degraded" || health === "unconfigured"
              ? "warning"
              : health && health !== "ok"
                ? "error"
                : isActive
                  ? "success"
                  : "grey"
            const statusLabel = isActive ? "active" : "idle"
            return (
              <Chip key={agent.id} color={color} variant="outline">
                {agent.name}: {statusLabel}
              </Chip>
            )
          })}
        </div>
      )}
    </div>
  )
}

type SpecHistorySectionProps = {
  specTasks: WorkflowSpecTask[]
  workflowSpecNames: ReadonlySet<string>
  selectedSpecName: string
  isLoadingSpecBundles: boolean
  specBundlesError: string | null
  deletingSpecName: string | null
  onSelectSpecBundle: (specName: string) => void
  onOpenDeleteDialog: (specName: string) => void
  onOpenGeneratingDeleteDialog: (specName: string) => void
}

export function SpecHistorySection({
  specTasks,
  workflowSpecNames,
  selectedSpecName,
  isLoadingSpecBundles,
  specBundlesError,
  deletingSpecName,
  onSelectSpecBundle,
  onOpenDeleteDialog,
  onOpenGeneratingDeleteDialog,
}: SpecHistorySectionProps) {
  return (
    <div className="max-h-64 overflow-hidden px-4 pt-3 pb-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Spec History</p>

        <p className="text-muted-foreground text-xs">
          {isLoadingSpecBundles ? 'Loading...' : `${specTasks.length} spec${specTasks.length === 1 ? '' : 's'}`}
        </p>
      </div>

      {specBundlesError ? (
        <p className="text-xs text-rose-600">{specBundlesError}</p>
      ) : specTasks.length === 0 ? (
        <p className="text-muted-foreground text-xs">No specs found. Generate one to get started.</p>
      ) : (
        <div className="max-h-44 overflow-y-auto pr-1">
          <div className="grid grid-cols-2 gap-1.5">
            {specTasks.map((task) => {
              const isGenerating = task.status === 'generating'
              const isAddedToWorkflow = workflowSpecNames.has(task.spec_name)
              const isSelected = task.spec_name === selectedSpecName

              if (isGenerating) {
                return (
                  <div
                    key={task.spec_name}
                    className="flex min-w-0 items-center gap-1"
                  >
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled
                      className="h-7 min-w-0 flex-1 border-blue-400 px-2 text-xs text-blue-500 opacity-100 dark:text-blue-400"
                    >
                      <Loader2 className="size-3 shrink-0 animate-spin" />

                      <span className="truncate">{task.spec_name}</span>
                    </Button>

                    <Button
                      type="button"
                      size="icon-xs"
                      variant="ghost"
                      className="text-muted-foreground hover:text-rose-600"
                      aria-label={`Delete ${task.spec_name}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        onOpenGeneratingDeleteDialog(task.spec_name)
                      }}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                )
              }

              return (
                <div
                  key={task.spec_name}
                  className="flex min-w-0 cursor-grab items-center gap-1 active:cursor-grabbing"
                  draggable
                  aria-label={`Drag ${task.spec_name} to prompt`}
                  title="Drag to chat input"
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = 'copy'
                    event.dataTransfer.setData(
                      SPEC_BUNDLE_DRAG_MIME_TYPE,
                      serializeSpecBundleDragPayload({
                        specName: task.spec_name,
                        specPath: task.spec_path,
                        requirementsPath: task.requirements_path,
                        designPath: task.design_path,
                        tasksPath: task.tasks_path,
                      })
                    )
                  }}
                >
                  <Button
                    type="button"
                    size="sm"
                    variant={isAddedToWorkflow ? 'success' : 'outline'}
                    className="h-7 min-w-0 flex-1 px-2 text-xs"
                    onClick={() => onSelectSpecBundle(task.spec_name)}
                  >
                    <GripVertical className="size-3 shrink-0 opacity-50" />

                    <BookOpen className="size-3 shrink-0" />

                    <span className="truncate">{task.spec_name}</span>

                    {isSelected ? (
                      <Eye
                        className={cn(
                          'size-3.5 shrink-0',
                          isAddedToWorkflow
                            ? 'text-white/90 dark:text-zinc-900/90'
                            : 'text-muted-foreground'
                        )}
                      />
                    ) : null}
                  </Button>

                  <Button
                    type="button"
                    size="icon-xs"
                    variant="ghost"
                    className="text-muted-foreground hover:text-rose-600"
                    aria-label={`Delete ${task.spec_name}`}
                    disabled={deletingSpecName === task.spec_name}
                    onClick={(event) => {
                      event.stopPropagation()
                      onOpenDeleteDialog(task.spec_name)
                    }}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

type SpecHistoryPanelProps = {
  specTasks: WorkflowSpecTask[]
  workflowSpecNames: ReadonlySet<string>
  selectedSpecName: string
  isLoadingSpecBundles: boolean
  specBundlesError: string | null
  deletingSpecName: string | null
  onSelectSpecBundle: (specName: string) => void
  onDeleteSpecBundle: (
    specName: string,
    options?: { force?: boolean }
  ) => Promise<boolean> | boolean
}

export function SpecHistoryPanel({
  specTasks,
  workflowSpecNames,
  selectedSpecName,
  isLoadingSpecBundles,
  specBundlesError,
  deletingSpecName,
  onSelectSpecBundle,
  onDeleteSpecBundle,
}: SpecHistoryPanelProps) {
  const [specNamePendingDelete, setSpecNamePendingDelete] = React.useState<string | null>(null)
  const [generatingSpecNameBlocked, setGeneratingSpecNameBlocked] = React.useState<string | null>(null)
  const [deleteError, setDeleteError] = React.useState<string | null>(null)
  const [generatingDeleteError, setGeneratingDeleteError] = React.useState<string | null>(null)

  const isDeleteDialogOpen = Boolean(specNamePendingDelete)
  const isGeneratingBlockDialogOpen = Boolean(generatingSpecNameBlocked)
  const isDeletingPendingSpec = Boolean(specNamePendingDelete && deletingSpecName === specNamePendingDelete)
  const isDeletingGeneratingSpec = Boolean(
    generatingSpecNameBlocked && deletingSpecName === generatingSpecNameBlocked
  )

  const handleOpenDeleteDialog = React.useCallback((nextSpecName: string) => {
    setDeleteError(null)
    setSpecNamePendingDelete(nextSpecName)
  }, [])

  const handleOpenGeneratingDeleteDialog = React.useCallback((nextSpecName: string) => {
    setGeneratingDeleteError(null)
    setGeneratingSpecNameBlocked(nextSpecName)
  }, [])

  const handleDeleteConfirm = React.useCallback(async () => {
    if (!specNamePendingDelete || isDeletingPendingSpec) return
    setDeleteError(null)
    const success = await onDeleteSpecBundle(specNamePendingDelete)

    if (success) {
      setSpecNamePendingDelete(null)
      return
    }

    setDeleteError('Failed to delete this spec bundle. Try again.')
  }, [isDeletingPendingSpec, onDeleteSpecBundle, specNamePendingDelete])

  const handleForceDeleteGeneratingSpec = React.useCallback(async () => {
    if (!generatingSpecNameBlocked || isDeletingGeneratingSpec) return

    setGeneratingDeleteError(null)

    const success = await onDeleteSpecBundle(generatingSpecNameBlocked, { force: true })

    if (success) {
      setGeneratingSpecNameBlocked(null)
      return
    }

    setGeneratingDeleteError('Failed to force delete this spec bundle. Try again.')
  }, [generatingSpecNameBlocked, isDeletingGeneratingSpec, onDeleteSpecBundle])

  const handleDialogOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (nextOpen) return
      if (isDeletingPendingSpec) return
      setDeleteError(null)
      setSpecNamePendingDelete(null)
    },
    [isDeletingPendingSpec]
  )

  return (
    <>
      <div className="border-t">
        <SpecHistorySection
          specTasks={specTasks}
          workflowSpecNames={workflowSpecNames}
          selectedSpecName={selectedSpecName}
          isLoadingSpecBundles={isLoadingSpecBundles}
          specBundlesError={specBundlesError}
          deletingSpecName={deletingSpecName}
          onSelectSpecBundle={onSelectSpecBundle}
          onOpenDeleteDialog={handleOpenDeleteDialog}
          onOpenGeneratingDeleteDialog={handleOpenGeneratingDeleteDialog}
        />
      </div>

      <DeleteSpecDialog
        isOpen={isDeleteDialogOpen}
        specNamePendingDelete={specNamePendingDelete}
        deleteError={deleteError}
        isDeletingPendingSpec={isDeletingPendingSpec}
        onOpenChange={handleDialogOpenChange}
        onConfirm={() => {
          void handleDeleteConfirm()
        }}
      />

      <Dialog
        open={isGeneratingBlockDialogOpen}
        onOpenChange={(open) => {
          if (open) return
          if (isDeletingGeneratingSpec) return
          setGeneratingDeleteError(null)
          setGeneratingSpecNameBlocked(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generation in progress</DialogTitle>

            <DialogDescription>
              <strong>{generatingSpecNameBlocked}</strong> is currently marked as generating. You can force delete it
              to remove the stuck entry now.
            </DialogDescription>
          </DialogHeader>

          {generatingDeleteError ? <p className="text-sm text-rose-600">{generatingDeleteError}</p> : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isDeletingGeneratingSpec}
              onClick={() => {
                setGeneratingDeleteError(null)
                setGeneratingSpecNameBlocked(null)
              }}
            >
              Cancel
            </Button>

            <Button
              type="button"
              variant="destructive"
              disabled={isDeletingGeneratingSpec}
              onClick={() => {
                void handleForceDeleteGeneratingSpec()
              }}
            >
              {isDeletingGeneratingSpec ? 'Force deleting...' : 'Force Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

type DeleteSpecDialogProps = {
  isOpen: boolean
  specNamePendingDelete: string | null
  deleteError: string | null
  isDeletingPendingSpec: boolean
  onOpenChange: (nextOpen: boolean) => void
  onConfirm: () => void
}

export function DeleteSpecDialog({
  isOpen,
  specNamePendingDelete,
  deleteError,
  isDeletingPendingSpec,
  onOpenChange,
  onConfirm,
}: DeleteSpecDialogProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete spec bundle?</DialogTitle>

          <DialogDescription>
            {specNamePendingDelete
              ? `This will permanently delete "${specNamePendingDelete}" and all spec files in that folder.`
              : "This will permanently delete this spec bundle and its files."}
          </DialogDescription>
        </DialogHeader>

        {deleteError ? <p className="text-sm text-rose-600">{deleteError}</p> : null}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={isDeletingPendingSpec}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>

          <Button
            type="button"
            variant="destructive"
            disabled={isDeletingPendingSpec}
            onClick={onConfirm}
          >
            {isDeletingPendingSpec ? "Deleting..." : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
