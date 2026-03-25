import { create } from "zustand"
import { persist } from "zustand/middleware"

import type {
  JiraUser,
  WorkflowCurrentSprint,
  WorkflowKanbanColumn,
  WorkflowTask,
  WorkflowTasksFetchSnapshotPayload,
} from "@/features/workflow-tasks/types"

type WorkflowTasksStoreState = {
  projectKey: string
  boardNumber: string
  assigneeFilter: string
  jiraUsers: JiraUser[]
  activeTab: "project" | "tasks" | "epics" | "specs"
  tickets: WorkflowTask[]
  currentSprint: WorkflowCurrentSprint | null
  kanbanColumns: WorkflowKanbanColumn[]
  server: string
  tool: string
  fetchedAt: string
  savedAt: string
  dbId: string
  warning: string
  setProjectKey: (projectKey: string) => void
  setBoardNumber: (boardNumber: string) => void
  setAssigneeFilter: (assigneeFilter: string) => void
  setJiraUsers: (jiraUsers: JiraUser[]) => void
  setActiveTab: (activeTab: "project" | "tasks" | "epics" | "specs") => void
  setFetchSnapshot: (payload: WorkflowTasksFetchSnapshotPayload) => void
  setFromConfig: (projectKey: string, boardNumber: string, assigneeFilter: string, jiraUsers: JiraUser[]) => void
  setWarning: (warning: string) => void
  clearFetchSnapshot: () => void
}

export const useWorkflowTasksStore = create<WorkflowTasksStoreState>()(
  persist(
    (set) => ({
      projectKey: "",
      boardNumber: "",
      assigneeFilter: "",
      jiraUsers: [],
      activeTab: "project",
      tickets: [],
      currentSprint: null,
      kanbanColumns: [],
      server: "",
      tool: "",
      fetchedAt: "",
      savedAt: "",
      dbId: "",
      warning: "",
      setProjectKey: (projectKey) => set({ projectKey }),
      setBoardNumber: (boardNumber) => set({ boardNumber }),
      setAssigneeFilter: (assigneeFilter) => set({ assigneeFilter }),
      setJiraUsers: (jiraUsers) => set({ jiraUsers }),
      setActiveTab: (activeTab) => set({ activeTab }),
      setFetchSnapshot: (payload) =>
        set({
          tickets: payload.tickets || [],
          currentSprint: payload.current_sprint || null,
          kanbanColumns: payload.kanban_columns || [],
          server: payload.server || "",
          tool: payload.tool || "",
          fetchedAt: payload.fetched_at || "",
          savedAt: payload.saved_at || "",
          dbId: payload.db_id || "",
          warning: (payload.warnings || []).join(" "),
        }),
      setFromConfig: (projectKey, boardNumber, assigneeFilter, jiraUsers) =>
        set((state) => ({
          projectKey: state.projectKey || projectKey || "",
          boardNumber: state.boardNumber || boardNumber || "",
          assigneeFilter: state.assigneeFilter || assigneeFilter || "",
          jiraUsers: state.jiraUsers.length > 0 ? state.jiraUsers : (jiraUsers || []),
        })),
      setWarning: (warning) => set({ warning }),
      clearFetchSnapshot: () =>
        set({
          tickets: [],
          currentSprint: null,
          kanbanColumns: [],
          server: "",
          tool: "",
          fetchedAt: "",
          savedAt: "",
          dbId: "",
          warning: "",
        }),
    }),
    {
      name: "workflow-tasks-storage",
      partialize: (state) => ({
        projectKey: state.projectKey,
        boardNumber: state.boardNumber,
        assigneeFilter: state.assigneeFilter,
        jiraUsers: state.jiraUsers,
        activeTab: state.activeTab,
        tickets: state.tickets,
        currentSprint: state.currentSprint,
        kanbanColumns: state.kanbanColumns,
        server: state.server,
        tool: state.tool,
        fetchedAt: state.fetchedAt,
        savedAt: state.savedAt,
        dbId: state.dbId,
        warning: state.warning,
      }),
    }
  )
)
