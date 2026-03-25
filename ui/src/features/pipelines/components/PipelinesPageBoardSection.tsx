import PipelinesKanbanBoard from '@/features/pipelines/components/PipelinesKanbanBoard'
import type { PipelineBacklogItem, PipelineState, PipelineTask } from '@/features/pipelines/types'

type PipelinesPageBoardSectionProps = {
  state: PipelineState | null
  isLoading: boolean
  isMutating: boolean
  backlog: PipelineBacklogItem[]
  currentTasks: PipelineTask[]
  runningTasks: PipelineTask[]
  completeTasks: PipelineTask[]
  trackedKeys: Set<string>
  onSelectTaskId: (taskId: string | null) => void
  onQueueFromBacklog: (item: PipelineBacklogItem) => Promise<void>
  onReorderCurrentBefore: (movingTaskId: string, beforeTaskId: string) => Promise<void>
  onReorderCurrentToEnd: (movingTaskId: string) => Promise<void>
  onMoveTaskToBacklog: (taskId: string) => Promise<void>
  onReenableTask: (taskId: string) => Promise<void>
  onStopRunningTask: (taskId: string) => Promise<void>
  onAdminForceResetTask: (taskId: string) => Promise<void>
  onAdminForceCompleteTask: (taskId: string) => Promise<void>
  onEditTaskDetails: (task: PipelineTask) => void
  onActionError: (message: string) => void
}

export default function PipelinesPageBoardSection({
  state,
  isLoading,
  isMutating,
  backlog,
  currentTasks,
  runningTasks,
  completeTasks,
  trackedKeys,
  onSelectTaskId,
  onQueueFromBacklog,
  onReorderCurrentBefore,
  onReorderCurrentToEnd,
  onMoveTaskToBacklog,
  onReenableTask,
  onStopRunningTask,
  onAdminForceResetTask,
  onAdminForceCompleteTask,
  onEditTaskDetails,
  onActionError,
}: PipelinesPageBoardSectionProps) {
  if (isLoading && !state) {
    return <p className='text-muted-foreground text-sm'>Loading pipeline state...</p>
  }

  return (
    <PipelinesKanbanBoard
      backlog={backlog}
      currentTasks={currentTasks}
      runningTasks={runningTasks}
      completeTasks={completeTasks}
      trackedKeys={trackedKeys}
      isMutating={isMutating}
      onSelectTaskId={onSelectTaskId}
      onQueueFromBacklog={onQueueFromBacklog}
      onReorderCurrentBefore={onReorderCurrentBefore}
      onReorderCurrentToEnd={onReorderCurrentToEnd}
      onMoveTaskToBacklog={onMoveTaskToBacklog}
      onReenableTask={onReenableTask}
      onStopRunningTask={onStopRunningTask}
      onAdminForceResetTask={onAdminForceResetTask}
      onAdminForceCompleteTask={onAdminForceCompleteTask}
      onEditTaskDetails={onEditTaskDetails}
      onActionError={onActionError}
    />
  )
}
