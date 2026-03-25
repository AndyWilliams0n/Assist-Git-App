import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  GitFork,
  Lock,
  RefreshCw,
  Search,
  Star,
  Unlock,
} from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/components/ui/card"
import { Input } from "@/shared/components/ui/input"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import { Skeleton } from "@/shared/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/shared/components/ui/tabs"
import { Chip } from "@/shared/components/chip"
import { useGitHubSettings, useGitHubRepos } from "../hooks/useGitHubRepos"
import { useGitLabSettings, useGitLabRepos } from "../hooks/useGitLabRepos"
import type { GitHubRepo, GitLabRepo } from "../types"

type AnyRepo = GitHubRepo | GitLabRepo

function isGitHubRepo(repo: AnyRepo): repo is GitHubRepo {
  return "clone_url" in repo
}

function RepoListItem({ repo }: { repo: AnyRepo; platform?: "github" | "gitlab" }) {
  const name = repo.name
  const description = repo.description
  const language = repo.language
  const stars = isGitHubRepo(repo) ? repo.stars : repo.star_count
  const isPrivate = isGitHubRepo(repo) ? repo.is_private : repo.visibility !== "public"
  const url = isGitHubRepo(repo)
    ? `https://github.com/${repo.full_name}`
    : `${repo.http_url_to_repo}`

  return (
    <div className="flex items-start justify-between gap-3 px-3 py-2.5 rounded-md hover:bg-muted/50 transition-colors group">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-sm font-medium truncate">{name}</span>
          {isPrivate ? (
            <Lock className="size-3 text-muted-foreground shrink-0" />
          ) : (
            <Unlock className="size-3 text-muted-foreground shrink-0" />
          )}
        </div>
        {description && (
          <p className="text-xs text-muted-foreground line-clamp-1">{description}</p>
        )}
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {language && <span>{language}</span>}
          {stars > 0 && (
            <span className="flex items-center gap-1">
              <Star className="size-3" />
              {stars.toLocaleString()}
            </span>
          )}
        </div>
      </div>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:text-foreground"
        onClick={(e) => e.stopPropagation()}
      >
        <ExternalLink className="size-3.5" />
      </a>
    </div>
  )
}

function RepoList({
  repos,
  isLoading,
  error,
  hasMore,
  search,
  onSearch,
  onLoadMore,
  platform,
}: {
  repos: AnyRepo[]
  isLoading: boolean
  error: string | null
  hasMore: boolean
  search: string
  onSearch: (term: string) => void
  onLoadMore: () => void
  platform: "github" | "gitlab"
}) {
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
        <Input
          placeholder="Search repositories…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="pl-8 h-8 text-xs"
        />
      </div>

      {error ? (
        <div className="flex items-center gap-2 p-3 text-xs text-destructive bg-destructive/10 rounded-md">
          <AlertCircle className="size-3.5 shrink-0" />
          {error}
        </div>
      ) : isLoading && repos.length === 0 ? (
        <div className="space-y-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-md" />
          ))}
        </div>
      ) : repos.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-6">
          {search ? `No repositories matching "${search}"` : "No repositories found"}
        </p>
      ) : (
        <ScrollArea className="h-72">
          <div className="space-y-0.5">
            {repos.map((repo) => (
              <RepoListItem
                key={isGitHubRepo(repo) ? repo.id : `gl-${repo.id}`}
                repo={repo}
                platform={platform}
              />
            ))}
            {hasMore && (
              <div className="pt-2 flex justify-center">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs gap-1.5"
                  onClick={onLoadMore}
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <RefreshCw className="size-3.5 animate-spin" />
                  ) : (
                    <GitFork className="size-3.5" />
                  )}
                  {isLoading ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}

function ConnectionStatusBadge({
  isConnected,
  username,
  isLoading,
}: {
  isConnected: boolean
  username?: string
  isLoading: boolean
}) {
  if (isLoading) {
    return <Skeleton className="h-5 w-20 rounded-full" />
  }
  if (isConnected) {
    return (
      <Chip color="success" variant="outline" className="gap-1 text-xs font-normal">
        <CheckCircle2 className="size-3" />
        {username ? username : "Connected"}
      </Chip>
    )
  }
  return (
    <Chip color="grey" variant="outline" className="gap-1 text-xs font-normal">
      Not connected
    </Chip>
  )
}

export function ConnectedPlatformsSection() {
  const { settings: ghSettings, isLoading: ghSettingsLoading } = useGitHubSettings()
  const { settings: glSettings, isLoading: glSettingsLoading } = useGitLabSettings()

  const ghConnected = ghSettings?.has_token === true
  const glConnected = glSettings?.has_token === true

  const github = useGitHubRepos(ghConnected)
  const gitlab = useGitLabRepos(glConnected)

  // Default to whichever platform is connected; prefer github
  const defaultTab = glConnected && !ghConnected ? "gitlab" : "github"

  // Don't render if neither is connected and settings are loaded
  const settingsLoaded = !ghSettingsLoading && !glSettingsLoading
  if (settingsLoaded && !ghConnected && !glConnected) {
    return null
  }

  return (
    <Card className="!shadow-none">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Connected Repositories</CardTitle>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">GitHub</span>
              <ConnectionStatusBadge
                isConnected={ghConnected}
                username={ghSettings?.username || undefined}
                isLoading={ghSettingsLoading}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">GitLab</span>
              <ConnectionStatusBadge
                isConnected={glConnected}
                username={glSettings?.username || undefined}
                isLoading={glSettingsLoading}
              />
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue={defaultTab}>
          <TabsList className="mb-3">
            <TabsTrigger value="github" className="text-xs" disabled={!ghConnected && settingsLoaded}>
              GitHub
              {ghConnected && github.repos.length > 0 && (
                <span className="ml-1.5 text-[10px] bg-primary/15 text-primary rounded-full px-1.5 py-0.5">
                  {github.repos.length}{github.hasMore ? "+" : ""}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="gitlab" className="text-xs" disabled={!glConnected && settingsLoaded}>
              GitLab
              {glConnected && gitlab.repos.length > 0 && (
                <span className="ml-1.5 text-[10px] bg-primary/15 text-primary rounded-full px-1.5 py-0.5">
                  {gitlab.repos.length}{gitlab.hasMore ? "+" : ""}
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="github" className="mt-0">
            {ghConnected ? (
              <RepoList
                repos={github.repos}
                isLoading={github.isLoading}
                error={github.error}
                hasMore={github.hasMore}
                search={github.search}
                onSearch={github.handleSearch}
                onLoadMore={github.loadMore}
                platform="github"
              />
            ) : (
              <p className="text-xs text-muted-foreground py-4 text-center">
                Add a GitHub token in API Token Settings to browse repositories.
              </p>
            )}
          </TabsContent>

          <TabsContent value="gitlab" className="mt-0">
            {glConnected ? (
              <RepoList
                repos={gitlab.repos}
                isLoading={gitlab.isLoading}
                error={gitlab.error}
                hasMore={gitlab.hasMore}
                search={gitlab.search}
                onSearch={gitlab.handleSearch}
                onLoadMore={gitlab.loadMore}
                platform="gitlab"
              />
            ) : (
              <p className="text-xs text-muted-foreground py-4 text-center">
                Add a GitLab token in API Token Settings to browse repositories.
              </p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
