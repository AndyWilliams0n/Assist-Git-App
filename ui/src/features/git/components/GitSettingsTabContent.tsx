import { Separator } from "@/shared/components/ui/separator"
import { TokenSettingsCard } from "../../workspace/components/TokenSettingsCard"
import { GitSettings } from "./GitSettings"
import type { GitWorkflowKey } from "../types"

interface WorkflowSettingsSection {
  key: GitWorkflowKey
  settingsTitle: string
  settingsDescription: string
}

interface GitSettingsTabContentProps {
  workflows: WorkflowSettingsSection[]
}

export function GitSettingsTabContent({ workflows }: GitSettingsTabContentProps) {
  return (
    <>
      <Separator />

      <div className="space-y-4">
        <TokenSettingsCard />

        <div className="grid gap-4 xl:grid-cols-2">
          {workflows.map((workflow) => (
            <section key={`settings-${workflow.key}`} className="space-y-2">
              <GitSettings
                workflowKey={workflow.key}
                title={workflow.settingsTitle}
                description={workflow.settingsDescription}
              />
            </section>
          ))}
        </div>
      </div>
    </>
  )
}
