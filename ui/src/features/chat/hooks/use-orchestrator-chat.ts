import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"

import { useChatStore } from "@/features/chat/store/chat-store"
import type {
  ChatMessage,
  ChatAttachment,
  ChatStreamItem,
  OrchestratorEvent,
  OrchestratorTask,
  ChatWorkflowMode,
} from "@/features/chat/types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const apiPrefix = "/api"

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

const isMessageEventType = (eventType: string) =>
  eventType === "user_message" || eventType === "assistant_message"

const isUserMessageEvent = (eventType: string) => eventType === "user_message"

const isAssistantMessageEvent = (eventType: string) =>
  eventType === "assistant_message"

const isTaskEventType = (eventType: string) =>
  eventType === "task_created" || eventType === "task_status"

const isHiddenEventType = (eventType: string) =>
  eventType === "codex_cli_output" || eventType === "cli_run_output"

const isTurnStartEvent = (eventType: string) => eventType === "turn_started"

const isTurnEndEvent = (eventType: string) =>
  eventType === "turn_completed" ||
  eventType === "turn_cancelled" ||
  eventType === "turn_error"

const getEventMessageId = (event: OrchestratorEvent) =>
  event.id || event.created_at || `event-${Date.now()}`

const getEventKey = (event: OrchestratorEvent) =>
  event.id || `${event.created_at || ""}-${event.event_type}-${event.agent || ""}`

const mergeAttachments = (
  existing: ChatAttachment[],
  incoming: ChatAttachment[]
) => {
  const byId = new Map(existing.map((attachment) => [attachment.id, attachment]))
  incoming.forEach((attachment) => {
    byId.set(attachment.id, attachment)
  })
  return Array.from(byId.values())
}

const mapAttachmentPayload = (payload: Record<string, unknown>): ChatAttachment | null => {
  const id = String(payload.id || "").trim()
  if (!id) {
    return null
  }

  return {
    id,
    messageEventId: String(payload.message_event_id || "").trim(),
    originalName: String(payload.original_name || "attachment").trim() || "attachment",
    mimeType: String(payload.mime_type || "application/octet-stream").trim(),
    sizeBytes: Number(payload.size_bytes || 0),
    createdAt: String(payload.created_at || "").trim(),
    url: String(payload.url || "").trim(),
  }
}

const parseAttachmentEvent = (
  content: string
): { messageEventId: string; attachments: ChatAttachment[] } | null => {
  if (!content || !content.trim()) {
    return null
  }

  try {
    const payload = JSON.parse(content) as Record<string, unknown>
    const messageEventId = String(payload.message_event_id || "").trim()
    const rawAttachments = Array.isArray(payload.attachments) ? payload.attachments : []
    const attachments = rawAttachments
      .map((item) => (item && typeof item === "object" ? mapAttachmentPayload(item as Record<string, unknown>) : null))
      .filter((item): item is ChatAttachment => Boolean(item))
    if (!messageEventId || attachments.length === 0) {
      return null
    }
    return { messageEventId, attachments }
  } catch {
    return null
  }
}

const buildAttachmentMapFromEvents = (events: OrchestratorEvent[]) => {
  const attachmentsByMessageId = new Map<string, ChatAttachment[]>()

  events.forEach((event) => {
    if (event.event_type !== "user_attachments") {
      return
    }

    const parsed = parseAttachmentEvent(event.content)
    if (!parsed) {
      return
    }

    const existing = attachmentsByMessageId.get(parsed.messageEventId) || []
    attachmentsByMessageId.set(
      parsed.messageEventId,
      mergeAttachments(existing, parsed.attachments)
    )
  })

  return attachmentsByMessageId
}

const buildAttachmentMapFromRecords = (
  attachments: Array<Record<string, unknown>>
) => {
  const attachmentsByMessageId = new Map<string, ChatAttachment[]>()

  attachments.forEach((record) => {
    const mapped = mapAttachmentPayload(record)
    if (!mapped || !mapped.messageEventId) {
      return
    }
    const existing = attachmentsByMessageId.get(mapped.messageEventId) || []
    attachmentsByMessageId.set(
      mapped.messageEventId,
      mergeAttachments(existing, [mapped])
    )
  })

  return attachmentsByMessageId
}

const createLocalMessage = (text: string, attachments: ChatAttachment[] = []): ChatMessage => ({
  id: `local-${Date.now()}`,
  text,
  sender: "user",
  summary: "",
  attachments,
  agent: "You",
  role: "user",
  createdAt: new Date().toISOString(),
})

const normalizeMessageText = (value: string) =>
  String(value || "")
    .replace(/\r\n?/g, "\n")
    .trim()

const buildMessageFromEvent = (
  event: OrchestratorEvent,
  summaryById: Map<string, string>,
  summaryByCreatedAt: Map<string, string>,
  attachmentsByMessageId: Map<string, ChatAttachment[]>
): ChatMessage | null => {
  if (!event?.content) {
    return null
  }

  if (!isMessageEventType(event.event_type)) {
    return null
  }

  const isUser = isUserMessageEvent(event.event_type)
  const createdAt = event.created_at || ""
  const id = getEventMessageId(event)
  const summary =
    summaryById.get(id) || (createdAt ? summaryByCreatedAt.get(createdAt) : "") || ""

  return {
    id,
    text: normalizeMessageText(event.content),
    sender: isUser ? "user" : "agent",
    summary,
    attachments: attachmentsByMessageId.get(id) || [],
    agent: isUser ? "You" : event.agent || "Orchestrator",
    role: isUser ? "user" : "assistant",
    createdAt,
  }
}

export default function useOrchestratorChat() {
  const [isSending, setIsSending] = useState(false)
  const [statusText, setStatusText] = useState("Ready.")
  const [isThinking, setIsThinking] = useState(false)
  const [hasActiveTurn, setHasActiveTurn] = useState(false)

  const { conversationId: routeConversationId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const messages = useChatStore((state) => state.messages)
  const addMessage = useChatStore((state) => state.addMessage)
  const setMessages = useChatStore((state) => state.setMessages)
  const updateMessage = useChatStore((state) => state.updateMessage)
  const conversationId = useChatStore((state) => state.conversationId)
  const setConversationId = useChatStore((state) => state.setConversationId)
  const eventCursor = useChatStore((state) => state.eventCursor)
  const setEventCursor = useChatStore((state) => state.setEventCursor)
  const orchestratorEvents = useChatStore((state) => state.orchestratorEvents)
  const orchestratorTasks = useChatStore((state) => state.orchestratorTasks)
  const workspaceRoot = useChatStore((state) => state.workspaceRoot)
  const secondaryWorkspaceRoot = useChatStore((state) => state.secondaryWorkspaceRoot)
  const workflowMode = useChatStore((state) => state.workflowMode)
  const selectedTicketKeys = useChatStore((state) => state.selectedTicketKeys)
  const ticketDetailsByKey = useChatStore((state) => state.ticketDetailsByKey)
  const suppressUrlSync = useChatStore((state) => state.suppressUrlSync)
  const setSuppressUrlSync = useChatStore((state) => state.setSuppressUrlSync)
  const setOrchestratorEvents = useChatStore((state) => state.setOrchestratorEvents)
  const addOrchestratorEvent = useChatStore((state) => state.addOrchestratorEvent)
  const setOrchestratorTasks = useChatStore((state) => state.setOrchestratorTasks)
  const setWorkflowMode = useChatStore((state) => state.setWorkflowMode)
  const rememberWorkflowMode = useChatStore((state) => state.rememberWorkflowMode)
  const restoreWorkflowMode = useChatStore((state) => state.restoreWorkflowMode)
  const addTicket = useChatStore((state) => state.addTicket)
  const setTicketDetails = useChatStore((state) => state.setTicketDetails)
  const rememberTickets = useChatStore((state) => state.rememberTickets)
  const restoreTickets = useChatStore((state) => state.restoreTickets)
  const rememberSecondaryWorkspace = useChatStore((state) => state.rememberSecondaryWorkspace)
  const restoreSecondaryWorkspace = useChatStore((state) => state.restoreSecondaryWorkspace)

  const streamRef = useRef<EventSource | null>(null)
  const messagesRef = useRef<ChatMessage[]>(messages)
  const eventsRef = useRef<OrchestratorEvent[]>(orchestratorEvents)
  const tasksRef = useRef<OrchestratorTask[]>(orchestratorTasks)
  const restoredConversationIdRef = useRef<string | null>(null)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    eventsRef.current = orchestratorEvents
  }, [orchestratorEvents])

  useEffect(() => {
    tasksRef.current = orchestratorTasks
  }, [orchestratorTasks])

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.close()
        streamRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!conversationId && streamRef.current) {
      streamRef.current.close()
      streamRef.current = null
    }

    if (!conversationId) {
      restoredConversationIdRef.current = null
      setHasActiveTurn(false)
      setIsThinking(false)
      setIsSending(false)
      setStatusText("Ready.")
    }
    restoreWorkflowMode(conversationId)
    restoreTickets(conversationId)
    restoreSecondaryWorkspace(conversationId)
  }, [conversationId, restoreSecondaryWorkspace, restoreTickets, restoreWorkflowMode])

  useEffect(() => {
    if (!workspaceRoot.trim() || selectedTicketKeys.length === 0) {
      return
    }

    let cancelled = false
    const loadMissing = async () => {
      for (const ticketKey of selectedTicketKeys) {
        if (ticketDetailsByKey[ticketKey]) {
          continue
        }
        try {
          const response = await fetch(
            buildApiUrl(
              `${apiPrefix}/tickets/${encodeURIComponent(ticketKey)}?workspace_root=${encodeURIComponent(
                workspaceRoot.trim()
              )}`
            )
          )
          if (!response.ok) {
            continue
          }
          const data = await response.json()
          if (cancelled) {
            return
          }
          if (data && data.ticket_key) {
            setTicketDetails({
              ticket_key: String(data.ticket_key),
              title: String(data.title || data.ticket_key),
              status: String(data.status || ""),
              priority: String(data.priority || ""),
              url: String(data.url || ""),
              ticket: (data.ticket || {}) as Record<string, unknown>,
              ticket_context: (data.ticket_context || {}) as Record<string, unknown>,
            })
          }
        } catch {
          continue
        }
      }
    }

    void loadMissing()
    return () => {
      cancelled = true
    }
  }, [selectedTicketKeys, setTicketDetails, ticketDetailsByKey, workspaceRoot])

  useEffect(() => {
    if (!conversationId) {
      return
    }
    rememberTickets(conversationId)
    rememberSecondaryWorkspace(conversationId)
  }, [
    conversationId,
    rememberSecondaryWorkspace,
    rememberTickets,
    secondaryWorkspaceRoot,
    selectedTicketKeys,
    ticketDetailsByKey,
  ])

  const updateWorkflowMode = (nextWorkflowMode: ChatWorkflowMode) => {
    setWorkflowMode(nextWorkflowMode)
    if (conversationId) {
      rememberWorkflowMode(conversationId, nextWorkflowMode)
    }
  }

  const replaceLocalUserMessage = (event: OrchestratorEvent) => {
    if (!isUserMessageEvent(event.event_type)) {
      return false
    }

    const normalizedEventText = normalizeMessageText(event.content)
    const index = messagesRef.current.findIndex(
      (message) =>
        message.sender === "user" &&
        message.id.startsWith("local-") &&
        normalizeMessageText(message.text) === normalizedEventText
    )

    if (index === -1) {
      return false
    }

    const nextMessages = [...messagesRef.current]
    const existing = nextMessages[index]
    nextMessages[index] = {
      ...existing,
      id: getEventMessageId(event),
      createdAt: event.created_at || existing.createdAt,
      text: normalizedEventText,
    }
    messagesRef.current = nextMessages
    setMessages(nextMessages)

    return true
  }

  const addMessageFromEvent = (event: OrchestratorEvent) => {
    if (!isMessageEventType(event.event_type)) {
      return
    }

    if (replaceLocalUserMessage(event)) {
      return
    }

    const messageId = getEventMessageId(event)
    const exists = messagesRef.current.some((existing) => existing.id === messageId)

    if (exists) {
      return
    }

    const summaryById = new Map(
      messagesRef.current.map((message) => [message.id, message.summary])
    )
    const summaryByCreatedAt = new Map(
      messagesRef.current
        .filter((message) => message.createdAt)
        .map((message) => [message.createdAt as string, message.summary])
    )
    const attachmentsByMessageId = buildAttachmentMapFromEvents(eventsRef.current)
    const mapped = buildMessageFromEvent(
      event,
      summaryById,
      summaryByCreatedAt,
      attachmentsByMessageId
    )

    if (mapped) {
      messagesRef.current = [...messagesRef.current, mapped]
      addMessage(mapped)
    }
  }

  const addEventIfMissing = (event: OrchestratorEvent) => {
    const exists = eventsRef.current.some(
      (existingEvent) => getEventKey(existingEvent) === getEventKey(event)
    )

    if (!exists) {
      addOrchestratorEvent(event)
    }
  }

  const applyTaskEvent = (event: OrchestratorEvent) => {
    if (!isTaskEventType(event.event_type)) {
      return false
    }

    if (!event.content) {
      return false
    }

    try {
      const payload = JSON.parse(event.content)

      if (event.event_type === "task_created") {
        const task = payload?.id ? payload : payload?.task

        if (!task?.id) {
          return false
        }

        const next = [...tasksRef.current]
        const index = next.findIndex((existing) => existing.id === task.id)

        if (index >= 0) {
          next[index] = { ...next[index], ...task }
        } else {
          next.push(task)
        }

        setOrchestratorTasks(next)

        return true
      }

      if (event.event_type === "task_status") {
        const taskId = payload?.task_id || payload?.id
        const status = payload?.status

        if (!taskId || !status) {
          return false
        }

        const next = [...tasksRef.current]
        const index = next.findIndex((existing) => existing.id === taskId)

        if (index >= 0) {
          next[index] = { ...next[index], status }
        } else {
          next.push({
            id: taskId,
            title: payload?.title || "Task",
            details: "",
            owner_agent: payload?.owner_agent || "Agent",
            status,
          })
        }

        setOrchestratorTasks(next)

        return true
      }
    } catch {
      return false
    }

    return false
  }

  const applyTicketEvent = (event: OrchestratorEvent) => {
    if (!event.content) {
      return
    }

    if (event.event_type === "jira_action") {
      try {
        const payload = JSON.parse(event.content) as Record<string, unknown>
        const keys = [
          ...((Array.isArray(payload.issue_keys) ? payload.issue_keys : []) as unknown[]),
          ...((Array.isArray(payload.updated_issue_keys) ? payload.updated_issue_keys : []) as unknown[]),
          payload.issue_key,
        ]
          .map((item) => String(item || "").trim().toUpperCase())
          .filter((item) => Boolean(item))

        keys.forEach((key) => addTicket(key))
      } catch {
        return
      }
      return
    }

    if (event.event_type === "selected_tickets" || event.event_type === "ticket_context_selected") {
      try {
        const payload = JSON.parse(event.content) as Record<string, unknown>
        const keys = (Array.isArray(payload.selected_ticket_keys) ? payload.selected_ticket_keys : [])
          .map((item) => String(item || "").trim().toUpperCase())
          .filter((item) => Boolean(item))
        keys.forEach((key) => addTicket(key))
      } catch {
        return
      }
    }
  }

  const openStream = (activeConversationId: string, cursor: string | null) => {
    if (streamRef.current) {
      streamRef.current.close()
    }

    const streamUrl = buildApiUrl(`${apiPrefix}/orchestrator/stream/${activeConversationId}`)
    const url = new URL(streamUrl, window.location.origin)

    if (cursor) {
      url.searchParams.set("since", cursor)
    }

    const stream = new EventSource(url.toString())
    streamRef.current = stream

    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)

        if (payload.created_at) {
          setEventCursor(payload.created_at)
        }

        const taskApplied = applyTaskEvent(payload)
        addEventIfMissing(payload)
        applyTicketEvent(payload)

        if (taskApplied) {
          return
        }

        addMessageFromEvent(payload)

        if (isTurnStartEvent(payload.event_type)) {
          setHasActiveTurn(true)
          setIsThinking(true)
          setStatusText("Orchestrator is coordinating...")
        }

        if (isTurnEndEvent(payload.event_type)) {
          setHasActiveTurn(false)
          setIsThinking(false)
          setIsSending(false)
          setStatusText("Ready.")
        }

        if (isAssistantMessageEvent(payload.event_type)) {
          setIsThinking(false)
        }
      } catch {
        return
      }
    }

    stream.onerror = () => {
      setStatusText("Connection interrupted. Retrying...")
    }
  }

  const loadOrchestratorState = async (activeConversationId: string) => {
    const response = await fetch(buildApiUrl(`${apiPrefix}/orchestrator/${activeConversationId}`))

    if (!response.ok) {
      return null
    }

    const data = await response.json()
    const events = Array.isArray(data.events) ? (data.events as OrchestratorEvent[]) : []
    const attachmentRecords = Array.isArray(data.attachments)
      ? (data.attachments as Array<Record<string, unknown>>)
      : []
    const tasks = Array.isArray(data.tasks) ? (data.tasks as OrchestratorTask[]) : []

    if (events.length > 0) {
      setOrchestratorEvents(events)
      events.forEach((event) => applyTicketEvent(event))

      const summaryById = new Map(
        messagesRef.current.map((message) => [message.id, message.summary])
      )
      const summaryByCreatedAt = new Map(
        messagesRef.current
          .filter((message) => message.createdAt)
          .map((message) => [message.createdAt as string, message.summary])
      )
      const attachmentsByMessageId = buildAttachmentMapFromEvents(events)
      const persistedAttachmentsByMessageId = buildAttachmentMapFromRecords(
        attachmentRecords
      )
      persistedAttachmentsByMessageId.forEach((value, key) => {
        const existing = attachmentsByMessageId.get(key) || []
        attachmentsByMessageId.set(key, mergeAttachments(existing, value))
      })
      const mappedMessages = events
        .map((event) =>
          buildMessageFromEvent(
            event,
            summaryById,
            summaryByCreatedAt,
            attachmentsByMessageId
          )
        )
        .filter((message): message is ChatMessage => Boolean(message))

      setMessages(mappedMessages)
    }

    if (tasks.length > 0) {
      setOrchestratorTasks(tasks)
    } else {
      setOrchestratorTasks([])
    }

    if (events.length > 0) {
      const lastEvent = events[events.length - 1]

      if (lastEvent?.created_at) {
        setEventCursor(lastEvent.created_at)
      }

      let turnIsActive = false

      events.forEach((event) => {
        if (isTurnStartEvent(event.event_type)) {
          turnIsActive = true
        } else if (isTurnEndEvent(event.event_type)) {
          turnIsActive = false
        }
      })

      setHasActiveTurn(turnIsActive)
      setIsThinking(turnIsActive)

      return lastEvent?.created_at || null
    }

    setHasActiveTurn(false)
    setIsThinking(false)

    return null
  }

  const restoreConversation = async (activeConversationId: string) => {
    setStatusText("Restoring conversation...")
    const latestCursor = await loadOrchestratorState(activeConversationId)
    openStream(activeConversationId, latestCursor || eventCursor)
    setStatusText("Ready.")
  }

  useEffect(() => {
    const nextConversationId = routeConversationId || null

    if (suppressUrlSync) {
      if (location.pathname !== "/chat" && location.pathname !== "/") {
        navigate("/chat", { replace: true })
        return
      }

      setSuppressUrlSync(false)

      return
    }

    if (nextConversationId && nextConversationId !== conversationId) {
      if (conversationId) {
        rememberTickets(conversationId)
        rememberSecondaryWorkspace(conversationId)
      }
      setConversationId(nextConversationId)
      setEventCursor(null)
      setMessages([])
      setOrchestratorEvents([])
      setOrchestratorTasks([])
    }
  }, [
    conversationId,
    location.pathname,
    navigate,
    rememberSecondaryWorkspace,
    routeConversationId,
    rememberTickets,
    setConversationId,
    setEventCursor,
    setMessages,
    setOrchestratorEvents,
    setOrchestratorTasks,
    setSuppressUrlSync,
    suppressUrlSync,
  ])

  useEffect(() => {
    if (suppressUrlSync) {
      return
    }

    if (!conversationId) {
      if (location.pathname !== "/chat" && location.pathname !== "/") {
        navigate("/chat", { replace: true })
      }

      return
    }

    const targetPath = `/chat/${conversationId}`

    if (location.pathname !== targetPath) {
      navigate(targetPath, { replace: true })
    }
  }, [conversationId, location.pathname, navigate, suppressUrlSync])

  useEffect(() => {
    if (!conversationId) {
      return
    }

    if (restoredConversationIdRef.current === conversationId) {
      return
    }

    restoredConversationIdRef.current = conversationId
    restoreConversation(conversationId)
    // Restore exactly once per conversation ID.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId])

  const sendMessage = async (text: string, files: File[] = []) => {
    const userMessageText = text.trim()

    if (!userMessageText) {
      return false
    }

    setIsSending(true)
    setIsThinking(true)
    setHasActiveTurn(true)
    setStatusText("Orchestrator is coordinating...")

    const newUserMessage = createLocalMessage(userMessageText)
    messagesRef.current = [...messagesRef.current, newUserMessage]
    addMessage(newUserMessage)

    try {
      const formData = new FormData()
      formData.append("message", userMessageText)
      if (conversationId) {
        formData.append("conversation_id", conversationId)
      }
      if (workspaceRoot && workspaceRoot.trim().length > 0) {
        formData.append("workspace_root", workspaceRoot.trim())
      }
      if (secondaryWorkspaceRoot && secondaryWorkspaceRoot.trim().length > 0) {
        formData.append("secondary_workspace_root", secondaryWorkspaceRoot.trim())
      }
      formData.append("workflow_mode", workflowMode)
      formData.append("selected_ticket_keys", JSON.stringify(selectedTicketKeys))
      files.forEach((file) => {
        formData.append("files", file, file.name)
      })

      const response = await fetch(buildApiUrl(`${apiPrefix}/orchestrator/submit`), {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`)
      }

      const data = await response.json()
      const nextConversationId = data.conversation_id as string
      const uploadedAttachments = Array.isArray(data.uploaded_attachments)
        ? (data.uploaded_attachments as Array<Record<string, unknown>>)
        : []
      const mappedUploadedAttachments = uploadedAttachments
        .map((item) => mapAttachmentPayload(item))
        .filter((item): item is ChatAttachment => Boolean(item))
      const newUserMessageWithAttachments =
        mappedUploadedAttachments.length > 0
          ? { ...newUserMessage, attachments: mappedUploadedAttachments }
          : newUserMessage

      if (mappedUploadedAttachments.length > 0) {
        updateMessage(newUserMessage.id, { attachments: mappedUploadedAttachments })
      }

      if (nextConversationId && nextConversationId !== conversationId) {
        rememberWorkflowMode(nextConversationId, workflowMode)
        rememberTickets(nextConversationId)
        rememberSecondaryWorkspace(nextConversationId)
        setConversationId(nextConversationId)
        setEventCursor(null)
        setMessages([newUserMessageWithAttachments])
        messagesRef.current = [newUserMessageWithAttachments]
        setOrchestratorEvents([])
        setOrchestratorTasks([])
      }

      if (nextConversationId && nextConversationId === conversationId) {
        rememberTickets(nextConversationId)
        rememberSecondaryWorkspace(nextConversationId)
        openStream(nextConversationId, eventCursor)
      }

      setStatusText("Waiting for agents...")
      return true
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected error"
      setStatusText(`Error: ${message}`)
      setIsThinking(false)
      setHasActiveTurn(false)
      return false
    } finally {
      setIsSending(false)
    }
  }

  const stopExecution = async () => {
    if (!conversationId) {
      return
    }

    setStatusText("Stopping agents...")

    try {
      const response = await fetch(buildApiUrl(`${apiPrefix}/orchestrator/stop`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ conversation_id: conversationId }),
      })

      if (!response.ok) {
        throw new Error(`Stop failed (${response.status})`)
      }

      setStatusText("Stopped.")
      setHasActiveTurn(false)
      setIsThinking(false)
      setIsSending(false)
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unexpected stop error"
      setStatusText(`Error: ${message}`)
    }
  }

  const updateMessageSummary = (messageId: string, summary: string) => {
    updateMessage(messageId, { summary })
  }

  const streamItems = useMemo<ChatStreamItem[]>(() => {
    const summaryById = new Map(messages.map((message) => [message.id, message.summary]))
    const summaryByCreatedAt = new Map(
      messages
        .filter((message) => message.createdAt)
        .map((message) => [message.createdAt as string, message.summary])
    )
    const attachmentsByMessageId = buildAttachmentMapFromEvents(orchestratorEvents)
    const messageById = new Map(messages.map((message) => [message.id, message]))
    const messageByCreatedAt = new Map(
      messages
        .filter((message) => message.createdAt)
        .map((message) => [message.createdAt as string, message])
    )

    const items: ChatStreamItem[] = []
    let buffer: OrchestratorEvent[] = []

    const flushThinking = () => {
      if (buffer.length > 0) {
        items.push({ type: "thinking", events: buffer })
        buffer = []
      }
    }

    orchestratorEvents.forEach((event) => {
      if (isHiddenEventType(event.event_type)) {
        return
      }

      if (event.event_type === "turn_completed") {
        return
      }

      if (isMessageEventType(event.event_type)) {
        flushThinking()

        const messageId = getEventMessageId(event)
        const existing =
          messageById.get(messageId) ||
          (event.created_at ? messageByCreatedAt.get(event.created_at) : undefined)
        const mapped =
          existing ||
          buildMessageFromEvent(
            event,
            summaryById,
            summaryByCreatedAt,
            attachmentsByMessageId
          )

        if (mapped) {
          items.push({ type: "message", message: mapped })
        }

        return
      }

      buffer.push(event)
    })

    flushThinking()

    const knownMessageIds = new Set(
      items
        .filter((item) => item.type === "message")
        .map((item) => item.message.id)
    )
    const pendingLocalMessages = messages
      .filter((message) => message.id.startsWith("local-") && !knownMessageIds.has(message.id))
      .sort((a, b) => {
        const aTime = a.createdAt ? Date.parse(a.createdAt) : 0
        const bTime = b.createdAt ? Date.parse(b.createdAt) : 0

        return aTime - bTime
      })

    pendingLocalMessages.forEach((message) => {
      items.push({ type: "message", message })
    })

    const hasThinkingItem = items.some((item) => item.type === "thinking")

    if (orchestratorTasks.length > 0 && !hasThinkingItem) {
      items.push({ type: "thinking", events: [] })
    }

    if (isThinking && (items.length === 0 || items[items.length - 1].type === "message")) {
      items.push({ type: "thinking", events: [] })
    }

    return items
  }, [isThinking, messages, orchestratorEvents, orchestratorTasks.length])

  const messageCount = useMemo(
    () => streamItems.filter((item) => item.type === "message").length,
    [streamItems]
  )

  return {
    streamItems,
    messageCount,
    isSending,
    hasActiveTurn,
    statusText,
    isThinking,
    orchestratorEvents,
    orchestratorTasks,
    workflowMode,
    updateWorkflowMode,
    sendMessage,
    stopExecution,
    updateMessageSummary,
  }
}
