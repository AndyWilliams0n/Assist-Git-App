import { Button } from "@/shared/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/shared/components/ui/card"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/shared/components/ui/toggle-group"
import type { HeartbeatUnit } from "@/features/pipelines/types"

export type BacklogWorkflowFilter = "all" | "specs" | "tickets"

type PipelineSettingsPanelProps = {
  startTime: string
  setStartTime: (value: string) => void
  endTime: string
  setEndTime: (value: string) => void
  heartbeatValue: number
  setHeartbeatValue: (value: number) => void
  heartbeatUnit: HeartbeatUnit
  setHeartbeatUnit: (value: HeartbeatUnit) => void
  maxRetries: number
  setMaxRetries: (value: number) => void
  automationEnabled: boolean
  handleSaveSettings: () => Promise<void>
  handleStartPipelineShortly: () => Promise<void>
  handleTriggerNextTaskNow: () => Promise<void>
  handleEnableAutomation: () => Promise<void>
  handleDisableAutomation: () => Promise<void>
  isMutating: boolean
  backlogWorkflowFilter: BacklogWorkflowFilter
  onBacklogWorkflowFilterChange: (value: BacklogWorkflowFilter) => void
}

export default function PipelineSettingsPanel({
  startTime,
  setStartTime,
  endTime,
  setEndTime,
  heartbeatValue,
  setHeartbeatValue,
  heartbeatUnit,
  setHeartbeatUnit,
  maxRetries,
  setMaxRetries,
  automationEnabled,
  handleSaveSettings,
  handleStartPipelineShortly,
  handleTriggerNextTaskNow,
  handleEnableAutomation,
  handleDisableAutomation,
  isMutating,
  backlogWorkflowFilter,
  onBacklogWorkflowFilterChange,
}: PipelineSettingsPanelProps) {
  return (
    <Card className="gap-0 py-0 shadow-none">
      <CardHeader className="px-4 pt-4 pb-3 sm:px-5">
        <CardTitle className="text-base">Schedule Settings</CardTitle>
        <CardDescription>Set the active window and heartbeat for pipeline processing.</CardDescription>
      </CardHeader>

      <CardContent className="px-4 pb-4 sm:px-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-2">
            <Label htmlFor="pipeline-start-time">Start</Label>
            <Input
              id="pipeline-start-time"
              type="time"
              value={startTime}
              onChange={(event) => setStartTime(event.target.value)}
              className="appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-inner-spin-button]:hidden [&::-webkit-clear-button]:hidden"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="pipeline-end-time">End</Label>
            <Input
              id="pipeline-end-time"
              type="time"
              value={endTime}
              onChange={(event) => setEndTime(event.target.value)}
              className="appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-inner-spin-button]:hidden [&::-webkit-clear-button]:hidden"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="pipeline-heartbeat-value">Heartbeat</Label>
            <Input
              id="pipeline-heartbeat-value"
              type="number"
              min={1}
              value={heartbeatValue}
              onChange={(event) => setHeartbeatValue(Math.max(1, Number(event.target.value || 1)))}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="pipeline-heartbeat-unit">Unit</Label>
            <Select value={heartbeatUnit} onValueChange={(value) => setHeartbeatUnit(value as HeartbeatUnit)}>
              <SelectTrigger id="pipeline-heartbeat-unit">
                <SelectValue placeholder="Select unit" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="minutes">Minutes</SelectItem>
                <SelectItem value="hours">Hours</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="pipeline-max-retries">Max retries</Label>
            <Input
              id="pipeline-max-retries"
              type="number"
              min={1}
              max={12}
              value={maxRetries}
              onChange={(event) => setMaxRetries(Math.min(12, Math.max(1, Number(event.target.value || 1))))}
            />
          </div>
        </div>
      </CardContent>

      <CardFooter className="border-t !px-4 !py-3 sm:px-5">
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" disabled={isMutating} onClick={() => void handleStartPipelineShortly()}>
              Start Pipeline Shortly
            </Button>

            <Button variant="outline" disabled={isMutating} onClick={() => void handleTriggerNextTaskNow()}>
              Trigger Next Task Now
            </Button>

            <Button
              disabled={isMutating || automationEnabled}
              onClick={() => void handleEnableAutomation()}
              className="bg-green-600 text-white hover:bg-green-700 disabled:bg-green-600/60"
            >
              Enable Automation
            </Button>

            <Button
              disabled={isMutating || !automationEnabled}
              onClick={() => void handleDisableAutomation()}
              className="bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/60"
            >
              Disable Automation
            </Button>

            <Button disabled={isMutating} onClick={() => void handleSaveSettings()}>
              Save Settings
            </Button>
          </div>

          <ToggleGroup
            type="single"
            value={backlogWorkflowFilter}
            onValueChange={(value) => {
              if (!value) return
              onBacklogWorkflowFilterChange(value as BacklogWorkflowFilter)
            }}
            aria-label="Backlog workflow filter"
          >
            <ToggleGroupItem value="all" aria-label="Show all workflow types">
              ALL
            </ToggleGroupItem>

            <ToggleGroupItem value="specs" aria-label="Show specs only">
              SPECS
            </ToggleGroupItem>

            <ToggleGroupItem value="tickets" aria-label="Show jira tickets only">
              TICKETS
            </ToggleGroupItem>
          </ToggleGroup>
        </div>

      </CardFooter>
    </Card>
  )
}
