import { Bot, Paperclip, ArrowUp, Square, X, GitBranch, Globe, ChevronDown } from "lucide-react"
import { useMemo } from "react"

import {
  FileUpload,
  FileUploadContent,
  FileUploadTrigger,
} from "@/shared/components/prompt-kit/file-upload"
import {
  PromptInput,
  PromptInputActions,
  PromptInputTextarea,
} from "@/shared/components/prompt-kit/prompt-input"
import { PromptSuggestion } from "@/shared/components/prompt-kit/prompt-suggestion"
import { Button } from "@/shared/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"
import { formatGitPlatformLabel } from "@/features/git/constants"
import { AddTicketMenu } from "@/features/chat/components/AddTicketMenu"
import { TicketChip } from "@/features/chat/components/TicketChip"
import type { ChatWorkflowMode, SelectedTicketSummary } from "@/features/chat/types"
import type { WorkspaceGitStatus } from "@/features/git/types"
import { Chip } from "@/shared/components/chip"

const workflowModeLabels: Record<ChatWorkflowMode, string> = {
  auto: "Mode: Auto (Alpha)",
  jira: "Mode: Jira Management",
  code_review: "Mode: Code Review (Ask)",
  code: "Mode: Code Development (Build)",
  research: "Mode: Research",
  stitch_generation: "Mode: Stitch Generation",
}

const defaultWorkflowModes: ChatWorkflowMode[] = ["auto", "jira", "code_review", "code", "research"]

type ChatComposerProps = {
  inputValue: string
  onInputValueChange: (value: string) => void
  onSubmit: () => void
  isSending: boolean
  isRunning: boolean
  statusText: string
  messageCount: number
  uploadedFiles: File[]
  uploadedFilesCount: number
  selectedTickets: SelectedTicketSummary[]
  selectedTicketKeys: string[]
  gitStatus: WorkspaceGitStatus | null
  onFilesAdded: (files: File[]) => void
  onFileRemoved?: (file: File) => void
  onTicketAdd: (ticketKey: string) => void
  onTicketRemove: (ticketKey: string) => void
  workflowMode: ChatWorkflowMode
  availableWorkflowModes?: ChatWorkflowMode[]
  onWorkflowModeChange: (workflowMode: ChatWorkflowMode) => void
  onStop: () => void
  showSuggestions: boolean
  suggestions: string[]
  onSuggestionClick: (suggestion: string) => void
}

export function ChatComposer({
  inputValue,
  onInputValueChange,
  onSubmit,
  isSending,
  isRunning,
  statusText,
  messageCount,
  uploadedFiles,
  uploadedFilesCount,
  selectedTickets,
  selectedTicketKeys,
  gitStatus,
  onFilesAdded,
  onFileRemoved,
  onTicketAdd,
  onTicketRemove,
  workflowMode,
  availableWorkflowModes = defaultWorkflowModes,
  onWorkflowModeChange,
  onStop,
  showSuggestions,
  suggestions,
  onSuggestionClick,
}: ChatComposerProps) {
  const fileSummaries = useMemo(
    () =>
      uploadedFiles.map((file) => ({
        key: `${file.name}-${file.size}-${file.lastModified}`,
        name: file.name,
      })),
    [uploadedFiles]
  )
  const showGitChips = Boolean(gitStatus?.is_git_repo)

  return (
    <div className="mx-auto w-full max-w-4xl pt-4 pb-2 px-2 shadow-[0_0_20px_10px_var(--background)] z-[2]">
      <FileUpload onFilesAdded={onFilesAdded}>
        <PromptInput
          value={inputValue}
          onValueChange={onInputValueChange}
          onSubmit={onSubmit}
          isLoading={isSending}
          disabled={isSending}
          className="w-full"
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 px-1">
            {showGitChips ? (
              <>
                <Chip color="info" variant="outline" className="gap-1.5 rounded-full px-3 py-1 text-xs">
                  <GitBranch className="h-3 w-3" />
                  {gitStatus?.branch || "unknown"}
                </Chip>

                {gitStatus?.platform && gitStatus.platform !== "unknown" ? (
                  <Chip className="gap-1.5 rounded-full px-3 py-1 text-xs">
                    <Globe className="h-3 w-3" />
                    {formatGitPlatformLabel(gitStatus.platform)}
                  </Chip>
                ) : null}
              </>
            ) : null}

            {fileSummaries.map((fileSummary, index) => (
              <div
                key={fileSummary.key}
                className="inline-flex items-center gap-2 rounded-full border bg-muted px-3 py-1 text-xs"
              >
                <span className="max-w-[240px] truncate">{fileSummary.name}</span>
                {onFileRemoved ? (
                  <button
                    type="button"
                    onClick={() => {
                      const file = uploadedFiles[index]
                      if (file) {
                        onFileRemoved(file)
                      }
                    }}
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={`Remove ${fileSummary.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : null}
              </div>
            ))}

            {selectedTickets.map((ticket) => (
              <TicketChip
                key={ticket.key}
                ticketKey={ticket.key}
                title={ticket.title}
                onRemove={() => onTicketRemove(ticket.key)}
              />
            ))}
          </div>

          <PromptInputTextarea
            placeholder={
              messageCount === 0
                ? "Type something or pick one from below..."
                : "Send a message..."
            }
            className="!bg-transparent"
          />

          <PromptInputActions className="mt-2 justify-between">
            <div className="flex items-center gap-2">
              <div onClick={(event) => event.stopPropagation()}>
                <FileUploadTrigger asChild>
                  <Button variant="ghost" size="icon" disabled={isSending}>
                    <Paperclip className="h-4 w-4" />
                  </Button>
                </FileUploadTrigger>
              </div>
              <div onClick={(event) => event.stopPropagation()}>
                <AddTicketMenu
                  onTicketSelected={onTicketAdd}
                  selectedTicketKeys={selectedTicketKeys}
                />
              </div>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    className="h-7 rounded-full border-zinc-400/60 bg-transparent px-3 text-xs text-muted-foreground"
                  >
                    <span>{workflowModeLabels[workflowMode]}</span>
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>

                <DropdownMenuContent align="start" className="min-w-40 rounded-2xl">
                  <DropdownMenuLabel>Workflow Mode</DropdownMenuLabel>

                  <DropdownMenuRadioGroup
                    value={workflowMode}
                    onValueChange={(value) => onWorkflowModeChange(value as ChatWorkflowMode)}
                  >
                    {availableWorkflowModes.map((mode) => (
                      <DropdownMenuRadioItem key={mode} value={mode}>
                        {workflowModeLabels[mode]}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>

              {uploadedFilesCount > 0 ? (
                <span className="text-muted-foreground text-xs">
                  {uploadedFilesCount} file{uploadedFilesCount > 1 ? "s" : ""} attached
                </span>
              ) : null}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs">{statusText}</span>

              <Button onClick={isRunning ? onStop : onSubmit} size="icon" className="rounded-full">
                {isRunning ? (
                  <Square size={24} />
                ) : (
                  <ArrowUp size={24} />
                )}
              </Button>
            </div>
          </PromptInputActions>
        </PromptInput>

        <FileUploadContent>
          <div className="rounded-xl border bg-card p-6 text-center">
            <Bot className="mx-auto mb-2 h-5 w-5" />
            <p className="text-sm">Drop files to attach them</p>
          </div>
        </FileUploadContent>
      </FileUpload>

      {showSuggestions ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {suggestions.map((suggestion) => (
            <PromptSuggestion key={suggestion} onClick={() => onSuggestionClick(suggestion)} size="sm">
              {suggestion}
            </PromptSuggestion>
          ))}
        </div>
      ) : null}
    </div>
  )
}
