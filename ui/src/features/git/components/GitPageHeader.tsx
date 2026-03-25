import { GitBranch } from "lucide-react"

export function GitPageHeader() {
  return (
    <div className="flex items-center gap-3">
      <div className="size-9 flex items-center justify-center rounded-lg bg-primary/10 text-primary">
        <GitBranch className="size-5" />
      </div>

      <div>
        <h1 className="text-xl font-semibold">Git Management</h1>

        <p className="text-sm text-muted-foreground">
          Configure separate Git hooks for chat, automation, and SPEC automation workflows
        </p>
      </div>
    </div>
  )
}
