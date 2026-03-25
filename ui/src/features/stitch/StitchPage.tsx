import * as React from 'react'
import { AlertCircle, Download, ExternalLink, Eye, FileCode2, RefreshCw } from 'lucide-react'

import { useGitStatus } from '@/features/git/hooks/useGitStatus'
import { DesignSystemPreview, type DesignSystemSnapshot } from '@/features/stitch/components/DesignSystemPreview'
import { SiteSubheader } from '@/shared/components/site-subheader.tsx'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'

type StitchStatus = {
  workspace_root: string
  is_git_repo: boolean
  repo_name: string
  linked: boolean
  project_id: string
  project_title: string
}

type StitchScreen = {
  screen_id: string
  name: string
  title: string
  screenshot_url: string
  html_url: string
  device_type?: string
  width?: number
  height?: number
}

type DownloadResult = {
  image_path?: string | null
  code_path?: string | null
}

type StitchDesignSystemResponse = {
  available: boolean
  design_md: string
  design_json: DesignSystemSnapshot | null
  design_md_path?: string
  assist_design_md_path?: string
  design_json_path?: string
  assist_design_json_path?: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const defaultStatus: StitchStatus = {
  workspace_root: '',
  is_git_repo: false,
  repo_name: '',
  linked: false,
  project_id: '',
  project_title: '',
}

const parseErrorDetails = (value: string): { title: string; message: string; stackTrace: string } => {
  const raw = String(value || '').trim()

  if (!raw) {
    return {
      title: 'Stitch error',
      message: 'Something went wrong while processing the Stitch request.',
      stackTrace: '',
    }
  }

  const summaryFromErrorToken = raw.match(/Error:\s*([^\n]+?)(?=\s+at\s|$)/)?.[1]?.trim() || ''
  const summaryFromFirstLine = raw.split('\n')[0]?.trim() || ''
  const summary = summaryFromErrorToken || summaryFromFirstLine
  const normalizedStack = raw
    .replace(/\s+at\s+/g, '\nat ')
    .replace(/(\^)\s+/g, '$1\n')
    .trim()

  if (summary.toLowerCase().includes('stitch_api_key') || summary.toLowerCase().includes('gemini_api_key')) {
    return {
      title: 'Stitch API key is missing',
      message: 'Set STITCH_API_KEY (or GEMINI_API_KEY) in your .env, then restart the backend.',
      stackTrace: normalizedStack,
    }
  }

  return {
    title: 'Stitch request failed',
    message: summary || 'The Stitch request did not complete successfully.',
    stackTrace: normalizedStack,
  }
}

export default function StitchPage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const workspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)
  const [activeTab, setActiveTab] = React.useState<'overview' | 'projects'>('overview')
  const [status, setStatus] = React.useState<StitchStatus>(defaultStatus)
  const [screens, setScreens] = React.useState<StitchScreen[]>([])
  const [designSystem, setDesignSystem] = React.useState<StitchDesignSystemResponse | null>(null)
  const [previewScreen, setPreviewScreen] = React.useState<StitchScreen | null>(null)
  const [downloadStateByScreenId, setDownloadStateByScreenId] = React.useState<Record<string, DownloadResult>>({})
  const [isLoadingStatus, setIsLoadingStatus] = React.useState(false)
  const [isLinkingProject, setIsLinkingProject] = React.useState(false)
  const [isLoadingScreens, setIsLoadingScreens] = React.useState(false)
  const [isLoadingDesignSystem, setIsLoadingDesignSystem] = React.useState(false)
  const [error, setError] = React.useState('')
  const { gitStatus } = useGitStatus(workspacePath)

  React.useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Stitch', href: '/stitch' },
    ])
  }, [setBreadcrumbs])

  const isGitLinkedWorkspace = Boolean(
    gitStatus?.is_git_repo &&
      (String(gitStatus.remote_url || '').trim() || (gitStatus.remotes?.length ?? 0) > 0)
  )

  const loadStatus = React.useCallback(async () => {
    const resolvedWorkspacePath = String(workspacePath || '').trim()

    if (!resolvedWorkspacePath) {
      setStatus(defaultStatus)
      setScreens([])
      setDesignSystem(null)
      return
    }

    setIsLoadingStatus(true)
    setError('')

    try {
      const response = await fetch(
        buildApiUrl(`/api/stitch/status?workspace=${encodeURIComponent(resolvedWorkspacePath)}`)
      )

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(String((payload as { detail?: string }).detail || `HTTP ${response.status}`))
      }

      const payload = (await response.json()) as StitchStatus
      setStatus(payload)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load Stitch status')
    } finally {
      setIsLoadingStatus(false)
    }
  }, [workspacePath])

  const loadScreens = React.useCallback(async () => {
    const resolvedWorkspacePath = String(workspacePath || '').trim()

    if (!resolvedWorkspacePath) {
      setScreens([])
      return
    }

    setIsLoadingScreens(true)
    setError('')

    try {
      const response = await fetch(
        buildApiUrl(`/api/stitch/screens?workspace=${encodeURIComponent(resolvedWorkspacePath)}`)
      )

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(String((payload as { detail?: string }).detail || `HTTP ${response.status}`))
      }

      const payload = (await response.json()) as { screens?: StitchScreen[] }
      setScreens(Array.isArray(payload.screens) ? payload.screens : [])
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load Stitch screens')
    } finally {
      setIsLoadingScreens(false)
    }
  }, [workspacePath])

  const loadDesignSystem = React.useCallback(async () => {
    const resolvedWorkspacePath = String(workspacePath || '').trim()

    if (!resolvedWorkspacePath) {
      setDesignSystem(null)
      return
    }

    setIsLoadingDesignSystem(true)
    setError('')

    try {
      const response = await fetch(
        buildApiUrl(`/api/stitch/design-system?workspace=${encodeURIComponent(resolvedWorkspacePath)}&refresh=true`)
      )

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(String((payload as { detail?: string }).detail || `HTTP ${response.status}`))
      }

      const payload = (await response.json()) as StitchDesignSystemResponse
      setDesignSystem(payload)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load Stitch design system')
    } finally {
      setIsLoadingDesignSystem(false)
    }
  }, [workspacePath])

  React.useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  React.useEffect(() => {
    if (!status.linked) {
      setScreens([])
      setDesignSystem(null)
      return
    }

    void loadScreens()
    void loadDesignSystem()
  }, [loadDesignSystem, loadScreens, status.linked])

  const linkProject = async () => {
    const resolvedWorkspacePath = String(workspacePath || '').trim()

    if (!resolvedWorkspacePath) {
      return
    }

    setIsLinkingProject(true)
    setError('')

    try {
      const response = await fetch(buildApiUrl('/api/stitch/link'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ workspace_root: resolvedWorkspacePath }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(String((payload as { detail?: string }).detail || `HTTP ${response.status}`))
      }

      await loadStatus()
      await loadScreens()
      await loadDesignSystem()
      setActiveTab('projects')
    } catch (linkError) {
      setError(linkError instanceof Error ? linkError.message : 'Failed to create or link Stitch project')
    } finally {
      setIsLinkingProject(false)
    }
  }

  const downloadScreenAssets = async (screen: StitchScreen) => {
    const resolvedWorkspacePath = String(workspacePath || '').trim()

    if (!resolvedWorkspacePath) {
      return
    }

    setError('')

    try {
      const response = await fetch(buildApiUrl('/api/stitch/screens/download'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          workspace_root: resolvedWorkspacePath,
          screen_id: screen.screen_id,
          title: screen.title,
        }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(String((payload as { detail?: string }).detail || `HTTP ${response.status}`))
      }

      const payload = (await response.json()) as {
        image_path?: string
        code_path?: string
      }

      setDownloadStateByScreenId((current) => ({
        ...current,
        [screen.screen_id]: {
          image_path: payload.image_path || null,
          code_path: payload.code_path || null,
        },
      }))
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : 'Failed to download Stitch screen assets')
    }
  }

  const hasWorkspace = String(workspacePath || '').trim().length > 0
  const parsedError = parseErrorDetails(error)
  const showMonochromeDesignSystem = !designSystem?.available

  return (
    <div className='flex min-h-0 w-full flex-1 flex-col'>
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as typeof activeTab)}
        className='flex min-h-0 flex-1 flex-col gap-0'
      >
        <SiteSubheader>
          <TabsList variant='line'>
            <TabsTrigger value='overview'>OVERVIEW</TabsTrigger>
            <TabsTrigger value='projects'>PROJECT CANVAS</TabsTrigger>
          </TabsList>

          <Button
            variant='outline'
            size='icon'
            className='ml-auto'
            onClick={() => {
              if (activeTab === 'projects') {
                void loadScreens()
                void loadDesignSystem()
                return
              }

              void loadStatus()
            }}
            disabled={
              activeTab === 'projects'
                ? !status.linked || isLoadingScreens || isLoadingDesignSystem
                : isLoadingStatus
            }
            aria-label={activeTab === 'projects' ? 'Reload canvas' : 'Refresh status'}
            title={activeTab === 'projects' ? 'Reload canvas' : 'Refresh status'}
          >
            <RefreshCw
              className={`h-4 w-4 ${
                (activeTab === 'projects' && (isLoadingScreens || isLoadingDesignSystem)) || (activeTab !== 'projects' && isLoadingStatus)
                  ? 'animate-spin'
                  : ''
              }`}
            />
          </Button>
        </SiteSubheader>

        <div className='w-full space-y-6 overflow-y-auto px-6 py-6'>
          {!hasWorkspace ? (
            <Card>
              <CardHeader>
                <CardTitle>Select a workspace</CardTitle>
                <CardDescription>Choose an active workspace before linking Stitch.</CardDescription>
              </CardHeader>
            </Card>
          ) : null}

          {!isGitLinkedWorkspace && hasWorkspace ? (
            <Card>
              <CardHeader>
                <CardTitle>Git-linked workspace required</CardTitle>
                <CardDescription>
                  Stitch linking is only enabled for workspaces connected to a git remote.
                </CardDescription>
              </CardHeader>
            </Card>
          ) : null}

          {error ? (
            <Alert variant='destructive'>
              <AlertCircle />

              <AlertTitle>{parsedError.title}</AlertTitle>

              <AlertDescription>
                <p className='text-sm font-medium text-foreground'>{parsedError.message}</p>

                <details className='w-full'>
                  <summary className='cursor-pointer text-xs font-medium text-foreground/80'>
                    Show technical details
                  </summary>

                  <pre className='mt-2 max-h-64 w-full overflow-auto rounded-md border border-destructive/30 bg-background/80 p-3 text-xs leading-relaxed text-foreground'>
                    {parsedError.stackTrace}
                  </pre>
                </details>
              </AlertDescription>
            </Alert>
          ) : null}

          <TabsContent value='overview' className='mt-0 space-y-6'>
            <Card>
              <CardHeader>
                <CardTitle>Stitch Workspace Link</CardTitle>
                <CardDescription>Create or load a Stitch project named after the git repository.</CardDescription>
              </CardHeader>

              <div className='space-y-4 px-6 pb-6'>
                <div className='space-y-1 text-sm'>
                  <p><span className='font-medium'>Workspace:</span> {workspacePath || '-'}</p>
                  <p><span className='font-medium'>Repository:</span> {status.repo_name || '-'}</p>
                  <p><span className='font-medium'>Project:</span> {status.project_title || '-'}</p>
                  <p><span className='font-medium'>Project ID:</span> {status.project_id || '-'}</p>
                  <p><span className='font-medium'>Linked:</span> {status.linked ? 'Yes' : 'No'}</p>
                </div>

                <div className='flex items-center gap-3'>
                  <Button
                    onClick={() => {
                      void linkProject()
                    }}
                    disabled={!hasWorkspace || !isGitLinkedWorkspace || isLinkingProject}
                  >
                    {isLinkingProject ? 'Linking…' : 'Create / Link Stitch Project'}
                  </Button>

                  <Button
                    variant='outline'
                    onClick={() => {
                      void loadStatus()
                    }}
                    disabled={isLoadingStatus}
                  >
                    {isLoadingStatus ? 'Refreshing…' : 'Refresh Status'}
                  </Button>
                </div>
              </div>
            </Card>
          </TabsContent>

          <TabsContent value='projects' className='mt-0 space-y-4'>
            {status.linked && screens.length === 0 && !isLoadingScreens ? (
              <Card>
                <CardHeader>
                  <CardTitle>No screens available</CardTitle>
                  <CardDescription>
                    Generate screens using Stitch Generation mode in chat, then reload this list.
                  </CardDescription>
                </CardHeader>
              </Card>
            ) : null}

            <Card>
              <CardHeader>
                <CardTitle>Design system</CardTitle>
                <CardDescription>
                  {showMonochromeDesignSystem
                    ? 'No design.md detected yet. Showing monochrome preview layout.'
                    : 'Loaded from Stitch design.md and normalized to JSON in .assist and .assist/stitch.'}
                </CardDescription>
              </CardHeader>

              <div className='px-4 pb-4 md:px-6 md:pb-6'>
                <DesignSystemPreview
                  designSystem={designSystem?.design_json || null}
                  monochrome={showMonochromeDesignSystem}
                />
              </div>
            </Card>

            <section className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
              {screens.map((screen) => {
                const hasScreenshot = Boolean(screen.screenshot_url)
                const hasHtml = Boolean(screen.html_url)
                const downloadState = downloadStateByScreenId[screen.screen_id]

                return (
                  <article
                    key={screen.screen_id}
                    className='group relative overflow-hidden rounded-2xl border bg-card shadow-sm'
                  >
                    <button
                      className='block w-full'
                      onClick={() => {
                        setPreviewScreen(screen)
                      }}
                      type='button'
                    >
                      {hasScreenshot ? (
                        <img
                          src={screen.screenshot_url}
                          alt={screen.title || screen.screen_id}
                          className='aspect-video w-full object-cover'
                        />
                      ) : (
                        <div className='flex aspect-video w-full items-center justify-center bg-muted text-sm text-muted-foreground'>
                          No screenshot available
                        </div>
                      )}
                    </button>

                    <div className='pointer-events-none absolute inset-x-0 top-0 bg-gradient-to-b from-black/55 to-transparent p-2'>
                      <p className='truncate text-xs font-medium text-white'>{screen.title || screen.screen_id}</p>
                    </div>

                    <div className='absolute bottom-2 right-2 flex items-center gap-2'>
                      <Button
                        size='icon'
                        variant='secondary'
                        className='h-8 w-8 rounded-full bg-black/70 text-white hover:bg-black'
                        onClick={() => {
                          setPreviewScreen(screen)
                        }}
                        type='button'
                      >
                        <Eye className='h-4 w-4' />
                      </Button>

                      {hasScreenshot ? (
                        <a href={screen.screenshot_url} target='_blank' rel='noreferrer'>
                          <Button
                            size='icon'
                            variant='secondary'
                            className='h-8 w-8 rounded-full bg-black/70 text-white hover:bg-black'
                            type='button'
                          >
                            <ExternalLink className='h-4 w-4' />
                          </Button>
                        </a>
                      ) : null}

                      {hasHtml ? (
                        <a href={screen.html_url} target='_blank' rel='noreferrer'>
                          <Button
                            size='icon'
                            variant='secondary'
                            className='h-8 w-8 rounded-full bg-black/70 text-white hover:bg-black'
                            type='button'
                          >
                            <FileCode2 className='h-4 w-4' />
                          </Button>
                        </a>
                      ) : null}

                      <Button
                        size='icon'
                        variant='secondary'
                        className='h-8 w-8 rounded-full bg-black/70 text-white hover:bg-black'
                        onClick={() => {
                          void downloadScreenAssets(screen)
                        }}
                        type='button'
                      >
                        <Download className='h-4 w-4' />
                      </Button>
                    </div>

                    {downloadState ? (
                      <div className='border-t px-3 py-2 text-xs text-muted-foreground'>
                        {downloadState.image_path ? <p>Image: <code>{downloadState.image_path}</code></p> : null}
                        {downloadState.code_path ? <p>HTML: <code>{downloadState.code_path}</code></p> : null}
                      </div>
                    ) : null}
                  </article>
                )
              })}
            </section>
          </TabsContent>
        </div>
      </Tabs>

      <Dialog
        open={Boolean(previewScreen)}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewScreen(null)
          }
        }}
      >
        <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-5xl'>
          <DialogHeader>
            <DialogTitle>{previewScreen?.title || previewScreen?.screen_id || 'Screen preview'}</DialogTitle>
          </DialogHeader>

          {previewScreen?.screenshot_url ? (
            <img
              src={previewScreen.screenshot_url}
              alt={previewScreen.title || previewScreen.screen_id}
              className='w-full rounded-lg border'
            />
          ) : (
            <div className='flex min-h-64 items-center justify-center rounded-lg border bg-muted text-sm text-muted-foreground'>
              No screenshot available
            </div>
          )}

          <div className='flex flex-wrap gap-2'>
            {previewScreen?.screenshot_url ? (
              <a href={previewScreen.screenshot_url} target='_blank' rel='noreferrer'>
                <Button variant='outline' size='sm'>
                  <ExternalLink className='mr-2 h-4 w-4' />
                  Open Screenshot
                </Button>
              </a>
            ) : null}

            {previewScreen?.html_url ? (
              <a href={previewScreen.html_url} target='_blank' rel='noreferrer'>
                <Button variant='outline' size='sm'>
                  <FileCode2 className='mr-2 h-4 w-4' />
                  Open HTML
                </Button>
              </a>
            ) : null}

            {previewScreen ? (
              <Button
                size='sm'
                onClick={() => {
                  void downloadScreenAssets(previewScreen)
                }}
              >
                <Download className='mr-2 h-4 w-4' />
                Download To Workspace
              </Button>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
