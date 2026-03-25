import { Download, Info, Mouse } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'

type FlowControlsProps = {
  wheelPanEnabled: boolean
  onSaveFlowJson: () => void
  onToggleWheelPan: () => void
  onOpenLegend: () => void
}

export default function FlowControls({
  wheelPanEnabled,
  onSaveFlowJson,
  onToggleWheelPan,
  onOpenLegend,
}: FlowControlsProps) {
  return (
    <div className='absolute bottom-4 right-4 z-30 flex items-center gap-2'>
      <Button type='button' variant='secondary' className='shadow-md' onClick={onSaveFlowJson}>
        <Download className='size-4' />
        Save Flow JSON
      </Button>

      <Button
        type='button'
        size='icon-sm'
        variant={wheelPanEnabled ? 'default' : 'outline'}
        className='shadow-md'
        aria-label={wheelPanEnabled ? 'Disable mouse wheel panning' : 'Enable mouse wheel panning'}
        aria-pressed={wheelPanEnabled}
        title={wheelPanEnabled ? 'Mouse wheel panning enabled' : 'Mouse wheel panning disabled'}
        onClick={onToggleWheelPan}
      >
        <Mouse className='size-4' />
      </Button>

      <Button type='button' variant='secondary' className='shadow-md' onClick={onOpenLegend}>
        <Info className='size-4' />
        Flow Legend
      </Button>
    </div>
  )
}
