import { useCallback, useMemo, useRef, useState } from "react"

import type {
  FileFolderDialogMode,
  FileSystemColumn,
  FileSystemEntry,
  FileSystemTreeResponse,
} from "@/shared/types/file-browser"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) return path
  return `${API_BASE_URL}${path}`
}

const joinPath = (base: string, segment: string) => {
  if (!base) return segment
  if (base.endsWith("/")) return `${base}${segment}`
  return `${base}/${segment}`
}

const parentPath = (path: string) => {
  const trimmed = path.trim()
  if (!trimmed || trimmed === "/") return "/"
  const normalized = trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed
  const separatorIndex = normalized.lastIndexOf("/")
  if (separatorIndex <= 0) return "/"
  return normalized.slice(0, separatorIndex)
}

const normalizeError = (error: unknown, fallback: string) => {
  if (error instanceof Error) return error.message
  return fallback
}

type UseFileFolderDialogArgs = {
  mode?: FileFolderDialogMode
  initialShowHidden?: boolean
}

type UseFileFolderDialogResult = {
  homePath: string
  columns: FileSystemColumn[]
  locations: Array<{ label: string; path: string }>
  selectedPath: string
  activeDirectoryPath: string
  selectedByColumnPath: Record<string, string>
  showHidden: boolean
  isLoading: boolean
  isCreatingFolder: boolean
  isRenamingEntry: boolean
  error: string | null
  openAtPath: (path: string) => Promise<void>
  refresh: () => Promise<void>
  setShowHidden: (value: boolean) => Promise<void>
  selectLocation: (path: string) => Promise<void>
  selectEntry: (columnIndex: number, entry: FileSystemEntry) => Promise<void>
  createFolder: (parentPath: string, name: string) => Promise<string | null>
  renameEntry: (path: string, name: string) => Promise<string | null>
  deleteEntry: (path: string) => Promise<boolean>
}

export default function useFileFolderDialog({
  mode = "file-and-folder",
  initialShowHidden = true,
}: UseFileFolderDialogArgs = {}): UseFileFolderDialogResult {
  const [homePath, setHomePath] = useState("")
  const [columns, setColumns] = useState<FileSystemColumn[]>([])
  const [selectedPath, setSelectedPath] = useState("")
  const [activeDirectoryPath, setActiveDirectoryPath] = useState("")
  const [selectedByColumnPath, setSelectedByColumnPath] = useState<Record<string, string>>({})
  const [showHidden, setShowHiddenState] = useState(initialShowHidden)
  const [isLoading, setIsLoading] = useState(false)
  const [isCreatingFolder, setIsCreatingFolder] = useState(false)
  const [isRenamingEntry, setIsRenamingEntry] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cacheRef = useRef<Map<string, FileSystemTreeResponse>>(new Map())

  const applyTree = useCallback((data: FileSystemTreeResponse) => {
    const nextColumns = data.columns || []
    const nextSelections: Record<string, string> = {}
    for (let index = 0; index < nextColumns.length - 1; index += 1) {
      nextSelections[nextColumns[index].path] = nextColumns[index + 1].path
    }

    setHomePath(data.home || "")
    setColumns(nextColumns)
    setActiveDirectoryPath(data.selected_path || "")
    setSelectedPath(data.selected_path || "")
    setSelectedByColumnPath(nextSelections)
  }, [])

  const loadTree = useCallback(
    async (path: string, options?: { force?: boolean; showHiddenOverride?: boolean }) => {
      const includeFiles = mode === "file-and-folder"
      const hidden = options?.showHiddenOverride ?? showHidden
      const cacheKey = `${path.trim()}::${includeFiles ? "1" : "0"}::${hidden ? "1" : "0"}`

      if (!options?.force) {
        const cached = cacheRef.current.get(cacheKey)
        if (cached) {
          applyTree(cached)
          setError(null)
          return
        }
      }

      setIsLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        if (path.trim()) params.set("path", path.trim())
        params.set("include_files", includeFiles ? "true" : "false")
        params.set("show_hidden", hidden ? "true" : "false")
        const response = await fetch(buildApiUrl(`/api/fs/tree?${params.toString()}`))
        if (!response.ok) {
          const body = await response.text()
          throw new Error(body || `Failed to load file tree (${response.status})`)
        }

        const data = (await response.json()) as FileSystemTreeResponse
        cacheRef.current.set(cacheKey, data)
        applyTree(data)
      } catch (err) {
        setError(normalizeError(err, "Failed to load file tree"))
      } finally {
        setIsLoading(false)
      }
    },
    [applyTree, mode, showHidden]
  )

  const openAtPath = useCallback(
    async (path: string) => {
      const nextPath = path.trim()
      if (nextPath) {
        setSelectedPath(nextPath)
        setActiveDirectoryPath(nextPath)
      }
      await loadTree(nextPath)
    },
    [loadTree]
  )

  const refresh = useCallback(async () => {
    const targetPath = activeDirectoryPath || selectedPath
    await loadTree(targetPath, { force: true })
  }, [activeDirectoryPath, loadTree, selectedPath])

  const setShowHidden = useCallback(
    async (value: boolean) => {
      setShowHiddenState(value)
      cacheRef.current.clear()
      const targetPath = activeDirectoryPath || selectedPath
      await loadTree(targetPath, { force: true, showHiddenOverride: value })
    },
    [activeDirectoryPath, loadTree, selectedPath]
  )

  const selectLocation = useCallback(
    async (path: string) => {
      await openAtPath(path)
    },
    [openAtPath]
  )

  const selectEntry = useCallback(
    async (columnIndex: number, entry: FileSystemEntry) => {
      const allowedColumnPaths = new Set(columns.slice(0, columnIndex + 1).map((column) => column.path))

      if (entry.type === "dir") {
        setSelectedByColumnPath((current) => {
          const trimmed = Object.fromEntries(
            Object.entries(current).filter(([columnPath]) => allowedColumnPaths.has(columnPath))
          )

          if (columns[columnIndex]) {
            trimmed[columns[columnIndex].path] = entry.path
          }

          return trimmed
        })
        setSelectedPath(entry.path)
        await loadTree(entry.path)
        return
      }

      if (mode === "folder-only") {
        return
      }

      setSelectedByColumnPath((current) => {
        const trimmed = Object.fromEntries(
          Object.entries(current).filter(([columnPath]) => allowedColumnPaths.has(columnPath))
        )
        if (columns[columnIndex]) {
          trimmed[columns[columnIndex].path] = entry.path
        }
        return trimmed
      })
      setSelectedPath(entry.path)
      setError(null)
    },
    [columns, loadTree, mode]
  )

  const createFolder = useCallback(
    async (parentPath: string, name: string) => {
      const trimmedName = name.trim()
      if (!trimmedName || !parentPath.trim()) return null

      setIsCreatingFolder(true)
      setError(null)
      try {
        const response = await fetch(buildApiUrl("/api/fs/mkdir"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: parentPath, name: trimmedName }),
        })

        if (!response.ok) {
          const body = await response.text()
          throw new Error(body || `Failed to create folder (${response.status})`)
        }

        const data = (await response.json()) as { directory?: { path?: string } }
        cacheRef.current.clear()
        const createdPath = data.directory?.path || joinPath(parentPath, trimmedName)
        await loadTree(createdPath, { force: true })
        return createdPath
      } catch (err) {
        setError(normalizeError(err, "Failed to create folder"))
        return null
      } finally {
        setIsCreatingFolder(false)
      }
    },
    [loadTree]
  )

  const renameEntry = useCallback(
    async (path: string, name: string) => {
      const trimmedPath = path.trim()
      const trimmedName = name.trim()
      if (!trimmedPath || !trimmedName) return null

      setIsRenamingEntry(true)
      setError(null)
      try {
        const response = await fetch(buildApiUrl("/api/fs/rename"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: trimmedPath, name: trimmedName }),
        })

        if (!response.ok) {
          const body = await response.text()
          throw new Error(body || `Failed to rename entry (${response.status})`)
        }

        const data = (await response.json()) as { entry?: { path?: string } }
        const nextPath = data.entry?.path || joinPath(parentPath(trimmedPath), trimmedName)
        cacheRef.current.clear()
        await loadTree(parentPath(trimmedPath), { force: true })
        setSelectedPath(nextPath)
        return nextPath
      } catch (err) {
        setError(normalizeError(err, "Failed to rename entry"))
        return null
      } finally {
        setIsRenamingEntry(false)
      }
    },
    [loadTree]
  )

  const deleteEntry = useCallback(
    async (path: string) => {
      const trimmedPath = path.trim()
      if (!trimmedPath) return false

      setError(null)
      try {
        const response = await fetch(buildApiUrl("/api/fs/rmdir"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: trimmedPath }),
        })

        if (!response.ok) {
          const body = await response.text()
          throw new Error(body || `Failed to delete folder (${response.status})`)
        }

        cacheRef.current.clear()
        const parent = parentPath(trimmedPath)
        await loadTree(parent, { force: true })
        setSelectedPath(parent)
        return true
      } catch (err) {
        setError(normalizeError(err, "Failed to delete folder"))
        return false
      }
    },
    [loadTree]
  )

  const locations = useMemo(() => {
    const candidates = [
      { label: "Home", path: homePath },
      { label: "Desktop", path: homePath ? joinPath(homePath, "Desktop") : "" },
      { label: "Documents", path: homePath ? joinPath(homePath, "Documents") : "" },
      { label: "Downloads", path: homePath ? joinPath(homePath, "Downloads") : "" },
      { label: "Root", path: "/" },
    ]

    const seen = new Set<string>()
    return candidates.filter((item) => {
      if (!item.path || seen.has(item.path)) return false
      seen.add(item.path)
      return true
    })
  }, [homePath])

  return {
    homePath,
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
    refresh,
    setShowHidden,
    selectLocation,
    selectEntry,
    createFolder,
    renameEntry,
    deleteEntry,
  }
}
