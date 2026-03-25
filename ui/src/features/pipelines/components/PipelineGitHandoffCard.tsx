import { Button } from '@/shared/components/ui/button'
import { resolvePipelineHandoffGuidance } from '@/features/pipelines/components/handoffs/pipeline-handoff-guidance'
import type { PipelineGitHandoff } from '@/features/pipelines/types'

type PipelineGitHandoffCardProps = {
  handoff: PipelineGitHandoff
  isMutating: boolean
  onResolveHandoff: (taskId: string, handoffId: string, reenableTask: boolean) => Promise<void>
  onKeepBlocked: (taskId: string) => Promise<void>
  onError: (message: string) => void
}

const normalizeText = (value: unknown) => String(value || '').trim()

/**
 * Renders a single unresolved Git handoff with scenario-specific guidance and actions.
 */
export default function PipelineGitHandoffCard({
  handoff,
  isMutating,
  onResolveHandoff,
  onKeepBlocked,
  onError,
}: PipelineGitHandoffCardProps) {
  const handoffId = normalizeText(handoff.id)
  const taskId = normalizeText(handoff.task_id)
  const jiraKey = normalizeText(handoff.jira_key) || 'n/a'
  const strategy = normalizeText(handoff.strategy) || 'manual_required'
  const sourceBranch = normalizeText(handoff.source_branch)
  const reason = normalizeText(handoff.reason) || 'No reason recorded.'
  const guidance = resolvePipelineHandoffGuidance(handoff)
  const actionsDisabled = isMutating || !taskId || !handoffId
  const taskIsBypassed = handoff.task_is_bypassed ?? false

  const handleAction = async (run: () => Promise<void>, fallbackMessage: string) => {
    try {
      await run()
    } catch (err) {
      onError(err instanceof Error ? err.message : fallbackMessage)
    }
  }

  return (
    <article className='rounded-lg border p-2 text-sm'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <p className='font-medium'>{jiraKey}</p>

        <div className='flex flex-wrap gap-1'>
          <span className='rounded-md border px-2 py-0.5 text-xs'>{strategy}</span>

          {sourceBranch ? (
            <span className='rounded-md border px-2 py-0.5 text-xs'>{sourceBranch}</span>
          ) : null}
        </div>
      </div>

      <p className='text-amber-700 text-xs'>{reason}</p>

      <div className='mt-2 rounded-md border border-amber-300/60 bg-amber-100/40 p-2 text-xs text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/20 dark:text-amber-200'>
        <p className='font-semibold'>{guidance.title}</p>

        <p className='mt-1'>{guidance.summary}</p>

        <ol className='mt-1 list-decimal space-y-0.5 pl-4'>
          {guidance.steps.map((step, index) => (
            <li key={`${guidance.key}-step-${index}`}>{step}</li>
          ))}
        </ol>

        {guidance.references.length > 0 ? (
          <div className='mt-1 space-y-0.5'>
            {guidance.references.map((reference) => (
              <p key={`${guidance.key}-${reference.label}`}>
                {reference.label}: <code>{reference.value}</code>
              </p>
            ))}
          </div>
        ) : null}
      </div>

      <div className='mt-2 flex flex-wrap gap-1'>
        {taskIsBypassed ? (
          <Button
            size='sm'
            variant='outline'
            disabled={actionsDisabled}
            onClick={() => {
              void handleAction(
                () => onResolveHandoff(taskId, handoffId, true),
                'Failed to resolve and re-enable'
              )
            }}
          >
            Resolve and Re-enable
          </Button>
        ) : null}

        <Button
          size='sm'
          variant='outline'
          disabled={actionsDisabled}
          onClick={() => {
            void handleAction(
              () => onResolveHandoff(taskId, handoffId, false),
              'Failed to resolve handoff'
            )
          }}
        >
          {taskIsBypassed ? 'Resolved Manually' : 'Dismiss'}
        </Button>

        {taskIsBypassed ? (
          <Button
            size='sm'
            variant='outline'
            disabled={isMutating || !taskId}
            onClick={() => {
              void handleAction(
                () => onKeepBlocked(taskId),
                'Failed to keep task blocked'
              )
            }}
          >
            Keep Blocked
          </Button>
        ) : null}
      </div>
    </article>
  )
}
