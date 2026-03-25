export type FileSystemEntry = {
  name: string
  path: string
  type: "dir" | "file"
  size?: number
  modified_at?: string
}

export type FileSystemColumn = {
  path: string
  name: string
  parent: string | null
  entries: FileSystemEntry[]
}

export type FileSystemTreeResponse = {
  home: string
  selected_path: string
  columns: FileSystemColumn[]
}

export type FileSystemSearchResponse = {
  path: string
  query: string
  entries: FileSystemEntry[]
}

export type FileFolderDialogMode = "file-and-folder" | "folder-only"
