import * as React from 'react'
import { Activity, History } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import { cn } from '@/shared/utils/utils.ts'
import { PanelHeader } from '@/shared/components/panel-header'
import {
  AgentActivitySection,
  PromptComposerSection,
  PromptHistorySection,
} from '@/features/prompts/components/PromptPanelSections'
import type { AgentStatus } from '@/shared/types/agents'
import type { PromptHistoryEntry } from '@/features/prompts/types'
import type { WorkspaceReferenceContextItem } from '@/features/prompts/utils/workspace-references'

type PromptPanelProps = {
  primaryWorkspacePath: string
  secondaryWorkspacePath: string | null
  history: PromptHistoryEntry[]
  specName: string
  specNameError: string | null
  promptMode: 'create' | 'edit'
  isProcessing: boolean
  isLoadingSpec: boolean
  agentStatuses: AgentStatus[]
  agentsMode: 'streaming' | 'polling'
  isAgentsLoading: boolean
  agentsError: string | null
  error: string | null
  isHistoryVisible: boolean
  isActivityVisible: boolean
  onSpecNameChange: (nextSpecName: string) => void
  onFetchSpecBundle: (specName: string) => Promise<string | null>
  onSubmit: (payload: { prompt: string; rawPrompt: string; context: WorkspaceReferenceContextItem[] }) => Promise<void | false> | void | false
  onToggleHistoryVisibility: () => void
  onToggleActivityVisibility: () => void
  className?: string
}

export function PromptPanel({
  primaryWorkspacePath,
  secondaryWorkspacePath,
  history,
  specName,
  specNameError,
  promptMode,
  isProcessing,
  isLoadingSpec,
  agentStatuses,
  agentsMode,
  isAgentsLoading,
  agentsError,
  error,
  isHistoryVisible,
  isActivityVisible,
  onSpecNameChange,
  onFetchSpecBundle,
  onSubmit,
  onToggleHistoryVisibility,
  onToggleActivityVisibility,
  className,
}: PromptPanelProps) {
  const endRef = React.useRef<HTMLDivElement | null>(null)

  const headerDescription = React.useMemo(() => {
    if (isHistoryVisible && isActivityVisible) {
      return 'History + activity + prompt input'
    }

    if (isHistoryVisible) {
      return 'History + prompt input'
    }

    if (isActivityVisible) {
      return 'Activity + prompt input'
    }

    return 'Prompt input'
  }, [isActivityVisible, isHistoryVisible])

  const shouldExpandComposer = !isHistoryVisible || !isActivityVisible

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [history])

  return (
    <section className={cn('flex h-full min-h-0 flex-col bg-background', className)}>
      <PanelHeader
        icon={<History className='text-muted-foreground size-4' />}
        title='Agent Panel'
        description={headerDescription}
        borderBottom
      >
        <div className='flex items-center gap-1'>
          <Button
            type='button'
            size='xs'
            variant={isHistoryVisible ? 'secondary' : 'ghost'}
            aria-pressed={isHistoryVisible}
            onClick={onToggleHistoryVisibility}
          >
            History
          </Button>

          <Button
            type='button'
            size='xs'
            variant={isActivityVisible ? 'secondary' : 'ghost'}
            aria-pressed={isActivityVisible}
            onClick={onToggleActivityVisibility}
          >
            <Activity className='size-3.5' />
            Activity
          </Button>
        </div>
      </PanelHeader>

      <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
        {isHistoryVisible ? (
          <PromptHistorySection
            history={history}
            specName={specName}
            isProcessing={isProcessing}
            isLoadingSpec={isLoadingSpec}
            error={error}
            endRef={endRef}
          />
        ) : null}

        <PromptComposerSection
          primaryWorkspacePath={primaryWorkspacePath}
          secondaryWorkspacePath={secondaryWorkspacePath}
          specName={specName}
          specNameError={specNameError}
          promptMode={promptMode}
          isProcessing={isProcessing}
          isLoadingSpec={isLoadingSpec}
          onSpecNameChange={onSpecNameChange}
          onFetchSpecBundle={onFetchSpecBundle}
          onSubmit={onSubmit}
          shouldExpandComposer={shouldExpandComposer}
        />

        {isActivityVisible ? (
          <AgentActivitySection
            agentStatuses={agentStatuses}
            agentsMode={agentsMode}
            isAgentsLoading={isAgentsLoading}
            agentsError={agentsError}
          />
        ) : null}
      </div>
    </section>
  )
}

export default PromptPanel
