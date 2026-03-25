export interface ConversationSummary {
  id: string
  created_at: string
  updated_at: string
  last_message: string | null
  last_role: string | null
  last_message_at: string | null
  message_count: number
}

export interface ConversationListResponse {
  conversations?: ConversationSummary[]
}
