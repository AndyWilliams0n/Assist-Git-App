import * as React from "react"
import { GitBranch, Lock, Search, Star, Unlock } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Input } from "@/shared/components/ui/input"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import { Skeleton } from "@/shared/components/ui/skeleton"
import type { GitHubRepo, GitLabRepo } from "../types"

type AnyRepo = GitHubRepo | GitLabRepo

function getRepoName(repo: AnyRepo): string {
  return "full_name" in repo ? repo.full_name : repo.path_with_namespace
}

function getRepoCloneUrl(repo: AnyRepo): string {
  return "clone_url" in repo ? repo.clone_url : repo.http_url_to_repo
}

function getRepoStars(repo: AnyRepo): number {
  return "stars" in repo ? repo.stars : repo.star_count
}

function isPrivate(repo: AnyRepo): boolean {
  return "is_private" in repo ? repo.is_private : repo.visibility === "private"
}

interface RepoSelectorProps {
  repos: AnyRepo[]
  isLoading: boolean
  error: string | null
  hasMore: boolean
  search: string
  onSearch: (term: string) => void
  onLoadMore: () => void
  selectedRepo: AnyRepo | null
  onSelect: (repo: AnyRepo) => void
}

export function RepoSelector({
  repos,
  isLoading,
  error,
  hasMore,
  search,
  onSearch,
  onLoadMore,
  selectedRepo,
  onSelect,
}: RepoSelectorProps) {
  const [searchInput, setSearchInput] = React.useState(search)
  const [visibilityFilter, setVisibilityFilter] = React.useState<"all" | "public" | "private">("all")
  const debounceRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleSearchChange = (value: string) => {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onSearch(value), 400)
  }

  React.useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current) }, [])

  const filteredRepos = React.useMemo(
    () =>
      repos.filter((repo) => {
        if (visibilityFilter === "all") return true
        const repoPrivate = isPrivate(repo)
        return visibilityFilter === "private" ? repoPrivate : !repoPrivate
      }),
    [repos, visibilityFilter]
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-1">
        <Button
          type="button"
          size="sm"
          variant={visibilityFilter === "all" ? "secondary" : "outline"}
          className="h-7 text-xs"
          onClick={() => setVisibilityFilter("all")}
        >
          All
        </Button>
        <Button
          type="button"
          size="sm"
          variant={visibilityFilter === "public" ? "secondary" : "outline"}
          className="h-7 text-xs"
          onClick={() => setVisibilityFilter("public")}
        >
          Public
        </Button>
        <Button
          type="button"
          size="sm"
          variant={visibilityFilter === "private" ? "secondary" : "outline"}
          className="h-7 text-xs"
          onClick={() => setVisibilityFilter("private")}
        >
          Private
        </Button>
      </div>

      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
        <Input
          placeholder="Search repositories..."
          className="pl-8 h-8 text-sm"
          value={searchInput}
          onChange={(e) => handleSearchChange(e.target.value)}
        />
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 text-destructive text-xs p-3">{error}</div>
      )}

      <ScrollArea className="h-64 rounded-md border">
        <div className="p-2 space-y-1">
          {isLoading && repos.length === 0
            ? Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 rounded-md" />
              ))
            : filteredRepos.map((repo) => {
                const name = getRepoName(repo)
                const cloneUrl = getRepoCloneUrl(repo)
                const stars = getRepoStars(repo)
                const priv = isPrivate(repo)
                const isSelected = selectedRepo !== null && getRepoCloneUrl(selectedRepo) === cloneUrl

                return (
                  <button
                    key={repo.id}
                    type="button"
                    className={`w-full flex items-start gap-2 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted ${
                      isSelected ? "bg-primary/10 ring-1 ring-primary" : ""
                    }`}
                    onClick={() => onSelect(repo)}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 text-xs font-medium truncate">
                        {priv ? (
                          <Lock className="size-3 shrink-0 text-muted-foreground" />
                        ) : (
                          <Unlock className="size-3 shrink-0 text-muted-foreground" />
                        )}
                        {name}
                      </div>
                      {repo.description && (
                        <p className="text-xs text-muted-foreground truncate mt-0.5">{repo.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                        {repo.language && <span>{repo.language}</span>}
                        {stars > 0 && (
                          <span className="flex items-center gap-0.5">
                            <Star className="size-2.5" />
                            {stars.toLocaleString()}
                          </span>
                        )}
                        <span className="flex items-center gap-0.5">
                          <GitBranch className="size-2.5" />
                          {repo.default_branch}
                        </span>
                      </div>
                    </div>
                  </button>
                )
              })}

          {!isLoading && filteredRepos.length === 0 && !error && (
            <div className="text-center text-xs text-muted-foreground py-8">No repositories found</div>
          )}

          {hasMore && !isLoading && repos.length > 0 && (
            <Button variant="ghost" size="sm" className="w-full text-xs" onClick={onLoadMore}>
              Load more
            </Button>
          )}

          {isLoading && repos.length > 0 && (
            <div className="text-center text-xs text-muted-foreground py-2">Loading...</div>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
