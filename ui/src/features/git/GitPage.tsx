import * as React from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Check,
  Filter,
  GitBranch,
  GitCommit,
  Loader2,
  Plus,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'

import { SiteSubheader } from '@/shared/components/site-subheader.tsx'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { ScrollArea } from '@/shared/components/ui/scroll-area'
import { Separator } from '@/shared/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { Textarea } from '@/shared/components/ui/textarea'
import { cn } from '@/shared/utils/utils.ts'
import { Chip } from '@/shared/components/chip'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import { sanitizeUrlForNavigation } from '@/shared/utils/secret-sanitizer'

import { CreateBranchDialog } from './components/CreateBranchDialog'
import { GitBranchesPanel, type GitRepositoryBranchItem } from './components/GitBranchesPanel'
import { GitPageHeader } from './components/GitPageHeader'
import { GitSettingsTabContent } from './components/GitSettingsTabContent'
import { GitWorkflowActionsSection } from './components/GitWorkflowActionsSection'
import { useGitStatus } from './hooks/useGitStatus'
import { useGitStore } from './store/git-store'
import type { GitWorkflowConfigs, GitWorkflowKey, WorkspaceGitStatus } from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const WORKFLOW_SECTIONS: Array<{
  key: GitWorkflowKey
  title: string
  summary: string
  settingsTitle: string
  settingsDescription: string
}> = [
  {
    key: 'chat',
    title: 'Chat',
    summary: 'Configure the Git hooks that run during direct chat-to-code requests.',
    settingsTitle: 'Chat Git Settings',
    settingsDescription:
      'These settings apply to chat workflow hooks unless a specific phase overrides them.',
  },
  {
    key: 'pipeline',
    title: 'Automation',
    summary: 'Configure the Git hooks that run during automation and pipeline executions.',
    settingsTitle: 'Automation Git Settings',
    settingsDescription:
      'These settings apply to automation/pipeline workflow hooks unless a specific phase overrides them.',
  },
  {
    key: 'pipeline_spec',
    title: 'Spec Automation',
    summary: 'Configure Git hooks that run during SPEC pipeline task executions only.',
    settingsTitle: 'Spec Automation Git Settings',
    settingsDescription:
      'These settings apply only to SPEC pipeline workflow hooks unless a specific phase overrides them.',
  },
]

type GitWorkflowConfigResponse = {
  workflows: GitWorkflowConfigs
}

type GitBranchesResponse = {
  detail?: string
  current?: string
  local?: string[]
  remote?: string[]
}

type GitDiffResponse = {
  detail?: string
  diff?: string
  staged?: boolean
}

type GitLogResponse = {
  detail?: string
  commits?: GitCommitListEntry[]
}

type GitCommitListEntry = {
  hash: string
  message: string
  author: string
  when: string
  refs?: string
}

type GitCommitActionResponse = {
  detail?: string
  error?: string
  success?: boolean
  skipped?: boolean
  reason?: string
}

type GitOpenInCursorResponse = {
  detail?: string
  ok?: boolean
  success?: boolean
  workspace?: string
  method?: string
}

type GitOpenInFilesResponse = {
  detail?: string
  ok?: boolean
  success?: boolean
  workspace?: string
  method?: string
}

type GitDeleteBranchResponse = {
  detail?: string
  ok?: boolean
}

type DiffFileStatus = 'modified' | 'added' | 'deleted' | 'renamed'

type DiffSource = 'working' | 'staged' | 'both'

type ParsedDiffFile = {
  path: string
  oldPath: string
  newPath: string
  status: DiffFileStatus
  additions: number
  deletions: number
  patch: string
}

type CombinedDiffFile = {
  path: string
  status: DiffFileStatus
  additions: number
  deletions: number
  patch: string
  source: DiffSource
}

type RepositoryListView = 'changes' | 'branches' | 'history'

type GitSyncAction = 'fetch' | 'pull' | 'merge' | 'rebase' | 'push'

type ClientDesktopPlatform = 'mac' | 'windows' | 'other'

const SYNC_ACTION_LABELS: Record<GitSyncAction, string> = {
  fetch: 'Fetch',
  pull: 'Pull',
  merge: 'Merge',
  rebase: 'Rebase',
  push: 'Push',
}

const FILE_STATUS_PRIORITY: Record<DiffFileStatus, number> = {
  deleted: 4,
  added: 3,
  renamed: 2,
  modified: 1,
}

const PROTECTED_BRANCH_NAMES = new Set(['main', 'master', 'develop', 'development', 'dev'])

type RepositoryQuickAction = {
  actionKey: 'open-cursor' | 'open-files' | 'open-remote'
  title: string
  secondaryText: string
  highlightedText?: string
  actionLabel: string
  shortcutKeys: string[]
}

const REPOSITORY_QUICK_ACTIONS: RepositoryQuickAction[] = [
  {
    actionKey: 'open-cursor',
    title: 'Open the repository in your external editor',
    secondaryText: '',
    actionLabel: 'Open in Cursor',
    shortcutKeys: ['CMD', 'SHIFT', 'E'],
  },
  {
    actionKey: 'open-files',
    title: 'View the files of your repository',
    secondaryText: '',
    actionLabel: 'View in Files',
    shortcutKeys: ['CMD', 'SHIFT', 'F'],
  },
  {
    actionKey: 'open-remote',
    title: 'Open the repository page in your browser',
    secondaryText: '',
    actionLabel: 'View on GitHub',
    shortcutKeys: ['CMD', 'SHIFT', 'G'],
  },
]

function ShortcutKeys({ keys }: { keys: string[] }) {
  return (
    <span className='inline-flex items-center gap-1.5 align-middle'>
      {keys.map((key) => (
        <kbd
          key={key}
          className='bg-muted/60 text-muted-foreground inline-flex min-w-5 items-center justify-center rounded border border-border/60 px-1.5 py-0.5 text-[10px] font-medium leading-none'
        >
          {key}
        </kbd>
      ))}
    </span>
  )
}

type DiffEmptyStatePanelProps = {
  onOpenInCursor: () => Promise<void>
  onOpenInFiles: () => Promise<void>
  onOpenRepository: () => void
  canOpenInCursor: boolean
  canOpenInFiles: boolean
  canOpenRepository: boolean
  showFilesAction: boolean
  isOpeningCursor: boolean
  isOpeningFiles: boolean
  openRepositoryLabel: string
}

function DiffEmptyStatePanel({
  onOpenInCursor,
  onOpenInFiles,
  onOpenRepository,
  canOpenInCursor,
  canOpenInFiles,
  canOpenRepository,
  showFilesAction,
  isOpeningCursor,
  isOpeningFiles,
  openRepositoryLabel,
}: DiffEmptyStatePanelProps) {
  const visibleActions = REPOSITORY_QUICK_ACTIONS.filter((item) => {
    if (item.actionKey === 'open-files') {
      return showFilesAction
    }

    return true
  })

  return (
    <div className='flex min-h-full items-center justify-center p-6'>
      <Card className='w-full max-w-3xl gap-0 overflow-hidden py-0'>
        {visibleActions.map((item, index) => (
          <React.Fragment key={item.actionLabel}>
            {index > 0 ? <Separator /> : null}

            <div className='grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-4 sm:gap-6 sm:px-6 sm:py-5'>
              <div className='space-y-1'>
                <p className='text-sm font-semibold'>{item.title}</p>

                {item.secondaryText || item.highlightedText ? (
                  <p className='text-sm text-muted-foreground'>
                    {item.secondaryText}
                    {item.highlightedText ? (
                      <span className='text-primary underline underline-offset-2'>{item.highlightedText}</span>
                    ) : null}
                  </p>
                ) : null}

                <p className='text-sm text-muted-foreground'>
                  Repository menu or <ShortcutKeys keys={item.shortcutKeys} />
                </p>
              </div>

              <Button
                type='button'
                variant='outline'
                size='sm'
                className='min-w-32 justify-center'
                disabled={
                  item.actionKey === 'open-cursor'
                    ? !canOpenInCursor || isOpeningCursor
                    : item.actionKey === 'open-files'
                      ? !canOpenInFiles || isOpeningFiles
                      : !canOpenRepository
                }
                onClick={() => {
                  if (item.actionKey === 'open-cursor') {
                    void onOpenInCursor()
                    return
                  }

                  if (item.actionKey === 'open-files') {
                    void onOpenInFiles()
                    return
                  }

                  onOpenRepository()
                }}
              >
                {item.actionKey === 'open-cursor' && isOpeningCursor ? (
                  <Loader2 className='size-3.5 animate-spin' />
                ) : null}

                {item.actionKey === 'open-files' && isOpeningFiles ? (
                  <Loader2 className='size-3.5 animate-spin' />
                ) : null}

                {item.actionKey === 'open-remote' ? openRepositoryLabel : item.actionLabel}
              </Button>
            </div>
          </React.Fragment>
        ))}
      </Card>
    </div>
  )
}

function detectClientDesktopPlatform(): ClientDesktopPlatform {
  if (typeof navigator === 'undefined') {
    return 'other'
  }

  const userAgentDataPlatform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform || ''
  const normalizedPlatform = String(userAgentDataPlatform || navigator.platform || navigator.userAgent || '').toLowerCase()

  if (normalizedPlatform.includes('mac')) {
    return 'mac'
  }

  if (normalizedPlatform.includes('win')) {
    return 'windows'
  }

  return 'other'
}

function getRepositoryWebUrl(remoteUrl: string, platform: string): string {
  const normalizedRemoteUrl = String(remoteUrl || '').trim()
  if (!normalizedRemoteUrl) {
    return ''
  }

  const sanitizedRemoteUrl = sanitizeUrlForNavigation(normalizedRemoteUrl)

  const fromSshScpMatch = sanitizedRemoteUrl.match(/^git@([^:]+):(.+)$/)
  if (fromSshScpMatch) {
    const host = String(fromSshScpMatch[1] || '').trim()
    const path = String(fromSshScpMatch[2] || '').trim()
    if (!host || !path) {
      return ''
    }
    return `https://${host}/${path}`.replace(/\.git$/i, '').replace(/\/+$/, '')
  }

  const fromSshUrlMatch = sanitizedRemoteUrl.match(/^ssh:\/\/git@([^/]+)\/(.+)$/i)
  if (fromSshUrlMatch) {
    const host = String(fromSshUrlMatch[1] || '').trim()
    const path = String(fromSshUrlMatch[2] || '').trim()
    if (!host || !path) {
      return ''
    }
    return `https://${host}/${path}`.replace(/\.git$/i, '').replace(/\/+$/, '')
  }

  try {
    const parsed = new URL(sanitizedRemoteUrl)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      return ''
    }

    const hostname = parsed.hostname.toLowerCase()
    const supportedPlatform =
      platform === 'github' ||
      platform === 'gitlab' ||
      hostname.includes('github') ||
      hostname.includes('gitlab')
    if (!supportedPlatform) {
      return ''
    }

    parsed.hash = ''
    parsed.search = ''
    parsed.pathname = parsed.pathname.replace(/\.git$/i, '').replace(/\/+$/, '')

    return parsed.toString()
  } catch {
    return ''
  }
}

function getRepositoryNameFromPath(workspacePath: string): string {
  const normalizedPath = workspacePath.trim()

  if (!normalizedPath) {
    return 'Repository'
  }

  const segments = normalizedPath.split(/[\\/]/).filter(Boolean)

  return segments[segments.length - 1] || normalizedPath
}

function detectDiffStatus(lines: string[]): DiffFileStatus {
  for (const line of lines) {
    if (line.startsWith('deleted file mode')) {
      return 'deleted'
    }

    if (line.startsWith('new file mode')) {
      return 'added'
    }

    if (line.startsWith('rename from ')) {
      return 'renamed'
    }
  }

  return 'modified'
}

function parseDiffFiles(diffText: string): ParsedDiffFile[] {
  const normalizedDiffText = String(diffText || '')

  if (!normalizedDiffText.trim()) {
    return []
  }

  const files: ParsedDiffFile[] = []
  const lines = normalizedDiffText.split('\n')
  let currentSectionLines: string[] = []

  const flushCurrentSection = () => {
    if (!currentSectionLines.length) {
      return
    }

    const headerLine = currentSectionLines[0] || ''
    const match = headerLine.match(/^diff --git a\/(.+?) b\/(.+)$/)

    if (!match) {
      currentSectionLines = []
      return
    }

    const oldPath = String(match[1] || '').trim()
    const newPath = String(match[2] || '').trim()
    const resolvedPath = newPath && newPath !== '/dev/null' ? newPath : oldPath
    const status = detectDiffStatus(currentSectionLines)

    let additions = 0
    let deletions = 0

    for (const line of currentSectionLines) {
      if (line.startsWith('+++') || line.startsWith('---')) {
        continue
      }

      if (line.startsWith('+')) {
        additions += 1
        continue
      }

      if (line.startsWith('-')) {
        deletions += 1
      }
    }

    files.push({
      path: resolvedPath || oldPath || newPath,
      oldPath,
      newPath,
      status,
      additions,
      deletions,
      patch: currentSectionLines.join('\n'),
    })

    currentSectionLines = []
  }

  for (const line of lines) {
    if (line.startsWith('diff --git ')) {
      flushCurrentSection()
      currentSectionLines = [line]
      continue
    }

    if (!currentSectionLines.length) {
      continue
    }

    currentSectionLines.push(line)
  }

  flushCurrentSection()

  return files
}

function mergeDiffFiles(workingFiles: ParsedDiffFile[], stagedFiles: ParsedDiffFile[]): CombinedDiffFile[] {
  const byPath = new Map<string, CombinedDiffFile>()

  const addFile = (file: ParsedDiffFile, source: DiffSource) => {
    const existing = byPath.get(file.path)

    if (!existing) {
      byPath.set(file.path, {
        path: file.path,
        status: file.status,
        additions: file.additions,
        deletions: file.deletions,
        patch: file.patch,
        source,
      })
      return
    }

    const mergedStatus =
      FILE_STATUS_PRIORITY[file.status] > FILE_STATUS_PRIORITY[existing.status]
        ? file.status
        : existing.status

    byPath.set(file.path, {
      ...existing,
      status: mergedStatus,
      additions: existing.additions + file.additions,
      deletions: existing.deletions + file.deletions,
      patch: `${existing.patch}\n\n${file.patch}`,
      source: existing.source === source ? existing.source : 'both',
    })
  }

  for (const file of workingFiles) {
    addFile(file, 'working')
  }

  for (const file of stagedFiles) {
    addFile(file, 'staged')
  }

  return Array.from(byPath.values()).sort((a, b) => a.path.localeCompare(b.path))
}

function getRecommendedSyncAction(
  gitStatus: WorkspaceGitStatus | null,
  currentBranch: string,
  targetBranch: string,
): GitSyncAction {
  if (!gitStatus?.is_git_repo) {
    return 'fetch'
  }

  const ahead = Number(gitStatus.ahead || 0)
  const behind = Number(gitStatus.behind || 0)
  const hasWorkingTreeChanges =
    Number(gitStatus.staged || 0) > 0 ||
    Number(gitStatus.modified || 0) > 0 ||
    Number(gitStatus.untracked || 0) > 0
  const normalizedCurrentBranch = String(currentBranch || '').trim()
  const normalizedTargetBranch = String(targetBranch || '').trim()
  const isCustomTargetBranch =
    Boolean(normalizedTargetBranch) &&
    Boolean(normalizedCurrentBranch) &&
    normalizedTargetBranch !== normalizedCurrentBranch

  if (ahead > 0) {
    return 'push'
  }

  if (hasWorkingTreeChanges) {
    return 'fetch'
  }

  if (isCustomTargetBranch) {
    return 'merge'
  }

  if (behind > 0 && ahead > 0) {
    return 'rebase'
  }

  if (behind > 0) {
    return 'pull'
  }

  return 'fetch'
}

function formatRelativeTimestamp(isoTimestamp: string | null): string {
  if (!isoTimestamp) {
    return 'Not synced yet'
  }

  const timestampMs = new Date(isoTimestamp).getTime()

  if (!Number.isFinite(timestampMs)) {
    return 'Not synced yet'
  }

  const deltaSeconds = Math.max(0, Math.round((Date.now() - timestampMs) / 1000))

  if (deltaSeconds < 15) {
    return 'just now'
  }

  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`
  }

  const deltaMinutes = Math.round(deltaSeconds / 60)

  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`
  }

  const deltaHours = Math.round(deltaMinutes / 60)

  if (deltaHours < 24) {
    return `${deltaHours}h ago`
  }

  const deltaDays = Math.round(deltaHours / 24)

  return `${deltaDays}d ago`
}

type DiffRenderRowKind = 'meta' | 'hunk' | 'context' | 'add' | 'delete'

type DiffRenderRow = {
  kind: DiffRenderRowKind
  oldLine: string
  newLine: string
  text: string
}

function buildDiffRows(patch: string): DiffRenderRow[] {
  const normalizedPatch = String(patch || '')
  const rows: DiffRenderRow[] = []
  const lines = normalizedPatch.split('\n')
  let oldLineNumber = 0
  let newLineNumber = 0

  for (const line of lines) {
    if (line.startsWith('@@')) {
      const hunkMatch = line.match(/@@ -([0-9]+)(?:,[0-9]+)? \+([0-9]+)(?:,[0-9]+)? @@/)
      if (hunkMatch) {
        oldLineNumber = Number.parseInt(hunkMatch[1], 10)
        newLineNumber = Number.parseInt(hunkMatch[2], 10)
      }
      rows.push({ kind: 'hunk', oldLine: '', newLine: '', text: line })
      continue
    }

    if (line.startsWith('+') && !line.startsWith('+++')) {
      rows.push({
        kind: 'add',
        oldLine: '',
        newLine: String(newLineNumber),
        text: line,
      })
      newLineNumber += 1
      continue
    }

    if (line.startsWith('-') && !line.startsWith('---')) {
      rows.push({
        kind: 'delete',
        oldLine: String(oldLineNumber),
        newLine: '',
        text: line,
      })
      oldLineNumber += 1
      continue
    }

    if (line.startsWith(' ')) {
      rows.push({
        kind: 'context',
        oldLine: String(oldLineNumber),
        newLine: String(newLineNumber),
        text: line,
      })
      oldLineNumber += 1
      newLineNumber += 1
      continue
    }

    rows.push({ kind: 'meta', oldLine: '', newLine: '', text: line })
  }

  return rows
}

function getDiffRowClassName(kind: DiffRenderRowKind): string {
  if (kind === 'add') {
    return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  }

  if (kind === 'delete') {
    return 'bg-rose-500/10 text-rose-700 dark:text-rose-300'
  }

  if (kind === 'hunk') {
    return 'bg-sky-500/10 text-sky-700 dark:text-sky-300'
  }

  if (kind === 'meta') {
    return 'text-muted-foreground'
  }

  return 'text-foreground/90'
}

function getFileStatusToken(status: DiffFileStatus): {
  label: string
  className: string
} {
  if (status === 'added') {
    return {
      label: '+',
      className: 'border-emerald-500/60 text-emerald-600 dark:text-emerald-400',
    }
  }

  if (status === 'deleted') {
    return {
      label: '-',
      className: 'border-rose-500/60 text-rose-600 dark:text-rose-400',
    }
  }

  if (status === 'renamed') {
    return {
      label: 'R',
      className: 'border-amber-500/60 text-amber-600 dark:text-amber-400',
    }
  }

  return {
    label: 'M',
    className: 'border-sky-500/60 text-sky-600 dark:text-sky-400',
  }
}

type GitRepositoryWorkbenchProps = {
  workspacePath: string
  gitStatus: WorkspaceGitStatus | null
  isGitStatusLoading: boolean
  gitStatusError: string | null
  localBranchOptions: string[]
  remoteBranchOptions: string[]
  isLoadingBranches: boolean
  onReloadBranches: () => Promise<void> | void
  onRefreshGitStatus: () => void
}

function GitRepositoryWorkbench({
  workspacePath,
  gitStatus,
  isGitStatusLoading,
  gitStatusError,
  localBranchOptions,
  remoteBranchOptions,
  isLoadingBranches,
  onReloadBranches,
  onRefreshGitStatus,
}: GitRepositoryWorkbenchProps) {
  const [activeBranchInput, setActiveBranchInput] = React.useState('')
  const [targetBranchInput, setTargetBranchInput] = React.useState('')
  const [listView, setListView] = React.useState<RepositoryListView>('changes')
  const [changedFileFilter, setChangedFileFilter] = React.useState('')
  const [branchFilter, setBranchFilter] = React.useState('')
  const [selectedChangedFilePath, setSelectedChangedFilePath] = React.useState('')
  const [workingDiff, setWorkingDiff] = React.useState('')
  const [stagedDiff, setStagedDiff] = React.useState('')
  const [isLoadingDiff, setIsLoadingDiff] = React.useState(false)
  const [diffError, setDiffError] = React.useState<string | null>(null)
  const [recentCommits, setRecentCommits] = React.useState<GitCommitListEntry[]>([])
  const [isLoadingHistory, setIsLoadingHistory] = React.useState(false)
  const [historyError, setHistoryError] = React.useState<string | null>(null)
  const [commitTitle, setCommitTitle] = React.useState('')
  const [commitDescription, setCommitDescription] = React.useState('')
  const [isBranchSelectOpen, setIsBranchSelectOpen] = React.useState(false)
  const [isCommitting, setIsCommitting] = React.useState(false)
  const [isSyncing, setIsSyncing] = React.useState(false)
  const [isOpeningCursor, setIsOpeningCursor] = React.useState(false)
  const [isOpeningFiles, setIsOpeningFiles] = React.useState(false)
  const [isSwitchingBranch, setIsSwitchingBranch] = React.useState(false)
  const [isDeletingBranch, setIsDeletingBranch] = React.useState(false)
  const [deletingBranchKey, setDeletingBranchKey] = React.useState<string | null>(null)
  const [isProtectedPushDialogOpen, setIsProtectedPushDialogOpen] = React.useState(false)
  const [isCreateBranchDialogOpen, setIsCreateBranchDialogOpen] = React.useState(false)
  const [lastFetchedAt, setLastFetchedAt] = React.useState<string | null>(null)

  const activeRemoteName = String(gitStatus?.remotes?.[0]?.name || 'origin').trim() || 'origin'
  const currentBranch = String(gitStatus?.branch || '').trim()
  const repositoryName = getRepositoryNameFromPath(workspacePath)
  const hasGitRepo = Boolean(gitStatus?.is_git_repo)
  const clientDesktopPlatform = React.useMemo(() => detectClientDesktopPlatform(), [])
  const canShowFilesAction = clientDesktopPlatform === 'mac' || clientDesktopPlatform === 'windows'

  const normalizedActiveBranchInput = activeBranchInput.trim()
  const normalizedTargetBranchInput = targetBranchInput.trim()
  const normalizedCommitTitle = commitTitle.trim()
  const normalizedCommitDescription = commitDescription.trim()
  const repositoryWebUrl = React.useMemo(
    () => getRepositoryWebUrl(gitStatus?.remote_url || '', gitStatus?.platform || ''),
    [gitStatus?.platform, gitStatus?.remote_url],
  )
  const openRepositoryLabel = React.useMemo(() => {
    if (gitStatus?.platform === 'gitlab') {
      return 'View on GitLab'
    }

    if (gitStatus?.platform === 'github') {
      return 'View on GitHub'
    }

    return 'View Repository'
  }, [gitStatus?.platform])

  const availableTargetBranches = React.useMemo(
    () =>
      Array.from(
        new Set(
          [...localBranchOptions, ...remoteBranchOptions]
            .map((branch) => String(branch || '').trim().replace(/^origin\//, ''))
            .filter(Boolean),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [localBranchOptions, remoteBranchOptions],
  )

  const localBranchItems = React.useMemo<GitRepositoryBranchItem[]>(() => {
    return Array.from(
      new Set(
        localBranchOptions
          .map((branch) => String(branch || '').trim())
          .filter(Boolean),
      ),
    )
      .sort((a, b) => a.localeCompare(b))
      .map((branchName) => {
        const normalizedBranchName = String(branchName || '').trim()
        const lowercaseBranchName = normalizedBranchName.toLowerCase()

        return {
          key: `local:${normalizedBranchName}`,
          name: normalizedBranchName,
          displayName: normalizedBranchName,
          shortName: normalizedBranchName,
          remoteName: activeRemoteName,
          scope: 'local',
          isCurrent: normalizedBranchName === currentBranch,
          isProtected: PROTECTED_BRANCH_NAMES.has(lowercaseBranchName),
        } satisfies GitRepositoryBranchItem
      })
  }, [activeRemoteName, currentBranch, localBranchOptions])

  const remoteBranchItems = React.useMemo<GitRepositoryBranchItem[]>(() => {
    const nextRemoteBranchItems: GitRepositoryBranchItem[] = []
    const uniqueRemoteBranchNames = Array.from(
      new Set(
        remoteBranchOptions
          .map((branch) => String(branch || '').trim())
          .filter(Boolean),
      ),
    )

    for (const remoteBranchName of uniqueRemoteBranchNames) {
      const normalizedRemoteBranchName = String(remoteBranchName || '').trim()
      const [remoteNamePart, ...branchNameParts] = normalizedRemoteBranchName.split('/')
      const resolvedRemoteName = String(remoteNamePart || activeRemoteName).trim() || activeRemoteName
      const resolvedShortName = branchNameParts.join('/').trim()

      if (!resolvedShortName || resolvedShortName === 'HEAD') {
        continue
      }

      const lowercaseShortName = resolvedShortName.toLowerCase()

      nextRemoteBranchItems.push({
        key: `remote:${normalizedRemoteBranchName}`,
        name: normalizedRemoteBranchName,
        displayName: normalizedRemoteBranchName,
        shortName: resolvedShortName,
        remoteName: resolvedRemoteName,
        scope: 'remote',
        isCurrent:
          resolvedRemoteName === activeRemoteName &&
          resolvedShortName === currentBranch,
        isProtected: PROTECTED_BRANCH_NAMES.has(lowercaseShortName),
      })
    }

    return nextRemoteBranchItems.sort((a, b) => a.displayName.localeCompare(b.displayName))
  }, [activeRemoteName, currentBranch, remoteBranchOptions])

  const allBranchItems = React.useMemo(
    () => [...localBranchItems, ...remoteBranchItems],
    [localBranchItems, remoteBranchItems],
  )

  const filteredBranchItems = React.useMemo(() => {
    const query = branchFilter.trim().toLowerCase()

    if (!query) {
      return allBranchItems
    }

    return allBranchItems.filter((branch) => {
      const branchSearchTarget = `${branch.displayName} ${branch.shortName}`.toLowerCase()

      return branchSearchTarget.includes(query)
    })
  }, [allBranchItems, branchFilter])

  const loadDiffs = React.useCallback(async () => {
    if (!workspacePath || !hasGitRepo) {
      setWorkingDiff('')
      setStagedDiff('')
      setDiffError(null)
      return
    }

    setIsLoadingDiff(true)

    try {
      const [workingResponse, stagedResponse] = await Promise.all([
        fetch(buildApiUrl(`/api/git/diff?workspace=${encodeURIComponent(workspacePath)}&staged=false`)),
        fetch(buildApiUrl(`/api/git/diff?workspace=${encodeURIComponent(workspacePath)}&staged=true`)),
      ])

      const workingPayload = (await workingResponse.json().catch(() => ({}))) as GitDiffResponse
      const stagedPayload = (await stagedResponse.json().catch(() => ({}))) as GitDiffResponse

      if (!workingResponse.ok) {
        throw new Error(workingPayload.detail ?? `Failed to load working diff (${workingResponse.status})`)
      }

      if (!stagedResponse.ok) {
        throw new Error(stagedPayload.detail ?? `Failed to load staged diff (${stagedResponse.status})`)
      }

      setWorkingDiff(String(workingPayload.diff || ''))
      setStagedDiff(String(stagedPayload.diff || ''))
      setDiffError(null)
    } catch (err) {
      setWorkingDiff('')
      setStagedDiff('')
      setDiffError(err instanceof Error ? err.message : 'Failed to load diffs')
    } finally {
      setIsLoadingDiff(false)
    }
  }, [hasGitRepo, workspacePath])

  const loadHistory = React.useCallback(async () => {
    if (!workspacePath || !hasGitRepo) {
      setRecentCommits([])
      setHistoryError(null)
      return
    }

    setIsLoadingHistory(true)

    try {
      const response = await fetch(buildApiUrl(`/api/git/log?workspace=${encodeURIComponent(workspacePath)}&limit=80`))
      const payload = (await response.json().catch(() => ({}))) as GitLogResponse

      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to load history (${response.status})`)
      }

      setRecentCommits(Array.isArray(payload.commits) ? payload.commits : [])
      setHistoryError(null)
    } catch (err) {
      setRecentCommits([])
      setHistoryError(err instanceof Error ? err.message : 'Failed to load history')
    } finally {
      setIsLoadingHistory(false)
    }
  }, [hasGitRepo, workspacePath])

  const refreshRepositoryData = React.useCallback(() => {
    onRefreshGitStatus()
    void onReloadBranches()
    void loadDiffs()

    if (listView === 'history') {
      void loadHistory()
    }
  }, [listView, loadDiffs, loadHistory, onRefreshGitStatus, onReloadBranches])

  const handleSwitchBranch = React.useCallback(
    async (nextBranchValue: string) => {
      const nextBranch = String(nextBranchValue || '').trim()

      if (!workspacePath || !hasGitRepo || !nextBranch || nextBranch === currentBranch) {
        setActiveBranchInput(nextBranch)
        return
      }

      setIsSwitchingBranch(true)

      try {
        const response = await fetch(buildApiUrl('/api/git/branch'), {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace: workspacePath, branch: nextBranch }),
        })

        const payload = (await response.json().catch(() => ({}))) as { detail?: string }

        if (!response.ok) {
          throw new Error(payload.detail ?? `Failed to switch branch (${response.status})`)
        }

        setActiveBranchInput(nextBranch)
        setTargetBranchInput(nextBranch)
        toast.success(`Switched to ${nextBranch}.`)
        refreshRepositoryData()
      } catch (err) {
        setActiveBranchInput(currentBranch)
        toast.error(err instanceof Error ? err.message : 'Failed to switch branch')
      } finally {
        setIsSwitchingBranch(false)
      }
    },
    [currentBranch, hasGitRepo, refreshRepositoryData, workspacePath],
  )

  const handleDeleteBranch = React.useCallback(
    async (branch: GitRepositoryBranchItem, force: boolean): Promise<boolean> => {
      if (!workspacePath || !hasGitRepo) {
        return false
      }

      setIsDeletingBranch(true)
      setDeletingBranchKey(branch.key)

      try {
        const params = new URLSearchParams({
          workspace: workspacePath,
          branch: branch.scope === 'remote' ? branch.name : branch.shortName,
          remote: String(branch.scope === 'remote'),
          remote_name: branch.remoteName,
          force: String(force),
        })

        const response = await fetch(buildApiUrl(`/api/git/branch?${params.toString()}`), {
          method: 'DELETE',
        })

        const payload = (await response.json().catch(() => ({}))) as GitDeleteBranchResponse

        if (!response.ok) {
          throw new Error(payload.detail ?? `Failed to delete branch (${response.status})`)
        }

        toast.success(`Deleted ${branch.scope} branch ${branch.displayName}.`)
        refreshRepositoryData()
        return true
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to delete branch')
        return false
      } finally {
        setIsDeletingBranch(false)
        setDeletingBranchKey(null)
      }
    },
    [hasGitRepo, refreshRepositoryData, workspacePath],
  )

  const isCurrentBranchPublished = React.useMemo(() => {
    const branch = normalizedActiveBranchInput || currentBranch

    if (!branch) {
      return true
    }

    return remoteBranchItems.some(
      (b) => b.shortName === branch && b.remoteName === activeRemoteName,
    )
  }, [activeRemoteName, currentBranch, normalizedActiveBranchInput, remoteBranchItems])

  const resolvedSyncAction = React.useMemo<GitSyncAction>(() => {
    const base = getRecommendedSyncAction(gitStatus, normalizedActiveBranchInput || currentBranch, normalizedTargetBranchInput)

    if (!isCurrentBranchPublished && base === 'fetch') {
      return 'push'
    }

    return base
  }, [currentBranch, gitStatus, isCurrentBranchPublished, normalizedActiveBranchInput, normalizedTargetBranchInput])

  const executeSyncAction = React.useCallback(async () => {
    if (!workspacePath || !hasGitRepo) {
      return
    }

    const targetBranch = normalizedTargetBranchInput || currentBranch || undefined

    setIsSyncing(true)

    try {
      const baseBody: {
        workspace: string
        remote: string
        branch?: string
        ff_only?: boolean
        rebase?: boolean
        set_upstream?: boolean
      } = {
        workspace: workspacePath,
        remote: activeRemoteName,
      }

      if (targetBranch) {
        baseBody.branch = targetBranch
      }

      let endpoint = '/api/git/fetch'

      if (resolvedSyncAction === 'pull') {
        endpoint = '/api/git/pull'
        baseBody.ff_only = true
        baseBody.rebase = false
      }

      if (resolvedSyncAction === 'merge') {
        endpoint = '/api/git/pull'
        baseBody.ff_only = false
        baseBody.rebase = false
      }

      if (resolvedSyncAction === 'rebase') {
        endpoint = '/api/git/pull'
        baseBody.ff_only = false
        baseBody.rebase = true
      }

      if (resolvedSyncAction === 'push') {
        endpoint = '/api/git/push'
        baseBody.set_upstream = true
      }

      const response = await fetch(buildApiUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(baseBody),
      })

      const payload = (await response.json().catch(() => ({}))) as { detail?: string }

      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to ${resolvedSyncAction} (${response.status})`)
      }

      const targetLabel = targetBranch ? `${activeRemoteName}/${targetBranch}` : activeRemoteName

      setLastFetchedAt(new Date().toISOString())
      toast.success(`${SYNC_ACTION_LABELS[resolvedSyncAction]} completed against ${targetLabel}.`)

      refreshRepositoryData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to ${resolvedSyncAction}`)
    } finally {
      setIsSyncing(false)
    }
  }, [
    activeRemoteName,
    currentBranch,
    hasGitRepo,
    normalizedTargetBranchInput,
    refreshRepositoryData,
    resolvedSyncAction,
    workspacePath,
  ])

  const commitChanges = React.useCallback(async () => {
    if (!workspacePath || !hasGitRepo || !normalizedCommitTitle) {
      return
    }

    const commitMessage = normalizedCommitDescription
      ? `${normalizedCommitTitle}\n\n${normalizedCommitDescription}`
      : normalizedCommitTitle

    const branch = normalizedActiveBranchInput || currentBranch || 'current branch'

    setIsCommitting(true)

    try {
      const commitResponse = await fetch(buildApiUrl('/api/git/commit'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace: workspacePath,
          message: commitMessage,
          add_all: true,
        }),
      })

      const commitPayload = (await commitResponse.json().catch(() => ({}))) as GitCommitActionResponse

      if (!commitResponse.ok || commitPayload.success === false) {
        throw new Error(commitPayload.detail ?? commitPayload.error ?? `Failed to commit changes (${commitResponse.status})`)
      }

      if (commitPayload.skipped || commitPayload.reason === 'nothing_to_commit') {
        toast.info('No changes were available to commit.')
        refreshRepositoryData()
        return
      }

      setCommitTitle('')
      setCommitDescription('')

      if (!isCurrentBranchPublished) {
        const pushResponse = await fetch(buildApiUrl('/api/git/push'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace: workspacePath,
            remote: activeRemoteName,
            branch: branch,
            set_upstream: true,
          }),
        })

        const pushPayload = (await pushResponse.json().catch(() => ({}))) as { detail?: string; ok?: boolean }

        if (!pushResponse.ok) {
          toast.warning(`Committed on ${branch}. Could not publish: ${pushPayload.detail ?? 'push failed'}.`)
          refreshRepositoryData()
          return
        }

        setLastFetchedAt(new Date().toISOString())
        toast.success(`Committed and published to ${activeRemoteName}/${branch}.`)
      } else {
        toast.success(`Committed changes on ${branch}.`)
      }

      refreshRepositoryData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to commit changes')
    } finally {
      setIsCommitting(false)
    }
  }, [
    activeRemoteName,
    currentBranch,
    hasGitRepo,
    isCurrentBranchPublished,
    normalizedActiveBranchInput,
    normalizedCommitDescription,
    normalizedCommitTitle,
    refreshRepositoryData,
    workspacePath,
  ])

  const openWorkspaceInCursor = React.useCallback(async () => {
    const normalizedWorkspacePath = workspacePath.trim()

    if (!normalizedWorkspacePath) {
      toast.error('Select a workspace to open in Cursor.')
      return
    }

    setIsOpeningCursor(true)

    try {
      const response = await fetch(buildApiUrl('/api/git/open-in-cursor'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: normalizedWorkspacePath }),
      })

      const payload = (await response.json().catch(() => ({}))) as GitOpenInCursorResponse

      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to open in Cursor (${response.status})`)
      }

      toast.success('Opened workspace in Cursor.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to open in Cursor')
    } finally {
      setIsOpeningCursor(false)
    }
  }, [workspacePath])

  const openWorkspaceInFiles = React.useCallback(async () => {
    const normalizedWorkspacePath = workspacePath.trim()

    if (!normalizedWorkspacePath) {
      toast.error('Select a workspace to view in Files.')
      return
    }

    setIsOpeningFiles(true)

    try {
      const response = await fetch(buildApiUrl('/api/git/open-in-files'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: normalizedWorkspacePath }),
      })

      const payload = (await response.json().catch(() => ({}))) as GitOpenInFilesResponse

      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to open in Files (${response.status})`)
      }

      toast.success('Opened workspace in Files.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to open in Files')
    } finally {
      setIsOpeningFiles(false)
    }
  }, [workspacePath])

  const openRepositoryInBrowser = React.useCallback(() => {
    if (!repositoryWebUrl) {
      toast.error('Repository URL is unavailable for this workspace.')
      return
    }

    window.open(repositoryWebUrl, '_blank', 'noopener,noreferrer')
  }, [repositoryWebUrl])

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target
      const targetElement = target instanceof HTMLElement ? target : null
      const tagName = String(targetElement?.tagName || '').toUpperCase()
      const isTextInputTarget =
        tagName === 'INPUT' ||
        tagName === 'TEXTAREA' ||
        targetElement?.isContentEditable === true

      if (isTextInputTarget) {
        return
      }

      const hasModifier = event.metaKey || event.ctrlKey
      if (!hasModifier || !event.shiftKey) {
        return
      }

      const key = String(event.key || '').toLowerCase()

      if (key === 'e') {
        event.preventDefault()
        void openWorkspaceInCursor()
        return
      }

      if (key === 'f') {
        if (!canShowFilesAction) {
          return
        }

        event.preventDefault()
        void openWorkspaceInFiles()
        return
      }

      if (key === 'g') {
        event.preventDefault()
        openRepositoryInBrowser()
      }
    }

    window.addEventListener('keydown', handleKeyDown)

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [canShowFilesAction, openRepositoryInBrowser, openWorkspaceInCursor, openWorkspaceInFiles])

  React.useEffect(() => {
    if (gitStatusError) {
      toast.error(gitStatusError)
    }
  }, [gitStatusError])

  React.useEffect(() => {
    setActiveBranchInput(currentBranch)
  }, [currentBranch])

  React.useEffect(() => {
    if (!availableTargetBranches.length) {
      setTargetBranchInput('')
      return
    }

    setTargetBranchInput((previous) => {
      const normalizedPrevious = String(previous || '').trim()

      if (normalizedPrevious && availableTargetBranches.includes(normalizedPrevious)) {
        return normalizedPrevious
      }

      if (currentBranch && availableTargetBranches.includes(currentBranch)) {
        return currentBranch
      }

      return availableTargetBranches[0]
    })
  }, [availableTargetBranches, currentBranch])

  React.useEffect(() => {
    if (!workspacePath || !hasGitRepo) {
      setWorkingDiff('')
      setStagedDiff('')
      setDiffError(null)
      return
    }

    void loadDiffs()
  }, [hasGitRepo, loadDiffs, workspacePath])

  React.useEffect(() => {
    if (listView !== 'history') {
      return
    }

    void loadHistory()
  }, [listView, loadHistory])

  const workingFiles = React.useMemo(() => parseDiffFiles(workingDiff), [workingDiff])
  const stagedFiles = React.useMemo(() => parseDiffFiles(stagedDiff), [stagedDiff])
  const changedFiles = React.useMemo(() => mergeDiffFiles(workingFiles, stagedFiles), [workingFiles, stagedFiles])

  const filteredChangedFiles = React.useMemo(() => {
    const query = changedFileFilter.trim().toLowerCase()

    if (!query) {
      return changedFiles
    }

    return changedFiles.filter((file) => file.path.toLowerCase().includes(query))
  }, [changedFileFilter, changedFiles])

  React.useEffect(() => {
    setSelectedChangedFilePath((previousPath) => {
      const normalizedPath = String(previousPath || '').trim()

      if (normalizedPath && changedFiles.some((file) => file.path === normalizedPath)) {
        return normalizedPath
      }

      return changedFiles[0]?.path ?? ''
    })
  }, [changedFiles])

  const selectedChangedFile = React.useMemo(
    () => changedFiles.find((file) => file.path === selectedChangedFilePath) ?? null,
    [changedFiles, selectedChangedFilePath],
  )

  const filteredLocalBranchItems = React.useMemo(
    () => filteredBranchItems.filter((branch) => branch.scope === 'local'),
    [filteredBranchItems],
  )

  const filteredRemoteBranchItems = React.useMemo(
    () => filteredBranchItems.filter((branch) => branch.scope === 'remote'),
    [filteredBranchItems],
  )

  const hasGitChanges =
    changedFiles.length > 0 ||
    Number(gitStatus?.staged || 0) > 0 ||
    Number(gitStatus?.modified || 0) > 0 ||
    Number(gitStatus?.untracked || 0) > 0

  const canCommit =
    hasGitRepo &&
    hasGitChanges &&
    !isCommitting &&
    !isSwitchingBranch &&
    !isSyncing &&
    !isDeletingBranch &&
    Boolean(normalizedCommitTitle)

  const canOpenBranchPicker =
    hasGitRepo &&
    !isLoadingBranches &&
    !isSwitchingBranch &&
    !isSyncing &&
    !isCommitting &&
    !isDeletingBranch

  const canRunSyncAction =
    hasGitRepo &&
    !isSyncing &&
    !isSwitchingBranch &&
    !isCommitting &&
    !isDeletingBranch

  const canRefreshRepository =
    !isSyncing &&
    !isSwitchingBranch &&
    !isCommitting &&
    !isDeletingBranch &&
    !isLoadingDiff

  const isCurrentBranchProtected = React.useMemo(() => {
    const normalizedBranch = String(normalizedActiveBranchInput || currentBranch || '').trim().toLowerCase()

    return normalizedBranch === 'main' || normalizedBranch === 'master'
  }, [currentBranch, normalizedActiveBranchInput])

  const shouldConfirmProtectedPush = React.useMemo(
    () => resolvedSyncAction === 'push' && isCurrentBranchProtected,
    [isCurrentBranchProtected, resolvedSyncAction],
  )

  const handleRequestSyncAction = React.useCallback(() => {
    if (shouldConfirmProtectedPush) {
      setIsProtectedPushDialogOpen(true)
      return
    }

    void executeSyncAction()
  }, [executeSyncAction, shouldConfirmProtectedPush])

  const syncActionLabel = React.useMemo(() => {
    if (!isCurrentBranchPublished && resolvedSyncAction === 'push') {
      return 'Publish Branch'
    }

    const targetBranch = normalizedTargetBranchInput || currentBranch

    if (!targetBranch) {
      return `${SYNC_ACTION_LABELS[resolvedSyncAction]} ${activeRemoteName}`
    }

    return `${SYNC_ACTION_LABELS[resolvedSyncAction]} ${targetBranch}`
  }, [activeRemoteName, currentBranch, isCurrentBranchPublished, normalizedTargetBranchInput, resolvedSyncAction])

  const syncContextText = React.useMemo(() => {
    if (!isCurrentBranchPublished) {
      return 'Branch not yet published to remote'
    }

    const targetBranch = normalizedTargetBranchInput || currentBranch

    if (!targetBranch) {
      return `Remote ${activeRemoteName}`
    }

    return `Remote ${activeRemoteName}/${targetBranch}`
  }, [activeRemoteName, currentBranch, isCurrentBranchPublished, normalizedTargetBranchInput])

  const selectedDiffRows = React.useMemo(
    () => (selectedChangedFile ? buildDiffRows(selectedChangedFile.patch) : []),
    [selectedChangedFile],
  )

  return (
    <section className='flex min-h-0 flex-1 flex-col overflow-hidden border-y bg-background'>
      <div className='grid h-14 shrink-0 grid-cols-[16rem_18rem_auto_18rem_minmax(0,1fr)] border-b bg-muted/20'>
        <div className='flex min-w-0 items-center gap-2 border-r px-3'>
          <GitBranch className='text-muted-foreground size-3.5 shrink-0' />

          <div className='min-w-0'>
            <p className='text-muted-foreground text-[11px]'>Current Repository</p>

            <p className='truncate text-sm font-semibold'>{repositoryName}</p>
          </div>
        </div>

        <div
          className={cn(
            'flex min-w-0 items-center gap-2 border-r px-3 transition-colors',
            canOpenBranchPicker ? 'cursor-pointer hover:bg-black/5 dark:hover:bg-white/5' : undefined,
          )}
          role='button'
          tabIndex={canOpenBranchPicker ? 0 : -1}
          aria-disabled={!canOpenBranchPicker}
          onClick={() => {
            if (!canOpenBranchPicker) {
              return
            }

            setIsBranchSelectOpen(true)
          }}
          onKeyDown={(event) => {
            if (!canOpenBranchPicker) {
              return
            }

            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              setIsBranchSelectOpen(true)
            }
          }}
        >
          <GitBranch className='text-muted-foreground size-3.5 shrink-0' />

          <div className='min-w-0 flex-1'>
            <p className='text-muted-foreground text-[11px]'>Current Branch</p>

            <Select
              open={isBranchSelectOpen}
              onOpenChange={setIsBranchSelectOpen}
              value={normalizedActiveBranchInput || undefined}
              onValueChange={(value) => {
                setActiveBranchInput(value)
                void handleSwitchBranch(value)
              }}
              disabled={!canOpenBranchPicker}
            >
              <SelectTrigger className='h-6 border-0 bg-transparent px-0 py-0 text-left text-sm font-semibold shadow-none focus-visible:ring-0'>
                <SelectValue placeholder={isLoadingBranches ? 'Loading branches...' : 'Select branch'} />
                <ChevronDown className='text-muted-foreground size-3.5' />
              </SelectTrigger>

              <SelectContent>
                {localBranchOptions.map((branch) => (
                  <SelectItem key={branch} value={branch}>
                    {branch}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div
          className={cn(
            'flex min-w-0 items-center border-r px-3 transition-colors',
            hasGitRepo ? 'cursor-pointer hover:bg-black/5 dark:hover:bg-white/5' : undefined,
          )}
          role='button'
          tabIndex={hasGitRepo ? 0 : -1}
          aria-disabled={!hasGitRepo}
          onClick={() => {
            if (!hasGitRepo) {
              return
            }

            setIsCreateBranchDialogOpen(true)
          }}
          onKeyDown={(event) => {
            if (!hasGitRepo) {
              return
            }

            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              setIsCreateBranchDialogOpen(true)
            }
          }}
        >
          <div className={cn('flex h-6 items-center gap-1.5 text-sm font-semibold', !hasGitRepo && 'text-muted-foreground')}>
            <Plus className='size-3.5' />
            <span>New Branch</span>
          </div>
        </div>

        <div
          className={cn(
            'flex min-w-0 items-center border-r px-3 transition-colors',
            canRunSyncAction ? 'cursor-pointer hover:bg-black/5 dark:hover:bg-white/5' : undefined,
          )}
          role='button'
          tabIndex={canRunSyncAction ? 0 : -1}
          aria-disabled={!canRunSyncAction}
          onClick={() => {
            if (!canRunSyncAction) {
              return
            }

            handleRequestSyncAction()
          }}
          onKeyDown={(event) => {
            if (!canRunSyncAction) {
              return
            }

            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              handleRequestSyncAction()
            }
          }}
        >
          <div className='min-w-0'>
            <div className={cn('flex h-6 items-center gap-1.5 text-sm font-semibold', !canRunSyncAction && 'text-muted-foreground')}>
              {isSyncing ? <Loader2 className='size-3.5 animate-spin' /> : <RefreshCw className='size-3.5' />}
              <span className='truncate'>{syncActionLabel}</span>
            </div>

            <p className='text-muted-foreground truncate text-[11px]'>Last synced {formatRelativeTimestamp(lastFetchedAt)}</p>
          </div>
        </div>

        <div className='flex min-w-0 items-center justify-end gap-2 px-3'>
          {isCurrentBranchProtected ? (
            <Chip color='warning' variant='outline' className='text-[10px]'>
              Protected
            </Chip>
          ) : null}

          <Button
            type='button'
            size='icon-sm'
            variant='outline'
            className='size-7'
            disabled={!canRefreshRepository}
            onClick={() => {
              refreshRepositoryData()
            }}
            aria-label='Refresh repository view'
          >
            {isGitStatusLoading || isLoadingDiff || isLoadingBranches ? (
              <Loader2 className='size-3.5 animate-spin' />
            ) : (
              <RefreshCw className='size-3.5' />
            )}
          </Button>
        </div>
      </div>


      <Dialog
        open={isProtectedPushDialogOpen}
        onOpenChange={(isOpen) => {
          if (!isSyncing) {
            setIsProtectedPushDialogOpen(isOpen)
          }
        }}
      >
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle className='text-base'>Push to protected branch?</DialogTitle>

            <DialogDescription>
              You are about to push to {normalizedActiveBranchInput || currentBranch || 'the current branch'}, which is marked as protected.
              Please confirm you want to continue.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              onClick={() => setIsProtectedPushDialogOpen(false)}
              disabled={isSyncing}
            >
              Cancel
            </Button>

            <Button
              type='button'
              variant='default'
              disabled={isSyncing}
              onClick={() => {
                setIsProtectedPushDialogOpen(false)
                void executeSyncAction()
              }}
            >
              {isSyncing ? <Loader2 className='size-3.5 animate-spin' /> : null}
              Push anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateBranchDialog
        isOpen={isCreateBranchDialogOpen}
        workspacePath={workspacePath}
        currentBranch={currentBranch}
        localBranchOptions={localBranchOptions}
        hasGitChanges={hasGitChanges}
        onClose={() => setIsCreateBranchDialogOpen(false)}
        onSuccess={(newBranch) => {
          toast.success(`Created and switched to branch ${newBranch}.`)
          refreshRepositoryData()
        }}
      />

      {!workspacePath.trim() ? (
        <div className='text-muted-foreground flex flex-1 items-center justify-center px-6 text-sm'>
          Select a workspace to load repository changes.
        </div>
      ) : !isGitStatusLoading && gitStatus && !gitStatus.is_git_repo ? (
        <div className='text-muted-foreground flex flex-1 items-center justify-center px-6 text-sm'>
          Current workspace is not a git repository.
        </div>
      ) : (
        <div className='grid min-h-0 flex-1 grid-cols-[23rem_minmax(0,1fr)]'>
          <div className='min-h-0 border-r'>
            <div
              className={cn(
                'grid h-full min-h-0',
                listView === 'history'
                  ? 'grid-rows-[auto_auto_minmax(0,1fr)]'
                  : 'grid-rows-[auto_auto_minmax(0,1fr)_auto]',
              )}
            >
              <div className='grid h-8 grid-cols-3 border-b'>
                <Button
                  type='button'
                  variant='ghost'
                  className={cn(
                    'h-full rounded-none text-xs',
                    listView === 'changes' && 'bg-muted text-foreground',
                  )}
                  onClick={() => setListView('changes')}
                >
                  Changes

                  <Chip color='grey' variant='outline' className='text-[10px]'>
                    {changedFiles.length}
                  </Chip>
                </Button>

                <Button
                  type='button'
                  variant='ghost'
                  className={cn(
                    'h-full rounded-none text-xs',
                    listView === 'branches' && 'bg-muted text-foreground',
                  )}
                  onClick={() => setListView('branches')}
                >
                  Branches

                  <Chip color='grey' variant='outline' className='text-[10px]'>
                    {allBranchItems.length}
                  </Chip>
                </Button>

                <Button
                  type='button'
                  variant='ghost'
                  className={cn(
                    'h-full rounded-none text-xs',
                    listView === 'history' && 'bg-muted text-foreground',
                  )}
                  onClick={() => setListView('history')}
                >
                  History
                </Button>
              </div>

              <div className='border-b p-1.5'>
                {listView === 'changes' ? (
                  <div className='flex items-center gap-1 rounded-sm border bg-transparent px-2'>
                    <Filter className='text-muted-foreground size-3.5 shrink-0' />

                    <Input
                      value={changedFileFilter}
                      onChange={(event) => setChangedFileFilter(event.target.value)}
                      placeholder='Filter changes'
                      className='h-7 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-0 dark:bg-transparent'
                    />
                  </div>
                ) : listView === 'branches' ? (
                  <div className='flex items-center gap-1 rounded-sm border bg-transparent px-2'>
                    <Filter className='text-muted-foreground size-3.5 shrink-0' />

                    <Input
                      value={branchFilter}
                      onChange={(event) => setBranchFilter(event.target.value)}
                      placeholder='Filter branches'
                      className='h-7 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-0 dark:bg-transparent'
                    />
                  </div>
                ) : (
                  <div className='text-muted-foreground px-1 text-[11px]'>Recent commit history</div>
                )}
              </div>

              <div className='min-h-0'>
                {listView === 'changes' ? (
                  <div className='grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]'>
                    <div className='flex items-center gap-2 border-b px-2 py-1.5 text-xs'>
                      <input type='checkbox' checked readOnly className='size-3 accent-primary' />
                      <span>{changedFiles.length} changed files</span>
                    </div>

                    <ScrollArea className='min-h-0'>
                      <div>
                        {isLoadingDiff ? (
                          <div className='text-muted-foreground flex items-center gap-2 px-2 py-2 text-xs'>
                            <Loader2 className='size-3.5 animate-spin' />
                            Loading changed files...
                          </div>
                        ) : diffError ? (
                          <div className='px-2 py-2 text-xs text-rose-600 dark:text-rose-400'>{diffError}</div>
                        ) : filteredChangedFiles.length === 0 ? (
                          <div className='text-muted-foreground px-2 py-2 text-xs'>
                            {changedFiles.length === 0 ? 'No changed files detected.' : 'No files match this filter.'}
                          </div>
                        ) : (
                          filteredChangedFiles.map((file) => {
                            const isSelected = file.path === selectedChangedFilePath
                            const statusToken = getFileStatusToken(file.status)

                            return (
                              <button
                                key={file.path}
                                type='button'
                                className={cn(
                                  'max-w-[367px] hover:bg-muted/30 flex w-full items-center gap-2 border-b px-2 py-1.5 text-left text-xs',
                                  isSelected && 'bg-muted/60',
                                )}
                                onClick={() => setSelectedChangedFilePath(file.path)}
                              >
                                <input type='checkbox' checked readOnly className='size-3 accent-primary' />

                                <span className='min-w-0 flex-1 truncate'>{file.path}</span>

                                <span
                                  className={cn(
                                    'inline-flex size-4 items-center justify-center rounded-sm border text-[10px] font-semibold',
                                    statusToken.className,
                                  )}
                                >
                                  {statusToken.label}
                                </span>
                              </button>
                            )
                          })
                        )}
                      </div>
                    </ScrollArea>
                  </div>
                ) : listView === 'branches' ? (
                  <ScrollArea className='h-full'>
                    <div>
                      {isLoadingBranches ? (
                        <div className='text-muted-foreground flex items-center gap-2 px-2 py-2 text-xs'>
                          <Loader2 className='size-3.5 animate-spin' />
                          Loading branches...
                        </div>
                      ) : filteredBranchItems.length === 0 ? (
                        <div className='text-muted-foreground px-2 py-2 text-xs'>
                          {allBranchItems.length === 0
                            ? 'No branches detected.'
                            : 'No branches match this filter.'}
                        </div>
                      ) : (
                        filteredBranchItems.map((branch) => {
                          return (
                            <div
                              key={branch.key}
                              className='max-w-[367px] flex w-full items-center gap-2 border-b px-2 py-1.5 text-left text-xs'
                            >
                              <GitBranch className='text-muted-foreground size-3.5 shrink-0' />

                              <div className='min-w-0 flex-1'>
                                <p className='truncate'>{branch.displayName}</p>

                                <p className='text-muted-foreground text-[10px]'>
                                  {branch.scope === 'local'
                                    ? 'Local'
                                    : `Remote · ${branch.remoteName}`}
                                </p>
                              </div>

                              {branch.isCurrent ? (
                                <Chip color='success' variant='outline' className='text-[10px]'>
                                  Current
                                </Chip>
                              ) : null}
                            </div>
                          )
                        })
                      )}
                    </div>
                  </ScrollArea>
                ) : (
                  <ScrollArea className='h-full'>
                    <div>
                      {isLoadingHistory ? (
                        <div className='text-muted-foreground flex items-center gap-2 px-2 py-2 text-xs'>
                          <Loader2 className='size-3.5 animate-spin' />
                          Loading history...
                        </div>
                      ) : historyError ? (
                        <div className='px-2 py-2 text-xs text-rose-600 dark:text-rose-400'>{historyError}</div>
                      ) : recentCommits.length === 0 ? (
                        <div className='text-muted-foreground px-2 py-2 text-xs'>No commits yet.</div>
                      ) : (
                        recentCommits.map((commit) => (
                          <div key={`${commit.hash}-${commit.when}`} className='max-w-[367px] hover:bg-muted/30 border-b px-2 py-2 text-xs'>
                            <p className='truncate font-medium'>{commit.message}</p>
                            <p className='text-muted-foreground truncate text-[11px]'>{commit.author} · {commit.when}</p>
                            <p className='text-muted-foreground font-mono text-[10px]'>{commit.hash}</p>
                          </div>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                )}
              </div>

              {listView === 'changes' ? (
                <div className='space-y-2 border-t p-2'>
                  <Input
                    value={commitTitle}
                    onChange={(event) => {
                      setCommitTitle(event.target.value)
                    }}
                    placeholder='Summary (required)'
                    className='h-7 text-xs'
                    maxLength={120}
                    disabled={!hasGitRepo || isCommitting || isSyncing || isSwitchingBranch}
                  />

                  <Textarea
                    value={commitDescription}
                    onChange={(event) => setCommitDescription(event.target.value)}
                    placeholder='Description'
                    className='min-h-[100px] resize-none text-xs'
                    disabled={!hasGitRepo || isCommitting || isSyncing || isSwitchingBranch}
                  />

                  <Button
                    type='button'
                    size='sm'
                    className='h-7 w-full gap-1.5 text-xs'
                    disabled={!canCommit}
                    onClick={() => {
                      void commitChanges()
                    }}
                  >
                    {isCommitting ? <Loader2 className='size-3.5 animate-spin' /> : <GitCommit className='size-3.5' />}
                    Commit {changedFiles.length > 0 ? `${changedFiles.length} file${changedFiles.length === 1 ? '' : 's'}` : ''}
                  </Button>
                </div>
              ) : listView === 'branches' ? (
                <div className='border-t p-2'>
                  <p className='text-muted-foreground text-[11px]'>
                    Branch actions are available in the right panel.
                  </p>
                </div>
              ) : null}
            </div>
          </div>

          <div className='grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]'>
            <div className='flex h-8 items-center justify-between border-b px-3'>
              <p className='min-w-0 truncate pr-2 text-xs'>
                {listView === 'branches'
                  ? 'Branch management'
                  : selectedChangedFile
                    ? selectedChangedFile.path
                    : 'Diff preview'}
              </p>

              <div className='flex items-center gap-1'>
                {listView === 'branches' ? (
                  <>
                    <Chip color='grey' variant='outline' className='text-[10px]'>
                      {localBranchItems.length} local
                    </Chip>

                    <Chip color='grey' variant='outline' className='text-[10px]'>
                      {remoteBranchItems.length} remote
                    </Chip>
                  </>
                ) : (
                  <>
                    {typeof gitStatus?.ahead === 'number' && gitStatus.ahead > 0 ? (
                      <Chip color='success' variant='outline' className='gap-1 text-[10px]'>
                        <ArrowUp className='size-3' />
                        {gitStatus.ahead} ahead
                      </Chip>
                    ) : null}

                    {typeof gitStatus?.behind === 'number' && gitStatus.behind > 0 ? (
                      <Chip color='warning' variant='outline' className='gap-1 text-[10px]'>
                        <ArrowDown className='size-3' />
                        {gitStatus.behind} behind
                      </Chip>
                    ) : null}

                    {typeof gitStatus?.staged === 'number' &&
                    gitStatus.staged === 0 &&
                    gitStatus.modified === 0 &&
                    gitStatus.untracked === 0 ? (
                      <Chip color='success' variant='outline' className='gap-1 text-[10px]'>
                        <Check className='size-3' />
                        Clean
                      </Chip>
                    ) : null}
                  </>
                )}
              </div>
            </div>

            {listView === 'branches' ? (
              <GitBranchesPanel
                localBranches={filteredLocalBranchItems}
                remoteBranches={filteredRemoteBranchItems}
                isLoadingBranches={isLoadingBranches}
                isSwitchingBranch={isSwitchingBranch}
                isDeletingBranch={isDeletingBranch}
                deletingBranchKey={deletingBranchKey}
                onCheckoutBranch={handleSwitchBranch}
                onDeleteBranch={handleDeleteBranch}
              />
            ) : (
              <ScrollArea className='min-h-0'>
                {selectedChangedFile ? (
                  <div className='font-mono text-[11px] leading-5'>
                    {selectedDiffRows.map((row, index) => (
                      <div key={`${index}-${row.text.slice(0, 20)}`} className='grid grid-cols-[3rem_3rem_minmax(0,1fr)]'>
                        <span className='text-muted-foreground border-r px-1.5 text-right select-none'>{row.oldLine || ' '}</span>

                        <span className='text-muted-foreground border-r px-1.5 text-right select-none'>{row.newLine || ' '}</span>

                        <span className={cn('px-2 whitespace-pre-wrap', getDiffRowClassName(row.kind))}>{row.text || ' '}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  isLoadingDiff ? (
                    <div className='text-muted-foreground flex h-full items-center justify-center px-6 text-sm'>
                      Loading diff...
                    </div>
                  ) : (
                    <DiffEmptyStatePanel
                      onOpenInCursor={openWorkspaceInCursor}
                      onOpenInFiles={openWorkspaceInFiles}
                      onOpenRepository={openRepositoryInBrowser}
                      canOpenInCursor={Boolean(workspacePath.trim())}
                      canOpenInFiles={Boolean(workspacePath.trim())}
                      canOpenRepository={Boolean(repositoryWebUrl)}
                      showFilesAction={canShowFilesAction}
                      isOpeningCursor={isOpeningCursor}
                      isOpeningFiles={isOpeningFiles}
                      openRepositoryLabel={openRepositoryLabel}
                    />
                  )
                )}
              </ScrollArea>
            )}
          </div>
        </div>
      )}

      <div className='border-t px-3 py-1 text-[11px] text-muted-foreground'>
        {syncContextText} · Auto mode chooses {SYNC_ACTION_LABELS[resolvedSyncAction].toLowerCase()}.
      </div>
    </section>
  )
}

export default function GitPage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const workspacePath = useDashboardSettingsStore((state) => state.primaryWorkspacePath)

  const [configSyncError, setConfigSyncError] = React.useState<string | null>(null)
  const [configLoaded, setConfigLoaded] = React.useState(false)
  const [isSavingConfig, setIsSavingConfig] = React.useState(false)
  const [branchOptions, setBranchOptions] = React.useState<string[]>([])
  const [remoteBranchOptions, setRemoteBranchOptions] = React.useState<string[]>([])
  const [isLoadingBranches, setIsLoadingBranches] = React.useState(false)

  const workflows = useGitStore((state) => state.workflows)
  const activeTab = useGitStore((state) => state.activeTab)
  const setActiveTab = useGitStore((state) => state.setActiveTab)
  const updateSettings = useGitStore((state) => state.updateSettings)
  const replaceConfig = useGitStore((state) => state.replaceConfig)

  const lastSavedSignatureRef = React.useRef('')

  const {
    gitStatus,
    isLoading: isGitStatusLoading,
    error: gitStatusError,
    refetch: refetchGitStatus,
  } = useGitStatus(workspacePath)

  const selectableBranchOptions = React.useMemo(
    () =>
      Array.from(
        new Set(
          [
            ...(gitStatus?.branch ? [gitStatus.branch] : []),
            ...branchOptions,
          ]
            .map((branch) => String(branch || '').trim())
            .filter(Boolean),
        ),
      ),
    [branchOptions, gitStatus?.branch],
  )

  const loadBranches = React.useCallback(async () => {
    if (!workspacePath) {
      setBranchOptions([])
      setRemoteBranchOptions([])
      return
    }

    setIsLoadingBranches(true)

    try {
      const response = await fetch(buildApiUrl(`/api/git/branches?workspace=${encodeURIComponent(workspacePath)}`))
      const payload = (await response.json().catch(() => ({}))) as GitBranchesResponse

      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to load branches (${response.status})`)
      }

      const nextLocal = Array.from(
        new Set((payload.local ?? []).map((branch) => String(branch || '').trim()).filter(Boolean)),
      )

      const nextRemote = Array.from(
        new Set((payload.remote ?? []).map((branch) => String(branch || '').trim()).filter(Boolean)),
      )

      setBranchOptions(nextLocal)
      setRemoteBranchOptions(nextRemote)
    } catch (err) {
      console.error('Failed to load branches:', err)
      setBranchOptions([])
      setRemoteBranchOptions([])
    } finally {
      setIsLoadingBranches(false)
    }
  }, [workspacePath])

  React.useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Git', href: '/git' },
    ])
  }, [setBreadcrumbs])

  React.useEffect(() => {
    if (configSyncError) {
      toast.error(configSyncError)
    }
  }, [configSyncError])

  React.useEffect(() => {
    let isCancelled = false

    const loadConfig = async () => {
      try {
        const response = await fetch(buildApiUrl('/api/git/workflow-config'))

        if (!response.ok) {
          throw new Error(`Failed to load Git workflow config (${response.status})`)
        }

        const payload = (await response.json()) as GitWorkflowConfigResponse

        if (isCancelled) {
          return
        }

        if (payload?.workflows?.chat && payload?.workflows?.pipeline && payload?.workflows?.pipeline_spec) {
          replaceConfig(payload.workflows)
          lastSavedSignatureRef.current = JSON.stringify(payload)
        }

        setConfigSyncError(null)
      } catch (err) {
        if (isCancelled) {
          return
        }

        setConfigSyncError(err instanceof Error ? err.message : 'Failed to load Git workflow config')
      } finally {
        if (!isCancelled) {
          setConfigLoaded(true)
        }
      }
    }

    void loadConfig()

    return () => {
      isCancelled = true
    }
  }, [replaceConfig])

  React.useEffect(() => {
    if (!workspacePath || !gitStatus?.is_git_repo) {
      setBranchOptions([])
      setRemoteBranchOptions([])
      return
    }

    void loadBranches()
  }, [gitStatus?.is_git_repo, loadBranches, workspacePath])

  const saveWorkflowConfig = React.useCallback(async (payload: GitWorkflowConfigResponse) => {
    setIsSavingConfig(true)

    try {
      const response = await fetch(buildApiUrl('/api/git/workflow-config'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        throw new Error(`Failed to save Git workflow config (${response.status})`)
      }

      const saved = (await response.json()) as GitWorkflowConfigResponse

      lastSavedSignatureRef.current = JSON.stringify(saved)
      setConfigSyncError(null)
    } catch (err) {
      setConfigSyncError(err instanceof Error ? err.message : 'Failed to save Git workflow config')
    } finally {
      setIsSavingConfig(false)
    }
  }, [])

  React.useEffect(() => {
    if (!configLoaded) {
      return
    }

    const payload: GitWorkflowConfigResponse = { workflows }
    const signature = JSON.stringify(payload)

    if (signature === lastSavedSignatureRef.current) {
      return
    }

    const timer = window.setTimeout(() => {
      void saveWorkflowConfig(payload)
    }, 300)

    return () => {
      window.clearTimeout(timer)
    }
  }, [configLoaded, saveWorkflowConfig, workflows])

  const chatWorkflow = WORKFLOW_SECTIONS.find((workflow) => workflow.key === 'chat')
  const automationWorkflow = WORKFLOW_SECTIONS.find((workflow) => workflow.key === 'pipeline')
  const specAutomationWorkflow = WORKFLOW_SECTIONS.find((workflow) => workflow.key === 'pipeline_spec')
  const resolvedActiveTab = activeTab === 'repository' ? 'branches' : activeTab

  React.useEffect(() => {
    if (activeTab !== 'repository') {
      return
    }

    setActiveTab('branches')
  }, [activeTab, setActiveTab])

  return (
    <div className='flex min-h-0 w-full flex-1 flex-col'>
      <Tabs
        value={resolvedActiveTab}
        onValueChange={(value) => setActiveTab(value as typeof activeTab)}
        className='flex min-h-0 flex-1 flex-col gap-0'
      >
        <SiteSubheader>
          <TabsList variant='line'>
            <TabsTrigger value='branches'>MANAGE</TabsTrigger>
            <TabsTrigger value='chat-actions'>CHAT ACTIONS</TabsTrigger>
            <TabsTrigger value='automation-actions'>TICKET AUTOMATION ACTIONS</TabsTrigger>
            <TabsTrigger value='spec-automation-actions'>SPEC AUTOMATION ACTIONS</TabsTrigger>
            <TabsTrigger value='settings'>SETTINGS</TabsTrigger>
          </TabsList>
        </SiteSubheader>

        <TabsContent value='branches' className='mt-0 flex min-h-0 flex-1 flex-col'>
          <GitRepositoryWorkbench
            workspacePath={workspacePath}
            gitStatus={gitStatus}
            isGitStatusLoading={isGitStatusLoading}
            gitStatusError={gitStatusError}
            localBranchOptions={selectableBranchOptions}
            remoteBranchOptions={remoteBranchOptions}
            isLoadingBranches={isLoadingBranches}
            onReloadBranches={loadBranches}
            onRefreshGitStatus={refetchGitStatus}
          />
        </TabsContent>

        <TabsContent value='chat-actions' className='mt-0 min-h-0 flex-1 overflow-y-auto p-6'>
          <div className='space-y-6'>
            <GitPageHeader />


            {chatWorkflow ? (
              <GitWorkflowActionsSection
                workflowKey={chatWorkflow.key}
                workflowTitle={chatWorkflow.title}
                workflowSummary={chatWorkflow.summary}
                defaultBranch={workflows[chatWorkflow.key].settings.defaultBranch}
                currentBranch={gitStatus?.branch ?? null}
                selectableBranchOptions={selectableBranchOptions}
                workspacePath={workspacePath}
                isGitRepo={Boolean(gitStatus?.is_git_repo)}
                isLoadingBranches={isLoadingBranches}
                configLoaded={configLoaded}
                isSavingConfig={isSavingConfig}
                showSubtask={false}
                onDefaultBranchChange={(value) => updateSettings(chatWorkflow.key, { defaultBranch: value })}
                onSave={() => {
                  void saveWorkflowConfig({ workflows })
                }}
              />
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value='automation-actions' className='mt-0 min-h-0 flex-1 overflow-y-auto p-6'>
          <div className='space-y-6'>
            <GitPageHeader />


            {automationWorkflow ? (
              <GitWorkflowActionsSection
                workflowKey={automationWorkflow.key}
                workflowTitle={automationWorkflow.title}
                workflowSummary={automationWorkflow.summary}
                defaultBranch={workflows[automationWorkflow.key].settings.defaultBranch}
                currentBranch={gitStatus?.branch ?? null}
                selectableBranchOptions={selectableBranchOptions}
                workspacePath={workspacePath}
                isGitRepo={Boolean(gitStatus?.is_git_repo)}
                isLoadingBranches={isLoadingBranches}
                configLoaded={configLoaded}
                isSavingConfig={isSavingConfig}
                onDefaultBranchChange={(value) => updateSettings(automationWorkflow.key, { defaultBranch: value })}
                onSave={() => {
                  void saveWorkflowConfig({ workflows })
                }}
              />
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value='spec-automation-actions' className='mt-0 min-h-0 flex-1 overflow-y-auto p-6'>
          <div className='space-y-6'>
            <GitPageHeader />


            {specAutomationWorkflow ? (
              <GitWorkflowActionsSection
                workflowKey={specAutomationWorkflow.key}
                workflowTitle={specAutomationWorkflow.title}
                workflowSummary={specAutomationWorkflow.summary}
                defaultBranch={workflows[specAutomationWorkflow.key].settings.defaultBranch}
                currentBranch={gitStatus?.branch ?? null}
                selectableBranchOptions={selectableBranchOptions}
                workspacePath={workspacePath}
                isGitRepo={Boolean(gitStatus?.is_git_repo)}
                isLoadingBranches={isLoadingBranches}
                configLoaded={configLoaded}
                isSavingConfig={isSavingConfig}
                onDefaultBranchChange={(value) => updateSettings(specAutomationWorkflow.key, { defaultBranch: value })}
                onSave={() => {
                  void saveWorkflowConfig({ workflows })
                }}
              />
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value='settings' className='mt-0 min-h-0 flex-1 overflow-y-auto p-6'>
          <div className='space-y-6'>
            <GitPageHeader />


            <GitSettingsTabContent workflows={WORKFLOW_SECTIONS} />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
