export const EDITOR_LINE_RANGE_MIME_TYPE = 'application/x-assist-editor-line-range'

type EditorLineRangePayload = {
  line_start: number
  line_end: number
}

type EditorLineRange = {
  lineStart: number
  lineEnd: number
}

type EditorClipboardSnapshot = {
  text: string
  lineStart: number
  lineEnd: number
  copiedAt: number
}

const MAX_EDITOR_CLIPBOARD_SNAPSHOT_AGE_MS = 5 * 60 * 1000

let lastEditorClipboardSnapshot: EditorClipboardSnapshot | null = null

const isPositiveInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value > 0

export const serializeEditorLineRangePayload = ({
  lineStart,
  lineEnd,
}: EditorLineRange) => {
  return JSON.stringify({
    line_start: lineStart,
    line_end: lineEnd,
  } satisfies EditorLineRangePayload)
}

export const parseEditorLineRangePayload = (rawValue: string | null | undefined): EditorLineRange | null => {
  if (!rawValue) return null

  try {
    const parsed = JSON.parse(rawValue) as Partial<EditorLineRangePayload>
    const lineStart = parsed.line_start
    const lineEnd = parsed.line_end

    if (!isPositiveInteger(lineStart) || !isPositiveInteger(lineEnd)) {
      return null
    }

    if (lineEnd < lineStart) {
      return null
    }

    return {
      lineStart,
      lineEnd,
    }
  } catch {
    return null
  }
}

const normalizeClipboardText = (value: string) => value.replace(/\r\n/g, '\n').trim()

export const rememberLastEditorClipboardSnapshot = ({
  text,
  lineStart,
  lineEnd,
}: {
  text: string
  lineStart: number
  lineEnd: number
}) => {
  const normalizedText = normalizeClipboardText(text)
  if (!normalizedText) {
    lastEditorClipboardSnapshot = null

    return
  }

  lastEditorClipboardSnapshot = {
    text: normalizedText,
    lineStart,
    lineEnd,
    copiedAt: Date.now(),
  }
}

export const resolveLastEditorClipboardLineRange = (value: string): EditorLineRange | null => {
  if (!lastEditorClipboardSnapshot) return null

  const snapshotAgeMs = Date.now() - lastEditorClipboardSnapshot.copiedAt
  if (snapshotAgeMs > MAX_EDITOR_CLIPBOARD_SNAPSHOT_AGE_MS) {
    lastEditorClipboardSnapshot = null

    return null
  }

  const normalizedValue = normalizeClipboardText(value)
  if (normalizedValue !== lastEditorClipboardSnapshot.text) {
    return null
  }

  return {
    lineStart: lastEditorClipboardSnapshot.lineStart,
    lineEnd: lastEditorClipboardSnapshot.lineEnd,
  }
}
