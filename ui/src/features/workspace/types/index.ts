export interface Workspace {
  id: string
  name: string
  path: string
  description: string
  is_active: number // 0 | 1
  created_at: string
  updated_at: string
}

export interface WorkspaceProject {
  id: string
  workspace_id: string
  name: string
  remote_url: string
  platform: "github" | "gitlab" | "bitbucket" | "unknown"
  local_path: string
  is_cloned: number // 0 | 1
  branch: string
  description: string
  language: string
  stars: number
  cloned_at: string
  created_at: string
  updated_at: string
}

export interface GitHubRepo {
  id: number
  name: string
  full_name: string
  clone_url: string
  ssh_url: string
  description: string
  language: string
  stars: number
  is_private: boolean
  updated_at: string
  default_branch: string
}

export interface GitLabRepo {
  id: number
  name: string
  path_with_namespace: string
  http_url_to_repo: string
  ssh_url_to_repo: string
  description: string
  language: string
  star_count: number
  visibility: string
  updated_at: string
  default_branch: string
}

export interface GitHubSettings {
  has_token: boolean
  token_masked: string
  username: string
}

export interface GitLabSettings {
  has_token: boolean
  token_masked: string
  url: string
  username: string
}

export type RepoPlatform = "github" | "gitlab"
