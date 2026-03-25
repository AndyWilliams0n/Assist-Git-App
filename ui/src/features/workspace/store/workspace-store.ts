import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { Workspace, WorkspaceProject } from "../types"

export type WorkspaceTabValue = "workspace" | "repository" | "all-repositories"

interface WorkspaceStore {
  workspaces: Workspace[]
  primaryWorkspaceId: string | null
  secondaryWorkspaceId: string | null
  activeWorkspaceId: string | null
  selectedWorkspaceId: string | null
  activeTab: WorkspaceTabValue
  projects: Record<string, WorkspaceProject[]>
  isLoading: boolean
  error: string | null

  setWorkspaces: (workspaces: Workspace[]) => void
  setPrimaryWorkspaceId: (id: string | null) => void
  setSecondaryWorkspaceId: (id: string | null) => void
  setActiveWorkspaceId: (id: string | null) => void
  setSelectedWorkspaceId: (id: string | null) => void
  setActiveTab: (activeTab: WorkspaceTabValue) => void
  setProjects: (workspaceId: string, projects: WorkspaceProject[]) => void
  addProject: (workspaceId: string, project: WorkspaceProject) => void
  updateProject: (workspaceId: string, projectId: string, updates: Partial<WorkspaceProject>) => void
  removeProject: (workspaceId: string, projectId: string) => void
  setLoading: (isLoading: boolean) => void
  setError: (error: string | null) => void
}

export const useWorkspaceStore = create<WorkspaceStore>()(
  persist(
    (set) => ({
      workspaces: [],
      primaryWorkspaceId: null,
      secondaryWorkspaceId: null,
      activeWorkspaceId: null,
      selectedWorkspaceId: null,
      activeTab: "workspace",
      projects: {},
      isLoading: false,
      error: null,

      setWorkspaces: (workspaces) => set({ workspaces }),

      setPrimaryWorkspaceId: (id) => set({ primaryWorkspaceId: id, activeWorkspaceId: id }),

      setSecondaryWorkspaceId: (id) => set({ secondaryWorkspaceId: id }),

      setActiveWorkspaceId: (id) => set({ activeWorkspaceId: id }),

      setSelectedWorkspaceId: (id) => set({ selectedWorkspaceId: id }),

      setActiveTab: (activeTab) => set({ activeTab }),

      setProjects: (workspaceId, projects) =>
        set((state) => ({ projects: { ...state.projects, [workspaceId]: projects } })),

      addProject: (workspaceId, project) =>
        set((state) => ({
          projects: {
            ...state.projects,
            [workspaceId]: [...(state.projects[workspaceId] ?? []), project],
          },
        })),

      updateProject: (workspaceId, projectId, updates) =>
        set((state) => ({
          projects: {
            ...state.projects,
            [workspaceId]: (state.projects[workspaceId] ?? []).map((p) =>
              p.id === projectId ? { ...p, ...updates } : p
            ),
          },
        })),

      removeProject: (workspaceId, projectId) =>
        set((state) => ({
          projects: {
            ...state.projects,
            [workspaceId]: (state.projects[workspaceId] ?? []).filter((p) => p.id !== projectId),
          },
        })),

      setLoading: (isLoading) => set({ isLoading }),

      setError: (error) => set({ error }),
    }),
    {
      name: "workspace-storage",
      partialize: (state) => ({
        primaryWorkspaceId: state.primaryWorkspaceId,
        secondaryWorkspaceId: state.secondaryWorkspaceId,
        activeWorkspaceId: state.activeWorkspaceId,
        selectedWorkspaceId: state.selectedWorkspaceId,
        activeTab: state.activeTab,
      }),
    }
  )
)
