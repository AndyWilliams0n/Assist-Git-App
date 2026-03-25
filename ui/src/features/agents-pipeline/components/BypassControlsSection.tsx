import { Loader2 } from "lucide-react"

import { Switch } from "@/shared/components/ui/switch"
import { TabsContent } from "@/shared/components/ui/tabs"

export type BypassKey = "jiraApi" | "sddSpec" | "codeBuilder" | "codeReview"

export type BypassState = {
  jiraApi: boolean
  sddSpec: boolean
  codeBuilder: boolean
  codeReview: boolean
}

type BypassItem = {
  key: BypassKey
  title: string
  description: string
}

type BypassControlsSectionProps = {
  bypassError: string | null
  localBypass: BypassState
  onToggleBypass: (key: BypassKey, checked: boolean) => Promise<void>
  updatingBypass: BypassKey | null
}

const BYPASS_ITEMS: BypassItem[] = [
  {
    key: "jiraApi",
    title: "Jira REST API Agent",
    description: "Disables Jira ticket execution and routes around the Jira workflow node.",
  },
  {
    key: "sddSpec",
    title: "SDD Spec Agent",
    description: "Falls back to legacy planner/pipeline bundle generation.",
  },
  {
    key: "codeBuilder",
    title: "Code Builder Codex",
    description: "Passes directly to Code Review Agent.",
  },
  {
    key: "codeReview",
    title: "Code Review Agent",
    description: "Runs Codex CLI review and tasks.md verification before final handoff.",
  },
]

function BypassControlRow({
  checked,
  description,
  disabled,
  isLoading,
  label,
  onCheckedChange,
}: {
  checked: boolean
  description: string
  disabled: boolean
  isLoading: boolean
  label: string
  onCheckedChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <div className="text-sm font-medium">{label}</div>

        <div className="text-muted-foreground text-xs">{description}</div>
      </div>

      <div className="flex items-center gap-2">
        {isLoading ? <Loader2 className="text-muted-foreground size-4 animate-spin" /> : null}

        <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
      </div>
    </div>
  )
}

export default function BypassControlsSection({
  bypassError,
  localBypass,
  onToggleBypass,
  updatingBypass,
}: BypassControlsSectionProps) {
  const disabled = updatingBypass !== null

  return (
    <TabsContent value="settings" className="mt-0">
      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-lg font-semibold">Bypass Controls</h2>

        <p className="text-muted-foreground text-sm">
          Bypass disables the selected agent and forwards the request to the next pipeline node.
        </p>

        <div className="mt-3 space-y-3">
          {BYPASS_ITEMS.map((item) => (
            <BypassControlRow
              key={item.key}
              checked={localBypass[item.key]}
              description={item.description}
              disabled={disabled}
              isLoading={updatingBypass === item.key}
              label={item.title}
              onCheckedChange={(checked) => {
                void onToggleBypass(item.key, checked)
              }}
            />
          ))}
        </div>

        {bypassError ? (
          <div className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-700">
            {bypassError}
          </div>
        ) : null}
      </section>
    </TabsContent>
  )
}
