import * as React from "react"
import type { Workspace } from "../types"
import { useWorkspaceStore } from "../store/workspace-store"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)
const API = buildApiUrl("/api/workspaces")

export function useWorkspaces() {
  const {
    workspaces,
    activeWorkspaceId,
    selectedWorkspaceId,
    setWorkspaces,
    setPrimaryWorkspaceId,
    setSecondaryWorkspaceId,
    setActiveWorkspaceId,
    setSelectedWorkspaceId,
    setLoading,
    setError,
    isLoading,
    error,
  } =
    useWorkspaceStore()
  const setWorkspacePath = useDashboardSettingsStore((s) => s.setPrimaryWorkspacePath)

  const fetchWorkspaces = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(API)
      if (!res.ok) throw new Error(`Failed to fetch workspaces: ${res.status}`)
      const data = await res.json()
      const ws: Workspace[] = data.workspaces ?? []
      const activeConfig = data.active_workspace_config as
        | { primary_workspace_id?: string | null; secondary_workspace_id?: string | null }
        | undefined
      const configuredPrimaryId = String(activeConfig?.primary_workspace_id || "").trim()
      const configuredSecondaryId = String(activeConfig?.secondary_workspace_id || "").trim()
      setWorkspaces(ws)
      const active =
        ws.find((workspace) => workspace.id === configuredPrimaryId) ??
        ws.find((w) => w.is_active === 1) ??
        null
      const currentSelectedWorkspaceId = useWorkspaceStore.getState().selectedWorkspaceId
      const selected =
        ws.find((w) => w.id === currentSelectedWorkspaceId) ??
        active ??
        null

      const resolvedPrimaryId = active?.id ?? selected?.id ?? null
      setPrimaryWorkspaceId(resolvedPrimaryId)
      setActiveWorkspaceId(resolvedPrimaryId)
      setSelectedWorkspaceId(selected?.id ?? null)
      if (configuredSecondaryId && ws.some((workspace) => workspace.id === configuredSecondaryId)) {
        setSecondaryWorkspaceId(configuredSecondaryId)
      } else {
        setSecondaryWorkspaceId(null)
      }
      const nextWorkspacePath =
        ws.find((workspace) => workspace.id === resolvedPrimaryId)?.path ??
        selected?.path ??
        ""
      setWorkspacePath(nextWorkspacePath)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [
    setActiveWorkspaceId,
    setPrimaryWorkspaceId,
    setSecondaryWorkspaceId,
    setError,
    setLoading,
    setSelectedWorkspaceId,
    setWorkspacePath,
    setWorkspaces,
  ])

  React.useEffect(() => {
    fetchWorkspaces()
  }, [fetchWorkspaces])

  const createWorkspace = React.useCallback(
    async (name: string, path: string, description = "") => {
      const res = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path, description }),
      })
      if (!res.ok) throw new Error(`Failed to create workspace: ${res.status}`)
      const ws: Workspace = await res.json()

      const activateRes = await fetch(`${API}/${ws.id}/activate`, { method: "PATCH" })
      if (!activateRes.ok) throw new Error(`Failed to activate workspace: ${activateRes.status}`)
      const activeWorkspace: Workspace = await activateRes.json()

      const nextWorkspaces = [...workspaces, activeWorkspace].map((workspace) => ({
        ...workspace,
        is_active: workspace.id === activeWorkspace.id ? 1 : 0,
      }))

      setWorkspaces(nextWorkspaces)
      setPrimaryWorkspaceId(activeWorkspace.id)
      setActiveWorkspaceId(activeWorkspace.id)
      setSelectedWorkspaceId(activeWorkspace.id)
      setWorkspacePath(activeWorkspace.path)
      return activeWorkspace
    },
    [
      setActiveWorkspaceId,
      setSelectedWorkspaceId,
      setWorkspacePath,
      setPrimaryWorkspaceId,
      workspaces,
      setWorkspaces,
    ]
  )

  const updateWorkspace = React.useCallback(
    async (id: string, updates: { name?: string; path?: string; description?: string }) => {
      const res = await fetch(`${API}/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      })
      if (!res.ok) throw new Error(`Failed to update workspace: ${res.status}`)
      const ws: Workspace = await res.json()
      setWorkspaces(workspaces.map((w) => (w.id === id ? ws : w)))
      return ws
    },
    [workspaces, setWorkspaces]
  )

  const deleteWorkspace = React.useCallback(
    async (id: string) => {
      const res = await fetch(`${API}/${id}`, { method: "DELETE" })
      if (!res.ok) throw new Error(`Failed to delete workspace: ${res.status}`)
      const deletedWorkspace = workspaces.find((workspace) => workspace.id === id) ?? null
      const nextWorkspaces = workspaces.filter((w) => w.id !== id)
      setWorkspaces(nextWorkspaces)

      if (deletedWorkspace?.is_active === 1 || activeWorkspaceId === id) {
        setPrimaryWorkspaceId(null)
        setSecondaryWorkspaceId(null)
        setActiveWorkspaceId(null)
        setSelectedWorkspaceId(null)
        setWorkspacePath("")
        return
      }

      if (selectedWorkspaceId === id) {
        const nextSelected = nextWorkspaces.find((workspace) => workspace.is_active === 1) ?? null
        setSelectedWorkspaceId(nextSelected?.id ?? null)

        const nextWorkspacePath = nextSelected?.path ?? ""
        setWorkspacePath(nextWorkspacePath)
      }
    },
    [
      activeWorkspaceId,
      selectedWorkspaceId,
      setActiveWorkspaceId,
      setPrimaryWorkspaceId,
      setSecondaryWorkspaceId,
      setSelectedWorkspaceId,
      setWorkspacePath,
      workspaces,
      setWorkspaces,
    ]
  )

  const activateWorkspace = React.useCallback(
    async (id: string) => {
      const res = await fetch(`${API}/${id}/activate`, { method: "PATCH" })
      if (!res.ok) throw new Error(`Failed to activate workspace: ${res.status}`)
      const ws: Workspace = await res.json()
      const updated = workspaces.map((w) => ({ ...w, is_active: w.id === id ? 1 : 0 }))
      setWorkspaces(updated)
      setPrimaryWorkspaceId(id)
      setActiveWorkspaceId(id)
      setSelectedWorkspaceId(id)
      setWorkspacePath(ws.path)
      return ws
    },
    [
      workspaces,
      setWorkspaces,
      setActiveWorkspaceId,
      setPrimaryWorkspaceId,
      setSelectedWorkspaceId,
      setWorkspacePath,
    ]
  )

  return { workspaces, isLoading, error, fetchWorkspaces, createWorkspace, updateWorkspace, deleteWorkspace, activateWorkspace }
}
