import { type ReactNode } from "react"
import { type Table as TanStackTable, flexRender } from "@tanstack/react-table"
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/components/ui/table"

type DataTableProps<TData> = {
  table: TanStackTable<TData>
  onRowClick?: (row: TData) => void
  isRowSelected?: (row: TData) => boolean
  topToolbarLeft?: ReactNode
  topToolbarRight?: ReactNode
  emptyMessage?: string
  selectedCount?: number
  totalCount?: number
  rowsPerPageOptions?: number[]
}

export default function DataTable<TData>({
  table,
  onRowClick,
  isRowSelected,
  topToolbarLeft,
  topToolbarRight,
  emptyMessage = "No results found.",
  selectedCount,
  totalCount,
  rowsPerPageOptions = [5, 10, 25, 50],
}: DataTableProps<TData>) {
  const showSelectionSummary = typeof selectedCount === "number" && typeof totalCount === "number"

  return (
    <section className="space-y-3">
      {topToolbarLeft || topToolbarRight ? (
        <div className="pt-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">{topToolbarLeft}</div>
            <div className="flex flex-wrap items-center justify-end gap-2">{topToolbarRight}</div>
          </div>
        </div>
      ) : null}

      <div className="rounded-lg border bg-card">
        <Table className="rounded-lg overflow-hidden">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} className="sticky top-0 z-10 bg-card">
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => {
                const selected = isRowSelected ? isRowSelected(row.original) : false

                return (
                  <TableRow
                    key={row.id}
                    data-state={selected ? "selected" : undefined}
                    className={onRowClick ? "cursor-pointer" : undefined}
                    onClick={() => onRowClick?.(row.original)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                )
              })
            ) : (
              <TableRow>
                <TableCell className="h-24 text-center" colSpan={table.getVisibleLeafColumns().length}>
                  {emptyMessage}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between gap-4">
        <p className="text-muted-foreground text-sm">
          {showSelectionSummary
            ? `${selectedCount} of ${totalCount} row(s) selected.`
            : `${table.getRowModel().rows.length} row(s)`}
        </p>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium">Rows per page</p>
            <select
              className="border-input bg-background ring-offset-background placeholder:text-muted-foreground focus-visible:ring-ring h-9 w-16 rounded-md border px-2 py-1 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
              value={table.getState().pagination.pageSize}
              onChange={(event) => {
                table.setPageSize(Number(event.target.value))
              }}
            >
              {rowsPerPageOptions.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </div>
          <p className="text-sm font-medium">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount() || 1}
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
              aria-label="Go to first page"
            >
              <ChevronsLeft className="size-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label="Go to previous page"
            >
              <ChevronLeft className="size-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label="Go to next page"
            >
              <ChevronRight className="size-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={() => table.setPageIndex(Math.max((table.getPageCount() || 1) - 1, 0))}
              disabled={!table.getCanNextPage()}
              aria-label="Go to last page"
            >
              <ChevronsRight className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}
