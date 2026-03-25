import { act, renderHook } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { usePipelineBoardInteractions } from '@/features/pipelines/hooks/usePipelineBoardInteractions'
import type { PipelineBacklogItem, PipelineTask } from '@/features/pipelines/types'

const makeTask = (id: string): PipelineTask => ({
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
  order_index: 0,
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

const makeBacklogItem = (overrides: Partial<PipelineBacklogItem> = {}): PipelineBacklogItem => ({
  key: 'TEST-100',
  task_source: 'jira',
  task_reference: 'TEST-100',
  title: 'Backlog ticket',
  issue_type: 'Story',
  status: 'To Do',
  priority: 'Medium',
  assignee: '',
  updated: '',
  fetched_at: '',
  payload: {},
  ...overrides,
})

describe('usePipelineBoardInteractions', () => {
  describe('selectedTask', () => {
    it('starts with no selected task', () => {
      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker: vi.fn(),
        })
      )

      expect(result.current.selectedTask).toBeNull()
      expect(result.current.selectedTaskId).toBeNull()
    })

    it('setSelectedTaskId selects a task', () => {
      const taskA = makeTask('a')

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA],
          allTasks: [taskA],
          reorderCurrent: vi.fn(),
          openWorkspacePicker: vi.fn(),
        })
      )

      act(() => result.current.setSelectedTaskId('a'))

      expect(result.current.selectedTaskId).toBe('a')
      expect(result.current.selectedTask).toEqual(taskA)
    })

    it('clears selectedTaskId when the selected task is removed from allTasks', () => {
      const taskA = makeTask('a')

      const { result, rerender } = renderHook(
        ({ allTasks }: { allTasks: PipelineTask[] }) =>
          usePipelineBoardInteractions({
            currentTasks: [],
            allTasks,
            reorderCurrent: vi.fn(),
            openWorkspacePicker: vi.fn(),
          }),
        { initialProps: { allTasks: [taskA] } }
      )

      act(() => result.current.setSelectedTaskId('a'))

      expect(result.current.selectedTaskId).toBe('a')

      rerender({ allTasks: [] })

      expect(result.current.selectedTaskId).toBeNull()
    })
  })

  describe('reorderCurrentToEnd', () => {
    it('moves a task to the end of the current list', async () => {
      const taskA = makeTask('a')
      const taskB = makeTask('b')
      const taskC = makeTask('c')
      const reorderCurrent = vi.fn().mockResolvedValue(undefined)

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA, taskB, taskC],
          allTasks: [taskA, taskB, taskC],
          reorderCurrent,
          openWorkspacePicker: vi.fn(),
        })
      )

      await act(() => result.current.reorderCurrentToEnd('a'))

      expect(reorderCurrent).toHaveBeenCalledWith(['b', 'c', 'a'])
    })

    it('has no effect when taskId is not in the list', async () => {
      const taskA = makeTask('a')
      const reorderCurrent = vi.fn().mockResolvedValue(undefined)

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA],
          allTasks: [taskA],
          reorderCurrent,
          openWorkspacePicker: vi.fn(),
        })
      )

      await act(() => result.current.reorderCurrentToEnd('unknown'))

      expect(reorderCurrent).toHaveBeenCalledWith(['a'])
    })
  })

  describe('reorderCurrentBefore', () => {
    it('moves a task before another task', async () => {
      const taskA = makeTask('a')
      const taskB = makeTask('b')
      const taskC = makeTask('c')
      const reorderCurrent = vi.fn().mockResolvedValue(undefined)

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA, taskB, taskC],
          allTasks: [taskA, taskB, taskC],
          reorderCurrent,
          openWorkspacePicker: vi.fn(),
        })
      )

      await act(() => result.current.reorderCurrentBefore('c', 'a'))

      expect(reorderCurrent).toHaveBeenCalledWith(['c', 'a', 'b'])
    })

    it('has no effect when moving task before itself', async () => {
      const taskA = makeTask('a')
      const taskB = makeTask('b')
      const reorderCurrent = vi.fn().mockResolvedValue(undefined)

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA, taskB],
          allTasks: [taskA, taskB],
          reorderCurrent,
          openWorkspacePicker: vi.fn(),
        })
      )

      await act(() => result.current.reorderCurrentBefore('a', 'a'))

      expect(reorderCurrent).toHaveBeenCalledWith(['a', 'b'])
    })

    it('has no effect when either task id is not found', async () => {
      const taskA = makeTask('a')
      const reorderCurrent = vi.fn().mockResolvedValue(undefined)

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [taskA],
          allTasks: [taskA],
          reorderCurrent,
          openWorkspacePicker: vi.fn(),
        })
      )

      await act(() => result.current.reorderCurrentBefore('a', 'unknown'))

      expect(reorderCurrent).toHaveBeenCalledWith(['a'])
    })
  })

  describe('queueFromBacklog', () => {
    it('calls openWorkspacePicker with queue action and jira key', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ key: 'TEST-42' })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ kind: 'queue', jiraKey: 'TEST-42' })
      )
    })

    it('extracts workspace_path from payload', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { workspace_path: '/projects/my-app' } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ workspacePath: '/projects/my-app' })
      )
    })

    it('extracts starting_git_branch_override from payload', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({
        payload: { starting_git_branch_override: 'feature/my-branch' },
      })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ startingGitBranchOverride: 'feature/my-branch' })
      )
    })

    it('uses branch fallback chain: starting_git_branch_override > working_branch > branch', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { branch: 'develop', working_branch: 'feature/from-working' } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ startingGitBranchOverride: 'feature/from-working' })
      )
    })

    it('sets defaultTaskType to subtask when dependency_mode is subtask', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { dependency_mode: 'subtask' } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ defaultTaskType: 'subtask' })
      )
    })

    it('sets defaultTaskType to task when dependency_mode is not subtask', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: {} })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ defaultTaskType: 'task' })
      )
    })

    it('extracts first depends_on key as defaultDependencyKey', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { depends_on: ['TEST-10', 'TEST-11'] } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ defaultDependencyKey: 'TEST-10' })
      )
    })

    it('normalises dependency keys to uppercase', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { depends_on: ['test-99'] } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ defaultDependencyKey: 'TEST-99' })
      )
    })

    it('uses parent_spec_name as fallback for defaultDependencyKey', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      const item = makeBacklogItem({ payload: { parent_spec_name: 'my-spec' } })

      await act(() => result.current.queueFromBacklog(item))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ defaultDependencyKey: 'MY-SPEC' })
      )
    })

    it('always sets workflow to codex', async () => {
      const openWorkspacePicker = vi.fn()

      const { result } = renderHook(() =>
        usePipelineBoardInteractions({
          currentTasks: [],
          allTasks: [],
          reorderCurrent: vi.fn(),
          openWorkspacePicker,
        })
      )

      await act(() => result.current.queueFromBacklog(makeBacklogItem()))

      expect(openWorkspacePicker).toHaveBeenCalledWith(
        expect.objectContaining({ workflow: 'codex' })
      )
    })
  })
})
