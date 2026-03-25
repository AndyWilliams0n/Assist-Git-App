import { useMemo } from "react"

import type { WorkflowTask } from "@/features/workflow-tasks/types"

const priorityScore = (value?: string) => {
  const text = (value || "").trim().toLowerCase()
  if (!text) return 0
  if (text.includes("highest") || text.includes("blocker") || text.includes("critical") || text.includes("p0")) return 700
  if (text.includes("high") || text.includes("p1")) return 600
  if (text.includes("medium") || text.includes("normal") || text.includes("p2")) return 500
  if (text.includes("low") || text.includes("p3")) return 400
  if (text.includes("lowest") || text.includes("minor") || text.includes("trivial") || text.includes("p4")) return 300
  return 100
}

const updatedTimestamp = (value?: string) => {
  if (!value) return 0
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

const issueType = (ticket: WorkflowTask) => (ticket.issue_type || "").trim().toLowerCase()

export const isEpicTicket = (ticket: WorkflowTask) => issueType(ticket).includes("epic")

export const isSubtaskTicket = (ticket: WorkflowTask) => {
  if (ticket.is_subtask) return true
  if ((ticket.parent_key || "").trim()) return true
  const type = issueType(ticket)
  return type.includes("sub-task") || type.includes("subtask")
}

const ticketKey = (ticket: WorkflowTask) => (ticket.key || "").trim().toUpperCase()

const compareTickets = (a: WorkflowTask, b: WorkflowTask) =>
  priorityScore(b.priority) - priorityScore(a.priority) ||
  updatedTimestamp(b.updated) - updatedTimestamp(a.updated) ||
  ticketKey(a).localeCompare(ticketKey(b))

export const sortWorkflowEpicsByPriority = (tickets: WorkflowTask[]): WorkflowTask[] =>
  [...tickets].filter(isEpicTicket).sort(compareTickets)

export const sortWorkflowTasksForTable = (tickets: WorkflowTask[]): WorkflowTask[] => {
  const epics: WorkflowTask[] = []
  const parentTickets: WorkflowTask[] = []
  const subtasks: WorkflowTask[] = []

  tickets.forEach((ticket) => {
    if (isEpicTicket(ticket)) {
      epics.push(ticket)
      return
    }
    if (isSubtaskTicket(ticket)) {
      subtasks.push(ticket)
      return
    }
    parentTickets.push(ticket)
  })

  const subtasksByParent = new Map<string, WorkflowTask[]>()
  const orphanSubtasks: WorkflowTask[] = []
  subtasks.forEach((ticket) => {
    const parentKey = (ticket.parent_key || "").trim().toUpperCase()
    if (!parentKey) {
      orphanSubtasks.push(ticket)
      return
    }
    const bucket = subtasksByParent.get(parentKey) || []
    bucket.push(ticket)
    subtasksByParent.set(parentKey, bucket)
  })
  subtasksByParent.forEach((bucket) => bucket.sort(compareTickets))

  const sortedParents = [...parentTickets].sort(compareTickets)
  const sortedEpics = [...epics].sort(compareTickets)
  const ordered: WorkflowTask[] = []
  const consumedParentKeys = new Set<string>()

  sortedParents.forEach((parent) => {
    const parentKey = ticketKey(parent)
    ordered.push(parent)
    if (parentKey && subtasksByParent.has(parentKey)) {
      consumedParentKeys.add(parentKey)
      ordered.push(...(subtasksByParent.get(parentKey) || []))
    }
  })

  const sortedOrphanSubtasks = [...orphanSubtasks].sort(compareTickets)
  ordered.push(...sortedOrphanSubtasks)

  const leftoverLinkedSubtasks: WorkflowTask[] = []
  subtasksByParent.forEach((bucket, parentKey) => {
    if (consumedParentKeys.has(parentKey)) return
    if (sortedEpics.some((epic) => ticketKey(epic) === parentKey)) return
    leftoverLinkedSubtasks.push(...bucket)
  })
  leftoverLinkedSubtasks.sort(compareTickets)
  ordered.push(...leftoverLinkedSubtasks)

  sortedEpics.forEach((epic) => {
    const epicKey = ticketKey(epic)
    ordered.push(epic)
    if (epicKey && subtasksByParent.has(epicKey)) {
      ordered.push(...(subtasksByParent.get(epicKey) || []))
    }
  })

  return ordered
}

export const useWorkflowTasksSortedTickets = (tickets: WorkflowTask[]) =>
  useMemo(() => sortWorkflowTasksForTable(tickets), [tickets])
