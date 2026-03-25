export const WORKSPACE_REFERENCE_MIME_TYPE = "application/x-assist-workspace-reference"
export const SPEC_BUNDLE_DRAG_MIME_TYPE = "application/x-assist-spec-bundle"
const MAX_PROMPT_CONTEXT_SNIPPET_CONTENT_LENGTH = 20_000
const PROMPT_CONTEXT_TRUNCATION_NOTICE = "\n\n[... content truncated to fit prompt context limits ...]"

export type WorkspaceReferenceKind = "file" | "dir" | "snippet" | "image" | "spec"
export type WorkspaceRole = "primary" | "secondary"

type WorkspaceFileReference = {
  id: string
  name: string
  kind: "file"
  absolutePath: string
  workspacePath: string
  workspaceRole: WorkspaceRole
}

type WorkspaceDirReference = {
  id: string
  name: string
  kind: "dir"
  absolutePath: string
  workspacePath: string
  workspaceRole: WorkspaceRole
}

type WorkspacePathReference = WorkspaceFileReference | WorkspaceDirReference

type WorkspaceSnippetReference = {
  id: string
  name: string
  kind: "snippet"
  content: string
  lineStart?: number
  lineEnd?: number
}

type WorkspaceImageReference = {
  id: string
  name: string
  kind: "image"
  mimeType: string
  dataUrl: string
}

type WorkspaceSpecReference = {
  id: string
  name: string
  kind: "spec"
  specName: string
  content: string
}

export type WorkspaceReference = WorkspacePathReference | WorkspaceSnippetReference | WorkspaceImageReference | WorkspaceSpecReference

type WorkspacePathReferenceContextItem = {
  name: string
  type: "file" | "folder"
  path: string
  workspace_role: WorkspaceRole
  absolute_path?: string
}

type WorkspaceSnippetReferenceContextItem = {
  name: string
  type: "snippet"
  content: string
  line_start?: number
  line_end?: number
}

type WorkspaceImageReferenceContextItem = {
  name: string
  type: "image"
  mime_type: string
  data_url: string
}

export type WorkspaceReferenceContextItem =
  | WorkspacePathReferenceContextItem
  | WorkspaceSnippetReferenceContextItem
  | WorkspaceImageReferenceContextItem

export type WorkspaceSpecDragPayload = {
  specName: string
  specPath?: string
  requirementsPath?: string
  designPath?: string
  tasksPath?: string
}

export type WorkspaceReferenceDragPayload = {
  name: string
  path: string
  type: "file" | "dir"
  workspaceRole?: WorkspaceRole
}

const truncatePromptContextContent = (value: string) => {
  const normalized = String(value || "")

  if (normalized.length <= MAX_PROMPT_CONTEXT_SNIPPET_CONTENT_LENGTH) {
    return normalized
  }

  const maxBaseLength = Math.max(
    0,
    MAX_PROMPT_CONTEXT_SNIPPET_CONTENT_LENGTH - PROMPT_CONTEXT_TRUNCATION_NOTICE.length
  )

  return `${normalized.slice(0, maxBaseLength)}${PROMPT_CONTEXT_TRUNCATION_NOTICE}`
}

const normalizePath = (value: string) => value.replace(/\\/g, "/").replace(/\/+$/, "")

export const toWorkspacePath = (absolutePath: string, workspaceRoot: string) => {
  const normalizedAbsolute = normalizePath(absolutePath)
  const normalizedWorkspace = normalizePath(workspaceRoot)

  if (!normalizedWorkspace) {
    return normalizedAbsolute || "."
  }

  if (normalizedAbsolute === normalizedWorkspace) {
    return "."
  }

  if (normalizedAbsolute.startsWith(`${normalizedWorkspace}/`)) {
    const relative = normalizedAbsolute.slice(normalizedWorkspace.length + 1)
    return relative ? `./${relative}` : "."
  }

  return normalizedAbsolute
}

export const makeWorkspaceReference = (
  payload: WorkspaceReferenceDragPayload,
  workspaceRoot: string,
  role: WorkspaceRole = "primary"
): WorkspaceReference => {
  const workspaceRole = payload.workspaceRole || role
  const workspacePath = toWorkspacePath(payload.path, workspaceRoot)

  if (payload.type === "dir") {
    return {
      id: `${workspaceRole}:${payload.type}:${workspacePath}`,
      name: payload.name,
      kind: "dir",
      absolutePath: payload.path,
      workspacePath,
      workspaceRole,
    }
  }

  return {
    id: `${workspaceRole}:${payload.type}:${workspacePath}`,
    name: payload.name,
    kind: "file",
    absolutePath: payload.path,
    workspacePath,
    workspaceRole,
  }
}

const sanitizeReferenceName = (value: string) => value.replace(/\s+/g, " ").trim()

const slugReferenceName = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "context"

export const makeSnippetWorkspaceReference = ({
  name,
  content,
  lineStart,
  lineEnd,
}: {
  name: string
  content: string
  lineStart?: number
  lineEnd?: number
}): WorkspaceReference => {
  const normalizedName = sanitizeReferenceName(name) || "Code"
  const normalizedContent = truncatePromptContextContent(content.trim())
  return {
    id: `snippet:${slugReferenceName(normalizedName)}:${normalizedContent.length}:${Date.now().toString(36)}`,
    name: normalizedName,
    kind: "snippet",
    content: normalizedContent,
    lineStart,
    lineEnd,
  }
}

export const makeImageWorkspaceReference = ({
  name,
  mimeType,
  dataUrl,
}: {
  name: string
  mimeType: string
  dataUrl: string
}): WorkspaceReference => {
  const normalizedName = sanitizeReferenceName(name) || "Image"
  return {
    id: `image:${slugReferenceName(normalizedName)}:${dataUrl.length}:${Date.now().toString(36)}`,
    name: normalizedName,
    kind: "image",
    mimeType: mimeType || "image/png",
    dataUrl,
  }
}

export const makeSpecBundleWorkspaceReference = (specName: string, content: string): WorkspaceReference => {
  const normalizedContent = truncatePromptContextContent(content)

  return {
    id: `spec:${specName}`,
    name: specName,
    kind: "spec",
    specName,
    content: normalizedContent,
  }
}

export const serializeSpecBundleDragPayload = (payload: WorkspaceSpecDragPayload): string =>
  JSON.stringify(payload)

export const parseSpecBundleDragPayload = (raw: string | null | undefined): WorkspaceSpecDragPayload | null => {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<WorkspaceSpecDragPayload>
    const specName = String(parsed.specName || "").trim()
    if (!specName) return null

    const specPath = String(parsed.specPath || "").trim()
    const requirementsPath = String(parsed.requirementsPath || "").trim()
    const designPath = String(parsed.designPath || "").trim()
    const tasksPath = String(parsed.tasksPath || "").trim()

    return {
      specName,
      specPath: specPath || undefined,
      requirementsPath: requirementsPath || undefined,
      designPath: designPath || undefined,
      tasksPath: tasksPath || undefined,
    }
  } catch {
    return null
  }
}

export const serializeWorkspaceReferenceDragPayload = (payload: WorkspaceReferenceDragPayload) =>
  JSON.stringify(payload)

export const parseWorkspaceReferenceDragPayload = (rawValue: string | null | undefined): WorkspaceReferenceDragPayload | null => {
  if (!rawValue) return null

  try {
    const parsed = JSON.parse(rawValue) as Partial<WorkspaceReferenceDragPayload>
    if (!parsed || (parsed.type !== "file" && parsed.type !== "dir")) {
      return null
    }

    const name = String(parsed.name || "").trim()
    const path = String(parsed.path || "").trim()
    if (!name || !path) {
      return null
    }

    return {
      name,
      path,
      type: parsed.type,
      workspaceRole: parsed.workspaceRole === "secondary" ? "secondary" : "primary",
    }
  } catch {
    return null
  }
}

const dedupeWorkspaceReferences = (references: WorkspaceReference[]) =>
  Array.from(new Map(references.map((reference) => [reference.id, reference])).values())

const toReferenceToken = (reference: WorkspaceReference) => {
  const workspaceTag = reference.kind === "dir" || reference.kind === "file"
    ? reference.workspaceRole === "secondary"
      ? " [secondary]"
      : " [primary]"
    : ""

  if (reference.kind === "dir") {
    if (reference.workspaceRole === "secondary") {
      return `@folder${workspaceTag} ${reference.workspacePath} (abs: ${reference.absolutePath})`
    }
    return `@folder${workspaceTag} ${reference.workspacePath}`
  }

  if (reference.kind === "file") {
    if (reference.workspaceRole === "secondary") {
      return `@file${workspaceTag} ${reference.workspacePath} (abs: ${reference.absolutePath})`
    }
    return `@file${workspaceTag} ${reference.workspacePath}`
  }

  if (reference.kind === "snippet") {
    const hasLineRange = Number.isFinite(reference.lineStart) && Number.isFinite(reference.lineEnd)
    if (hasLineRange) {
      return `@snippet lines ${reference.lineStart}-${reference.lineEnd}`
    }
    return `@snippet ${reference.name}`
  }

  if (reference.kind === "spec") {
    return `@spec ${reference.specName}`
  }

  return `@image ${reference.name}`
}

export const buildWorkspaceReferenceContext = (references: WorkspaceReference[]): WorkspaceReferenceContextItem[] =>
  dedupeWorkspaceReferences(references).map((reference) => {
    if (reference.kind === "dir" || reference.kind === "file") {
      return {
        name: reference.name,
        type: reference.kind === "dir" ? "folder" : "file",
        path: reference.workspacePath,
        workspace_role: reference.workspaceRole,
        absolute_path: reference.absolutePath,
      }
    }

    if (reference.kind === "snippet") {
      return {
        name: reference.name,
        type: "snippet",
        content: truncatePromptContextContent(reference.content),
        line_start: reference.lineStart,
        line_end: reference.lineEnd,
      }
    }

    if (reference.kind === "image") {
      return {
        name: reference.name,
        type: "image",
        mime_type: reference.mimeType,
        data_url: reference.dataUrl,
      }
    }

    if (reference.kind === "spec") {
      return {
        name: reference.name,
        type: "snippet",
        content: truncatePromptContextContent(reference.content),
      }
    }

    throw new Error(`Unsupported workspace reference kind: ${(reference as { kind: string }).kind}`)
  })

const replaceReferenceMentions = (
  prompt: string,
  references: WorkspaceReference[],
  toToken: (reference: WorkspaceReference) => string
) => {
  const dedupedReferences = dedupeWorkspaceReferences(references)
  const referenceQueuesByMention = new Map<string, WorkspaceReference[]>()

  dedupedReferences.forEach((reference) => {
    const mentionToken = `@${reference.name}`.trim()
    if (!mentionToken || mentionToken === "@") return

    const mentionKey = mentionToken.toLowerCase()
    const existing = referenceQueuesByMention.get(mentionKey) || []
    referenceQueuesByMention.set(mentionKey, [...existing, reference])
  })

  if (referenceQueuesByMention.size === 0) return prompt

  const mentionUsageByToken = new Map<string, number>()
  const mentionCandidates = Array.from(referenceQueuesByMention.keys())
    .map((mentionKey) => ({ mentionKey, mentionToken: mentionKey }))
    .sort((left, right) => right.mentionToken.length - left.mentionToken.length)
  const isMentionBoundary = (char: string | undefined) =>
    !char || /\s|[.,;:!?)}\]]/.test(char)
  let output = ""
  let cursor = 0

  while (cursor < prompt.length) {
    const atIndex = prompt.indexOf("@", cursor)

    if (atIndex < 0) {
      output += prompt.slice(cursor)
      break
    }

    output += prompt.slice(cursor, atIndex)

    const lowerTail = prompt.slice(atIndex).toLowerCase()
    const matchedCandidate = mentionCandidates.find((candidate) => {
      if (!lowerTail.startsWith(candidate.mentionToken)) return false
      const boundaryChar = prompt[atIndex + candidate.mentionToken.length]
      return isMentionBoundary(boundaryChar)
    })

    if (!matchedCandidate) {
      output += "@"
      cursor = atIndex + 1
      continue
    }

    const mentionToken = prompt.slice(atIndex, atIndex + matchedCandidate.mentionToken.length)
    const queue = referenceQueuesByMention.get(matchedCandidate.mentionKey)

    if (!queue || queue.length === 0) {
      output += mentionToken
      cursor = atIndex + mentionToken.length
      continue
    }

    const usageCount = mentionUsageByToken.get(matchedCandidate.mentionKey) || 0
    const queueIndex = Math.min(usageCount, queue.length - 1)
    const reference = queue[queueIndex]
    mentionUsageByToken.set(matchedCandidate.mentionKey, usageCount + 1)

    output += toToken(reference)
    cursor = atIndex + mentionToken.length
  }

  return output
}

export const buildInlinePromptWithWorkspaceReferences = (
  prompt: string,
  references: WorkspaceReference[]
) => {
  const trimmedPrompt = prompt.trim()
  if (!trimmedPrompt) return ""
  if (references.length === 0) return trimmedPrompt

  return replaceReferenceMentions(trimmedPrompt, references, toReferenceToken)
}

export const buildPromptWithWorkspaceReferences = (
  prompt: string,
  references: WorkspaceReference[]
) => {
  const inlineResolved = buildInlinePromptWithWorkspaceReferences(prompt, references)
  if (!inlineResolved) return ""
  if (references.length === 0) return inlineResolved

  const dedupedReferences = dedupeWorkspaceReferences(references)
  const referenceLines = dedupedReferences.map(
    (reference) => `- ${toReferenceToken(reference)}`
  )

  return `${inlineResolved}\n\nWorkspace references:\n${referenceLines.join("\n")}`
}
