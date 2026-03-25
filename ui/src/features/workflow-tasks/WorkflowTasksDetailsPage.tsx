import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"

import {
  type ActivityTab,
  WorkflowTaskActivitySection,
  WorkflowTaskAttachmentPreviewDialog,
  WorkflowTaskAttachmentsSection,
  WorkflowTaskDescriptionSection,
  WorkflowTaskDetailsSection,
  WorkflowTaskHeader,
  WorkflowTaskNotFoundState,
  WorkflowTaskSubtasksSection,
} from "@/features/workflow-tasks/components/WorkflowTaskDetailsSections"
import { useWorkflowTasksPageData } from "@/features/workflow-tasks/hooks/useWorkflowTasksPageData"
import type {
  WorkflowTask,
  WorkflowTaskAttachment,
  WorkflowTaskComment,
  WorkflowTaskHistoryEntry,
} from "@/features/workflow-tasks/types"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"])

const formatDate = (value?: string) => {
  if (!value) return "n/a"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const issueUrlFor = (task: WorkflowTask, issueBaseUrl: string) => task.url || (issueBaseUrl ? `${issueBaseUrl}${task.key}` : "")

const attachmentNameFor = (attachment: WorkflowTaskAttachment, index: number) =>
  (attachment.filename || "").trim() || `Attachment ${index + 1}`

const resolveAttachmentUrl = (url?: string) => {
  const trimmed = (url || "").trim()
  if (!trimmed) return ""
  if (/^(?:https?:|data:|blob:)/i.test(trimmed)) return trimmed
  if (trimmed.startsWith("/") && API_BASE_URL) return `${API_BASE_URL}${trimmed}`
  return trimmed
}

const attachmentExtensionFor = (attachment: WorkflowTaskAttachment) => {
  const filename = attachment.filename || ""
  const source = filename || attachment.url || ""
  const withoutQuery = source.split("?")[0]
  const lastDot = withoutQuery.lastIndexOf(".")
  if (lastDot < 0) return ""
  return withoutQuery.slice(lastDot + 1).trim().toLowerCase()
}

const isImageAttachment = (attachment: WorkflowTaskAttachment) => IMAGE_EXTENSIONS.has(attachmentExtensionFor(attachment))

export default function WorkflowTasksDetailsPage() {
  const navigate = useNavigate()
  const { taskKey } = useParams()
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const {
    tickets,
    isLoadingConfig,
    error,
    warning,
    issueBaseUrl,
    fetchTickets,
    isFetching,
  } = useWorkflowTasksPageData()

  const [descriptionOpen, setDescriptionOpen] = useState(true)
  const [subtasksOpen, setSubtasksOpen] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(true)
  const [activityTab, setActivityTab] = useState<ActivityTab>("all")
  const [previewAttachment, setPreviewAttachment] = useState<WorkflowTaskAttachment | null>(null)

  const normalizedTaskKey = (taskKey || "").trim().toUpperCase()

  const selectedTask = useMemo(
    () => tickets.find((task) => task.key.trim().toUpperCase() === normalizedTaskKey) || null,
    [tickets, normalizedTaskKey]
  )

  useEffect(() => {
    setBreadcrumbs([
      { label: "Dashboard", href: "/" },
      { label: "Workflow Tasks", href: "/workflow-tasks" },
      { label: selectedTask?.key || normalizedTaskKey || "Task Details" },
    ])
  }, [normalizedTaskKey, selectedTask?.key, setBreadcrumbs])

  useEffect(() => {
    setDescriptionOpen(true)
    setSubtasksOpen(true)
    setDetailsOpen(true)
    setActivityTab("all")
    setPreviewAttachment(null)
  }, [selectedTask?.key])

  const selectedParentKey = useMemo(() => {
    if (!selectedTask) return ""
    if (selectedTask.is_subtask) {
      return (selectedTask.parent_key || "").trim().toUpperCase()
    }
    return (selectedTask.key || "").trim().toUpperCase()
  }, [selectedTask])

  const selectedSubtasks = useMemo(() => {
    if (!selectedTask || !selectedParentKey) return [] as WorkflowTask[]
    return tickets.filter((task) => (task.parent_key || "").trim().toUpperCase() === selectedParentKey)
  }, [selectedParentKey, selectedTask, tickets])

  const subtasksDonePercent = useMemo(() => {
    if (!selectedSubtasks.length) return 0
    const doneCount = selectedSubtasks.filter((task) => (task.status || "").toLowerCase().includes("done")).length
    return Math.round((doneCount / selectedSubtasks.length) * 100)
  }, [selectedSubtasks])

  const selectedComments = useMemo(() => {
    if (!selectedTask || !Array.isArray(selectedTask.comments)) return [] as WorkflowTaskComment[]
    return selectedTask.comments
  }, [selectedTask])

  const selectedAttachments = useMemo(() => {
    if (!selectedTask || !Array.isArray(selectedTask.attachments)) return [] as WorkflowTaskAttachment[]
    return selectedTask.attachments.filter((attachment) => Boolean((attachment.filename || attachment.url || "").trim()))
  }, [selectedTask])

  const selectedHistory = useMemo(() => {
    if (!selectedTask || !Array.isArray(selectedTask.history)) return [] as WorkflowTaskHistoryEntry[]
    return selectedTask.history
  }, [selectedTask])

  const detailsRows = selectedTask
    ? [
      { label: "Assignee", value: selectedTask.assignee || "None" },
      { label: "Reporter", value: selectedTask.reporter || "None" },
      { label: "Priority", value: selectedTask.priority || "None" },
      { label: "Parent", value: selectedTask.parent_key || "None" },
      { label: "Due date", value: selectedTask.due_date ? formatDate(selectedTask.due_date) : "None" },
      {
        label: "Labels",
        value: selectedTask.labels && selectedTask.labels.length ? selectedTask.labels.join(", ") : "None",
      },
      { label: "Team", value: selectedTask.team || "None" },
      { label: "Start date", value: selectedTask.start_date ? formatDate(selectedTask.start_date) : "None" },
      {
        label: "Sprint",
        value: selectedTask.sprints && selectedTask.sprints.length ? selectedTask.sprints.join(", ") : "None",
      },
      { label: "Story point estimate", value: selectedTask.story_points || "None" },
      { label: "Development", value: selectedTask.development || "None" },
    ]
    : []

  const hasActivity = selectedComments.length > 0 || selectedHistory.length > 0
  const subtaskSectionTitle = selectedTask?.is_subtask
    ? `Related subtasks (${selectedParentKey || "same parent"})`
    : "Subtasks"
  const previewAttachmentUrl = previewAttachment ? resolveAttachmentUrl(previewAttachment.url) : ""
  const previewAttachmentName = previewAttachment ? attachmentNameFor(previewAttachment, 0) : ""
  const previewIsImage = previewAttachment ? isImageAttachment(previewAttachment) : false

  if (isLoadingConfig && tickets.length === 0) {
    return (
      <div className="p-4">
        <p className="text-muted-foreground text-sm">Loading workflow task details...</p>
      </div>
    )
  }

  if (!selectedTask) {
    return (
      <WorkflowTaskNotFoundState
        normalizedTaskKey={normalizedTaskKey}
        error={error}
        warning={warning}
        isFetching={isFetching}
        onBack={() => navigate("/workflow-tasks")}
        onRefresh={() => {
          void fetchTickets()
        }}
      />
    )
  }

  return (
    <div className="flex flex-1 min-h-0 w-full overflow-hidden">
      <div className="flex flex-1 min-h-0 flex-col gap-4 p-6 overflow-y-auto">
        <WorkflowTaskHeader
          task={selectedTask}
          issueUrl={issueUrlFor(selectedTask, issueBaseUrl)}
          onBack={() => navigate("/workflow-tasks")}
          onOpenJira={() => window.open(issueUrlFor(selectedTask, issueBaseUrl), "_blank")}
        />

        <WorkflowTaskDescriptionSection
          isOpen={descriptionOpen}
          onOpenChange={setDescriptionOpen}
          description={selectedTask.description || ""}
        />

        <WorkflowTaskAttachmentsSection
          attachments={selectedAttachments}
          onPreviewAttachment={setPreviewAttachment}
          resolveAttachmentUrl={resolveAttachmentUrl}
          attachmentNameFor={attachmentNameFor}
          attachmentExtensionFor={attachmentExtensionFor}
          isImageAttachment={isImageAttachment}
        />

        <WorkflowTaskSubtasksSection
          isOpen={subtasksOpen}
          onOpenChange={setSubtasksOpen}
          title={subtaskSectionTitle}
          donePercent={subtasksDonePercent}
          subtasks={selectedSubtasks}
          isCurrentTaskSubtask={Boolean(selectedTask.is_subtask)}
          currentTaskKey={selectedTask.key}
          onOpenTask={(taskKey) => navigate(`/workflow-tasks/${encodeURIComponent(taskKey)}`)}
        />

        <WorkflowTaskDetailsSection
          isOpen={detailsOpen}
          onOpenChange={setDetailsOpen}
          rows={detailsRows}
        />

        <WorkflowTaskActivitySection
          activityTab={activityTab}
          onActivityTabChange={setActivityTab}
          hasActivity={hasActivity}
          comments={selectedComments}
          history={selectedHistory}
          formatDate={formatDate}
        />
      </div>

      <WorkflowTaskAttachmentPreviewDialog
        isOpen={Boolean(previewAttachment)}
        onOpenChange={(isOpen) => {
          if (!isOpen) {
            setPreviewAttachment(null)
          }
        }}
        taskKey={selectedTask.key}
        previewAttachmentUrl={previewAttachmentUrl}
        previewAttachmentName={previewAttachmentName}
        previewIsImage={previewIsImage}
      />
    </div>
  )
}
