export type SpecTab = "requirements.md" | "design.md" | "tasks.md"

export type SpecContentState = Record<SpecTab, string>

export type PromptHistoryEntry = {
  id: string
  timestamp: string
  message: string
  type: "user" | "system"
}

export type SaveState = {
  status: "idle" | "success" | "error"
  message: string
}

export type SpecBundleSummary = {
  spec_name: string
  updated_at: string
  files: string[]
  has_full_bundle: boolean
}

export type SpecBundlePayload = {
  spec_name: string
  requirements: string
  design: string
  tasks: string
  history: PromptHistoryEntry[]
  updated_at: string
}

export type FileTreeSnapshotNode = {
  name: string
  path: string
  type: "dir" | "file"
  children?: FileTreeSnapshotNode[]
}

export type FileTreeSnapshot = {
  root: FileTreeSnapshotNode | null
  expandedPaths: string[]
}
