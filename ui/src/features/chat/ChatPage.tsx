import { useEffect, useState } from "react"

import { ChatContainerRoot } from "@/shared/components/prompt-kit/chat-container"
import { ScrollButton } from "@/shared/components/prompt-kit/scroll-button"
import { ChatComposer } from "@/features/chat/components/ChatComposer"
import { ChatStreamContent } from "@/features/chat/components/ChatStreamContent"
import useOrchestratorChat from "@/features/chat/hooks/use-orchestrator-chat"
import { useChatStore } from "@/features/chat/store/chat-store"
import type { ChatWorkflowMode } from "@/features/chat/types"
import { useGitStatus } from "@/features/git/hooks/useGitStatus"
import { useWorkspaces } from "@/features/workspace/hooks/useWorkspaces"
import FileFolderDialog from "@/shared/components/file-folder-dialog"
import { WorkspaceRequiredState } from "@/shared/components/workspace-required-state"
import useFileFolderDialog from "@/shared/hooks/useFileFolderDialog"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

type StitchWorkspaceStatus = {
  is_git_repo: boolean
  linked: boolean
  project_id: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const suggestionsByMode: Record<ChatWorkflowMode, string[]> = {
  auto: [
    "Please provide an overview of this project",
    "What should I work on next in this repository?",
  ],
  jira: [
    "Summarize the current status of my selected Jira tickets",
    "Draft a clear implementation plan for these tickets",
  ],
  code_review: [
    "Review this codebase architecture and highlight key risks",
    "Analyze components and styling patterns, then suggest improvements",
  ],
  code: [
    "Analyze this codebase and suggest high-impact refactors",
    "Help me implement the selected ticket end-to-end",
  ],
  research: [
    "Research the best approach for this technical problem",
    "Compare 2-3 options and recommend one with trade-offs",
  ],
  stitch_generation: [
    "Generate a desktop landing page concept for this product",
    "Create 2 layout ideas for a dashboard with primary and secondary actions",
  ],
}

const mergeFiles = (existingFiles: File[], incomingFiles: File[]) => {
  const nextFiles = [...existingFiles]

  incomingFiles.forEach((file) => {
    const exists = nextFiles.some(
      (existing) =>
        existing.name === file.name &&
        existing.size === file.size &&
        existing.lastModified === file.lastModified
    )

    if (!exists) {
      nextFiles.push(file)
    }
  })

  return nextFiles
}

const removeFile = (existingFiles: File[], targetFile: File) =>
  existingFiles.filter(
    (file) =>
      !(
        file.name === targetFile.name &&
        file.size === targetFile.size &&
        file.lastModified === targetFile.lastModified
      )
  )

export default function ChatPage() {
  const [inputValue, setInputValue] = useState("")
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([])
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const [stitchStatus, setStitchStatus] = useState<StitchWorkspaceStatus | null>(null)

  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const setPrimaryWorkspacePath = useDashboardSettingsStore((state) => state.setPrimaryWorkspacePath)
  const secondaryWorkspacePath = useDashboardSettingsStore((state) => state.secondaryWorkspacePath)
  const workspacePickerRequestId = useDashboardSettingsStore((state) => state.workspacePickerRequestId)
  const consumeWorkspacePickerRequest = useDashboardSettingsStore((state) => state.consumeWorkspacePickerRequest)
  const workspaceRoot = useChatStore((state) => state.workspaceRoot)
  const setSecondaryWorkspaceRoot = useChatStore((state) => state.setSecondaryWorkspaceRoot)
  const selectedTicketKeys = useChatStore((state) => state.selectedTicketKeys)
  const ticketDetailsByKey = useChatStore((state) => state.ticketDetailsByKey)
  const addTicket = useChatStore((state) => state.addTicket)
  const removeTicket = useChatStore((state) => state.removeTicket)
  const setWorkspaceRoot = useChatStore((state) => state.setWorkspaceRoot)
  const { workspaces, isLoading: isLoadingWorkspaces } = useWorkspaces()
  const { gitStatus } = useGitStatus(workspaceRoot || "")

  const {
    streamItems,
    messageCount,
    isSending,
    hasActiveTurn,
    statusText,
    isThinking,
    orchestratorTasks,
    workflowMode,
    updateWorkflowMode,
    sendMessage,
    stopExecution,
  } = useOrchestratorChat()

  const {
    columns,
    locations,
    selectedPath,
    activeDirectoryPath,
    selectedByColumnPath,
    showHidden,
    isLoading: browserLoading,
    isCreatingFolder,
    isRenamingEntry,
    error: browserError,
    openAtPath,
    setShowHidden,
    selectLocation,
    selectEntry,
    createFolder,
    renameEntry,
    deleteEntry,
  } = useFileFolderDialog({ mode: "folder-only" })

  useEffect(() => {
    setBreadcrumbs([
      { label: "Dashboard", href: "/" },
      { label: "Chat" },
    ])
  }, [setBreadcrumbs])

  useEffect(() => {
    setPrimaryWorkspacePath(workspaceRoot || "")
  }, [setPrimaryWorkspacePath, workspaceRoot])

  useEffect(() => {
    setSecondaryWorkspaceRoot(secondaryWorkspacePath || null)
  }, [secondaryWorkspacePath, setSecondaryWorkspaceRoot])

  useEffect(() => {
    if (workspacePickerRequestId <= 0) return
    setWorkspaceOpen(true)
    void openAtPath(workspaceRoot || "")
    consumeWorkspacePickerRequest(workspacePickerRequestId)
  }, [
    consumeWorkspacePickerRequest,
    openAtPath,
    workspacePickerRequestId,
    workspaceRoot,
  ])

  useEffect(() => {
    let cancelled = false
    const resolvedWorkspaceRoot = workspaceRoot.trim()
    let refreshTimer: number | null = null

    if (!resolvedWorkspaceRoot) {
      setStitchStatus(null)
      return
    }

    const loadStitchStatus = async () => {
      try {
        const response = await fetch(
          buildApiUrl(`/api/stitch/status?workspace=${encodeURIComponent(resolvedWorkspaceRoot)}`)
        )

        if (!response.ok) {
          if (!cancelled) {
            setStitchStatus(null)
          }
          return
        }

        const payload = (await response.json()) as StitchWorkspaceStatus

        if (!cancelled) {
          setStitchStatus(payload)
        }
      } catch {
        if (!cancelled) {
          setStitchStatus(null)
        }
      }
    }

    void loadStitchStatus()

    refreshTimer = window.setInterval(() => {
      void loadStitchStatus()
    }, 20_000)

    return () => {
      cancelled = true

      if (refreshTimer) {
        window.clearInterval(refreshTimer)
      }
    }
  }, [workspaceRoot])

  const hasStreamItems = streamItems.length > 0
  const isRunning = hasActiveTurn || isSending
  const hasSavedWorkspaces = workspaces.length > 0
  const hasCurrentWorkspace = workspaceRoot.trim().length > 0
  const stitchModeEnabled = Boolean(stitchStatus?.is_git_repo && stitchStatus?.linked && stitchStatus?.project_id)
  const availableWorkflowModes: ChatWorkflowMode[] = stitchModeEnabled
    ? ["auto", "jira", "code_review", "code", "research", "stitch_generation"]
    : ["auto", "jira", "code_review", "code", "research"]
  const suggestions = suggestionsByMode[workflowMode]
  const showWorkspaceRequiredState = !isLoadingWorkspaces && (!hasSavedWorkspaces || !hasCurrentWorkspace)
  const selectedTickets = selectedTicketKeys.map((key) => ({
    key,
    title: ticketDetailsByKey[key]?.title || key,
    status: ticketDetailsByKey[key]?.status,
  }))

  useEffect(() => {
    if (workflowMode === "stitch_generation" && !stitchModeEnabled) {
      updateWorkflowMode("code_review")
    }
  }, [stitchModeEnabled, updateWorkflowMode, workflowMode])

  const submitMessage = async () => {
    const text = inputValue.trim()

    if (!text) {
      return
    }

    const filesToSend = [...uploadedFiles]
    const sent = await sendMessage(text, filesToSend)
    if (sent) {
      setInputValue("")
      setUploadedFiles([])
    }
  }

  const appendFiles = (files: File[]) => {
    setUploadedFiles((existing) => mergeFiles(existing, files))
  }

  const removeUploadedFile = (file: File) => {
    setUploadedFiles((existing) => removeFile(existing, file))
  }

  const closeWorkspacePicker = () => {
    setWorkspaceOpen(false)
  }

  const commitWorkspaceSelection = () => {
    const path = selectedPath.trim()
    if (!path) return
    setWorkspaceRoot(path)
    setPrimaryWorkspacePath(path)
    setWorkspaceOpen(false)
  }

  return (
    showWorkspaceRequiredState ? (
      <WorkspaceRequiredState
        description="Create a workspace and set it as the current workspace before starting a chat."
      />
    ) : (
      <div className="relative flex min-h-0 flex-1 w-full flex-col">
        <div className="relative flex flex-1 min-h-0 w-full">
          <ChatContainerRoot className="w-full">
            <ChatStreamContent
              streamItems={streamItems}
              orchestratorTasks={orchestratorTasks}
              isThinking={isThinking}
              statusText={statusText}
            />

            <div className="absolute right-4 bottom-4">
              <ScrollButton />
            </div>
          </ChatContainerRoot>
        </div>

        <ChatComposer
          inputValue={inputValue}
          onInputValueChange={setInputValue}
          onSubmit={submitMessage}
          isSending={isSending}
          isRunning={isRunning}
          statusText={statusText}
          messageCount={messageCount}
          uploadedFiles={uploadedFiles}
          uploadedFilesCount={uploadedFiles.length}
          selectedTickets={selectedTickets}
          selectedTicketKeys={selectedTicketKeys}
          gitStatus={gitStatus}
          onFilesAdded={appendFiles}
          onFileRemoved={removeUploadedFile}
          onTicketAdd={addTicket}
          onTicketRemove={removeTicket}
          workflowMode={workflowMode}
          availableWorkflowModes={availableWorkflowModes}
          onWorkflowModeChange={updateWorkflowMode}
          onStop={stopExecution}
          showSuggestions={!hasStreamItems}
          suggestions={suggestions}
          onSuggestionClick={setInputValue}
        />

        <FileFolderDialog
          open={workspaceOpen}
          onClose={closeWorkspacePicker}
          title="Select Workspace Folder"
          mode="folder-only"
          locations={locations}
          columns={columns}
          selectedByColumnPath={selectedByColumnPath}
          selectedPath={selectedPath}
          activeDirectoryPath={activeDirectoryPath}
          isLoading={browserLoading}
          isCreatingFolder={isCreatingFolder}
          isRenamingEntry={isRenamingEntry}
          error={browserError}
          showHidden={showHidden}
          onShowHiddenChange={(value) => {
            void setShowHidden(value)
          }}
          onSelectLocation={(path) => {
            void selectLocation(path)
          }}
          onSelectEntry={(columnIndex, entry) => {
            void selectEntry(columnIndex, entry)
          }}
          onCreateFolder={createFolder}
          onRenameEntry={renameEntry}
          onDeleteEntry={deleteEntry}
          onConfirm={commitWorkspaceSelection}
        />
      </div>
    )
  )
}
