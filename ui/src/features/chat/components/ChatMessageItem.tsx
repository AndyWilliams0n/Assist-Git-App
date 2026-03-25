import {
  Message,
  MessageAvatar,
  MessageContent,
} from "@/shared/components/prompt-kit/message"
import { Image } from "@/shared/components/prompt-kit/image"
import type { ChatMessage } from "@/features/chat/types"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

type ChatMessageItemProps = {
  message: ChatMessage
}

export function ChatMessageItem({ message }: ChatMessageItemProps) {
  const isUser = message.sender === "user"
  const attachments = message.attachments || []

  const formatFileSize = (sizeBytes: number) => {
    if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
      return ""
    }

    if (sizeBytes < 1024) {
      return `${sizeBytes} B`
    }

    const kb = sizeBytes / 1024
    if (kb < 1024) {
      return `${kb.toFixed(1)} KB`
    }

    const mb = kb / 1024
    return `${mb.toFixed(1)} MB`
  }

  return (
    <Message className={isUser ? "justify-end" : "justify-start"}>
      {!isUser ? <MessageAvatar src="" alt="Assistant" fallback="AI" /> : null}

      <div className="max-w-[80%] space-y-1">
        <MessageContent markdown>{message.text}</MessageContent>

        {attachments.length > 0 ? (
          <div className="flex gap-2 justify-end pt-1 space-y-2 text-end">
            {attachments.map((attachment) => {
              const isImage = attachment.mimeType.startsWith("image/")
              if (isImage && attachment.url) {
                return (
                  <a
                    key={`${API_BASE_URL}${attachment.url}`}
                    href={`${API_BASE_URL}${attachment.url}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block"
                  >
                    <Image
                      src={`${API_BASE_URL}${attachment.url}`}
                      alt={attachment.originalName}
                      className="max-h-[80px] w-auto border"
                    />
                  </a>
                )
              }

              return (
                <a
                  key={attachment.id}
                  href={attachment.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center rounded-md border bg-muted px-2 py-1 text-xs hover:bg-muted/80"
                >
                  {attachment.originalName}
                  {attachment.sizeBytes > 0 ? ` (${formatFileSize(attachment.sizeBytes)})` : ""}
                </a>
              )
            })}
          </div>
        ) : null}
      </div>

      {isUser ? <MessageAvatar src="" alt="You" fallback="ME" /> : null}
    </Message>
  )
}
