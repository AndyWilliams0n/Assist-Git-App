import { useMemo, useState } from "react"

import type { ConversationSummary } from "@/features/chat-history/types"

export const useHistorySelection = (conversations: ConversationSummary[]) => {
  const [rawSelectedIds, setRawSelectedIds] = useState<string[]>([])
  const conversationIds = useMemo(
    () => new Set(conversations.map((conversation) => conversation.id)),
    [conversations]
  )
  const selectedIds = useMemo(
    () => rawSelectedIds.filter((id) => conversationIds.has(id)),
    [conversationIds, rawSelectedIds]
  )

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setRawSelectedIds(conversations.map((conversation) => conversation.id))
      return
    }

    setRawSelectedIds([])
  }

  const handleSelectOne = (conversationId: string) => {
    setRawSelectedIds((prev) =>
      prev.includes(conversationId)
        ? prev.filter((id) => id !== conversationId)
        : [...prev, conversationId]
    )
  }

  const clearSelection = () => {
    setRawSelectedIds([])
  }

  const allSelected = conversations.length > 0 && selectedIds.length === conversations.length
  const isIndeterminate = selectedIds.length > 0 && !allSelected

  return {
    selectedIds,
    allSelected,
    isIndeterminate,
    handleSelectAll,
    handleSelectOne,
    clearSelection,
  }
}
