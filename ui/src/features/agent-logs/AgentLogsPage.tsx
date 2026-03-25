import { useEffect, useState } from 'react'

import { SiteSubheader } from '@/shared/components/site-subheader.tsx'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import LogTerminal from '@/features/agent-logs/components/LogTerminal'
import useAgentLogs from '@/features/agent-logs/hooks/useAgentLogs'
import type { PipelineLog } from '@/features/agent-logs/hooks/useAgentLogs'

const buttonClass = 'rounded border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-400 hover:text-zinc-200'

function formatLogLine(log: PipelineLog): string {
  const level = (log.level ?? 'info').toUpperCase().padEnd(5)
  const jira = log.jira_key ? `[${log.jira_key}] ` : ''

  return `${log.created_at} [${level}] ${jira}${log.message}`
}

export default function AgentLogsPage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const { logs, connected, error, clear } = useAgentLogs()
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Agent Logs' },
    ])
  }, [setBreadcrumbs])

  async function handleCopy() {
    const text = logs.map(formatLogLine).join('\n')

    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <SiteSubheader>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span
              className={`size-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-zinc-600'}`}
            />

            <span className="text-xs text-zinc-500">
              {connected ? 'Live' : 'Connecting...'}
            </span>
          </div>

          {error ? (
            <span className="text-xs text-yellow-500">{error}</span>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            <button onClick={handleCopy} className={buttonClass}>
              {copied ? 'Copied!' : 'Copy Logs'}
            </button>

            <button onClick={clear} className={buttonClass}>
              Clear
            </button>
          </div>
        </div>
      </SiteSubheader>

      <div className="flex min-h-0 w-full flex-1 overflow-hidden p-6">
        <LogTerminal logs={logs} />
      </div>
    </div>
  )
}
