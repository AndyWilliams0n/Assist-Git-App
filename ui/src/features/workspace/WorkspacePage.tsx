import * as React from 'react'
import { SiteSubheader } from '@/shared/components/site-subheader.tsx'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { formatGitPlatformLabel } from '@/features/git/constants'
import { useGitStatus } from '@/features/git/hooks/useGitStatus'
import { WorkspaceGitStatus } from '@/shared/components/workspace-git-status'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import { useWorkspaces } from './hooks/useWorkspaces'
import { useWorkspaceProjects } from './hooks/useWorkspaceProjects'
import { useGitHubSettings } from './hooks/useGitHubRepos'
import { useGitLabSettings } from './hooks/useGitLabRepos'
import { AddWorkspaceDialog } from './components/AddWorkspaceDialog'
import { AddProjectDialog } from './components/AddProjectDialog'
import { WorkspacePageHeader } from './components/WorkspacePageHeader'
import { WorkspaceTabContentSection } from './components/WorkspaceTabContentSection'
import { RepositoryTabContentSection } from './components/RepositoryTabContentSection'
import { ConnectedPlatformsSection } from './components/ConnectedPlatformsSection'
import { WorkspaceActivationDialog } from './components/WorkspaceActivationDialog'
import { useWorkspaceStore, type WorkspaceTabValue } from './store/workspace-store'
import type { Workspace } from './types'

function formatWorkspacePathForDialog(path: string) {
  const normalized = path.replace(/\\/g, '/').replace(/\/+$/, '')

  if (!normalized) {
    return '.'
  }

  if (!normalized.startsWith('/')) {
    return normalized.startsWith('.') ? normalized : `./${normalized}`
  }

  const segments = normalized.split('/').filter(Boolean)
  const relativeSegments = segments.slice(-3)

  return `./${relativeSegments.join('/')}`
}

export default function WorkspacePage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const workspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)
  const selectedWorkspaceId = useWorkspaceStore((state) => state.selectedWorkspaceId)
  const setSelectedWorkspaceId = useWorkspaceStore((state) => state.setSelectedWorkspaceId)
  const allProjects = useWorkspaceStore((state) => state.projects)
  const activeTab = useWorkspaceStore((state) => state.activeTab)
  const setActiveTab = useWorkspaceStore((state) => state.setActiveTab)
  const { workspaces, isLoading, createWorkspace, deleteWorkspace, activateWorkspace } = useWorkspaces()
  const githubSettings = useGitHubSettings()
  const gitlabSettings = useGitLabSettings()
  const hasGitHubToken = Boolean(githubSettings.settings?.has_token)
  const hasGitLabToken = Boolean(gitlabSettings.settings?.has_token)
  const selectedWorkspace = workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null
  const selectedWorkspacePath = selectedWorkspace?.path ?? workspacePath
  const {
    projects,
    isLoading: projectsLoading,
    cloneProject,
    addProjectToWorkspace,
    removeProjectFromWorkspace,
  } = useWorkspaceProjects(selectedWorkspaceId)
  const {
    gitStatus,
    isLoading: isGitStatusLoading,
    error: gitStatusError,
    refetch: refetchGitStatus,
  } = useGitStatus(selectedWorkspacePath)
  const selectedWorkspaceGitLinked = Boolean(
    selectedWorkspace &&
      gitStatus?.is_git_repo &&
      (String(gitStatus.remote_url || '').trim() || (gitStatus.remotes?.length ?? 0) > 0)
  )
  const repositoryTabEnabled = Boolean(selectedWorkspace && (projects.length > 0 || selectedWorkspaceGitLinked))
  const [showAddWorkspace, setShowAddWorkspace] = React.useState(false)
  const [showAddProject, setShowAddProject] = React.useState(false)
  const [addProjectInitialTab, setAddProjectInitialTab] = React.useState<'github' | 'gitlab' | 'manual'>('github')
  const [cloningIds, setCloningIds] = React.useState<Set<string>>(new Set())
  const [pendingActivationWorkspace, setPendingActivationWorkspace] = React.useState<Workspace | null>(null)
  const [isConfirmingActivation, setIsConfirmingActivation] = React.useState(false)
  const [activationError, setActivationError] = React.useState<string | null>(null)
  const [workspaceBranchRefreshSignal, setWorkspaceBranchRefreshSignal] = React.useState(0)

  React.useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Workspaces', href: '/workspace' },
    ])
  }, [setBreadcrumbs])

  React.useEffect(() => {
    if (!selectedWorkspaceId) {
      const activeWorkspace = workspaces.find((workspace) => workspace.is_active === 1)

      if (activeWorkspace) {
        setSelectedWorkspaceId(activeWorkspace.id)
      }
    }
  }, [workspaces, selectedWorkspaceId, setSelectedWorkspaceId])

  React.useEffect(() => {
    if (!repositoryTabEnabled && activeTab === 'repository') {
      setActiveTab('workspace')
    }
  }, [activeTab, repositoryTabEnabled, setActiveTab])

  const handleClone = async (projectId: string) => {
    setCloningIds((previous) => new Set(previous).add(projectId))

    try {
      const result = await cloneProject(projectId)

      if (!result.ok) {
        console.error('Clone failed:', result.error)
      }
    } finally {
      setCloningIds((previous) => {
        const next = new Set(previous)
        next.delete(projectId)
        return next
      })
    }
  }

  const getProjectCount = (workspaceId: string) => (allProjects[workspaceId] ?? []).length

  const openAddRepoDialogForWorkspace = (workspaceId: string, platform: 'github' | 'gitlab') => {
    setSelectedWorkspaceId(workspaceId)
    setAddProjectInitialTab(platform)
    setShowAddProject(true)
  }

  const handleWorkspaceActivateIntent = React.useCallback(
    (workspace: Workspace) => {
      if (workspace.is_active === 1) {
        setSelectedWorkspaceId(workspace.id)
        return
      }

      setActivationError(null)
      setPendingActivationWorkspace(workspace)
    },
    [setSelectedWorkspaceId]
  )

  const confirmWorkspaceActivation = React.useCallback(async () => {
    if (!pendingActivationWorkspace) {
      return
    }

    setIsConfirmingActivation(true)
    setActivationError(null)

    try {
      await activateWorkspace(pendingActivationWorkspace.id)
      setPendingActivationWorkspace(null)
    } catch (error) {
      setActivationError(error instanceof Error ? error.message : 'Failed to activate workspace')
    } finally {
      setIsConfirmingActivation(false)
    }
  }, [activateWorkspace, pendingActivationWorkspace])

  const closeActivationDialog = React.useCallback(() => {
    setPendingActivationWorkspace(null)
    setActivationError(null)
  }, [])

  const handleWorkspaceGitStatusRefresh = React.useCallback(() => {
    refetchGitStatus()
    setWorkspaceBranchRefreshSignal((previous) => previous + 1)
  }, [refetchGitStatus])

  const repositoryHostLabel = React.useMemo(() => {
    const statusPlatform = String(gitStatus?.platform || '').trim().toLowerCase()

    if (statusPlatform && statusPlatform !== 'unknown' && statusPlatform !== 'auto') {
      return formatGitPlatformLabel(statusPlatform)
    }

    const firstProjectPlatform = String(projects[0]?.platform || '').trim().toLowerCase()

    if (firstProjectPlatform && firstProjectPlatform !== 'unknown') {
      return formatGitPlatformLabel(firstProjectPlatform)
    }

    return 'Git Host'
  }, [gitStatus?.platform, projects])

  const formattedActivationPath = pendingActivationWorkspace
    ? formatWorkspacePathForDialog(pendingActivationWorkspace.path)
    : '.'

  return (
    <div className='flex flex-1 flex-col min-h-0 w-full'>
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as WorkspaceTabValue)}
        className='flex min-h-0 flex-1 flex-col gap-0'
      >
        <SiteSubheader>
          <TabsList variant='line'>
            <TabsTrigger value='workspace'>WORKSPACE</TabsTrigger>
            <TabsTrigger value='repository' disabled={!repositoryTabEnabled}>
              REPOSITORY
            </TabsTrigger>
            <TabsTrigger value='all-repositories'>ALL REPOSITORIES</TabsTrigger>
          </TabsList>
        </SiteSubheader>

        <div className='w-full px-6 py-6 space-y-6 overflow-y-auto'>
          <WorkspacePageHeader
            activeTab={activeTab}
            repositoryHostLabel={repositoryHostLabel}
            selectedWorkspace={selectedWorkspace}
            onAddWorkspace={() => setShowAddWorkspace(true)}
          />

          <TabsContent value='workspace' className='mt-0'>
            <WorkspaceTabContentSection
              workspaces={workspaces}
              isLoading={isLoading}
              hasGitHubToken={hasGitHubToken}
              hasGitLabToken={hasGitLabToken}
              selectedWorkspaceId={selectedWorkspaceId}
              selectedWorkspaceGitLinked={selectedWorkspaceGitLinked}
              getProjectCount={getProjectCount}
              onResetWorkspaceSelection={() => setSelectedWorkspaceId(null)}
              onCreateWorkspace={() => setShowAddWorkspace(true)}
              onDeleteWorkspace={deleteWorkspace}
              onActivateWorkspace={handleWorkspaceActivateIntent}
              onOpenAddRepoDialog={openAddRepoDialogForWorkspace}
            />
          </TabsContent>

          <TabsContent value='repository' className='mt-0 space-y-6'>
            <RepositoryTabContentSection
              selectedWorkspace={selectedWorkspace}
              selectedWorkspacePath={selectedWorkspacePath}
              projects={projects}
              projectsLoading={projectsLoading}
              cloningIds={cloningIds}
              repositoryTabEnabled={repositoryTabEnabled}
              workspaceBranchRefreshSignal={workspaceBranchRefreshSignal}
              gitStatus={gitStatus}
              isGitStatusLoading={isGitStatusLoading}
              gitStatusError={gitStatusError}
              onCloneProject={handleClone}
              onRemoveProject={removeProjectFromWorkspace}
              onRefreshGitStatus={handleWorkspaceGitStatusRefresh}
              showActiveWorkspaceBranch={false}
            />
          </TabsContent>

          <TabsContent value='all-repositories' className='mt-0 space-y-6'>
            <WorkspaceGitStatus
              gitStatus={gitStatus}
              isLoading={isGitStatusLoading}
              error={gitStatusError}
              onRefresh={handleWorkspaceGitStatusRefresh}
            />

            <ConnectedPlatformsSection />
          </TabsContent>
        </div>
      </Tabs>

      <AddWorkspaceDialog
        open={showAddWorkspace}
        onOpenChange={setShowAddWorkspace}
        onSubmit={async (name, path, description) => {
          const workspace = await createWorkspace(name, path, description)
          setSelectedWorkspaceId(workspace.id)
        }}
      />

      <AddProjectDialog
        open={showAddProject}
        onOpenChange={setShowAddProject}
        workspacePath={selectedWorkspace?.path ?? workspacePath}
        initialTab={addProjectInitialTab}
        onSubmit={async (data) => {
          const createdProject = await addProjectToWorkspace(data)
          const cloneResult = await cloneProject(createdProject.id, { wipeExisting: true })

          if (!cloneResult.ok) {
            throw new Error(cloneResult.error || 'Repository added, but clone failed')
          }
        }}
      />

      <WorkspaceActivationDialog
        pendingWorkspace={pendingActivationWorkspace}
        isConfirmingActivation={isConfirmingActivation}
        activationError={activationError}
        formattedWorkspacePath={formattedActivationPath}
        onConfirm={() => {
          void confirmWorkspaceActivation()
        }}
        onClose={closeActivationDialog}
      />
    </div>
  )
}
