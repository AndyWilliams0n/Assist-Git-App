import { create } from "zustand"
import { persist } from "zustand/middleware"
import type {
  GitActionConfig,
  GitActionType,
  GitWorkflowConfig,
  GitWorkflowConfigs,
  GitWorkflowKey,
  GitWorkflowSettings,
  PipelinePhaseConfig,
} from "../types"

export type GitPageTab = "repository" | "branches" | "chat-actions" | "automation-actions" | "spec-automation-actions" | "settings"
export type GitActionSlot = "primary" | "secondary" | "subtask-primary" | "subtask-secondary"

// Default git action config
const defaultAction = (): GitActionConfig => ({
  type: "none" as GitActionType,
  enabled: false,
  branchNamePattern: "feature/{description}",
  reuseExistingBranch: true,
  commitMessagePattern: "feat: {description}",
  targetBranch: "",
  prTitlePattern: "feat: {description}",
  prBodyTemplate: "## Summary\n\n{description}\n\n## Changes\n\n- ",
  draft: false,
  pushBeforePr: true,
  customCommand: "",
})

// Default pipeline phases matching the code-build workflow
const defaultPhases = (workflowKey: GitWorkflowKey): PipelinePhaseConfig[] => {
  if (workflowKey === "chat") {
    return [
      {
        id: "initial",
        label: "Pre-Intent / Chat Start",
        description: "Before the Orchestrator Agent starts a chat-to-code run",
        agentName: "Orchestrator Agent",
        icon: "play",
        gitAction: defaultAction(),
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "planning",
        label: "Pre-Code Builder",
        description: "After planning/SDD generation and before Code Builder Codex",
        agentName: ["Planner Agent", "Orchestrator Agent"],
        icon: "clipboard",
        gitAction: { ...defaultAction(), type: "create_branch", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "build",
        label: "Pre-Code Review",
        description: "After Code Builder output and before Code Review Agent",
        agentName: "Code Builder Codex",
        icon: "code",
        gitAction: { ...defaultAction(), type: "commit", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "review",
        label: "Pre-Complete Result",
        description: "After review and before the final Orchestrator response",
        agentName: "Code Review Agent",
        icon: "search",
        gitAction: { ...defaultAction(), type: "create_pr", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "complete",
        label: "Complete",
        description: "Final terminal state for chat execution",
        agentName: "Orchestrator Agent",
        icon: "check",
        gitAction: defaultAction(),
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
    ]
  }

  if (workflowKey === "pipeline_spec") {
    return [
      {
        id: "initial",
        label: "Pre-Intent / Pipeline SPEC Start",
        description: "Before the Pipeline Agent starts a SPEC task run",
        agentName: ["Orchestrator Agent", "Pipeline Agent"],
        icon: "play",
        gitAction: defaultAction(),
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "planning",
        label: "Pre-Code Builder",
        description: "Before Code Builder Codex runs for SPEC task execution",
        agentName: ["Planner Agent", "Pipeline Agent"],
        icon: "clipboard",
        gitAction: { ...defaultAction(), type: "create_branch", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "build",
        label: "Pre-Code Review",
        description: "After Code Builder and before Code Review (or review checkpoint)",
        agentName: "Code Builder Codex",
        icon: "code",
        gitAction: { ...defaultAction(), type: "commit", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "review",
        label: "Pre-Complete Result",
        description: "After review and before Orchestrator/Pipeline completion result",
        agentName: "Code Review Agent",
        icon: "search",
        gitAction: { ...defaultAction(), type: "create_pr", enabled: false },
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
      {
        id: "complete",
        label: "Complete",
        description: "Final response / pipeline completion terminal stage",
        agentName: ["Orchestrator Agent", "Pipeline Agent"],
        icon: "check",
        gitAction: defaultAction(),
        secondaryGitAction: defaultAction(),
        subtaskGitAction: defaultAction(),
        subtaskSecondaryGitAction: defaultAction(),
      },
    ]
  }

  return [
    {
      id: "initial",
      label: "Pre-Intent / Pipeline Start",
      description: "Before the Pipeline Agent starts the automation run",
      agentName: ["Orchestrator Agent", "Pipeline Agent"],
      icon: "play",
      gitAction: defaultAction(),
      secondaryGitAction: defaultAction(),
      subtaskGitAction: defaultAction(),
      subtaskSecondaryGitAction: defaultAction(),
    },
    {
      id: "planning",
      label: "Pre-Code Builder",
      description: "After planning/SDD bundle and before Code Builder Codex",
      agentName: ["Planner Agent", "Pipeline Agent"],
      icon: "clipboard",
      gitAction: { ...defaultAction(), type: "create_branch", enabled: false },
      secondaryGitAction: defaultAction(),
      subtaskGitAction: defaultAction(),
      subtaskSecondaryGitAction: defaultAction(),
    },
    {
      id: "build",
      label: "Pre-Code Review",
      description: "After Code Builder and before Code Review (or review checkpoint)",
      agentName: "Code Builder Codex",
      icon: "code",
      gitAction: { ...defaultAction(), type: "commit", enabled: false },
      secondaryGitAction: defaultAction(),
      subtaskGitAction: defaultAction(),
      subtaskSecondaryGitAction: defaultAction(),
    },
    {
      id: "review",
      label: "Pre-Complete Result",
      description: "After review and before Orchestrator/Pipeline completion result",
      agentName: "Code Review Agent",
      icon: "search",
      gitAction: { ...defaultAction(), type: "create_pr", enabled: false },
      secondaryGitAction: defaultAction(),
      subtaskGitAction: defaultAction(),
      subtaskSecondaryGitAction: defaultAction(),
    },
    {
      id: "complete",
      label: "Complete",
      description: "Final response / pipeline completion terminal stage",
      agentName: ["Orchestrator Agent", "Pipeline Agent"],
      icon: "check",
      gitAction: defaultAction(),
      secondaryGitAction: defaultAction(),
      subtaskGitAction: defaultAction(),
      subtaskSecondaryGitAction: defaultAction(),
    },
  ]
}

const defaultSettings = (): GitWorkflowSettings => ({
  defaultBranch: "main",
  branchNamePattern: "feature/{description}",
  commitMessagePattern: "feat: {description}",
  prTitlePattern: "feat: {description}",
  prBodyTemplate: "## Summary\n\n{description}\n\n## Changes\n\n- \n\n## Test Plan\n\n- ",
  platform: "auto",
  autoDetect: true,
  autoPushOnCommit: false,
})

const defaultWorkflowConfig = (workflowKey: GitWorkflowKey): GitWorkflowConfig => ({
  phases: defaultPhases(workflowKey),
  settings: defaultSettings(),
})

const defaultWorkflows = (): GitWorkflowConfigs => ({
  chat: defaultWorkflowConfig("chat"),
  pipeline: defaultWorkflowConfig("pipeline"),
  pipeline_spec: defaultWorkflowConfig("pipeline_spec"),
})

interface GitStore {
  workflows: GitWorkflowConfigs
  activeTab: GitPageTab

  updatePhaseAction: (
    workflowKey: GitWorkflowKey,
    phaseId: string,
    slot: GitActionSlot,
    action: Partial<GitActionConfig>
  ) => void
  updateSettings: (workflowKey: GitWorkflowKey, settings: Partial<GitWorkflowSettings>) => void
  setPhases: (workflowKey: GitWorkflowKey, phases: PipelinePhaseConfig[]) => void
  setSettings: (workflowKey: GitWorkflowKey, settings: GitWorkflowSettings) => void
  replaceConfig: (config: GitWorkflowConfigs) => void
  resetPhases: (workflowKey: GitWorkflowKey) => void
  resetSettings: (workflowKey: GitWorkflowKey) => void
  setActiveTab: (activeTab: GitPageTab) => void
}

export const useGitStore = create<GitStore>()(
  persist(
    (set) => ({
      workflows: defaultWorkflows(),
      activeTab: "branches",

      updatePhaseAction: (workflowKey, phaseId, slot, actionUpdates) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              phases: state.workflows[workflowKey].phases.map((phase) => {
                if (phase.id !== phaseId) return phase

                if (slot === "subtask-secondary") {
                  return { ...phase, subtaskSecondaryGitAction: { ...phase.subtaskSecondaryGitAction, ...actionUpdates } }
                }

                if (slot === "subtask-primary") {
                  return { ...phase, subtaskGitAction: { ...phase.subtaskGitAction, ...actionUpdates } }
                }

                if (slot === "secondary") {
                  return { ...phase, secondaryGitAction: { ...phase.secondaryGitAction, ...actionUpdates } }
                }

                return { ...phase, gitAction: { ...phase.gitAction, ...actionUpdates } }
              }),
            },
          },
        })),

      updateSettings: (workflowKey, settingsUpdates) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              settings: { ...state.workflows[workflowKey].settings, ...settingsUpdates },
            },
          },
        })),

      setPhases: (workflowKey, phases) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              phases,
            },
          },
        })),

      setSettings: (workflowKey, settings) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              settings,
            },
          },
        })),

      replaceConfig: (config) => {
        const next: GitWorkflowConfigs = {
          chat: defaultWorkflowConfig("chat"),
          pipeline: defaultWorkflowConfig("pipeline"),
          pipeline_spec: defaultWorkflowConfig("pipeline_spec"),
        }

        for (const workflowKey of ["chat", "pipeline", "pipeline_spec"] as const) {
          const incoming = config[workflowKey]
          if (!incoming) continue

          const fallback = defaultWorkflowConfig(workflowKey)
          const incomingPhases = Array.isArray(incoming.phases) ? incoming.phases : []
          const fallbackById = new Map(fallback.phases.map((phase) => [phase.id, phase] as const))

          const phases = fallback.phases.map((fallbackPhase) => {
            const matched = incomingPhases.find((phase) => phase.id === fallbackPhase.id)
            if (!matched) return fallbackPhase

            return {
              ...fallbackPhase,
              ...matched,
              gitAction: { ...fallbackPhase.gitAction, ...(matched.gitAction || {}) },
              secondaryGitAction: {
                ...fallbackPhase.secondaryGitAction,
                ...(matched.secondaryGitAction || {}),
              },
              subtaskGitAction: {
                ...fallbackPhase.subtaskGitAction,
                ...(matched.subtaskGitAction || {}),
              },
              subtaskSecondaryGitAction: {
                ...fallbackPhase.subtaskSecondaryGitAction,
                ...(matched.subtaskSecondaryGitAction || {}),
              },
            }
          })

          for (const extraPhase of incomingPhases) {
            if (!extraPhase || fallbackById.has(extraPhase.id)) continue
            phases.push({
              ...extraPhase,
              gitAction: { ...defaultAction(), ...(extraPhase.gitAction || {}) },
              secondaryGitAction: {
                ...defaultAction(),
                ...(extraPhase.secondaryGitAction || {}),
              },
              subtaskGitAction: {
                ...defaultAction(),
                ...(extraPhase.subtaskGitAction || {}),
              },
              subtaskSecondaryGitAction: {
                ...defaultAction(),
                ...(extraPhase.subtaskSecondaryGitAction || {}),
              },
            })
          }

          next[workflowKey] = {
            phases,
            settings: { ...fallback.settings, ...(incoming.settings || {}) },
          }
        }

        set({ workflows: next })
      },

      resetPhases: (workflowKey) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              phases: defaultPhases(workflowKey),
            },
          },
        })),

      resetSettings: (workflowKey) =>
        set((state) => ({
          workflows: {
            ...state.workflows,
            [workflowKey]: {
              ...state.workflows[workflowKey],
              settings: defaultSettings(),
            },
          },
        })),
      setActiveTab: (activeTab) => set({ activeTab }),
    }),
    {
      name: "git-workflow-storage-v4",
      partialize: (state) => ({
        workflows: state.workflows,
        activeTab: state.activeTab,
      }),
    }
  )
)
