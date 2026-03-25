import * as React from "react"
import { FolderOpen } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/components/ui/dialog"
import { Input } from "@/shared/components/ui/input"
import { Label } from "@/shared/components/ui/label"
import { Textarea } from "@/shared/components/ui/textarea"
import FileFolderDialog from "@/shared/components/file-folder-dialog"
import useFileFolderDialog from "@/shared/hooks/useFileFolderDialog"
import type { FileSystemEntry } from "@/shared/types/file-browser"

interface AddWorkspaceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (name: string, path: string, description: string) => Promise<void>
}

export function AddWorkspaceDialog({ open, onOpenChange, onSubmit }: AddWorkspaceDialogProps) {
  const [name, setName] = React.useState("")
  const [path, setPath] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [showFileBrowser, setShowFileBrowser] = React.useState(false)

  const {
    columns,
    locations,
    selectedPath: browserSelectedPath,
    activeDirectoryPath,
    selectedByColumnPath,
    showHidden,
    isLoading: browserLoading,
    isCreatingFolder,
    isRenamingEntry,
    error: browserError,
    openAtPath,
    setShowHidden,
    selectLocation,
    selectEntry,
    createFolder,
    renameEntry,
    deleteEntry,
  } = useFileFolderDialog({ mode: "folder-only" })

  const handleBrowseConfirm = () => {
    if (browserSelectedPath) {
      setPath(browserSelectedPath)
    }
    setShowFileBrowser(false)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !path.trim()) {
      setError("Name and path are required")
      return
    }
    setError(null)
    setIsSubmitting(true)
    try {
      await onSubmit(name.trim(), path.trim(), description.trim())
      setName("")
      setPath("")
      setDescription("")
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create workspace")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      {/* modal={false} when file browser is open so react-remove-scroll
          doesn't block pointer events on the FileFolderDialog overlay */}
      <Dialog open={open} onOpenChange={onOpenChange} modal={!showFileBrowser}>
        <DialogContent
          className="sm:max-w-md"
          onInteractOutside={(e) => {
            // Prevent Radix from closing this dialog when the user clicks
            // inside the FileFolderDialog overlay (which renders above us at z-60)
            if (showFileBrowser) e.preventDefault()
          }}
        >
          <DialogHeader>
            <DialogTitle>New Workspace</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                placeholder="My Project"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label>Local Path</Label>
              <div className="flex gap-2">
                <Input
                  placeholder="/Users/you/projects/my-project"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  className="flex-1 font-mono text-xs"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => { void openAtPath(path || ""); setShowFileBrowser(true) }}
                  title="Browse for folder"
                >
                  <FolderOpen className="size-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                The folder on your machine to use as the workspace root.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label>Description (optional)</Label>
              <Textarea
                placeholder="What is this workspace for?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
              />
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Creating..." : "Create Workspace"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <FileFolderDialog
        open={showFileBrowser}
        title="Select Workspace Folder"
        mode="folder-only"
        locations={locations}
        columns={columns}
        selectedByColumnPath={selectedByColumnPath}
        selectedPath={browserSelectedPath}
        activeDirectoryPath={activeDirectoryPath}
        showHidden={showHidden}
        isLoading={browserLoading}
        isCreatingFolder={isCreatingFolder}
        isRenamingEntry={isRenamingEntry}
        error={browserError}
        onShowHiddenChange={(value: boolean) => void setShowHidden(value)}
        onSelectLocation={(p: string) => void selectLocation(p)}
        onSelectEntry={(columnIndex: number, entry: FileSystemEntry) => void selectEntry(columnIndex, entry)}
        onCreateFolder={createFolder}
        onRenameEntry={renameEntry}
        onDeleteEntry={deleteEntry}
        onClose={() => setShowFileBrowser(false)}
        onConfirm={handleBrowseConfirm}
      />
    </>
  )
}
