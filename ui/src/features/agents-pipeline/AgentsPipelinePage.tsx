import { useEffect, useMemo, useState } from "react"

import { SiteSubheader } from "@/shared/components/site-subheader.tsx"
import { Tabs, TabsList, TabsTrigger } from "@/shared/components/ui/tabs"
import AgentsTabSection from "@/features/agents-pipeline/components/AgentsTabSection"
import BypassControlsSection, {
  type BypassKey,
  type BypassState,
} from "@/features/agents-pipeline/components/BypassControlsSection"
import PipelineOverviewSection from "@/features/agents-pipeline/components/PipelineOverviewSection"
import { useAgentsPipelineStore } from "@/features/agents-pipeline/store/agents-pipeline-store"
import useAgentsStatus from "@/shared/hooks/useAgentsStatus"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

type BypassPayload = {
  jira_api_bypass?: boolean
  sdd_spec_bypass?: boolean
  code_builder_bypass?: boolean
  code_review_bypass?: boolean
}

const BYPASS_PAYLOAD_KEYS: Record<BypassKey, keyof BypassPayload> = {
  jiraApi: "jira_api_bypass",
  sddSpec: "sdd_spec_bypass",
  codeBuilder: "code_builder_bypass",
  codeReview: "code_review_bypass",
}

const ROLE_EXECUTION_ORDER: Record<string, number> = {
  chat_graph: 0,
  ticket_pipeline_graph: 1,
  spec_pipeline_graph: 2,
  orchestrator: 3,
  planner: 4,
  jira_api: 5,
  sdd_spec: 6,
  code_builder: 7,
  code_review: 8,
  git_ops: 9,
  git_content: 10,
  pipeline: 11,
  heartbeat: 12,
  research: 13,
  cli_agent: 14,
  workspace: 15,
  notifier: 16,
  logger: 17,
}

const healthFailures = new Set(["degraded", "unconfigured"])

const roleRank = (role?: string) => {
  const normalizedRole = (role || "").toLowerCase()
  return ROLE_EXECUTION_ORDER[normalizedRole] ?? Number.MAX_SAFE_INTEGER
}

const needsHealth = (agent: { provider?: string | null; health?: string | null; bypassed?: boolean }) => {
  if (agent.bypassed) {
    return false
  }

  if (agent.provider) {
    return true
  }

  return healthFailures.has((agent.health || "").toLowerCase())
}

export default function AgentsPipelinePage() {
  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const activeTab = useAgentsPipelineStore((state) => state.activeTab)
  const setActiveTab = useAgentsPipelineStore((state) => state.setActiveTab)
  const { agents, bypass, error, isLoading, mode } = useAgentsStatus()

  const [bypassError, setBypassError] = useState<string | null>(null)
  const [localBypass, setLocalBypass] = useState<BypassState>(bypass)
  const [updatingBypass, setUpdatingBypass] = useState<BypassKey | null>(null)

  useEffect(() => {
    setBreadcrumbs([
      { label: "Dashboard", href: "/" },
      { label: "Agents Pipeline" },
    ])
  }, [setBreadcrumbs])

  const orderedAgents = useMemo(() => {
    return [...agents].sort((a, b) => {
      const rankDifference = roleRank(a.role) - roleRank(b.role)
      if (rankDifference !== 0) {
        return rankDifference
      }

      const groupCompare = (a.group || "").localeCompare(b.group || "")
      if (groupCompare !== 0) {
        return groupCompare
      }

      return (a.name || "").localeCompare(b.name || "")
    })
  }, [agents])

  const summary = useMemo(() => {
    const active = orderedAgents.filter((agent) => Boolean(agent.is_active)).length
    const healthCheckedAgents = orderedAgents.filter((agent) => needsHealth(agent))
    const failedHealthCount = healthCheckedAgents.filter((agent) =>
      healthFailures.has((agent.health || "").toLowerCase())
    ).length
    const healthy = healthCheckedAgents.length - failedHealthCount
    const pipeline = agents.find((agent) => agent.name.toLowerCase() === "pipeline agent")
    const research = agents.find((agent) => agent.role === "research")
    const sddSpec = agents.find((agent) => agent.name.toLowerCase() === "sdd spec agent")
    const gitContent = agents.find((agent) => agent.name.toLowerCase() === "git content agent")
    const chatGraph = agents.find((agent) => agent.role === "chat_graph")
    const ticketPipelineGraph = agents.find((agent) => agent.role === "ticket_pipeline_graph")
    const specPipelineGraph = agents.find((agent) => agent.role === "spec_pipeline_graph")

    return {
      total: orderedAgents.length,
      active,
      healthy,
      failedHealthCount,
      hasHealthFailure: failedHealthCount > 0,
      researchActive: Boolean(research?.is_active),
      pipelineActive: Boolean(pipeline?.is_active),
      sddSpecActive: Boolean(sddSpec?.is_active),
      gitContentActive: Boolean(gitContent?.is_active),
      chatGraphReady: Boolean(chatGraph),
      chatGraphActive: Boolean(chatGraph?.is_active),
      ticketGraphReady: Boolean(ticketPipelineGraph),
      ticketGraphActive: Boolean(ticketPipelineGraph?.is_active),
      specGraphReady: Boolean(specPipelineGraph),
      specGraphActive: Boolean(specPipelineGraph?.is_active),
    }
  }, [agents, orderedAgents])

  useEffect(() => {
    setLocalBypass(bypass)
  }, [bypass])

  const updateBypass = async (payload: BypassPayload) => {
    const response = await fetch(buildApiUrl("/api/agents/bypass"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      throw new Error("Failed to update bypass settings")
    }
  }

  const handleToggleBypass = async (key: BypassKey, checked: boolean) => {
    const payloadKey = BYPASS_PAYLOAD_KEYS[key]
    const previous = localBypass[key]
    const payload = { [payloadKey]: checked } as BypassPayload

    setBypassError(null)
    setUpdatingBypass(key)
    setLocalBypass((current) => ({ ...current, [key]: checked }))

    try {
      await updateBypass(payload)
    } catch (err) {
      setLocalBypass((current) => ({ ...current, [key]: previous }))
      setBypassError(err instanceof Error ? err.message : "Failed to update bypass")
    } finally {
      setUpdatingBypass(null)
    }
  }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as typeof activeTab)} className="flex min-h-0 flex-1 flex-col gap-0">
        <SiteSubheader>
          <TabsList variant="line">
            <TabsTrigger value="agents">AGENTS</TabsTrigger>

            <TabsTrigger value="settings">SETTINGS</TabsTrigger>
          </TabsList>
        </SiteSubheader>

        <div className="flex min-h-0 w-full flex-1 overflow-auto">
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-6">
            <PipelineOverviewSection mode={mode} summary={summary} />

            {error ? (
              <div className="rounded-md border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-700">
                {error}
              </div>
            ) : null}

            <AgentsTabSection agents={orderedAgents} isLoading={isLoading} />

            <BypassControlsSection
              bypassError={bypassError}
              localBypass={localBypass}
              onToggleBypass={handleToggleBypass}
              updatingBypass={updatingBypass}
            />
          </div>
        </div>
      </Tabs>
    </div>
  )
}
