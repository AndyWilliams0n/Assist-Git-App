import { create } from "zustand"

import type { PipelineState, PipelineSyncMode } from "@/features/pipelines/types"

const applyPendingOrder = (state: PipelineState, pendingOrder: string[]): PipelineState => {
  if (!state.columns?.current?.length) return state

  const orderMap = new Map(pendingOrder.map((id, i) => [id, i]))
  const sorted = [...state.columns.current].sort((a, b) => {
    const aIdx = orderMap.get(a.id) ?? Number.MAX_SAFE_INTEGER
    const bIdx = orderMap.get(b.id) ?? Number.MAX_SAFE_INTEGER

    return aIdx - bIdx
  })

  return { ...state, columns: { ...state.columns, current: sorted } }
}

type PipelinesStoreState = {
  state: PipelineState | null
  isLoading: boolean
  isMutating: boolean
  error: string | null
  mode: PipelineSyncMode
  pendingCurrentOrder: string[] | null
  setPipelineState: (state: PipelineState | null) => void
  setIsLoading: (isLoading: boolean) => void
  setIsMutating: (isMutating: boolean) => void
  setError: (error: string | null) => void
  setMode: (mode: PipelineSyncMode) => void
  applyPipelineState: (state: PipelineState) => void
  applyOptimisticReorder: (orderedTaskIds: string[]) => void
  clearOptimisticReorder: () => void
}

export const usePipelinesStore = create<PipelinesStoreState>()((set) => ({
  state: null,
  isLoading: true,
  isMutating: false,
  error: null,
  mode: "polling",
  pendingCurrentOrder: null,

  setPipelineState: (state) => set({ state }),

  setIsLoading: (isLoading) => set({ isLoading }),

  setIsMutating: (isMutating) => set({ isMutating }),

  setError: (error) => set({ error }),

  setMode: (mode) => set({ mode }),

  applyPipelineState: (incomingState) =>
    set((prev) => {
      const nextState =
        prev.pendingCurrentOrder && prev.pendingCurrentOrder.length > 0
          ? applyPendingOrder(incomingState, prev.pendingCurrentOrder)
          : incomingState

      return { state: nextState, error: null, isLoading: false }
    }),

  applyOptimisticReorder: (orderedTaskIds) =>
    set((prev) => {
      const currentState = prev.state

      if (!currentState?.columns?.current) {
        return { pendingCurrentOrder: orderedTaskIds }
      }

      const orderMap = new Map(orderedTaskIds.map((id, i) => [id, i]))
      const sorted = [...currentState.columns.current].sort((a, b) => {
        const aIdx = orderMap.get(a.id) ?? Number.MAX_SAFE_INTEGER
        const bIdx = orderMap.get(b.id) ?? Number.MAX_SAFE_INTEGER

        return aIdx - bIdx
      })

      return {
        pendingCurrentOrder: orderedTaskIds,
        state: { ...currentState, columns: { ...currentState.columns, current: sorted } },
      }
    }),

  clearOptimisticReorder: () => set({ pendingCurrentOrder: null }),
}))
