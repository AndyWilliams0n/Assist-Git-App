import { useEffect, useRef } from "react"
import FileFolderDialog from "@/shared/components/file-folder-dialog"
import useFileFolderDialog from "@/shared/hooks/useFileFolderDialog"
import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings"
import type { FileSystemEntry } from "@/shared/types/file-browser"

interface GlobalWorkspacePickerProps {
  open: boolean
  onClose: () => void
}

export function GlobalWorkspacePicker({ open, onClose }: GlobalWorkspacePickerProps) {
  const workspacePath = useDashboardSettingsStore((s) => s.primaryWorkspacePath)
  const setWorkspacePath = useDashboardSettingsStore((s) => s.setPrimaryWorkspacePath)

  const {
    columns,
    locations,
    selectedPath,
    activeDirectoryPath,
    selectedByColumnPath,
    showHidden,
    isLoading,
    isCreatingFolder,
    isRenamingEntry,
    error,
    openAtPath,
    setShowHidden,
    selectLocation,
    selectEntry,
    createFolder,
    renameEntry,
    deleteEntry,
  } = useFileFolderDialog({ mode: "folder-only" })

  // When the picker opens, navigate the browser to the current workspace (or home)
  const workspacePathRef = useRef(workspacePath)
  workspacePathRef.current = workspacePath

  useEffect(() => {
    if (open) {
      void openAtPath(workspacePathRef.current || "")
    }
  }, [open, openAtPath])

  const handleConfirm = () => {
    const path = selectedPath.trim()
    if (path) {
      setWorkspacePath(path)
    }
    onClose()
  }

  return (
    <FileFolderDialog
      open={open}
      title="Change Workspace"
      mode="folder-only"
      locations={locations}
      columns={columns}
      selectedByColumnPath={selectedByColumnPath}
      selectedPath={selectedPath}
      activeDirectoryPath={activeDirectoryPath}
      showHidden={showHidden}
      isLoading={isLoading}
      isCreatingFolder={isCreatingFolder}
      isRenamingEntry={isRenamingEntry}
      error={error}
      onShowHiddenChange={(value: boolean) => void setShowHidden(value)}
      onSelectLocation={(path: string) => void selectLocation(path)}
      onSelectEntry={(columnIndex: number, entry: FileSystemEntry) =>
        void selectEntry(columnIndex, entry)
      }
      onCreateFolder={createFolder}
      onRenameEntry={renameEntry}
      onDeleteEntry={deleteEntry}
      onClose={onClose}
      onConfirm={handleConfirm}
    />
  )
}
