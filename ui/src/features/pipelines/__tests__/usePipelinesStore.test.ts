import { beforeEach, describe, it, expect } from 'vitest'

import { usePipelinesStore } from '@/features/pipelines/store/usePipelinesStore'
import type { PipelineState, PipelineTask } from '@/features/pipelines/types'

const makeTask = (id: string, orderIndex: number): PipelineTask => ({
  id,
  jira_key: `TEST-${id}`,
  task_source: 'jira',
  task_relation: 'task',
  title: `Task ${id}`,
  workspace_path: '/workspace',
  jira_complete_column_name: '',
  starting_git_branch_override: '',
  workflow: 'codex',
  status: 'current',
  order_index: orderIndex,
  version: 1,
  failure_reason: '',
  is_bypassed: 0,
  bypass_reason: '',
  bypass_source: '',
  bypassed_at: '',
  bypassed_by: '',
  is_dependency_blocked: 0,
  dependency_block_reason: '',
  execution_state: 'ready',
  last_failure_code: '',
  jira_payload_json: '',
  jira_payload: {},
  active_run_id: '',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  runs: [],
  logs: [],
  dependencies: [],
  dependent_task_ids: [],
  unresolved_handoffs: [],
  unresolved_handoff_count: 0,
})

const makePipelineState = (currentTasks: PipelineTask[] = []): PipelineState => ({
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
    countdown_seconds: 300,
    last_heartbeat_at: '',
    last_cycle_at: '',
  },
  columns: {
    current: currentTasks,
    running: [],
    complete: [],
  },
  backlog: [],
})

describe('usePipelinesStore', () => {
  beforeEach(() => {
    usePipelinesStore.setState({
      state: null,
      isLoading: true,
      isMutating: false,
      error: null,
      mode: 'polling',
      pendingCurrentOrder: null,
    })
  })

  describe('initial state', () => {
    it('starts with null state', () => {
      expect(usePipelinesStore.getState().state).toBeNull()
    })

    it('starts with isLoading true', () => {
      expect(usePipelinesStore.getState().isLoading).toBe(true)
    })

    it('starts with isMutating false', () => {
      expect(usePipelinesStore.getState().isMutating).toBe(false)
    })

    it('starts with no error', () => {
      expect(usePipelinesStore.getState().error).toBeNull()
    })

    it('starts in polling mode', () => {
      expect(usePipelinesStore.getState().mode).toBe('polling')
    })
  })

  describe('setPipelineState', () => {
    it('sets the pipeline state', () => {
      const state = makePipelineState()
      usePipelinesStore.getState().setPipelineState(state)
      expect(usePipelinesStore.getState().state).toEqual(state)
    })

    it('allows setting state to null', () => {
      usePipelinesStore.getState().setPipelineState(makePipelineState())
      usePipelinesStore.getState().setPipelineState(null)
      expect(usePipelinesStore.getState().state).toBeNull()
    })
  })

  describe('setIsLoading', () => {
    it('updates isLoading', () => {
      usePipelinesStore.getState().setIsLoading(false)
      expect(usePipelinesStore.getState().isLoading).toBe(false)
    })
  })

  describe('setIsMutating', () => {
    it('updates isMutating', () => {
      usePipelinesStore.getState().setIsMutating(true)
      expect(usePipelinesStore.getState().isMutating).toBe(true)
    })
  })

  describe('setError', () => {
    it('sets error message', () => {
      usePipelinesStore.getState().setError('Something went wrong')
      expect(usePipelinesStore.getState().error).toBe('Something went wrong')
    })

    it('clears error when set to null', () => {
      usePipelinesStore.getState().setError('Error')
      usePipelinesStore.getState().setError(null)
      expect(usePipelinesStore.getState().error).toBeNull()
    })
  })

  describe('setMode', () => {
    it('switches to streaming mode', () => {
      usePipelinesStore.getState().setMode('streaming')
      expect(usePipelinesStore.getState().mode).toBe('streaming')
    })

    it('switches back to polling mode', () => {
      usePipelinesStore.getState().setMode('streaming')
      usePipelinesStore.getState().setMode('polling')
      expect(usePipelinesStore.getState().mode).toBe('polling')
    })
  })

  describe('applyPipelineState', () => {
    it('sets state and clears error', () => {
      usePipelinesStore.setState({ error: 'old error' })
      const incoming = makePipelineState()
      usePipelinesStore.getState().applyPipelineState(incoming)
      expect(usePipelinesStore.getState().state).toEqual(incoming)
      expect(usePipelinesStore.getState().error).toBeNull()
    })

    it('sets isLoading to false', () => {
      usePipelinesStore.getState().applyPipelineState(makePipelineState())
      expect(usePipelinesStore.getState().isLoading).toBe(false)
    })

    it('applies pending order when pendingCurrentOrder is set', () => {
      const taskA = makeTask('a', 0)
      const taskB = makeTask('b', 1)
      const taskC = makeTask('c', 2)

      usePipelinesStore.setState({ pendingCurrentOrder: ['c', 'a', 'b'] })

      const incoming = makePipelineState([taskA, taskB, taskC])
      usePipelinesStore.getState().applyPipelineState(incoming)

      const currentIds = usePipelinesStore.getState().state?.columns.current.map((t) => t.id)
      expect(currentIds).toEqual(['c', 'a', 'b'])
    })

    it('does not apply pending order when pendingCurrentOrder is null', () => {
      const taskA = makeTask('a', 0)
      const taskB = makeTask('b', 1)

      usePipelinesStore.setState({ pendingCurrentOrder: null })

      const incoming = makePipelineState([taskA, taskB])
      usePipelinesStore.getState().applyPipelineState(incoming)

      const currentIds = usePipelinesStore.getState().state?.columns.current.map((t) => t.id)
      expect(currentIds).toEqual(['a', 'b'])
    })

    it('does not apply pending order when pendingCurrentOrder is empty', () => {
      const taskA = makeTask('a', 0)
      const taskB = makeTask('b', 1)

      usePipelinesStore.setState({ pendingCurrentOrder: [] })

      const incoming = makePipelineState([taskA, taskB])
      usePipelinesStore.getState().applyPipelineState(incoming)

      const currentIds = usePipelinesStore.getState().state?.columns.current.map((t) => t.id)
      expect(currentIds).toEqual(['a', 'b'])
    })
  })

  describe('applyOptimisticReorder', () => {
    it('reorders current tasks optimistically when state has tasks', () => {
      const taskA = makeTask('a', 0)
      const taskB = makeTask('b', 1)
      const taskC = makeTask('c', 2)

      usePipelinesStore.setState({ state: makePipelineState([taskA, taskB, taskC]) })

      usePipelinesStore.getState().applyOptimisticReorder(['c', 'b', 'a'])

      const currentIds = usePipelinesStore.getState().state?.columns.current.map((t) => t.id)
      expect(currentIds).toEqual(['c', 'b', 'a'])
    })

    it('stores pending order for later application when state has no tasks', () => {
      usePipelinesStore.setState({ state: null })

      usePipelinesStore.getState().applyOptimisticReorder(['c', 'b', 'a'])

      expect(usePipelinesStore.getState().pendingCurrentOrder).toEqual(['c', 'b', 'a'])
    })

    it('places unknown task ids at the end of sorted order', () => {
      const taskA = makeTask('a', 0)
      const taskB = makeTask('b', 1)
      const taskC = makeTask('c', 2)

      usePipelinesStore.setState({ state: makePipelineState([taskA, taskB, taskC]) })

      usePipelinesStore.getState().applyOptimisticReorder(['b', 'a'])

      const currentIds = usePipelinesStore.getState().state?.columns.current.map((t) => t.id)
      expect(currentIds?.[0]).toBe('b')
      expect(currentIds?.[1]).toBe('a')
      expect(currentIds?.[2]).toBe('c')
    })
  })

  describe('clearOptimisticReorder', () => {
    it('clears the pending order', () => {
      usePipelinesStore.setState({ pendingCurrentOrder: ['a', 'b'] })
      usePipelinesStore.getState().clearOptimisticReorder()
      expect(usePipelinesStore.getState().pendingCurrentOrder).toBeNull()
    })
  })
})
