import * as React from "react"
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, FolderTree, Loader2, RefreshCw } from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import { ScrollArea } from "@/shared/components/ui/scroll-area"
import { cn } from "@/shared/utils/utils.ts"
import { PanelHeader } from "@/shared/components/panel-header"
import type { FileSystemEntry, FileSystemTreeResponse } from "@/shared/types/file-browser"
import type { FileTreeSnapshot, FileTreeSnapshotNode } from "@/features/prompts/types"
import {
  serializeWorkspaceReferenceDragPayload,
  type WorkspaceRole,
  WORKSPACE_REFERENCE_MIME_TYPE,
} from "@/features/prompts/utils/workspace-references"

type TreeNode = {
  name: string
  path: string
  type: "dir" | "file"
  children?: TreeNode[] | null
  isLoading?: boolean
}

type FileTreePanelProps = {
  workspacePath: string
  onTreeSnapshotChange: (snapshot: FileTreeSnapshot) => void
  workspaceRole?: WorkspaceRole
  title?: string
  description?: string
  readOnly?: boolean
  className?: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

const mapEntryToNode = (entry: FileSystemEntry): TreeNode => ({
  name: entry.name,
  path: entry.path,
  type: entry.type,
  children: entry.type === "dir" ? null : undefined,
  isLoading: false,
})

const treeNameFromPath = (path: string) => {
  const normalized = path.replace(/\\/g, "/")
  const parts = normalized.split("/").filter(Boolean)
  return parts[parts.length - 1] || normalized || "workspace"
}

const updateTreeNode = (node: TreeNode, targetPath: string, updater: (value: TreeNode) => TreeNode): TreeNode => {
  if (node.path === targetPath) {
    return updater(node)
  }

  if (!Array.isArray(node.children) || node.children.length === 0) {
    return node
  }

  let changed = false
  const nextChildren = node.children.map((child) => {
    const nextChild = updateTreeNode(child, targetPath, updater)
    if (nextChild !== child) {
      changed = true
    }
    return nextChild
  })

  if (!changed) {
    return node
  }

  return {
    ...node,
    children: nextChildren,
  }
}

const serializeNode = (node: TreeNode): FileTreeSnapshotNode => ({
  name: node.name,
  path: node.path,
  type: node.type,
  children: Array.isArray(node.children) ? node.children.map(serializeNode) : undefined,
})

export function FileTreePanel({
  workspacePath,
  onTreeSnapshotChange,
  workspaceRole = "primary",
  title = "Explorer",
  description = "Workspace files",
  readOnly = false,
  className,
}: FileTreePanelProps) {
  const [tree, setTree] = React.useState<TreeNode | null>(null)
  const [expandedPaths, setExpandedPaths] = React.useState<Set<string>>(new Set())
  const [isLoadingRoot, setIsLoadingRoot] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const fetchDirectoryEntries = React.useCallback(async (path: string) => {
    const params = new URLSearchParams()
    params.set("path", path)
    params.set("include_files", "true")
    params.set("show_hidden", "false")

    const response = await fetch(buildApiUrl(`/api/fs/tree?${params.toString()}`))
    if (!response.ok) {
      const body = await response.text()
      throw new Error(body || `Failed to load file tree (${response.status})`)
    }

    const payload = (await response.json()) as FileSystemTreeResponse
    const activeColumn = payload.columns[payload.columns.length - 1]
    return activeColumn?.entries || []
  }, [])

  const loadRoot = React.useCallback(async () => {
    const trimmedPath = workspacePath.trim()
    if (!trimmedPath) {
      setTree(null)
      setExpandedPaths(new Set())
      setError(null)
      return
    }

    setIsLoadingRoot(true)
    setError(null)
    try {
      const entries = await fetchDirectoryEntries(trimmedPath)
      const nextTree: TreeNode = {
        name: treeNameFromPath(trimmedPath),
        path: trimmedPath,
        type: "dir",
        children: entries.map(mapEntryToNode),
        isLoading: false,
      }
      setTree(nextTree)
      setExpandedPaths(new Set([trimmedPath]))
    } catch (err) {
      setTree(null)
      setExpandedPaths(new Set())
      setError(err instanceof Error ? err.message : "Failed to load file tree")
    } finally {
      setIsLoadingRoot(false)
    }
  }, [fetchDirectoryEntries, workspacePath])

  React.useEffect(() => {
    void loadRoot()
  }, [loadRoot])

  React.useEffect(() => {
    onTreeSnapshotChange({
      root: tree ? serializeNode(tree) : null,
      expandedPaths: Array.from(expandedPaths),
    })
  }, [expandedPaths, onTreeSnapshotChange, tree])

  const toggleDirectory = React.useCallback(
    async (path: string) => {
      if (!tree) return

      const wasExpanded = expandedPaths.has(path)
      const nextExpanded = new Set(expandedPaths)
      if (wasExpanded) {
        if (path !== tree.path) {
          nextExpanded.delete(path)
        }
        setExpandedPaths(nextExpanded)
        return
      }

      nextExpanded.add(path)
      setExpandedPaths(nextExpanded)

      const maybeTarget = (() => {
        const walk = (node: TreeNode): TreeNode | null => {
          if (node.path === path) return node
          if (!Array.isArray(node.children)) return null
          for (const child of node.children) {
            const found = walk(child)
            if (found) return found
          }
          return null
        }
        return walk(tree)
      })()

      if (!maybeTarget || maybeTarget.type !== "dir" || maybeTarget.children !== null) {
        return
      }

      setTree((current) =>
        current
          ? updateTreeNode(current, path, (node) => ({
              ...node,
              isLoading: true,
            }))
          : current
      )

      try {
        const children = await fetchDirectoryEntries(path)
        setTree((current) =>
          current
            ? updateTreeNode(current, path, (node) => ({
                ...node,
                isLoading: false,
                children: children.map(mapEntryToNode),
              }))
            : current
        )
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to expand folder")
        setTree((current) =>
          current
            ? updateTreeNode(current, path, (node) => ({
                ...node,
                isLoading: false,
              }))
            : current
        )
      }
    },
    [expandedPaths, fetchDirectoryEntries, tree]
  )

  const renderNode = React.useCallback(
    (node: TreeNode, depth = 0): React.ReactNode => {
      const isDirectory = node.type === "dir"
      const isExpanded = isDirectory ? expandedPaths.has(node.path) : false
      const leftPadding = `${0.5 + depth * 0.875}rem`

      return (
        <div key={node.path}>
          <button
            type="button"
            draggable
            className={cn(
              "hover:bg-accent flex w-full items-center gap-1.5 rounded-md py-1.5 pr-2 text-left text-sm transition-colors",
              isDirectory && "font-medium"
            )}
            style={{ paddingLeft: leftPadding }}
            onDragStart={(event) => {
              const payload = serializeWorkspaceReferenceDragPayload({
                name: node.name,
                path: node.path,
                type: node.type,
                workspaceRole,
              })
              event.dataTransfer.effectAllowed = "copy"
              event.dataTransfer.setData(WORKSPACE_REFERENCE_MIME_TYPE, payload)
              event.dataTransfer.setData("text/plain", node.path)
            }}
            onClick={() => {
              if (isDirectory) {
                void toggleDirectory(node.path)
              }
            }}
            aria-expanded={isDirectory ? isExpanded : undefined}
            aria-label={node.name}
          >
            {isDirectory ? (
              isExpanded ? (
                <ChevronDown className="text-muted-foreground size-3.5 shrink-0" />
              ) : (
                <ChevronRight className="text-muted-foreground size-3.5 shrink-0" />
              )
            ) : (
              <span className="size-3.5 shrink-0" aria-hidden="true" />
            )}

            {isDirectory ? (
              isExpanded ? (
                <FolderOpen className="text-primary size-4 shrink-0" />
              ) : (
                <Folder className="text-primary size-4 shrink-0" />
              )
            ) : (
              <File className="text-muted-foreground size-4 shrink-0" />
            )}

            <span className="truncate">{node.name}</span>
            {node.isLoading ? <Loader2 className="text-muted-foreground ml-auto size-3.5 animate-spin" /> : null}
          </button>

          {isDirectory && isExpanded && Array.isArray(node.children)
            ? node.children.map((child) => renderNode(child, depth + 1))
            : null}
        </div>
      )
    },
    [expandedPaths, toggleDirectory, workspaceRole]
  )

  return (
    <section className={cn("flex h-full min-h-0 flex-col bg-background", className)}>
      <PanelHeader
        icon={<FolderTree className="text-muted-foreground size-4" />}
        title={title}
        description={readOnly ? `${description} · read-only` : description}
        borderBottom
      >
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Refresh file tree"
          disabled={isLoadingRoot}
          onClick={() => void loadRoot()}
        >
          <RefreshCw className={cn("size-4", isLoadingRoot && "animate-spin")} />
        </Button>
      </PanelHeader>

      {error ? <p className="px-4 py-2 text-xs text-rose-600">{error}</p> : null}

      <ScrollArea className="flex-1 min-h-0 px-2 py-3">
        {isLoadingRoot ? (
          <div className="text-muted-foreground flex items-center gap-2 px-2 py-2 text-sm">
            <Loader2 className="size-4 animate-spin" />
            Loading workspace tree...
          </div>
        ) : tree ? (
          <div className="space-y-0.5 pb-6">{renderNode(tree)}</div>
        ) : (
          <p className="text-muted-foreground px-2 py-2 text-sm">No workspace selected.</p>
        )}
      </ScrollArea>
    </section>
  )
}

export default FileTreePanel
