export type WorkflowTaskAttachment = {
  filename?: string
  url?: string
}

export type WorkflowTaskComment = {
  id?: string
  author?: string
  body?: string
  created?: string
  updated?: string
}

export type WorkflowTaskHistoryChange = {
  field?: string
  from?: string
  to?: string
}

export type WorkflowTaskHistoryEntry = {
  id?: string
  author?: string
  created?: string
  changes?: WorkflowTaskHistoryChange[]
}

export type WorkflowTask = {
  key: string
  summary?: string
  description?: string
  status?: string
  status_id?: string
  assignee?: string
  reporter?: string
  priority?: string
  updated?: string
  due_date?: string
  start_date?: string
  labels?: string[]
  sprints?: string[]
  story_points?: string
  team?: string
  development?: string
  issue_type?: string
  parent_key?: string
  is_subtask?: boolean
  attachments_count?: number
  attachments?: WorkflowTaskAttachment[]
  comments?: WorkflowTaskComment[]
  history?: WorkflowTaskHistoryEntry[]
  url?: string
}

export type WorkflowSprintStatusCount = {
  name: string
  ticket_count: number
}

export type WorkflowCurrentSprint = {
  id?: string
  name?: string
  state?: string
  goal?: string
  start_date?: string
  end_date?: string
  complete_date?: string
  board_id?: string
  ticket_count?: number
  tickets?: WorkflowTask[]
  counts_by_status?: WorkflowSprintStatusCount[]
}

export type WorkflowKanbanColumn = {
  name: string
  ticket_count: number
  source?: string
  share_of_total?: number
  relative_width?: number
  statuses?: { id?: string; name?: string }[]
  status_count?: number
  configured_index?: number
  min?: number | null
  max?: number | null
}

export type JiraUser = {
  accountId: string
  displayName: string
  emailAddress?: string
}

export type WorkflowTasksConfigResponse = {
  workspace_root: string
  server: string
  jira_base_url: string
  backlog_url: string
  project_key: string
  board_id: string
  max_results: string
  configured: boolean
  assignee_filter: string
  jira_users: JiraUser[]
}

export type WorkflowTasksFetchResponse = {
  server: string
  tool: string
  backlog_url: string
  fetched_at: string
  db_id?: string
  saved_at?: string
  ticket_count: number
  tickets: WorkflowTask[]
  current_sprint?: WorkflowCurrentSprint | null
  kanban_columns?: WorkflowKanbanColumn[]
  warnings?: string[]
  raw_result_json?: string
  raw_result_path?: string
}

export type WorkflowTasksFetchHistoryItem = {
  id: string
  created_at: string
  backlog_url: string
  server: string
  tool: string
  ticket_count: number
  tickets: WorkflowTask[]
  current_sprint?: WorkflowCurrentSprint | null
  kanban_columns?: WorkflowKanbanColumn[]
  warnings?: string[]
  raw_result_json?: string
  raw_result_path?: string
}

export type WorkflowTasksFetchSnapshotPayload = {
  tickets?: WorkflowTask[]
  server?: string
  tool?: string
  fetched_at?: string
  saved_at?: string
  db_id?: string
  current_sprint?: WorkflowCurrentSprint | null
  kanban_columns?: WorkflowKanbanColumn[]
  warnings?: string[]
}

export type SpecTaskStatus = 'generating' | 'generated' | 'pending' | 'complete' | 'failed'

export type WorkflowSpecTask = {
  id: string
  spec_name: string
  workspace_path: string
  spec_path: string
  requirements_path: string
  design_path: string
  tasks_path: string
  summary: string
  status: SpecTaskStatus
  parent_spec_name?: string
  parent_spec_task_id?: string
  dependency_mode?: 'independent' | 'parent' | 'subtask'
  depends_on?: string[]
  created_at: string
  updated_at: string
}

export type WorkflowSpecTasksResponse = {
  spec_tasks: WorkflowSpecTask[]
}
