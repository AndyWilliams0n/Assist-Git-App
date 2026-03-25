import { type ReactNode } from 'react'
import { type Table as TanStackTable } from '@tanstack/react-table'
import { ChevronDown, ListTodo, RefreshCw, Search } from 'lucide-react'

import { SiteSubheader } from '@/shared/components/site-subheader.tsx'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Input } from '@/shared/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type {
  JiraUser,
  WorkflowCurrentSprint,
  WorkflowKanbanColumn,
  WorkflowSpecTask,
  WorkflowSprintStatusCount,
} from '@/features/workflow-tasks/types'
import DataTable from '@/shared/components/data-table'
import { Chip } from '@/shared/components/chip'

type WorkflowTasksTabsHeaderProps = {
  activeTab: string
}

type WorkflowTasksHeaderSectionProps = {
  shouldRender: boolean
  projectKey: string
  boardNumber: string
  assigneeFilter: string
  jiraUsers: JiraUser[]
  onProjectKeyChange: (value: string) => void
  onBoardNumberChange: (value: string) => void
  onAssigneeFilterChange: (value: string) => void
  onFetchUsers: () => void
  isFetchingUsers: boolean
  onBlurSave: () => void
  canFetch: boolean
  isFetching: boolean
  isLoadingConfig: boolean
  onFetchTasks: () => void
  ticketsCount: number
  tasksWithoutEpicsCount: number
  epicsCount: number
  specsCount: number
  server: string
  tool: string
  fetchedAt?: string
  savedAt?: string
  dbId: string
  formatDate: (value?: string) => string
}

type WorkflowProjectTabProps = {
  currentSprint: WorkflowCurrentSprint | null
  sprintTicketsCount: number
  sprintStatusCounts: WorkflowSprintStatusCount[]
  sprintTicketKeys: string[]
  sprintTicketKeyPreview: string[]
  sprintTicketKeyOverflowCount: number
  kanbanColumns: WorkflowKanbanColumn[]
  maxKanbanCount: number
  hasExactKanbanConfig: boolean
  formatDate: (value?: string) => string
}

type WorkflowTableTabProps<TRow> = {
  value: string
  title: string
  table: TanStackTable<TRow>
  onRowClick: (row: TRow) => void
  emptyMessage: string
  searchPlaceholder: string
  globalFilter: string
  onGlobalFilterChange: (value: string) => void
  topToolbarLeftActions?: ReactNode
}

type SpecTaskDeleteDialogProps = {
  pendingTask: WorkflowSpecTask | null
  isDeleting: boolean
  deleteError: string | null
  onOpenChange: (isOpen: boolean) => void
  onCancel: () => void
  onConfirmDelete: () => void
}

export function WorkflowTasksTabsHeader({ activeTab }: WorkflowTasksTabsHeaderProps) {
  return (
    <SiteSubheader>
      <TabsList variant='line'>
        <TabsTrigger value='project' data-state={activeTab === 'project' ? 'active' : 'inactive'}>
          PROJECT
        </TabsTrigger>

        <TabsTrigger value='tasks' data-state={activeTab === 'tasks' ? 'active' : 'inactive'}>
          TASKS
        </TabsTrigger>

        <TabsTrigger value='epics' data-state={activeTab === 'epics' ? 'active' : 'inactive'}>
          EPICS
        </TabsTrigger>

        <TabsTrigger value='specs' data-state={activeTab === 'specs' ? 'active' : 'inactive'}>
          SPECS
        </TabsTrigger>
      </TabsList>
    </SiteSubheader>
  )
}

export function WorkflowTasksHeaderSection({
  shouldRender,
  projectKey,
  boardNumber,
  assigneeFilter,
  jiraUsers,
  onProjectKeyChange,
  onBoardNumberChange,
  onAssigneeFilterChange,
  onFetchUsers,
  isFetchingUsers,
  onBlurSave,
  canFetch,
  isFetching,
  isLoadingConfig,
  onFetchTasks,
  ticketsCount,
  tasksWithoutEpicsCount,
  epicsCount,
  specsCount,
  server,
  tool,
  fetchedAt,
  savedAt,
  dbId,
  formatDate,
}: WorkflowTasksHeaderSectionProps) {
  if (!shouldRender) return null

  const assigneeSelectValue = assigneeFilter || '__all__'

  return (
    <>
      <div className='flex items-center gap-3'>
        <div className='flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary'>
          <ListTodo className='size-5' />
        </div>

        <div>
          <h1 className='text-xl font-semibold tracking-tight'>Workflow Tasks</h1>

          <p className='text-muted-foreground text-sm'>
            Fetch tasks from your Jira backlog via the Jira REST API.
          </p>
        </div>
      </div>

      <div className='flex flex-col gap-2 md:flex-row'>
        <Input
          placeholder='PROJECT'
          value={projectKey}
          onChange={(event) => onProjectKeyChange(event.target.value)}
          onBlur={onBlurSave}
        />

        <Input
          placeholder='BOARD NUMBER'
          value={boardNumber}
          onChange={(event) => onBoardNumberChange(event.target.value)}
          onBlur={onBlurSave}
        />

        <Button
          type='button'
          className='md:min-w-40'
          disabled={isFetching || isLoadingConfig || !canFetch}
          onClick={onFetchTasks}
        >
          <RefreshCw className={`size-4 ${isFetching ? 'animate-spin' : ''}`} />
          {isFetching ? 'Fetching...' : 'Fetch Tasks'}
        </Button>
      </div>

      <div className='flex flex-col gap-2 sm:flex-row sm:items-center'>
        <Select
          value={assigneeSelectValue}
          onValueChange={(value) => {
            onAssigneeFilterChange(value === '__all__' ? '' : value)
          }}
        >
          <SelectTrigger className='w-full sm:w-56'>
            <SelectValue placeholder='Filter by assignee' />
          </SelectTrigger>

          <SelectContent>
            <SelectItem value='__all__'>All assignees</SelectItem>

            <SelectItem value='__unassigned__'>Unassigned</SelectItem>

            {jiraUsers.map((user) => (
              <SelectItem key={user.accountId} value={user.displayName}>
                {user.displayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          type='button'
          variant='outline'
          size='sm'
          disabled={isFetchingUsers}
          onClick={onFetchUsers}
        >
          <RefreshCw className={`size-4 ${isFetchingUsers ? 'animate-spin' : ''}`} />
          {isFetchingUsers ? 'Loading...' : 'Load Users'}
        </Button>
      </div>

      <div className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
        <span className='rounded-md border px-2 py-1'>{ticketsCount} tasks</span>

        <span className='rounded-md border px-2 py-1'>{tasksWithoutEpicsCount} tasks/subtasks</span>

        <span className='rounded-md border px-2 py-1'>{epicsCount} epics</span>

        <span className='rounded-md border px-2 py-1'>{specsCount} specs</span>

        {server ? <span className='rounded-md border px-2 py-1'>Server {server}</span> : null}

        {tool ? <span className='rounded-md border px-2 py-1'>Tool {tool}</span> : null}

        {fetchedAt ? <span className='rounded-md border px-2 py-1'>Updated {formatDate(fetchedAt)}</span> : null}

        {savedAt ? <span className='rounded-md border px-2 py-1'>Saved {formatDate(savedAt)}</span> : null}

        {dbId ? <span className='rounded-md border px-2 py-1'>DB {dbId.slice(0, 8)}</span> : null}
      </div>
    </>
  )
}

export function WorkflowProjectTab({
  currentSprint,
  sprintTicketsCount,
  sprintStatusCounts,
  sprintTicketKeys,
  sprintTicketKeyPreview,
  sprintTicketKeyOverflowCount,
  kanbanColumns,
  maxKanbanCount,
  hasExactKanbanConfig,
  formatDate,
}: WorkflowProjectTabProps) {
  return (
    <TabsContent value='project' className='mt-0 space-y-6'>
      <section className='space-y-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-lg font-semibold'>Current Sprint</h2>

          <div className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
            <span className='rounded-md border px-2 py-1'>
              {currentSprint?.ticket_count ?? sprintTicketsCount} tickets
            </span>

            {currentSprint?.name ? (
              <span className='rounded-md border px-2 py-1'>{currentSprint.name}</span>
            ) : null}

            {currentSprint?.state ? (
              <span className='rounded-md border px-2 py-1'>State {currentSprint.state}</span>
            ) : null}

            {currentSprint?.start_date ? (
              <span className='rounded-md border px-2 py-1'>Start {formatDate(currentSprint.start_date)}</span>
            ) : null}

            {currentSprint?.end_date ? (
              <span className='rounded-md border px-2 py-1'>End {formatDate(currentSprint.end_date)}</span>
            ) : null}
          </div>
        </div>

        {currentSprint?.goal ? (
          <p className='text-muted-foreground text-sm'>{currentSprint.goal}</p>
        ) : null}

        <div className='grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
          <div className='rounded-lg border bg-card'>
            <TooltipProvider delayDuration={150}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Sprint</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Start</TableHead>
                    <TableHead>End</TableHead>
                    <TableHead>Complete</TableHead>
                    <TableHead>Goal</TableHead>
                    <TableHead>Tickets</TableHead>
                    <TableHead>Ticket Keys</TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {currentSprint ? (
                    <TableRow>
                      <TableCell className='font-medium'>{currentSprint.name || 'Current Sprint'}</TableCell>

                      <TableCell>{currentSprint.state || 'n/a'}</TableCell>

                      <TableCell>{formatDate(currentSprint.start_date)}</TableCell>

                      <TableCell>{formatDate(currentSprint.end_date)}</TableCell>

                      <TableCell>{formatDate(currentSprint.complete_date)}</TableCell>

                      <TableCell className='max-w-80'>
                        <span className='line-clamp-2' title={currentSprint.goal || ''}>
                          {currentSprint.goal || 'n/a'}
                        </span>
                      </TableCell>

                      <TableCell className='tabular-nums'>{currentSprint.ticket_count ?? sprintTicketsCount}</TableCell>

                      <TableCell>
                        {sprintTicketKeys.length > 0 ? (
                          <div className='flex flex-wrap items-center gap-1.5'>
                            {sprintTicketKeyPreview.map((key) => (
                              <Chip key={`sprint-chip-${key}`} color='info' variant='filled'>
                                {key}
                              </Chip>
                            ))}

                            {sprintTicketKeyOverflowCount > 0 ? (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Chip color='info' variant='outline' className='cursor-help'>
                                    +{sprintTicketKeyOverflowCount} more
                                  </Chip>
                                </TooltipTrigger>

                                <TooltipContent className='max-w-sm'>
                                  <div className='space-y-1'>
                                    <div className='font-medium'>Sprint Tickets ({sprintTicketKeys.length})</div>

                                    <div className='max-h-48 overflow-y-auto'>
                                      {sprintTicketKeys.join(', ')}
                                    </div>
                                  </div>
                                </TooltipContent>
                              </Tooltip>
                            ) : null}
                          </div>
                        ) : (
                          <span className='text-muted-foreground'>n/a</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ) : (
                    <TableRow>
                      <TableCell colSpan={8} className='text-muted-foreground h-24 text-center'>
                        No current sprint metadata returned yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TooltipProvider>
          </div>

          <div className='rounded-lg border bg-card p-4'>
            <div className='mb-3 flex items-center justify-between'>
              <h3 className='text-sm font-semibold'>Sprint Counts</h3>

              <span className='text-muted-foreground text-xs'>{sprintTicketsCount} total</span>
            </div>

            <div className='space-y-2'>
              {sprintStatusCounts.length > 0 ? (
                sprintStatusCounts.map((item) => (
                  <div
                    key={`sprint-count-${item.name}`}
                    className='flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm'
                  >
                    <span className='truncate'>{item.name || 'Unknown'}</span>

                    <span className='font-medium tabular-nums'>{item.ticket_count}</span>
                  </div>
                ))
              ) : (
                <p className='text-muted-foreground text-sm'>No sprint counts available.</p>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className='space-y-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-lg font-semibold'>Kanban Board Columns</h2>

          <div className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
            <span>{kanbanColumns.length > 0 ? `${kanbanColumns.length} columns` : 'No columns yet'}</span>

            <span className='rounded-md border px-2 py-1'>
              {hasExactKanbanConfig
                ? 'Exact board columns from Jira REST config'
                : 'Observed statuses from backlog + current sprint'}
            </span>
          </div>
        </div>

        <div className='rounded-lg border bg-card p-4'>
          {kanbanColumns.length > 0 ? (
            <div className='space-y-3'>
              {kanbanColumns.map((column) => {
                const count = Number(column.ticket_count) || 0

                const widthPct = maxKanbanCount > 0
                  ? Math.max((count / maxKanbanCount) * 100, count > 0 ? 6 : 0)
                  : 0

                const sharePct = typeof column.share_of_total === 'number'
                  ? Math.round(column.share_of_total * 100)
                  : undefined

                return (
                  <div key={`kanban-column-${column.name}`} className='grid grid-cols-[160px_minmax(0,1fr)_auto] gap-3'>
                    <div className='truncate pt-0.5 text-sm font-medium'>{column.name || 'Unknown'}</div>

                    <div className='space-y-1'>
                      <div className='bg-muted h-3 overflow-hidden rounded-full'>
                        <div
                          className='h-full rounded-full bg-primary/80 transition-[width]'
                          style={{ width: `${widthPct}%` }}
                        />
                      </div>

                      {Array.isArray(column.statuses) && column.statuses.length > 0 ? (
                        <p className='text-muted-foreground line-clamp-2 text-xs'>
                          {column.statuses
                            .map((status) => status.name || status.id || '')
                            .filter(Boolean)
                            .join(', ') || 'No mapped statuses'}
                        </p>
                      ) : null}
                    </div>

                    <div className='text-muted-foreground min-w-20 pt-0.5 text-right text-xs tabular-nums'>
                      {count} {sharePct !== undefined ? `(${sharePct}%)` : ''}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className='text-muted-foreground text-sm'>
              Kanban column data will appear after a Jira fetch.
            </p>
          )}
        </div>
      </section>
    </TabsContent>
  )
}

export function WorkflowTableTab<TRow>({
  value,
  title,
  table,
  onRowClick,
  emptyMessage,
  searchPlaceholder,
  globalFilter,
  onGlobalFilterChange,
  topToolbarLeftActions,
}: WorkflowTableTabProps<TRow>) {
  return (
    <TabsContent value={value} className='mt-0'>
      <section className='space-y-2'>
        <h2 className='text-lg font-semibold'>{title}</h2>

        <DataTable
          table={table}
          onRowClick={onRowClick}
          emptyMessage={emptyMessage}
          topToolbarLeft={
            <div className='flex w-full flex-wrap items-center gap-2'>
              {topToolbarLeftActions ? (
                <div className='flex items-center gap-2'>
                  {topToolbarLeftActions}
                </div>
              ) : null}

              <div className='relative w-full min-w-60 md:w-80'>
                <Search className='text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2' />

                <Input
                  placeholder={searchPlaceholder}
                  value={globalFilter}
                  onChange={(event) => onGlobalFilterChange(event.target.value)}
                  className='h-9 w-full pl-9'
                />
              </div>
            </div>
          }
          topToolbarRight={
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type='button' variant='outline' size='sm'>
                  Columns
                  <ChevronDown className='ml-2 size-4' />
                </Button>
              </DropdownMenuTrigger>

              <DropdownMenuContent align='end'>
                {table
                  .getAllColumns()
                  .filter((column) => column.getCanHide())
                  .map((column) => (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      className='capitalize'
                      checked={column.getIsVisible()}
                      onCheckedChange={(nextValue) => column.toggleVisibility(Boolean(nextValue))}
                    >
                      {column.id.replace('_', ' ')}
                    </DropdownMenuCheckboxItem>
                  ))}
              </DropdownMenuContent>
            </DropdownMenu>
          }
        />
      </section>
    </TabsContent>
  )
}

export function SpecTaskDeleteDialog({
  pendingTask,
  isDeleting,
  deleteError,
  onOpenChange,
  onCancel,
  onConfirmDelete,
}: SpecTaskDeleteDialogProps) {
  return (
    <Dialog open={Boolean(pendingTask)} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Delete Spec Task?</DialogTitle>

          <DialogDescription>
            This removes the task entry only. It does not delete any spec files from disk.
          </DialogDescription>
        </DialogHeader>

        <div className='min-w-0 space-y-1 text-sm'>
          <div>
            <span className='text-muted-foreground'>Spec:</span>{' '}
            <span className='font-medium'>{pendingTask?.spec_name || 'n/a'}</span>
          </div>

          <div className='text-muted-foreground max-w-full break-all text-xs'>
            {pendingTask?.spec_path || ''}
          </div>
        </div>

        {deleteError ? <p className='text-sm text-rose-600'>{deleteError}</p> : null}

        <DialogFooter className='flex-wrap'>
          <Button
            type='button'
            variant='outline'
            disabled={isDeleting}
            onClick={onCancel}
          >
            Cancel
          </Button>

          <Button
            type='button'
            variant='destructive'
            disabled={isDeleting}
            onClick={onConfirmDelete}
          >
            {isDeleting ? 'Deleting...' : 'Delete Task'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
