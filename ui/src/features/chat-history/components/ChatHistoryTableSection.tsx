import { useMemo, useState } from "react"
import {
  type ColumnDef,
  type ColumnSort,
  getFilteredRowModel,
  type VisibilityState,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  ChevronDown,
  MoreHorizontal,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"
import { Input } from "@/shared/components/ui/input"
import type { ConversationSummary } from "@/features/chat-history/types"
import DataTable from "@/shared/components/data-table"

type ChatHistoryTableSectionProps = {
  conversations: ConversationSummary[]
  selectedIds: string[]
  allSelected: boolean
  isIndeterminate: boolean
  deleting: boolean
  loading: boolean
  onSelectAll: (checked: boolean) => void
  onSelectOne: (conversationId: string) => void
  onOpenConversation: (conversationId: string) => void
  onDeleteConversations: (ids: string[]) => void
  onRefresh: () => void
}

const formatTimestamp = (value?: string | null) => {
  if (!value) {
    return "-"
  }

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date)
}

const truncateCellClassName = "max-w-[280px] truncate"

const compareTimestamp = (a?: string | null, b?: string | null) => {
  const first = a ? new Date(a).getTime() : 0
  const second = b ? new Date(b).getTime() : 0

  if (Number.isNaN(first) || Number.isNaN(second)) {
    return String(a ?? "").localeCompare(String(b ?? ""))
  }

  return first - second
}

export default function ChatHistoryTableSection({
  conversations,
  selectedIds,
  allSelected,
  isIndeterminate,
  deleting,
  loading,
  onSelectAll,
  onSelectOne,
  onOpenConversation,
  onDeleteConversations,
  onRefresh,
}: ChatHistoryTableSectionProps) {
  const [sorting, setSorting] = useState<ColumnSort[]>([{ id: "updated_at", desc: true }])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [globalFilter, setGlobalFilter] = useState("")

  const columns = useMemo<ColumnDef<ConversationSummary>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        enableHiding: false,
        header: () => (
          <input
            type="checkbox"
            className="h-4 w-4 cursor-pointer rounded border-border align-middle"
            checked={allSelected}
            aria-label="Select all conversations"
            ref={(element) => {
              if (element) {
                element.indeterminate = isIndeterminate
              }
            }}
            onChange={(event) => onSelectAll(event.target.checked)}
            onClick={(event) => event.stopPropagation()}
          />
        ),
        cell: ({ row }) => {
          const conversation = row.original
          const isSelected = selectedIds.includes(conversation.id)

          return (
            <div
              onClick={(event) => {
                event.stopPropagation()
              }}
            >
              <input
                type="checkbox"
                className="h-4 w-4 cursor-pointer rounded border-border align-middle"
                checked={isSelected}
                aria-label={`Select conversation ${conversation.id}`}
                onChange={() => onSelectOne(conversation.id)}
              />
            </div>
          )
        },
      },
      {
        accessorKey: "id",
        id: "conversation",
        header: "Conversation",
        cell: ({ row }) => {
          const conversation = row.original

          return (
            <div>
              <p className="font-medium">Conversation {conversation.id.slice(0, 8)}</p>
              <p className="text-muted-foreground text-xs">{conversation.id}</p>
            </div>
          )
        },
      },
      {
        accessorKey: "updated_at",
        header: ({ column }) => {
          return (
            <Button
              type="button"
              variant="ghost"
              className="h-auto p-0 font-medium"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              Updated
              <ArrowUpDown className="ml-2 size-4" />
            </Button>
          )
        },
        sortingFn: (rowA, rowB) => compareTimestamp(rowA.original.updated_at, rowB.original.updated_at),
        cell: ({ row }) => formatTimestamp(row.original.updated_at),
      },
      {
        accessorKey: "message_count",
        header: ({ column }) => {
          return (
            <Button
              type="button"
              variant="ghost"
              className="h-auto p-0 font-medium"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              Messages
              <ArrowUpDown className="ml-2 size-4" />
            </Button>
          )
        },
        cell: ({ row }) => row.original.message_count ?? 0,
      },
      {
        accessorKey: "last_role",
        header: ({ column }) => {
          return (
            <Button
              type="button"
              variant="ghost"
              className="h-auto p-0 font-medium"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              Last Role
              <ArrowUpDown className="ml-2 size-4" />
            </Button>
          )
        },
        cell: ({ row }) => row.original.last_role || "-",
      },
      {
        accessorKey: "last_message",
        header: "Last Message",
        cell: ({ row }) => (
          <div className={truncateCellClassName}>{row.original.last_message || "No messages yet."}</div>
        ),
      },
      {
        id: "actions",
        enableHiding: false,
        enableSorting: false,
        header: () => <div className="text-right">Actions</div>,
        cell: ({ row }) => {
          const conversation = row.original

          return (
            <div
              className="text-right"
              onClick={(event) => {
                event.stopPropagation()
              }}
            >
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label="Open actions menu">
                    <MoreHorizontal className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Actions</DropdownMenuLabel>
                  <DropdownMenuItem onClick={() => onOpenConversation(conversation.id)}>
                    Open conversation
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    disabled={deleting}
                    onClick={() => onDeleteConversations([conversation.id])}
                  >
                    <Trash2 className="mr-2 size-4" />
                    Delete conversation
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )
        },
      },
    ],
    [allSelected, deleting, isIndeterminate, onDeleteConversations, onOpenConversation, onSelectAll, onSelectOne, selectedIds]
  )

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: conversations,
    columns,
    state: {
      sorting,
      columnVisibility,
      globalFilter,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  })

  return (
    <DataTable
      table={table}
      onRowClick={(row) => onOpenConversation(row.id)}
      isRowSelected={(row) => selectedIds.includes(row.id)}
      emptyMessage="No conversations found."
      selectedCount={selectedIds.length}
      totalCount={conversations.length}
      topToolbarLeft={
        <>
          <p className="text-muted-foreground text-sm">{selectedIds.length} selected</p>
          <div className="relative w-full min-w-60 md:w-80">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
            <Input
              placeholder="Search conversations..."
              value={globalFilter}
              onChange={(event) => setGlobalFilter(event.target.value)}
              className="h-9 w-full pl-9"
            />
          </div>
        </>
      }
      topToolbarRight={
        <>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="outline" size="sm">
                Columns
                <ChevronDown className="ml-2 size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {table
                .getAllColumns()
                .filter((column) => column.getCanHide())
                .map((column) => (
                  <DropdownMenuCheckboxItem
                    key={column.id}
                    className="capitalize"
                    checked={column.getIsVisible()}
                    onCheckedChange={(value) => column.toggleVisibility(Boolean(value))}
                  >
                    {column.id.replace("_", " ")}
                  </DropdownMenuCheckboxItem>
                ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={selectedIds.length === 0 || deleting}
            onClick={() => onDeleteConversations(selectedIds)}
          >
            <Trash2 className="size-4" />
            Delete Selected
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={loading || deleting}
            onClick={onRefresh}
          >
            <RefreshCw className="size-4" />
            Refresh
          </Button>
        </>
      }
    />
  )
}
