import { describe, it, expect, vi } from 'vitest'

import { COLUMN_DEFS, canDropInColumn, parseDragPayload, statusTone } from '@/features/pipelines/components/kanban/kanban-utils'
import type { PipelineKanbanItem } from '@/features/pipelines/components/kanban/types'

const makeBacklogItem = (tracked: boolean): PipelineKanbanItem => ({
  id: 'item-1',
  name: 'TEST-1',
  column: 'backlog',
  kind: 'backlog',
  tracked,
  status: 'backlog',
})

const makeTaskItem = (status: 'current' | 'running' | 'complete'): PipelineKanbanItem => ({
  id: 'task-1',
  name: 'TEST-1',
  column: status,
  kind: 'task',
  tracked: true,
  status,
})

describe('COLUMN_DEFS', () => {
  it('defines four columns in order: backlog, current, running, complete', () => {
    const ids = COLUMN_DEFS.map((col) => col.id)
    expect(ids).toEqual(['backlog', 'current', 'running', 'complete'])
  })

  it('assigns correct display names', () => {
    expect(COLUMN_DEFS[0].name).toBe('Backlog')
    expect(COLUMN_DEFS[1].name).toBe('Task Queue')
    expect(COLUMN_DEFS[2].name).toBe('Running')
    expect(COLUMN_DEFS[3].name).toBe('Complete')
  })
})

describe('statusTone', () => {
  it('returns success outline for running', () => {
    expect(statusTone('running')).toEqual({ color: 'success', variant: 'outline' })
  })

  it('returns success filled for complete', () => {
    expect(statusTone('complete')).toEqual({ color: 'success', variant: 'filled' })
  })

  it('returns info outline for current', () => {
    expect(statusTone('current')).toEqual({ color: 'info', variant: 'outline' })
  })

  it('returns grey outline for backlog', () => {
    expect(statusTone('backlog')).toEqual({ color: 'grey', variant: 'outline' })
  })
})

describe('canDropInColumn', () => {
  describe('backlog items', () => {
    it('allows untracked backlog item to drop into current column', () => {
      expect(canDropInColumn(makeBacklogItem(false), 'current')).toBe(true)
    })

    it('prevents tracked backlog item from dropping into current column', () => {
      expect(canDropInColumn(makeBacklogItem(true), 'current')).toBe(false)
    })

    it('prevents backlog item from dropping into backlog column', () => {
      expect(canDropInColumn(makeBacklogItem(false), 'backlog')).toBe(false)
    })

    it('prevents backlog item from dropping into running column', () => {
      expect(canDropInColumn(makeBacklogItem(false), 'running')).toBe(false)
    })

    it('prevents backlog item from dropping into complete column', () => {
      expect(canDropInColumn(makeBacklogItem(false), 'complete')).toBe(false)
    })
  })

  describe('current task items', () => {
    it('allows current task to drop into current column (reorder)', () => {
      expect(canDropInColumn(makeTaskItem('current'), 'current')).toBe(true)
    })

    it('allows current task to drop back into backlog column', () => {
      expect(canDropInColumn(makeTaskItem('current'), 'backlog')).toBe(true)
    })

    it('prevents current task from dropping into running column', () => {
      expect(canDropInColumn(makeTaskItem('current'), 'running')).toBe(false)
    })

    it('prevents current task from dropping into complete column', () => {
      expect(canDropInColumn(makeTaskItem('current'), 'complete')).toBe(false)
    })
  })

  describe('running and complete task items', () => {
    it('prevents running task from dropping into any column', () => {
      const item = makeTaskItem('running')
      expect(canDropInColumn(item, 'current')).toBe(false)
      expect(canDropInColumn(item, 'running')).toBe(false)
      expect(canDropInColumn(item, 'complete')).toBe(false)
      expect(canDropInColumn(item, 'backlog')).toBe(false)
    })

    it('prevents complete task from dropping into any column', () => {
      const item = makeTaskItem('complete')
      expect(canDropInColumn(item, 'current')).toBe(false)
      expect(canDropInColumn(item, 'running')).toBe(false)
      expect(canDropInColumn(item, 'complete')).toBe(false)
      expect(canDropInColumn(item, 'backlog')).toBe(false)
    })
  })
})

describe('parseDragPayload', () => {
  const makeDragEvent = (data: string) => {
    return {
      dataTransfer: {
        getData: vi.fn().mockReturnValue(data),
      },
    } as unknown as DragEvent<HTMLElement>
  }

  it('parses a valid drag payload with itemId', () => {
    const event = makeDragEvent(JSON.stringify({ itemId: 'task-1' }))
    const result = parseDragPayload(event)
    expect(result).toEqual({ itemId: 'task-1' })
  })

  it('returns null when dataTransfer has no data', () => {
    const event = makeDragEvent('')
    expect(parseDragPayload(event)).toBeNull()
  })

  it('returns null when payload has no itemId', () => {
    const event = makeDragEvent(JSON.stringify({ other: 'value' }))
    expect(parseDragPayload(event)).toBeNull()
  })

  it('returns null when JSON is malformed', () => {
    const event = makeDragEvent('not-valid-json{{{')
    expect(parseDragPayload(event)).toBeNull()
  })
})
