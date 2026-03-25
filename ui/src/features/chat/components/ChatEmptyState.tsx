import { TextShimmer } from "@/shared/components/prompt-kit/text-shimmer"

export function ChatEmptyState() {
  return (
    <div className="flex min-h-[220px] flex-1 flex-col items-center justify-center gap-2">
      <TextShimmer className="text-2xl">Get started with Coding Agent today...</TextShimmer>
      <p className="text-muted-foreground text-sm">
        Ask a question to start a new orchestrated run.
      </p>
    </div>
  )
}
