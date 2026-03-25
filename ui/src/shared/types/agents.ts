export interface AgentStatus {
  id: string
  name: string
  provider?: string | null
  model?: string | null
  group?: string
  role?: string
  kind?: "agent" | "subagent" | string
  enabled?: boolean
  dependencies?: string[]
  source?: string | null
  description?: string | null
  capabilities?: string[]
  is_active?: boolean
  in_flight?: number
  last_active_at?: string | null
  last_error?: string | null
  total_calls?: number
  health?: string | null
  uptime_seconds?: number
  status?: string
  bypassed?: boolean
}

export interface AgentsSnapshot {
  updated_at?: string
  app_uptime_seconds?: number
  app_uptime?: string
  bypass?: {
    jira_api_bypass?: boolean
    sdd_spec_bypass?: boolean
    code_builder_bypass?: boolean
    code_review_bypass?: boolean
  }
  agents: AgentStatus[]
}
