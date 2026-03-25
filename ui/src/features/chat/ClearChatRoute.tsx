import { useEffect } from "react"
import { useNavigate } from "react-router-dom"

import { useChatStore } from "@/features/chat/store/chat-store"

export default function ClearChatRoute() {
  const navigate = useNavigate()
  const clearChat = useChatStore((state) => state.clearChat)

  useEffect(() => {
    clearChat()
    navigate("/chat", { replace: true })
  }, [clearChat, navigate])

  return null
}
