export type PipelineTaskStatus = "current" | "running" | "complete"
export type PipelineWorkflow = "codex"
export type PipelineTaskSource = "jira" | "spec"

export type PipelineBacklogItem = {
  key: string
  task_source: PipelineTaskSource
  task_reference: string
  title: string
  issue_type: string
  status: string
  priority: string
  assignee: string
  updated: string
  fetched_at: string
  payload: Record<string, unknown>
}

export type PipelineLog = {
  id: string
  task_id: string
  run_id: string
  jira_key: string
  level: string
  message: string
  created_at: string
}

export type PipelineRun = {
  id: string
  task_id: string
  jira_key: string
  task_source: PipelineTaskSource
  version: number
  status: string
  workspace_path: string
  workflow: PipelineWorkflow
  attempt_count?: number
  max_retries?: number
  attempts_failed?: number
  attempts_completed?: number
  current_activity?: string
  brief_path: string
  spec_path: string
  task_path: string
  codex_status: string
  codex_summary: string
  failure_reason: string
  started_at: string
  ended_at: string
  created_at: string
  updated_at: string
}

export type PipelineTaskDependency = {
  id: string
  task_id: string
  depends_on_task_id: string
  dependency_type: string
  created_at: string
  updated_at: string
}

export type PipelineGitHandoff = {
  id: string
  task_id: string
  run_id: string
  jira_key: string
  strategy: string
  stash_ref: string
  commit_sha: string
  source_branch: string
  target_branch: string
  file_summary_json: string
  file_summary?: unknown
  reason: string
  resolved: number
  resolved_at: string
  resolved_by: string
  resolution_note: string
  created_at: string
  updated_at: string
  task_status?: string
  task_is_bypassed?: boolean
}

export type PipelineTask = {
  id: string
  jira_key: string
  task_source: PipelineTaskSource
  task_relation: "task" | "subtask"
  title: string
  workspace_path: string
  jira_complete_column_name: string
  starting_git_branch_override: string
  workflow: PipelineWorkflow
  status: PipelineTaskStatus
  order_index: number
  version: number
  failure_reason: string
  is_bypassed: number
  bypass_reason: string
  bypass_source: string
  bypassed_at: string
  bypassed_by: string
  is_dependency_blocked: number
  dependency_block_reason: string
  execution_state: "ready" | "blocked" | "attention_required"
  last_failure_code: string
  jira_payload_json: string
  jira_payload: Record<string, unknown>
  active_run_id: string
  created_at: string
  updated_at: string
  runs: PipelineRun[]
  logs: PipelineLog[]
  dependencies: PipelineTaskDependency[]
  dependent_task_ids: string[]
  unresolved_handoffs: PipelineGitHandoff[]
  unresolved_handoff_count: number
}

export type PipelineColumns = {
  current: PipelineTask[]
  running: PipelineTask[]
  complete: PipelineTask[]
}

export type PipelineSettings = {
  active_window_start: string
  active_window_end: string
  heartbeat_interval_minutes: number
  automation_enabled?: boolean
  max_retries?: number
  review_failure_mode?: "strict" | "skip_acceptance" | "skip_all"
  last_heartbeat_at: string
  last_cycle_at: string
}

export type PipelineHeartbeat = {
  active_window_start: string
  active_window_end: string
  heartbeat_interval_minutes: number
  active_window_state: "active" | "inactive"
  is_active: boolean
  next_heartbeat_at: string
  countdown_seconds: number
  last_heartbeat_at: string
  last_cycle_at: string
}

export type PipelineState = {
  updated_at: string
  settings: PipelineSettings
  heartbeat: PipelineHeartbeat
  columns: PipelineColumns
  backlog: PipelineBacklogItem[]
  handoffs?: {
    unresolved_count: number
    unresolved: PipelineGitHandoff[]
  }
}

export type PipelineRefreshBacklogResponse = {
  count: number
  fetched_at: string
  tickets: Array<Record<string, unknown>>
}

export type PipelineQueueResponse = {
  task: PipelineTask
}

export type PipelineMoveResponse = {
  task: PipelineTask
}

export type PipelineSettingsResponse = {
  settings: PipelineSettings
}

export type PipelineTaskDependenciesResponse = {
  task_id: string
  dependencies: PipelineTaskDependency[]
}

export type PipelineTaskHandoffsResponse = {
  task_id: string
  handoffs: PipelineGitHandoff[]
}

export type PipelineHeartbeatTriggerResponse = {
  scheduled: boolean
  delay_seconds: number
  next_heartbeat_override_at: string
}

export type PipelineNextTaskTriggerResponse = {
  queued: boolean
}
