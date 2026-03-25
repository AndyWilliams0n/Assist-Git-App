import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import ChatHistoryContentSection from '@/features/chat-history/components/ChatHistoryContentSection'
import ChatHistoryHeaderSection from '@/features/chat-history/components/ChatHistoryHeaderSection'
import { useHistoryData } from '@/features/chat-history/hooks/useHistoryData'
import { useHistorySelection } from '@/features/chat-history/hooks/useHistorySelection'
import { useChatStore } from '@/features/chat/store/chat-store'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'

export default function ChatHistoryPage() {
  const navigate = useNavigate()

  const setBreadcrumbs = useDashboardSettingsStore((state) => state.setBreadcrumbs)
  const resetConversationState = useChatStore((state) => state.resetConversationState)

  const { conversations, loading, deleting, error, loadHistory, deleteConversations } = useHistoryData()

  const {
    selectedIds,
    allSelected,
    isIndeterminate,
    handleSelectAll,
    handleSelectOne,
    clearSelection,
  } = useHistorySelection(conversations)

  useEffect(() => {
    setBreadcrumbs([
      { label: 'Dashboard', href: '/' },
      { label: 'Chat', href: '/chat' },
      { label: 'History' },
    ])
  }, [setBreadcrumbs])

  useEffect(() => {
    if (error) {
      toast.error(error)
    }
  }, [error])

  const summaryCounts = useMemo(() => {
    const totalMessages = conversations.reduce(
      (sum, conversation) => sum + (conversation.message_count || 0),
      0
    )

    return { totalMessages }
  }, [conversations])

  const handleOpenConversation = (conversationId: string) => {
    resetConversationState()

    navigate(`/chat/${conversationId}`)
  }

  const handleDelete = async (ids: string[]) => {
    const deleted = await deleteConversations(ids)

    if (deleted) {
      clearSelection()
    }
  }

  const handleDeleteConversations = (ids: string[]) => {
    void handleDelete(ids)
  }

  const handleRefresh = () => {
    void loadHistory()
  }

  return (
    <div className='flex flex-1 min-h-0 w-full overflow-hidden'>
      <div className='flex flex-1 min-h-0 flex-col gap-4 p-6'>
        <ChatHistoryHeaderSection
          chatsCount={conversations.length}
          totalMessages={summaryCounts.totalMessages}
        />

        <ChatHistoryContentSection
          conversations={conversations}
          selectedIds={selectedIds}
          allSelected={allSelected}
          isIndeterminate={isIndeterminate}
          deleting={deleting}
          loading={loading}
          onSelectAll={handleSelectAll}
          onSelectOne={handleSelectOne}
          onOpenConversation={handleOpenConversation}
          onDeleteConversations={handleDeleteConversations}
          onRefresh={handleRefresh}
        />
      </div>
    </div>
  )
}
