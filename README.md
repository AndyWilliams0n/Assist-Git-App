# Assist-Git-App

Scoped replica focused on Workspace + Git flows.

## Project layout
- `app/`: FastAPI backend for workspace, git, and provider integrations.
- `ui/`: React + Vite + shadcn frontend exposing only `Workspace` and `Git`.

## Retained API surface
- `/health`
- `/api/git/*`
- `/api/workspaces*`
- `/api/github/*`
- `/api/gitlab/*`
- `/api/fs/tree`, `/api/fs/mkdir`, `/api/fs/rename`, `/api/fs/rmdir` (used by workspace folder picker)

Removed domains: Jira, pipelines/workflows/orchestrator, SDD/spec routes, Slack, and Stitch.

## Environment
- Frontend: configure `ui/.env` from `ui/.env.example` (`VITE_API_BASE_URL` required).
- Backend token resolution precedence:
1. Provider token saved in settings (`/api/github/settings`, `/api/gitlab/settings`)
2. Provider env vars (`GITHUB_TOKEN`, `GITLAB_TOKEN`)
3. Shared PAT env var (`GIT_SHARED_PAT`, optional alias `ASSIST_GIT_PAT`)

## CLI prerequisites
- `git` is required for workspace clone and git actions.
- `gh` and `glab` are optional but required for platform-specific PR/MR flows.
- Missing tools return explicit API errors with installation guidance.

## Repository hygiene
- Detect pycache-only directories in scoped roots:
  - `python3 scripts/cleanup_pycache_only_dirs.py --root .assist/specs/GIT-1-2 --root app --dry-run`
- Remove pycache-only directories in scoped roots:
  - `python3 scripts/cleanup_pycache_only_dirs.py --root .assist/specs/GIT-1-2 --root app --delete`
