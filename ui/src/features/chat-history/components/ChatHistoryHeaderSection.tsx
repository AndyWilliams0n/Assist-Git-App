import { History } from 'lucide-react'

import { Chip } from '@/shared/components/chip'

type ChatHistoryHeaderSectionProps = {
  chatsCount: number
  totalMessages: number
}

export default function ChatHistoryHeaderSection({
  chatsCount,
  totalMessages,
}: ChatHistoryHeaderSectionProps) {
  return (
    <div className='space-y-2'>
      <div className='flex items-center gap-3'>
        <div className='flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary'>
          <History className='size-5' />
        </div>

        <div>
          <h1 className='text-xl font-semibold tracking-tight'>History</h1>

          <p className='text-muted-foreground text-sm'>
            Jump back into any previous chat thread. Selecting a conversation will load its
            messages.
          </p>
        </div>
      </div>

      <div className='flex flex-wrap gap-2'>
        <Chip color='grey' variant='outline'>
          {chatsCount} chats
        </Chip>

        <Chip color='grey' variant='outline'>
          {totalMessages} messages
        </Chip>
      </div>
    </div>
  )
}
