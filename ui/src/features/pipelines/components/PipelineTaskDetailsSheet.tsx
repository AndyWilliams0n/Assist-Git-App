import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/shared/components/ui/sheet"
import type { PipelineTask } from "@/features/pipelines/types"

const formatTime = (value: string) => {
  if (!value) return "n/a"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

type PipelineTaskDetailsSheetProps = {
  task: PipelineTask | null
  onOpenChange: (open: boolean) => void
}

export default function PipelineTaskDetailsSheet({ task, onOpenChange }: PipelineTaskDetailsSheetProps) {
  return (
    <Sheet open={Boolean(task)} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full max-w-xl overflow-y-auto p-0 sm:max-w-xl">
        {task ? (
          <div className="flex h-full flex-col">
            <SheetHeader className="border-b">
              <SheetTitle>{task.jira_key}</SheetTitle>
              <SheetDescription>
                {task.task_source.toUpperCase()} • v{task.version} • {(task.workflow || "codex").toUpperCase()} • {task.status.toUpperCase()}
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-4 p-4 text-sm">
              <section className="space-y-1">
                <h4 className="font-semibold">Summary</h4>
                <p>{task.title}</p>
                <p className="text-muted-foreground">Workspace: {task.workspace_path || "n/a"}</p>
                {task.starting_git_branch_override ? (
                  <p className="text-muted-foreground">
                    Starting Git Branch Override: {task.starting_git_branch_override}
                  </p>
                ) : null}
                <p className="text-muted-foreground">Execution state: {(task.execution_state || "ready").toUpperCase()}</p>
                {Number(task.is_bypassed || 0) ? (
                  <p className="text-amber-700">
                    Bypassed: {task.bypass_reason || "Enabled"}
                    {task.bypass_source ? ` (${task.bypass_source})` : ""}
                  </p>
                ) : null}
                {Number(task.is_dependency_blocked || 0) ? (
                  <p className="text-amber-700">
                    Dependency block: {task.dependency_block_reason || "Waiting on dependencies"}
                  </p>
                ) : null}
                {Number(task.unresolved_handoff_count || 0) > 0 ? (
                  <p className="text-amber-700">
                    Unresolved handoffs: {task.unresolved_handoff_count}
                  </p>
                ) : null}
                <p className="text-muted-foreground">Last update: {formatTime(task.updated_at)}</p>
                {task.failure_reason ? <p className="text-rose-600">{task.failure_reason}</p> : null}
              </section>

              <section className="space-y-2">
                <h4 className="font-semibold">Version History</h4>
                {task.runs.length === 0 ? (
                  <p className="text-muted-foreground">No runs recorded yet.</p>
                ) : (
                  task.runs.map((run) => (
                    <div key={run.id} className="rounded-md border p-2">
                      <p className="font-medium">
                        v{run.version} • {run.status.toUpperCase()}
                      </p>
                      <p className="text-muted-foreground">Started: {formatTime(run.started_at)}</p>
                      <p className="text-muted-foreground">Ended: {formatTime(run.ended_at)}</p>
                      <p className="text-muted-foreground">Builder: {run.codex_status || "n/a"}</p>
                      <p className="text-muted-foreground">
                        Loop: attempt {Number(run.attempt_count || 0)}/{Number(run.max_retries || 0)} • completed{" "}
                        {Number(run.attempts_completed || 0)} • failed {Number(run.attempts_failed || 0)}
                      </p>
                      {run.current_activity ? <p className="text-muted-foreground">{run.current_activity}</p> : null}
                      {run.failure_reason ? <p className="text-rose-600">{run.failure_reason}</p> : null}
                    </div>
                  ))
                )}
              </section>

              <section className="space-y-2">
                <h4 className="font-semibold">Logs</h4>
                {task.logs.length === 0 ? (
                  <p className="text-muted-foreground">No logs recorded yet.</p>
                ) : (
                  task.logs.map((log) => (
                    <div key={log.id} className="rounded-md border p-2">
                      <p className="text-muted-foreground text-xs">
                        {formatTime(log.created_at)} • {log.level.toUpperCase()}
                      </p>
                      <p>{log.message}</p>
                    </div>
                  ))
                )}
              </section>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
