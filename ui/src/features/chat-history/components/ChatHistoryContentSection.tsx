import ChatHistoryTableSection from '@/features/chat-history/components/ChatHistoryTableSection'
import type { ConversationSummary } from '@/features/chat-history/types'

type ChatHistoryContentSectionProps = {
  conversations: ConversationSummary[]
  selectedIds: string[]
  allSelected: boolean
  isIndeterminate: boolean
  deleting: boolean
  loading: boolean
  onSelectAll: (checked: boolean) => void
  onSelectOne: (conversationId: string) => void
  onOpenConversation: (conversationId: string) => void
  onDeleteConversations: (ids: string[]) => void
  onRefresh: () => void
}

export default function ChatHistoryContentSection({
  conversations,
  selectedIds,
  allSelected,
  isIndeterminate,
  deleting,
  loading,
  onSelectAll,
  onSelectOne,
  onOpenConversation,
  onDeleteConversations,
  onRefresh,
}: ChatHistoryContentSectionProps) {
  if (loading) {
    return <p className='text-muted-foreground text-sm'>Loading history...</p>
  }

  if (conversations.length === 0) {
    return <p className='text-muted-foreground text-sm'>No conversations yet.</p>
  }

  return (
    <div className='min-h-0 flex-1 overflow-auto'>
      <ChatHistoryTableSection
        conversations={conversations}
        selectedIds={selectedIds}
        allSelected={allSelected}
        isIndeterminate={isIndeterminate}
        deleting={deleting}
        loading={loading}
        onSelectAll={onSelectAll}
        onSelectOne={onSelectOne}
        onOpenConversation={onOpenConversation}
        onDeleteConversations={onDeleteConversations}
        onRefresh={onRefresh}
      />
    </div>
  )
}
