import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import AgentsWorkflowFlow, {
  type AgentsWorkflowFlowHandle,
} from '@/features/agents-flow/components/AgentsWorkflowFlow'
import FlowControls from '@/features/agents-flow/components/FlowControls'
import FlowLegendDialog from '@/features/agents-flow/components/FlowLegendDialog'
import FlowLoadingOverlay from '@/features/agents-flow/components/FlowLoadingOverlay'
import useAgentsStatus from '@/shared/hooks/useAgentsStatus'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'

export default function AgentsFlowPage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const { agents, error, isLoading, mode } = useAgentsStatus()
  const [legendOpen, setLegendOpen] = useState(false)
  const [wheelPanEnabled, setWheelPanEnabled] = useState(true)
  const flowRef = useRef<AgentsWorkflowFlowHandle>(null)

  useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Architecture Flow' },
    ])
  }, [setBreadcrumbs])

  const summary = useMemo(() => {
    const active = agents.filter((agent) => Boolean(agent.is_active)).length
    const healthy = agents.filter((agent) => agent.health === 'ok').length
    const degraded = agents.filter((agent) => agent.health === 'degraded').length
    const unconfigured = agents.filter((agent) => agent.health === 'unconfigured').length
    const research = agents.find((agent) => agent.name.toLowerCase() === 'research agent')
    const pipeline = agents.find((agent) => agent.name.toLowerCase() === 'pipeline agent')
    const sddSpec = agents.find((agent) => agent.name.toLowerCase() === 'sdd spec agent')
    const gitContent = agents.find((agent) => agent.name.toLowerCase() === 'git content agent')

    return {
      total: agents.length,
      active,
      healthy,
      degraded,
      unconfigured,
      researchActive: Boolean(research?.is_active),
      pipelineActive: Boolean(pipeline?.is_active),
      sddSpecActive: Boolean(sddSpec?.is_active),
      gitContentActive: Boolean(gitContent?.is_active),
    }
  }, [agents])

  const handleSaveFlowJson = useCallback(() => {
    const flowJson = flowRef.current?.exportFlow()
    if (!flowJson || typeof window === 'undefined') {
      return
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const blob = new Blob([flowJson], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = `agents-flow-${timestamp}.json`
    window.document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.URL.revokeObjectURL(url)
  }, [])

  return (
    <div className='relative flex flex-1 min-h-0 w-full'>
      <FlowLoadingOverlay isVisible={isLoading && agents.length === 0} />

      <AgentsWorkflowFlow ref={flowRef} agents={agents} wheelPanEnabled={wheelPanEnabled} />

      <FlowControls
        wheelPanEnabled={wheelPanEnabled}
        onSaveFlowJson={handleSaveFlowJson}
        onToggleWheelPan={() => setWheelPanEnabled((current) => !current)}
        onOpenLegend={() => setLegendOpen(true)}
      />

      <FlowLegendDialog
        error={error}
        isOpen={legendOpen}
        mode={mode}
        onClose={() => setLegendOpen(false)}
        summary={summary}
        wheelPanEnabled={wheelPanEnabled}
      />
    </div>
  )
}
