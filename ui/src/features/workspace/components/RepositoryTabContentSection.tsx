import { FolderGit2 } from 'lucide-react'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { WorkspaceGitStatus } from '@/shared/components/workspace-git-status'
import type { WorkspaceGitStatus as WorkspaceGitStatusData } from '@/features/git/types'
import { ActiveWorkspaceBranchCard } from './ActiveWorkspaceBranchCard'
import { ProjectCard } from './ProjectCard'
import type { Workspace, WorkspaceProject } from '../types'

interface RepositoryTabContentSectionProps {
  selectedWorkspace: Workspace | null
  selectedWorkspacePath: string
  projects: WorkspaceProject[]
  projectsLoading: boolean
  cloningIds: Set<string>
  repositoryTabEnabled: boolean
  workspaceBranchRefreshSignal: number
  gitStatus: WorkspaceGitStatusData | null
  isGitStatusLoading: boolean
  gitStatusError: string | null
  onCloneProject: (projectId: string) => Promise<void>
  onRemoveProject: (projectId: string) => Promise<void>
  onRefreshGitStatus: () => void
  showWorkspaceSummary?: boolean
  showActiveWorkspaceBranch?: boolean
}

export function RepositoryTabContentSection({
  selectedWorkspace,
  selectedWorkspacePath,
  projects,
  projectsLoading,
  cloningIds,
  repositoryTabEnabled,
  workspaceBranchRefreshSignal,
  gitStatus,
  isGitStatusLoading,
  gitStatusError,
  onCloneProject,
  onRemoveProject,
  onRefreshGitStatus,
  showWorkspaceSummary = true,
  showActiveWorkspaceBranch = true,
}: RepositoryTabContentSectionProps) {
  return (
    <>
      {showWorkspaceSummary && selectedWorkspace ? (
        <section className='space-y-4'>
          <div className='flex items-center justify-between gap-4'>
            <div className='flex items-center gap-2'>
              <FolderGit2 className='size-4 text-muted-foreground' />
              <span className='font-medium'>{selectedWorkspace.name}</span>
              <span className='text-xs text-muted-foreground'>- Repositories</span>
            </div>
          </div>

          {projectsLoading ? (
            <div className='grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3'>
              {Array.from({ length: 2 }).map((_, index) => (
                <Skeleton key={index} className='h-36 rounded-lg' />
              ))}
            </div>
          ) : projects.length > 0 ? (
            <div className='grid grid-cols-1 lg:grid-cols-2 gap-3 lg:items-stretch'>
              <div className='h-full'>
                <div className='grid grid-cols-1 gap-3 h-full auto-rows-fr'>
                  {projects.map((project) => (
                    <ProjectCard
                      key={project.id}
                      project={project}
                      onClone={() => {
                        void onCloneProject(project.id)
                      }}
                      onRemove={() => {
                        void onRemoveProject(project.id)
                      }}
                      isCloning={cloningIds.has(project.id)}
                    />
                  ))}
                </div>
              </div>

              <div className='h-full'>
                <WorkspaceGitStatus
                  gitStatus={gitStatus}
                  isLoading={isGitStatusLoading}
                  error={gitStatusError}
                  onRefresh={onRefreshGitStatus}
                  className='h-full'
                  showBranchAndChangeChips={false}
                />
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {showActiveWorkspaceBranch && repositoryTabEnabled ? (
        <ActiveWorkspaceBranchCard
          workspacePath={selectedWorkspacePath}
          refreshSignal={workspaceBranchRefreshSignal}
        />
      ) : null}
    </>
  )
}
