import { Network } from "lucide-react"
import { Chip } from "@/shared/components/chip"
import type { PipelineState, PipelineSyncMode } from "@/features/pipelines/types"

const formatTime = (value: string) => {
  if (!value) return "n/a"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const formatCountdown = (seconds: number) => {
  const safe = Math.max(0, seconds)
  const h = Math.floor(safe / 3600)
  const m = Math.floor((safe % 3600) / 60)
  const s = safe % 60
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
}

type PipelineHeaderProps = {
  state: PipelineState | null
  mode: PipelineSyncMode
  heartbeatCountdown: number
}

export default function PipelineHeader({
  state,
  mode,
  heartbeatCountdown,
}: PipelineHeaderProps) {
  const hasRunningTask = (state?.columns?.running.length || 0) > 0
  const nextHeartbeatLabel = hasRunningTask
    ? "After running task"
    : formatTime(state?.heartbeat?.next_heartbeat_at || "")
  const countdownLabel = hasRunningTask ? "Paused" : formatCountdown(heartbeatCountdown)

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Network className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Automation Pipeline</h1>
            <p className="text-muted-foreground text-sm">
              Autonomous Jira task pipeline (Backlog → Task Queue → Running → Complete).
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip color="grey" variant="outline">
          Window {state?.heartbeat?.active_window_start || "--:--"} → {state?.heartbeat?.active_window_end || "--:--"}
        </Chip>
        <Chip color="grey" variant="outline">
          Heartbeat {state?.heartbeat?.heartbeat_interval_minutes || "--"} min
        </Chip>
        <Chip color="grey" variant="outline">
          Next heartbeat {nextHeartbeatLabel}
        </Chip>
        <Chip color="grey" variant="outline">
          Countdown {countdownLabel}
        </Chip>
        {hasRunningTask ? (
          <Chip color="success" variant="outline">
            Execution waiting for running task
          </Chip>
        ) : null}
        <Chip color={state?.heartbeat?.active_window_state === "active" ? "success" : "warning"} variant="outline">
          Active window {state?.heartbeat?.active_window_state === "active" ? "ACTIVE" : "INACTIVE"}
        </Chip>
        <Chip color="grey" variant="outline">
          Sync {mode}
        </Chip>
      </div>
    </section>
  )
}
