import * as React from "react"
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  GitBranch,
  GitCommit,
  Loader2,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Upload,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/shared/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/components/ui/select"
import { useGitStatus } from "@/features/git/hooks/useGitStatus"
import { Chip } from "@/shared/components/chip"
import { cn } from "@/shared/utils/utils.ts"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)
const MAX_DIFF_PREVIEW_LINES = 420

type DiffMode = "working" | "staged"

interface GitBranchesResponse {
  detail?: string
  current?: string
  local?: string[]
  remote?: string[]
}

interface GitDiffResponse {
  detail?: string
  diff?: string
  staged?: boolean
}

interface GitCommitActionResponse {
  detail?: string
  success?: boolean
  skipped?: boolean
  reason?: string
  output?: string
  error?: string
}

interface GitPushActionResponse {
  detail?: string
  ok?: boolean
  git?: {
    remote?: string
    branch?: string
  }
}

interface DiffStats {
  files: number
  added: number
  removed: number
}

function canForceSyncFromError(errorText: string | null): boolean {
  const normalized = String(errorText || "").toLowerCase()
  if (!normalized) return false
  return (
    normalized.includes("would be overwritten by merge") ||
    normalized.includes("please move or remove them before you merge") ||
    normalized.includes("please commit your changes or stash them") ||
    normalized.includes("your local changes to the following files would be overwritten")
  )
}

function extractDiffStats(diffText: string): DiffStats {
  let files = 0
  let added = 0
  let removed = 0

  for (const line of diffText.split("\n")) {
    if (line.startsWith("diff --git ")) {
      files += 1
      continue
    }
    if (line.startsWith("+") && !line.startsWith("+++")) {
      added += 1
      continue
    }
    if (line.startsWith("-") && !line.startsWith("---")) {
      removed += 1
    }
  }

  return { files, added, removed }
}

function diffLineClassName(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10"
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "text-rose-600 dark:text-rose-400 bg-rose-500/10"
  }
  if (line.startsWith("@@")) {
    return "text-sky-600 dark:text-sky-400"
  }
  if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++")) {
    return "text-muted-foreground"
  }
  return "text-foreground/90"
}

interface ActiveWorkspaceBranchCardProps {
  workspacePath: string
  refreshSignal?: number
}

export function ActiveWorkspaceBranchCard({ workspacePath, refreshSignal }: ActiveWorkspaceBranchCardProps) {
  const [localBranchOptions, setLocalBranchOptions] = React.useState<string[]>([])
  const [remoteBranchOptions, setRemoteBranchOptions] = React.useState<string[]>([])
  const [activeBranchInput, setActiveBranchInput] = React.useState("")
  const [newBranchName, setNewBranchName] = React.useState("")
  const [commitMessage, setCommitMessage] = React.useState("")
  const [branchFilter, setBranchFilter] = React.useState("")
  const [diffMode, setDiffMode] = React.useState<DiffMode>("working")
  const [diffText, setDiffText] = React.useState("")
  const [isLoadingBranches, setIsLoadingBranches] = React.useState(false)
  const [isLoadingDiff, setIsLoadingDiff] = React.useState(false)
  const [isSwitchingBranch, setIsSwitchingBranch] = React.useState(false)
  const [isPullingBranch, setIsPullingBranch] = React.useState(false)
  const [isCommittingChanges, setIsCommittingChanges] = React.useState(false)
  const [isPushingBranch, setIsPushingBranch] = React.useState(false)
  const [isForceSyncingBranch, setIsForceSyncingBranch] = React.useState(false)
  const [isCreatingBranch, setIsCreatingBranch] = React.useState(false)
  const [forceSyncDialogOpen, setForceSyncDialogOpen] = React.useState(false)
  const [branchActionError, setBranchActionError] = React.useState<string | null>(null)
  const [diffError, setDiffError] = React.useState<string | null>(null)

  const {
    gitStatus,
    isLoading: isLoadingGitStatus,
    error: gitStatusError,
    refetch,
  } = useGitStatus(workspacePath)

  const canShowForceSync = canForceSyncFromError(branchActionError)
  const currentWorkspaceBranch = String(gitStatus?.branch || "").trim()
  const activeRemoteName = String(gitStatus?.remotes?.[0]?.name || "origin").trim() || "origin"
  const normalizedActiveBranchInput = activeBranchInput.trim()
  const normalizedNewBranchName = newBranchName.trim()
  const normalizedCommitMessage = commitMessage.trim()
  const stagedChangeCount = Number(gitStatus?.staged || 0)
  const modifiedChangeCount = Number(gitStatus?.modified || 0)
  const untrackedChangeCount = Number(gitStatus?.untracked || 0)
  const hasWorkingTreeChanges = stagedChangeCount > 0 || modifiedChangeCount > 0 || untrackedChangeCount > 0
  const hasStagedChanges = stagedChangeCount > 0
  const commitUsesAddAll = diffMode === "working"
  const canCommitCurrentDiff = commitUsesAddAll ? hasWorkingTreeChanges : hasStagedChanges
  const hasOutgoingCommits = Number(gitStatus?.ahead || 0) > 0
  const isBranchSelectionChanged = Boolean(normalizedActiveBranchInput) && normalizedActiveBranchInput !== currentWorkspaceBranch
  const branchActionsBusy = (
    isSwitchingBranch ||
    isPullingBranch ||
    isCommittingChanges ||
    isPushingBranch ||
    isForceSyncingBranch ||
    isCreatingBranch
  )

  const localBranches = React.useMemo(
    () =>
      Array.from(
        new Set(
          [
            ...(gitStatus?.branch ? [gitStatus.branch] : []),
            ...localBranchOptions,
          ]
            .map((branch) => String(branch || "").trim())
            .filter(Boolean)
        )
      ),
    [gitStatus?.branch, localBranchOptions]
  )

  const filteredLocalBranches = React.useMemo(() => {
    const query = branchFilter.trim().toLowerCase()
    if (!query) return localBranches
    return localBranches.filter((branch) => branch.toLowerCase().includes(query))
  }, [branchFilter, localBranches])

  const filteredRemoteBranches = React.useMemo(() => {
    const query = branchFilter.trim().toLowerCase()
    if (!query) return remoteBranchOptions
    return remoteBranchOptions.filter((branch) => branch.toLowerCase().includes(query))
  }, [branchFilter, remoteBranchOptions])

  const diffPreviewLines = React.useMemo(() => {
    if (!diffText) return []
    return diffText.split("\n").slice(0, MAX_DIFF_PREVIEW_LINES)
  }, [diffText])

  const hasDiffOverflow = React.useMemo(() => {
    if (!diffText) return false
    return diffText.split("\n").length > MAX_DIFF_PREVIEW_LINES
  }, [diffText])

  const diffStats = React.useMemo(() => extractDiffStats(diffText), [diffText])
  const previousRefreshSignalRef = React.useRef<number | undefined>(refreshSignal)

  const loadBranches = React.useCallback(async () => {
    if (!workspacePath) {
      setLocalBranchOptions([])
      setRemoteBranchOptions([])
      return
    }

    setIsLoadingBranches(true)
    try {
      const res = await fetch(buildApiUrl(`/api/git/branches?workspace=${encodeURIComponent(workspacePath)}`))
      const payload = (await res.json().catch(() => ({}))) as GitBranchesResponse
      if (!res.ok) {
        throw new Error(payload?.detail ?? `Failed to load branches (${res.status})`)
      }

      const nextLocal = Array.from(
        new Set((payload.local ?? []).map((branch) => String(branch || "").trim()).filter(Boolean))
      )
      const nextRemote = Array.from(
        new Set((payload.remote ?? []).map((branch) => String(branch || "").trim()).filter(Boolean))
      )

      setLocalBranchOptions(nextLocal)
      setRemoteBranchOptions(nextRemote)
      const remoteCurrent = String(payload.current || "").trim()
      if (remoteCurrent) {
        setActiveBranchInput((previous) => (previous.trim() ? previous : remoteCurrent))
      }
    } catch (err) {
      setLocalBranchOptions([])
      setRemoteBranchOptions([])
      toast.error(err instanceof Error ? err.message : "Failed to load branches")
    } finally {
      setIsLoadingBranches(false)
    }
  }, [workspacePath])

  const loadDiff = React.useCallback(
    async (mode: DiffMode = diffMode) => {
      if (!workspacePath) {
        setDiffText("")
        setDiffError(null)
        return
      }

      setIsLoadingDiff(true)
      try {
        const staged = mode === "staged"
        const res = await fetch(
          buildApiUrl(`/api/git/diff?workspace=${encodeURIComponent(workspacePath)}&staged=${staged}`)
        )
        const payload = (await res.json().catch(() => ({}))) as GitDiffResponse
        if (!res.ok) {
          throw new Error(payload?.detail ?? `Failed to load ${mode} diff (${res.status})`)
        }

        setDiffText(String(payload.diff || ""))
        setDiffError(null)
      } catch (err) {
        setDiffText("")
        setDiffError(err instanceof Error ? err.message : "Failed to load diff")
      } finally {
        setIsLoadingDiff(false)
      }
    },
    [diffMode, workspacePath]
  )

  const refreshWorkspaceData = React.useCallback(async () => {
    await Promise.all([loadBranches(), loadDiff(diffMode), refetch()])
  }, [diffMode, loadBranches, loadDiff, refetch])

  const switchToBranch = React.useCallback(
    async (branchName: string) => {
      const branch = String(branchName || "").trim()
      if (!workspacePath || !branch || !gitStatus?.is_git_repo) return

      setIsSwitchingBranch(true)
      setBranchActionError(null)
      try {
        const res = await fetch(buildApiUrl("/api/git/branch"), {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workspace: workspacePath, branch }),
        })
        const payload = (await res.json().catch(() => ({}))) as { detail?: string }
        if (!res.ok) {
          throw new Error(payload?.detail ?? `Failed to switch branch (${res.status})`)
        }

        setActiveBranchInput(branch)
        toast.success(`Switched to ${branch}`)
        await refreshWorkspaceData()
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to switch branch"
        setBranchActionError(message)
        toast.error(message)
      } finally {
        setIsSwitchingBranch(false)
      }
    },
    [gitStatus?.is_git_repo, refreshWorkspaceData, workspacePath]
  )

  const commitChanges = React.useCallback(async () => {
    if (!workspacePath || !gitStatus?.is_git_repo || !normalizedCommitMessage) return

    const commitScopeLabel = commitUsesAddAll ? "working tree" : "staged changes"

    setIsCommittingChanges(true)
    try {
      const res = await fetch(buildApiUrl("/api/git/commit"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: workspacePath,
          message: normalizedCommitMessage,
          add_all: commitUsesAddAll,
        }),
      })
      const payload = (await res.json().catch(() => ({}))) as GitCommitActionResponse
      if (!res.ok || payload.success === false) {
        throw new Error(payload?.detail ?? payload?.error ?? `Failed to commit ${commitScopeLabel} (${res.status})`)
      }

      if (payload.skipped || payload.reason === "nothing_to_commit") {
        toast.info(`No ${commitScopeLabel} changes available to commit.`)
      } else {
        setCommitMessage("")
        toast.success(`Committed ${commitScopeLabel} on ${currentWorkspaceBranch || "current branch"}.`)
      }

      await refreshWorkspaceData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to commit changes")
    } finally {
      setIsCommittingChanges(false)
    }
  }, [
    commitUsesAddAll,
    currentWorkspaceBranch,
    gitStatus?.is_git_repo,
    normalizedCommitMessage,
    refreshWorkspaceData,
    workspacePath,
  ])

  const pushBranch = React.useCallback(async () => {
    if (!workspacePath || !gitStatus?.is_git_repo || !currentWorkspaceBranch) return

    setIsPushingBranch(true)
    try {
      const res = await fetch(buildApiUrl("/api/git/push"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: workspacePath,
          remote: activeRemoteName,
          branch: currentWorkspaceBranch,
          set_upstream: true,
        }),
      })
      const payload = (await res.json().catch(() => ({}))) as GitPushActionResponse
      if (!res.ok || payload.ok === false) {
        throw new Error(payload?.detail ?? `Failed to push ${currentWorkspaceBranch} (${res.status})`)
      }

      const pushedBranch = String(payload.git?.branch || currentWorkspaceBranch).trim()
      const pushedRemote = String(payload.git?.remote || activeRemoteName).trim()
      toast.success(`Pushed ${pushedBranch || "current branch"} to ${pushedRemote || "origin"}.`)

      await refreshWorkspaceData()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to push branch")
    } finally {
      setIsPushingBranch(false)
    }
  }, [activeRemoteName, currentWorkspaceBranch, gitStatus?.is_git_repo, refreshWorkspaceData, workspacePath])

  React.useEffect(() => {
    setActiveBranchInput(gitStatus?.branch ?? "")
  }, [gitStatus?.branch, workspacePath])

  React.useEffect(() => {
    if (!workspacePath || !gitStatus?.is_git_repo) {
      setLocalBranchOptions([])
      setRemoteBranchOptions([])
      setDiffText("")
      setDiffError(null)
      return
    }

    void loadBranches()
    void loadDiff(diffMode)
  }, [diffMode, gitStatus?.is_git_repo, loadBranches, loadDiff, workspacePath])

  React.useEffect(() => {
    if (refreshSignal === undefined) return
    if (previousRefreshSignalRef.current === refreshSignal) return

    previousRefreshSignalRef.current = refreshSignal
    if (!workspacePath || !gitStatus?.is_git_repo) return

    setBranchActionError(null)
    void refreshWorkspaceData()
  }, [gitStatus?.is_git_repo, refreshSignal, refreshWorkspaceData, workspacePath])

  const statusHeadline = gitStatusError
    ? gitStatusError
    : !workspacePath
      ? "Select a workspace to manage branches."
      : !gitStatus?.is_git_repo
        ? "Current workspace is not a git repository."
        : "Use this panel for branch switching, branch creation, and troubleshooting."

  return (
    <>
      <section className="rounded-lg border bg-card p-4 space-y-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <GitBranch className="size-4" />
              Active Workspace Branch
            </h2>

            <p className="text-xs text-muted-foreground">{statusHeadline}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {isLoadingGitStatus ? (
              <Chip color="grey" variant="outline" className="gap-1">
                <Loader2 className="size-3 animate-spin" />
                Loading status
              </Chip>
            ) : null}

            {currentWorkspaceBranch ? (
              <Chip color="info" variant="outline" className="gap-1">
                <GitBranch className="size-3" />
                {currentWorkspaceBranch}
              </Chip>
            ) : null}

            {typeof gitStatus?.ahead === "number" && gitStatus.ahead > 0 ? (
              <Chip color="success" variant="outline" className="gap-1">
                <ArrowUp className="size-3" />
                {gitStatus.ahead} ahead
              </Chip>
            ) : null}

            {typeof gitStatus?.behind === "number" && gitStatus.behind > 0 ? (
              <Chip color="warning" variant="outline" className="gap-1">
                <ArrowDown className="size-3" />
                {gitStatus.behind} behind
              </Chip>
            ) : null}

            {typeof gitStatus?.staged === "number" ? (
              <Chip color="success" variant="outline">{gitStatus.staged} staged</Chip>
            ) : null}

            {typeof gitStatus?.modified === "number" ? (
              <Chip color="error" variant="outline">{gitStatus.modified} modified</Chip>
            ) : null}

            {typeof gitStatus?.untracked === "number" ? (
              <Chip color="warning" variant="outline">{gitStatus.untracked} untracked</Chip>
            ) : null}
          </div>
        </div>

        <div className="rounded-md border p-3 space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Active Branch Controls</h3>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground">Remote {activeRemoteName}</span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-7"
                      aria-label="More branch actions"
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      variant="destructive"
                      disabled={!canShowForceSync || !workspacePath || !gitStatus?.is_git_repo || branchActionsBusy}
                      onClick={() => setForceSyncDialogOpen(true)}
                    >
                      <AlertTriangle className="size-3.5" />
                      Force Sync Branch
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_auto]">
              <div className="space-y-1">
                <Label htmlFor="workspace-active-branch-input" className="text-xs">Branch Name</Label>
                <Select
                  value={normalizedActiveBranchInput || undefined}
                  onValueChange={(value) => {
                    setActiveBranchInput(value)
                    setBranchActionError(null)
                  }}
                  disabled={!workspacePath || !gitStatus?.is_git_repo || isLoadingBranches || branchActionsBusy}
                >
                  <SelectTrigger id="workspace-active-branch-input" className="h-8 w-full">
                    <SelectValue placeholder={isLoadingBranches ? "Loading branches..." : "Select branch"} />
                  </SelectTrigger>
                  <SelectContent>
                    {localBranches.map((branch) => (
                      <SelectItem key={branch} value={branch}>{branch}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {isBranchSelectionChanged ? (
                <Button
                  type="button"
                  size="sm"
                  className="h-8 gap-1.5 xl:self-end"
                  disabled={
                    !workspacePath ||
                    !gitStatus?.is_git_repo ||
                    branchActionsBusy ||
                    !normalizedActiveBranchInput
                  }
                  onClick={() => void switchToBranch(normalizedActiveBranchInput)}
                >
                  {isSwitchingBranch ? <Loader2 className="size-3.5 animate-spin" /> : <GitBranch className="size-3.5" />}
                  Switch Branch
                </Button>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 gap-1.5 xl:self-end"
                  disabled={!workspacePath || !gitStatus?.is_git_repo || branchActionsBusy}
                  onClick={async () => {
                    if (!workspacePath || !gitStatus?.is_git_repo) return

                    setIsPullingBranch(true)
                    setBranchActionError(null)
                    try {
                      const res = await fetch(buildApiUrl("/api/git/pull"), {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          workspace: workspacePath,
                          remote: activeRemoteName,
                          branch: currentWorkspaceBranch || undefined,
                          ff_only: true,
                        }),
                      })
                      const payload = (await res.json().catch(() => ({}))) as { detail?: string }
                      if (!res.ok) {
                        throw new Error(payload?.detail ?? `Failed to pull latest changes (${res.status})`)
                      }

                      toast.success("Pulled latest changes (fast-forward only)")
                      await refreshWorkspaceData()
                    } catch (err) {
                      const message = err instanceof Error ? err.message : "Failed to pull latest changes"
                      setBranchActionError(message)
                      toast.error(message)
                    } finally {
                      setIsPullingBranch(false)
                    }
                  }}
                >
                  {isPullingBranch ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                  Pull
                </Button>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Branch Creation And Recovery</h3>
            <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_auto]">
              <Input
                value={newBranchName}
                onChange={(event) => {
                  setNewBranchName(event.target.value)
                  setBranchActionError(null)
                }}
                placeholder="Create a new branch (e.g. feature/DEV-123)"
                className="h-8"
                disabled={!workspacePath || !gitStatus?.is_git_repo || branchActionsBusy}
              />

              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5"
                disabled={!workspacePath || !gitStatus?.is_git_repo || branchActionsBusy || !normalizedNewBranchName}
                onClick={async () => {
                  if (!workspacePath || !gitStatus?.is_git_repo || !normalizedNewBranchName) return

                  setIsCreatingBranch(true)
                  try {
                    const res = await fetch(buildApiUrl("/api/git/branch"), {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        workspace: workspacePath,
                        branch_name: normalizedNewBranchName,
                        base_branch: currentWorkspaceBranch || undefined,
                      }),
                    })
                    const payload = (await res.json().catch(() => ({}))) as { error?: string; detail?: string }
                    if (!res.ok) {
                      throw new Error(payload?.detail ?? payload?.error ?? `Failed to create branch (${res.status})`)
                    }

                    setActiveBranchInput(normalizedNewBranchName)
                    setNewBranchName("")
                    toast.success(`Created and switched to ${normalizedNewBranchName}`)
                    await refreshWorkspaceData()
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : "Failed to create branch")
                  } finally {
                    setIsCreatingBranch(false)
                  }
                }}
              >
                {isCreatingBranch ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
                Create Branch
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-md border p-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Branch Explorer</h3>
              <span className="text-[11px] text-muted-foreground">
                {localBranches.length} local / {remoteBranchOptions.length} remote
              </span>
            </div>

            <Input
              value={branchFilter}
              onChange={(event) => setBranchFilter(event.target.value)}
              placeholder="Filter branches..."
              className="h-8"
              disabled={!workspacePath || !gitStatus?.is_git_repo}
            />

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="space-y-2">
                <p className="text-[11px] font-medium text-muted-foreground">Local Branches</p>
                <ScrollArea className="h-48 rounded-md border">
                  <div className="p-1.5 space-y-1">
                    {filteredLocalBranches.length === 0 ? (
                      <p className="px-2 py-1.5 text-[11px] text-muted-foreground">No matching local branches.</p>
                    ) : (
                      filteredLocalBranches.map((branch) => {
                        const isCurrent = branch === currentWorkspaceBranch
                        const isSelected = branch === normalizedActiveBranchInput
                        return (
                          <div
                            key={branch}
                            className={cn(
                              "flex items-center justify-between gap-2 rounded-sm border px-2 py-1.5",
                              isCurrent && "border-emerald-500/40 bg-emerald-500/10",
                              !isCurrent && isSelected && "border-sky-500/40 bg-sky-500/10"
                            )}
                          >
                            <button
                              type="button"
                              className="min-w-0 flex-1 truncate text-left text-xs"
                              onClick={() => {
                                setActiveBranchInput(branch)
                                setBranchActionError(null)
                              }}
                            >
                              {branch}
                            </button>

                            {isCurrent ? (
                              <Chip color="success" variant="outline" className="text-[10px] px-1.5 py-0">Current</Chip>
                            ) : (
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="h-6 px-2 text-[10px]"
                                disabled={branchActionsBusy}
                                onClick={() => void switchToBranch(branch)}
                              >
                                Checkout
                              </Button>
                            )}
                          </div>
                        )
                      })
                    )}
                  </div>
                </ScrollArea>
              </div>

              <div className="space-y-2">
                <p className="text-[11px] font-medium text-muted-foreground">Remote Branches</p>
                <ScrollArea className="h-48 rounded-md border">
                  <div className="p-1.5 space-y-1">
                    {filteredRemoteBranches.length === 0 ? (
                      <p className="px-2 py-1.5 text-[11px] text-muted-foreground">No matching remote branches.</p>
                    ) : (
                      filteredRemoteBranches.map((branch) => (
                        <div key={branch} className="rounded-sm border px-2 py-1.5 text-xs text-muted-foreground truncate">
                          {branch}
                        </div>
                      ))
                    )}
                  </div>
                </ScrollArea>
              </div>
            </div>
          </div>

          <div className="rounded-md border p-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Diff Inspector</h3>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  size="sm"
                  variant={diffMode === "working" ? "default" : "outline"}
                  className="h-7 px-2 text-[11px]"
                  onClick={() => setDiffMode("working")}
                  disabled={!workspacePath || !gitStatus?.is_git_repo || isLoadingDiff}
                >
                  Working
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={diffMode === "staged" ? "default" : "outline"}
                  className="h-7 px-2 text-[11px]"
                  onClick={() => setDiffMode("staged")}
                  disabled={!workspacePath || !gitStatus?.is_git_repo || isLoadingDiff}
                >
                  Staged
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <Chip color="grey" variant="outline">{diffStats.files} files</Chip>
              <Chip color="success" variant="outline">+{diffStats.added} added</Chip>
              <Chip color="error" variant="outline">-{diffStats.removed} removed</Chip>
            </div>

            {diffError ? (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-700">
                {diffError}
              </div>
            ) : isLoadingDiff ? (
              <div className="rounded-md border px-3 py-6 text-xs text-muted-foreground flex items-center gap-2">
                <Loader2 className="size-3.5 animate-spin" />
                Loading diff preview...
              </div>
            ) : diffPreviewLines.length === 0 ? (
              <div className="rounded-md border px-3 py-6 text-xs text-muted-foreground">
                No {diffMode === "staged" ? "staged" : "working tree"} diff detected.
              </div>
            ) : (
              <ScrollArea className="h-80 rounded-md border">
                <pre className="font-mono text-[11px] leading-5">
                  {diffPreviewLines.map((line, index) => (
                    <div key={`${index}-${line.slice(0, 12)}`} className={cn("px-2 py-0.5 whitespace-pre-wrap", diffLineClassName(line))}>
                      {line || " "}
                    </div>
                  ))}
                  {hasDiffOverflow ? (
                    <div className="px-2 py-1 text-muted-foreground text-[10px]">
                      Preview limited to the first {MAX_DIFF_PREVIEW_LINES} lines.
                    </div>
                  ) : null}
                </pre>
              </ScrollArea>
            )}
          </div>
        </div>

        <div className="rounded-md border p-3 space-y-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Commit And Push</h3>
              <p className="text-[11px] text-muted-foreground">
                Commit manually from the diff inspector, then push the active workspace branch.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <Chip color={commitUsesAddAll ? "info" : "warning"} variant="outline">
                {commitUsesAddAll ? "Mode: Working Tree" : "Mode: Staged Only"}
              </Chip>
              <Chip color={hasOutgoingCommits ? "success" : "grey"} variant="outline">
                {hasOutgoingCommits ? `${gitStatus?.ahead || 0} ahead to push` : "No outgoing commits"}
              </Chip>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              value={commitMessage}
              onChange={(event) => {
                setCommitMessage(event.target.value)
                setBranchActionError(null)
              }}
              placeholder="Commit message (e.g. feat: add manual commit controls)"
              className="h-8"
              maxLength={180}
              disabled={!workspacePath || !gitStatus?.is_git_repo || branchActionsBusy}
            />

            {hasOutgoingCommits ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5"
                disabled={!workspacePath || !gitStatus?.is_git_repo || branchActionsBusy || !currentWorkspaceBranch}
                onClick={() => void pushBranch()}
              >
                {isPushingBranch ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
                Push Branch
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                className="h-8 gap-1.5"
                disabled={
                  !workspacePath ||
                  !gitStatus?.is_git_repo ||
                  branchActionsBusy ||
                  !normalizedCommitMessage ||
                  !canCommitCurrentDiff
                }
                onClick={() => void commitChanges()}
              >
                {isCommittingChanges ? <Loader2 className="size-3.5 animate-spin" /> : <GitCommit className="size-3.5" />}
                {commitUsesAddAll ? "Commit Working Tree" : "Commit Staged"}
              </Button>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">
            {commitUsesAddAll
              ? "Working mode stages modified and untracked files before committing."
              : "Staged mode commits only files that are already staged."}
          </p>
        </div>

      </section>

      <Dialog open={forceSyncDialogOpen} onOpenChange={setForceSyncDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Force Sync Branch?</DialogTitle>
            <DialogDescription>
              This will fetch the remote branch, delete untracked files, and hard-reset the local branch to match the remote exactly.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-sm">
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-700 dark:text-amber-300">
              Local untracked files and local modifications on <strong>{currentWorkspaceBranch || "the current branch"}</strong> will be discarded.
            </div>
            {branchActionError ? (
              <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                Triggering error: {branchActionError}
              </div>
            ) : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setForceSyncDialogOpen(false)} disabled={isForceSyncingBranch}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={!workspacePath || !gitStatus?.is_git_repo || isForceSyncingBranch}
              onClick={async () => {
                if (!workspacePath || !gitStatus?.is_git_repo) return

                setIsForceSyncingBranch(true)
                setBranchActionError(null)
                try {
                  const res = await fetch(buildApiUrl("/api/git/force-sync"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      workspace: workspacePath,
                      remote: activeRemoteName,
                      branch: currentWorkspaceBranch || undefined,
                    }),
                  })
                  const payload = (await res.json().catch(() => ({}))) as { detail?: string }
                  if (!res.ok) {
                    throw new Error(payload?.detail ?? `Failed to force sync branch (${res.status})`)
                  }

                  toast.success(`Force-synced ${currentWorkspaceBranch || "current branch"} to remote`)
                  setForceSyncDialogOpen(false)
                  await refreshWorkspaceData()
                } catch (err) {
                  const message = err instanceof Error ? err.message : "Failed to force sync branch"
                  setBranchActionError(message)
                  toast.error(message)
                } finally {
                  setIsForceSyncingBranch(false)
                }
              }}
            >
              {isForceSyncingBranch ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Confirm Force Sync
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
