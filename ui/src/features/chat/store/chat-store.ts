import { create } from "zustand"
import { persist } from "zustand/middleware"

import type {
  ChatMessage,
  OrchestratorEvent,
  OrchestratorTask,
  ChatWorkflowMode,
  SelectedTicketDetails,
} from "@/features/chat/types"

type ChatState = {
  messages: ChatMessage[]
  conversationId: string | null
  eventCursor: string | null
  orchestratorEvents: OrchestratorEvent[]
  orchestratorTasks: OrchestratorTask[]
  workspaceRoot: string
  secondaryWorkspaceRoot: string | null
  workflowMode: ChatWorkflowMode
  workflowModesByConversation: Record<string, ChatWorkflowMode>
  selectedTicketKeys: string[]
  ticketDetailsByKey: Record<string, SelectedTicketDetails>
  selectedTicketsByConversation: Record<string, string[]>
  ticketDetailsByConversation: Record<string, Record<string, SelectedTicketDetails>>
  secondaryWorkspacesByConversation: Record<string, string | null>
  suppressUrlSync: boolean
  addMessage: (message: ChatMessage) => void
  setMessages: (messages: ChatMessage[]) => void
  updateMessage: (messageId: string, updates: Partial<ChatMessage>) => void
  setConversationId: (conversationId: string | null) => void
  setEventCursor: (eventCursor: string | null) => void
  setOrchestratorEvents: (events: OrchestratorEvent[]) => void
  addOrchestratorEvent: (event: OrchestratorEvent) => void
  setOrchestratorTasks: (tasks: OrchestratorTask[]) => void
  setWorkspaceRoot: (workspaceRoot: string) => void
  setSecondaryWorkspaceRoot: (secondaryWorkspaceRoot: string | null) => void
  setWorkflowMode: (workflowMode: ChatWorkflowMode) => void
  rememberWorkflowMode: (conversationId: string, workflowMode: ChatWorkflowMode) => void
  restoreWorkflowMode: (conversationId: string | null) => void
  addTicket: (ticketKey: string) => void
  removeTicket: (ticketKey: string) => void
  clearTickets: () => void
  setTicketDetails: (details: SelectedTicketDetails) => void
  rememberTickets: (conversationId: string) => void
  restoreTickets: (conversationId: string | null) => void
  rememberSecondaryWorkspace: (conversationId: string) => void
  restoreSecondaryWorkspace: (conversationId: string | null) => void
  setSuppressUrlSync: (suppressUrlSync: boolean) => void
  clearChat: () => void
  resetConversationState: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      conversationId: null,
      eventCursor: null,
      orchestratorEvents: [],
      orchestratorTasks: [],
      workspaceRoot: "",
      secondaryWorkspaceRoot: null,
      workflowMode: "code_review",
      workflowModesByConversation: {},
      selectedTicketKeys: [],
      ticketDetailsByKey: {},
      selectedTicketsByConversation: {},
      ticketDetailsByConversation: {},
      secondaryWorkspacesByConversation: {},
      suppressUrlSync: false,
      addMessage: (message) =>
        set((state) => ({ messages: [...state.messages, message] })),
      setMessages: (messages) => set({ messages }),
      updateMessage: (messageId, updates) =>
        set((state) => ({
          messages: state.messages.map((message) =>
            message.id === messageId ? { ...message, ...updates } : message
          ),
        })),
      setConversationId: (conversationId) => set({ conversationId }),
      setEventCursor: (eventCursor) => set({ eventCursor }),
      setOrchestratorEvents: (events) => set({ orchestratorEvents: events }),
      addOrchestratorEvent: (event) =>
        set((state) => ({
          orchestratorEvents: [...state.orchestratorEvents, event],
        })),
      setOrchestratorTasks: (tasks) => set({ orchestratorTasks: tasks }),
      setWorkspaceRoot: (workspaceRoot) => set({ workspaceRoot }),
      setSecondaryWorkspaceRoot: (secondaryWorkspaceRoot) =>
        set({ secondaryWorkspaceRoot: secondaryWorkspaceRoot?.trim() ? secondaryWorkspaceRoot : null }),
      setWorkflowMode: (workflowMode) => set({ workflowMode }),
      rememberWorkflowMode: (conversationId, workflowMode) =>
        set((state) => ({
          workflowMode,
          workflowModesByConversation: {
            ...state.workflowModesByConversation,
            [conversationId]: workflowMode,
          },
        })),
      restoreWorkflowMode: (conversationId) =>
        set((state) => ({
          workflowMode: conversationId
            ? state.workflowModesByConversation[conversationId] || "code_review"
            : "code_review",
        })),
      addTicket: (ticketKey) =>
        set((state) => {
          const normalized = ticketKey.trim().toUpperCase()
          if (!normalized || state.selectedTicketKeys.includes(normalized)) {
            return state
          }
          return { selectedTicketKeys: [...state.selectedTicketKeys, normalized] }
        }),
      removeTicket: (ticketKey) =>
        set((state) => {
          const normalized = ticketKey.trim().toUpperCase()
          if (!normalized) {
            return state
          }
          const nextSelected = state.selectedTicketKeys.filter((item) => item !== normalized)
          const nextDetails = { ...state.ticketDetailsByKey }
          delete nextDetails[normalized]
          return {
            selectedTicketKeys: nextSelected,
            ticketDetailsByKey: nextDetails,
          }
        }),
      clearTickets: () => set({ selectedTicketKeys: [], ticketDetailsByKey: {} }),
      setTicketDetails: (details) =>
        set((state) => {
          const key = details.ticket_key.trim().toUpperCase()
          if (!key) {
            return state
          }
          return {
            ticketDetailsByKey: {
              ...state.ticketDetailsByKey,
              [key]: { ...details, ticket_key: key },
            },
          }
        }),
      rememberTickets: (conversationId) =>
        set((state) => {
          const key = conversationId.trim()
          if (!key) {
            return state
          }
          return {
            selectedTicketsByConversation: {
              ...state.selectedTicketsByConversation,
              [key]: [...state.selectedTicketKeys],
            },
            ticketDetailsByConversation: {
              ...state.ticketDetailsByConversation,
              [key]: { ...state.ticketDetailsByKey },
            },
          }
        }),
      restoreTickets: (conversationId) =>
        set((state) => {
          const key = (conversationId || "").trim()
          if (!key) {
            return {
              selectedTicketKeys: [],
              ticketDetailsByKey: {},
            }
          }
          return {
            selectedTicketKeys: [...(state.selectedTicketsByConversation[key] || [])],
            ticketDetailsByKey: { ...(state.ticketDetailsByConversation[key] || {}) },
          }
        }),
      rememberSecondaryWorkspace: (conversationId) =>
        set((state) => {
          const key = conversationId.trim()
          if (!key) {
            return state
          }
          return {
            secondaryWorkspacesByConversation: {
              ...state.secondaryWorkspacesByConversation,
              [key]: state.secondaryWorkspaceRoot,
            },
          }
        }),
      restoreSecondaryWorkspace: (conversationId) =>
        set((state) => {
          const key = (conversationId || "").trim()
          if (!key) {
            return {
              secondaryWorkspaceRoot: null,
            }
          }
          return {
            secondaryWorkspaceRoot: state.secondaryWorkspacesByConversation[key] ?? null,
          }
        }),
      setSuppressUrlSync: (suppressUrlSync) => set({ suppressUrlSync }),
      clearChat: () =>
        set({
          messages: [],
          conversationId: null,
          eventCursor: null,
          orchestratorEvents: [],
          orchestratorTasks: [],
          workflowMode: "code_review",
          secondaryWorkspaceRoot: null,
          selectedTicketKeys: [],
          ticketDetailsByKey: {},
          suppressUrlSync: true,
        }),
      resetConversationState: () =>
        set({
          messages: [],
          conversationId: null,
          eventCursor: null,
          orchestratorEvents: [],
          orchestratorTasks: [],
          workflowMode: "code_review",
          secondaryWorkspaceRoot: null,
          selectedTicketKeys: [],
          ticketDetailsByKey: {},
          suppressUrlSync: false,
        }),
    }),
    { name: "chat-v2-storage" }
  )
)
