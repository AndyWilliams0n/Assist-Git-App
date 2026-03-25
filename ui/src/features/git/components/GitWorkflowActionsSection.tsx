import { GitBranch, Loader2, Save } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Label } from "@/shared/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/components/ui/select"
import { ACTIVE_WORKSPACE_BRANCH_VALUE, formatGitDefaultBranchLabel } from "../constants"
import { GitWorkflowTimeline } from "./GitWorkflowTimeline"
import type { GitWorkflowKey } from "../types"

interface GitWorkflowActionsSectionProps {
  workflowKey: GitWorkflowKey
  workflowTitle: string
  workflowSummary: string
  defaultBranch: string
  currentBranch: string | null
  selectableBranchOptions: string[]
  workspacePath: string
  isGitRepo: boolean
  isLoadingBranches: boolean
  configLoaded: boolean
  isSavingConfig: boolean
  showSubtask?: boolean
  onDefaultBranchChange: (value: string) => void
  onSave: () => void
}

export function GitWorkflowActionsSection({
  workflowKey,
  workflowTitle,
  workflowSummary,
  defaultBranch,
  currentBranch,
  selectableBranchOptions,
  workspacePath,
  isGitRepo,
  isLoadingBranches,
  configLoaded,
  isSavingConfig,
  showSubtask = true,
  onDefaultBranchChange,
  onSave,
}: GitWorkflowActionsSectionProps) {
  const branchOptions = Array.from(
    new Set(
      [
        ...selectableBranchOptions,
        defaultBranch,
      ].filter(
        (branchName) =>
          Boolean(String(branchName || "").trim()) &&
          String(branchName) !== ACTIVE_WORKSPACE_BRANCH_VALUE
      )
    )
  )

  const placeholder = !workspacePath || !isGitRepo
    ? "Select a git workspace first"
    : isLoadingBranches
      ? "Loading branches..."
      : "Select default branch"

  const selectId = `git-default-working-branch-${workflowKey}`

  return (
    <section className="space-y-6">
      <div className="rounded-lg border bg-card p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="space-y-1">
            <h2 className="text-sm font-medium flex items-center gap-2">
              <GitBranch className="size-4" />
              {workflowTitle} Default Working Branch
            </h2>

            <p className="text-xs text-muted-foreground">
              Used by {workflowTitle.toLowerCase()} pull/rebase/PR actions when their per-action target branch is left blank.
            </p>
          </div>

          <div className="w-full md:w-80 space-y-1.5">
            <Label htmlFor={selectId} className="text-xs">
              Target Branch Default
            </Label>

            <Select
              value={defaultBranch}
              onValueChange={onDefaultBranchChange}
              disabled={!workspacePath || !isGitRepo || isLoadingBranches}
            >
              <SelectTrigger id={selectId} className="h-8">
                <SelectValue placeholder={placeholder} />
              </SelectTrigger>

              <SelectContent>
                <SelectItem value={ACTIVE_WORKSPACE_BRANCH_VALUE}>
                  Use active workspace branch
                </SelectItem>

                {branchOptions.map((branchName) => (
                  <SelectItem key={branchName} value={branchName}>
                    {branchName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <p className="text-[11px] text-muted-foreground">
              Selected default:{" "}
              <code className="font-mono">
                {formatGitDefaultBranchLabel(defaultBranch, currentBranch)}
              </code>
              . This is used when a workflow action leaves its target/base branch blank.
            </p>

            <div className="pt-1">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="gap-1.5"
                disabled={!configLoaded || isSavingConfig}
                onClick={onSave}
              >
                {isSavingConfig ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                Save {workflowTitle} Branch Default
              </Button>
            </div>
          </div>
        </div>
      </div>

      <GitWorkflowTimeline
        workflowKey={workflowKey}
        workflowLabel={workflowTitle}
        description={workflowSummary}
        variant="task"
        showTable={false}
      />

      {showSubtask && (
        <GitWorkflowTimeline
          workflowKey={workflowKey}
          workflowLabel={workflowTitle}
          description={workflowSummary}
          variant="subtask"
          showTable={false}
        />
      )}

      <GitWorkflowTimeline
        workflowKey={workflowKey}
        workflowLabel={workflowTitle}
        description={workflowSummary}
        variant="task"
        showTimeline={false}
        showTable={true}
        showSubtaskColumns={showSubtask}
      />
    </section>
  )
}
