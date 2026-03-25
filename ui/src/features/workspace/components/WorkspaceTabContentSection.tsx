import { FolderOpen, Plus } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { WorkspaceCard } from './WorkspaceCard'
import type { Workspace } from '../types'

interface WorkspaceTabContentSectionProps {
  workspaces: Workspace[]
  isLoading: boolean
  hasGitHubToken: boolean
  hasGitLabToken: boolean
  selectedWorkspaceId: string | null
  selectedWorkspaceGitLinked: boolean
  getProjectCount: (workspaceId: string) => number
  onResetWorkspaceSelection: () => void
  onCreateWorkspace: () => void
  onDeleteWorkspace: (workspaceId: string) => Promise<void>
  onActivateWorkspace: (workspace: Workspace) => void
  onOpenAddRepoDialog: (workspaceId: string, platform: 'github' | 'gitlab') => void
}

export function WorkspaceTabContentSection({
  workspaces,
  isLoading,
  hasGitHubToken,
  hasGitLabToken,
  selectedWorkspaceId,
  selectedWorkspaceGitLinked,
  getProjectCount,
  onResetWorkspaceSelection,
  onCreateWorkspace,
  onDeleteWorkspace,
  onActivateWorkspace,
  onOpenAddRepoDialog,
}: WorkspaceTabContentSectionProps) {
  return (
    <section className='space-y-4'>
      <div className='flex items-center gap-2'>
        <button
          type='button'
          className='flex items-center gap-1.5 text-sm font-medium hover:text-foreground/80 transition-colors'
          onClick={onResetWorkspaceSelection}
        >
          <FolderOpen className='size-4' />
          Workspaces ({workspaces.length})
        </button>
      </div>

      {isLoading ? (
        <div className='grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3'>
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className='h-28 rounded-lg' />
          ))}
        </div>
      ) : workspaces.length === 0 ? (
        <div className='rounded-lg border border-dashed p-8 text-center'>
          <FolderOpen className='size-10 mx-auto text-muted-foreground/40 mb-3' />
          <p className='text-sm font-medium mb-1'>No workspaces yet</p>
          <p className='text-xs text-muted-foreground mb-4'>
            Create a workspace to organise your projects and repositories.
          </p>
          <Button size='sm' onClick={onCreateWorkspace} className='gap-1.5'>
            <Plus className='size-4' />
            New Workspace
          </Button>
        </div>
      ) : (
        <div className='grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3'>
          {workspaces.map((workspace) => {
            const projectCount = getProjectCount(workspace.id)
            const isSelectedWorkspace = selectedWorkspaceId === workspace.id
            const hasLinkedRepo = projectCount > 0 || (isSelectedWorkspace && selectedWorkspaceGitLinked)

            return (
              <WorkspaceCard
                key={workspace.id}
                workspace={workspace}
                projectCount={projectCount}
                hasLinkedRepo={hasLinkedRepo}
                onSelect={() => onActivateWorkspace(workspace)}
                onActivate={() => onActivateWorkspace(workspace)}
                onEdit={() => {
                  // TODO: edit dialog
                }}
                onDelete={() => {
                  void onDeleteWorkspace(workspace.id)
                }}
                canAddGithubRepo={hasGitHubToken}
                canAddGitlabRepo={hasGitLabToken}
                onAddGithubRepo={() => onOpenAddRepoDialog(workspace.id, 'github')}
                onAddGitlabRepo={() => onOpenAddRepoDialog(workspace.id, 'gitlab')}
              />
            )
          })}
        </div>
      )}
    </section>
  )
}
