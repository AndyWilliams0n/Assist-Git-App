import { useCallback, useEffect, useState } from "react"

import type { ConversationListResponse, ConversationSummary } from "@/features/chat-history/types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""
const apiPrefix = "/api"

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }

  return `${API_BASE_URL}${path}`
}

export const useHistoryData = () => {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadHistory = useCallback(async () => {
    setLoading(true)

    try {
      const response = await fetch(buildApiUrl(`${apiPrefix}/conversations?limit=100`))

      if (!response.ok) {
        throw new Error("Failed to load chat history")
      }

      const data = (await response.json()) as ConversationListResponse
      setConversations(data.conversations || [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load chat history")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  const deleteConversations = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) {
        return false
      }

      const confirmation = window.confirm(
        `Delete ${ids.length} conversation${ids.length === 1 ? "" : "s"}?`
      )

      if (!confirmation) {
        return false
      }

      setDeleting(true)

      try {
        const response = await fetch(buildApiUrl(`${apiPrefix}/conversations/delete`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        })

        if (!response.ok) {
          throw new Error("Failed to delete conversations")
        }

        await loadHistory()
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to delete conversations")
        return false
      } finally {
        setDeleting(false)
      }
    },
    [loadHistory]
  )

  return {
    conversations,
    loading,
    deleting,
    error,
    loadHistory,
    deleteConversations,
  }
}
