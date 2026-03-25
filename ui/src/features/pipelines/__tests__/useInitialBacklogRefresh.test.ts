import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { useInitialBacklogRefresh } from '@/features/pipelines/hooks/useInitialBacklogRefresh'

describe('useInitialBacklogRefresh', () => {
  it('calls refreshBacklog when not loading and backlog is empty', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    renderHook(() =>
      useInitialBacklogRefresh({ isLoading: false, backlogLength: 0, refreshBacklog })
    )

    expect(refreshBacklog).toHaveBeenCalledOnce()
  })

  it('does not call refreshBacklog while loading', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    renderHook(() =>
      useInitialBacklogRefresh({ isLoading: true, backlogLength: 0, refreshBacklog })
    )

    expect(refreshBacklog).not.toHaveBeenCalled()
  })

  it('does not call refreshBacklog when backlog is not empty', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    renderHook(() =>
      useInitialBacklogRefresh({ isLoading: false, backlogLength: 5, refreshBacklog })
    )

    expect(refreshBacklog).not.toHaveBeenCalled()
  })

  it('only calls refreshBacklog once even if re-rendered', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    const { rerender } = renderHook(
      ({ isLoading, backlogLength }: { isLoading: boolean; backlogLength: number }) =>
        useInitialBacklogRefresh({ isLoading, backlogLength, refreshBacklog }),
      { initialProps: { isLoading: false, backlogLength: 0 } }
    )

    rerender({ isLoading: false, backlogLength: 0 })
    rerender({ isLoading: false, backlogLength: 0 })

    expect(refreshBacklog).toHaveBeenCalledOnce()
  })

  it('does not call refreshBacklog when loading completes but backlog already has items', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    const { rerender } = renderHook(
      ({ isLoading, backlogLength }: { isLoading: boolean; backlogLength: number }) =>
        useInitialBacklogRefresh({ isLoading, backlogLength, refreshBacklog }),
      { initialProps: { isLoading: true, backlogLength: 0 } }
    )

    rerender({ isLoading: false, backlogLength: 3 })

    expect(refreshBacklog).not.toHaveBeenCalled()
  })

  it('calls refreshBacklog when loading transitions from true to false with empty backlog', () => {
    const refreshBacklog = vi.fn().mockResolvedValue(undefined)

    const { rerender } = renderHook(
      ({ isLoading, backlogLength }: { isLoading: boolean; backlogLength: number }) =>
        useInitialBacklogRefresh({ isLoading, backlogLength, refreshBacklog }),
      { initialProps: { isLoading: true, backlogLength: 0 } }
    )

    expect(refreshBacklog).not.toHaveBeenCalled()

    rerender({ isLoading: false, backlogLength: 0 })

    expect(refreshBacklog).toHaveBeenCalledOnce()
  })
})
