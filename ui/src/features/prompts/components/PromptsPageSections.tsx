import { FileText, type LucideIcon, Sparkles } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Textarea } from '@/shared/components/ui/textarea'
import { Chip } from '@/shared/components/chip'

import FileTreePanel from '@/features/prompts/components/FileTreePanel'
import PromptPanel from '@/features/prompts/components/PromptPanel'
import SpecDocumentPanel from '@/features/prompts/components/SpecDocumentPanel'
import { SpecHistoryPanel } from '@/features/prompts/components/PromptPanelSections'
import type { WorkspaceReferenceContextItem } from '@/features/prompts/utils/workspace-references'
import type {
  FileTreeSnapshot,
  PromptHistoryEntry,
  SaveState,
  SpecContentState,
  SpecTab,
} from '@/features/prompts/types'
import type { WorkflowSpecTask } from '@/features/workflow-tasks/types'
import type { AgentStatus } from '@/shared/types/agents'

export type PromptsColumnKey = 'left' | 'center' | 'right'

export type ColumnToggleOption = {
  key: PromptsColumnKey
  label: string
  icon: LucideIcon
}

type PromptsPageHeaderProps = {
  promptMode: 'create' | 'edit'
  columnToggleOptions: ColumnToggleOption[]
  columnVisibility: Record<PromptsColumnKey, boolean>
  visibleColumns: PromptsColumnKey[]
  specName: string
  secondaryWorkspacePath: string | null
  isSpecInWorkflowTasks: boolean
  shouldShowAddToTasksButton: boolean
  isAddingSpecTask: boolean
  onToggleColumnVisibility: (column: PromptsColumnKey) => void
  onOpenSecondaryWorkspaceDialog: () => void
  onClearSecondaryWorkspace: () => void
  onOpenImportBundleDialog: () => void
  onNewSpec: () => void
  onOpenWorkflowSpecsTab: () => void
  onOpenAddTaskDialog: () => void
}

export function PromptsPageHeader({
  promptMode,
  columnToggleOptions,
  columnVisibility,
  visibleColumns,
  specName,
  secondaryWorkspacePath,
  isSpecInWorkflowTasks,
  shouldShowAddToTasksButton,
  isAddingSpecTask,
  onToggleColumnVisibility,
  onOpenSecondaryWorkspaceDialog,
  onClearSecondaryWorkspace,
  onOpenImportBundleDialog,
  onNewSpec,
  onOpenWorkflowSpecsTab,
  onOpenAddTaskDialog,
}: PromptsPageHeaderProps) {
  return (
    <div className='bg-background/70 flex items-center justify-between border-b px-5 py-3 backdrop-blur md:px-6'>
      <div className='flex items-center gap-3'>
        <div className='bg-primary/10 text-primary flex size-9 items-center justify-center rounded-lg'>
          <Sparkles className='size-5' />
        </div>

        <div>
          <h1 className='text-lg font-semibold md:text-xl'>Create A Spec</h1>

          <p className='text-muted-foreground text-xs md:text-sm'>Generate, refine, and save spec bundles.</p>

          <div className='mt-1'>
            <Chip
              color={promptMode === 'edit' ? 'warning' : 'info'}
              variant='outline'
              className='rounded-full px-2 py-0.5 text-[10px]'
            >
              {promptMode === 'edit' ? 'Edit Mode' : 'Create Mode'}
            </Chip>
          </div>
        </div>
      </div>

      <div className='flex items-center gap-2'>
        <div className='flex items-center gap-1'>
          {columnToggleOptions.map((toggleOption) => {
            const Icon = toggleOption.icon
            const isVisible = columnVisibility[toggleOption.key]
            const isOnlyVisibleColumn = isVisible && visibleColumns.length === 1

            return (
              <Button
                key={toggleOption.key}
                type='button'
                size='xs'
                variant={isVisible ? 'secondary' : 'ghost'}
                aria-pressed={isVisible}
                aria-label={`${isVisible ? 'Hide' : 'Show'} ${toggleOption.label}`}
                title={`${isVisible ? 'Hide' : 'Show'} ${toggleOption.label}`}
                disabled={isOnlyVisibleColumn}
                onClick={() => onToggleColumnVisibility(toggleOption.key)}
              >
                <Icon className='size-3.5' />
                {toggleOption.label}
              </Button>
            )
          })}
        </div>

        <Chip color='grey' variant='outline' className='max-w-[14rem] truncate'>
          {specName ? `Spec: ${specName}` : 'No spec generated yet'}
        </Chip>

        <Button
          type='button'
          size='sm'
          variant='outline'
          onClick={onOpenImportBundleDialog}
        >
          Import Bundle
        </Button>

        <Button
          type='button'
          size='sm'
          variant='outline'
          onClick={() => {
            if (secondaryWorkspacePath?.trim()) {
              onClearSecondaryWorkspace()
              return
            }

            onOpenSecondaryWorkspaceDialog()
          }}
        >
          {secondaryWorkspacePath?.trim() ? 'x Clear Reference Workspace' : '+ Add Reference Workspace'}
        </Button>

        <Button type='button' size='sm' onClick={onNewSpec}>
          + New Spec
        </Button>

        {isSpecInWorkflowTasks ? (
          <Button type='button' size='sm' variant='warning' onClick={onOpenWorkflowSpecsTab}>
            View Task
          </Button>
        ) : null}

        {!isSpecInWorkflowTasks && shouldShowAddToTasksButton ? (
          <Button
            type='button'
            size='sm'
            variant='success'
            disabled={isAddingSpecTask}
            onClick={onOpenAddTaskDialog}
          >
            + Add To Tasks
          </Button>
        ) : null}
      </div>
    </div>
  )
}

type PromptsPageColumnsProps = {
  columnVisibility: Record<PromptsColumnKey, boolean>
  gridTemplateColumns: string
  isLastVisibleColumn: (column: PromptsColumnKey) => boolean
  primaryWorkspacePath: string
  secondaryWorkspacePath: string | null
  activeTab: SpecTab
  specContent: SpecContentState
  isEditorGenerating: boolean
  editorLoadingMessage: string
  isSaving: boolean
  saveState: SaveState
  shouldShowCenterEmptyState: boolean
  history: PromptHistoryEntry[]
  specName: string
  specNameError: string | null
  promptMode: 'create' | 'edit'
  specTasks: WorkflowSpecTask[]
  workflowSpecNames: ReadonlySet<string>
  isLoadingSpecBundles: boolean
  specBundlesError: string | null
  isGeneratingSpec: boolean
  isLoadingSelectedSpec: boolean
  deletingSpecName: string | null
  trackedAgents: AgentStatus[]
  agentsMode: 'streaming' | 'polling'
  isAgentsLoading: boolean
  agentsError: string | null
  error: string | null
  isHistoryVisible: boolean
  isAgentActivityVisible: boolean
  onPrimaryTreeSnapshotChange: (snapshot: FileTreeSnapshot) => void
  onSecondaryTreeSnapshotChange: (snapshot: FileTreeSnapshot) => void
  onTabChange: (tab: SpecTab) => void
  onEditorContentChange: (nextValue: string) => void
  onSave: () => void
  onSpecNameChange: (nextSpecName: string) => void
  onSelectSpecBundle: (specName: string) => void
  onDeleteSpecBundle: (
    specName: string,
    options?: { force?: boolean }
  ) => Promise<boolean> | boolean
  onFetchSpecBundle: (specName: string) => Promise<string | null>
  onToggleHistoryVisibility: () => void
  onToggleAgentActivityVisibility: () => void
  onSubmitPrompt: (payload: {
    prompt: string
    rawPrompt: string
    context: WorkspaceReferenceContextItem[]
  }) => Promise<void | false> | void | false
}

export function PromptsPageColumns({
  columnVisibility,
  gridTemplateColumns,
  isLastVisibleColumn,
  primaryWorkspacePath,
  secondaryWorkspacePath,
  activeTab,
  specContent,
  isEditorGenerating,
  editorLoadingMessage,
  isSaving,
  saveState,
  shouldShowCenterEmptyState,
  history,
  specName,
  specNameError,
  promptMode,
  specTasks,
  workflowSpecNames,
  isLoadingSpecBundles,
  specBundlesError,
  isGeneratingSpec,
  isLoadingSelectedSpec,
  deletingSpecName,
  trackedAgents,
  agentsMode,
  isAgentsLoading,
  agentsError,
  error,
  isHistoryVisible,
  isAgentActivityVisible,
  onPrimaryTreeSnapshotChange,
  onSecondaryTreeSnapshotChange,
  onTabChange,
  onEditorContentChange,
  onSave,
  onSpecNameChange,
  onSelectSpecBundle,
  onDeleteSpecBundle,
  onFetchSpecBundle,
  onToggleHistoryVisibility,
  onToggleAgentActivityVisibility,
  onSubmitPrompt,
}: PromptsPageColumnsProps) {
  return (
    <div className='min-h-0 flex-1 overflow-hidden'>
      <div className='grid h-full min-h-0' style={{ gridTemplateColumns }}>
        {columnVisibility.left ? (
          <div className={`flex h-full min-h-0 flex-col ${isLastVisibleColumn('left') ? '' : 'border-r'}`}>
            <div className='min-h-0 flex-1'>
              {secondaryWorkspacePath?.trim() ? (
                <div className='grid h-full min-h-0 grid-rows-2'>
                  <div className='min-h-0 border-b'>
                    <FileTreePanel
                      workspacePath={primaryWorkspacePath}
                      workspaceRole='primary'
                      title='Output'
                      description={primaryWorkspacePath}
                      onTreeSnapshotChange={onPrimaryTreeSnapshotChange}
                      className='min-h-0'
                    />
                  </div>

                  <div className='min-h-0'>
                    <FileTreePanel
                      workspacePath={secondaryWorkspacePath}
                      workspaceRole='secondary'
                      title='Reference'
                      description={secondaryWorkspacePath}
                      readOnly
                      onTreeSnapshotChange={onSecondaryTreeSnapshotChange}
                      className='min-h-0'
                    />
                  </div>
                </div>
              ) : (
                <FileTreePanel
                  workspacePath={primaryWorkspacePath}
                  workspaceRole='primary'
                  title='Output'
                  description={primaryWorkspacePath}
                  onTreeSnapshotChange={onPrimaryTreeSnapshotChange}
                  className='min-h-0'
                />
              )}
            </div>

            {isHistoryVisible ? (
              <SpecHistoryPanel
                specTasks={specTasks}
                workflowSpecNames={workflowSpecNames}
                selectedSpecName={specName}
                isLoadingSpecBundles={isLoadingSpecBundles}
                specBundlesError={specBundlesError}
                deletingSpecName={deletingSpecName}
                onSelectSpecBundle={onSelectSpecBundle}
                onDeleteSpecBundle={onDeleteSpecBundle}
              />
            ) : null}
          </div>
        ) : null}

        {columnVisibility.center ? (
          <div className={`h-full min-h-0 ${isLastVisibleColumn('center') ? '' : 'border-r'}`}>
            {shouldShowCenterEmptyState ? (
              <PromptsPageCenterEmptyState />
            ) : (
              <SpecDocumentPanel
                activeTab={activeTab}
                content={specContent}
                isLoading={isEditorGenerating}
                loadingMessage={editorLoadingMessage}
                isSaving={isSaving}
                saveState={saveState}
                onTabChange={onTabChange}
                onContentChange={onEditorContentChange}
                onSave={onSave}
                className='min-h-0'
              />
            )}
          </div>
        ) : null}

        {columnVisibility.right ? (
          <div className='h-full min-h-0'>
            <PromptPanel
              primaryWorkspacePath={primaryWorkspacePath}
              secondaryWorkspacePath={secondaryWorkspacePath}
              history={history}
              specName={specName}
              specNameError={specNameError}
              promptMode={promptMode}
              isProcessing={isGeneratingSpec}
              isLoadingSpec={isLoadingSelectedSpec}
              agentStatuses={trackedAgents}
              agentsMode={agentsMode}
              isAgentsLoading={isAgentsLoading}
              agentsError={agentsError}
              error={error}
              isHistoryVisible={isHistoryVisible}
              isActivityVisible={isAgentActivityVisible}
              onSpecNameChange={onSpecNameChange}
              onFetchSpecBundle={onFetchSpecBundle}
              onSubmit={onSubmitPrompt}
              onToggleHistoryVisibility={onToggleHistoryVisibility}
              onToggleActivityVisibility={onToggleAgentActivityVisibility}
              className='min-h-0'
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}

type AddSpecTaskDialogProps = {
  isOpen: boolean
  isAddingSpecTask: boolean
  specName: string
  specTaskSummary: string
  canSubmitSpecTaskSummary: boolean
  onOpenChange: (nextOpen: boolean) => void
  onSpecTaskSummaryChange: (nextSummary: string) => void
  onCancel: () => void
  onConfirm: () => void
}

export function AddSpecTaskDialog({
  isOpen,
  isAddingSpecTask,
  specName,
  specTaskSummary,
  canSubmitSpecTaskSummary,
  onOpenChange,
  onSpecTaskSummaryChange,
  onCancel,
  onConfirm,
}: AddSpecTaskDialogProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>Add Spec Task</DialogTitle>

          <DialogDescription>
            Set a clear summary for <span className='font-medium'>{specName || 'this spec'}</span>. This text is shown wherever the task appears.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-2'>
          <label className='text-sm font-medium' htmlFor='spec-task-summary-input'>
            Task Summary
          </label>

          <Textarea
            id='spec-task-summary-input'
            value={specTaskSummary}
            rows={5}
            placeholder='Describe the expected outcome for this spec task...'
            disabled={isAddingSpecTask}
            onChange={(event) => {
              onSpecTaskSummaryChange(event.target.value)
            }}
          />
        </div>

        <DialogFooter>
          <Button type='button' variant='outline' disabled={isAddingSpecTask} onClick={onCancel}>
            Cancel
          </Button>

          <Button
            type='button'
            variant='success'
            disabled={isAddingSpecTask || !canSubmitSpecTaskSummary}
            onClick={onConfirm}
          >
            {isAddingSpecTask ? 'Adding...' : 'Add Task'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PromptsPageCenterEmptyState() {
  return (
    <section className='relative flex h-full min-h-0 items-center justify-center px-6 py-10'>
      <div className='pointer-events-none absolute inset-0' />

      <div className='relative z-10 flex w-full max-w-md flex-col items-center rounded-2xl px-8 py-10 text-center opacity-20'>
        <div className='mb-4 flex size-12 items-center justify-center'>
          <FileText className='size-12' />
        </div>

        <h2 className='text-xl font-semibold tracking-tight'>No Spec</h2>

        <p className='mt-2 text-sm'>Please generate a spec or load one from history.</p>
      </div>
    </section>
  )
}
