import { useEffect, useState } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

const STREAM_RETRY_DELAY_MS = 5000

export type LogLevel = 'info' | 'warn' | 'warning' | 'error' | 'debug'

export type PipelineLog = {
  id: string
  task_id: string
  run_id: string
  jira_key: string
  level: LogLevel
  message: string
  created_at: string
}

type AgentLogsState = {
  logs: PipelineLog[]
  connected: boolean
  error: string | null
}

export default function useAgentLogs() {
  const [state, setState] = useState<AgentLogsState>({
    logs: [],
    connected: false,
    error: null,
  })

  useEffect(() => {
    let eventSource: EventSource | null = null
    let retryTimeout: number | null = null
    let cancelled = false

    function connect() {
      if (cancelled) return

      eventSource = new EventSource(buildApiUrl('/api/logs/stream'))

      eventSource.onopen = () => {
        if (cancelled) return

        setState((prev) => ({ ...prev, connected: true, error: null }))
      }

      eventSource.onmessage = (event) => {
        if (cancelled || !event.data) return

        try {
          const parsed = JSON.parse(event.data) as
            | { type: 'history'; logs: PipelineLog[] }
            | { type: 'log'; log: PipelineLog }

          if (parsed.type === 'history') {
            setState((prev) => ({
              ...prev,
              logs: parsed.logs,
              connected: true,
              error: null,
            }))
          } else if (parsed.type === 'log') {
            setState((prev) => ({
              ...prev,
              logs: [...prev.logs, parsed.log],
            }))
          }
        } catch {
          // Ignore malformed events
        }
      }

      eventSource.onerror = () => {
        if (cancelled) return

        eventSource?.close()
        eventSource = null
        setState((prev) => ({
          ...prev,
          connected: false,
          error: 'Stream disconnected. Reconnecting...',
        }))

        retryTimeout = window.setTimeout(() => {
          retryTimeout = null

          if (!cancelled) {
            connect()
          }
        }, STREAM_RETRY_DELAY_MS)
      }
    }

    connect()

    return () => {
      cancelled = true

      if (retryTimeout) {
        window.clearTimeout(retryTimeout)
      }

      eventSource?.close()
    }
  }, [])

  function clear() {
    setState((prev) => ({ ...prev, logs: [] }))
  }

  return {
    logs: state.logs,
    connected: state.connected,
    error: state.error,
    clear,
  }
}
