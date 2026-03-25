import { useEffect } from "react"
import { useNavigate } from "react-router-dom"

import { usePromptsStore } from "@/features/prompts/store/prompts-store"

export default function ClearPromptRoute() {
  const navigate = useNavigate()
  const clearCurrentSpecId = usePromptsStore((state) => state.clearCurrentSpecId)

  useEffect(() => {
    clearCurrentSpecId()
    navigate("/prompt", { replace: true })
  }, [clearCurrentSpecId, navigate])

  return null
}
