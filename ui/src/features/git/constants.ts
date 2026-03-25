export const ACTIVE_WORKSPACE_BRANCH_VALUE = "__active_workspace_branch__"

export function formatGitDefaultBranchLabel(defaultBranch: string, currentBranch?: string | null): string {
  if (defaultBranch === ACTIVE_WORKSPACE_BRANCH_VALUE) {
    const normalizedCurrentBranch = String(currentBranch || "").trim()
    return normalizedCurrentBranch
      ? `Use active workspace branch (${normalizedCurrentBranch})`
      : "Use active workspace branch"
  }

  const normalizedBranch = String(defaultBranch || "").trim()
  return normalizedBranch || "main"
}

export function formatGitPlatformLabel(platform: string): string {
  if (platform === "github") return "GitHub"
  if (platform === "gitlab") return "GitLab"
  if (platform === "bitbucket") return "Bitbucket"
  return platform || "Unknown"
}
