type PipelinesPageStatusProps = {
  pageError: string | null
  backlogCount: number
  isLoading: boolean
  isMutating: boolean
  sharedWorkflowTicketsCount: number
  sharedWorkflowWarning: string | null
  onDismissError?: () => void
}

export default function PipelinesPageStatus({
  pageError,
  backlogCount,
  isLoading,
  isMutating,
  sharedWorkflowTicketsCount,
  sharedWorkflowWarning,
  onDismissError,
}: PipelinesPageStatusProps) {
  return (
    <>
      {pageError ? (
        <div className='flex items-start justify-between gap-2 rounded-md border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-700'>
          <span>{pageError}</span>

          {onDismissError ? (
            <button
              type='button'
              aria-label='Dismiss error'
              className='shrink-0 opacity-60 hover:opacity-100'
              onClick={onDismissError}
            >
              ✕
            </button>
          ) : null}
        </div>
      ) : null}

      {!pageError && backlogCount === 0 && !isLoading && !isMutating && sharedWorkflowTicketsCount === 0 ? (
        <p className='text-muted-foreground text-sm'>
          No shared Jira tickets found yet. Fetch tickets from Workflow Tasks / Agents Flow first; this page will sync
          backlog automatically.
          {sharedWorkflowWarning ? ` ${sharedWorkflowWarning}` : ''}
        </p>
      ) : null}
    </>
  )
}
