import { useEffect, useState } from "react"
import { Plus, Ticket } from "lucide-react"

import { Button } from "@/shared/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"

type AvailableTicket = {
  key: string
  title: string
  status?: string
}

type AddTicketMenuProps = {
  onTicketSelected: (ticketKey: string) => void
  selectedTicketKeys: string[]
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ""

const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path
  }
  return `${API_BASE_URL}${path}`
}

export function AddTicketMenu({ onTicketSelected, selectedTicketKeys }: AddTicketMenuProps) {
  const [open, setOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tickets, setTickets] = useState<AvailableTicket[]>([])

  useEffect(() => {
    if (!open) {
      return
    }

    let cancelled = false

    const loadTickets = async () => {
      setIsLoading(true)
      setError(null)
      try {
        const response = await fetch(buildApiUrl("/api/tickets/available"))
        if (!response.ok) {
          throw new Error(`Request failed (${response.status})`)
        }
        const data = await response.json()
        const rawTickets = Array.isArray(data.tickets)
          ? (data.tickets as Array<Record<string, unknown>>)
          : []
        const nextTickets = rawTickets
          .map((item) => ({
            key: String(item?.key || "").trim().toUpperCase(),
            title: String(item?.title || "").trim() || "Untitled ticket",
            status: String(item?.status || "").trim(),
          }))
          .filter((item) => item.key)
        if (!cancelled) {
          setTickets(nextTickets)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load tickets")
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadTickets()

    return () => {
      cancelled = true
    }
  }, [open])

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="Add ticket">
          <Plus className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="min-w-56 rounded-xl">
        <DropdownMenuLabel>Add Context</DropdownMenuLabel>

        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Ticket className="h-4 w-4" />
            Add Workflow/Jira ticket
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="max-h-80 min-w-80 overflow-auto">
            {isLoading ? (
              <DropdownMenuItem disabled>Loading tickets...</DropdownMenuItem>
            ) : null}
            {error ? (
              <DropdownMenuItem disabled>{error}</DropdownMenuItem>
            ) : null}
            {!isLoading && !error && tickets.length === 0 ? (
              <DropdownMenuItem disabled>No tickets available</DropdownMenuItem>
            ) : null}
            {!isLoading && !error
              ? tickets.map((ticket) => {
                  const isSelected = selectedTicketKeys.includes(ticket.key)
                  return (
                    <DropdownMenuItem
                      key={ticket.key}
                      disabled={isSelected}
                      onSelect={(event) => {
                        event.preventDefault()
                        if (isSelected) {
                          return
                        }
                        onTicketSelected(ticket.key)
                      }}
                      className="flex flex-col items-start gap-0.5"
                    >
                      <span className="font-semibold">{ticket.key}</span>
                      <span className="text-muted-foreground max-w-[260px] truncate text-xs">{ticket.title}</span>
                      {ticket.status ? <span className="text-muted-foreground text-[10px]">{ticket.status}</span> : null}
                    </DropdownMenuItem>
                  )
                })
              : null}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
