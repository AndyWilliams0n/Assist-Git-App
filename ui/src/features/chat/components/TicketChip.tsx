import { Ticket, X } from "lucide-react"

import { Chip } from "@/shared/components/chip"

type TicketChipProps = {
  ticketKey: string
  title: string
  onRemove: () => void
}

export function TicketChip({ ticketKey, title, onRemove }: TicketChipProps) {
  const normalizedTitle = String(title || "").trim()
  const showTitle = normalizedTitle.length > 0 && normalizedTitle.toUpperCase() !== ticketKey.toUpperCase()

  return (
    <Chip
      color="warning"
      variant="outline"
      className="inline-flex max-w-full items-center gap-1.5 rounded-full px-3 py-1 text-xs"
    >
      <Ticket className="h-3 w-3 shrink-0" />
      <span className="max-w-[120px] truncate font-semibold">{ticketKey}</span>
      {showTitle ? <span className="max-w-[220px] truncate text-current/80">{normalizedTitle}</span> : null}
      <button
        type="button"
        onClick={onRemove}
        className="ml-0.5 rounded-sm text-current/70 hover:text-current focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-current/40"
        aria-label={`Remove ${ticketKey}`}
      >
        <X className="h-3 w-3" />
      </button>
    </Chip>
  )
}
