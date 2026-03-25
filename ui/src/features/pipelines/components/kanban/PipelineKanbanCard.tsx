import { useState, type DragEvent } from 'react'
import {
  AlertTriangle,
  Ban,
  Check,
  EllipsisVertical,
  Folder,
  GitBranch,
  GripVertical,
  History,
  Info,
  Link2,
  Loader2,
  RotateCcw,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { statusTone } from '@/features/pipelines/components/kanban/kanban-utils'
import type { ColumnId, PipelineKanbanItem } from '@/features/pipelines/components/kanban/types'
import type { PipelineBacklogItem, PipelineTask } from '@/features/pipelines/types'
import { cn } from '@/shared/utils/utils.ts'
import { Chip } from '@/shared/components/chip'

type PipelineKanbanCardProps = {
  item: PipelineKanbanItem
  columnId: ColumnId
  isMutating: boolean
  isDragging: boolean
  isDropBeforeTarget?: boolean
  queuePosition?: number
  queueTotal?: number
  dependencyOrderWarningTaskKey?: string
  onSelectTaskId: (taskId: string | null) => void
  onCardDragStart: (event: DragEvent<HTMLElement>, item: PipelineKanbanItem) => void
  onCardDragEnd: () => void
  onCurrentInsertionDragOver: (event: DragEvent<HTMLElement>, beforeTaskId: string | null) => void
  onCurrentInsertionDrop: (event: DragEvent<HTMLElement>, beforeTaskId: string | null) => void
  onQueueFromBacklog: (item: PipelineBacklogItem) => Promise<void>
  onMoveTaskToBacklog: (taskId: string) => Promise<void>
  onReenableTask: (taskId: string) => Promise<void>
  onStopRunningTask: (taskId: string) => Promise<void>
  onAdminForceResetTask: (taskId: string) => Promise<void>
  onAdminForceCompleteTask: (taskId: string) => Promise<void>
  onEditTaskDetails: (task: PipelineTask) => void
  onRunAction: (fn: () => Promise<void>) => void
}

type TaskInfoTone = 'default' | 'warning' | 'error' | 'success'

type TaskInfoRow = {
  key: string
  icon: LucideIcon
  title: string
  value: string
  tone?: TaskInfoTone
}

type CardMessageTone = 'error' | 'warning' | 'info'

type CardMessage = {
  key: string
  title: string
  value: string
  tone: CardMessageTone
}

const numberOrZero = (value: unknown) => {
  const parsed = Number(value || 0)

  if (!Number.isFinite(parsed)) {
    return 0
  }

  return Math.max(0, Math.floor(parsed))
}

const toStringList = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const normalized: string[] = []
  const seen: Set<string> = new Set()

  for (const item of value) {
    const text = String(item || '').trim()

    if (!text) {
      continue
    }

    const key = text.toLowerCase()

    if (seen.has(key)) {
      continue
    }

    seen.add(key)
    normalized.push(text)
  }

  return normalized
}

const toDependencyKeyList = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }

  const normalized: string[] = []
  const seen: Set<string> = new Set()

  for (const item of value) {
    const key = String(item || '').trim().toUpperCase()

    if (!key || seen.has(key)) {
      continue
    }

    seen.add(key)
    normalized.push(key)
  }

  return normalized
}

const firstNonEmptyText = (...values: unknown[]) => {
  for (const value of values) {
    const normalized = String(value || '').trim()

    if (!normalized) {
      continue
    }

    return normalized
  }

  return ''
}

const normalizeMessage = (value: string) => {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

const loopStatsForTask = (task: PipelineTask) => {
  const latestRun = task.runs[0]
  const attemptCount = numberOrZero(latestRun?.attempt_count)
  const maxRetries = numberOrZero(latestRun?.max_retries)
  const attemptsFailed = numberOrZero(latestRun?.attempts_failed)
  const attemptsCompleted = numberOrZero(latestRun?.attempts_completed)
  const retriesUsed = Math.max(0, attemptCount - 1)
  const retryBudget = maxRetries > 0 ? Math.max(0, maxRetries - 1) : 0
  const attemptsRunning = task.status === 'running' ? 1 : 0
  const hasLoopStats =
    attemptCount > 0 ||
    maxRetries > 0 ||
    attemptsFailed > 0 ||
    attemptsCompleted > 0 ||
    attemptsRunning > 0
  const currentActivity = String(latestRun?.current_activity || task.logs[0]?.message || '').trim()

  return {
    hasLoopStats,
    attemptCount,
    maxRetries,
    attemptsFailed,
    attemptsCompleted,
    attemptsRunning,
    retriesUsed,
    retryBudget,
    currentActivity,
  }
}

const collectTaskMessages = ({
  task,
  isBypassed,
  isDependencyBlocked,
}: {
  task: PipelineTask
  isBypassed: boolean
  isDependencyBlocked: boolean
}): CardMessage[] => {
  const messages: CardMessage[] = []
  const seen: Set<string> = new Set()

  const pushMessage = ({
    title,
    value,
    tone,
  }: {
    title: string
    value: string
    tone: CardMessageTone
  }) => {
    const trimmed = String(value || '').trim()

    if (!trimmed) {
      return
    }

    const key = normalizeMessage(trimmed)

    if (!key || seen.has(key)) {
      return
    }

    seen.add(key)

    messages.push({
      key,
      title,
      value: trimmed,
      tone,
    })
  }

  pushMessage({
    title: 'Failure',
    value: String(task.failure_reason || ''),
    tone: 'error',
  })

  if (isBypassed) {
    if (!isDependencyBlocked) {
      pushMessage({
        title: 'Bypass',
        value: String(task.bypass_reason || ''),
        tone: 'warning',
      })
    }
  }

  if (isDependencyBlocked) {
    pushMessage({
      title: 'Dependency',
      value: String(task.dependency_block_reason || task.bypass_reason || ''),
      tone: 'warning',
    })
  }

  return messages
}

const taskInfoToneClass: Record<TaskInfoTone, string> = {
  default: 'text-muted-foreground',
  warning: 'text-amber-700 dark:text-amber-300',
  error: 'text-rose-700 dark:text-rose-300',
  success: 'text-emerald-700 dark:text-emerald-300',
}

const messageToneClass: Record<CardMessageTone, string> = {
  error: 'border-rose-300/70 bg-rose-50/80 text-rose-900 dark:border-rose-700/70 dark:bg-rose-950/25 dark:text-rose-200',
  warning: 'border-amber-300/70 bg-amber-50/80 text-amber-900 dark:border-amber-700/70 dark:bg-amber-950/25 dark:text-amber-200',
  info: 'border-sky-300/70 bg-sky-50/70 text-sky-900 dark:border-sky-700/70 dark:bg-sky-950/25 dark:text-sky-200',
}

const messageToneIcon: Record<CardMessageTone, LucideIcon> = {
  error: AlertTriangle,
  warning: Ban,
  info: Info,
}

function DragAffordance({
  enabled,
  text,
}: {
  enabled: boolean
  text: string
}) {
  return (
    <div
      className={cn(
        'mb-2 inline-flex items-center gap-2 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors',
        enabled
          ? 'border-sky-300/70 bg-sky-50/70 text-sky-700 dark:border-sky-700/60 dark:bg-sky-950/25 dark:text-sky-300'
          : 'border-zinc-300/50 bg-zinc-50/60 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-400'
      )}
      aria-hidden='true'
    >
      <span className='grid grid-cols-2 gap-0.5'>
        <span className='h-1 w-1 rounded-full bg-current' />

        <span className='h-1 w-1 rounded-full bg-current' />

        <span className='h-1 w-1 rounded-full bg-current' />

        <span className='h-1 w-1 rounded-full bg-current' />
      </span>

      <span>{text}</span>
    </div>
  )
}

function DragHandle({
  enabled,
  label,
}: {
  enabled: boolean
  label: string
}) {
  return (
    <span
      className={cn(
        'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border',
        enabled
          ? 'border-zinc-300/80 text-zinc-500 dark:border-zinc-700 dark:text-zinc-400'
          : 'border-zinc-300/50 text-zinc-400 dark:border-zinc-800 dark:text-zinc-600'
      )}
      aria-hidden='true'
      title={label}
    >
      <GripVertical className='h-3.5 w-3.5' />
    </span>
  )
}

function TaskInfoList({ rows }: { rows: TaskInfoRow[] }) {
  if (!rows.length) {
    return null
  }

  return (
    <ul className='mt-3 space-y-1.5 border-t border-border/60 pt-2'>
      {rows.map((row) => {
        const Icon = row.icon

        return (
          <li key={row.key} className={cn('flex items-start gap-2 text-xs', taskInfoToneClass[row.tone || 'default'])}>
            <Icon className='mt-0.5 h-3.5 w-3.5 shrink-0' aria-hidden='true' />

            <span className='shrink-0 font-medium'>{row.title}</span>

            <span className='min-w-0 truncate' title={row.value}>
              {row.value || 'n/a'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function TaskMessagePanel({
  messages,
  open,
}: {
  messages: CardMessage[]
  open: boolean
}) {
  if (!messages.length) {
    return null
  }

  const primary = messages[0]
  const details = messages.slice(1)
  const compactPreviewLength = 110
  const hasLongPrimary = primary.value.length > compactPreviewLength
  const hasDetails = hasLongPrimary || details.length > 0
  const Icon = messageToneIcon[primary.tone]

  return (
    <section className={cn('mt-3 rounded-md border p-1.5', messageToneClass[primary.tone])}>
      <div className='flex items-start gap-2'>
        <Icon className='mt-0.5 h-4 w-4 shrink-0' aria-hidden='true' />

        <div className='min-w-0 flex-1'>
          <div className='flex items-start justify-between gap-2'>
            <p className='text-[11px] font-semibold uppercase tracking-wide'>{primary.title}</p>
          </div>

          <p className={cn('mt-0.5 break-words text-[11px] leading-4', !open && 'line-clamp-2')}>
            {open || !hasLongPrimary ? primary.value : `${primary.value.slice(0, compactPreviewLength)}...`}
          </p>
        </div>
      </div>

      {hasDetails && open ? (
        <div className='mt-2 space-y-2'>
          {details.map((message) => {
            const DetailIcon = messageToneIcon[message.tone]

            return (
              <div
                key={message.key}
                className={cn('rounded border p-2 text-xs', messageToneClass[message.tone])}
              >
                <div className='flex items-start gap-2'>
                  <DetailIcon className='mt-0.5 h-3.5 w-3.5 shrink-0' aria-hidden='true' />

                  <div className='min-w-0'>
                    <p className='text-[11px] font-semibold uppercase tracking-wide'>{message.title}</p>

                    <p className='mt-1 break-words'>{message.value}</p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : null}
    </section>
  )
}

type LoadingButtonKey =
  | 'queue'
  | 'move-to-backlog'
  | 'reenable'
  | 'stop'
  | 'remove'
  | 'admin-reset'
  | 'admin-complete'

export default function PipelineKanbanCard({
  item,
  columnId,
  isMutating,
  isDragging,
  isDropBeforeTarget = false,
  queuePosition,
  queueTotal,
  dependencyOrderWarningTaskKey,
  onSelectTaskId,
  onCardDragStart,
  onCardDragEnd,
  onCurrentInsertionDragOver,
  onCurrentInsertionDrop,
  onQueueFromBacklog,
  onMoveTaskToBacklog,
  onReenableTask,
  onStopRunningTask,
  onAdminForceResetTask,
  onAdminForceCompleteTask,
  onEditTaskDetails,
  onRunAction,
}: PipelineKanbanCardProps) {
  const [loadingButton, setLoadingButton] = useState<LoadingButtonKey | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  const runWithLoading = (key: LoadingButtonKey, fn: () => Promise<void>) => {
    setLoadingButton(key)
    onRunAction(() => fn().finally(() => setLoadingButton(null)))
  }

  if (item.kind === 'backlog' && item.backlog) {
    const tone = statusTone(item.status)
    const disabled = item.tracked || isMutating
    const backlogSourceLabel = item.backlog.task_source === 'spec' ? 'SPEC' : 'JIRA'
    const backlogPayload = item.backlog.payload && typeof item.backlog.payload === 'object'
      ? item.backlog.payload as Record<string, unknown>
      : {}
    const rawBacklogDependencyMode = String(backlogPayload.dependency_mode || '').trim().toLowerCase()
    const backlogDependsOnKeys = toDependencyKeyList(backlogPayload.depends_on)
    const parentDependencyKey = String(backlogPayload.parent_spec_name || '').trim().toUpperCase()
    const backlogDependencyKeys = [...backlogDependsOnKeys]

    if (parentDependencyKey && !backlogDependencyKeys.includes(parentDependencyKey)) {
      backlogDependencyKeys.unshift(parentDependencyKey)
    }

    const backlogIsSubtask = item.backlog.task_source === 'spec'
      && (rawBacklogDependencyMode === 'subtask' || backlogDependencyKeys.length > 0)
    const backlogTaskTypeLabel = backlogIsSubtask ? 'Subtask' : 'Task'
    const backlogDependsOnLabel = backlogDependencyKeys.length > 0 ? backlogDependencyKeys.join(', ') : 'n/a'
    const backlogWorkingBranchOverride = firstNonEmptyText(
      backlogPayload.starting_git_branch_override,
      backlogPayload.startingGitBranchOverride,
      backlogPayload.starting_git_branch,
      backlogPayload.working_branch,
      backlogPayload.active_working_branch,
      backlogPayload.branch,
    )
    const backlogWorkingBranchLabel = backlogWorkingBranchOverride || 'Active workspace branch'
    const hasBacklogWorkingBranchOverride = Boolean(backlogWorkingBranchOverride)

    const backlogRows: TaskInfoRow[] = [
      {
        key: 'status',
        icon: Info,
        title: 'Status',
        value: item.backlog.status || 'n/a',
      },
      {
        key: 'priority',
        icon: AlertTriangle,
        title: 'Priority',
        value: item.backlog.priority || 'n/a',
      },
      {
        key: 'working-branch',
        icon: GitBranch,
        title: 'Working Branch',
        value: backlogWorkingBranchLabel,
        tone: hasBacklogWorkingBranchOverride ? 'success' : 'default',
      },
    ]

    if (item.backlog.task_source === 'spec') {
      backlogRows.push({
        key: 'relation',
        icon: Link2,
        title: 'Task Type',
        value: backlogTaskTypeLabel,
      })

      backlogRows.push({
        key: 'depends-on',
        icon: Link2,
        title: 'Depends On',
        value: backlogDependsOnLabel,
      })
    }

    return (
      <article
        key={item.id}
        draggable={!disabled}
        onDragStart={(event) => onCardDragStart(event, item)}
        onDragEnd={onCardDragEnd}
        className={cn(
          'min-h-[fit-content] group relative overflow-hidden rounded-lg border p-3 shadow-none transition-all duration-150',
          disabled
            ? 'cursor-default'
            : 'cursor-grab active:cursor-grabbing hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-sm',
          isDragging && 'cursor-grabbing scale-[0.99] opacity-60 ring-2 ring-sky-400/60'
        )}
        aria-grabbed={isDragging}
      >
        <DragAffordance enabled={!disabled} text={disabled ? 'Already tracked' : 'Drag to queue'} />

        <button type='button' className='w-full text-left' onClick={() => onSelectTaskId(null)}>
          <div className='flex items-center justify-between gap-2'>
            <p className='font-medium text-sm'>{item.backlog.key}</p>

            <div className='flex items-center gap-1'>
              {isDragging ? (
                <Chip color='info' variant='outline'>
                  Dragging
                </Chip>
              ) : null}

              <Chip color={tone.color} variant={tone.variant}>
                {item.tracked ? 'Tracked' : backlogSourceLabel}
              </Chip>
            </div>
          </div>

          <p className='mt-2 line-clamp-2 text-sm'>{item.backlog.title}</p>

          <TaskInfoList rows={backlogRows} />
        </button>

        <Button
          className='mt-3 w-full shadow-none'
          size='sm'
          variant='outline'
          disabled={disabled}
          onClick={() => {
            runWithLoading('queue', () => onQueueFromBacklog(item.backlog as PipelineBacklogItem))
          }}
        >
          {loadingButton === 'queue' ? <Loader2 className='mr-1.5 size-3.5 animate-spin' /> : null}

          Queue to Task Queue
        </Button>
      </article>
    )
  }

  const task = item.task

  if (!task) {
    return null
  }

  const tone = statusTone(task.status)
  const taskSourceLabel = task.task_source === 'spec' ? 'SPEC' : 'JIRA'
  const isBypassed = Boolean(Number(task.is_bypassed || 0))
  const isDependencyBlocked = Boolean(Number(task.is_dependency_blocked || 0))
  const hasFailureReason = Boolean(String(task.failure_reason || '').trim())
  const hasUnresolvedHandoff = Number(task.unresolved_handoff_count || 0) > 0
  const isAttentionRequired = task.execution_state === 'attention_required'
  const isBlockedExecutionState = task.execution_state === 'blocked' || task.execution_state === 'attention_required'
  const hasBlockingState = isBypassed || isDependencyBlocked || hasUnresolvedHandoff || isBlockedExecutionState
  const isDependencyOnlyBlock = isDependencyBlocked && !hasFailureReason && !hasUnresolvedHandoff
  const draggable = task.status === 'current' && !isMutating
  const jiraCompleteRule = (task.jira_complete_column_name || '').trim() || 'No completion move set'
  const workingBranchRule = (task.starting_git_branch_override || '').trim() || 'Git Actions Default'
  const hasWorkingBranchOverride = Boolean((task.starting_git_branch_override || '').trim())
  const isCurrentQueueCard = columnId === 'current' && task.status === 'current' && typeof queuePosition === 'number'
  const isQueueLead = isCurrentQueueCard && queuePosition === 1
  const isFixRerun = task.version > 1
  const loopStats = loopStatsForTask(task)

  const payloadDependencyMode = String(task.jira_payload?.dependency_mode || '').trim().toLowerCase()
  const payloadDependsOn = toStringList(task.jira_payload?.depends_on)
  const isSubtask = payloadDependencyMode === 'subtask' || payloadDependsOn.length > 0 || task.dependencies.length > 0
  const relationLabel = isSubtask ? 'SUBTASK' : 'TASK'
  const subtaskDependencyLabel = payloadDependsOn.length
    ? payloadDependsOn.join(', ')
    : task.dependencies.length > 0
      ? `${task.dependencies.length} linked task${task.dependencies.length === 1 ? '' : 's'}`
      : 'n/a'

  const executionChipLabel = isCurrentQueueCard
    ? isQueueLead
      ? 'Next'
      : `#${queuePosition}`
    : null

  const showDragHandle = task.status === 'current'
  const statusHeaderIcon =
    task.status === 'complete'
      ? {
          Icon: Check,
          className: 'text-emerald-500 dark:text-emerald-300',
          label: 'Complete',
        }
      : null

  const primaryHeaderChip: {
    color: 'success' | 'info' | 'grey'
    variant: 'filled' | 'outline'
    label: string
  } | null = executionChipLabel
    ? {
        color: isQueueLead ? 'success' : 'info',
        variant: isQueueLead ? 'filled' : 'outline',
        label: executionChipLabel,
      }
    : task.status !== 'current' && !statusHeaderIcon
      ? {
          color: tone.color,
          variant: tone.variant,
          label: `${task.status.toUpperCase()} v${task.version}`,
        }
      : null

  const loopSummary = loopStats.hasLoopStats
    ? `Attempt ${loopStats.attemptCount || 0}/${loopStats.maxRetries || 0} • Retries ${loopStats.retriesUsed}/${loopStats.retryBudget} • running ${loopStats.attemptsRunning} completed ${loopStats.attemptsCompleted} failed ${loopStats.attemptsFailed}`
    : ''

  const stateFlags: string[] = []

  if (isBlockedExecutionState) {
    stateFlags.push(isAttentionRequired ? 'Stopped' : 'Blocked')
  }

  if (isDependencyBlocked) {
    stateFlags.push('Dependency blocked')
  }

  if (isBypassed) {
    if (!isDependencyBlocked) {
      stateFlags.push('Bypassed')
    }
  }

  if (hasUnresolvedHandoff) {
    stateFlags.push(`Handoff ${task.unresolved_handoff_count}`)
  }

  if (isFixRerun) {
    stateFlags.push('Fix rerun')
  }

  const stateSummary = stateFlags.length ? stateFlags.join(' • ') : 'Ready'

  const infoRows: TaskInfoRow[] = [
    {
      key: 'workspace',
      icon: Folder,
      title: 'Workspace',
      value: task.workspace_path || 'n/a',
    },
    {
      key: 'jira-complete',
      icon: Info,
      title: 'Jira Complete',
      value: jiraCompleteRule,
    },
    {
      key: 'working-branch',
      icon: GitBranch,
      title: 'Working Branch',
      value: workingBranchRule,
      tone: hasWorkingBranchOverride ? 'success' : 'default',
    },
    {
      key: 'execution-state',
      icon: Ban,
      title: 'Execution State',
      value: stateSummary,
      tone: hasBlockingState ? 'warning' : 'default',
    },
  ]

  if (isCurrentQueueCard) {
    infoRows.push({
      key: 'queue-order',
      icon: Link2,
      title: 'Queue Order',
      value: isQueueLead
        ? 'Top of queue: this task executes first.'
        : `Pipeline order ${queuePosition}${queueTotal ? ` of ${queueTotal}` : ''}.`,
      tone: isQueueLead ? 'success' : 'default',
    })
  }

  if (isSubtask) {
    infoRows.push({
      key: 'depends-on',
      icon: Link2,
      title: 'Depends On',
      value: subtaskDependencyLabel,
      tone: isDependencyBlocked ? 'warning' : 'default',
    })
  }

  if (loopStats.hasLoopStats) {
    infoRows.push({
      key: 'retry-loop',
      icon: RotateCcw,
      title: 'Retry Loop',
      value: loopSummary,
      tone: hasBlockingState ? 'warning' : 'default',
    })
  }

  if (task.status === 'running' && loopStats.currentActivity) {
    infoRows.push({
      key: 'current-activity',
      icon: Info,
      title: 'Current Activity',
      value: loopStats.currentActivity,
      tone: 'success',
    })
  }

  const taskMessages = collectTaskMessages({
    task,
    isBypassed,
    isDependencyBlocked,
  })
  const visibleTaskMessages = isDependencyOnlyBlock ? [] : taskMessages
  const isSpecTask = task.task_source === 'spec'
  const canForceComplete = task.status === 'current'
  const canEditDetails = task.status === 'current'

  return (
    <article
      key={item.id}
      draggable={draggable}
      onDragStart={(event) => onCardDragStart(event, item)}
      onDragEnd={onCardDragEnd}
      onDragOver={
        columnId === 'current'
          ? (event) => {
              onCurrentInsertionDragOver(event, task.id)
            }
          : undefined
      }
      onDrop={
        columnId === 'current'
          ? (event) => {
              onCurrentInsertionDrop(event, task.id)
            }
          : undefined
      }
      className={cn(
        'min-h-[fit-content] group relative overflow-hidden rounded-lg border p-3 shadow-none transition-all duration-150',
        '[&_*]:cursor-inherit',
        draggable
          ? 'cursor-grab active:cursor-grabbing hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-sm'
          : 'cursor-default',
        isDragging && 'cursor-grabbing scale-[0.99] opacity-60 ring-2 ring-sky-400/60',
        isDropBeforeTarget && 'ring-2 ring-sky-300 ring-offset-1'
      )}
      aria-grabbed={isDragging}
      title={draggable ? 'Drag to reorder this queue card' : undefined}
    >
      <div className='relative z-10 pointer-events-none'>
        <div className='w-full text-left'>
          <div className='space-y-1.5'>
            <div className='flex items-center justify-between gap-2'>
              <div className='inline-flex min-w-0 items-center gap-2'>
                {showDragHandle ? (
                  <DragHandle
                    enabled={draggable}
                    label={
                      draggable
                        ? 'Drag to reorder queue'
                        : task.status === 'running'
                          ? 'Locked while running'
                          : 'Reordering available in Task Queue'
                    }
                  />
                ) : null}

                <p className='truncate text-sm'>{task.title}</p>
              </div>

              {primaryHeaderChip ? (
                <Chip color={primaryHeaderChip.color} variant={primaryHeaderChip.variant}>
                  {primaryHeaderChip.label}
                </Chip>
              ) : statusHeaderIcon ? (
                <statusHeaderIcon.Icon
                  className={cn('h-4 w-4 shrink-0', statusHeaderIcon.className)}
                  aria-label={statusHeaderIcon.label}
                />
              ) : null}

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type='button'
                    size='icon-xs'
                    variant='ghost'
                    className='pointer-events-auto h-7 w-7'
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                    }}
                    aria-label='Open task admin menu'
                  >
                    <EllipsisVertical className='h-4 w-4' />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align='end'>
                  <DropdownMenuLabel>Admin Actions</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => {
                      onSelectTaskId(task.id)
                      setHistoryOpen(true)
                    }}
                  >
                    <History className='h-4 w-4' />
                    Show History
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!canEditDetails || isMutating}
                    onClick={() => {
                      onEditTaskDetails(task)
                    }}
                  >
                    <Info className='h-4 w-4' />
                    Set Card Details
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!canForceComplete || isMutating}
                    onClick={() => {
                      runWithLoading('admin-complete', () => onAdminForceCompleteTask(task.id))
                    }}
                  >
                    {loadingButton === 'admin-complete' ? <Loader2 className='size-3.5 animate-spin' /> : null}
                    {loadingButton !== 'admin-complete' ? <Check className='h-4 w-4' /> : null}
                    Mark As Complete
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!isSpecTask || isMutating}
                    onClick={() => {
                      runWithLoading('admin-reset', () => onAdminForceResetTask(task.id))
                    }}
                  >
                    {loadingButton === 'admin-reset' ? <Loader2 className='size-3.5 animate-spin' /> : null}
                    {loadingButton !== 'admin-reset' ? <RotateCcw className='h-4 w-4' /> : null}
                    Force Reset SPEC
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className='flex items-center justify-between gap-2'>
              <p className='shrink-0 text-sm font-medium'>{task.jira_key}</p>

              <div className='flex items-center gap-1'>
                <Chip color='grey' variant='outline'>
                  {taskSourceLabel}
                </Chip>

                <Chip color='grey' variant='outline'>
                  {relationLabel}
                </Chip>

                {isDependencyBlocked ? (
                  <Chip color='warning' variant='outline'>
                    Dependency
                  </Chip>
                ) : null}
              </div>
            </div>
          </div>

          <TaskInfoList rows={infoRows} />
        </div>

        <TaskMessagePanel messages={visibleTaskMessages} open={historyOpen} />

        <div className='mt-3 flex flex-wrap gap-1'>
          {task.status === 'current' ? (
            <Button
              className='pointer-events-auto shadow-none'
              size='sm'
              variant='outline'
              disabled={isMutating}
              onClick={() => {
                runWithLoading('move-to-backlog', () => onMoveTaskToBacklog(task.id))
              }}
            >
              {loadingButton === 'move-to-backlog' ? <Loader2 className='mr-1.5 size-3.5 animate-spin' /> : null}

              Move to Backlog
            </Button>
          ) : null}

          {task.status === 'current' && isBlockedExecutionState && !isDependencyOnlyBlock ? (
            <Button
              className='pointer-events-auto shadow-none'
              size='sm'
              variant='outline'
              disabled={isMutating}
              onClick={() => {
                runWithLoading('reenable', () => onReenableTask(task.id))
              }}
            >
              {loadingButton === 'reenable' ? <Loader2 className='mr-1.5 size-3.5 animate-spin' /> : null}

              Re-enable Task
            </Button>
          ) : null}

          {task.status === 'running' ? (
            <Button
              className='pointer-events-auto shadow-none'
              size='sm'
              variant='destructive'
              disabled={isMutating}
              onClick={() => {
                runWithLoading('stop', () => onStopRunningTask(task.id))
              }}
            >
              {loadingButton === 'stop' ? <Loader2 className='mr-1.5 size-3.5 animate-spin' /> : null}

              Stop
            </Button>
          ) : null}

          {task.status === 'complete' ? (
            <Button
              className='pointer-events-auto shadow-none'
              size='sm'
              variant='outline'
              disabled={isMutating}
              onClick={() => {
                runWithLoading('remove', () => onMoveTaskToBacklog(task.id))
              }}
            >
              {loadingButton === 'remove' ? <Loader2 className='mr-1.5 size-3.5 animate-spin' /> : null}

              Remove from Pipeline
            </Button>
          ) : null}
        </div>
      </div>

      {dependencyOrderWarningTaskKey ? (
        <div className='pointer-events-none absolute inset-0 z-20 flex items-center justify-center px-3'>
          <div className='rounded-md border border-black bg-black px-3 py-2 text-center text-xs font-semibold text-white shadow-sm backdrop-blur-sm dark:border-white dark:bg-white dark:text-black'>
            DEPENDENT ON TASK: {dependencyOrderWarningTaskKey}. Please reorder.
          </div>
        </div>
      ) : null}
    </article>
  )
}
