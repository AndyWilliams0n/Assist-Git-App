type FlowLoadingOverlayProps = {
  isVisible: boolean
}

export default function FlowLoadingOverlay({ isVisible }: FlowLoadingOverlayProps) {
  if (!isVisible) {
    return null
  }

  return (
    <div className='absolute inset-0 z-20 flex items-center justify-center bg-background/70 text-sm text-muted-foreground'>
      Loading agents flow...
    </div>
  )
}
