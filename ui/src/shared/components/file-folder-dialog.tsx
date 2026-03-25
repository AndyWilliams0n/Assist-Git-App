import { useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronRight,
  Columns3,
  Download,
  File,
  Folder,
  FolderPen,
  FolderOpen,
  FolderPlus,
  HardDrive,
  Home,
  Monitor,
  Search,
  SortAsc,
  Trash2,
} from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem } from "@/shared/components/ui/dropdown-menu"
import { Input } from "@/shared/components/ui/input"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import { Switch } from "@/shared/components/ui/switch"
import { cn } from "@/shared/utils/utils.ts"
import type { FileFolderDialogMode, FileSystemColumn, FileSystemEntry } from "@/shared/types/file-browser"

type FileFolderDialogProps = {
  open: boolean
  title?: string
  mode?: FileFolderDialogMode
  locations: Array<{ label: string; path: string }>
  columns: FileSystemColumn[]
  selectedByColumnPath: Record<string, string>
  selectedPath: string
  activeDirectoryPath: string
  isLoading?: boolean
  isCreatingFolder?: boolean
  isRenamingEntry?: boolean
  error: string | null
  showHidden: boolean
  onShowHiddenChange: (value: boolean) => void | Promise<void>
  onSelectLocation: (path: string) => void | Promise<void>
  onSelectEntry: (columnIndex: number, entry: FileSystemEntry) => void | Promise<void>
  onCreateFolder: (parentPath: string, name: string) => Promise<string | null>
  onRenameEntry: (path: string, name: string) => Promise<string | null>
  onDeleteEntry: (path: string) => Promise<boolean>
  onClose: () => void
  onConfirm: () => void
}

const getBaseName = (path: string) => {
  if (!path) return ""
  const segments = path.split("/").filter(Boolean)
  if (segments.length === 0) return "/"
  return segments[segments.length - 1]
}

const locationIcon = (label: string) => {
  if (label === "Home") return Home
  if (label === "Desktop") return Monitor
  if (label === "Downloads") return Download
  if (label === "Root") return HardDrive
  return Folder
}

export default function FileFolderDialog({
  open,
  title,
  mode = "file-and-folder",
  locations,
  columns,
  selectedByColumnPath,
  selectedPath,
  activeDirectoryPath,
  isLoading = false,
  isCreatingFolder = false,
  isRenamingEntry = false,
  error,
  showHidden,
  onShowHiddenChange,
  onSelectLocation,
  onSelectEntry,
  onCreateFolder,
  onRenameEntry,
  onDeleteEntry,
  onClose,
  onConfirm,
}: FileFolderDialogProps) {
  const [createFolderParentPath, setCreateFolderParentPath] = useState<string | null>(null)
  const [createFolderName, setCreateFolderName] = useState("")
  const [createFolderHasError, setCreateFolderHasError] = useState(false)
  const [createFolderShakeKey, setCreateFolderShakeKey] = useState(0)
  const isCommittingCreateFolderRef = useRef(false)
  const isCreateFolderAttemptLockedRef = useRef(false)
  const skipNextCreateFolderBlurRef = useRef(false)
  const [contextMenuOpen, setContextMenuOpen] = useState(false)
  const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 })
  const [contextMenuTarget, setContextMenuTarget] = useState<{
    columnIndex: number
    entry: FileSystemEntry
  } | null>(null)
  const [renameEntryPath, setRenameEntryPath] = useState<string | null>(null)
  const [renameEntryName, setRenameEntryName] = useState("")
  const [renameEntryOriginalName, setRenameEntryOriginalName] = useState("")
  const [renameEntryHasError, setRenameEntryHasError] = useState(false)
  const [renameEntryShakeKey, setRenameEntryShakeKey] = useState(0)
  const isCommittingRenameRef = useRef(false)
  const isRenameAttemptLockedRef = useRef(false)
  const skipNextRenameBlurRef = useRef(false)

  const rightMostColumnPath = columns[columns.length - 1]?.path || activeDirectoryPath
  const selectedName = useMemo(() => getBaseName(selectedPath), [selectedPath])

  const startCreateFolder = () => {
    if (!rightMostColumnPath) return
    setCreateFolderParentPath(rightMostColumnPath)
    setCreateFolderName("")
    setCreateFolderHasError(false)
    setCreateFolderShakeKey(0)
    isCreateFolderAttemptLockedRef.current = false
    skipNextCreateFolderBlurRef.current = false
  }

  const cancelCreateFolder = () => {
    setCreateFolderParentPath(null)
    setCreateFolderName("")
    setCreateFolderHasError(false)
    setCreateFolderShakeKey(0)
    isCreateFolderAttemptLockedRef.current = false
    skipNextCreateFolderBlurRef.current = false
  }

  const closeContextMenu = () => {
    setContextMenuOpen(false)
    setContextMenuTarget(null)
  }

  const contextMenuTargetEntry = contextMenuTarget?.entry || null
  const contextMenuEntryIsDir = contextMenuTargetEntry?.type === "dir"
  const contextMenuNextColumn = contextMenuTarget
    ? columns[contextMenuTarget.columnIndex + 1]
    : undefined
  const canDeleteContextMenuFolder = Boolean(
    contextMenuTargetEntry
    && contextMenuEntryIsDir
    && contextMenuNextColumn
    && contextMenuNextColumn.path === contextMenuTargetEntry.path
    && contextMenuNextColumn.entries.length === 0
  )

  const startRenameEntry = (entry: FileSystemEntry) => {
    cancelCreateFolder()
    setRenameEntryPath(entry.path)
    setRenameEntryName(entry.name)
    setRenameEntryOriginalName(entry.name)
    setRenameEntryHasError(false)
    setRenameEntryShakeKey(0)
    isRenameAttemptLockedRef.current = false
    skipNextRenameBlurRef.current = false
    closeContextMenu()
  }

  const cancelRenameEntry = () => {
    setRenameEntryPath(null)
    setRenameEntryName("")
    setRenameEntryOriginalName("")
    setRenameEntryHasError(false)
    setRenameEntryShakeKey(0)
    isRenameAttemptLockedRef.current = false
    skipNextRenameBlurRef.current = false
  }

  useEffect(() => {
    if (open) return
    setCreateFolderParentPath(null)
    setCreateFolderName("")
    setCreateFolderHasError(false)
    setCreateFolderShakeKey(0)
    isCreateFolderAttemptLockedRef.current = false
    skipNextCreateFolderBlurRef.current = false
    setContextMenuOpen(false)
    setContextMenuTarget(null)
    setRenameEntryPath(null)
    setRenameEntryName("")
    setRenameEntryOriginalName("")
    setRenameEntryHasError(false)
    setRenameEntryShakeKey(0)
    isRenameAttemptLockedRef.current = false
    skipNextRenameBlurRef.current = false
  }, [open])

  const commitCreateFolder = async () => {
    if (
      !createFolderParentPath
      || isCommittingCreateFolderRef.current
      || isCreateFolderAttemptLockedRef.current
    ) return
    isCommittingCreateFolderRef.current = true
    isCreateFolderAttemptLockedRef.current = true
    try {
      const name = createFolderName.trim()
      if (!name) {
        cancelCreateFolder()
        return
      }

      const createdPath = await onCreateFolder(createFolderParentPath, name)
      if (createdPath) {
        cancelCreateFolder()
      } else {
        setCreateFolderHasError(true)
        setCreateFolderShakeKey((value) => value + 1)
        isCreateFolderAttemptLockedRef.current = false
      }
    } catch {
      setCreateFolderHasError(true)
      setCreateFolderShakeKey((value) => value + 1)
      isCreateFolderAttemptLockedRef.current = false
    } finally {
      isCommittingCreateFolderRef.current = false
    }
  }

  const commitRenameEntry = async () => {
    if (
      !renameEntryPath
      || isCommittingRenameRef.current
      || isRenameAttemptLockedRef.current
    ) return
    isCommittingRenameRef.current = true
    isRenameAttemptLockedRef.current = true
    try {
      const name = renameEntryName.trim()
      if (!name) {
        cancelRenameEntry()
        return
      }

      if (name === renameEntryOriginalName.trim()) {
        cancelRenameEntry()
        return
      }

      const renamedPath = await onRenameEntry(renameEntryPath, name)
      if (renamedPath) {
        cancelRenameEntry()
      } else {
        setRenameEntryHasError(true)
        setRenameEntryShakeKey((value) => value + 1)
        isRenameAttemptLockedRef.current = false
      }
    } catch {
      setRenameEntryHasError(true)
      setRenameEntryShakeKey((value) => value + 1)
      isRenameAttemptLockedRef.current = false
    } finally {
      isCommittingRenameRef.current = false
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm p-3 md:p-5">
      <div className="bg-background text-foreground flex h-[92vh] w-full max-w-[96rem] flex-col overflow-hidden rounded-xl border shadow-xl">
        <header className="bg-card flex shrink-0 items-center justify-between border-b px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <h2 className="text-sm font-semibold md:text-base">
            {title || (mode === "folder-only" ? "Select Folder" : "Select File")}
          </h2>
          <Button variant="ghost" size="icon-sm" disabled aria-label="Search">
            <Search className="size-4" />
          </Button>
        </header>

        <div className="bg-card flex shrink-0 items-center gap-2 border-b px-4 py-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={startCreateFolder}
            disabled={!rightMostColumnPath || isCreatingFolder}
          >
            <FolderPlus className="size-4" />
            New Folder
          </Button>
          <div className="bg-secondary flex items-center gap-2 rounded-md px-3 py-1.5">
            <span className="text-xs font-medium">Hidden</span>
            <Switch checked={showHidden} onCheckedChange={(next) => void onShowHiddenChange(Boolean(next))} />
          </div>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" disabled aria-label="Sort">
              <SortAsc className="size-4" />
            </Button>
            <Button variant="ghost" size="icon-sm" disabled aria-label="Column view">
              <Columns3 className="size-4" />
            </Button>
          </div>
        </div>

        <main className="bg-muted/35 flex-1 overflow-x-auto overflow-y-hidden">
          <div className="flex h-full min-w-max">
            <section className="bg-card h-full w-64 shrink-0 border-r">
              <div className="text-muted-foreground px-4 py-3 text-xs font-semibold tracking-wide uppercase">
                Locations
              </div>
              <ScrollArea className="h-[calc(100%-3rem)] px-2 pb-2">
                <div className="space-y-1">
                  {locations.map((location) => {
                    const LocationIcon = locationIcon(location.label)

                    return (
                      <button
                        key={location.path}
                        type="button"
                        onClick={() => void onSelectLocation(location.path)}
                        className="hover:bg-accent flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors"
                      >
                        <span className="flex items-center gap-3 overflow-hidden">
                          <LocationIcon className="size-4 shrink-0" />
                          <span className="truncate text-sm font-medium">{location.label}</span>
                        </span>
                        <ChevronRight className="size-4 shrink-0 opacity-70" />
                      </button>
                    )
                  })}
                </div>
              </ScrollArea>
            </section>

            {columns.map((column, columnIndex) => (
              <section
                key={column.path}
                className="bg-card h-full w-72 max-w-72 shrink-0 overflow-hidden border-r shadow-[4px_0_20px_-14px_hsl(var(--foreground)/0.35)]"
              >
                <div className="bg-card/95 flex items-center justify-between border-b px-4 py-3 backdrop-blur">
                  <span
                    className="text-muted-foreground min-w-0 flex-1 truncate text-xs font-semibold"
                    title={column.name}
                  >
                    {column.name}
                  </span>
                  <span className="text-muted-foreground ml-2 shrink-0 text-xs">{column.entries.length} items</span>
                </div>

                <ScrollArea className="h-[calc(100%-3rem)] p-2">
                  <div className="w-full min-w-0 space-y-1">
                    {createFolderParentPath === column.path ? (
                      <div
                        key={`new-folder-input-${createFolderShakeKey}`}
                        className={cn(
                          "rounded-lg px-2 py-1",
                          createFolderHasError
                            ? "bg-rose-100/70 file-folder-error-shake"
                            : "bg-muted/35"
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <FolderOpen className={cn("size-4 shrink-0", createFolderHasError ? "text-rose-600" : "text-primary")} />
                          <Input
                            value={createFolderName}
                            onChange={(event) => {
                              setCreateFolderName(event.target.value)
                              isCreateFolderAttemptLockedRef.current = false
                              if (createFolderHasError) {
                                setCreateFolderHasError(false)
                              }
                            }}
                            onBlur={() => {
                              if (skipNextCreateFolderBlurRef.current) {
                                skipNextCreateFolderBlurRef.current = false
                                return
                              }
                              void commitCreateFolder()
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault()
                                skipNextCreateFolderBlurRef.current = true
                                void commitCreateFolder()
                                return
                              }
                              if (event.key === "Escape") {
                                event.preventDefault()
                                cancelCreateFolder()
                              }
                            }}
                            autoFocus
                            className="h-7 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 focus-visible:outline-none"
                            aria-label="New folder name"
                          />
                        </div>
                      </div>
                    ) : null}

                    {column.entries.map((entry) => {
                      const isSelected = selectedByColumnPath[column.path] === entry.path
                      const isDirectory = entry.type === "dir"
                      const iconClass = isDirectory ? "text-primary" : "text-muted-foreground"
                      const isRenaming = renameEntryPath === entry.path

                      return (
                        <div key={`${column.path}-${entry.path}`} className="w-full max-w-full overflow-hidden">
                          {isRenaming ? (
                            <div
                              key={`rename-entry-input-${renameEntryShakeKey}`}
                              className={cn(
                                "rounded-lg px-2 py-1",
                                renameEntryHasError
                                  ? "bg-rose-100/70 file-folder-error-shake"
                                  : "bg-muted/35"
                              )}
                            >
                              <div className="flex items-center gap-2">
                                {isDirectory ? (
                                  <FolderOpen className="text-primary size-4 shrink-0" />
                                ) : (
                                  <File className="text-primary size-4 shrink-0" />
                                )}
                                <Input
                                  value={renameEntryName}
                                  onChange={(event) => {
                                    setRenameEntryName(event.target.value)
                                    isRenameAttemptLockedRef.current = false
                                    if (renameEntryHasError) {
                                      setRenameEntryHasError(false)
                                    }
                                  }}
                                  onBlur={() => {
                                    if (skipNextRenameBlurRef.current) {
                                      skipNextRenameBlurRef.current = false
                                      return
                                    }
                                    void commitRenameEntry()
                                  }}
                                  onKeyDown={(event) => {
                                    if (event.key === "Enter") {
                                      event.preventDefault()
                                      skipNextRenameBlurRef.current = true
                                      void commitRenameEntry()
                                      return
                                    }
                                    if (event.key === "Escape") {
                                      event.preventDefault()
                                      cancelRenameEntry()
                                    }
                                  }}
                                  autoFocus
                                  className="h-7 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 focus-visible:outline-none"
                                  aria-label={`Rename ${isDirectory ? "folder" : "file"} name`}
                                />
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => void onSelectEntry(columnIndex, entry)}
                              onContextMenu={(event) => {
                                event.preventDefault()
                                void (async () => {
                                  await onSelectEntry(columnIndex, entry)
                                  setContextMenuPosition({ x: event.clientX, y: event.clientY })
                                  setContextMenuTarget({ columnIndex, entry })
                                  setContextMenuOpen(true)
                                })()
                              }}
                              className={cn(
                                "hover:bg-accent flex w-full min-w-0 max-w-full items-center justify-between overflow-hidden rounded-lg px-3 py-2 text-left transition-colors",
                                isSelected && "bg-primary text-primary-foreground hover:bg-primary/90"
                              )}
                            >
                              <span className="flex w-0 min-w-0 flex-1 items-center gap-3 overflow-hidden">
                                {isDirectory ? (
                                  <Folder className={cn("size-4 shrink-0", !isSelected && iconClass)} />
                                ) : (
                                  <File className={cn("size-4 shrink-0", !isSelected && iconClass)} />
                                )}
                                <span className="w-0 min-w-0 flex-1 overflow-hidden">
                                  <span className="block max-w-full truncate text-sm font-medium" title={entry.name}>
                                    {entry.name}
                                  </span>
                                  <span
                                    className={cn(
                                      "text-muted-foreground block max-w-full truncate text-[10px]",
                                      isSelected && "text-primary-foreground/80"
                                    )}
                                  >
                                    {isDirectory ? "Folder" : "File"}
                                  </span>
                                </span>
                              </span>
                              {isDirectory ? <ChevronRight className="size-4 shrink-0 opacity-70" /> : null}
                            </button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </ScrollArea>
              </section>
            ))}

            {columns.length === 0 ? (
              <section className="bg-card text-muted-foreground flex h-full w-80 shrink-0 items-center justify-center border-r p-6 text-center text-sm">
                Select a location to browse folders.
              </section>
            ) : null}
          </div>
        </main>

        <footer className="bg-card flex shrink-0 items-center justify-between gap-3 border-t px-4 py-3">
          <div className="min-w-0">
            <p className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">Selected</p>
            <p className="truncate text-sm font-medium">{selectedName || "Nothing selected"}</p>
            {selectedPath ? (
              <p className="text-muted-foreground truncate text-xs" title={selectedPath}>
                {selectedPath}
              </p>
            ) : null}
            {isLoading ? <p className="text-muted-foreground mt-1 text-xs">Loading...</p> : null}
            {error ? <p className="mt-1 text-xs text-rose-600">{error}</p> : null}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={!selectedPath || isLoading || isCreatingFolder || isRenamingEntry} onClick={onConfirm}>
              {mode === "folder-only" ? "Select Folder" : "Open"}
            </Button>
          </div>
        </footer>

        <DropdownMenu
          open={contextMenuOpen}
          onOpenChange={(nextOpen) => {
            setContextMenuOpen(nextOpen)
            if (!nextOpen) {
              setContextMenuTarget(null)
            }
          }}
        >
          <div
            className="fixed size-0"
            style={{ left: contextMenuPosition.x, top: contextMenuPosition.y }}
            aria-hidden
          />
          <DropdownMenuContent
            align="start"
            side="right"
            sideOffset={4}
            className="z-[80] min-w-56"
            style={{ position: "fixed", left: contextMenuPosition.x, top: contextMenuPosition.y }}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
            }}
          >
            <DropdownMenuItem
              className="gap-2 whitespace-nowrap"
              disabled={!contextMenuTarget || isRenamingEntry}
              onSelect={(event) => {
                event.preventDefault()
                if (!contextMenuTarget) return
                startRenameEntry(contextMenuTarget.entry)
              }}
            >
              <FolderPen className="size-4" />
              Rename Folder
            </DropdownMenuItem>
            {canDeleteContextMenuFolder ? (
              <DropdownMenuItem
                className="gap-2 whitespace-nowrap"
                disabled={!contextMenuTargetEntry || isRenamingEntry}
                onSelect={(event) => {
                  event.preventDefault()
                  if (!contextMenuTargetEntry) return
                  const targetPath = contextMenuTargetEntry.path
                  closeContextMenu()
                  void onDeleteEntry(targetPath)
                }}
              >
                <Trash2 className="size-4" />
                Delete Folder
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
