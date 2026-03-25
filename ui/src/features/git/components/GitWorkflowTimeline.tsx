import * as React from "react"
import {
  Bot,
  Check,
  CheckCircle2,
  ClipboardList,
  Download,
  Code2,
  GitBranch,
  GitCommit,
  GitMerge,
  GitPullRequest,
  Play,
  Plus,
  Search,
  Settings2,
  X,
  Zap,
} from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Separator } from "@/shared/components/ui/separator"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/shared/components/ui/tooltip"
import { Chip } from "@/shared/components/chip"
import { GitActionConfig } from "./GitActionConfig"
import { type GitActionSlot, useGitStore } from "../store/git-store"
import type { GitActionType, GitWorkflowKey, PipelinePhaseConfig } from "../types"

// Map agent icon names to Lucide icons
function AgentIcon({ name }: { name: string }) {
  const icons: Record<string, React.ReactNode> = {
    play: <Play className="size-5" />,
    clipboard: <ClipboardList className="size-5" />,
    code: <Code2 className="size-5" />,
    search: <Search className="size-5" />,
    check: <CheckCircle2 className="size-5" />,
  }

  return <>{icons[name] ?? <Bot className="size-5" />}</>
}

// Helper to normalise agentName to an array
function agentNames(name: string | string[]): string[] {
  return Array.isArray(name) ? name : [name]
}

type ActionVisualConfig = {
  label: string
  icon: React.ReactNode
  badgeColorClass: string
  nodeColorClass: string
  connectorColorClass: string
}

const ACTION_VISUALS: Record<GitActionType, ActionVisualConfig> = {
  none: {
    label: "None",
    icon: <X className="size-3" />,
    badgeColorClass: "text-muted-foreground",
    nodeColorClass: "border-dashed border-border bg-muted/30 text-muted-foreground hover:border-primary/40 hover:text-foreground",
    connectorColorClass: "bg-border",
  },
  check_git: {
    label: "Check Git",
    icon: <Search className="size-3" />,
    badgeColorClass: "text-blue-500",
    nodeColorClass: "border-blue-500/40 bg-blue-500/10 text-blue-400",
    connectorColorClass: "bg-blue-500/40",
  },
  check_pr: {
    label: "Check PR",
    icon: <GitPullRequest className="size-3" />,
    badgeColorClass: "text-fuchsia-500",
    nodeColorClass: "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-400",
    connectorColorClass: "bg-fuchsia-500/40",
  },
  fetch: {
    label: "Fetch",
    icon: <Download className="size-3" />,
    badgeColorClass: "text-sky-500",
    nodeColorClass: "border-sky-500/40 bg-sky-500/10 text-sky-400",
    connectorColorClass: "bg-sky-500/40",
  },
  pull: {
    label: "Pull",
    icon: <Download className="size-3" />,
    badgeColorClass: "text-cyan-500",
    nodeColorClass: "border-cyan-500/40 bg-cyan-500/10 text-cyan-400",
    connectorColorClass: "bg-cyan-500/40",
  },
  rebase: {
    label: "Rebase",
    icon: <GitMerge className="size-3" />,
    badgeColorClass: "text-violet-500",
    nodeColorClass: "border-violet-500/40 bg-violet-500/10 text-violet-400",
    connectorColorClass: "bg-violet-500/40",
  },
  create_branch: {
    label: "New Branch",
    icon: <GitBranch className="size-3" />,
    badgeColorClass: "text-teal-500",
    nodeColorClass: "border-teal-500/40 bg-teal-500/10 text-teal-400",
    connectorColorClass: "bg-teal-500/40",
  },
  commit: {
    label: "Commit",
    icon: <GitCommit className="size-3" />,
    badgeColorClass: "text-amber-500",
    nodeColorClass: "border-amber-500/40 bg-amber-500/10 text-amber-400",
    connectorColorClass: "bg-amber-500/40",
  },
  create_pr: {
    label: "Create PR",
    icon: <GitPullRequest className="size-3" />,
    badgeColorClass: "text-emerald-500",
    nodeColorClass: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
    connectorColorClass: "bg-emerald-500/40",
  },
  push: {
    label: "Push",
    icon: <Play className="size-3" />,
    badgeColorClass: "text-purple-500",
    nodeColorClass: "border-purple-500/40 bg-purple-500/10 text-purple-400",
    connectorColorClass: "bg-purple-500/40",
  },
  custom: {
    label: "Custom",
    icon: <Zap className="size-3" />,
    badgeColorClass: "text-rose-500",
    nodeColorClass: "border-rose-500/40 bg-rose-500/10 text-rose-400",
    connectorColorClass: "bg-rose-500/40",
  },
}

// Small badge showing the configured git action type
function ActionTypeBadge({ type }: { type: GitActionType }) {
  const c = ACTION_VISUALS[type] ?? ACTION_VISUALS.none

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${c.badgeColorClass}`}>
      {c.icon}
      {c.label}
    </span>
  )
}

type SlotActionNodeProps = {
  action: PipelinePhaseConfig["gitAction"]
  onConfigure: () => void
  label: string
  phaseLabel: string
}

function SlotActionNode({ action, onConfigure, label, phaseLabel }: SlotActionNodeProps) {
  const hasAction = action.type !== "none"
  const icon = hasAction ? (
    <GitBranch className="size-3.5" />
  ) : (
    <Plus className="size-3.5" />
  )
  const actionVisuals = ACTION_VISUALS[action.type] ?? ACTION_VISUALS.none
  const actionClass = hasAction
    ? actionVisuals.nodeColorClass
    : ACTION_VISUALS.none.nodeColorClass

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onConfigure}
          className={`
            group flex h-8 w-8 items-center justify-center rounded-md border transition-all
            ${actionClass}
          `}
          aria-label={`Configure ${label.toLowerCase()} git action after ${phaseLabel}`}
        >
          {icon}
        </button>
      </TooltipTrigger>

      <TooltipContent side="bottom">
        <p>
          {label}: {hasAction ? action.type : "none"} after <strong>{phaseLabel}</strong>
        </p>
      </TooltipContent>
    </Tooltip>
  )
}

type PhaseConnectorProps = {
  phase: PipelinePhaseConfig
  variant: "task" | "subtask"
  onConfigurePrimary: () => void
  onConfigureSecondary: () => void
}

// The connector between phases with optional git action indicator
function PhaseConnector({ phase, variant, onConfigurePrimary, onConfigureSecondary }: PhaseConnectorProps) {
  const primaryAction = variant === "subtask" ? phase.subtaskGitAction : phase.gitAction
  const secondaryAction = variant === "subtask" ? phase.subtaskSecondaryGitAction : phase.secondaryGitAction

  const primaryHasAction = primaryAction.type !== "none"
  const secondaryHasAction = secondaryAction.type !== "none"
  const connectorClass = primaryHasAction
    ? (ACTION_VISUALS[primaryAction.type] ?? ACTION_VISUALS.none).connectorColorClass
    : secondaryHasAction
      ? (ACTION_VISUALS[secondaryAction.type] ?? ACTION_VISUALS.none).connectorColorClass
      : ACTION_VISUALS.none.connectorColorClass

  return (
    <div className="flex flex-col items-center gap-1 shrink-0 relative">
      <div className="flex items-center gap-0">
        <div className={`h-[3px] w-5 ${connectorClass}`} />

        <div className="flex flex-col items-center gap-1 rounded-lg border border-border/60 bg-card/70 px-1.5 py-1">
          <SlotActionNode
            action={primaryAction}
            onConfigure={onConfigurePrimary}
            label="Primary"
            phaseLabel={phase.label}
          />

          <SlotActionNode
            action={secondaryAction}
            onConfigure={onConfigureSecondary}
            label="Secondary"
            phaseLabel={phase.label}
          />
        </div>

        <div className={`h-[3px] w-5 ${connectorClass}`} />
      </div>
    </div>
  )
}

// Single pipeline phase card
function PhaseCard({ phase }: { phase: PipelinePhaseConfig }) {
  const names = agentNames(phase.agentName)

  return (
    <div className="flex flex-col items-center gap-1 shrink-0">
      <div className="flex w-[150px] min-w-[150px] max-w-[150px] flex-col items-center gap-2 rounded-xl border bg-card px-3 py-4 shadow-none text-center">
        <div className="size-10 flex items-center justify-center rounded-full bg-muted text-muted-foreground">
          <AgentIcon name={phase.icon} />
        </div>

        <div>
          <p className="text-sm font-medium">{phase.label}</p>

          {names.length === 1 ? (
            <p className="text-[10px] text-muted-foreground mt-0.5 max-w-[100px]">{names[0]}</p>
          ) : (
            <div className="flex flex-col items-center gap-0.5 mt-0.5">
              {names.map((n) => (
                <p key={n} className="text-[10px] text-muted-foreground max-w-[110px] leading-tight">{n}</p>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

type PhaseActionCellProps = {
  isLast: boolean
  primaryAction: PipelinePhaseConfig["gitAction"]
  secondaryAction: PipelinePhaseConfig["gitAction"]
  primarySlot: GitActionSlot
  secondarySlot: GitActionSlot
  onConfigure: (slot: GitActionSlot) => void
}

function PhaseActionCell({
  isLast,
  primaryAction,
  secondaryAction,
  primarySlot,
  secondarySlot,
  onConfigure,
}: PhaseActionCellProps) {
  const primaryHasAction = primaryAction.type !== "none"
  const secondaryHasAction = secondaryAction.type !== "none"

  if (isLast) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-muted-foreground">Primary</span>

      {primaryHasAction ? (
        <ActionTypeBadge type={primaryAction.type} />
      ) : (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 w-fit px-2 text-xs text-muted-foreground hover:text-primary justify-start gap-1"
          onClick={() => onConfigure(primarySlot)}
        >
          <Plus className="size-3" />
          Add primary action
        </Button>
      )}

      <span className="text-[11px] text-muted-foreground mt-1">Secondary</span>

      {secondaryHasAction ? (
        <ActionTypeBadge type={secondaryAction.type} />
      ) : (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 w-fit px-2 text-xs text-muted-foreground hover:text-primary justify-start gap-1"
          onClick={() => onConfigure(secondarySlot)}
        >
          <Plus className="size-3" />
          Add secondary action
        </Button>
      )}
    </div>
  )
}

type PhaseStatusCellProps = {
  isLast: boolean
  primaryHasAction: boolean
  secondaryHasAction: boolean
  primaryEnabled: boolean
  secondaryEnabled: boolean
}

function PhaseStatusCell({ isLast, primaryHasAction, secondaryHasAction, primaryEnabled, secondaryEnabled }: PhaseStatusCellProps) {
  const hasAction = primaryHasAction || secondaryHasAction
  const isEnabled = (primaryHasAction && primaryEnabled) || (secondaryHasAction && secondaryEnabled)

  if (isLast) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  if (isEnabled) {
    return (
      <Chip color="success" variant="outline" className="gap-1">
        <Check className="size-3" />
        Enabled
      </Chip>
    )
  }

  if (hasAction) {
    return (
      <Chip color="warning" variant="outline" className="gap-1">
        <X className="size-3" />
        Disabled
      </Chip>
    )
  }

  return <span className="text-xs text-muted-foreground">No actions configured</span>
}

const SLOT_LABELS: Record<GitActionSlot, string> = {
  "primary": "Task Primary",
  "secondary": "Task Secondary",
  "subtask-primary": "SubTask Primary",
  "subtask-secondary": "SubTask Secondary",
}

interface GitWorkflowTimelineProps {
  workflowKey: GitWorkflowKey
  workflowLabel: string
  description: string
  variant?: "task" | "subtask"
  showTable?: boolean
  showTimeline?: boolean
  showSubtaskColumns?: boolean
}

export function GitWorkflowTimeline({
  workflowKey,
  workflowLabel,
  description,
  variant = "task",
  showTable = true,
  showTimeline = true,
  showSubtaskColumns = true,
}: GitWorkflowTimelineProps) {
  const phases = useGitStore((s) => s.workflows[workflowKey].phases)
  const updatePhaseAction = useGitStore((s) => s.updatePhaseAction)

  const [configuringTarget, setConfiguringTarget] = React.useState<{
    phaseId: string
    slot: GitActionSlot
  } | null>(null)

  const primarySlot: GitActionSlot = variant === "subtask" ? "subtask-primary" : "primary"
  const secondarySlot: GitActionSlot = variant === "subtask" ? "subtask-secondary" : "secondary"

  const configuringPhase = phases.find((p) => p.id === configuringTarget?.phaseId) ?? null
  const configuringSlot = configuringTarget?.slot ?? primarySlot

  const configuringAction = React.useMemo(() => {
    if (!configuringPhase) return null

    if (configuringSlot === "subtask-secondary") return configuringPhase.subtaskSecondaryGitAction
    if (configuringSlot === "subtask-primary") return configuringPhase.subtaskGitAction
    if (configuringSlot === "secondary") return configuringPhase.secondaryGitAction

    return configuringPhase.gitAction
  }, [configuringPhase, configuringSlot])

  const variantLabel = variant === "subtask" ? "SubTask" : "Task"

  return (
    <TooltipProvider>
      <div className="space-y-4">
        {showTimeline && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">{workflowLabel} {variantLabel} Git Workflow Hooks</h3>

                <p className="text-xs text-muted-foreground mt-0.5">
                  {description} Click the connector nodes to set up actions.
                </p>
              </div>

              <Button
                variant="ghost"
                size="sm"
                className="text-xs gap-1"
                onClick={() => {
                  const firstPhaseId = phases[0]?.id
                  if (!firstPhaseId) return
                  setConfiguringTarget({ phaseId: firstPhaseId, slot: primarySlot })
                }}
              >
                <Settings2 className="size-3.5" />
                Configure
              </Button>
            </div>

            {/* Scrollable horizontal timeline */}
            <div className="overflow-x-auto pb-2">
              <div className="flex items-center gap-0 min-w-max px-1">
                {phases.map((phase, index) => (
                  <React.Fragment key={phase.id}>
                    <PhaseCard phase={phase} />

                    {index < phases.length - 1 && (
                      <PhaseConnector
                        phase={phase}
                        variant={variant}
                        onConfigurePrimary={() => setConfiguringTarget({ phaseId: phase.id, slot: primarySlot })}
                        onConfigureSecondary={() => setConfiguringTarget({ phaseId: phase.id, slot: secondarySlot })}
                      />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap items-center gap-4 pt-1">
              <Separator className="flex-1" />

              <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                <span className="flex items-center gap-1">
                  <div className="size-2 rounded-full bg-primary" />
                  Active action
                </span>

                <span className="flex items-center gap-1">
                  <div className="size-2 rounded-full border border-dashed border-muted-foreground" />
                  No action
                </span>
              </div>

              <Separator className="flex-1" />
            </div>
          </>
        )}

        {/* Phase summary table - shown with full task + subtask columns */}
        {showTable ? (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">Phase</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">Agent</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">{showSubtaskColumns ? 'Task Git Action' : 'Git Action'}</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">{showSubtaskColumns ? 'Task Status' : 'Status'}</th>
                  {showSubtaskColumns && (
                    <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">SubTask Git Action</th>
                  )}
                  {showSubtaskColumns && (
                    <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground w-1/6">SubTask Status</th>
                  )}
                </tr>
              </thead>

              <tbody>
                {phases.map((phase, index) => {
                  const isLast = index === phases.length - 1
                  const names = agentNames(phase.agentName)

                  return (
                    <tr
                      key={phase.id}
                      className={`${!isLast ? "border-b" : ""} hover:bg-muted/30 transition-colors`}
                    >
                      <td className="px-4 py-3 font-medium">{phase.label}</td>

                      <td className="px-4 py-3">
                        {names.length === 1 ? (
                          <span className="text-muted-foreground">{names[0]}</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {names.map((n) => (
                              <Chip key={n} size="sm">{n}</Chip>
                            ))}
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3">
                        <PhaseActionCell
                          isLast={isLast}
                          primaryAction={phase.gitAction}
                          secondaryAction={phase.secondaryGitAction}
                          primarySlot="primary"
                          secondarySlot="secondary"
                          onConfigure={(slot) => setConfiguringTarget({ phaseId: phase.id, slot })}
                        />
                      </td>

                      <td className="px-4 py-3">
                        <PhaseStatusCell
                          isLast={isLast}
                          primaryHasAction={phase.gitAction.type !== "none"}
                          secondaryHasAction={phase.secondaryGitAction.type !== "none"}
                          primaryEnabled={phase.gitAction.enabled}
                          secondaryEnabled={phase.secondaryGitAction.enabled}
                        />
                      </td>

                      {showSubtaskColumns && (
                        <td className="px-4 py-3">
                          <PhaseActionCell
                            isLast={isLast}
                            primaryAction={phase.subtaskGitAction}
                            secondaryAction={phase.subtaskSecondaryGitAction}
                            primarySlot="subtask-primary"
                            secondarySlot="subtask-secondary"
                            onConfigure={(slot) => setConfiguringTarget({ phaseId: phase.id, slot })}
                          />
                        </td>
                      )}

                      {showSubtaskColumns && (
                        <td className="px-4 py-3">
                          <PhaseStatusCell
                            isLast={isLast}
                            primaryHasAction={phase.subtaskGitAction.type !== "none"}
                            secondaryHasAction={phase.subtaskSecondaryGitAction.type !== "none"}
                            primaryEnabled={phase.subtaskGitAction.enabled}
                            secondaryEnabled={phase.subtaskSecondaryGitAction.enabled}
                          />
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {/* Git Action Config dialog */}
        {configuringPhase && configuringAction && (
          <GitActionConfig
            open={!!configuringTarget}
            onClose={() => setConfiguringTarget(null)}
            workflowKey={workflowKey}
            workflowLabel={workflowLabel}
            phaseLabel={`${configuringPhase.label} (${SLOT_LABELS[configuringSlot]})`}
            action={configuringAction}
            onChange={(updates) => updatePhaseAction(workflowKey, configuringPhase.id, configuringSlot, updates)}
          />
        )}
      </div>
    </TooltipProvider>
  )
}
