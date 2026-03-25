from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents_git import GitAgent
from app.agents_workspace.agent import WorkspaceAgent
from app.db import (
    create_workspace,
    create_workspace_project,
    delete_workspace,
    delete_workspace_project,
    get_active_workspace_config,
    init_db,
    list_workspace_projects,
    list_workspaces,
    set_active_workspace,
    set_active_workspace_config,
    update_workspace,
    update_workspace_project,
)
from app.fs_browser import create_directory, delete_empty_directory, list_tree_columns, rename_entry
from app.settings_store import (
    ensure_settings_file_exists,
    get_github_settings,
    get_github_token,
    get_github_username,
    get_git_workflow_settings,
    get_gitlab_settings,
    get_gitlab_token,
    get_gitlab_url,
    get_gitlab_username,
    update_github_settings,
    update_git_workflow_settings,
    update_gitlab_settings,
)

load_dotenv()

app = FastAPI(title="Assist Git API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

git_agent = GitAgent()
workspace_agent = WorkspaceAgent()


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    ensure_settings_file_exists()
    git_agent.register()
    workspace_agent.register()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


class GitBranchBody(BaseModel):
    workspace: str
    branch_name: str
    base_branch: str | None = None


class GitSwitchBranchBody(BaseModel):
    workspace: str
    branch: str


class GitFetchBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None


class GitPullBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None
    ff_only: bool = True
    rebase: bool = False


class GitPushBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None
    set_upstream: bool = True


class GitForceSyncBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None


class GitCommitBody(BaseModel):
    workspace: str
    message: str
    add_all: bool = True


class GitStashBody(BaseModel):
    workspace: str
    message: str | None = None


class GitOpenInCursorBody(BaseModel):
    workspace: str


class GitOpenInFilesBody(BaseModel):
    workspace: str


class GitPrBody(BaseModel):
    workspace: str
    title: str
    body: str = ""
    target_branch: str = "main"
    draft: bool = False
    push_first: bool = True
    platform: str = "auto"


class GitWorkflowConfigBody(BaseModel):
    workflows: dict[str, dict[str, object]] | None = None
    workflow_key: str | None = None
    phases: list[dict[str, object]] | None = None
    settings: dict[str, object] | None = None


PROTECTED_GIT_BRANCHES: set[str] = {"main", "master", "develop", "development", "dev"}


@app.get("/api/git/status")
async def git_status(workspace: str = "") -> dict:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_status(workspace)


@app.get("/api/git/status/stream")
async def git_status_stream(workspace: str = "") -> StreamingResponse:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")

    async def event_generator():
        last_payload = ""
        try:
            while True:
                payload = json.dumps(await git_agent.get_status(workspace), sort_keys=True)
                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/git/workflow-config")
async def git_workflow_config_get() -> dict[str, object]:
    return get_git_workflow_settings()


@app.put("/api/git/workflow-config")
async def git_workflow_config_put(body: GitWorkflowConfigBody) -> dict[str, object]:
    return update_git_workflow_settings(
        workflows=body.workflows,
        workflow_key=body.workflow_key,
        phases=body.phases,
        workflow_settings=body.settings,
    )


@app.get("/api/git/branches")
async def git_branches(workspace: str = "") -> dict:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")
    return await git_agent.get_branches(workspace)


@app.post("/api/git/branch")
async def git_create_branch(body: GitBranchBody) -> dict:
    return await git_agent.create_branch(body.workspace, body.branch_name, body.base_branch)


@app.patch("/api/git/branch")
async def git_switch_branch(body: GitSwitchBranchBody) -> dict:
    workspace = body.workspace.strip()
    branch = body.branch.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")
    if not branch:
        raise HTTPException(status_code=400, detail="branch is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.switch_branch(workspace, branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to switch branch")

    return {"ok": True, "git": result}


@app.delete("/api/git/branch")
async def git_delete_branch(
    workspace: str = "",
    branch: str = "",
    remote: bool = False,
    force: bool = False,
    remote_name: str = "origin",
) -> dict:
    normalized_workspace = workspace.strip()
    normalized_branch = branch.strip()
    normalized_remote_name = remote_name.strip() or "origin"

    if not normalized_workspace:
        raise HTTPException(status_code=400, detail="workspace is required")
    if not normalized_branch:
        raise HTTPException(status_code=400, detail="branch is required")

    if remote and normalized_branch.startswith(f"{normalized_remote_name}/"):
        normalized_branch = normalized_branch[len(normalized_remote_name) + 1 :]

    if not normalized_branch:
        raise HTTPException(status_code=400, detail="branch is required")

    if normalized_branch.lower() in PROTECTED_GIT_BRANCHES:
        raise HTTPException(status_code=400, detail="Protected branches cannot be deleted from this view")

    detection = await git_agent.detect_git(normalized_workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    current_branch = str(detection.get("branch") or "").strip()
    if normalized_branch == current_branch:
        raise HTTPException(status_code=400, detail="Cannot delete the currently checked-out branch")

    if remote:
        result = await git_agent.delete_remote_branch(
            normalized_workspace,
            normalized_branch,
            remote=normalized_remote_name,
        )
    else:
        result = await git_agent.delete_branch(normalized_workspace, normalized_branch, force=force)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to delete branch")

    return {"ok": True, "git": result}


@app.post("/api/git/fetch")
async def git_fetch(body: GitFetchBody) -> dict:
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.fetch(workspace=workspace, remote=remote, branch=branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to fetch latest changes")

    return {"ok": True, "git": result}


@app.post("/api/git/pull")
async def git_pull(body: GitPullBody) -> dict:
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.pull(
        workspace=workspace,
        remote=remote,
        branch=branch,
        ff_only=bool(body.ff_only),
        rebase=bool(body.rebase),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to pull latest changes")

    return {"ok": True, "git": result}


@app.post("/api/git/push")
async def git_push(body: GitPushBody) -> dict:
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.push(
        workspace=workspace,
        remote=remote,
        branch=branch,
        set_upstream=bool(body.set_upstream),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to push branch")

    return {"ok": True, "git": result}


@app.post("/api/git/force-sync")
async def git_force_sync(body: GitForceSyncBody) -> dict:
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.force_sync(workspace=workspace, remote=remote, branch=branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to force sync branch")

    return {"ok": True, "git": result}


@app.post("/api/git/commit")
async def git_commit(body: GitCommitBody) -> dict:
    return await git_agent.commit(body.workspace, body.message, body.add_all)


@app.post("/api/git/stash")
async def git_stash(body: GitStashBody) -> dict:
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.stash(workspace, body.message)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to stash changes")

    return {"ok": True, **result}


@app.post("/api/git/stash/pop")
async def git_stash_pop(body: GitStashBody) -> dict:
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.stash_pop(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to pop stash")

    return {"ok": True, **result}


@app.post("/api/git/open-in-cursor")
async def git_open_in_cursor(body: GitOpenInCursorBody) -> dict:
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.open_in_cursor(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to open workspace in Cursor")

    return {"ok": True, **result}


@app.post("/api/git/open-in-files")
async def git_open_in_files(body: GitOpenInFilesBody) -> dict:
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.open_in_files(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to open workspace in Files")

    return {"ok": True, **result}


@app.get("/api/git/prs")
async def git_list_prs(workspace: str = "", platform: str = "auto") -> dict:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.list_prs(workspace, platform)


@app.post("/api/git/pr")
async def git_create_pr(body: GitPrBody) -> dict:
    return await git_agent.create_pr(
        workspace=body.workspace,
        title=body.title,
        body=body.body,
        target_branch=body.target_branch,
        draft=body.draft,
        push_first=body.push_first,
        platform=body.platform,
    )


@app.get("/api/git/log")
async def git_log(workspace: str = "", limit: int = 10) -> dict:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_log(workspace, limit)


@app.get("/api/git/diff")
async def git_diff(workspace: str = "", staged: bool = False) -> dict:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_diff(workspace, staged)


class WorkspaceCreateBody(BaseModel):
    name: str
    path: str
    description: str = ""


class WorkspaceUpdateBody(BaseModel):
    name: str | None = None
    path: str | None = None
    description: str | None = None


class ActiveWorkspaceConfigBody(BaseModel):
    primary_workspace_id: str
    secondary_workspace_id: str | None = None


class WorkspaceProjectCreateBody(BaseModel):
    remote_url: str
    local_path: str
    platform: str
    name: str
    description: str = ""
    language: str = ""
    stars: int = 0


class WorkspaceProjectSwitchBranchBody(BaseModel):
    branch: str


class WorkspaceProjectCloneBody(BaseModel):
    wipe_existing: bool = False


@app.get("/api/workspaces")
async def workspaces_list() -> dict:
    return {
        "workspaces": list_workspaces(),
        "active_workspace_config": get_active_workspace_config(),
    }


@app.get("/api/workspaces/active-config")
async def workspaces_active_config() -> dict:
    return get_active_workspace_config()


@app.put("/api/workspaces/active-config")
async def workspaces_set_active_config(body: ActiveWorkspaceConfigBody) -> dict:
    primary_workspace_id = str(body.primary_workspace_id or "").strip()
    if not primary_workspace_id:
        raise HTTPException(status_code=400, detail="primary_workspace_id is required")

    workspaces = list_workspaces()
    known_ids = {str(workspace.get("id") or "") for workspace in workspaces}
    if primary_workspace_id not in known_ids:
        raise HTTPException(status_code=404, detail="Primary workspace not found")

    secondary_workspace_id = str(body.secondary_workspace_id or "").strip() or None
    if secondary_workspace_id and secondary_workspace_id not in known_ids:
        raise HTTPException(status_code=404, detail="Secondary workspace not found")

    if secondary_workspace_id == primary_workspace_id:
        raise HTTPException(status_code=400, detail="Secondary workspace must be different from primary workspace")

    set_active_workspace(primary_workspace_id)
    return set_active_workspace_config(primary_workspace_id, secondary_workspace_id)


@app.post("/api/workspaces")
async def workspaces_create(body: WorkspaceCreateBody) -> dict:
    return create_workspace(name=body.name.strip(), path=body.path.strip(), description=body.description.strip())


@app.put("/api/workspaces/{workspace_id}")
async def workspaces_update(workspace_id: str, body: WorkspaceUpdateBody) -> dict:
    ws = update_workspace(workspace_id, name=body.name, path=body.path, description=body.description)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.delete("/api/workspaces/{workspace_id}")
async def workspaces_delete(workspace_id: str) -> dict:
    ok = delete_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"ok": True}


@app.patch("/api/workspaces/{workspace_id}/activate")
async def workspaces_activate(workspace_id: str) -> dict:
    ws = set_active_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.get("/api/workspaces/{workspace_id}/projects")
async def workspace_projects_list(workspace_id: str) -> dict:
    return {"projects": list_workspace_projects(workspace_id)}


@app.post("/api/workspaces/{workspace_id}/projects")
async def workspace_projects_create(workspace_id: str, body: WorkspaceProjectCreateBody) -> dict:
    return create_workspace_project(
        workspace_id=workspace_id,
        name=body.name.strip(),
        remote_url=body.remote_url.strip(),
        platform=body.platform.strip(),
        local_path=body.local_path.strip(),
        description=body.description.strip(),
        language=body.language.strip(),
        stars=body.stars,
    )


@app.delete("/api/workspaces/{workspace_id}/projects/{project_id}")
async def workspace_projects_delete(workspace_id: str, project_id: str) -> dict:
    ok = delete_workspace_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


@app.post("/api/workspaces/{workspace_id}/projects/{project_id}/clone")
async def workspace_projects_clone(
    workspace_id: str,
    project_id: str,
    body: WorkspaceProjectCloneBody | None = None,
) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    clone_url = str(proj["remote_url"])
    platform = str(proj.get("platform") or "").lower()

    if clone_url.startswith("https://"):
        if platform == "github":
            token = get_github_token()
            if token and "github.com" in clone_url:
                clone_url = clone_url.replace("https://", f"https://x-access-token:{quote(token, safe='')}@", 1)
        elif platform == "gitlab":
            token = get_gitlab_token()
            if token:
                clone_url = clone_url.replace("https://", f"https://oauth2:{quote(token, safe='')}@", 1)

    result = await workspace_agent.clone_repo(clone_url, proj["local_path"], wipe_existing=bool(body and body.wipe_existing))
    if result.get("success"):
        now = datetime.now(timezone.utc).isoformat()
        detected_branch = ""
        try:
            git_status_result = await git_agent.get_status(proj["local_path"])
            if git_status_result.get("is_git_repo"):
                detected_branch = str(git_status_result.get("branch") or "")
        except Exception:
            detected_branch = ""

        updated = update_workspace_project(project_id, is_cloned=1, cloned_at=now, branch=detected_branch)
        return {"ok": True, "project": updated, "message": result.get("message", "")}

    return {"ok": False, "error": result.get("error", "Clone failed")}


@app.get("/api/workspaces/{workspace_id}/projects/{project_id}/branches")
async def workspace_projects_branches(workspace_id: str, project_id: str) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("is_cloned"):
        raise HTTPException(status_code=422, detail="Project is not cloned")
    return await git_agent.get_branches(proj["local_path"])


@app.patch("/api/workspaces/{workspace_id}/projects/{project_id}/branch")
async def workspace_projects_switch_branch(
    workspace_id: str,
    project_id: str,
    body: WorkspaceProjectSwitchBranchBody,
) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("is_cloned"):
        raise HTTPException(status_code=422, detail="Project is not cloned")

    result = await git_agent.switch_branch(proj["local_path"], body.branch.strip())
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to switch branch")

    updated = update_workspace_project(project_id, branch=body.branch.strip())
    return {"ok": True, "project": updated, "git": result}


class GitHubSettingsBody(BaseModel):
    token: str | None = None
    username: str | None = None


@app.get("/api/github/settings")
async def github_get_settings() -> dict:
    return get_github_settings()


@app.put("/api/github/settings")
async def github_update_settings(body: GitHubSettingsBody) -> dict:
    return update_github_settings(token=body.token, username=body.username)


@app.get("/api/github/repos")
async def github_list_repos(page: int = 1, per_page: int = 30, search: str = "") -> dict:
    token = get_github_token()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub token not configured. Set GITHUB_TOKEN or GIT_SHARED_PAT, or configure via /api/github/settings.",
        )

    username = get_github_username()
    return await workspace_agent.list_github_repos(
        token=token,
        username=username,
        page=page,
        per_page=per_page,
        search=search,
    )


@app.get("/api/github/user")
async def github_get_user() -> dict:
    token = get_github_token()
    if not token:
        return {"success": False, "error": "GitHub token not configured"}
    return await workspace_agent.get_github_user(token)


class GitLabSettingsBody(BaseModel):
    token: str | None = None
    url: str | None = None
    username: str | None = None


@app.get("/api/gitlab/settings")
async def gitlab_get_settings() -> dict:
    return get_gitlab_settings()


@app.put("/api/gitlab/settings")
async def gitlab_update_settings(body: GitLabSettingsBody) -> dict:
    return update_gitlab_settings(token=body.token, url=body.url, username=body.username)


@app.get("/api/gitlab/repos")
async def gitlab_list_repos(page: int = 1, per_page: int = 30, search: str = "") -> dict:
    token = get_gitlab_token()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitLab token not configured. Set GITLAB_TOKEN or GIT_SHARED_PAT, or configure via /api/gitlab/settings.",
        )

    gitlab_url = get_gitlab_url()
    username = get_gitlab_username()
    return await workspace_agent.list_gitlab_repos(
        token=token,
        gitlab_url=gitlab_url,
        username=username,
        page=page,
        per_page=per_page,
        search=search,
    )


@app.get("/api/gitlab/user")
async def gitlab_get_user() -> dict:
    token = get_gitlab_token()
    if not token:
        return {"success": False, "error": "GitLab token not configured"}
    gitlab_url = get_gitlab_url()
    return await workspace_agent.get_gitlab_user(token, gitlab_url)


class FsTreeQuery(BaseModel):
    path: str | None = None
    include_files: bool = True
    show_hidden: bool = False


class FsMkdirBody(BaseModel):
    path: str
    name: str


class FsRenameBody(BaseModel):
    path: str
    name: str


class FsRmdirBody(BaseModel):
    path: str


@app.get("/api/fs/tree")
async def fs_tree(path: str | None = None, include_files: bool = True, show_hidden: bool = False) -> dict[str, object]:
    try:
        return list_tree_columns(path, include_files=include_files, show_hidden=show_hidden)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/mkdir")
async def fs_mkdir(body: FsMkdirBody) -> dict[str, object]:
    try:
        created = create_directory(body.path, body.name)
        return {"ok": True, "directory": created}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/rename")
async def fs_rename(body: FsRenameBody) -> dict[str, object]:
    try:
        renamed = rename_entry(body.path, body.name)
        return {"ok": True, "entry": renamed}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/rmdir")
async def fs_rmdir(body: FsRmdirBody) -> dict[str, object]:
    try:
        deleted = delete_empty_directory(body.path)
        return {"ok": True, "directory": deleted}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
