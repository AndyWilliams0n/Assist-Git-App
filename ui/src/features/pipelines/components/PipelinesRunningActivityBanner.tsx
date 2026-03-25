type PipelinesRunningActivityBannerProps = {
  runningActivityLine: string
}

export default function PipelinesRunningActivityBanner({ runningActivityLine }: PipelinesRunningActivityBannerProps) {
  if (!runningActivityLine) {
    return null
  }

  return (
    <div className='rounded-md border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-emerald-700 text-sm dark:text-emerald-300'>
      <p className='truncate' title={runningActivityLine}>
        {runningActivityLine}
      </p>
    </div>
  )
}
