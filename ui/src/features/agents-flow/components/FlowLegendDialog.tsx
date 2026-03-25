import { X } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import { Chip } from '@/shared/components/chip'

type FlowSummary = {
  total: number
  active: number
  healthy: number
  degraded: number
  unconfigured: number
  researchActive: boolean
  pipelineActive: boolean
  sddSpecActive: boolean
  gitContentActive: boolean
}

type FlowLegendDialogProps = {
  error: string | null
  isOpen: boolean
  mode: 'streaming' | 'polling'
  onClose: () => void
  summary: FlowSummary
  wheelPanEnabled: boolean
}

const renderAgentSummaryChips = (summary: FlowSummary, mode: 'streaming' | 'polling') => (
  <div className='mb-3 flex flex-wrap gap-2'>
    <Chip color='grey' variant='outline'>
      {summary.total} agents
    </Chip>

    <Chip color='success' variant='filled'>
      {summary.active} active
    </Chip>

    <Chip color='success' variant='outline'>
      {summary.healthy} healthy
    </Chip>

    <Chip color='warning' variant='outline'>
      {summary.degraded} degraded
    </Chip>

    <Chip color='error' variant='outline'>
      {summary.unconfigured} unconfigured
    </Chip>

    <Chip color='info' variant='outline'>
      {mode === 'streaming' ? 'streaming events' : 'polling mode'}
    </Chip>

    <Chip color={summary.researchActive ? 'success' : 'grey'} variant='outline'>
      Research: {summary.researchActive ? 'active' : 'idle'}
    </Chip>

    <Chip color={summary.pipelineActive ? 'success' : 'grey'} variant='outline'>
      Pipeline: {summary.pipelineActive ? 'active' : 'idle'}
    </Chip>

    <Chip color={summary.sddSpecActive ? 'success' : 'grey'} variant='outline'>
      SDD Spec: {summary.sddSpecActive ? 'active' : 'idle'}
    </Chip>

    <Chip color={summary.gitContentActive ? 'success' : 'grey'} variant='outline'>
      Git Content: {summary.gitContentActive ? 'active' : 'idle'}
    </Chip>
  </div>
)

const renderFlowLegendChips = (wheelPanEnabled: boolean) => (
  <div className='flex flex-wrap gap-2'>
    <Chip color='info' variant='outline'>
      Blue: ChatGraph intent branches
    </Chip>

    <Chip color='info' variant='outline'>
      Purple: SpecPipelineGraph · Send() fan-out
    </Chip>

    <Chip color='success' variant='outline'>
      Green: TicketPipelineGraph execution
    </Chip>

    <Chip color='error' variant='outline'>
      Red dashed: retry loop · bypass · failure
    </Chip>

    <Chip color='grey' variant='outline'>
      Grey dashed: AsyncPostgresSaver checkpointer
    </Chip>

    <Chip color='warning' variant='outline'>
      Diamond: conditional edge · route_review()
    </Chip>

    <Chip color={wheelPanEnabled ? 'success' : 'grey'} variant='outline'>
      Mouse wheel pan: {wheelPanEnabled ? 'on' : 'off'}
    </Chip>
  </div>
)

export default function FlowLegendDialog({
  error,
  isOpen,
  mode,
  onClose,
  summary,
  wheelPanEnabled,
}: FlowLegendDialogProps) {
  if (!isOpen) {
    return null
  }

  return (
    <div
      className='fixed inset-0 z-40 flex items-end justify-end bg-black/45 p-4 sm:items-center sm:justify-center'
      role='dialog'
      aria-modal='true'
      aria-label='Agents flow legend'
      onClick={onClose}
    >
      <div
        className='w-full max-w-xl rounded-xl border bg-background p-4 shadow-xl'
        onClick={(event) => event.stopPropagation()}
      >
        <div className='mb-3 flex items-start justify-between gap-3'>
          <div>
            <h2 className='text-base font-semibold'>Agents Flow Legend</h2>

            <p className='text-sm text-muted-foreground'>
              LangGraph architecture — ChatGraph, SpecPipelineGraph, and TicketPipelineGraph — all
              backed by AsyncPostgresSaver checkpointing via Supabase.
            </p>
          </div>

          <Button type='button' variant='ghost' size='icon-sm' aria-label='Close' onClick={onClose}>
            <X className='size-4' />
          </Button>
        </div>

        {error ? (
          <div className='mb-3 rounded-md border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-700'>
            {error}
          </div>
        ) : null}

        {renderAgentSummaryChips(summary, mode)}

        {renderFlowLegendChips(wheelPanEnabled)}

        <div className='mt-4 flex justify-end'>
          <Button type='button' variant='outline' onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  )
}
