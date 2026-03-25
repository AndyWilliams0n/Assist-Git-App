import * as React from "react"
import { ArrowUp, Loader2 } from "lucide-react"

import { PromptInput, PromptInputActions, PromptInputTextarea } from "@/shared/components/prompt-kit/prompt-input"
import { Button } from "@/shared/components/ui/button"

type SimplifiedChatInputProps = {
  onSubmit: (prompt: string) => Promise<void> | void
  isProcessing: boolean
  placeholder?: string
}

export function SimplifiedChatInput({
  onSubmit,
  isProcessing,
  placeholder = "Describe the spec you want to generate...",
}: SimplifiedChatInputProps) {
  const [value, setValue] = React.useState("")

  const handleSubmit = React.useCallback(async () => {
    const trimmed = value.trim()
    if (!trimmed || isProcessing) return

    await onSubmit(trimmed)
    setValue("")
  }, [isProcessing, onSubmit, value])

  return (
    <PromptInput
      value={value}
      onValueChange={setValue}
      onSubmit={() => {
        void handleSubmit()
      }}
      isLoading={isProcessing}
      disabled={isProcessing}
      className="w-full rounded-xl"
    >
      <PromptInputTextarea
        placeholder={placeholder}
        className="min-h-24 text-sm"
      />

      <PromptInputActions className="mt-2 justify-end">
        <Button
          type="button"
          onClick={() => {
            void handleSubmit()
          }}
          size="icon-sm"
          className="rounded-full"
          disabled={isProcessing || value.trim().length === 0}
          aria-label="Send prompt"
        >
          {isProcessing ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
        </Button>
      </PromptInputActions>
    </PromptInput>
  )
}

export default SimplifiedChatInput
