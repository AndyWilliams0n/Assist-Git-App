import * as React from 'react'
import { Loader2 } from 'lucide-react'

import {
  EDITOR_LINE_RANGE_MIME_TYPE,
  rememberLastEditorClipboardSnapshot,
  serializeEditorLineRangePayload,
} from '@/shared/utils/editor-clipboard.ts'
import { cn } from '@/shared/utils/utils.ts'

const MARKDOWN_LANGUAGE = 'markdown'
const AURORA_X_THEME = 'aurora-x'
const GITHUB_LIGHT_THEME = 'github-light'
const DEFAULT_EDITOR_FONT_FAMILY =
  'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, Courier New, monospace)'
const DEFAULT_EDITOR_FONT_STYLE = 'normal'
const DEFAULT_EDITOR_FONT_WEIGHT = '400'
const DEFAULT_EDITOR_FONT_SIZE_PX = 14
const DEFAULT_EDITOR_LETTER_SPACING = 'normal'
const DEFAULT_EDITOR_TAB_SIZE = '2'
const DEFAULT_EDITOR_PADDING_PX = 12
const DEFAULT_EDITOR_LINE_HEIGHT_PX = 24

type MarkdownHighlighter = {
  codeToHtml: (code: string, options: { lang: string; theme: string }) => string
}

type HighlightedContent = {
  source: string
  html: string
}

type EditorSelectionRange = {
  start: number
  end: number
}

type LineRange = {
  startLineIndex: number
  endLineIndex: number
}

type VisualRow = {
  lineIndex: number
  lineLabel: string
}

let markdownHighlighterPromise: Promise<MarkdownHighlighter> | null = null

const getMarkdownHighlighter = () => {
  if (!markdownHighlighterPromise) {
    markdownHighlighterPromise = Promise.all([
      import('shiki/core'),
      import('shiki/engine/javascript'),
      import('@shikijs/langs/markdown'),
      import('@shikijs/themes/aurora-x'),
      import('@shikijs/themes/github-light'),
    ]).then(([shikiCore, shikiEngine, markdownLanguageModule, auroraXThemeModule, githubLightThemeModule]) => {
      return shikiCore.createHighlighterCore({
        themes: [auroraXThemeModule.default, githubLightThemeModule.default],
        langs: [markdownLanguageModule.default],
        engine: shikiEngine.createJavaScriptRegexEngine(),
      })
    })
  }

  return markdownHighlighterPromise
}

type EditorProps = {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  isLoading?: boolean
  loadingMessage?: string
  isWordWrapEnabled?: boolean
  placeholder?: string
  ariaLabel?: string
  className?: string
  textareaClassName?: string
  colorScheme?: 'dark' | 'light'
}

function Editor({
  value,
  onChange,
  disabled = false,
  isLoading = false,
  loadingMessage = 'Loading content...',
  isWordWrapEnabled = true,
  placeholder = '',
  ariaLabel = 'Editor',
  className,
  textareaClassName,
  colorScheme = 'dark',
}: EditorProps) {
  const lineNumbersRef = React.useRef<HTMLDivElement | null>(null)

  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null)

  const lineHighlightLayerRef = React.useRef<HTMLDivElement | null>(null)

  const highlightLayerRef = React.useRef<HTMLDivElement | null>(null)

  const lineMeasureRef = React.useRef<HTMLDivElement | null>(null)

  const lineDragStateRef = React.useRef<{ pointerId: number; anchorLineIndex: number } | null>(null)

  const [highlightedContent, setHighlightedContent] = React.useState<HighlightedContent | null>(null)

  const [selectionRange, setSelectionRange] = React.useState<EditorSelectionRange | null>(null)

  const [draggedLineRange, setDraggedLineRange] = React.useState<LineRange | null>(null)

  const [wrappedLineRows, setWrappedLineRows] = React.useState<number[]>([])

  const [wrappedLineHeightsPx, setWrappedLineHeightsPx] = React.useState<number[]>([])

  const [editorViewportWidth, setEditorViewportWidth] = React.useState(0)

  const [editorPaddingTopPx, setEditorPaddingTopPx] = React.useState(DEFAULT_EDITOR_PADDING_PX)

  const [editorPaddingRightPx, setEditorPaddingRightPx] = React.useState(DEFAULT_EDITOR_PADDING_PX)

  const [editorPaddingBottomPx, setEditorPaddingBottomPx] = React.useState(DEFAULT_EDITOR_PADDING_PX)

  const [editorPaddingLeftPx, setEditorPaddingLeftPx] = React.useState(DEFAULT_EDITOR_PADDING_PX)

  const [editorLineHeightPx, setEditorLineHeightPx] = React.useState(DEFAULT_EDITOR_LINE_HEIGHT_PX)

  const [editorFontFamily, setEditorFontFamily] = React.useState(DEFAULT_EDITOR_FONT_FAMILY)

  const [editorFontStyle, setEditorFontStyle] = React.useState(DEFAULT_EDITOR_FONT_STYLE)

  const [editorFontWeight, setEditorFontWeight] = React.useState(DEFAULT_EDITOR_FONT_WEIGHT)

  const [editorFontSizePx, setEditorFontSizePx] = React.useState(DEFAULT_EDITOR_FONT_SIZE_PX)

  const [editorLetterSpacing, setEditorLetterSpacing] = React.useState(DEFAULT_EDITOR_LETTER_SPACING)

  const [editorTabSize, setEditorTabSize] = React.useState(DEFAULT_EDITOR_TAB_SIZE)

  const logicalLines = React.useMemo(() => value.split('\n'), [value])

  const lineCount = Math.max(1, logicalLines.length)

  const syncEditorMetrics = React.useCallback(() => {
    const textareaElement = textareaRef.current

    if (!textareaElement || typeof window === 'undefined') return

    const computedStyle = window.getComputedStyle(textareaElement)

    const nextFontFamily = computedStyle.fontFamily
    const nextFontStyle = computedStyle.fontStyle
    const nextFontWeight = computedStyle.fontWeight
    const nextFontSizePx = Number.parseFloat(computedStyle.fontSize)
    const nextLetterSpacing = computedStyle.letterSpacing
    const nextTabSize = computedStyle.getPropertyValue('tab-size').trim()
    const nextLineHeight = Number.parseFloat(computedStyle.lineHeight)

    const paddingTop = Number.parseFloat(computedStyle.paddingTop)

    const paddingLeft = Number.parseFloat(computedStyle.paddingLeft)

    const paddingBottom = Number.parseFloat(computedStyle.paddingBottom)

    const paddingRight = Number.parseFloat(computedStyle.paddingRight)
    const fallbackLineHeightPx = Number.isFinite(nextFontSizePx)
      ? Math.round(nextFontSizePx * (DEFAULT_EDITOR_LINE_HEIGHT_PX / DEFAULT_EDITOR_FONT_SIZE_PX))
      : DEFAULT_EDITOR_LINE_HEIGHT_PX

    setEditorViewportWidth(textareaElement.clientWidth)

    setEditorLineHeightPx(Number.isFinite(nextLineHeight) ? nextLineHeight : fallbackLineHeightPx)

    setEditorFontFamily(nextFontFamily || DEFAULT_EDITOR_FONT_FAMILY)

    setEditorFontStyle(nextFontStyle || DEFAULT_EDITOR_FONT_STYLE)

    setEditorFontWeight(nextFontWeight || DEFAULT_EDITOR_FONT_WEIGHT)

    setEditorFontSizePx(Number.isFinite(nextFontSizePx) ? nextFontSizePx : DEFAULT_EDITOR_FONT_SIZE_PX)

    setEditorLetterSpacing(nextLetterSpacing || DEFAULT_EDITOR_LETTER_SPACING)

    setEditorTabSize(nextTabSize || DEFAULT_EDITOR_TAB_SIZE)

    setEditorPaddingTopPx(Number.isFinite(paddingTop) ? paddingTop : DEFAULT_EDITOR_PADDING_PX)

    setEditorPaddingRightPx(Number.isFinite(paddingRight) ? paddingRight : DEFAULT_EDITOR_PADDING_PX)

    setEditorPaddingBottomPx(Number.isFinite(paddingBottom) ? paddingBottom : DEFAULT_EDITOR_PADDING_PX)

    setEditorPaddingLeftPx(Number.isFinite(paddingLeft) ? paddingLeft : DEFAULT_EDITOR_PADDING_PX)
  }, [])

  const lineStartOffsets = React.useMemo(() => {
    return logicalLines
      .reduce<{ offsets: number[]; nextOffset: number }>(
        (accumulator, lineText, lineIndex) => {
          const lineOffset = accumulator.nextOffset
          const separatorLength = lineIndex < logicalLines.length - 1 ? 1 : 0

          return {
            offsets: [...accumulator.offsets, lineOffset],
            nextOffset: lineOffset + lineText.length + separatorLength,
          }
        },
        {
          offsets: [],
          nextOffset: 0,
        }
      )
      .offsets
  }, [logicalLines])

  const visualRows = React.useMemo<VisualRow[]>(
    () =>
      logicalLines.flatMap((_, lineIndex) => {
        const visualRowCount = isWordWrapEnabled ? wrappedLineRows[lineIndex] || 1 : 1

        return Array.from({ length: visualRowCount }, (_, rowIndex) => ({
          lineIndex,
          lineLabel: rowIndex === 0 ? `${lineIndex + 1}` : '',
        }))
      }),
    [isWordWrapEnabled, logicalLines, wrappedLineRows]
  )

  const lineIndexByVisualRow = React.useMemo(() => visualRows.map((row) => row.lineIndex), [visualRows])

  const syncOverlayScroll = React.useCallback((scrollTop: number, scrollLeft: number) => {
    if (lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = scrollTop
    }

    if (lineHighlightLayerRef.current) {
      lineHighlightLayerRef.current.scrollTop = scrollTop
      lineHighlightLayerRef.current.scrollLeft = scrollLeft
    }

    if (highlightLayerRef.current) {
      highlightLayerRef.current.scrollTop = scrollTop
      highlightLayerRef.current.scrollLeft = scrollLeft
    }
  }, [])

  const getLineIndexFromTextOffset = React.useCallback(
    (offset: number) => {
      const clampedOffset = Math.max(0, Math.min(offset, value.length))

      let low = 0
      let high = lineStartOffsets.length - 1
      let resolvedLineIndex = 0

      while (low <= high) {
        const middleIndex = Math.floor((low + high) / 2)

        if (lineStartOffsets[middleIndex] <= clampedOffset) {
          resolvedLineIndex = middleIndex
          low = middleIndex + 1
        } else {
          high = middleIndex - 1
        }
      }

      return resolvedLineIndex
    },
    [lineStartOffsets, value.length]
  )

  const resolveLineRangeFromSelectionOffsets = React.useCallback(
    (nextSelectionRange: EditorSelectionRange | null): LineRange | null => {
      if (!nextSelectionRange) return null

      const normalizedStartOffset = Math.max(0, Math.min(nextSelectionRange.start, nextSelectionRange.end))
      const normalizedEndOffset = Math.max(0, Math.max(nextSelectionRange.start, nextSelectionRange.end))

      if (normalizedEndOffset === normalizedStartOffset) return null

      const startLineIndex = getLineIndexFromTextOffset(normalizedStartOffset)
      const endLineIndex = getLineIndexFromTextOffset(Math.max(normalizedStartOffset, normalizedEndOffset - 1))

      return {
        startLineIndex: Math.min(startLineIndex, endLineIndex),
        endLineIndex: Math.max(startLineIndex, endLineIndex),
      }
    },
    [getLineIndexFromTextOffset]
  )

  const setTextareaSelectionForLineRange = React.useCallback(
    (startLineIndex: number, endLineIndex: number) => {
      const textareaElement = textareaRef.current

      if (!textareaElement) return

      const normalizedStartLineIndex = Math.max(0, Math.min(startLineIndex, endLineIndex))
      const normalizedEndLineIndex = Math.min(lineCount - 1, Math.max(startLineIndex, endLineIndex))
      const startOffset = lineStartOffsets[normalizedStartLineIndex] ?? 0
      const lineEndOffset = (lineStartOffsets[normalizedEndLineIndex] ?? 0) + (logicalLines[normalizedEndLineIndex]?.length ?? 0)
      const hasTrailingNewLine = normalizedEndLineIndex < lineCount - 1
      const endOffset = hasTrailingNewLine ? lineEndOffset + 1 : lineEndOffset

      textareaElement.focus()
      textareaElement.setSelectionRange(startOffset, endOffset)

      setSelectionRange({
        start: startOffset,
        end: endOffset,
      })
    },
    [lineCount, lineStartOffsets, logicalLines]
  )

  const getLineIndexFromPointerPosition = React.useCallback(
    (clientY: number) => {
      const lineNumbersElement = lineNumbersRef.current

      if (!lineNumbersElement || lineIndexByVisualRow.length === 0) return 0

      const gutterRect = lineNumbersElement.getBoundingClientRect()
      const verticalOffset = clientY - gutterRect.top + lineNumbersElement.scrollTop - editorPaddingTopPx
      const visualRowIndex = Math.max(
        0,
        Math.min(lineIndexByVisualRow.length - 1, Math.floor(verticalOffset / Math.max(editorLineHeightPx, 1)))
      )

      return lineIndexByVisualRow[visualRowIndex] ?? 0
    },
    [editorLineHeightPx, editorPaddingTopPx, lineIndexByVisualRow]
  )

  const syncSelectionFromTextarea = React.useCallback(() => {
    const textareaElement = textareaRef.current

    if (!textareaElement) return

    setSelectionRange({
      start: textareaElement.selectionStart,
      end: textareaElement.selectionEnd,
    })
  }, [])

  const resolveClipboardLineRangePayload = React.useCallback(
    (selectionStart: number, selectionEnd: number): string | null => {
      const normalizedStartOffset = Math.max(0, Math.min(selectionStart, selectionEnd))
      const normalizedEndOffset = Math.max(selectionStart, selectionEnd)

      if (normalizedEndOffset === normalizedStartOffset) return null

      const startLineIndex = getLineIndexFromTextOffset(normalizedStartOffset)
      const endLineIndex = getLineIndexFromTextOffset(Math.max(normalizedStartOffset, normalizedEndOffset - 1))
      const lineStart = Math.min(startLineIndex, endLineIndex) + 1
      const lineEnd = Math.max(startLineIndex, endLineIndex) + 1
      const selectedText = value.slice(normalizedStartOffset, normalizedEndOffset)

      rememberLastEditorClipboardSnapshot({
        text: selectedText,
        lineStart,
        lineEnd,
      })

      return serializeEditorLineRangePayload({
        lineStart,
        lineEnd,
      })
    },
    [getLineIndexFromTextOffset, value]
  )

  const handleLineNumbersPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (disabled) return

      event.preventDefault()

      const lineIndex = getLineIndexFromPointerPosition(event.clientY)

      lineDragStateRef.current = {
        pointerId: event.pointerId,
        anchorLineIndex: lineIndex,
      }

      setDraggedLineRange({
        startLineIndex: lineIndex,
        endLineIndex: lineIndex,
      })

      lineNumbersRef.current?.setPointerCapture(event.pointerId)

      setTextareaSelectionForLineRange(lineIndex, lineIndex)
    },
    [disabled, getLineIndexFromPointerPosition, setTextareaSelectionForLineRange]
  )

  const handleLineNumbersPointerMove = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const activeDragState = lineDragStateRef.current
      const lineNumbersElement = lineNumbersRef.current
      const textareaElement = textareaRef.current

      if (!activeDragState || !lineNumbersElement || !textareaElement) return
      if (activeDragState.pointerId !== event.pointerId) return

      const gutterRect = lineNumbersElement.getBoundingClientRect()
      let nextScrollTop = textareaElement.scrollTop

      if (event.clientY < gutterRect.top) {
        const visualRowDelta = Math.ceil((gutterRect.top - event.clientY) / Math.max(editorLineHeightPx, 1))

        nextScrollTop = Math.max(0, textareaElement.scrollTop - visualRowDelta * editorLineHeightPx)
      } else if (event.clientY > gutterRect.bottom) {
        const visualRowDelta = Math.ceil((event.clientY - gutterRect.bottom) / Math.max(editorLineHeightPx, 1))
        const maxScrollTop = Math.max(0, textareaElement.scrollHeight - textareaElement.clientHeight)

        nextScrollTop = Math.min(maxScrollTop, textareaElement.scrollTop + visualRowDelta * editorLineHeightPx)
      }

      if (nextScrollTop !== textareaElement.scrollTop) {
        textareaElement.scrollTop = nextScrollTop
        syncOverlayScroll(nextScrollTop, textareaElement.scrollLeft)
      }

      const lineIndex = getLineIndexFromPointerPosition(event.clientY)

      setDraggedLineRange((currentRange) => {
        if (
          currentRange &&
          currentRange.startLineIndex === activeDragState.anchorLineIndex &&
          currentRange.endLineIndex === lineIndex
        ) {
          return currentRange
        }

        return {
          startLineIndex: activeDragState.anchorLineIndex,
          endLineIndex: lineIndex,
        }
      })

      setTextareaSelectionForLineRange(activeDragState.anchorLineIndex, lineIndex)
    },
    [editorLineHeightPx, getLineIndexFromPointerPosition, setTextareaSelectionForLineRange, syncOverlayScroll]
  )

  const handleLineNumbersPointerEnd = React.useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const activeDragState = lineDragStateRef.current

    if (!activeDragState || activeDragState.pointerId !== event.pointerId) return

    lineDragStateRef.current = null
    setDraggedLineRange(null)

    if (lineNumbersRef.current?.hasPointerCapture(event.pointerId)) {
      lineNumbersRef.current.releasePointerCapture(event.pointerId)
    }
  }, [])

  React.useEffect(() => {
    let isCancelled = false

    async function highlightMarkdownContent() {
      if (!value) {
        setHighlightedContent(null)

        return
      }

      const shikiTheme = colorScheme === 'light' ? GITHUB_LIGHT_THEME : AURORA_X_THEME

      try {
        const markdownHighlighter = await getMarkdownHighlighter()

        const nextHighlightedHtml = markdownHighlighter.codeToHtml(value, {
          lang: MARKDOWN_LANGUAGE,
          theme: shikiTheme,
        })

        if (!isCancelled) {
          setHighlightedContent({
            source: value,
            html: nextHighlightedHtml,
          })
        }
      } catch (error) {
        if (!isCancelled) {
          setHighlightedContent(null)
        }

        console.error('Failed to highlight markdown content in editor.', error)
      }
    }

    highlightMarkdownContent()

    return () => {
      isCancelled = true
    }
  }, [value, colorScheme])

  React.useEffect(() => {
    const textareaElement = textareaRef.current

    if (!textareaElement || typeof ResizeObserver === 'undefined') {
      syncEditorMetrics()

      return
    }

    syncEditorMetrics()

    const resizeObserver = new ResizeObserver(() => {
      syncEditorMetrics()
    })

    resizeObserver.observe(textareaElement)

    return () => {
      resizeObserver.disconnect()
    }
  }, [syncEditorMetrics])

  React.useEffect(() => {
    if (typeof document === 'undefined' || !('fonts' in document)) return

    const fontFaceSet = document.fonts
    const handleFontsChanged = () => {
      syncEditorMetrics()
    }

    void fontFaceSet.ready.then(handleFontsChanged).catch(() => undefined)

    if (typeof fontFaceSet.addEventListener === 'function') {
      fontFaceSet.addEventListener('loadingdone', handleFontsChanged)

      return () => {
        fontFaceSet.removeEventListener('loadingdone', handleFontsChanged)
      }
    }
  }, [syncEditorMetrics])

  React.useLayoutEffect(() => {
    if (!isWordWrapEnabled) {
      setWrappedLineRows(Array.from({ length: lineCount }, () => 1))
      setWrappedLineHeightsPx(Array.from({ length: lineCount }, () => editorLineHeightPx))

      return
    }

    const measureRootElement = lineMeasureRef.current

    if (!measureRootElement || editorViewportWidth <= 0) {
      setWrappedLineRows(Array.from({ length: lineCount }, () => 1))
      setWrappedLineHeightsPx(Array.from({ length: lineCount }, () => editorLineHeightPx))

      return
    }

    const measuredHeights = logicalLines.map((_, lineIndex) => {
      const measuredLineElement = measureRootElement.children.item(lineIndex) as HTMLElement | null
      if (!measuredLineElement) return editorLineHeightPx

      const measuredHeight = measuredLineElement.getBoundingClientRect().height
      if (!Number.isFinite(measuredHeight) || measuredHeight <= 0) return editorLineHeightPx

      return measuredHeight
    })

    const measuredRows = measuredHeights.map((measuredHeight) =>
      Math.max(1, Math.round(measuredHeight / Math.max(editorLineHeightPx, 1)))
    )

    setWrappedLineRows((currentRows) => {
      if (
        currentRows.length === measuredRows.length &&
        currentRows.every((rowCount, index) => rowCount === measuredRows[index])
      ) {
        return currentRows
      }

      return measuredRows
    })

    setWrappedLineHeightsPx((currentHeights) => {
      if (
        currentHeights.length === measuredHeights.length &&
        currentHeights.every((height, index) => Math.abs(height - measuredHeights[index]) < 0.25)
      ) {
        return currentHeights
      }

      return measuredHeights
    })
  }, [editorLineHeightPx, editorViewportWidth, isWordWrapEnabled, lineCount, logicalLines])

  React.useLayoutEffect(() => {
    syncSelectionFromTextarea()
  }, [syncSelectionFromTextarea, value])

  React.useEffect(() => {
    const handleSelectionChange = () => {
      if (document.activeElement !== textareaRef.current) return

      syncSelectionFromTextarea()
    }

    document.addEventListener('selectionchange', handleSelectionChange)

    return () => {
      document.removeEventListener('selectionchange', handleSelectionChange)
    }
  }, [syncSelectionFromTextarea])

  const selectedLineRange = React.useMemo(() => {
    if (draggedLineRange) {
      return {
        startLineIndex: Math.min(draggedLineRange.startLineIndex, draggedLineRange.endLineIndex),
        endLineIndex: Math.max(draggedLineRange.startLineIndex, draggedLineRange.endLineIndex),
      }
    }

    return resolveLineRangeFromSelectionOffsets(selectionRange)
  }, [draggedLineRange, resolveLineRangeFromSelectionOffsets, selectionRange])

  const measuredEditorWidth = Math.max(1, editorViewportWidth - editorPaddingLeftPx - editorPaddingRightPx)

  const sharedEditorTextStyle = React.useMemo<React.CSSProperties>(
    () => ({
      boxSizing: 'border-box',
      fontFamily: editorFontFamily,
      fontStyle: editorFontStyle,
      fontWeight: editorFontWeight,
      fontSize: `${editorFontSizePx}px`,
      letterSpacing: editorLetterSpacing,
      lineHeight: `${editorLineHeightPx}px`,
      tabSize: editorTabSize,
    }),
    [editorFontFamily, editorFontStyle, editorFontWeight, editorFontSizePx, editorLetterSpacing, editorLineHeightPx, editorTabSize]
  )

  const textareaStyle = React.useMemo<React.CSSProperties>(
    () => ({
      ...sharedEditorTextStyle,
      paddingTop: `${editorPaddingTopPx}px`,
      paddingRight: `${editorPaddingRightPx}px`,
      paddingBottom: `${editorPaddingBottomPx}px`,
      paddingLeft: `${editorPaddingLeftPx}px`,
    }),
    [sharedEditorTextStyle, editorPaddingTopPx, editorPaddingRightPx, editorPaddingBottomPx, editorPaddingLeftPx]
  )

  const shouldRenderHighlightedContent =
    Boolean(value) && Boolean(highlightedContent?.html) && highlightedContent?.source === value

  const isLineIndexSelected = (lineIndex: number) =>
    Boolean(selectedLineRange) &&
    lineIndex >= (selectedLineRange?.startLineIndex ?? -1) &&
    lineIndex <= (selectedLineRange?.endLineIndex ?? -1)

  return (
    <div className={cn('relative flex h-full min-h-0 overflow-hidden rounded-lg border bg-background', className)}>
      <div
        ref={lineNumbersRef}
        className='bg-muted/40 text-muted-foreground w-14 shrink-0 overflow-hidden border-r text-right text-xs select-none cursor-default'
        style={{
          lineHeight: `${editorLineHeightPx}px`,
          paddingTop: `${editorPaddingTopPx}px`,
          paddingBottom: `${editorPaddingBottomPx}px`,
        }}
        onPointerDown={handleLineNumbersPointerDown}
        onPointerMove={handleLineNumbersPointerMove}
        onPointerUp={handleLineNumbersPointerEnd}
        onPointerCancel={handleLineNumbersPointerEnd}
        onLostPointerCapture={handleLineNumbersPointerEnd}
      >
        {visualRows.map((row, rowIndex) => (
          <div
            key={`line-number-row-${rowIndex}`}
            className={cn('pr-3', isLineIndexSelected(row.lineIndex) ? 'bg-accent/50 text-foreground' : undefined)}
            style={{ minHeight: `${editorLineHeightPx}px` }}
          >
            {row.lineLabel}
          </div>
        ))}
      </div>

      <div className='relative h-full min-h-0 flex-1'>
        <div
          ref={lineHighlightLayerRef}
          className={cn(
            'pointer-events-none absolute inset-0 z-10 overflow-y-auto',
            isWordWrapEnabled ? 'overflow-x-hidden' : 'overflow-x-auto'
          )}
          aria-hidden='true'
        >
          <div
            className='min-h-full'
            style={{
              boxSizing: 'border-box',
              paddingTop: `${editorPaddingTopPx}px`,
              paddingBottom: `${editorPaddingBottomPx}px`,
            }}
          >
            {logicalLines.map((_, lineIndex) => {
              const lineHeightPx = isWordWrapEnabled ? wrappedLineHeightsPx[lineIndex] || editorLineHeightPx : editorLineHeightPx

              return (
                <div
                  key={`line-highlight-${lineIndex}`}
                  className={isLineIndexSelected(lineIndex) ? 'bg-accent/35' : 'bg-transparent'}
                  style={{ height: `${lineHeightPx}px` }}
                />
              )
            })}
          </div>
        </div>

        {shouldRenderHighlightedContent ? (
          <div
            ref={highlightLayerRef}
            className={cn(
              'pointer-events-none absolute inset-0 z-0 overflow-y-auto',
              isWordWrapEnabled ? 'overflow-x-hidden' : 'overflow-x-auto'
            )}
            aria-hidden='true'
          >
            <div
              className={cn(
                '[&_pre]:m-0 [&_pre]:p-0 [&_pre]:[font-family:inherit] [&_pre]:[font-size:inherit] [&_pre]:[line-height:inherit]',
                '[&_pre]:[font-style:inherit] [&_pre]:[font-weight:inherit] [&_pre]:[letter-spacing:inherit] [&_pre]:[tab-size:inherit]',
                '[&_pre]:min-h-full',
                isWordWrapEnabled ? '[&_pre]:whitespace-pre-wrap [&_pre]:break-words' : '[&_pre]:whitespace-pre'
              )}
              style={{
                ...sharedEditorTextStyle,
                paddingTop: `${editorPaddingTopPx}px`,
                paddingRight: `${editorPaddingRightPx}px`,
                paddingBottom: `${editorPaddingBottomPx}px`,
                paddingLeft: `${editorPaddingLeftPx}px`,
              }}
              dangerouslySetInnerHTML={{ __html: highlightedContent?.html ?? '' }}
            />
          </div>
        ) : null}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onSelect={syncSelectionFromTextarea}
          onCopy={(event) => {
            const payload = resolveClipboardLineRangePayload(
              event.currentTarget.selectionStart,
              event.currentTarget.selectionEnd
            )

            if (!payload || !event.clipboardData) return

            event.clipboardData.setData(EDITOR_LINE_RANGE_MIME_TYPE, payload)
          }}
          onCut={(event) => {
            const payload = resolveClipboardLineRangePayload(
              event.currentTarget.selectionStart,
              event.currentTarget.selectionEnd
            )

            if (!payload || !event.clipboardData) return

            event.clipboardData.setData(EDITOR_LINE_RANGE_MIME_TYPE, payload)
          }}
          onScroll={(event) => {
            const { scrollTop, scrollLeft } = event.currentTarget

            syncOverlayScroll(scrollTop, scrollLeft)
          }}
          wrap={isWordWrapEnabled ? 'soft' : 'off'}
          className={cn(
            'relative z-20 h-full min-h-0 w-full resize-none overflow-y-auto border-0 bg-transparent outline-none',
            shouldRenderHighlightedContent ? 'text-transparent caret-foreground selection:bg-transparent' : 'text-primary',
            isWordWrapEnabled ? 'overflow-x-hidden' : 'overflow-x-auto',
            textareaClassName
          )}
          style={textareaStyle}
          placeholder={placeholder}
          aria-label={ariaLabel}
          disabled={disabled}
        />
      </div>

      <div className='pointer-events-none absolute -z-10 h-0 overflow-hidden opacity-0' aria-hidden='true'>
        <div
          ref={lineMeasureRef}
          style={{
            width: `${measuredEditorWidth}px`,
            ...sharedEditorTextStyle,
            whiteSpace: 'pre-wrap',
            overflowWrap: 'anywhere',
            wordBreak: 'break-word',
          }}
        >
          {logicalLines.map((lineText, lineIndex) => (
            <div key={`measure-line-${lineIndex}`}>{lineText.length === 0 ? '\u200b' : lineText}</div>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className='bg-background/80 absolute inset-0 flex items-center justify-center backdrop-blur-[1px]'>
          <div className='text-muted-foreground inline-flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm'>
            <Loader2 className='size-4 animate-spin' />
            {loadingMessage}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export { Editor }
