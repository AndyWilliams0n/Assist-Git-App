import * as React from "react"
import { Button } from "@/shared/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/components/ui/tabs"
import { useGitHubRepos, useGitHubSettings } from "../hooks/useGitHubRepos"
import { useGitLabRepos, useGitLabSettings } from "../hooks/useGitLabRepos"
import { RepoSelector } from "./RepoSelector"
import type { GitHubRepo, GitLabRepo } from "../types"

type AnyRepo = GitHubRepo | GitLabRepo

function getRepoName(repo: AnyRepo): string {
  return repo.name
}

function getCloneUrl(repo: AnyRepo): string {
  return "clone_url" in repo ? repo.clone_url : repo.http_url_to_repo
}

function getPlatform(repo: AnyRepo): "github" | "gitlab" {
  return "clone_url" in repo ? "github" : "gitlab"
}

function getDescription(repo: AnyRepo): string {
  return repo.description ?? ""
}

function getLanguage(repo: AnyRepo): string {
  return repo.language ?? ""
}

function getStars(repo: AnyRepo): number {
  return "stars" in repo ? repo.stars : repo.star_count
}

interface AddProjectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspacePath: string
  initialTab?: "github" | "gitlab" | "manual"
  onSubmit: (data: {
    remote_url: string
    local_path: string
    platform: string
    name: string
    description: string
    language: string
    stars: number
  }) => Promise<void>
}

export function AddProjectDialog({ open, onOpenChange, workspacePath, initialTab, onSubmit }: AddProjectDialogProps) {
  const [tab, setTab] = React.useState<"github" | "gitlab" | "manual">("github")
  const [selectedRepo, setSelectedRepo] = React.useState<AnyRepo | null>(null)
  const [localPath, setLocalPath] = React.useState("")
  const [manualUrl, setManualUrl] = React.useState("")
  const [manualName, setManualName] = React.useState("")
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [showEraseConfirm, setShowEraseConfirm] = React.useState(false)

  const githubSettings = useGitHubSettings()
  const gitlabSettings = useGitLabSettings()
  const hasGitHubToken = Boolean(githubSettings.settings?.has_token)
  const hasGitLabToken = Boolean(gitlabSettings.settings?.has_token)
  const availableTabs = React.useMemo(() => {
    const tabs: Array<"github" | "gitlab" | "manual"> = []
    if (hasGitHubToken) tabs.push("github")
    if (hasGitLabToken) tabs.push("gitlab")
    tabs.push("manual")
    return tabs
  }, [hasGitHubToken, hasGitLabToken])

  const github = useGitHubRepos(open && tab === "github")
  const gitlab = useGitLabRepos(open && tab === "gitlab")
  const workspaceRoot = React.useMemo(() => (workspacePath ? workspacePath.replace(/\/$/, "") : ""), [workspacePath])

  React.useEffect(() => {
    if (!open) return
    if (initialTab) {
      setTab(initialTab)
      setSelectedRepo(null)
    }
    setShowEraseConfirm(false)
    setError(null)
    if (!availableTabs.includes(tab)) {
      setTab(availableTabs[0] ?? "manual")
    }
  }, [open, tab, availableTabs, initialTab])

  // Auto-fill local path when repo selected
  React.useEffect(() => {
    if (selectedRepo) {
      setLocalPath(workspaceRoot)
    }
  }, [selectedRepo, workspaceRoot])

  // Keep manual clone path pinned to the selected workspace root.
  React.useEffect(() => {
    if (tab !== "manual") return
    setLocalPath(workspaceRoot)
  }, [tab, manualName, workspaceRoot])

  // Prefill the field with the selected workspace path even before a repo is chosen.
  React.useEffect(() => {
    if (!open) return
    if (!selectedRepo && tab !== "manual") {
      setLocalPath(workspaceRoot)
    }
  }, [open, selectedRepo, tab, workspaceRoot])

  const handleSubmit = async () => {
    setError(null)
    if (!localPath.trim()) {
      setError("Local path is required")
      return
    }

    let data: Parameters<typeof onSubmit>[0]

    if (tab === "manual") {
      if (!manualUrl.trim() || !manualName.trim()) {
        setError("URL and name are required")
        return
      }
      data = {
        remote_url: manualUrl.trim(),
        local_path: localPath.trim(),
        platform: "unknown",
        name: manualName.trim(),
        description: "",
        language: "",
        stars: 0,
      }
    } else {
      if (!selectedRepo) {
        setError("Please select a repository")
        return
      }
      data = {
        remote_url: getCloneUrl(selectedRepo),
        local_path: localPath.trim(),
        platform: getPlatform(selectedRepo),
        name: getRepoName(selectedRepo),
        description: getDescription(selectedRepo),
        language: getLanguage(selectedRepo),
        stars: getStars(selectedRepo),
      }
    }

    setIsSubmitting(true)
    try {
      await onSubmit(data)
      setSelectedRepo(null)
      setLocalPath("")
      setManualUrl("")
      setManualName("")
      setShowEraseConfirm(false)
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add project")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl p-0 gap-0">
        <DialogHeader className="px-6 pt-6 pb-4 border-b">
          <DialogTitle>Add Repository</DialogTitle>
        </DialogHeader>

        <div className="max-h-[70vh] overflow-y-auto px-6 py-4 space-y-4">
          <div className="space-y-1">
            <p className="text-sm font-medium">Clone a project from:</p>
            <p className="text-xs text-muted-foreground">
              Choose a provider with a configured token, or use a manual clone URL.
            </p>
          </div>

          <Tabs value={tab} onValueChange={(v) => { setTab(v as typeof tab); setSelectedRepo(null) }}>
            <TabsList className="w-full">
              {hasGitHubToken && <TabsTrigger value="github" className="flex-1 text-xs">GitHub</TabsTrigger>}
              {hasGitLabToken && <TabsTrigger value="gitlab" className="flex-1 text-xs">GitLab</TabsTrigger>}
              <TabsTrigger value="manual" className="flex-1 text-xs">Manual URL</TabsTrigger>
            </TabsList>

            {hasGitHubToken && (
              <TabsContent value="github" className="mt-4">
                <RepoSelector
                  repos={github.repos}
                  isLoading={github.isLoading}
                  error={github.error}
                  hasMore={github.hasMore}
                  search={github.search}
                  onSearch={github.handleSearch}
                  onLoadMore={github.loadMore}
                  selectedRepo={selectedRepo}
                  onSelect={setSelectedRepo}
                />
              </TabsContent>
            )}

            {hasGitLabToken && (
              <TabsContent value="gitlab" className="mt-4">
                <RepoSelector
                  repos={gitlab.repos}
                  isLoading={gitlab.isLoading}
                  error={gitlab.error}
                  hasMore={gitlab.hasMore}
                  search={gitlab.search}
                  onSearch={gitlab.handleSearch}
                  onLoadMore={gitlab.loadMore}
                  selectedRepo={selectedRepo}
                  onSelect={setSelectedRepo}
                />
              </TabsContent>
            )}

            <TabsContent value="manual" className="mt-4 space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Repository Name</Label>
                <Input
                  placeholder="my-project"
                  value={manualName}
                  onChange={(e) => setManualName(e.target.value)}
                  className="text-sm h-8"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Clone URL</Label>
                <Input
                  placeholder="https://github.com/user/repo.git"
                  value={manualUrl}
                  onChange={(e) => setManualUrl(e.target.value)}
                  className="text-sm h-8"
                />
              </div>
            </TabsContent>
          </Tabs>

          {!hasGitHubToken && !hasGitLabToken && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-700">
              No GitHub or GitLab token is configured yet. Configure one in the workspace page "API Tokens" panel to browse repositories.
            </div>
          )}

          <div className="space-y-1.5">
            <Label className="text-xs">Local Clone Path</Label>
            <Input
              placeholder="/Users/you/projects/my-repo"
              value={localPath}
              readOnly
              disabled
              className="text-sm h-8"
            />
            <p className="text-xs text-muted-foreground">
              Locked to the selected workspace folder root.
            </p>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
          {showEraseConfirm && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-800">
              All files in this workspace folder will be erased before cloning. Click Continue to proceed.
            </div>
          )}
        </div>

        <DialogFooter className="border-t px-6 py-4 flex-row justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {showEraseConfirm ? (
            <Button onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? "Adding & Cloning..." : "Continue"}
            </Button>
          ) : (
            <Button
              onClick={() => {
                setError(null)
                setShowEraseConfirm(true)
              }}
              disabled={isSubmitting}
            >
              Add & Clone Repository
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
