import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, it, expect, vi } from 'vitest'

import { usePipelinesData } from '@/features/pipelines/hooks/usePipelinesData'
import { usePipelinesStore } from '@/features/pipelines/store/usePipelinesStore'
import type { PipelineState } from '@/features/pipelines/types'

const mockPipelineState: PipelineState = {
  updated_at: '2024-01-01T00:00:00Z',
  settings: {
    active_window_start: '18:00',
    active_window_end: '06:00',
    heartbeat_interval_minutes: 60,
    last_heartbeat_at: '',
    last_cycle_at: '',
  },
  heartbeat: {
    active_window_start: '18:00',
    active_window_end: '06:00',
    heartbeat_interval_minutes: 60,
    active_window_state: 'active',
    is_active: true,
    next_heartbeat_at: '',
    countdown_seconds: 120,
    last_heartbeat_at: '',
    last_cycle_at: '',
  },
  columns: { current: [], running: [], complete: [] },
  backlog: [],
}

// Returns a mock fetch response object.
const mockResponse = (body: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 500,
  json: vi.fn().mockResolvedValue(body),
})

// Builds a fetch mock where:
//   1st call  → initial loadState on mount (always returns mockPipelineState)
//   2nd+ calls → provided in order via mutationResponses, then falls back to mockPipelineState
const buildFetchMock = (...mutationResponses: ReturnType<typeof mockResponse>[]) => {
  const queue = [...mutationResponses]

  return vi.fn()
    .mockResolvedValueOnce(mockResponse(mockPipelineState))
    .mockImplementation(() => {
      const next = queue.shift()
      if (next !== undefined) return Promise.resolve(next)
      return Promise.resolve(mockResponse(mockPipelineState))
    })
}

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close() {}
}

beforeEach(() => {
  MockEventSource.instances = []

  vi.stubGlobal('EventSource', MockEventSource)

  usePipelinesStore.setState({
    state: null,
    isLoading: true,
    isMutating: false,
    error: null,
    mode: 'polling',
    pendingCurrentOrder: null,
  })
})

describe('usePipelinesData', () => {
  describe('initial load via SSE + state fetch', () => {
    it('applies pipeline state on mount', async () => {
      vi.stubGlobal('fetch', buildFetchMock())

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.state).toEqual(mockPipelineState)
    })

    it('sets mode to streaming on mount', async () => {
      vi.stubGlobal('fetch', buildFetchMock())

      renderHook(() => usePipelinesData())

      await waitFor(() => expect(usePipelinesStore.getState().mode).toBe('streaming'))
    })

    it('sets error when state fetch fails', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({ ok: false, status: 500, json: vi.fn() })
      )

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.error).toBeTruthy())

      expect(result.current.error).toContain('500')
    })

    it('applies SSE message data to store', async () => {
      vi.stubGlobal('fetch', buildFetchMock())

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => MockEventSource.instances.length > 0)

      const updatedState = { ...mockPipelineState, updated_at: '2024-06-01T00:00:00Z' }

      act(() => {
        const es = MockEventSource.instances[0]
        es.onmessage?.({ data: JSON.stringify(updatedState) } as MessageEvent)
      })

      await waitFor(() =>
        expect(result.current.state?.updated_at).toBe('2024-06-01T00:00:00Z')
      )
    })

    it('sets error on SSE stream disconnect', async () => {
      vi.stubGlobal('fetch', buildFetchMock())

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => MockEventSource.instances.length > 0)

      act(() => {
        MockEventSource.instances[0].onerror?.()
      })

      await waitFor(() => expect(result.current.error).toBeTruthy())
    })
  })

  describe('heartbeatCountdown', () => {
    it('initialises heartbeat countdown from state', async () => {
      vi.stubGlobal('fetch', buildFetchMock())

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      expect(result.current.heartbeatCountdown).toBe(120)
    })
  })

  describe('refreshBacklog', () => {
    it('calls refresh endpoint and reloads state', async () => {
      // 1=initial loadState, 2=refresh POST, 3=subsequent loadState after refresh
      const fetchMock = buildFetchMock(
        mockResponse({ count: 5, fetched_at: '', tickets: [] }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.refreshBacklog())

      const refreshCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/backlog/refresh')
      )
      expect(refreshCall).toBeDefined()
      expect(refreshCall?.[1]).toMatchObject({ method: 'POST' })
    })

    it('sets error when refresh fails', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ detail: 'Refresh failed' }, false)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await expect(act(() => result.current.refreshBacklog())).rejects.toThrow()

      await waitFor(() => expect(result.current.error).toBeTruthy())
    })
  })

  describe('queueTask', () => {
    it('posts to queue endpoint with correct body', async () => {
      // 1=initial loadState, 2=queue POST, 3=subsequent loadState
      const fetchMock = buildFetchMock(
        mockResponse({ task: {} }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() =>
        result.current.queueTask('TEST-1', '/workspace', 'codex', 'Done', 'main', ['dep-1'], 'task')
      )

      const queueCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/queue')
      )
      expect(queueCall).toBeDefined()

      const body = JSON.parse((queueCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.jira_key).toBe('TEST-1')
      expect(body.workspace_path).toBe('/workspace')
      expect(body.workflow).toBe('codex')
      expect(body.jira_complete_column_name).toBe('Done')
      expect(body.starting_git_branch_override).toBe('main')
      expect(body.depends_on_task_ids).toEqual(['dep-1'])
      expect(body.task_relation).toBe('task')
    })

    it('extracts error detail from response body on failure', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ detail: 'Task already queued' }, false)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await expect(
        act(() => result.current.queueTask('TEST-1', '/workspace', 'codex'))
      ).rejects.toThrow('Task already queued')
    })
  })

  describe('moveTask', () => {
    it('posts to move endpoint with correct task id and target status', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ task: {} }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.moveTask('task-abc', 'backlog'))

      const moveCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/task-abc/move')
      )
      expect(moveCall).toBeDefined()
      expect(moveCall?.[1]).toMatchObject({ method: 'POST' })

      const body = JSON.parse((moveCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.target_status).toBe('backlog')
    })

    it('extracts error detail from response body on failure', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ detail: 'Task not found' }, false)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await expect(
        act(() => result.current.moveTask('task-abc', 'backlog'))
      ).rejects.toThrow('Task not found')
    })
  })

  describe('reorderCurrent', () => {
    it('applies optimistic reorder and posts to reorder endpoint', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ ok: true })
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.reorderCurrent(['b', 'a']))

      const reorderCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/reorder')
      )
      expect(reorderCall).toBeDefined()
      expect(reorderCall?.[1]).toMatchObject({ method: 'POST' })

      const body = JSON.parse((reorderCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.ordered_task_ids).toEqual(['b', 'a'])
    })

    it('clears pending order after successful reorder', async () => {
      const fetchMock = buildFetchMock(mockResponse({ ok: true }))

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.reorderCurrent(['b', 'a']))

      expect(usePipelinesStore.getState().pendingCurrentOrder).toBeNull()
    })
  })

  describe('updateSettings', () => {
    it('patches settings endpoint with correct body', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ settings: mockPipelineState.settings }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.updateSettings('20:00', '08:00', 120, 6))

      const settingsCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/settings')
      )
      expect(settingsCall).toBeDefined()
      expect(settingsCall?.[1]).toMatchObject({ method: 'PATCH' })

      const body = JSON.parse((settingsCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.active_window_start).toBe('20:00')
      expect(body.active_window_end).toBe('08:00')
      expect(body.heartbeat_interval_minutes).toBe(120)
      expect(body.max_retries).toBe(6)
    })
  })

  describe('setTaskBypass', () => {
    it('patches bypass endpoint with bypassed flag and reason', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({}),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.setTaskBypass('task-1', true, 'Manual skip', true))

      const bypassCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/task-1/bypass')
      )
      expect(bypassCall).toBeDefined()
      expect(bypassCall?.[1]).toMatchObject({ method: 'PATCH' })

      const body = JSON.parse((bypassCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.bypassed).toBe(true)
      expect(body.reason).toBe('Manual skip')
      expect(body.resolve_handoffs).toBe(true)
    })
  })

  describe('resolveTaskHandoff', () => {
    it('posts to resolve handoff endpoint', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ task_id: 'task-1', handoffs: [] }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.resolveTaskHandoff('task-1', 'handoff-9', true))

      const resolveCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/task-1/handoffs/handoff-9/resolve')
      )
      expect(resolveCall).toBeDefined()
      expect(resolveCall?.[1]).toMatchObject({ method: 'POST' })

      const body = JSON.parse((resolveCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.reenable_task).toBe(true)
    })
  })

  describe('setTaskDependencies', () => {
    it('puts task dependencies endpoint with correct ids', async () => {
      const fetchMock = buildFetchMock(
        mockResponse({ task_id: 'task-1', dependencies: [] }),
        mockResponse(mockPipelineState)
      )

      vi.stubGlobal('fetch', fetchMock)

      const { result } = renderHook(() => usePipelinesData())

      await waitFor(() => expect(result.current.isLoading).toBe(false))

      await act(() => result.current.setTaskDependencies('task-1', ['task-2', 'task-3']))

      const depsCall = fetchMock.mock.calls.find(([url]: [string]) =>
        String(url).includes('/api/pipelines/tasks/task-1/dependencies')
      )
      expect(depsCall).toBeDefined()
      expect(depsCall?.[1]).toMatchObject({ method: 'PUT' })

      const body = JSON.parse((depsCall?.[1] as RequestInit).body as string) as Record<string, unknown>
      expect(body.depends_on_task_ids).toEqual(['task-2', 'task-3'])
    })
  })
})
