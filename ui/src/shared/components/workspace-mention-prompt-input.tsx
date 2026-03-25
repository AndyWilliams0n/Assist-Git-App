import * as React from "react"
import { ArrowUp, BookOpen, Code2, File, Folder, ImagePlus, Loader2, X } from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import {
  EDITOR_LINE_RANGE_MIME_TYPE,
  parseEditorLineRangePayload,
  resolveLastEditorClipboardLineRange,
} from "@/shared/utils/editor-clipboard.ts"
import { cn } from "@/shared/utils/utils.ts"
import { Chip } from "@/shared/components/chip"
import type { FileSystemSearchResponse } from "@/shared/types/file-browser"
import {
  buildInlinePromptWithWorkspaceReferences,
  buildPromptWithWorkspaceReferences,
  buildWorkspaceReferenceContext,
  makeImageWorkspaceReference,
  makeSnippetWorkspaceReference,
  makeSpecBundleWorkspaceReference,
  makeWorkspaceReference,
  parseSpecBundleDragPayload,
  parseWorkspaceReferenceDragPayload,
  SPEC_BUNDLE_DRAG_MIME_TYPE,
  type WorkspaceReference,
  type WorkspaceReferenceContextItem,
  type WorkspaceReferenceDragPayload,
  WORKSPACE_REFERENCE_MIME_TYPE,
} from "@/features/prompts/utils/workspace-references"

type MentionRange = {
  start: number
  end: number
  query: string
}

type WorkspaceMentionPromptInputProps = {
  primaryWorkspacePath: string
  secondaryWorkspacePath?: string
  onSubmit: (payload: { prompt: string; rawPrompt: string; context: WorkspaceReferenceContextItem[] }) => Promise<void | false> | void | false
  onFetchSpecBundle?: (specName: string) => Promise<string | null>
  isProcessing: boolean
  mode?: "create" | "edit"
  placeholder?: string
  className?: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const MENTION_TRIGGER_PATTERN = /(?:^|\s)@([A-Za-z0-9._-]*)$/
const MAX_SNIPPET_LENGTH = 20000
const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
const MAX_IMAGE_REFERENCES = 4
const MIN_TEXTAREA_HEIGHT_PX = 96
const MAX_TEXTAREA_HEIGHT_PX = 224

const computeMentionRange = (text: string, caret: number): MentionRange | null => {
  const clampedCaret = Math.max(0, Math.min(caret, text.length))
  const prefix = text.slice(0, clampedCaret)
  const match = prefix.match(MENTION_TRIGGER_PATTERN)
  if (!match) return null

  const query = match[1] || ""
  const start = clampedCaret - query.length - 1
  const atSymbol = text[start]
  if (start < 0 || atSymbol !== "@") return null

  return {
    start,
    end: clampedCaret,
    query,
  }
}

const asDragPayload = (
  entry: { name: string; path: string; type: "dir" | "file" },
  workspaceRole: "primary" | "secondary"
): WorkspaceReferenceDragPayload => ({
  name: entry.name,
  path: entry.path,
  type: entry.type,
  workspaceRole,
})

const hasWorkspaceDragPayload = (event: React.DragEvent) => {
  const types = Array.from(event.dataTransfer.types || [])
  return types.includes(WORKSPACE_REFERENCE_MIME_TYPE) || types.includes(SPEC_BUNDLE_DRAG_MIME_TYPE)
}

const readFileAsDataUrl = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`Failed to read file: ${file.name}`))
    reader.onload = () => resolve(String(reader.result || ""))
    reader.readAsDataURL(file)
  })

const parseLineNumber = (value: string): number | null => {
  const match = value.match(/^\s*(\d+)(?:\s+[^\s]|\s*[|:])/)
  if (!match) return null
  const parsed = Number.parseInt(match[1], 10)
  return Number.isFinite(parsed) ? parsed : null
}

const extractSnippetLineRange = (text: string): { lineStart?: number; lineEnd?: number } => {
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean)
  if (lines.length === 0) return {}

  const first = parseLineNumber(lines[0])
  const last = parseLineNumber(lines[lines.length - 1])

  if (!Number.isFinite(first) || !Number.isFinite(last)) {
    return {}
  }

  if ((last as number) < (first as number)) {
    return {}
  }

  return {
    lineStart: first as number,
    lineEnd: last as number,
  }
}

const mentionToneClass = (tone: "primary" | "secondary" | "snippet" | "snippet-lines" | "image" | "spec") => {
  if (tone === "secondary") {
    return "text-amber-600 dark:text-amber-400"
  }

  if (tone === "snippet-lines") {
    return "text-teal-600 dark:text-teal-400"
  }

  if (tone === "snippet") {
    return "text-rose-600 dark:text-rose-400"
  }

  if (tone === "image") {
    return "text-violet-600 dark:text-violet-400"
  }

  return "text-sky-600 dark:text-sky-400"
}

const renderHighlightedText = (value: string, references: WorkspaceReference[]) => {
  if (!value) return null
  if (references.length === 0) return value

  const mentionTonesByToken = new Map<string, Array<"primary" | "secondary" | "snippet" | "snippet-lines" | "image" | "spec">>()

  references.forEach((reference) => {
    const mentionToken = `@${reference.name}`.trim()
    if (!mentionToken || mentionToken === "@") return

    const mentionKey = mentionToken.toLowerCase()
    const tone =
      reference.kind === "dir" || reference.kind === "file"
        ? reference.workspaceRole === "secondary"
          ? "secondary"
          : "primary"
        : reference.kind === "snippet" && /^lines\s+\d+-\d+$/i.test(reference.name.trim())
          ? "snippet-lines"
        : reference.kind
    const existingRoles = mentionTonesByToken.get(mentionKey) || []

    mentionTonesByToken.set(mentionKey, [...existingRoles, tone])
  })

  if (mentionTonesByToken.size === 0) return value

  const mentionUsageByToken = new Map<string, number>()
  const mentionCandidates = Array.from(mentionTonesByToken.keys())
    .map((mentionKey) => ({ mentionKey, mentionToken: mentionKey }))
    .sort((left, right) => right.mentionToken.length - left.mentionToken.length)
  const isMentionBoundary = (char: string | undefined) =>
    !char || /\s|[.,;:!?)}\]]/.test(char)

  const result: React.ReactNode[] = []
  let cursor = 0

  while (cursor < value.length) {
    const atIndex = value.indexOf("@", cursor)

    if (atIndex < 0) {
      result.push(
        <span key={`tail-${cursor}`}>{value.slice(cursor)}</span>
      )
      break
    }

    if (atIndex > cursor) {
      result.push(
        <span key={`text-${cursor}`}>{value.slice(cursor, atIndex)}</span>
      )
    }

    const lowerTail = value.slice(atIndex).toLowerCase()
    const matchedCandidate = mentionCandidates.find((candidate) => {
      if (!lowerTail.startsWith(candidate.mentionToken)) return false
      const boundaryChar = value[atIndex + candidate.mentionToken.length]
      return isMentionBoundary(boundaryChar)
    })

    if (!matchedCandidate) {
      result.push(
        <span key={`raw-at-${atIndex}`}>@</span>
      )
      cursor = atIndex + 1
      continue
    }

    const mentionToken = value.slice(atIndex, atIndex + matchedCandidate.mentionToken.length)
    const mentionTones = mentionTonesByToken.get(matchedCandidate.mentionKey)

    if (!mentionTones || mentionTones.length === 0) {
      result.push(
        <span key={`raw-token-${atIndex}`}>{mentionToken}</span>
      )
      cursor = atIndex + mentionToken.length
      continue
    }

    const usageCount = mentionUsageByToken.get(matchedCandidate.mentionKey) || 0
    const toneIndex = Math.min(usageCount, mentionTones.length - 1)
    const tone = mentionTones[toneIndex]
    mentionUsageByToken.set(matchedCandidate.mentionKey, usageCount + 1)

    result.push(
      <span
        key={`mention-${atIndex}`}
        className={cn(mentionToneClass(tone))}
      >
        {mentionToken}
      </span>
    )

    cursor = atIndex + mentionToken.length
  }

  return result
}

const nextSnippetName = (references: WorkspaceReference[], fallbackText: string) => {
  const lineRange = extractSnippetLineRange(fallbackText)
  const hasLineRange = Number.isFinite(lineRange.lineStart) && Number.isFinite(lineRange.lineEnd)
  if (hasLineRange) {
    return {
      name: `Lines ${lineRange.lineStart}-${lineRange.lineEnd}`,
      lineStart: lineRange.lineStart,
      lineEnd: lineRange.lineEnd,
    }
  }

  const nextIndex = references.filter((reference) => {
    if (reference.kind !== "snippet") return false
    return !Number.isFinite(reference.lineStart) || !Number.isFinite(reference.lineEnd)
  }).length + 1
  return {
    name: `Code ${nextIndex}`,
    lineStart: undefined,
    lineEnd: undefined,
  }
}

const shouldCapturePastedSnippet = (value: string) => {
  const trimmed = value.trim()
  if (!trimmed) return false
  if (trimmed.startsWith("```") || trimmed.endsWith("```")) return true

  const hasLineRange = Number.isFinite(extractSnippetLineRange(trimmed).lineStart)
  if (hasLineRange) return true

  const codeIndicators = [
    "import ",
    "export ",
    "const ",
    "let ",
    "function ",
    "class ",
    "=>",
    "{",
    "}",
    "</",
    "/>",
    "def ",
    "return ",
    ";",
  ]

  if (codeIndicators.some((indicator) => trimmed.includes(indicator))) {
    return true
  }

  const lines = trimmed.split("\n").filter((line) => line.trim().length > 0)
  return lines.length >= 4 && /[{};<>()[\]]/.test(trimmed)
}

export function WorkspaceMentionPromptInput({
  primaryWorkspacePath,
  secondaryWorkspacePath,
  onSubmit,
  onFetchSpecBundle,
  isProcessing,
  mode = "create",
  placeholder = "Describe the spec you want to generate...",
  className,
}: WorkspaceMentionPromptInputProps) {
  const [value, setValue] = React.useState("")
  const [references, setReferences] = React.useState<WorkspaceReference[]>([])
  const [mentionRange, setMentionRange] = React.useState<MentionRange | null>(null)
  const [suggestions, setSuggestions] = React.useState<WorkspaceReferenceDragPayload[]>([])
  const [activeSuggestionIndex, setActiveSuggestionIndex] = React.useState(0)
  const [isSearching, setIsSearching] = React.useState(false)
  const [isDropActive, setIsDropActive] = React.useState(false)
  const [attachmentError, setAttachmentError] = React.useState<string | null>(null)
  const [textareaHeightPx, setTextareaHeightPx] = React.useState(MIN_TEXTAREA_HEIGHT_PX)

  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const highlightRef = React.useRef<HTMLDivElement | null>(null)
  const imageInputRef = React.useRef<HTMLInputElement | null>(null)
  const dragDepthRef = React.useRef(0)
  const syncOverlayScroll = React.useCallback((scrollTop: number, scrollLeft: number) => {
    if (!highlightRef.current) return
    highlightRef.current.scrollTop = scrollTop
    highlightRef.current.scrollLeft = scrollLeft
  }, [])
  const resolveWorkspaceRoot = React.useCallback(
    (workspaceRole: "primary" | "secondary") => {
      if (workspaceRole === "secondary" && secondaryWorkspacePath?.trim()) {
        return secondaryWorkspacePath.trim()
      }
      return primaryWorkspacePath.trim()
    },
    [primaryWorkspacePath, secondaryWorkspacePath]
  )

  const updateTextareaHeight = React.useCallback((element: HTMLTextAreaElement | null) => {
    if (!element) return

    const previousScrollTop = element.scrollTop
    element.style.height = "0px"
    const measuredHeight = Math.min(Math.max(element.scrollHeight, MIN_TEXTAREA_HEIGHT_PX), MAX_TEXTAREA_HEIGHT_PX)
    element.style.height = ""
    element.scrollTop = previousScrollTop

    setTextareaHeightPx((current) => (current === measuredHeight ? current : measuredHeight))
    syncOverlayScroll(element.scrollTop, element.scrollLeft)
  }, [syncOverlayScroll])

  const syncMentionRange = React.useCallback((nextValue: string, caretPosition: number) => {
    setMentionRange(computeMentionRange(nextValue, caretPosition))
  }, [])

  const updateValueAndSelection = React.useCallback(
    (nextValue: string, nextCaretPosition: number) => {
      setValue(nextValue)

      window.requestAnimationFrame(() => {
        const textarea = textareaRef.current
        if (!textarea) return
        textarea.focus()
        textarea.setSelectionRange(nextCaretPosition, nextCaretPosition)
        updateTextareaHeight(textarea)
      })

      syncMentionRange(nextValue, nextCaretPosition)
    },
    [syncMentionRange, updateTextareaHeight]
  )

  const upsertReference = React.useCallback((nextReference: WorkspaceReference) => {
    setReferences((current) => {
      if (current.some((reference) => reference.id === nextReference.id)) {
        return current
      }
      return [...current, nextReference]
    })
  }, [])

  const insertMentionReference = React.useCallback(
    ({
      reference,
      range,
      clearSuggestions = false,
    }: {
      reference: WorkspaceReference
      range?: { start: number; end: number }
      clearSuggestions?: boolean
    }) => {
      const textarea = textareaRef.current
      const selectionStart = textarea?.selectionStart ?? value.length
      const selectionEnd = textarea?.selectionEnd ?? value.length
      const resolvedRange = range ?? {
        start: selectionStart,
        end: selectionEnd,
      }
      const mentionToken = `@${reference.name}`
      const insertion = `${mentionToken} `
      const nextValue = `${value.slice(0, resolvedRange.start)}${insertion}${value.slice(resolvedRange.end)}`
      const nextCaret = resolvedRange.start + insertion.length

      upsertReference(reference)
      updateValueAndSelection(nextValue, nextCaret)

      if (clearSuggestions) {
        setSuggestions([])
        setActiveSuggestionIndex(0)
      }
    },
    [updateValueAndSelection, upsertReference, value]
  )

  const applySuggestion = React.useCallback((suggestion: WorkspaceReferenceDragPayload) => {
    const textarea = textareaRef.current
    const selectionStart = textarea?.selectionStart ?? value.length
    const selectionEnd = textarea?.selectionEnd ?? value.length
    const range = mentionRange ?? {
      start: selectionStart,
      end: selectionEnd,
      query: "",
    }
    const workspaceRole = suggestion.workspaceRole === "secondary" ? "secondary" : "primary"
    const workspaceRoot = resolveWorkspaceRoot(workspaceRole)
    if (!workspaceRoot) return
    const nextReference = makeWorkspaceReference(suggestion, workspaceRoot, workspaceRole)

    insertMentionReference({
      reference: nextReference,
      range: { start: range.start, end: range.end },
      clearSuggestions: true,
    })
  }, [insertMentionReference, mentionRange, resolveWorkspaceRoot, value.length])

  const insertDroppedReference = React.useCallback((payload: WorkspaceReferenceDragPayload) => {
    const workspaceRole = payload.workspaceRole === "secondary" ? "secondary" : "primary"
    const workspaceRoot = resolveWorkspaceRoot(workspaceRole)
    if (!workspaceRoot) return
    const nextReference = makeWorkspaceReference(payload, workspaceRoot, workspaceRole)
    insertMentionReference({ reference: nextReference })
  }, [insertMentionReference, resolveWorkspaceRoot])

  const handleAddImages = React.useCallback(async (files: File[]) => {
    if (files.length === 0) return

    const currentImageCount = references.filter((reference) => reference.kind === "image").length
    const remainingSlots = Math.max(0, MAX_IMAGE_REFERENCES - currentImageCount)
    if (remainingSlots <= 0) {
      setAttachmentError(`You can attach up to ${MAX_IMAGE_REFERENCES} images per prompt.`)
      return
    }

    const imageFiles = files.filter((file) => file.type.startsWith("image/")).slice(0, remainingSlots)
    if (imageFiles.length === 0) {
      setAttachmentError("Only image files are supported here.")
      return
    }

    const oversized = imageFiles.find((file) => file.size > MAX_IMAGE_SIZE_BYTES)
    if (oversized) {
      setAttachmentError(`${oversized.name} is larger than 5MB.`)
      return
    }

    try {
      const nextReferences = await Promise.all(
        imageFiles.map(async (file) => {
          const dataUrl = await readFileAsDataUrl(file)
          return makeImageWorkspaceReference({
            name: `Image ${file.name}`,
            mimeType: file.type || "image/png",
            dataUrl,
          })
        })
      )

      setAttachmentError(null)

      setReferences((current) => {
        const merged = [...current]
        nextReferences.forEach((nextReference) => {
          if (!merged.some((reference) => reference.id === nextReference.id)) {
            merged.push(nextReference)
          }
        })
        return merged
      })

      const mentionInsertion = nextReferences.map((reference) => `@${reference.name}`).join(" ")
      const textarea = textareaRef.current
      const start = textarea?.selectionStart ?? value.length
      const end = textarea?.selectionEnd ?? value.length
      const needsPrefixSpace = start > 0 && !/\s$/.test(value.slice(0, start))
      const insertion = `${needsPrefixSpace ? " " : ""}${mentionInsertion} `
      const nextValue = `${value.slice(0, start)}${insertion}${value.slice(end)}`
      const nextCaret = start + insertion.length

      updateValueAndSelection(nextValue, nextCaret)
    } catch {
      setAttachmentError("Failed to process image attachments.")
    }
  }, [references, updateValueAndSelection, value])

  const submitPrompt = React.useCallback(async () => {
    if (isProcessing) return
    const trimmedValue = value.trim()
    if (!trimmedValue) return

    const promptWithReferences = buildPromptWithWorkspaceReferences(trimmedValue, references)
    if (!promptWithReferences) return

    const rawPromptWithInlineReferences = buildInlinePromptWithWorkspaceReferences(trimmedValue, references)
    const context = buildWorkspaceReferenceContext(references)

    const result = await onSubmit({ prompt: promptWithReferences, rawPrompt: rawPromptWithInlineReferences, context })

    if (result === false) return

    setValue("")
    setReferences([])
    setMentionRange(null)
    setSuggestions([])
    setActiveSuggestionIndex(0)
    setAttachmentError(null)
    setTextareaHeightPx(MIN_TEXTAREA_HEIGHT_PX)

    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current
      if (!textarea) return
      textarea.scrollTop = 0
      textarea.scrollLeft = 0
      syncOverlayScroll(0, 0)
    })
  }, [isProcessing, onSubmit, references, syncOverlayScroll, value])

  React.useEffect(() => {
    updateTextareaHeight(textareaRef.current)
  }, [updateTextareaHeight, value])

  React.useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    syncOverlayScroll(textarea.scrollTop, textarea.scrollLeft)
  }, [syncOverlayScroll, textareaHeightPx, value])

  React.useEffect(() => {
    const primaryRoot = primaryWorkspacePath.trim()
    const secondaryRoot = secondaryWorkspacePath?.trim() || ""
    if (!mentionRange || (!primaryRoot && !secondaryRoot)) {
      setSuggestions([])
      setIsSearching(false)
      setActiveSuggestionIndex(0)
      return
    }

    let isCancelled = false
    const controller = new AbortController()

    const timer = window.setTimeout(async () => {
      try {
        setIsSearching(true)
        const searchWorkspace = async (workspacePath: string, workspaceRole: "primary" | "secondary") => {
          const params = new URLSearchParams()
          params.set("path", workspacePath)
          params.set("query", mentionRange.query)
          params.set("limit", "8")
          params.set("include_files", "true")
          params.set("show_hidden", "false")
          const response = await fetch(buildApiUrl(`/api/fs/search?${params.toString()}`), {
            signal: controller.signal,
          })
          if (!response.ok) {
            throw new Error(`Failed to search files (${response.status})`)
          }
          const payload = (await response.json()) as FileSystemSearchResponse
          const entries = Array.isArray(payload.entries) ? payload.entries : []
          return entries.map((entry) => asDragPayload(entry, workspaceRole))
        }

        const searchTasks: Array<Promise<WorkspaceReferenceDragPayload[]>> = []
        if (primaryRoot) {
          searchTasks.push(searchWorkspace(primaryRoot, "primary"))
        }
        if (secondaryRoot) {
          searchTasks.push(searchWorkspace(secondaryRoot, "secondary"))
        }
        const settledResults = await Promise.allSettled(searchTasks)
        if (isCancelled) return

        const merged = settledResults
          .filter(
            (result): result is PromiseFulfilledResult<WorkspaceReferenceDragPayload[]> =>
              result.status === "fulfilled"
          )
          .flatMap((result) => result.value)
        const deduped = Array.from(
          new Map(
            merged.map((item) => [
              `${item.workspaceRole || "primary"}:${item.type}:${item.path}`,
              item,
            ])
          ).values()
        )
        const nextSuggestions = deduped.slice(0, 12)

        setSuggestions(nextSuggestions)
        setActiveSuggestionIndex(0)
      } catch {
        if (!isCancelled) {
          setSuggestions([])
        }
      } finally {
        if (!isCancelled) {
          setIsSearching(false)
        }
      }
    }, 120)

    return () => {
      isCancelled = true
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [mentionRange, primaryWorkspacePath, secondaryWorkspacePath])

  const isSuggestionMenuOpen = Boolean(mentionRange) && (isSearching || suggestions.length > 0)

  const helperText = isDropActive
    ? "Drop a file or folder to create a workspace reference."
    : mentionRange
      ? "Use arrow keys and Enter to pick a reference."
      : mode === "edit"
        ? "Edit mode: type @ for files/folders, paste code for snippets, or attach images."
        : "Create mode: type @ for files/folders, paste code for snippets, or attach images."

  return (
    <div
      className={cn("relative isolate flex min-h-0 flex-col", className)}
      onDragEnter={(event) => {
        if (!hasWorkspaceDragPayload(event)) return
        dragDepthRef.current += 1
        setIsDropActive(true)
      }}
      onDragLeave={(event) => {
        if (!hasWorkspaceDragPayload(event)) return
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
        if (dragDepthRef.current === 0) {
          setIsDropActive(false)
        }
      }}
      onDragOver={(event) => {
        if (!hasWorkspaceDragPayload(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = "copy"
      }}
      onDrop={async (event) => {
        dragDepthRef.current = 0
        setIsDropActive(false)

        // Handle spec bundle drag
        const rawSpecPayload = event.dataTransfer.getData(SPEC_BUNDLE_DRAG_MIME_TYPE)
        const specPayload = parseSpecBundleDragPayload(rawSpecPayload)

        if (specPayload) {
          event.preventDefault()

          const workspaceRoot = resolveWorkspaceRoot("primary")
          const fallbackFilePath =
            specPayload.requirementsPath ||
            specPayload.designPath ||
            specPayload.tasksPath ||
            ""
          const targetPath = (specPayload.specPath || fallbackFilePath).trim()
          const targetType: WorkspaceReferenceDragPayload["type"] = specPayload.specPath?.trim()
            ? "dir"
            : "file"

          if (workspaceRoot && targetPath) {
            const pathReference = makeWorkspaceReference(
              {
                name: specPayload.specName,
                path: targetPath,
                type: targetType,
                workspaceRole: "primary",
              },
              workspaceRoot,
              "primary"
            )

            insertMentionReference({ reference: pathReference })
            return
          }

          if (!onFetchSpecBundle) {
            return
          }

          const content = await onFetchSpecBundle(specPayload.specName)

          if (content !== null) {
            const specRef = makeSpecBundleWorkspaceReference(specPayload.specName, content)
            insertMentionReference({ reference: specRef })
          }

          return
        }

        // Handle file / folder drag
        const rawPayload = event.dataTransfer.getData(WORKSPACE_REFERENCE_MIME_TYPE)
        const payload = parseWorkspaceReferenceDragPayload(rawPayload)

        if (!payload) return
        event.preventDefault()
        insertDroppedReference(payload)
      }}
    >
      {isSuggestionMenuOpen ? (
        <div className="absolute right-0 bottom-[calc(100%+0.5rem)] left-0 z-[120]">
          <div className="bg-popover/98 border rounded-lg shadow-xl backdrop-blur-sm overflow-hidden">
            <ScrollArea className="max-h-52 overflow-y-auto overflow-x-hidden">
              <div className="p-1">
                {isSearching ? (
                  <div className="text-muted-foreground flex items-center gap-2 px-2 py-1.5 text-xs">
                    <Loader2 className="size-3.5 animate-spin" />
                    Searching workspace...
                  </div>
                ) : (
                  suggestions.map((suggestion, index) => {
                    const isActive = index === activeSuggestionIndex
                    const workspaceRole = suggestion.workspaceRole === "secondary" ? "secondary" : "primary"
                    const iconClassName = workspaceRole === "secondary"
                      ? mentionToneClass("secondary")
                      : suggestion.type === "dir"
                        ? "text-primary"
                        : "text-muted-foreground"
                    return (
                      <button
                        key={`${workspaceRole}:${suggestion.type}:${suggestion.path}`}
                        type="button"
                        className={cn(
                          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                          isActive ? "bg-accent text-accent-foreground" : "hover:bg-accent/70"
                        )}
                        onMouseDown={(event) => {
                          event.preventDefault()
                          applySuggestion(suggestion)
                        }}
                      >
                        {suggestion.type === "dir" ? (
                          <Folder className={cn("size-3.5 shrink-0", iconClassName)} />
                        ) : (
                          <File className={cn("size-3.5 shrink-0", iconClassName)} />
                        )}
                        <span className={cn("truncate font-medium", mentionToneClass(workspaceRole))}>
                          @{suggestion.name}
                        </span>
                        <span className="text-muted-foreground ml-auto text-[10px] uppercase">
                          [{workspaceRole === "secondary" ? "reference" : "primary"}]
                        </span>
                      </button>
                    )
                  })
                )}
              </div>
            </ScrollArea>
          </div>
        </div>
      ) : null}

      <div
        className={cn(
          "border-input bg-background flex min-h-0 flex-1 flex-col rounded-xl border p-2 shadow-xs transition-colors",
          isDropActive && "border-sky-500/60 bg-sky-500/5"
        )}
      >
        {references.length > 0 ? (
          <div className="mb-2 flex flex-wrap items-center gap-2 px-1">
            {references.map((reference) => {
              let icon: React.ReactNode = <File className="size-3" />
              let detail = ""
              let chipColor: "warning" | "info" | "purple" | "grey" | "success" = "info"
              let chipClassName = ""

              if (reference.kind === "dir") {
                icon = <Folder className="size-3" />
                detail = reference.workspaceRole === "secondary"
                  ? `ref · ${reference.workspacePath}`
                  : reference.workspacePath
                chipColor = reference.workspaceRole === "secondary" ? "warning" : "info"
              } else if (reference.kind === "file") {
                icon = <File className="size-3" />
                detail = reference.workspaceRole === "secondary"
                  ? `ref · ${reference.workspacePath}`
                  : reference.workspacePath
                chipColor = reference.workspaceRole === "secondary" ? "warning" : "info"
              } else if (reference.kind === "snippet") {
                icon = <Code2 className="size-3" />
                detail = `${reference.content.length} chars`
                chipColor = "success"
                chipClassName = /^lines\s+\d+-\d+$/i.test(reference.name.trim())
                  ? "border-teal-500/50 text-teal-600 dark:text-teal-400"
                  : "border-rose-500/50 text-rose-600 dark:text-rose-400"
              } else if (reference.kind === "spec") {
                icon = <BookOpen className="size-3" />
                detail = "spec bundle"
                chipColor = "info"
              } else {
                icon = <ImagePlus className="size-3" />
                detail = (reference as { mimeType: string }).mimeType
                chipColor = "purple"
              }

              return (
                <Chip
                  key={reference.id}
                  color={chipColor}
                  variant="outline"
                  className={cn(
                    "inline-flex max-w-full items-center gap-2 rounded-full px-2.5 py-1 text-xs",
                    chipClassName
                  )}
                >
                  {icon}
                  <span className="max-w-[200px] truncate">@{reference.name}</span>
                  <span className="text-muted-foreground max-w-[220px] truncate text-[10px]">{detail}</span>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      setReferences((current) => current.filter((item) => item.id !== reference.id))
                    }}
                    aria-label={`Remove @${reference.name} reference`}
                  >
                    <X className="size-3" />
                  </button>
                </Chip>
              )
            })}
          </div>
        ) : null}

        <div className="relative min-h-24 flex-1" style={{ minHeight: `${textareaHeightPx}px` }}>
          <div
            ref={highlightRef}
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 overflow-auto px-2 py-1.5 !font-sans !text-[14px] leading-6 whitespace-pre-wrap break-words"
          >
            {value.length === 0 ? (
              <span className="text-muted-foreground">{placeholder}</span>
            ) : (
              renderHighlightedText(value, references)
            )}
          </div>

          <textarea
            ref={textareaRef}
            value={value}
            disabled={isProcessing}
            aria-label="Prompt input"
            wrap="soft"
            className="caret-foreground selection:bg-sky-500/30 absolute inset-0 h-full min-h-0 w-full resize-none overflow-auto bg-transparent px-2 py-1.5 !font-sans !text-[14px] leading-6 text-transparent outline-none"
            onChange={(event) => {
              const nextValue = event.target.value
              setValue(nextValue)
              syncMentionRange(nextValue, event.target.selectionStart ?? nextValue.length)
              updateTextareaHeight(event.target)
              syncOverlayScroll(event.target.scrollTop, event.target.scrollLeft)
            }}
            onPaste={(event) => {
              const pastedText = event.clipboardData.getData("text/plain").trim()
              if (!pastedText) return

              const clipboardLineRangeFromMime = parseEditorLineRangePayload(
                event.clipboardData.getData(EDITOR_LINE_RANGE_MIME_TYPE)
              )
              const clipboardLineRange = clipboardLineRangeFromMime ?? resolveLastEditorClipboardLineRange(pastedText)

              const shouldAttachSnippet = Boolean(clipboardLineRange) || shouldCapturePastedSnippet(pastedText)
              if (!shouldAttachSnippet) return

              event.preventDefault()
              setAttachmentError(null)

              const normalizedSnippet = pastedText.length > MAX_SNIPPET_LENGTH
                ? pastedText.slice(0, MAX_SNIPPET_LENGTH)
                : pastedText

              const snippetInfo = clipboardLineRange
                ? {
                    name: `Lines ${clipboardLineRange.lineStart}-${clipboardLineRange.lineEnd}`,
                    lineStart: clipboardLineRange.lineStart,
                    lineEnd: clipboardLineRange.lineEnd,
                  }
                : nextSnippetName(references, normalizedSnippet)
              const snippetReference = makeSnippetWorkspaceReference({
                name: snippetInfo.name,
                content: normalizedSnippet,
                lineStart: snippetInfo.lineStart,
                lineEnd: snippetInfo.lineEnd,
              })

              insertMentionReference({
                reference: snippetReference,
              })
            }}
            onScroll={(event) => {
              syncOverlayScroll(event.currentTarget.scrollTop, event.currentTarget.scrollLeft)
            }}
            onClick={(event) => {
              syncMentionRange(event.currentTarget.value, event.currentTarget.selectionStart ?? event.currentTarget.value.length)
            }}
            onKeyUp={(event) => {
              syncMentionRange(event.currentTarget.value, event.currentTarget.selectionStart ?? event.currentTarget.value.length)
            }}
            onKeyDown={(event) => {
              if (isSuggestionMenuOpen && suggestions.length > 0) {
                if (event.key === "ArrowDown") {
                  event.preventDefault()
                  setActiveSuggestionIndex((current) => (current + 1) % suggestions.length)
                  return
                }

                if (event.key === "ArrowUp") {
                  event.preventDefault()
                  setActiveSuggestionIndex((current) => (current - 1 + suggestions.length) % suggestions.length)
                  return
                }

                if (event.key === "Enter" || event.key === "Tab") {
                  event.preventDefault()
                  const suggestion = suggestions[activeSuggestionIndex]
                  if (suggestion) {
                    applySuggestion(suggestion)
                  }
                  return
                }

                if (event.key === "Escape") {
                  event.preventDefault()
                  setMentionRange(null)
                  setSuggestions([])
                  setActiveSuggestionIndex(0)
                  return
                }
              }

              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                void submitPrompt()
              }
            }}
          />
        </div>

        {attachmentError ? <p className="mt-2 px-1 text-xs text-rose-600">{attachmentError}</p> : null}

        <div className="mt-2 flex items-center justify-between px-1">
          <span className="text-muted-foreground text-xs">{helperText}</span>

          <div className="flex items-center gap-2">
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(event) => {
                const files = Array.from(event.target.files || [])
                event.currentTarget.value = ""
                void handleAddImages(files)
              }}
            />

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="rounded-full"
              disabled={isProcessing}
              aria-label="Attach image"
              onClick={() => {
                imageInputRef.current?.click()
              }}
            >
              <ImagePlus className="size-4" />
            </Button>

            <Button
              type="button"
              onClick={() => {
                void submitPrompt()
              }}
              size="icon-sm"
              className="rounded-full"
              disabled={isProcessing || value.trim().length === 0}
              aria-label="Send prompt"
            >
              {isProcessing ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default WorkspaceMentionPromptInput
