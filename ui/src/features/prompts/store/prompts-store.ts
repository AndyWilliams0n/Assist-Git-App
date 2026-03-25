import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { SpecTab } from '@/features/prompts/types'

type PromptsState = {
  currentSpecId: string | null
  activeTab: SpecTab
  pollingSpecNames: string[]
}

type PromptsActions = {
  setCurrentSpecId: (nextSpecId: string | null) => void
  setActiveTab: (activeTab: SpecTab) => void
  clearCurrentSpecId: () => void
  addPollingSpec: (specName: string) => void
  removePollingSpec: (specName: string) => void
}

export const usePromptsStore = create<PromptsState & PromptsActions>()(
  persist(
    (set) => ({
      currentSpecId: null,
      activeTab: 'requirements.md',
      pollingSpecNames: [],
      setCurrentSpecId: (nextSpecId) =>
        set({ currentSpecId: nextSpecId && nextSpecId.trim() ? nextSpecId.trim() : null }),
      setActiveTab: (activeTab) => set({ activeTab }),
      clearCurrentSpecId: () => set({ currentSpecId: null }),
      addPollingSpec: (specName) =>
        set((state) => ({
          pollingSpecNames: state.pollingSpecNames.includes(specName)
            ? state.pollingSpecNames
            : [...state.pollingSpecNames, specName],
        })),
      removePollingSpec: (specName) =>
        set((state) => ({
          pollingSpecNames: state.pollingSpecNames.filter((n) => n !== specName),
        })),
    }),
    { name: 'prompts-storage' }
  )
)
