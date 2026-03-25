import { create } from "zustand"
import { persist } from "zustand/middleware"

export type DashboardBreadcrumb = {
  label: string
  href?: string
}

type ThemeMode = "light" | "dark"

type DashboardSettingsState = {
  breadcrumbs: DashboardBreadcrumb[]
  theme: ThemeMode
  primaryWorkspacePath: string
  secondaryWorkspacePath: string | null
  setPrimaryWorkspacePath: (workspacePath: string) => void
  setSecondaryWorkspacePath: (workspacePath: string | null) => void
  // Backward compatibility alias for primary workspace path.
  workspacePath: string
  setWorkspacePath: (workspacePath: string) => void
  workspacePickerRequestId: number
  setBreadcrumbs: (breadcrumbs: DashboardBreadcrumb[]) => void
  setTheme: (theme: ThemeMode) => void
  requestWorkspacePicker: () => void
  consumeWorkspacePickerRequest: (requestId: number) => void
  toggleTheme: () => void
  resetBreadcrumbs: () => void
}

const defaultBreadcrumbs: DashboardBreadcrumb[] = [
  { label: "Dashboard", href: "/" },
]

export const useDashboardSettingsStore = create<DashboardSettingsState>()(
  persist(
    (set) => ({
      breadcrumbs: defaultBreadcrumbs,
      theme: "light",
      primaryWorkspacePath: "",
      secondaryWorkspacePath: null,
      workspacePath: "",
      workspacePickerRequestId: 0,
      setBreadcrumbs: (breadcrumbs) => set({ breadcrumbs }),
      setTheme: (theme) => set({ theme }),
      setPrimaryWorkspacePath: (workspacePath) =>
        set({
          primaryWorkspacePath: workspacePath,
          workspacePath,
        }),
      setSecondaryWorkspacePath: (workspacePath) =>
        set({
          secondaryWorkspacePath: workspacePath?.trim() ? workspacePath : null,
        }),
      setWorkspacePath: (workspacePath) =>
        set({
          primaryWorkspacePath: workspacePath,
          workspacePath,
        }),
      requestWorkspacePicker: () =>
        set((state) => ({ workspacePickerRequestId: state.workspacePickerRequestId + 1 })),
      consumeWorkspacePickerRequest: (requestId) =>
        set((state) =>
          state.workspacePickerRequestId === requestId ? { workspacePickerRequestId: 0 } : state
        ),
      toggleTheme: () =>
        set((state) => ({
          theme: state.theme === "dark" ? "light" : "dark",
        })),
      resetBreadcrumbs: () => set({ breadcrumbs: defaultBreadcrumbs }),
    }),
    {
      name: "dashboard-settings",
      merge: (persistedState, currentState) => {
        const persisted = (persistedState || {}) as Partial<DashboardSettingsState>
        const fallbackPrimaryPath = String(persisted.primaryWorkspacePath || persisted.workspacePath || "")
        return {
          ...currentState,
          ...persisted,
          primaryWorkspacePath: fallbackPrimaryPath,
          workspacePath: fallbackPrimaryPath,
          secondaryWorkspacePath: persisted.secondaryWorkspacePath ?? null,
        }
      },
      partialize: (state) => ({
        breadcrumbs: state.breadcrumbs,
        theme: state.theme,
        primaryWorkspacePath: state.primaryWorkspacePath,
        secondaryWorkspacePath: state.secondaryWorkspacePath,
        workspacePath: state.workspacePath,
      }),
    }
  )
)
