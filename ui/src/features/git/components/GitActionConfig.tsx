import * as React from "react"
import { Download, GitBranch, GitCommit, GitMerge, GitPullRequest, Play, Search, Settings2, X, Zap } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/components/ui/select"
import { Switch } from "@/shared/components/ui/switch"
import { Textarea } from "@/shared/components/ui/textarea"
import { Separator } from "@/shared/components/ui/separator"
import { formatGitDefaultBranchLabel } from "../constants"
import { useGitStore } from "../store/git-store"
import type { GitActionConfig as GitActionConfigType, GitActionType, GitWorkflowKey } from "../types"

interface GitActionConfigProps {
  open: boolean
  onClose: () => void
  workflowKey: GitWorkflowKey
  workflowLabel: string
  phaseLabel: string
  action: GitActionConfigType
  onChange: (updates: Partial<GitActionConfigType>) => void
}

const ACTION_OPTIONS: {
  value: GitActionType
  label: string
  icon: React.ReactNode
  description: string
}[] = [
  {
    value: "none",
    label: "No Action",
    icon: <X className="size-4" />,
    description: "Skip git action for this phase",
  },
  {
    value: "check_git",
    label: "Check for Git",
    icon: <Search className="size-4" />,
    description: "Verify the workspace is a git repository",
  },
  {
    value: "check_pr",
    label: "Check Existing PR/MR",
    icon: <GitPullRequest className="size-4" />,
    description: "Look for an existing open pull/merge request",
  },
  {
    value: "fetch",
    label: "Fetch Latest Refs",
    icon: <Download className="size-4" />,
    description: "Fetch refs from remote without modifying the working tree",
  },
  {
    value: "pull",
    label: "Pull Latest Changes",
    icon: <Download className="size-4" />,
    description: "Pull the latest changes from the remote branch (fast-forward only)",
  },
  {
    value: "rebase",
    label: "Rebase on Base Branch",
    icon: <GitMerge className="size-4" />,
    description: "Fetch the selected/default branch and rebase the current branch onto it",
  },
  {
    value: "create_branch",
    label: "Create Feature Branch",
    icon: <GitBranch className="size-4" />,
    description: "Create and checkout a new feature branch",
  },
  {
    value: "commit",
    label: "Commit Changes",
    icon: <GitCommit className="size-4" />,
    description: "Stage and commit all workspace changes",
  },
  {
    value: "create_pr",
    label: "Create PR / MR",
    icon: <GitPullRequest className="size-4" />,
    description: "Open a pull request (GitHub) or merge request (GitLab)",
  },
  {
    value: "push",
    label: "Push Branch",
    icon: <Play className="size-4" />,
    description: "Push the current branch to the configured remote",
  },
  {
    value: "custom",
    label: "Custom Command",
    icon: <Zap className="size-4" />,
    description: "Run a custom git command",
  },
]

function PatternHint({ vars }: { vars: string[] }) {
  return (
    <p className="text-xs text-muted-foreground mt-1">
      Variables:{" "}
      {vars.map((v) => (
        <code key={v} className="mx-0.5 font-mono bg-muted px-1 rounded">{`{${v}}`}</code>
      ))}
    </p>
  )
}

export function GitActionConfig({
  open,
  onClose,
  workflowKey,
  workflowLabel,
  phaseLabel,
  action,
  onChange,
}: GitActionConfigProps) {
  const globalDefaultBranch = useGitStore((s) => s.workflows[workflowKey].settings.defaultBranch)
  if (!open) return null

  const selectedActionOption =
    ACTION_OPTIONS.find((opt) => opt.value === action.type) ?? ACTION_OPTIONS[0]
  const showBranchPattern = action.type === "create_branch"
  const showCommitPattern = action.type === "commit"
  const showPrFields = action.type === "create_pr"
  const showCustom = action.type === "custom"
  const showTargetBranch = (
    action.type === "create_pr" ||
    action.type === "fetch" ||
    action.type === "pull" ||
    action.type === "rebase"
  )
  const hasConfig = action.type !== "none" && action.type !== "check_git"
  const globalTargetBranch = formatGitDefaultBranchLabel(globalDefaultBranch)
  const hasTargetBranchOverride = String(action.targetBranch || "").trim().length > 0
  const displayedTargetBranch = hasTargetBranchOverride ? String(action.targetBranch || "") : globalTargetBranch
  const targetBranchLabel =
    action.type === "create_pr"
      ? `Target Branch (default: ${globalTargetBranch})`
      : action.type === "fetch"
        ? `Remote Branch to Fetch (default: ${globalTargetBranch})`
      : action.type === "pull"
        ? `Remote Branch to Pull (default: ${globalTargetBranch})`
        : `Branch to Rebase Onto (default: ${globalTargetBranch})`
  const targetBranchHint =
    action.type === "create_pr"
      ? `Branch that the PR/MR merges into. Use the toggle below to inherit the global default (${globalTargetBranch}).`
      : action.type === "fetch"
        ? `Remote branch to fetch. Use the toggle below to inherit the global default (${globalTargetBranch}).`
      : action.type === "pull"
        ? `Remote branch to pull from. Use the toggle below to inherit the global default (${globalTargetBranch}).`
        : `Branch to fetch and rebase onto. Use the toggle below to inherit the global default (${globalTargetBranch}).`

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-lg rounded-lg border shadow-lg flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b shrink-0">
          <div className="flex items-center gap-2">
            <Settings2 className="size-4 text-muted-foreground" />
            <div>
              <h3 className="text-base font-semibold">Git Action</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                Configure the handoff Git action for {workflowLabel}
              </p>
              <p className="text-xs font-medium text-foreground mt-1 leading-tight">
                {phaseLabel}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-5 py-4 space-y-5 flex-1">

          {/* Action type */}
          <div className="space-y-1.5">
            <Label>Action Type</Label>
            <Select
              value={action.type}
              onValueChange={(val) =>
                onChange({ type: val as GitActionType, enabled: val !== "none" })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select action type" />
              </SelectTrigger>
              <SelectContent className="z-[200]">
                {ACTION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex items-start gap-2 rounded-md border bg-muted/30 px-3 py-2">
              <div className="mt-0.5 text-muted-foreground">{selectedActionOption.icon}</div>
              <div className="min-w-0">
                <p className="text-sm font-medium leading-none">{selectedActionOption.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{selectedActionOption.description}</p>
                {(action.type === "fetch" || action.type === "pull" || action.type === "rebase" || action.type === "create_pr") && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Uses global default branch <code className="font-mono">{globalTargetBranch}</code> when no per-action override is set.
                  </p>
                )}
              </div>
            </div>
          </div>

          {action.type !== "none" && (
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm">Enable this action</Label>
                <p className="text-xs text-muted-foreground">Runs automatically at this workflow handoff checkpoint</p>
              </div>
              <Switch
                checked={action.enabled}
                onCheckedChange={(v) => onChange({ enabled: v })}
              />
            </div>
          )}

          {hasConfig && <Separator />}

          {/* Branch name pattern */}
          {showBranchPattern && (
            <>
              <div className="space-y-1.5">
                <Label>Branch Name Pattern</Label>
                <Input
                  value={action.branchNamePattern}
                  onChange={(e) => onChange({ branchNamePattern: e.target.value })}
                  placeholder="feature/{description}"
                />
                <PatternHint vars={["description", "ticket", "type", "date"]} />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm">Reuse Existing Branch</Label>
                  <p className="text-xs text-muted-foreground">
                    If the branch already exists, check it out instead of failing (recommended for reruns)
                  </p>
                </div>
                <Switch
                  checked={action.reuseExistingBranch ?? true}
                  onCheckedChange={(v) => onChange({ reuseExistingBranch: v })}
                />
              </div>
            </>
          )}

          {/* Commit message pattern */}
          {showCommitPattern && (
            <div className="space-y-1.5">
              <Label>Commit Message Pattern</Label>
              <Input
                value={action.commitMessagePattern}
                onChange={(e) => onChange({ commitMessagePattern: e.target.value })}
                placeholder="feat: {description}"
              />
              <PatternHint vars={["description", "ticket", "type", "branch"]} />
            </div>
          )}

          {/* PR / MR fields */}
          {showPrFields && (
            <>
              <div className="space-y-1.5">
                <Label>PR / MR Title Pattern</Label>
                <Input
                  value={action.prTitlePattern}
                  onChange={(e) => onChange({ prTitlePattern: e.target.value })}
                  placeholder="feat: {description}"
                />
                <PatternHint vars={["description", "ticket", "branch", "type"]} />
              </div>

              <div className="space-y-1.5">
                <Label>PR / MR Body Template</Label>
                <Textarea
                  value={action.prBodyTemplate}
                  onChange={(e) => onChange({ prBodyTemplate: e.target.value })}
                  placeholder={"## Summary\n\n{description}"}
                  rows={5}
                />
                <PatternHint vars={["description", "ticket", "branch", "summary"]} />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm">Create as Draft</Label>
                  <p className="text-xs text-muted-foreground">Open PR/MR in draft state</p>
                </div>
                <Switch
                  checked={action.draft}
                  onCheckedChange={(v) => onChange({ draft: v })}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm">Push Before Creating</Label>
                  <p className="text-xs text-muted-foreground">Push branch to remote first</p>
                </div>
                <Switch
                  checked={action.pushBeforePr}
                  onCheckedChange={(v) => onChange({ pushBeforePr: v })}
                />
              </div>
            </>
          )}

          {/* Target branch */}
          {showTargetBranch && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between rounded-md border bg-muted/20 px-3 py-2">
                <div>
                  <Label className="text-sm">Use Global Default Branch</Label>
                  <p className="text-xs text-muted-foreground">
                    Inherits <code className="font-mono">{globalTargetBranch}</code> from the Git page
                  </p>
                </div>
                <Switch
                  checked={!hasTargetBranchOverride}
                  onCheckedChange={(useDefault) =>
                    onChange({
                      targetBranch: useDefault ? "" : displayedTargetBranch,
                    })
                  }
                />
              </div>
              <Label>{targetBranchLabel}</Label>
              <Input
                value={displayedTargetBranch}
                onChange={(e) => onChange({ targetBranch: e.target.value })}
                placeholder={globalTargetBranch}
                disabled={!hasTargetBranchOverride}
              />
              <p className="text-xs text-muted-foreground">{targetBranchHint}</p>
            </div>
          )}

          {/* Custom command */}
          {showCustom && (
            <div className="space-y-1.5">
              <Label>Custom Git Command</Label>
              <Input
                value={action.customCommand}
                onChange={(e) => onChange({ customCommand: e.target.value })}
                placeholder="git stash"
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Full command to run (must start with <code className="font-mono">git</code>)
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t shrink-0">
          <Button variant="outline" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}
