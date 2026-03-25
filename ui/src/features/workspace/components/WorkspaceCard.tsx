import { CheckCircle2, FolderOpen, Github, Gitlab, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react"
import { Button } from "@/shared/components/ui/button"
import { Card, CardContent, CardHeader } from "@/shared/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/components/ui/dropdown-menu"
import { Chip } from "@/shared/components/chip"
import type { Workspace } from "../types"

interface WorkspaceCardProps {
  workspace: Workspace
  projectCount: number
  hasLinkedRepo?: boolean
  onSelect: () => void
  onActivate: () => void
  onEdit: () => void
  onDelete: () => void
  canAddGithubRepo?: boolean
  canAddGitlabRepo?: boolean
  onAddGithubRepo?: () => void
  onAddGitlabRepo?: () => void
}

export function WorkspaceCard({
  workspace,
  projectCount,
  hasLinkedRepo,
  onSelect,
  onActivate,
  onEdit,
  onDelete,
  canAddGithubRepo = false,
  canAddGitlabRepo = false,
  onAddGithubRepo,
  onAddGitlabRepo,
}: WorkspaceCardProps) {
  const isActive = workspace.is_active === 1
  const hasLinkedRepository = hasLinkedRepo ?? projectCount > 0
  const statusRingClass = isActive ? "ring-emerald-500/70" : "ring-border"

  return (
    <Card
      className={`cursor-pointer shadow-none hover:shadow-none transition-colors border-border ring-1 ${statusRingClass}`}
      onClick={onSelect}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start gap-2 min-w-0">
          <div className="size-8 flex items-center justify-center rounded-md bg-primary/10 text-primary shrink-0">
            <FolderOpen className="size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm truncate">{workspace.name}</span>
              {isActive && (
                <Chip color="success" variant="filled" className="text-xs shrink-0 gap-1 inline-flex">
                  <CheckCircle2 className="size-3" />
                  Active
                </Chip>
              )}
            </div>
            <p className="text-xs text-muted-foreground break-all mt-0.5">{workspace.path}</p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-0 flex items-end justify-between gap-2">
        <div className="min-w-0">
          {workspace.description && (
            <p className="text-xs text-muted-foreground mb-2 line-clamp-2">{workspace.description}</p>
          )}
          <p className="text-xs text-muted-foreground">
            {projectCount} {projectCount === 1 ? "project" : "projects"}
          </p>
          <div className="mt-2">
            <Chip
              color={hasLinkedRepository ? "success" : "warning"}
              variant="outline"
              className="text-[10px]"
            >
              {hasLinkedRepository ? "Git Linked" : "Pending Git Link"}
            </Chip>
          </div>
          {!hasLinkedRepository && projectCount === 0 && (canAddGithubRepo || canAddGitlabRepo) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {canAddGithubRepo && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1"
                  onClick={(e) => {
                    e.stopPropagation()
                    onAddGithubRepo?.()
                  }}
                >
                  <Plus className="size-3" />
                  <Github className="size-3" />
                  Add GitHub Repo
                </Button>
              )}
              {canAddGitlabRepo && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1"
                  onClick={(e) => {
                    e.stopPropagation()
                    onAddGitlabRepo?.()
                  }}
                >
                  <Plus className="size-3" />
                  <Gitlab className="size-3" />
                  Add GitLab Repo
                </Button>
              )}
            </div>
          )}
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="icon" className="size-7 shrink-0 self-end">
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {!isActive && (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation()
                  onActivate()
                }}
              >
                <CheckCircle2 className="size-4 mr-2" />
                Set as Active
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation()
                onEdit()
              }}
            >
              <Pencil className="size-4 mr-2" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
            >
              <Trash2 className="size-4 mr-2" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardContent>
    </Card>
  )
}
