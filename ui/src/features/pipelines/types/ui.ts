import type { PipelineTaskSource, PipelineTaskStatus, PipelineWorkflow } from "@/features/pipelines/types/pipeline"

export type PipelineSyncMode = "streaming" | "polling"
export type HeartbeatUnit = "minutes" | "hours"

export type FsEntry = {
  name: string
  path: string
  type: "dir" | "file"
  size?: number
  modified_at?: string
}

export type FsBrowseResponse = {
  path: string
  parent: string | null
  home: string
  entries: FsEntry[]
}

export type DragPayload =
  | { source: "backlog"; jiraKey: string }
  | { source: "task"; taskId: string; fromStatus: PipelineTaskStatus }

export type PipelineDependencyOption = {
  key: string
  label: string
  source: "spec" | "ticket"
}

export type PipelineTaskRelationType = "task" | "subtask"

export type PipelineWorkspaceAction =
  | {
      kind: "queue"
      jiraKey: string
      taskSource?: PipelineTaskSource
      workspacePath: string
      workflow: PipelineWorkflow
      jiraCompleteColumnName?: string
      startingGitBranchOverride?: string
      defaultTaskType?: PipelineTaskRelationType
      defaultDependencyKey?: string
    }
  | {
      kind: "move"
      taskId: string
      jiraKey: string
      taskSource?: PipelineTaskSource
      workspacePath: string
      workflow: PipelineWorkflow
      jiraCompleteColumnName?: string
      startingGitBranchOverride?: string
      defaultTaskType?: PipelineTaskRelationType
      defaultDependencyKey?: string
    }

export type PendingWorkspaceAction = PipelineWorkspaceAction | null
