import * as React from "react"
import type { WorkspaceProject } from "../types"
import { useWorkspaceStore } from "../store/workspace-store"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

export function useWorkspaceProjects(workspaceId: string | null) {
  const { projects, setProjects, addProject, updateProject, removeProject } = useWorkspaceStore()
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const currentProjects = workspaceId ? (projects[workspaceId] ?? []) : []

  const fetchProjects = React.useCallback(async () => {
    if (!workspaceId) return
    setIsLoading(true)
    setError(null)
    try {
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects`))
      if (!res.ok) throw new Error(`Failed to fetch projects: ${res.status}`)
      const data = await res.json()
      setProjects(workspaceId, data.projects ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setIsLoading(false)
    }
  }, [workspaceId, setProjects])

  React.useEffect(() => {
    fetchProjects()
  }, [fetchProjects])

  const addProjectToWorkspace = React.useCallback(
    async (body: {
      remote_url: string
      local_path: string
      platform: string
      name: string
      description?: string
      language?: string
      stars?: number
    }) => {
      if (!workspaceId) throw new Error("No workspace selected")
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`Failed to add project: ${res.status}`)
      const proj: WorkspaceProject = await res.json()
      addProject(workspaceId, proj)
      return proj
    },
    [workspaceId, addProject]
  )

  const removeProjectFromWorkspace = React.useCallback(
    async (projectId: string) => {
      if (!workspaceId) throw new Error("No workspace selected")
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects/${projectId}`), { method: "DELETE" })
      if (!res.ok) throw new Error(`Failed to remove project: ${res.status}`)
      removeProject(workspaceId, projectId)
    },
    [workspaceId, removeProject]
  )

  const cloneProject = React.useCallback(
    async (projectId: string, options?: { wipeExisting?: boolean }) => {
      if (!workspaceId) throw new Error("No workspace selected")
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects/${projectId}/clone`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wipe_existing: Boolean(options?.wipeExisting) }),
      })
      const data = await res.json()
      if (data.ok && data.project) {
        updateProject(workspaceId, projectId, data.project)
      }
      return data
    },
    [workspaceId, updateProject]
  )

  const getProjectBranches = React.useCallback(
    async (projectId: string) => {
      if (!workspaceId) throw new Error("No workspace selected")
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects/${projectId}/branches`))
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(data?.detail ?? `Failed to load branches: ${res.status}`)
      }
      return (await res.json()) as { current: string; local: string[]; remote: string[] }
    },
    [workspaceId]
  )

  const switchProjectBranch = React.useCallback(
    async (projectId: string, branch: string) => {
      if (!workspaceId) throw new Error("No workspace selected")
      const res = await fetch(buildApiUrl(`/api/workspaces/${workspaceId}/projects/${projectId}/branch`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ branch }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) throw new Error(data?.detail ?? `Failed to switch branch: ${res.status}`)
      if (data?.project) {
        updateProject(workspaceId, projectId, data.project)
      }
      return data as { ok: boolean; project?: WorkspaceProject }
    },
    [workspaceId, updateProject]
  )

  return {
    projects: currentProjects,
    isLoading,
    error,
    fetchProjects,
    addProjectToWorkspace,
    removeProjectFromWorkspace,
    cloneProject,
    getProjectBranches,
    switchProjectBranch,
  }
}
