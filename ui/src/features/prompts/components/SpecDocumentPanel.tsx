import * as React from "react"
import { CheckCircle2, FileText, Loader2, Save, XCircle } from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/shared/components/ui/tabs"
import { Editor } from "@/shared/components/editor"
import { PanelHeader } from "@/shared/components/panel-header"
import { cn } from "@/shared/utils/utils.ts"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"
import type { SaveState, SpecContentState, SpecTab } from "@/features/prompts/types"

type SpecDocumentPanelProps = {
  activeTab: SpecTab
  content: SpecContentState
  isLoading: boolean
  loadingMessage?: string
  isSaving: boolean
  saveState: SaveState
  onTabChange: (tab: SpecTab) => void
  onContentChange: (value: string) => void
  onSave: () => void
  className?: string
}

const SPEC_TABS: SpecTab[] = ["requirements.md", "design.md", "tasks.md"]

const saveStatusLabel = (state: SaveState, isSaving: boolean) => {
  if (isSaving) return "Saving..."
  if (state.status === "success") return state.message || "Saved"
  if (state.status === "error") return state.message || "Save failed"
  return "Ready"
}

export function SpecDocumentPanel({
  activeTab,
  content,
  isLoading,
  loadingMessage,
  isSaving,
  saveState,
  onTabChange,
  onContentChange,
  onSave,
  className,
}: SpecDocumentPanelProps) {
  const theme = useDashboardSettingsStore((state) => state.theme)

  const [isWordWrapEnabled, setIsWordWrapEnabled] = React.useState(true)

  const contentValue = content[activeTab] || ""

  return (
    <section className={cn("relative flex h-full min-h-0 flex-col bg-background", className)}>
      <PanelHeader
        icon={<FileText className="text-muted-foreground size-4" />}
        title="Editor"
        description="requirements / design / tasks"
        borderBottom
      >
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={isLoading || isSaving}
          onClick={() => {
            setIsWordWrapEnabled((current) => !current)
          }}
          className="h-7 px-2 text-xs"
        >
          {isWordWrapEnabled ? "Wrap: on" : "Wrap: off"}
        </Button>
      </PanelHeader>

      <Tabs
        value={activeTab}
        onValueChange={(value) => onTabChange(value as SpecTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="mx-3 mt-3 !flex !flex-row items-stretch justify-start">
          {SPEC_TABS.map((tab) => (
            <TabsTrigger key={tab} value={tab} className="!w-auto !flex-none !justify-center text-xs md:text-sm">
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="min-h-0 flex-1 px-3 pt-3 pb-2">
          <Editor
            value={contentValue}
            onChange={onContentChange}
            isWordWrapEnabled={isWordWrapEnabled}
            placeholder="Enter markdown content..."
            ariaLabel={`${activeTab} editor`}
            disabled={isLoading || isSaving}
            isLoading={isLoading}
            loadingMessage={loadingMessage || "Generating spec content..."}
            colorScheme={theme}
          />
        </div>
      </Tabs>

      <div className="flex items-center justify-between border-t px-3 py-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-xs",
            saveState.status === "error" ? "text-rose-600" : "text-muted-foreground"
          )}
        >
          {saveState.status === "success" ? <CheckCircle2 className="size-3.5" /> : null}
          {saveState.status === "error" ? <XCircle className="size-3.5" /> : null}
          {isSaving ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {saveStatusLabel(saveState, isSaving)}
        </span>

        <Button
          type="button"
          size="sm"
          onClick={onSave}
          disabled={isLoading || isSaving}
          className="gap-1.5"
        >
          <Save className="size-4" />
          Save
        </Button>
      </div>
    </section>
  )
}

export default SpecDocumentPanel
