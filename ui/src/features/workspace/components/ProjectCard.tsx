import {
  CheckCircle2,
  CircleDashed,
  Download,
  ExternalLink,
  GitBranch,
  MoreHorizontal,
  Star,
  Trash2,
} from "lucide-react"
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
import { obfuscateSecretsInText, sanitizeUrlForNavigation } from "@/shared/utils/secret-sanitizer"
import type { WorkspaceProject } from "../types"

interface ProjectCardProps {
  project: WorkspaceProject
  onClone: () => void
  onRemove: () => void
  isCloning?: boolean
}

export function ProjectCard({ project, onClone, onRemove, isCloning }: ProjectCardProps) {
  const isCloned = project.is_cloned === 1
  const platformLabel = project.platform.charAt(0).toUpperCase() + project.platform.slice(1)
  const safeRemoteUrl = sanitizeUrlForNavigation(project.remote_url)

  return (
    <Card className="group shadow-none hover:shadow-none h-full">
      <CardHeader className="pb-2">
        <div className="flex items-start gap-2 min-w-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Chip
                color={project.platform === "github" ? "black" : project.platform === "gitlab" ? "warning" : "grey"}
                variant="filled"
                className={project.platform === "gitlab" ? "text-white border-orange-600 bg-orange-600" : ""}
              >
                {platformLabel}
              </Chip>
              <span className="font-medium text-sm truncate">{project.name}</span>
            </div>
            <p className="text-xs text-muted-foreground break-all mt-0.5">{obfuscateSecretsInText(project.remote_url)}</p>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-7 shrink-0 ml-auto opacity-100 md:opacity-0 md:group-hover:opacity-100">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <a href={safeRemoteUrl} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="size-4 mr-2" />
                  Open in Browser
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={onRemove}>
                <Trash2 className="size-4 mr-2" />
                Remove
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-2">
        {project.description && (
          <p className="text-xs text-muted-foreground line-clamp-2">{project.description}</p>
        )}

        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {project.language && <span>{project.language}</span>}
          {project.stars > 0 && (
            <span className="flex items-center gap-1">
              <Star className="size-3" />
              {project.stars.toLocaleString()}
            </span>
          )}
          {(project.branch || project.is_cloned === 1) && (
            <span className="flex items-center gap-1">
              <GitBranch className="size-3" />
              {project.branch || "main"}
            </span>
          )}
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs">
            {isCloned ? (
              <Chip color="success" variant="outline" className="gap-1 inline-flex">
                <CheckCircle2 className="size-3 text-green-500" />
                Cloned
              </Chip>
            ) : (
              <Chip color="grey" variant="outline" className="gap-1 inline-flex">
                <CircleDashed className="size-3" />
                Not cloned
              </Chip>
            )}
          </div>

          {!isCloned && (
            <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={onClone} disabled={isCloning}>
              <Download className="size-3" />
              {isCloning ? "Cloning..." : "Clone"}
            </Button>
          )}
        </div>

        <p className="text-xs text-muted-foreground break-all">{project.local_path}</p>
      </CardContent>
    </Card>
  )
}
