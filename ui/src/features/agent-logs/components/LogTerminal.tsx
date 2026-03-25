import { useEffect, useRef, useState } from 'react'
import { codeToHtml } from 'shiki'

import type { PipelineLog, LogLevel } from '@/features/agent-logs/hooks/useAgentLogs'

type Props = {
  logs: PipelineLog[]
}

const LEVEL_CLASS: Record<string, string> = {
  info: 'text-emerald-400',
  warn: 'text-yellow-400',
  warning: 'text-yellow-400',
  error: 'text-red-400',
  debug: 'text-zinc-500',
}

const LEVEL_LABEL: Record<string, string> = {
  info: 'INFO ',
  warn: 'WARN ',
  warning: 'WARN ',
  error: 'ERROR',
  debug: 'DEBUG',
}

function formatTime(isoString: string): string {
  try {
    const date = new Date(isoString)

    return date.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return '--:--:--'
  }
}

function isJsonString(value: string): boolean {
  const trimmed = value.trimStart()
  return trimmed.startsWith('{') || trimmed.startsWith('[')
}

function JsonMessage({ message }: { message: string }) {
  const [html, setHtml] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    codeToHtml(message, { lang: 'json', theme: 'github-dark' })
      .then((result) => {
        if (!cancelled) {
          setHtml(result)
        }
      })
      .catch(() => {
        // Fall back to plain rendering
      })

    return () => {
      cancelled = true
    }
  }, [message])

  if (html) {
    return (
      <span
        className="block overflow-x-auto whitespace-pre-wrap text-xs [&>pre]:bg-transparent! [&>pre]:p-0! [&_code]:text-xs!"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  }

  return <span className="whitespace-pre-wrap break-all">{message}</span>
}

function LogLine({ log }: { log: PipelineLog }) {
  const levelClass = LEVEL_CLASS[(log.level as LogLevel) ?? 'info'] ?? 'text-zinc-400'
  const levelLabel = LEVEL_LABEL[(log.level as LogLevel) ?? 'info'] ?? 'INFO '
  const isJson = isJsonString(log.message)

  return (
    <div className="flex gap-2 py-0.5 leading-relaxed hover:bg-white/5">
      <span className="shrink-0 text-zinc-600">{formatTime(log.created_at)}</span>

      <span className={`shrink-0 font-semibold ${levelClass}`}>[{levelLabel}]</span>

      {log.jira_key ? (
        <span className="shrink-0 text-sky-500">[{log.jira_key}]</span>
      ) : null}

      <span className="min-w-0 flex-1 text-zinc-300">
        {isJson ? (
          <JsonMessage message={log.message} />
        ) : (
          <span className="whitespace-pre-wrap break-all">{log.message}</span>
        )}
      </span>
    </div>
  )
}

export default function LogTerminal({ logs }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  function handleScroll() {
    const el = containerRef.current

    if (!el) return

    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 font-mono text-sm">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-2">
        <span className="size-3 rounded-full bg-red-500/80" />

        <span className="size-3 rounded-full bg-yellow-500/80" />

        <span className="size-3 rounded-full bg-emerald-500/80" />

        <span className="ml-2 text-xs text-zinc-500">agent logs</span>

        {!autoScroll && (
          <button
            onClick={() => {
              setAutoScroll(true)
              bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
            }}
            className="ml-auto rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 hover:text-zinc-200"
          >
            scroll to bottom
          </button>
        )}
      </div>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3"
      >
        {logs.length === 0 ? (
          <span className="text-zinc-600">Waiting for logs...</span>
        ) : (
          logs.map((log) => (
            <LogLine key={log.id} log={log} />
          ))
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
