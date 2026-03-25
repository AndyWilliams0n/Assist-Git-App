export type ChatSender = "user" | "agent"

export type ChatRole = "user" | "assistant"

export type ChatWorkflowMode = "auto" | "jira" | "code_review" | "code" | "research" | "stitch_generation"

export interface SelectedTicketSummary {
  key: string
  title: string
  status?: string
  priority?: string
  assignee?: string
  updated?: string
}

export interface SelectedTicketDetails {
  ticket_key: string
  title: string
  status?: string
  priority?: string
  url?: string
  ticket?: Record<string, unknown>
  ticket_context?: Record<string, unknown>
}

export interface ChatAttachment {
  id: string
  messageEventId: string
  originalName: string
  mimeType: string
  sizeBytes: number
  createdAt: string
  url: string
}

export interface ChatMessage {
  id: string
  text: string
  sender: ChatSender
  summary: string
  attachments?: ChatAttachment[]
  agent?: string
  role?: ChatRole
  createdAt?: string
}

export interface OrchestratorEvent {
  id?: string
  conversation_id?: string
  task_id?: string | null
  agent?: string
  event_type: string
  content: string
  created_at?: string
}

export interface OrchestratorTask {
  id?: string
  conversation_id?: string
  title: string
  details: string
  owner_agent: string
  status: string
  created_at?: string
  updated_at?: string
}

export type ChatStreamItem =
  | { type: "message"; message: ChatMessage }
  | { type: "thinking"; events: OrchestratorEvent[] }
