import {
  ChatContainerContent,
  ChatContainerScrollAnchor,
} from "@/shared/components/prompt-kit/chat-container"
import { ThinkingPanel } from "@/features/chat/components/ThinkingPanel"
import { ChatEmptyState } from "@/features/chat/components/ChatEmptyState"
import { ChatMessageItem } from "@/features/chat/components/ChatMessageItem"
import type { ChatStreamItem, OrchestratorTask } from "@/features/chat/types"

type ChatStreamContentProps = {
  streamItems: ChatStreamItem[]
  orchestratorTasks: OrchestratorTask[]
  isThinking: boolean
  statusText: string
}

export function ChatStreamContent({
  streamItems,
  orchestratorTasks,
  isThinking,
  statusText,
}: ChatStreamContentProps) {
  const hasStreamItems = streamItems.length > 0

  return (
    <ChatContainerContent className="mx-auto w-full max-w-4xl gap-4 p-4 mt-[72px]">
      {!hasStreamItems ? <ChatEmptyState /> : null}

      {streamItems.map((item, index) => {
        if (item.type === "thinking") {
          const isLastItem = index === streamItems.length - 1
          const shouldAnimate = isLastItem && isThinking

          return (
            <ThinkingPanel
              key={`thinking-${index}`}
              events={item.events}
              tasks={orchestratorTasks}
              isThinking={shouldAnimate}
              statusText={statusText}
            />
          )
        }

        return <ChatMessageItem key={item.message.id} message={item.message} />
      })}

      <ChatContainerScrollAnchor />
    </ChatContainerContent>
  )
}
