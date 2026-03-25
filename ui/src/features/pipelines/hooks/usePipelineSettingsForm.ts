import { useCallback, useEffect, useState } from "react"

import type { HeartbeatUnit, PipelineSettings } from "@/features/pipelines/types"

type UsePipelineSettingsFormArgs = {
  settings?: PipelineSettings
  onSave: (
    activeWindowStart: string,
    activeWindowEnd: string,
    heartbeatIntervalMinutes: number,
    maxRetries: number
  ) => Promise<void>
}

export const usePipelineSettingsForm = ({ settings, onSave }: UsePipelineSettingsFormArgs) => {
  const [startTime, setStartTime] = useState("18:00")
  const [endTime, setEndTime] = useState("06:00")
  const [heartbeatValue, setHeartbeatValue] = useState(5)
  const [heartbeatUnit, setHeartbeatUnit] = useState<HeartbeatUnit>("minutes")
  const [maxRetries, setMaxRetries] = useState(4)

  const settingsStart = settings?.active_window_start
  const settingsEnd = settings?.active_window_end
  const settingsInterval = settings?.heartbeat_interval_minutes
  const settingsMaxRetries = settings?.max_retries

  useEffect(() => {
    if (settingsStart === undefined && settingsEnd === undefined && settingsInterval === undefined) {
      return
    }

    const minutes = Number(settingsInterval || 5)
    if (minutes >= 60 && minutes % 60 === 0) {
      setHeartbeatUnit("hours")
      setHeartbeatValue(Math.max(1, minutes / 60))
    } else {
      setHeartbeatUnit("minutes")
      setHeartbeatValue(Math.max(5, minutes))
    }

    setStartTime(settingsStart || "18:00")
    setEndTime(settingsEnd || "06:00")
    setMaxRetries(Math.min(12, Math.max(1, Number(settingsMaxRetries || 4))))
  }, [settingsEnd, settingsInterval, settingsMaxRetries, settingsStart])

  const handleSaveSettings = useCallback(async () => {
    const intervalMinutes = heartbeatUnit === "hours" ? heartbeatValue * 60 : heartbeatValue
    await onSave(startTime, endTime, Math.max(5, intervalMinutes), Math.min(12, Math.max(1, maxRetries)))
  }, [endTime, heartbeatUnit, heartbeatValue, maxRetries, onSave, startTime])

  return {
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
    handleSaveSettings,
  }
}
