import * as React from "react"
import { RotateCcw, Save } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/components/ui/card"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/components/ui/select"
import { Switch } from "@/shared/components/ui/switch"
import { Textarea } from "@/shared/components/ui/textarea"
import { Separator } from "@/shared/components/ui/separator"
import { useGitStore } from "../store/git-store"
import type { GitPlatform, GitWorkflowKey } from "../types"

interface GitSettingsProps {
  workflowKey: GitWorkflowKey
  title: string
  description: string
}

function PatternHint({ vars }: { vars: string[] }) {
  return (
    <p className="text-xs text-muted-foreground mt-1">
      Variables:{" "}
      {vars.map((v) => (
        <code key={v} className="mx-0.5 font-mono bg-muted px-1 rounded">{`{${v}}`}</code>
      ))}
    </p>
  )
}

export function GitSettings({ workflowKey, title, description }: GitSettingsProps) {
  const settings = useGitStore((s) => s.workflows[workflowKey].settings)
  const updateSettings = useGitStore((s) => s.updateSettings)
  const resetSettings = useGitStore((s) => s.resetSettings)

  // Local draft state
  const [draft, setDraft] = React.useState(settings)
  const [saved, setSaved] = React.useState(false)

  // Keep draft in sync when settings change externally
  React.useEffect(() => {
    setDraft(settings)
  }, [settings])

  function handleSave() {
    updateSettings(workflowKey, draft)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function handleReset() {
    resetSettings(workflowKey)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <CardDescription className="text-xs">
          {description}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Platform */}
        <div className="space-y-1.5">
          <Label>Git Platform</Label>
          <Select
            value={draft.platform}
            onValueChange={(v) => setDraft((d) => ({ ...d, platform: v as GitPlatform }))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto-detect (from remote URL)</SelectItem>
              <SelectItem value="github">GitHub (uses gh CLI)</SelectItem>
              <SelectItem value="gitlab">GitLab (uses glab CLI)</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Auto-detect reads the remote URL to choose the right CLI tool.
          </p>
        </div>

        {/* Branch naming */}
        <div className="space-y-1.5">
          <Label>Branch Name Pattern</Label>
          <Input
            value={draft.branchNamePattern}
            onChange={(e) => setDraft((d) => ({ ...d, branchNamePattern: e.target.value }))}
            placeholder="feature/{description}"
          />
          <PatternHint vars={["description", "ticket", "type", "date"]} />
        </div>

        {/* Commit message */}
        <div className="space-y-1.5">
          <Label>Commit Message Pattern</Label>
          <Input
            value={draft.commitMessagePattern}
            onChange={(e) => setDraft((d) => ({ ...d, commitMessagePattern: e.target.value }))}
            placeholder="feat: {description}"
          />
          <PatternHint vars={["description", "ticket", "type", "branch"]} />
        </div>

        <Separator />

        {/* PR title */}
        <div className="space-y-1.5">
          <Label>PR / MR Title Pattern</Label>
          <Input
            value={draft.prTitlePattern}
            onChange={(e) => setDraft((d) => ({ ...d, prTitlePattern: e.target.value }))}
            placeholder="feat: {description}"
          />
          <PatternHint vars={["description", "ticket", "branch", "type"]} />
        </div>

        {/* PR body */}
        <div className="space-y-1.5">
          <Label>PR / MR Body Template</Label>
          <Textarea
            value={draft.prBodyTemplate}
            onChange={(e) => setDraft((d) => ({ ...d, prBodyTemplate: e.target.value }))}
            placeholder="## Summary&#10;&#10;{description}"
            rows={6}
          />
          <PatternHint vars={["description", "ticket", "branch", "summary"]} />
        </div>

        <Separator />

        {/* Toggles */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm">Auto-detect Git on Open</Label>
              <p className="text-xs text-muted-foreground">
                Automatically check workspace git status when the page loads
              </p>
            </div>
            <Switch
              checked={draft.autoDetect}
              onCheckedChange={(v) => setDraft((d) => ({ ...d, autoDetect: v }))}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm">Auto-push After Commit</Label>
              <p className="text-xs text-muted-foreground">
                Automatically push to remote after committing
              </p>
            </div>
            <Switch
              checked={draft.autoPushOnCommit}
              onCheckedChange={(v) => setDraft((d) => ({ ...d, autoPushOnCommit: v }))}
            />
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-2">
          <Button onClick={handleSave} size="sm" className="gap-1.5">
            <Save className="size-3.5" />
            {saved ? "Saved!" : "Save Settings"}
          </Button>
          <Button variant="ghost" size="sm" className="gap-1.5" onClick={handleReset}>
            <RotateCcw className="size-3.5" />
            Reset Defaults
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
