import * as React from 'react'
import { GitBranch, Loader2 } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const buildApiUrl = (path: string) => (API_BASE_URL ? `${API_BASE_URL}${path}` : path)

type BaseBranchOption = 'default' | 'current'

type ChangesOption = 'stash' | 'bring'

type Step = 'configure' | 'changes'

type CreateBranchResponse = {
  success?: boolean
  branch?: string
  detail?: string
  error?: string
}

type StashResponse = {
  ok?: boolean
  detail?: string
}

function detectDefaultBaseBranch(localBranchOptions: string[]): string {
  const lower = localBranchOptions.map((b) => b.toLowerCase())

  if (lower.includes('main')) {
    return 'main'
  }

  if (lower.includes('master')) {
    return 'master'
  }

  return localBranchOptions[0] ?? 'main'
}

export type CreateBranchDialogProps = {
  isOpen: boolean
  workspacePath: string
  currentBranch: string
  localBranchOptions: string[]
  hasGitChanges: boolean
  onClose: () => void
  onSuccess: (branchName: string) => void
}

export function CreateBranchDialog({
  isOpen,
  workspacePath,
  currentBranch,
  localBranchOptions,
  hasGitChanges,
  onClose,
  onSuccess,
}: CreateBranchDialogProps) {
  const [step, setStep] = React.useState<Step>('configure')
  const [branchName, setBranchName] = React.useState('')
  const [baseBranchOption, setBaseBranchOption] = React.useState<BaseBranchOption>('default')
  const [changesOption, setChangesOption] = React.useState<ChangesOption>('stash')
  const [isCreating, setIsCreating] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const defaultBaseBranch = React.useMemo(
    () => detectDefaultBaseBranch(localBranchOptions),
    [localBranchOptions],
  )

  const isCurrentBranchDefault =
    currentBranch.toLowerCase() === 'main' || currentBranch.toLowerCase() === 'master'

  const resolvedBaseBranch =
    baseBranchOption === 'current' ? currentBranch : defaultBaseBranch

  const normalizedBranchName = branchName.trim()

  const canAdvance = Boolean(normalizedBranchName)

  const handleClose = React.useCallback(() => {
    if (isCreating) {
      return
    }

    setStep('configure')
    setBranchName('')
    setBaseBranchOption('default')
    setChangesOption('stash')
    setError(null)
    onClose()
  }, [isCreating, onClose])

  const handleNext = React.useCallback(() => {
    if (!canAdvance) {
      return
    }

    if (hasGitChanges) {
      setStep('changes')
      return
    }

    void createBranch()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAdvance, hasGitChanges])

  const createBranch = React.useCallback(async () => {
    if (!normalizedBranchName || !workspacePath) {
      return
    }

    setIsCreating(true)
    setError(null)

    const baseIsCurrentBranch = resolvedBaseBranch === currentBranch
    const needsStash = hasGitChanges && (changesOption === 'stash' || !baseIsCurrentBranch)
    const needsStashPop = hasGitChanges && changesOption === 'bring' && !baseIsCurrentBranch

    try {
      if (needsStash) {
        const stashResponse = await fetch(buildApiUrl('/api/git/stash'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace: workspacePath,
            message: `WIP on ${currentBranch} before switching to ${normalizedBranchName}`,
          }),
        })

        const stashPayload = (await stashResponse.json().catch(() => ({}))) as StashResponse

        if (!stashResponse.ok) {
          throw new Error(stashPayload.detail ?? 'Failed to stash changes')
        }
      }

      const createResponse = await fetch(buildApiUrl('/api/git/branch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace: workspacePath,
          branch_name: normalizedBranchName,
          base_branch: baseIsCurrentBranch && changesOption === 'bring' ? undefined : resolvedBaseBranch,
        }),
      })

      const createPayload = (await createResponse.json().catch(() => ({}))) as CreateBranchResponse

      if (!createResponse.ok || createPayload.success === false) {
        if (needsStash) {
          await fetch(buildApiUrl('/api/git/stash/pop'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workspace: workspacePath }),
          }).catch(() => undefined)
        }

        throw new Error(createPayload.detail ?? createPayload.error ?? 'Failed to create branch')
      }

      if (needsStashPop) {
        const popResponse = await fetch(buildApiUrl('/api/git/stash/pop'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace: workspacePath }),
        })

        const popPayload = (await popResponse.json().catch(() => ({}))) as StashResponse

        if (!popResponse.ok) {
          throw new Error(popPayload.detail ?? 'Branch created but failed to restore changes from stash')
        }
      }

      handleClose()
      onSuccess(normalizedBranchName)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create branch')
    } finally {
      setIsCreating(false)
    }
  }, [
    changesOption,
    currentBranch,
    handleClose,
    hasGitChanges,
    normalizedBranchName,
    onSuccess,
    resolvedBaseBranch,
    workspacePath,
  ])

  const handleKeyDown = React.useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key !== 'Enter') {
        return
      }

      if (step === 'configure' && canAdvance) {
        handleNext()
      }
    },
    [canAdvance, handleNext, step],
  )

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className='sm:max-w-md' onKeyDown={handleKeyDown}>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2 text-base'>
            <GitBranch className='size-4' />

            {step === 'configure' ? 'Create New Branch' : 'Handle Uncommitted Changes'}
          </DialogTitle>

          <DialogDescription>
            {step === 'configure'
              ? 'Enter a name and choose where the new branch should start from.'
              : 'You have uncommitted changes. Choose what to do with them.'}
          </DialogDescription>
        </DialogHeader>

        {step === 'configure' ? (
          <div className='space-y-4 py-1'>
            <div className='space-y-1.5'>
              <Label htmlFor='branch-name' className='text-sm'>
                Branch name
              </Label>

              <Input
                id='branch-name'
                value={branchName}
                onChange={(event) => {
                  setBranchName(event.target.value.replace(/\s+/g, '-'))
                  setError(null)
                }}
                placeholder='e.g. feature/my-new-feature'
                className='h-8 text-sm'
                autoFocus
                disabled={isCreating}
              />
            </div>

            <div className='space-y-2'>
              <Label className='text-sm'>Start branch from</Label>

              <div className='space-y-2'>
                <label className='flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/5'>
                  <input
                    type='radio'
                    name='base-branch'
                    value='default'
                    checked={baseBranchOption === 'default'}
                    onChange={() => setBaseBranchOption('default')}
                    disabled={isCreating}
                    className='mt-0.5 accent-primary'
                  />

                  <div>
                    <p className='text-sm font-medium font-mono'>{defaultBaseBranch}</p>

                    <p className='text-xs text-muted-foreground'>
                      Start from the default base branch
                    </p>
                  </div>
                </label>

                {!isCurrentBranchDefault ? (
                  <label className='flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/5'>
                    <input
                      type='radio'
                      name='base-branch'
                      value='current'
                      checked={baseBranchOption === 'current'}
                      onChange={() => setBaseBranchOption('current')}
                      disabled={isCreating}
                      className='mt-0.5 accent-primary'
                    />

                    <div>
                      <p className='text-sm font-medium font-mono'>{currentBranch}</p>

                      <p className='text-xs text-muted-foreground'>
                        Start from your current branch
                      </p>
                    </div>
                  </label>
                ) : null}
              </div>
            </div>

            {error ? (
              <p className='text-xs text-rose-600 dark:text-rose-400'>{error}</p>
            ) : null}
          </div>
        ) : (
          <div className='space-y-2 py-1'>
            <label className='flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/5'>
              <input
                type='radio'
                name='changes-option'
                value='stash'
                checked={changesOption === 'stash'}
                onChange={() => setChangesOption('stash')}
                disabled={isCreating}
                className='mt-0.5 accent-primary'
              />

              <div>
                <p className='text-sm font-semibold'>Leave my changes on {currentBranch}</p>

                <p className='text-xs text-muted-foreground'>
                  Your in-progress work will be stashed on this branch for you to return to later.
                </p>
              </div>
            </label>

            <label className='flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors has-[:checked]:border-primary has-[:checked]:bg-primary/5'>
              <input
                type='radio'
                name='changes-option'
                value='bring'
                checked={changesOption === 'bring'}
                onChange={() => setChangesOption('bring')}
                disabled={isCreating}
                className='mt-0.5 accent-primary'
              />

              <div>
                <p className='text-sm font-semibold'>Bring my changes to {normalizedBranchName}</p>

                <p className='text-xs text-muted-foreground'>
                  Your in-progress work will follow you to the new branch.
                </p>
              </div>
            </label>

            {error ? (
              <p className='text-xs text-rose-600 dark:text-rose-400'>{error}</p>
            ) : null}
          </div>
        )}

        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={step === 'changes' ? () => setStep('configure') : handleClose}
            disabled={isCreating}
          >
            {step === 'changes' ? 'Back' : 'Cancel'}
          </Button>

          <Button
            type='button'
            size='sm'
            disabled={step === 'configure' ? !canAdvance || isCreating : isCreating}
            onClick={step === 'configure' ? handleNext : () => void createBranch()}
          >
            {isCreating ? <Loader2 className='size-3.5 animate-spin' /> : null}

            {step === 'configure'
              ? hasGitChanges
                ? 'Next'
                : 'Create Branch'
              : 'Create Branch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
