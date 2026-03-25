import { create } from "zustand"
import { persist } from "zustand/middleware"

export type AgentsPipelineTab = "agents" | "settings"

type AgentsPipelineStore = {
  activeTab: AgentsPipelineTab
  setActiveTab: (activeTab: AgentsPipelineTab) => void
}

export const useAgentsPipelineStore = create<AgentsPipelineStore>()(
  persist(
    (set) => ({
      activeTab: "agents",
      setActiveTab: (activeTab) => set({ activeTab }),
    }),
    {
      name: "agents-pipeline-storage",
      partialize: (state) => ({
        activeTab: state.activeTab,
      }),
    }
  )
)
