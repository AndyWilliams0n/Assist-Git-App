import * as React from "react"
import type { GitHubRepo, GitHubSettings } from "../types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

export function useGitHubSettings() {
  const [settings, setSettings] = React.useState<GitHubSettings | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)

  const fetchSettings = React.useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await fetch(buildApiUrl("/api/github/settings"))
      if (res.ok) setSettings(await res.json())
    } finally {
      setIsLoading(false)
    }
  }, [])

  React.useEffect(() => { fetchSettings() }, [fetchSettings])

  const saveSettings = React.useCallback(async (token?: string, username?: string) => {
    const res = await fetch(buildApiUrl("/api/github/settings"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, username }),
    })
    if (!res.ok) throw new Error("Failed to save GitHub settings")
    const updated: GitHubSettings = await res.json()
    setSettings(updated)
    return updated
  }, [])

  return { settings, isLoading, fetchSettings, saveSettings }
}

export function useGitHubRepos(enabled: boolean) {
  const [repos, setRepos] = React.useState<GitHubRepo[]>([])
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [page, setPage] = React.useState(1)
  const [hasMore, setHasMore] = React.useState(true)
  const [search, setSearch] = React.useState("")

  const fetchRepos = React.useCallback(
    async (nextPage: number, searchTerm: string, reset = false) => {
      if (!enabled) return
      setIsLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams({ page: String(nextPage), per_page: "30", search: searchTerm })
        const res = await fetch(buildApiUrl(`/api/github/repos?${params}`))
        if (!res.ok) {
          const errData = await res.json().catch(() => null)
          setError(errData?.detail ?? `Failed to load GitHub repos: ${res.status}`)
          return
        }
        const data = await res.json()
        if (!data.success && data.error) {
          setError(data.error)
          return
        }
        const fetched: GitHubRepo[] = data.repos ?? []
        setRepos(reset ? fetched : (prev) => [...prev, ...fetched])
        setHasMore(fetched.length === 30)
        setPage(nextPage)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error")
      } finally {
        setIsLoading(false)
      }
    },
    [enabled]
  )

  React.useEffect(() => {
    if (enabled) fetchRepos(1, "", true)
  }, [enabled, fetchRepos])

  const handleSearch = React.useCallback(
    (term: string) => {
      setSearch(term)
      fetchRepos(1, term, true)
    },
    [fetchRepos]
  )

  const loadMore = React.useCallback(() => {
    if (!isLoading && hasMore) fetchRepos(page + 1, search, false)
  }, [isLoading, hasMore, page, search, fetchRepos])

  return { repos, isLoading, error, hasMore, search, handleSearch, loadMore, refetch: () => fetchRepos(1, search, true) }
}
