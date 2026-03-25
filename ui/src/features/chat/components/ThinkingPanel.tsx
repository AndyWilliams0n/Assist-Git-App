import { useEffect, useMemo, useState } from "react"

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtItem,
  ChainOfThoughtStep,
  ChainOfThoughtTrigger,
} from "@/shared/components/prompt-kit/chain-of-thought"
import {
  Steps,
  StepsContent,
  StepsItem,
  StepsTrigger,
} from "@/shared/components/prompt-kit/steps"
import { TextShimmer } from "@/shared/components/prompt-kit/text-shimmer"
import { Tool } from "@/shared/components/prompt-kit/tool"
import type { ToolPart } from "@/shared/components/prompt-kit/tool"
import type {
  OrchestratorEvent,
  OrchestratorTask,
} from "@/features/chat/types"

type TimelineTone = "neutral" | "info" | "success" | "error"

type TimelineItem = {
  id: string
  title: string
  detail: string
  tone: TimelineTone
  timestamp: string
  toolPart?: ToolPart
}

type ThinkingPanelProps = {
  events: OrchestratorEvent[]
  tasks: OrchestratorTask[]
  isThinking: boolean
  statusText: string
}

const statusToneClassByTone: Record<TimelineTone, string> = {
  neutral: "text-muted-foreground",
  info: "text-blue-500",
  success: "text-green-500",
  error: "text-red-500",
}

const parseJson = (value: string): Record<string, unknown> | null => {
  try {
    const parsed = JSON.parse(value)

    if (parsed && typeof parsed === "object") {
      return parsed as Record<string, unknown>
    }
  } catch {
    return null
  }

  return null
}

const singleLine = (value: string, maxChars = 180) => {
  const normalized = (value || "")
    .replace(/\s+/g, " ")
    .replace(/```[\s\S]*?```/g, "[code]")
    .trim()

  if (!normalized) {
    return ""
  }

  if (normalized.length <= maxChars) {
    return normalized
  }

  return `${normalized.slice(0, maxChars)}...`
}

const formatTimestamp = (value?: string) => {
  if (!value) {
    return ""
  }

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleTimeString()
}

const toTitleCase = (value: string) =>
  value
    .split("_")
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ")

const resolveTaskTitle = (
  taskId: string | undefined,
  tasksById: Map<string, OrchestratorTask>
) => {
  if (!taskId) {
    return "Task"
  }

  const taskTitle = tasksById.get(taskId)?.title

  if (taskTitle) {
    return taskTitle
  }

  return `Task ${taskId.slice(0, 8)}`
}

const parseToolPart = (event: OrchestratorEvent): ToolPart | null => {
  const eventType = event.event_type || ""

  if (!eventType.includes("tool")) {
    return null
  }

  const payload = parseJson(event.content || "")

  if (!payload) {
    return {
      type: eventType,
      state: "output-available",
      output: { raw: event.content },
    }
  }

  const payloadState = String(payload.state || payload.status || "").toLowerCase()
  let state: ToolPart["state"] = "input-available"

  if (payloadState.includes("stream") || payloadState.includes("running")) {
    state = "input-streaming"
  } else if (payloadState.includes("error") || payloadState.includes("fail")) {
    state = "output-error"
  } else if (payloadState.includes("done") || payloadState.includes("success")) {
    state = "output-available"
  }

  return {
    type: String(payload.tool || payload.name || eventType),
    state,
    input:
      payload.input && typeof payload.input === "object"
        ? (payload.input as Record<string, unknown>)
        : undefined,
    output:
      payload.output && typeof payload.output === "object"
        ? (payload.output as Record<string, unknown>)
        : undefined,
    toolCallId: payload.call_id ? String(payload.call_id) : undefined,
    errorText: payload.error ? String(payload.error) : undefined,
  }
}

const normalizeEvent = (
  event: OrchestratorEvent,
  index: number,
  tasksById: Map<string, OrchestratorTask>
): TimelineItem | null => {
  const eventType = event.event_type || ""

  if (!eventType || eventType === "assistant_message" || eventType === "user_message") {
    return null
  }

  const payload = parseJson(event.content || "")
  const eventId = event.id || `${event.created_at || "event"}-${eventType}-${index}`
  const timestamp = formatTimestamp(event.created_at)

  if (eventType === "turn_started") {
    return {
      id: eventId,
      title: "Turn started",
      detail: "Orchestrator started coordinating agents.",
      tone: "info",
      timestamp,
    }
  }

  if (eventType === "turn_completed") {
    return {
      id: eventId,
      title: "Turn completed",
      detail: "All active tasks for this turn have completed.",
      tone: "success",
      timestamp,
    }
  }

  if (eventType === "workflow_selected") {
    const intent = String(payload?.intent || "unknown")
    const reason = singleLine(String(payload?.reason || ""))

    return {
      id: eventId,
      title: `Intent routed: ${intent}`,
      detail: reason,
      tone: "info",
      timestamp,
    }
  }

  if (eventType === "task_created") {
    const title = String(payload?.title || resolveTaskTitle(event.task_id || undefined, tasksById))

    return {
      id: eventId,
      title: `Task created: ${title}`,
      detail: singleLine(String(payload?.details || "")),
      tone: "neutral",
      timestamp,
    }
  }

  if (eventType === "task_status") {
    const status = String(payload?.status || "").toLowerCase()
    const taskId = String(payload?.task_id || event.task_id || "")
    const taskTitle = resolveTaskTitle(taskId, tasksById)

    let tone: TimelineTone = "neutral"

    if (status === "done") {
      tone = "success"
    } else if (status === "blocked") {
      tone = "error"
    } else if (status === "in_progress") {
      tone = "info"
    }

    return {
      id: eventId,
      title: `Task ${status || "updated"}: ${taskTitle}`,
      detail: "",
      tone,
      timestamp,
    }
  }

  if (eventType === "turn_error") {
    return {
      id: eventId,
      title: "Run failed",
      detail: singleLine(event.content),
      tone: "error",
      timestamp,
    }
  }

  const toolPart = parseToolPart(event)

  return {
    id: eventId,
    title: toTitleCase(eventType),
    detail: singleLine(event.content),
    tone: "neutral",
    timestamp,
    toolPart: toolPart || undefined,
  }
}

export function ThinkingPanel({
  events,
  tasks,
  isThinking,
  statusText,
}: ThinkingPanelProps) {
  const [isPanelOpen, setIsPanelOpen] = useState(isThinking)

  const tasksById = useMemo(() => {
    const map = new Map<string, OrchestratorTask>()

    tasks.forEach((task) => {
      if (task.id) {
        map.set(task.id, task)
      }
    })

    return map
  }, [tasks])

  const timelineItems = useMemo(
    () =>
      events
        .map((event, index) => normalizeEvent(event, index, tasksById))
        .filter((item): item is TimelineItem => Boolean(item)),
    [events, tasksById]
  )

  useEffect(() => {
    if (isThinking) {
      setIsPanelOpen(true)
    }
  }, [isThinking])

  return (
    <div className="w-full max-w-4xl">
      <Steps open={isPanelOpen} onOpenChange={setIsPanelOpen} className="w-full">
        <StepsTrigger className="mb-2">
          <TextShimmer active={isThinking}>
            {isThinking ? "Thinking..." : "View thinking process"}
          </TextShimmer>
        </StepsTrigger>

        <StepsContent>
          {timelineItems.length === 0 ? (
            <StepsItem>
              {statusText || "Orchestrator is coordinating..."}
            </StepsItem>
          ) : (
            <ChainOfThought className="space-y-2">
              {timelineItems.map((item) => (
                <ChainOfThoughtStep key={item.id}>
                  <ChainOfThoughtTrigger
                    leftIcon={<span className={statusToneClassByTone[item.tone]}>•</span>}
                  >
                    {item.title}
                  </ChainOfThoughtTrigger>

                  <ChainOfThoughtContent>
                    <ChainOfThoughtItem className="rounded-lg border p-3">
                      {item.detail ? <p className="mb-2">{item.detail}</p> : null}
                      <p className="text-xs">{item.timestamp}</p>
                      {item.toolPart ? <Tool toolPart={item.toolPart} /> : null}
                    </ChainOfThoughtItem>
                  </ChainOfThoughtContent>
                </ChainOfThoughtStep>
              ))}
            </ChainOfThought>
          )}
        </StepsContent>
      </Steps>
    </div>
  )
}
