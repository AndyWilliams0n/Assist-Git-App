import { useEffect, useState } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

const STREAM_RETRY_DELAY_MS = 10000

type ConnectionStatus = 'connected' | 'disconnected' | 'unknown'

type ConnectionStatusStore = {
  status: ConnectionStatus
}

const listeners = new Set<(state: ConnectionStatusStore) => void>()

let store: ConnectionStatusStore = {
  status: 'unknown',
}

let subscriberCount = 0
let eventSource: EventSource | null = null
let streamRetryTimeoutId: number | null = null

function emit() {
  for (const listener of listeners) {
    listener(store)
  }
}

function setStore(next: Partial<ConnectionStatusStore>) {
  store = { ...store, ...next }
  emit()
}

function closeStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function clearStreamRetry() {
  if (streamRetryTimeoutId) {
    window.clearTimeout(streamRetryTimeoutId)
    streamRetryTimeoutId = null
  }
}

function scheduleStreamRetry() {
  if (streamRetryTimeoutId || subscriberCount <= 0) {
    return
  }

  streamRetryTimeoutId = window.setTimeout(() => {
    streamRetryTimeoutId = null

    if (subscriberCount > 0) {
      startStreaming()
    }
  }, STREAM_RETRY_DELAY_MS)
}

function startStreaming() {
  if (eventSource || subscriberCount <= 0) {
    return
  }

  clearStreamRetry()

  try {
    const source = new EventSource(buildApiUrl('/api/connection/stream'))
    eventSource = source

    source.onmessage = (event) => {
      if (!event.data || event.data.startsWith(':')) {
        return
      }

      try {
        const data = JSON.parse(event.data) as { connected: boolean }
        setStore({ status: data.connected ? 'connected' : 'disconnected' })
      } catch {
        // ignore parse errors
      }
    }

    source.onerror = () => {
      closeStream()

      if (subscriberCount > 0) {
        scheduleStreamRetry()
      }
    }
  } catch {
    scheduleStreamRetry()
  }
}

function teardownIfUnused() {
  if (subscriberCount > 0) {
    return
  }

  closeStream()
  clearStreamRetry()
}

export default function useConnectionStatus() {
  const [state, setState] = useState(store)

  useEffect(() => {
    const listener = (next: ConnectionStatusStore) => {
      setState(next)
    }

    listeners.add(listener)
    subscriberCount += 1
    setState(store)
    startStreaming()

    return () => {
      listeners.delete(listener)
      subscriberCount = Math.max(0, subscriberCount - 1)
      teardownIfUnused()
    }
  }, [])

  return { status: state.status }
}
