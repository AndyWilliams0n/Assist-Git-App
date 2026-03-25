import { useCallback, useEffect, useRef, useState } from 'react'

import type { WorkspaceGitStatus } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const POLL_INTERVAL_MS = 15_000
const STREAM_RETRY_DELAY_MS = 8_000

interface UseGitStatusResult {
  gitStatus: WorkspaceGitStatus | null
  isLoading: boolean
  error: string | null
  refetch: () => void
}

export function useGitStatus(workspace: string): UseGitStatusResult {
  const [gitStatus, setGitStatus] = useState<WorkspaceGitStatus | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const streamRef = useRef<EventSource | null>(null)
  const pollIntervalRef = useRef<number | null>(null)
  const streamRetryTimeoutRef = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }, [])

  const stopStreamRetry = useCallback(() => {
    if (streamRetryTimeoutRef.current) {
      window.clearTimeout(streamRetryTimeoutRef.current)
      streamRetryTimeoutRef.current = null
    }
  }, [])

  const stopStreaming = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.close()
      streamRef.current = null
    }
  }, [])

  const fetchStatus = useCallback(async () => {
    if (!workspace) {
      setGitStatus(null)
      setError(null)
      setIsLoading(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(
        buildApiUrl(`/api/git/status?workspace=${encodeURIComponent(workspace)}`),
        { signal: controller.signal },
      )

      const contentType = response.headers.get('content-type') ?? ''
      if (!contentType.includes('application/json')) {
        throw new Error('Backend not available')
      }

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error((payload as { detail?: string }).detail ?? `HTTP ${response.status}`)
      }

      const data: WorkspaceGitStatus = await response.json()
      setGitStatus(data)
      setError(null)
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return
      }

      setError(err instanceof Error ? err.message : 'Failed to fetch git status')
      setGitStatus(null)
    } finally {
      setIsLoading(false)
    }
  }, [workspace])

  const startPolling = useCallback(() => {
    if (!workspace || pollIntervalRef.current) {
      return
    }

    void fetchStatus()
    pollIntervalRef.current = window.setInterval(() => {
      void fetchStatus()
    }, POLL_INTERVAL_MS)
  }, [fetchStatus, workspace])

  const scheduleStreamRetry = useCallback(() => {
    if (streamRetryTimeoutRef.current || !workspace) {
      return
    }

    streamRetryTimeoutRef.current = window.setTimeout(() => {
      streamRetryTimeoutRef.current = null
      if (!workspace) {
        return
      }

      if (typeof EventSource === 'undefined') {
        startPolling()
        return
      }

      const streamUrl = buildApiUrl(`/api/git/status/stream?workspace=${encodeURIComponent(workspace)}`)
      try {
        const source = new EventSource(streamUrl)
        streamRef.current = source
        source.onmessage = (event) => {
          if (!event.data) {
            return
          }

          try {
            const payload = JSON.parse(event.data) as WorkspaceGitStatus
            setGitStatus(payload)
            setError(null)
            setIsLoading(false)
            stopPolling()
          } catch {
            setError('Failed to parse git status stream')
          }
        }

        source.onerror = () => {
          stopStreaming()
          startPolling()
          scheduleStreamRetry()
        }
      } catch {
        startPolling()
        scheduleStreamRetry()
      }
    }, STREAM_RETRY_DELAY_MS)
  }, [startPolling, stopPolling, stopStreaming, workspace])

  const startStreaming = useCallback(() => {
    if (!workspace || typeof EventSource === 'undefined') {
      startPolling()
      return
    }

    stopStreaming()
    stopStreamRetry()
    setIsLoading(true)
    setError(null)

    const streamUrl = buildApiUrl(`/api/git/status/stream?workspace=${encodeURIComponent(workspace)}`)
    try {
      const source = new EventSource(streamUrl)
      streamRef.current = source
      source.onmessage = (event) => {
        if (!event.data) {
          return
        }

        try {
          const payload = JSON.parse(event.data) as WorkspaceGitStatus
          setGitStatus(payload)
          setError(null)
          setIsLoading(false)
          stopPolling()
        } catch {
          setError('Failed to parse git status stream')
        }
      }

      source.onerror = () => {
        stopStreaming()
        startPolling()
        scheduleStreamRetry()
      }
    } catch {
      startPolling()
      scheduleStreamRetry()
    }
  }, [scheduleStreamRetry, startPolling, stopPolling, stopStreamRetry, stopStreaming, workspace])

  useEffect(() => {
    if (!workspace) {
      abortRef.current?.abort()
      stopStreaming()
      stopPolling()
      stopStreamRetry()
      setGitStatus(null)
      setError(null)
      setIsLoading(false)
      return
    }

    startStreaming()

    return () => {
      abortRef.current?.abort()
      stopStreaming()
      stopPolling()
      stopStreamRetry()
    }
  }, [startStreaming, stopPolling, stopStreamRetry, stopStreaming, workspace])

  return { gitStatus, isLoading, error, refetch: () => void fetchStatus() }
}
