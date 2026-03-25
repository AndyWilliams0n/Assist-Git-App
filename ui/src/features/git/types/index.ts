// Git platform types
export type GitPlatform = "github" | "gitlab" | "bitbucket" | "unknown" | "auto"
export type GitWorkflowKey = "chat" | "pipeline" | "pipeline_spec"

// Git action types available per pipeline phase
export type GitActionType =
  | "none"
  | "check_git"
  | "check_pr"
  | "fetch"
  | "pull"
  | "rebase"
  | "create_branch"
  | "commit"
  | "create_pr"
  | "push"
  | "custom"

// Configuration for a specific git action
export interface GitActionConfig {
  type: GitActionType
  enabled: boolean
  branchNamePattern: string
  reuseExistingBranch: boolean
  commitMessagePattern: string
  targetBranch: string
  prTitlePattern: string
  prBodyTemplate: string
  draft: boolean
  pushBeforePr: boolean
  customCommand: string
}

// A pipeline phase with an optional git action assigned after it
export interface PipelinePhaseConfig {
  id: string
  label: string
  description: string
  /** One agent name, or multiple when the phase is shared across workflows */
  agentName: string | string[]
  icon: string
  gitAction: GitActionConfig
  secondaryGitAction: GitActionConfig
  subtaskGitAction: GitActionConfig
  subtaskSecondaryGitAction: GitActionConfig
}

// Global git workflow settings
export interface GitWorkflowSettings {
  defaultBranch: string
  branchNamePattern: string
  commitMessagePattern: string
  prTitlePattern: string
  prBodyTemplate: string
  platform: GitPlatform
  autoDetect: boolean
  autoPushOnCommit: boolean
}

export interface GitWorkflowConfig {
  phases: PipelinePhaseConfig[]
  settings: GitWorkflowSettings
}

export type GitWorkflowConfigs = Record<GitWorkflowKey, GitWorkflowConfig>

// Workspace git status (from API)
export interface WorkspaceGitStatus {
  is_git_repo: boolean
  workspace: string
  branch: string
  staged: number
  modified: number
  untracked: number
  ahead: number
  behind: number
  remotes: Array<{ name: string; url: string }>
  remote_url: string
  platform: string
  last_commit: {
    hash: string
    message: string
    author: string
    when: string
  } | null
  gh_available: boolean
  glab_available: boolean
  error?: string
}

// Branch info from API
export interface GitBranchInfo {
  current: string
  local: string[]
  remote: string[]
}

// PR info from API
export interface GitPR {
  number?: number
  title: string
  headRefName?: string
  baseRefName?: string
  state?: string
  url?: string
  iid?: number
  web_url?: string
}
