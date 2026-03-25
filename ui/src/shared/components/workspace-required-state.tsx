import { FolderOpen, type LucideIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { Card, CardContent } from "@/shared/components/ui/card"

type WorkspaceRequiredStateProps = {
  title?: string
  description?: string
  icon?: LucideIcon
}

const defaultTitle = "Choose a workspace first"
const defaultDescription =
  "Create a workspace and set it as the current workspace before using this page."

export function WorkspaceRequiredState({
  title = defaultTitle,
  description = defaultDescription,
  icon: Icon = FolderOpen,
}: WorkspaceRequiredStateProps) {
  return (
    <div className="flex min-h-full flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-2xl border-dashed">
        <CardContent className="flex flex-col items-center justify-center px-6 py-16 text-center sm:px-10">
          <Icon className="size-32 text-muted-foreground/20" aria-hidden="true" />
          <h1 className="mt-8 text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
            {description}
          </p>
          <Button asChild className="mt-8">
            <Link to="/workspace">Open Workspaces</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
