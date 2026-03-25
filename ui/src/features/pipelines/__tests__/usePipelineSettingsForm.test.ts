import { act, renderHook } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { usePipelineSettingsForm } from '@/features/pipelines/hooks/usePipelineSettingsForm'
import type { PipelineSettings } from '@/features/pipelines/types'

const makeSettings = (overrides: Partial<PipelineSettings> = {}): PipelineSettings => ({
  active_window_start: '18:00',
  active_window_end: '06:00',
  heartbeat_interval_minutes: 60,
  max_retries: 4,
  last_heartbeat_at: '',
  last_cycle_at: '',
  ...overrides,
})

describe('usePipelineSettingsForm', () => {
  describe('default values when no settings provided', () => {
    it('defaults startTime to 18:00', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      expect(result.current.startTime).toBe('18:00')
    })

    it('defaults endTime to 06:00', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      expect(result.current.endTime).toBe('06:00')
    })

    it('defaults heartbeatValue to 5', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      expect(result.current.heartbeatValue).toBe(5)
    })

    it('defaults heartbeatUnit to minutes', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      expect(result.current.heartbeatUnit).toBe('minutes')
    })

    it('defaults maxRetries to 4', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      expect(result.current.maxRetries).toBe(4)
    })
  })

  describe('settings initialisation', () => {
    it('loads startTime from settings', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ settings: makeSettings({ active_window_start: '09:00' }), onSave: vi.fn() })
      )

      expect(result.current.startTime).toBe('09:00')
    })

    it('loads endTime from settings', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ settings: makeSettings({ active_window_end: '17:00' }), onSave: vi.fn() })
      )

      expect(result.current.endTime).toBe('17:00')
    })

    it('converts 60-minute interval to 1 hour', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ heartbeat_interval_minutes: 60 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.heartbeatUnit).toBe('hours')
      expect(result.current.heartbeatValue).toBe(1)
    })

    it('converts 120-minute interval to 2 hours', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ heartbeat_interval_minutes: 120 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.heartbeatUnit).toBe('hours')
      expect(result.current.heartbeatValue).toBe(2)
    })

    it('keeps minutes unit when interval is not a whole-hour multiple', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ heartbeat_interval_minutes: 30 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.heartbeatUnit).toBe('minutes')
      expect(result.current.heartbeatValue).toBe(30)
    })

    it('enforces minimum heartbeat value of 5 minutes', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ heartbeat_interval_minutes: 2 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.heartbeatValue).toBe(5)
    })

    it('loads maxRetries from settings', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ max_retries: 8 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.maxRetries).toBe(8)
    })

    it('clamps maxRetries to max of 12', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ max_retries: 20 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.maxRetries).toBe(12)
    })

    it('falls back to default of 4 when max_retries is 0 (falsy)', () => {
      // The hook uses `Number(settingsMaxRetries || 4)` so 0 falls back to 4
      const { result } = renderHook(() =>
        usePipelineSettingsForm({
          settings: makeSettings({ max_retries: 0 }),
          onSave: vi.fn(),
        })
      )

      expect(result.current.maxRetries).toBe(4)
    })
  })

  describe('form field setters', () => {
    it('setStartTime updates startTime', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      act(() => result.current.setStartTime('10:00'))

      expect(result.current.startTime).toBe('10:00')
    })

    it('setEndTime updates endTime', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      act(() => result.current.setEndTime('22:00'))

      expect(result.current.endTime).toBe('22:00')
    })

    it('setHeartbeatValue updates heartbeatValue', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      act(() => result.current.setHeartbeatValue(15))

      expect(result.current.heartbeatValue).toBe(15)
    })

    it('setHeartbeatUnit updates heartbeatUnit', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      act(() => result.current.setHeartbeatUnit('hours'))

      expect(result.current.heartbeatUnit).toBe('hours')
    })

    it('setMaxRetries updates maxRetries', () => {
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave: vi.fn() })
      )

      act(() => result.current.setMaxRetries(6))

      expect(result.current.maxRetries).toBe(6)
    })
  })

  describe('handleSaveSettings', () => {
    it('calls onSave with minutes value when unit is minutes', async () => {
      const onSave = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave })
      )

      act(() => {
        result.current.setStartTime('20:00')
        result.current.setEndTime('08:00')
        result.current.setHeartbeatUnit('minutes')
        result.current.setHeartbeatValue(30)
        result.current.setMaxRetries(3)
      })

      await act(() => result.current.handleSaveSettings())

      expect(onSave).toHaveBeenCalledWith('20:00', '08:00', 30, 3)
    })

    it('converts hours to minutes when unit is hours', async () => {
      const onSave = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave })
      )

      act(() => {
        result.current.setHeartbeatUnit('hours')
        result.current.setHeartbeatValue(2)
      })

      await act(() => result.current.handleSaveSettings())

      expect(onSave).toHaveBeenCalledWith('18:00', '06:00', 120, 4)
    })

    it('enforces minimum interval of 5 minutes on save', async () => {
      const onSave = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave })
      )

      act(() => {
        result.current.setHeartbeatUnit('minutes')
        result.current.setHeartbeatValue(1)
      })

      await act(() => result.current.handleSaveSettings())

      const savedInterval = (onSave.mock.calls[0] as [string, string, number, number])[2]
      expect(savedInterval).toBeGreaterThanOrEqual(5)
    })

    it('clamps maxRetries to 1-12 range on save', async () => {
      const onSave = vi.fn().mockResolvedValue(undefined)
      const { result } = renderHook(() =>
        usePipelineSettingsForm({ onSave })
      )

      act(() => result.current.setMaxRetries(99))

      await act(() => result.current.handleSaveSettings())

      const savedRetries = (onSave.mock.calls[0] as [string, string, number, number])[3]
      expect(savedRetries).toBe(12)
    })
  })
})
