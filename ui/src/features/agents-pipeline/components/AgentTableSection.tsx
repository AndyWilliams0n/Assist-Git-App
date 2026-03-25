import { useMemo } from "react"

import { Chip } from "@/shared/components/chip"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table"
import type { AgentStatus } from "@/shared/types/agents"

type AgentTableSectionProps = {
  agents: AgentStatus[]
}

const COLUMN_COUNT = 13

const healthTone = (health?: string | null) => {
  switch (health) {
    case "ok":
      return { label: "healthy", color: "success" as const }
    case "degraded":
      return { label: "degraded", color: "warning" as const }
    case "unconfigured":
      return { label: "unconfigured", color: "error" as const }
    default:
      return { label: "unknown", color: "grey" as const }
  }
}

const needsHealth = (agent: AgentStatus) => {
  if (agent.bypassed) {
    return false
  }

  if (agent.provider) {
    return true
  }

  const health = (agent.health || "").toLowerCase()
  return health === "degraded" || health === "unconfigured"
}

const formatTime = (value?: string | null) => {
  if (!value) {
    return "-"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

const formatDuration = (seconds?: number) => {
  if (!Number.isFinite(seconds) || seconds === undefined) {
    return "-"
  }

  const total = Math.max(0, Math.floor(seconds))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)

  if (days > 0) {
    return `${days}d ${hours}h`
  }

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }

  return `${minutes}m`
}

const GROUP_LABELS: Record<string, string> = {
  graphs: "LangGraph",
  agents: "Agents",
}

const formatGroupLabel = (group: string) => GROUP_LABELS[group] ?? group

const truncateCellClassName = "max-w-[220px] truncate"

export default function AgentTableSection({ agents }: AgentTableSectionProps) {
  const idToName = useMemo(() => {
    const map: Record<string, string> = {}
    agents.forEach((agent) => {
      map[agent.id] = agent.name
    })
    return map
  }, [agents])

  const groupedAgents = useMemo(() => {
    const groups: { label: string; agents: AgentStatus[] }[] = []
    const seen = new Map<string, AgentStatus[]>()

    agents.forEach((agent) => {
      const key = agent.group || "other"

      if (!seen.has(key)) {
        seen.set(key, [])
        groups.push({ label: key, agents: seen.get(key)! })
      }

      seen.get(key)!.push(agent)
    })

    return groups
  }, [agents])

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Agent Status</h2>

      <div className="rounded-lg border bg-card">
        <Table className="rounded-lg overflow-hidden">
          <TableHeader>
            <TableRow>
              <TableHead className="sticky top-0 z-10 bg-card">Name</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Role</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Kind</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Model</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Capabilities</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Health</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Status</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Bypass</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Calls</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Last Active</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Uptime</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Last Error</TableHead>

              <TableHead className="sticky top-0 z-10 bg-card">Dependencies</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {groupedAgents.map(({ label, agents: groupAgents }) => (
              <>
                <TableRow key={`group-${label}`} className="bg-muted/40 hover:bg-muted/40">
                  <TableCell
                    colSpan={COLUMN_COUNT}
                    className="py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    {formatGroupLabel(label)}
                  </TableCell>
                </TableRow>

                {groupAgents.map((agent) => {
                  const health = healthTone(agent.health)
                  const deps = (agent.dependencies || [])
                    .map((depId) => idToName[depId] || depId)
                    .join(", ")
                  const active = Boolean(agent.is_active)
                  const showHealth = needsHealth(agent)

                  return (
                    <TableRow key={agent.id}>
                      <TableCell>{agent.name}</TableCell>

                      <TableCell>{agent.role || "-"}</TableCell>

                      <TableCell>{agent.kind || "-"}</TableCell>

                      <TableCell className={truncateCellClassName}>
                        {agent.model ? (
                          <Chip color="purple" variant="outline">
                            {agent.model}
                          </Chip>
                        ) : (
                          "-"
                        )}
                      </TableCell>

                      <TableCell className={truncateCellClassName}>
                        {(agent.capabilities || []).join(", ") || "-"}
                      </TableCell>

                      <TableCell>
                        {showHealth ? (
                          <Chip color={health.color} variant="outline">
                            {health.label}
                          </Chip>
                        ) : (
                          "-"
                        )}
                      </TableCell>

                      <TableCell>
                        <Chip
                          color={agent.status === "bypassed" ? "error" : active ? "success" : "grey"}
                          variant={agent.status === "bypassed" ? "filled" : active ? "filled" : "outline"}
                        >
                          {agent.status === "bypassed" ? "Bypassed" : active ? "Active" : "Idle"}
                        </Chip>
                      </TableCell>

                      <TableCell>
                        <Chip
                          color={agent.bypassed ? "error" : "grey"}
                          variant={agent.bypassed ? "filled" : "outline"}
                        >
                          {agent.bypassed ? "On" : "Off"}
                        </Chip>
                      </TableCell>

                      <TableCell>{agent.total_calls ?? 0}</TableCell>

                      <TableCell>{formatTime(agent.last_active_at)}</TableCell>

                      <TableCell>{formatDuration(agent.uptime_seconds)}</TableCell>

                      <TableCell className={truncateCellClassName}>{agent.last_error || "-"}</TableCell>

                      <TableCell className={truncateCellClassName}>{deps || "None"}</TableCell>
                    </TableRow>
                  )
                })}
              </>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}
