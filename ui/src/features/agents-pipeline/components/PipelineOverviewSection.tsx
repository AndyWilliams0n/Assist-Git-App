import { Bot } from "lucide-react"

import { Chip } from "@/shared/components/chip"

type AgentsStatusMode = "streaming" | "polling"

type PipelineSummary = {
  total: number
  active: number
  healthy: number
  failedHealthCount: number
  hasHealthFailure: boolean
  researchActive: boolean
  pipelineActive: boolean
  sddSpecActive: boolean
  gitContentActive: boolean
  chatGraphReady: boolean
  chatGraphActive: boolean
  ticketGraphReady: boolean
  ticketGraphActive: boolean
  specGraphReady: boolean
  specGraphActive: boolean
}

type PipelineOverviewSectionProps = {
  mode: AgentsStatusMode
  summary: PipelineSummary
}

export default function PipelineOverviewSection({ mode, summary }: PipelineOverviewSectionProps) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Bot className="size-5" />
        </div>

        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agents Pipeline</h1>

          <p className="text-muted-foreground text-sm">
            Live agent status via {mode === "streaming" ? "streaming events" : "polling"}.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <Chip color="grey" variant="outline">
          {summary.total} agents
        </Chip>

        <Chip color="success" variant="filled">
          {summary.active} active
        </Chip>

        <Chip color={summary.hasHealthFailure ? "warning" : "success"} variant="outline">
          Health: {summary.hasHealthFailure ? "degraded" : "healthy"}
        </Chip>

        <Chip color="grey" variant="outline">
          {summary.healthy} passed, {summary.failedHealthCount} failed
        </Chip>
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip
          color={!summary.chatGraphReady ? "error" : summary.chatGraphActive ? "success" : "grey"}
          variant="outline"
        >
          Chat Graph: {!summary.chatGraphReady ? "unavailable" : summary.chatGraphActive ? "active" : "ready"}
        </Chip>

        <Chip
          color={!summary.ticketGraphReady ? "error" : summary.ticketGraphActive ? "success" : "grey"}
          variant="outline"
        >
          Ticket Graph: {!summary.ticketGraphReady ? "unavailable" : summary.ticketGraphActive ? "active" : "ready"}
        </Chip>

        <Chip
          color={!summary.specGraphReady ? "error" : summary.specGraphActive ? "success" : "grey"}
          variant="outline"
        >
          Spec Graph: {!summary.specGraphReady ? "unavailable" : summary.specGraphActive ? "active" : "ready"}
        </Chip>

        <Chip color={summary.researchActive ? "success" : "grey"} variant="outline">
          Research: {summary.researchActive ? "active" : "idle"}
        </Chip>

        <Chip color={summary.pipelineActive ? "success" : "grey"} variant="outline">
          Pipeline: {summary.pipelineActive ? "active" : "idle"}
        </Chip>

        <Chip color={summary.sddSpecActive ? "success" : "grey"} variant="outline">
          SDD Spec: {summary.sddSpecActive ? "active" : "idle"}
        </Chip>

        <Chip color={summary.gitContentActive ? "success" : "grey"} variant="outline">
          Git Content: {summary.gitContentActive ? "active" : "idle"}
        </Chip>
      </div>
    </section>
  )
}
