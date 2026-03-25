import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import type { Workspace } from '../types'

interface WorkspaceActivationDialogProps {
  pendingWorkspace: Workspace | null
  isConfirmingActivation: boolean
  activationError: string | null
  formattedWorkspacePath: string
  onConfirm: () => void
  onClose: () => void
}

export function WorkspaceActivationDialog({
  pendingWorkspace,
  isConfirmingActivation,
  activationError,
  formattedWorkspacePath,
  onConfirm,
  onClose,
}: WorkspaceActivationDialogProps) {
  return (
    <Dialog
      open={pendingWorkspace !== null}
      onOpenChange={(open) => {
        if (open || isConfirmingActivation) {
          return
        }

        onClose()
      }}
    >
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Set Current Workspace?</DialogTitle>
          <DialogDescription>
            This will set the current workspace to this folder:
          </DialogDescription>
        </DialogHeader>

        <div className='rounded-md border bg-muted/40 px-3 py-2 font-mono text-xs break-all'>
          {formattedWorkspacePath}
        </div>

        {pendingWorkspace ? (
          <p className='text-xs text-muted-foreground break-all'>{pendingWorkspace.path}</p>
        ) : null}

        {activationError ? (
          <p className='text-xs text-destructive'>{activationError}</p>
        ) : null}

        <DialogFooter>
          <Button variant='outline' onClick={onClose} disabled={isConfirmingActivation}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={isConfirmingActivation}>
            {isConfirmingActivation ? 'Setting Workspace...' : 'Continue'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
