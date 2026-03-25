import * as React from 'react'
import { GitBranch, Loader2, Trash2 } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { ScrollArea } from '@/shared/components/ui/scroll-area'
import { cn } from '@/shared/utils/utils.ts'
import { Chip } from '@/shared/components/chip'

export type GitRepositoryBranchScope = 'local' | 'remote'

export type GitRepositoryBranchItem = {
  key: string
  name: string
  displayName: string
  shortName: string
  remoteName: string
  scope: GitRepositoryBranchScope
  isCurrent: boolean
  isProtected: boolean
}

type GitBranchesPanelProps = {
  localBranches: GitRepositoryBranchItem[]
  remoteBranches: GitRepositoryBranchItem[]
  isLoadingBranches: boolean
  isSwitchingBranch: boolean
  isDeletingBranch: boolean
  deletingBranchKey: string | null
  onCheckoutBranch: (branchName: string) => Promise<void> | void
  onDeleteBranch: (branch: GitRepositoryBranchItem, force: boolean) => Promise<boolean>
}

function BranchCardRow({
  branch,
  isSwitchingBranch,
  isDeletingBranch,
  deletingBranchKey,
  onCheckoutBranch,
  onRequestDelete,
}: {
  branch: GitRepositoryBranchItem
  isSwitchingBranch: boolean
  isDeletingBranch: boolean
  deletingBranchKey: string | null
  onCheckoutBranch: (branchName: string) => Promise<void> | void
  onRequestDelete: (branch: GitRepositoryBranchItem) => void
}) {
  const isDeletingThisBranch = deletingBranchKey === branch.key
  const canDeleteBranch =
    !branch.isCurrent &&
    !branch.isProtected &&
    !isDeletingBranch &&
    !isSwitchingBranch
  const canCheckoutBranch =
    branch.scope === 'local' &&
    !branch.isCurrent &&
    !isSwitchingBranch &&
    !isDeletingBranch

  return (
    <div className={cn('rounded-md border p-2')}>
      <div className='grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-3'>
        <div className='min-w-0'>
          <p className='truncate text-xs font-medium'>{branch.displayName}</p>

          <p className='text-[11px] text-muted-foreground'>
            {branch.scope === 'local'
              ? 'Local branch'
              : `Remote branch · ${branch.remoteName}`}
          </p>

          <div className='mt-1 flex flex-wrap items-center gap-1'>
            {branch.isCurrent ? (
              <Chip color='success' variant='outline' className='text-[10px]'>
                Current
              </Chip>
            ) : null}

            {branch.isProtected ? (
              <Chip color='warning' variant='outline' className='text-[10px]'>
                Protected
              </Chip>
            ) : null}
          </div>
        </div>

        <div className='flex shrink-0 items-center gap-1'>
          {branch.scope === 'local' ? (
            <Button
              type='button'
              size='xs'
              variant='outline'
              className='h-6 text-[10px]'
              disabled={!canCheckoutBranch}
              onClick={() => {
                void onCheckoutBranch(branch.shortName)
              }}
            >
              Checkout
            </Button>
          ) : null}

          <Button
            type='button'
            size='xs'
            variant='destructive'
            className='h-6 text-[10px]'
            disabled={!canDeleteBranch}
            onClick={() => onRequestDelete(branch)}
          >
            {isDeletingThisBranch ? <Loader2 className='size-3 animate-spin' /> : <Trash2 className='size-3' />}
            Delete
          </Button>
        </div>
      </div>
    </div>
  )
}

export function GitBranchesPanel({
  localBranches,
  remoteBranches,
  isLoadingBranches,
  isSwitchingBranch,
  isDeletingBranch,
  deletingBranchKey,
  onCheckoutBranch,
  onDeleteBranch,
}: GitBranchesPanelProps) {
  const [deleteBranchTarget, setDeleteBranchTarget] = React.useState<GitRepositoryBranchItem | null>(null)
  const [deleteConfirmation, setDeleteConfirmation] = React.useState('')
  const [forceDeleteLocalBranch, setForceDeleteLocalBranch] = React.useState(false)
  const [isSubmittingDelete, setIsSubmittingDelete] = React.useState(false)

  const requiredDeleteText = deleteBranchTarget?.displayName || ''
  const hasMatchingDeleteText = deleteConfirmation.trim() === requiredDeleteText

  React.useEffect(() => {
    setDeleteConfirmation('')
    setForceDeleteLocalBranch(false)
  }, [deleteBranchTarget])

  const handleDeleteBranch = React.useCallback(async () => {
    if (!deleteBranchTarget || !hasMatchingDeleteText || isSubmittingDelete) {
      return
    }

    setIsSubmittingDelete(true)

    const didDelete = await onDeleteBranch(
      deleteBranchTarget,
      deleteBranchTarget.scope === 'local' ? forceDeleteLocalBranch : false,
    )

    setIsSubmittingDelete(false)

    if (didDelete) {
      setDeleteBranchTarget(null)
    }
  }, [
    deleteBranchTarget,
    forceDeleteLocalBranch,
    hasMatchingDeleteText,
    isSubmittingDelete,
    onDeleteBranch,
  ])

  return (
    <div className='grid h-full min-h-0 grid-cols-1 gap-4 p-4 xl:grid-cols-2'>
      <Card className='flex min-h-0 flex-col p-0'>
        <div className='flex items-center justify-between border-b px-3 py-2'>
          <p className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
            Local Branches
          </p>

          <Chip color='grey' variant='outline' className='text-[10px]'>
            {localBranches.length}
          </Chip>
        </div>

        <ScrollArea className='min-h-0 flex-1'>
          <div className='space-y-2 p-2'>
            {isLoadingBranches ? (
              <div className='text-muted-foreground flex items-center gap-2 px-1 py-2 text-xs'>
                <Loader2 className='size-3.5 animate-spin' />
                Loading local branches...
              </div>
            ) : localBranches.length === 0 ? (
              <p className='text-muted-foreground px-1 py-2 text-xs'>
                No local branches found.
              </p>
            ) : (
              localBranches.map((branch) => (
                <BranchCardRow
                  key={branch.key}
                  branch={branch}
                  isSwitchingBranch={isSwitchingBranch}
                  isDeletingBranch={isDeletingBranch}
                  deletingBranchKey={deletingBranchKey}
                  onCheckoutBranch={onCheckoutBranch}
                  onRequestDelete={setDeleteBranchTarget}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </Card>

      <Card className='flex min-h-0 flex-col p-0'>
        <div className='flex items-center justify-between border-b px-3 py-2'>
          <p className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
            Remote Branches
          </p>

          <Chip color='grey' variant='outline' className='text-[10px]'>
            {remoteBranches.length}
          </Chip>
        </div>

        <ScrollArea className='min-h-0 flex-1'>
          <div className='space-y-2 p-2'>
            {isLoadingBranches ? (
              <div className='text-muted-foreground flex items-center gap-2 px-1 py-2 text-xs'>
                <Loader2 className='size-3.5 animate-spin' />
                Loading remote branches...
              </div>
            ) : remoteBranches.length === 0 ? (
              <p className='text-muted-foreground px-1 py-2 text-xs'>
                No remote branches found.
              </p>
            ) : (
              remoteBranches.map((branch) => (
                <BranchCardRow
                  key={branch.key}
                  branch={branch}
                  isSwitchingBranch={isSwitchingBranch}
                  isDeletingBranch={isDeletingBranch}
                  deletingBranchKey={deletingBranchKey}
                  onCheckoutBranch={onCheckoutBranch}
                  onRequestDelete={setDeleteBranchTarget}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </Card>

      <Dialog
        open={Boolean(deleteBranchTarget)}
        onOpenChange={(isOpen) => {
          if (isSubmittingDelete) {
            return
          }

          if (!isOpen) {
            setDeleteBranchTarget(null)
          }
        }}
      >
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2 text-base'>
              <GitBranch className='size-4' />
              Delete {deleteBranchTarget?.scope || 'branch'}
            </DialogTitle>

            <DialogDescription className='space-y-2'>
              <span className='block'>
                This action cannot be undone. Type{' '}
                <span className='font-semibold text-foreground'>
                  {requiredDeleteText}
                </span>{' '}
                to confirm.
              </span>

              <span className='block'>
                Protected and currently checked-out branches cannot be deleted.
              </span>
            </DialogDescription>
          </DialogHeader>

          <div className='space-y-3'>
            <Input
              value={deleteConfirmation}
              onChange={(event) => setDeleteConfirmation(event.target.value)}
              placeholder={requiredDeleteText ? `Type ${requiredDeleteText}` : 'Type branch name'}
              disabled={isSubmittingDelete}
            />

            {deleteBranchTarget?.scope === 'local' ? (
              <label className='flex items-center gap-2 text-xs text-muted-foreground'>
                <input
                  type='checkbox'
                  checked={forceDeleteLocalBranch}
                  onChange={(event) => setForceDeleteLocalBranch(event.target.checked)}
                  disabled={isSubmittingDelete}
                  className='size-3 accent-primary'
                />
                Force delete if the branch has unmerged commits.
              </label>
            ) : null}
          </div>

          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              onClick={() => setDeleteBranchTarget(null)}
              disabled={isSubmittingDelete}
            >
              Cancel
            </Button>

            <Button
              type='button'
              variant='destructive'
              disabled={!hasMatchingDeleteText || isSubmittingDelete}
              onClick={() => {
                void handleDeleteBranch()
              }}
            >
              {isSubmittingDelete ? (
                <Loader2 className='size-3.5 animate-spin' />
              ) : (
                <Trash2 className='size-3.5' />
              )}
              Delete Branch
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
