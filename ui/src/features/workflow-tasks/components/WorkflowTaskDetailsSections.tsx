import { ChevronDown, ChevronRight, ExternalLink, Eye, FileImage, FileText } from 'lucide-react'

import { Image } from '@/shared/components/prompt-kit/image'
import { Markdown } from '@/shared/components/prompt-kit/markdown'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardFooter } from '@/shared/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { ScrollArea } from '@/shared/components/ui/scroll-area'
import { Separator } from '@/shared/components/ui/separator'
import type {
  WorkflowTask,
  WorkflowTaskAttachment,
  WorkflowTaskComment,
  WorkflowTaskHistoryEntry,
} from '@/features/workflow-tasks/types'
import { Chip } from '@/shared/components/chip'

export type ActivityTab = 'all' | 'comments' | 'history'

type WorkflowTaskNotFoundStateProps = {
  normalizedTaskKey: string
  error: string | null
  warning: string
  isFetching: boolean
  onBack: () => void
  onRefresh: () => void
}

type WorkflowTaskHeaderProps = {
  task: WorkflowTask
  issueUrl: string
  onBack: () => void
  onOpenJira: () => void
}

type WorkflowTaskDescriptionSectionProps = {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  description: string
}

type WorkflowTaskAttachmentsSectionProps = {
  attachments: WorkflowTaskAttachment[]
  onPreviewAttachment: (attachment: WorkflowTaskAttachment) => void
  resolveAttachmentUrl: (url?: string) => string
  attachmentNameFor: (attachment: WorkflowTaskAttachment, index: number) => string
  attachmentExtensionFor: (attachment: WorkflowTaskAttachment) => string
  isImageAttachment: (attachment: WorkflowTaskAttachment) => boolean
}

type WorkflowTaskSubtasksSectionProps = {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  title: string
  donePercent: number
  subtasks: WorkflowTask[]
  isCurrentTaskSubtask: boolean
  currentTaskKey: string
  onOpenTask: (taskKey: string) => void
}

type WorkflowTaskDetailsSectionProps = {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  rows: { label: string; value: string }[]
}

type WorkflowTaskActivitySectionProps = {
  activityTab: ActivityTab
  onActivityTabChange: (tab: ActivityTab) => void
  hasActivity: boolean
  comments: WorkflowTaskComment[]
  history: WorkflowTaskHistoryEntry[]
  formatDate: (value?: string) => string
}

type WorkflowTaskAttachmentPreviewDialogProps = {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  taskKey: string
  previewAttachmentUrl: string
  previewAttachmentName: string
  previewIsImage: boolean
}

export function WorkflowTaskNotFoundState({
  normalizedTaskKey,
  error,
  warning,
  isFetching,
  onBack,
  onRefresh,
}: WorkflowTaskNotFoundStateProps) {
  return (
    <div className='flex flex-1 flex-col gap-4 p-6'>
      <div className='space-y-1'>
        <h1 className='text-xl font-semibold tracking-tight'>Task not found</h1>

        <p className='text-muted-foreground text-sm'>
          Could not find task <span className='font-mono'>{normalizedTaskKey || '(unknown)'}</span> in current data.
        </p>
      </div>

      {error ? (
        <div className='rounded-md border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-700'>
          {error}
        </div>
      ) : null}

      {warning ? (
        <div className='rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-700'>
          {warning}
        </div>
      ) : null}

      <div className='flex gap-2'>
        <Button type='button' variant='outline' onClick={onBack}>
          Back to tasks
        </Button>

        <Button type='button' disabled={isFetching} onClick={onRefresh}>
          Refresh tasks
        </Button>
      </div>
    </div>
  )
}

export function WorkflowTaskHeader({ task, issueUrl, onBack, onOpenJira }: WorkflowTaskHeaderProps) {
  return (
    <>
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='space-y-1'>
          <p className='text-muted-foreground text-xs uppercase tracking-wide'>
            {task.issue_type || 'Work item'} / {task.key}
          </p>

          <h1 className='text-xl font-semibold tracking-tight'>{task.summary || '(No summary)'}</h1>

          <div className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
            <span className='rounded-md border px-2 py-1'>{task.status || 'No status'}</span>

            <span className='rounded-md border px-2 py-1'>{task.priority || 'No priority'}</span>

            <span className='rounded-md border px-2 py-1'>{task.assignee || 'Unassigned'}</span>
          </div>
        </div>

        <div className='flex gap-2'>
          <Button type='button' variant='outline' onClick={onBack}>
            Back
          </Button>

          {issueUrl ? (
            <Button type='button' variant='outline' onClick={onOpenJira}>
              <ExternalLink className='size-4' />
              Open in Jira
            </Button>
          ) : null}
        </div>
      </div>

      <Separator />
    </>
  )
}

export function WorkflowTaskDescriptionSection({
  isOpen,
  onOpenChange,
  description,
}: WorkflowTaskDescriptionSectionProps) {
  return (
    <Collapsible open={isOpen} onOpenChange={onOpenChange} className='rounded-md border'>
      <CollapsibleTrigger asChild>
        <Button type='button' variant='ghost' className='flex w-full items-center justify-between rounded-b-none px-3 py-2'>
          <span className='flex items-center gap-2 font-medium'>
            {isOpen ? <ChevronDown className='size-4' /> : <ChevronRight className='size-4' />}
            Description
          </span>

          <span className='text-muted-foreground text-xs'>{isOpen ? 'Hide' : 'Show'}</span>
        </Button>
      </CollapsibleTrigger>

      <CollapsibleContent className='px-3 pb-3'>
        {description ? (
          <Markdown className='prose prose-sm max-w-none dark:prose-invert'>{description}</Markdown>
        ) : (
          <p className='text-muted-foreground text-sm'>No description</p>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

export function WorkflowTaskAttachmentsSection({
  attachments,
  onPreviewAttachment,
  resolveAttachmentUrl,
  attachmentNameFor,
  attachmentExtensionFor,
  isImageAttachment,
}: WorkflowTaskAttachmentsSectionProps) {
  return (
    <section className='space-y-3 rounded-md border p-3'>
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='space-y-1'>
          <h2 className='font-semibold'>Attachments</h2>

          <p className='text-muted-foreground text-sm'>
            {attachments.length > 0
              ? `${attachments.length} attachment${attachments.length === 1 ? '' : 's'} on this ticket.`
              : 'No attachments on this ticket.'}
          </p>
        </div>
      </div>

      {attachments.length === 0 ? null : (
        <div className='grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
          {attachments.map((attachment, index) => {
            const resolvedUrl = resolveAttachmentUrl(attachment.url)
            const name = attachmentNameFor(attachment, index)
            const extension = attachmentExtensionFor(attachment)
            const isImage = isImageAttachment(attachment)

            return (
              <Card key={`${name}-${resolvedUrl || index}`} className='gap-0 overflow-hidden py-0'>
                <div className='bg-muted/30 flex aspect-video items-center justify-center overflow-hidden border-b'>
                  {isImage && resolvedUrl ? (
                    <button
                      type='button'
                      className='h-full w-full cursor-zoom-in'
                      onClick={() => onPreviewAttachment(attachment)}
                    >
                      <Image
                        src={resolvedUrl}
                        alt={name}
                        className='h-full w-full rounded-none object-cover'
                      />
                    </button>
                  ) : (
                    <button
                      type='button'
                      className='flex h-full w-full items-center justify-center gap-2 px-4 text-sm font-medium'
                      onClick={() => onPreviewAttachment(attachment)}
                    >
                      {isImage ? <FileImage className='size-5' /> : <FileText className='size-5' />}

                      <span>{extension ? extension.toUpperCase() : 'FILE'}</span>
                    </button>
                  )}
                </div>

                <CardContent className='space-y-3 p-3'>
                  <div className='min-w-0 space-y-1'>
                    <p className='truncate font-medium' title={name}>
                      {name}
                    </p>

                    <Chip color='grey' variant='outline' className='uppercase tracking-wide'>
                      {extension || 'file'}
                    </Chip>
                  </div>
                </CardContent>

                <CardFooter className='flex flex-wrap gap-2 border-t p-3'>
                  <div className='flex flex-wrap gap-2'>
                    <Button type='button' size='sm' variant='outline' onClick={() => onPreviewAttachment(attachment)}>
                      <Eye className='size-4' />
                      Preview
                    </Button>

                    {resolvedUrl ? (
                      <Button type='button' size='sm' variant='outline' asChild>
                        <a href={resolvedUrl} target='_blank' rel='noreferrer'>
                          <ExternalLink className='size-4' />
                          Open
                        </a>
                      </Button>
                    ) : null}
                  </div>
                </CardFooter>
              </Card>
            )
          })}
        </div>
      )}
    </section>
  )
}

export function WorkflowTaskSubtasksSection({
  isOpen,
  onOpenChange,
  title,
  donePercent,
  subtasks,
  isCurrentTaskSubtask,
  currentTaskKey,
  onOpenTask,
}: WorkflowTaskSubtasksSectionProps) {
  return (
    <Collapsible open={isOpen} onOpenChange={onOpenChange} className='rounded-md border'>
      <CollapsibleTrigger asChild>
        <Button type='button' variant='ghost' className='flex w-full items-center justify-between rounded-b-none px-3 py-2'>
          <span className='flex items-center gap-2 font-medium'>
            {isOpen ? <ChevronDown className='size-4' /> : <ChevronRight className='size-4' />}
            {title}
          </span>

          <span className='text-muted-foreground text-xs'>{isOpen ? 'Hide' : 'Show'}</span>
        </Button>
      </CollapsibleTrigger>

      <CollapsibleContent className='space-y-3 px-3 pb-3'>
        <div>
          <p className='text-muted-foreground text-sm'>{donePercent}% Done</p>

          <div className='bg-muted mt-2 h-2 w-full overflow-hidden rounded-full'>
            <div className='bg-primary h-2' style={{ width: `${donePercent}%` }} />
          </div>
        </div>

        {subtasks.length === 0 ? (
          <p className='text-muted-foreground text-sm'>
            {isCurrentTaskSubtask ? 'No related subtasks.' : 'No subtasks.'}
          </p>
        ) : (
          <div className='rounded-md border'>
            <table className='w-full text-sm'>
              <thead className='bg-muted/60'>
                <tr>
                  <th className='px-3 py-2 text-left font-medium'>Work</th>
                  <th className='px-3 py-2 text-left font-medium'>Priority</th>
                  <th className='px-3 py-2 text-left font-medium'>Assignee</th>
                  <th className='px-3 py-2 text-left font-medium'>Status</th>
                </tr>
              </thead>

              <tbody>
                {subtasks.map((task) => (
                  <tr
                    key={task.key}
                    className='hover:bg-muted/40 cursor-pointer border-t'
                    onClick={() => onOpenTask(task.key)}
                  >
                    <td className='px-3 py-2'>
                      {task.key} {task.summary || ''}
                      {task.key === currentTaskKey ? ' (current)' : ''}
                    </td>

                    <td className='px-3 py-2'>{task.priority || 'None'}</td>

                    <td className='px-3 py-2'>{task.assignee || 'Unassigned'}</td>

                    <td className='px-3 py-2'>{task.status || 'None'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

export function WorkflowTaskDetailsSection({
  isOpen,
  onOpenChange,
  rows,
}: WorkflowTaskDetailsSectionProps) {
  return (
    <Collapsible open={isOpen} onOpenChange={onOpenChange} className='rounded-md border'>
      <CollapsibleTrigger asChild>
        <Button type='button' variant='ghost' className='flex w-full items-center justify-between rounded-b-none px-3 py-2'>
          <span className='flex items-center gap-2 font-medium'>
            {isOpen ? <ChevronDown className='size-4' /> : <ChevronRight className='size-4' />}
            Details
          </span>

          <span className='text-muted-foreground text-xs'>{isOpen ? 'Hide' : 'Show'}</span>
        </Button>
      </CollapsibleTrigger>

      <CollapsibleContent className='px-3 pb-3'>
        <div className='divide-y rounded-md border'>
          {rows.map((row) => (
            <div key={row.label} className='grid grid-cols-[170px_1fr] gap-2 px-3 py-2 text-sm'>
              <span className='text-muted-foreground'>{row.label}</span>

              <span>{row.value}</span>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function WorkflowTaskActivitySection({
  activityTab,
  onActivityTabChange,
  hasActivity,
  comments,
  history,
  formatDate,
}: WorkflowTaskActivitySectionProps) {
  return (
    <section className='space-y-3 rounded-md border p-3'>
      <h2 className='font-semibold'>Activity</h2>

      <div className='flex flex-wrap gap-2'>
        <Button type='button' size='sm' variant={activityTab === 'all' ? 'default' : 'outline'} onClick={() => onActivityTabChange('all')}>
          All
        </Button>

        <Button
          type='button'
          size='sm'
          variant={activityTab === 'comments' ? 'default' : 'outline'}
          onClick={() => onActivityTabChange('comments')}
        >
          Comments
        </Button>

        <Button
          type='button'
          size='sm'
          variant={activityTab === 'history' ? 'default' : 'outline'}
          onClick={() => onActivityTabChange('history')}
        >
          History
        </Button>
      </div>

      {!hasActivity ? (
        <p className='text-muted-foreground text-sm'>No comments or history available for this issue.</p>
      ) : (
        <div className='space-y-3'>
          {(activityTab === 'all' || activityTab === 'comments') &&
            comments.map((item, index) => (
              <div key={`comment-${item.id || index}`} className='rounded-md border p-3'>
                <p className='text-muted-foreground text-xs'>
                  {item.author || 'Unknown'} - {item.created ? formatDate(item.created) : 'n/a'} - comment
                </p>

                <p className='mt-1 text-sm'>{item.body || '(empty comment)'}</p>
              </div>
            ))}

          {(activityTab === 'all' || activityTab === 'history') &&
            history.map((item, index) => (
              <div key={`history-${item.id || index}`} className='rounded-md border p-3'>
                <p className='text-muted-foreground text-xs'>
                  {item.author || 'Unknown'} - {item.created ? formatDate(item.created) : 'n/a'} - history
                </p>

                {item.changes && item.changes.length ? (
                  <div className='mt-1 space-y-1 text-sm'>
                    {item.changes.map((change, changeIndex) => (
                      <p key={`${item.id || index}-${changeIndex}`}>
                        {change.field || 'Field'}: {change.from || 'None'} to {change.to || 'None'}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className='mt-1 text-sm'>No detailed field changes.</p>
                )}
              </div>
            ))}
        </div>
      )}
    </section>
  )
}

export function WorkflowTaskAttachmentPreviewDialog({
  isOpen,
  onOpenChange,
  taskKey,
  previewAttachmentUrl,
  previewAttachmentName,
  previewIsImage,
}: WorkflowTaskAttachmentPreviewDialogProps) {
  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className='flex max-h-[90vh] max-w-6xl flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl'>
        <DialogHeader className='border-b px-6 pt-6 pb-4'>
          <DialogTitle className='pr-10'>{previewAttachmentName || 'Attachment preview'}</DialogTitle>

          <DialogDescription>
            Previewing attachment for {taskKey}. If it does not render here, open it in a new tab.
          </DialogDescription>
        </DialogHeader>

        <div className='flex min-h-0 flex-1 flex-col px-6 py-4'>
          {previewAttachmentUrl ? (
            previewIsImage ? (
              <ScrollArea className='h-[72vh] rounded-md border'>
                <div className='flex min-h-full items-start justify-center bg-muted/20 p-4'>
                  <Image
                    src={previewAttachmentUrl}
                    alt={previewAttachmentName || 'Attachment preview'}
                    className='max-h-none w-auto max-w-full object-contain'
                  />
                </div>
              </ScrollArea>
            ) : (
              <div className='space-y-3'>
                <div className='text-muted-foreground text-xs'>
                  Embedded preview depends on the file type and Jira response headers.
                </div>

                <div className='overflow-hidden rounded-md border'>
                  <iframe
                    src={previewAttachmentUrl}
                    title={previewAttachmentName || 'Attachment preview'}
                    className='h-[68vh] w-full bg-background'
                  />
                </div>
              </div>
            )
          ) : (
            <p className='text-muted-foreground text-sm'>This attachment does not include a preview URL.</p>
          )}

          {previewAttachmentUrl ? (
            <div className='mt-4 flex justify-end'>
              <Button type='button' variant='outline' asChild>
                <a href={previewAttachmentUrl} target='_blank' rel='noreferrer'>
                  <ExternalLink className='size-4' />
                  Open in new tab
                </a>
              </Button>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
