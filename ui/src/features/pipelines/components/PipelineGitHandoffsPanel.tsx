import PipelineGitHandoffCard from '@/features/pipelines/components/PipelineGitHandoffCard'
import type { PipelineGitHandoff } from '@/features/pipelines/types'

type PipelineGitHandoffsPanelProps = {
  handoffs: PipelineGitHandoff[]
  isMutating: boolean
  onResolveHandoff: (taskId: string, handoffId: string, reenableTask: boolean) => Promise<void>
  onKeepBlocked: (taskId: string) => Promise<void>
  onError: (message: string) => void
}

/**
 * Displays all unresolved Git handoffs with consistent guidance and actions.
 */
export default function PipelineGitHandoffsPanel({
  handoffs,
  isMutating,
  onResolveHandoff,
  onKeepBlocked,
  onError,
}: PipelineGitHandoffsPanelProps) {
  if (handoffs.length === 0) {
    return null
  }

  return (
    <section className='rounded-xl border bg-card shadow-sm'>
      <header className='border-b p-2'>
        <div className='flex items-start justify-between gap-2'>
          <div className='min-w-0'>
            <p className='font-semibold text-sm'>Pending Git Handoffs</p>

            <p className='text-muted-foreground text-xs'>
              Fix the Git issue in your workspace, then re-enable the blocked task.
            </p>
          </div>

          <span className='rounded-md border px-2 py-0.5 text-xs'>{handoffs.length}</span>
        </div>
      </header>

      <div className='space-y-2 p-2'>
        {handoffs.map((handoff) => (
          <PipelineGitHandoffCard
            key={handoff.id}
            handoff={handoff}
            isMutating={isMutating}
            onResolveHandoff={onResolveHandoff}
            onKeepBlocked={onKeepBlocked}
            onError={onError}
          />
        ))}
      </div>
    </section>
  )
}
