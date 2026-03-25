import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  FileCode,
  GitBranch,
  GitCommit,
  Globe,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardTitle } from '@/shared/components/ui/card'
import { Separator } from '@/shared/components/ui/separator'
import { formatGitPlatformLabel } from '@/features/git/constants'
import type { WorkspaceGitStatus } from '@/features/git/types'
import { Chip } from '@/shared/components/chip'
import { obfuscateSecretsInText } from '@/shared/utils/secret-sanitizer'
import { cn } from '@/shared/utils/utils.ts'

interface WorkspaceGitStatusProps {
  gitStatus: WorkspaceGitStatus | null
  isLoading: boolean
  error: string | null
  onRefresh: () => void
  className?: string
  showBranchAndChangeChips?: boolean
}

export function WorkspaceGitStatus({
  gitStatus,
  isLoading,
  error,
  onRefresh,
  className,
  showBranchAndChangeChips = true,
}: WorkspaceGitStatusProps) {
  return (
    <Card className={cn('!shadow-none p-0 h-full', className)}>
      <CardContent className='p-4 h-full'>
        <div className='flex items-center justify-between'>
          <CardTitle className='text-sm font-medium flex items-center gap-2'>
            <GitBranch className='size-4' />
            Workspace Git Status
          </CardTitle>

          <Button
            variant='ghost'
            size='icon'
            className='size-7'
            onClick={onRefresh}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className='size-3.5 animate-spin' />
            ) : (
              <RefreshCw className='size-3.5' />
            )}
          </Button>
        </div>

        <div className='mt-3'>
          {error ? (
            <div className={`flex items-center gap-2 text-sm ${error === 'Backend not available' ? 'text-muted-foreground' : 'text-destructive'}`}>
              <AlertCircle className='size-4 shrink-0' />

              <span>{error === 'Backend not available' ? 'Backend not running — start the API server to see live git status.' : error}</span>
            </div>
          ) : isLoading && !gitStatus ? (
            <div className='flex items-center gap-2 text-sm text-muted-foreground'>
              <Loader2 className='size-4 animate-spin' />

              Checking git status…
            </div>
          ) : !gitStatus ? (
            <div className='text-sm text-muted-foreground'>No workspace selected.</div>
          ) : !gitStatus.is_git_repo ? (
            <div className='flex items-center gap-2'>
              <Chip color='error' variant='outline' className='gap-1'>
                <X className='size-3' />

                Not a Git repo
              </Chip>

              <span className='text-xs text-muted-foreground'>{gitStatus.workspace}</span>
            </div>
          ) : (
            <div className='space-y-3'>
              <div className='flex flex-wrap items-center gap-2'>
                <Chip color='success' variant='outline' className='gap-1'>
                  <Check className='size-3' />

                  Git detected
                </Chip>

                {showBranchAndChangeChips ? (
                  <Chip color='info' variant='outline' className='gap-1'>
                    <GitBranch className='size-3' />

                    {gitStatus.branch || 'unknown'}
                  </Chip>
                ) : null}

                {showBranchAndChangeChips && gitStatus.platform && gitStatus.platform !== 'unknown' && (
                  <Chip className='gap-1'>
                    <Globe className='size-3' />

                    {formatGitPlatformLabel(gitStatus.platform)}
                  </Chip>
                )}

                {showBranchAndChangeChips && gitStatus.ahead > 0 && (
                  <Chip color='warning' variant='outline' className='gap-1'>
                    <ArrowUp className='size-3' />

                    {gitStatus.ahead} ahead
                  </Chip>
                )}

                {showBranchAndChangeChips && gitStatus.behind > 0 && (
                  <Chip color='warning' variant='outline' className='gap-1'>
                    <ArrowDown className='size-3' />

                    {gitStatus.behind} behind
                  </Chip>
                )}
              </div>

              {showBranchAndChangeChips && (gitStatus.modified > 0 || gitStatus.staged > 0 || gitStatus.untracked > 0) && (
                <div className='flex flex-wrap items-center gap-2'>
                  {gitStatus.staged > 0 && (
                    <Chip color='success' variant='outline'>{gitStatus.staged} staged</Chip>
                  )}

                  {gitStatus.modified > 0 && (
                    <Chip color='error' variant='outline'>{gitStatus.modified} modified</Chip>
                  )}

                  {gitStatus.untracked > 0 && (
                    <Chip>{gitStatus.untracked} untracked</Chip>
                  )}
                </div>
              )}

              {showBranchAndChangeChips &&
                gitStatus.modified === 0 &&
                gitStatus.staged === 0 &&
                gitStatus.untracked === 0 && (
                  <div className='text-xs text-muted-foreground flex items-center gap-1'>
                    <Check className='size-3 text-emerald-500' />

                    Working tree clean
                  </div>
                )}

              {gitStatus.remote_url && (
                <>
                  <Separator />

                  <div className='flex items-start gap-2 text-xs text-muted-foreground'>
                    <Globe className='size-3 mt-0.5 shrink-0' />

                    <span className='truncate'>{obfuscateSecretsInText(gitStatus.remote_url)}</span>
                  </div>
                </>
              )}

              {gitStatus.last_commit?.hash && (
                <div className='flex items-start gap-2 text-xs text-muted-foreground'>
                  <GitCommit className='size-3 mt-0.5 shrink-0' />

                  <span>
                    <span className='font-mono mr-1'>{gitStatus.last_commit.hash}</span>
                    {gitStatus.last_commit.message}
                    <span className='ml-1 opacity-60'>· {gitStatus.last_commit.when}</span>
                  </span>
                </div>
              )}

              <Separator />

              <div className='flex items-center gap-2 text-xs'>
                <span className='text-muted-foreground'>CLI tools:</span>

                <Chip
                  color={gitStatus.gh_available ? 'success' : 'error'}
                  variant='outline'
                  className='gap-1'
                >
                  <FileCode className='size-3' />
                  gh
                </Chip>

                <Chip
                  color={gitStatus.glab_available ? 'success' : 'error'}
                  variant='outline'
                  className='gap-1'
                >
                  <FileCode className='size-3' />

                  glab
                </Chip>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
