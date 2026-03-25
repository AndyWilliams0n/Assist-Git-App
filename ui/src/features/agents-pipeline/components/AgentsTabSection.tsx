import { TabsContent } from "@/shared/components/ui/tabs"
import type { AgentStatus } from "@/shared/types/agents"
import AgentTableSection from "@/features/agents-pipeline/components/AgentTableSection"

type AgentsTabSectionProps = {
  agents: AgentStatus[]
  isLoading: boolean
}

export default function AgentsTabSection({ agents, isLoading }: AgentsTabSectionProps) {
  return (
    <TabsContent value="agents" className="mt-0">
      {isLoading && agents.length === 0 ? (
        <p className="text-muted-foreground text-sm">Loading agent status...</p>
      ) : (
        <AgentTableSection agents={agents} />
      )}
    </TabsContent>
  )
}
