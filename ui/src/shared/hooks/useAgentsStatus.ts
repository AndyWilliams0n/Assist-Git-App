import { useEffect, useMemo, useState } from "react"

import type { AgentsSnapshot } from "@/shared/types/agents"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

const REFRESH_INTERVAL_MS = 5000
const STREAM_RETRY_DELAY_MS = 10000
const apiPrefix = "/api"

type AgentsStatusMode = "streaming" | "polling"

type AgentsStatusStore = {
  snapshot: AgentsSnapshot | null
  isLoading: boolean
  error: string | null
  mode: AgentsStatusMode
}

const listeners = new Set<(state: AgentsStatusStore) => void>()

let store: AgentsStatusStore = {
  snapshot: null,
  isLoading: true,
  error: null,
  mode: "polling",
}

let subscriberCount = 0
let pollIntervalId: number | null = null
let streamRetryTimeoutId: number | null = null
let eventSource: EventSource | null = null

function emit() {
  for (const listener of listeners) {
    listener(store)
  }
}

function setStore(next: Partial<AgentsStatusStore>) {
  store = { ...store, ...next }
  emit()
}

async function fetchSnapshot() {
  const response = await fetch(buildApiUrl(`${apiPrefix}/agents`))

  if (!response.ok) {
    throw new Error("Failed to fetch agent status")
  }

  return response.json() as Promise<AgentsSnapshot>
}

function applySnapshot(data: AgentsSnapshot) {
  setStore({
    snapshot: data,
    isLoading: false,
    error: null,
  })
}

function clearPolling() {
  if (pollIntervalId) {
    window.clearInterval(pollIntervalId)
    pollIntervalId = null
  }
}

function clearStreamRetry() {
  if (streamRetryTimeoutId) {
    window.clearTimeout(streamRetryTimeoutId)
    streamRetryTimeoutId = null
  }
}

function closeStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

async function refreshPollingSnapshot() {
  try {
    const data = await fetchSnapshot()
    applySnapshot(data)
  } catch (err) {
    setStore({
      error: err instanceof Error ? err.message : "Failed to load agents",
      isLoading: false,
    })
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

function startPolling() {
  if (pollIntervalId) {
    return
  }

  setStore({ mode: "polling" })
  void refreshPollingSnapshot()
  pollIntervalId = window.setInterval(() => {
    void refreshPollingSnapshot()
  }, REFRESH_INTERVAL_MS)
}

function stopPollingIfStreaming() {
  if (eventSource) {
    clearPolling()
  }
}

function startStreaming() {
  if (eventSource || subscriberCount <= 0) {
    return
  }

  clearStreamRetry()

  try {
    const source = new EventSource(buildApiUrl(`${apiPrefix}/agents/stream`))
    eventSource = source
    setStore({ mode: "streaming" })

    source.onmessage = (event) => {
      if (!event.data) {
        return
      }

      try {
        const data = JSON.parse(event.data) as AgentsSnapshot
        applySnapshot(data)
        stopPollingIfStreaming()
      } catch (parseError) {
        setStore({
          error:
            parseError instanceof Error
              ? parseError.message
              : "Failed to parse agent stream",
        })
      }
    }

    source.onerror = () => {
      closeStream()
      if (subscriberCount > 0) {
        startPolling()
        scheduleStreamRetry()
      }
    }

    void fetchSnapshot()
      .then((data) => {
        applySnapshot(data)
      })
      .catch(() => {
        if (subscriberCount > 0) {
          startPolling()
          scheduleStreamRetry()
        }
      })
  } catch {
    startPolling()
    scheduleStreamRetry()
  }
}

function ensureStarted() {
  if (subscriberCount <= 0) {
    return
  }

  if (!store.snapshot && !store.error) {
    setStore({ isLoading: true })
  }

  startStreaming()
}

function teardownIfUnused() {
  if (subscriberCount > 0) {
    return
  }

  closeStream()
  clearPolling()
  clearStreamRetry()
}

export default function useAgentsStatus() {
  const [state, setState] = useState(store)

  useEffect(() => {
    const listener = (next: AgentsStatusStore) => {
      setState(next)
    }

    listeners.add(listener)
    subscriberCount += 1
    setState(store)
    ensureStarted()

    return () => {
      listeners.delete(listener)
      subscriberCount = Math.max(0, subscriberCount - 1)
      teardownIfUnused()
    }
  }, [])

  const agents = useMemo(() => state.snapshot?.agents ?? [], [state.snapshot?.agents])
  const bypass = useMemo(
    () => ({
      jiraApi:
        Boolean(state.snapshot?.bypass?.jira_api_bypass) ||
        Boolean(
          agents.find((agent) => (agent.role || "").toLowerCase() === "jira_api")?.bypassed
        ),
      sddSpec:
        Boolean(state.snapshot?.bypass?.sdd_spec_bypass) ||
        Boolean(
          agents.find((agent) => (agent.role || "").toLowerCase() === "sdd_spec")?.bypassed
        ),
      codeBuilder:
        Boolean(state.snapshot?.bypass?.code_builder_bypass) ||
        Boolean(
          agents.find((agent) => (agent.role || "").toLowerCase() === "code_builder")?.bypassed
        ),
      codeReview:
        Boolean(state.snapshot?.bypass?.code_review_bypass) ||
        Boolean(
          agents.find((agent) => (agent.role || "").toLowerCase() === "code_review")?.bypassed
        ),
    }),
    [
      agents,
      state.snapshot?.bypass?.jira_api_bypass,
      state.snapshot?.bypass?.sdd_spec_bypass,
      state.snapshot?.bypass?.code_builder_bypass,
      state.snapshot?.bypass?.code_review_bypass,
    ]
  )

  return {
    snapshot: state.snapshot,
    agents,
    bypass,
    isLoading: state.isLoading,
    error: state.error,
    mode: state.mode,
  }
}
