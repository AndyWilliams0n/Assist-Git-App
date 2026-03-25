import { useCallback, useEffect, useRef } from 'react'

import type { WorkflowSpecTask } from '@/features/workflow-tasks/types'

const POLL_INTERVAL_MS = 3000
const MAX_POLL_DURATION_MS = 10 * 60 * 1000

type UseSpecGenerationPollerOptions = {
  onGenerated: (task: WorkflowSpecTask) => void
  onError: (specName: string) => void
  enabled: boolean
}

/**
 * Polls GET /api/spec-tasks/{specName} every 3s while status is 'generating'.
 * Calls onGenerated when status becomes 'generated'.
 * Calls onError when status becomes 'failed' or the 10-minute timeout is exceeded.
 */
export function useSpecGenerationPoller(
  specName: string | null,
  workspacePath: string,
  options: UseSpecGenerationPollerOptions
): void {
  const { onGenerated, onError, enabled } = options

  const onGeneratedRef = useRef(onGenerated)
  const onErrorRef = useRef(onError)

  onGeneratedRef.current = onGenerated
  onErrorRef.current = onError

  const poll = useCallback(async () => {
    if (!specName) {
      return
    }

    const params = new URLSearchParams({ workspace_path: workspacePath })
    const response = await fetch(`/api/spec-tasks/${encodeURIComponent(specName)}?${params}`)

    if (!response.ok) {
      return
    }

    const task: WorkflowSpecTask = await response.json()

    if (task.status === 'generated') {
      onGeneratedRef.current(task)
    } else if (task.status === 'failed') {
      onErrorRef.current(specName)
    }

    return task.status
  }, [specName, workspacePath])

  useEffect(() => {
    if (!enabled || !specName) {
      return
    }

    const startedAt = Date.now()
    let stopped = false

    const interval = setInterval(async () => {
      if (stopped) {
        return
      }

      if (Date.now() - startedAt > MAX_POLL_DURATION_MS) {
        clearInterval(interval)
        onErrorRef.current(specName)
        return
      }

      const status = await poll()

      if (status === 'generated' || status === 'failed') {
        clearInterval(interval)
      }
    }, POLL_INTERVAL_MS)

    return () => {
      stopped = true
      clearInterval(interval)
    }
  }, [enabled, specName, poll])
}
