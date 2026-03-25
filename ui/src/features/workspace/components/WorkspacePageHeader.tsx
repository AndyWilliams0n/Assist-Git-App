import { FolderGit2, GitBranch, Layers, Plus } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import type { WorkspaceTabValue } from '../store/workspace-store'
import type { Workspace } from '../types'

interface WorkspacePageHeaderProps {
  activeTab: WorkspaceTabValue
  repositoryHostLabel: string
  selectedWorkspace: Workspace | null
  onAddWorkspace: () => void
}

export function WorkspacePageHeader({
  activeTab,
  repositoryHostLabel,
  selectedWorkspace,
  onAddWorkspace,
}: WorkspacePageHeaderProps) {
  const HeaderIcon = activeTab === 'workspace'
    ? Layers
    : activeTab === 'repository'
      ? FolderGit2
      : GitBranch

  const title = activeTab === 'workspace'
    ? 'Workspaces'
    : activeTab === 'repository'
      ? `Linked Repository On ${repositoryHostLabel}`
      : 'All Repositories'

  const description = activeTab === 'workspace'
    ? 'Manage workspaces and linked GitHub/GitLab repositories'
    : activeTab === 'repository'
      ? `${selectedWorkspace ? selectedWorkspace.name : 'Selected workspace'} repository management`
      : 'Browse repositories across your connected GitHub and GitLab accounts'

  return (
    <div className='flex items-start justify-between gap-4'>
      <div className='flex items-center gap-3'>
        <div className='size-9 flex items-center justify-center rounded-lg bg-primary/10 text-primary'>
          <HeaderIcon className='size-5' />
        </div>

        <div>
          <h1 className='text-xl font-semibold'>{title}</h1>

          <p className='text-sm text-muted-foreground'>{description}</p>
        </div>
      </div>

      {activeTab === 'workspace' ? (
        <div className='flex items-center gap-2'>
          <Button size='sm' className='gap-1.5 shrink-0' onClick={onAddWorkspace}>
            <Plus className='size-4' />
            New Workspace
          </Button>
        </div>
      ) : null}
    </div>
  )
}
