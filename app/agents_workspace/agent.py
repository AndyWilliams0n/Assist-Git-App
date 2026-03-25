from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from app.agent_registry import AgentDefinition, make_agent_id, register_agent
from app.workspace import ensure_workspace_bootstrap

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _github_request(path: str, token: str, params: dict | None = None) -> Any:
    """Synchronous GitHub REST API call (used in async context via executor)."""
    url = f"{_GITHUB_API}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "AI-Multi-Agent-Assistant/1.0")
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _gitlab_request(path: str, token: str, gitlab_url: str, params: dict | None = None) -> Any:
    """Synchronous GitLab REST API call (used in async context via executor)."""
    base = gitlab_url.rstrip("/")
    url = f"{base}/api/v4{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url)
    req.add_header("PRIVATE-TOKEN", token)
    req.add_header("User-Agent", "AI-Multi-Agent-Assistant/1.0")
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


class WorkspaceAgent:
    """Handles GitHub/GitLab repo listing and git clone operations."""

    def __init__(self) -> None:
        self.agent_id: str | None = None
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        agent_id = make_agent_id("agents", "Workspace Agent")
        self.agent_id = agent_id
        register_agent(
            AgentDefinition(
                id=agent_id,
                name="Workspace Agent",
                provider=None,
                model=None,
                group="agents",
                role="workspace",
                kind="worker",
                enabled=True,
                dependencies=[],
                source="app/agents_workspace/agent.py",
                description="Lists GitHub/GitLab repositories and clones them into local workspaces.",
                capabilities=["workspace", "github", "gitlab", "clone", "repositories"],
            )
        )
        self._registered = True

    # ------------------------------------------------------------------
    # GitHub
    # ------------------------------------------------------------------

    async def list_github_repos(
        self,
        token: str,
        username: str = "",
        page: int = 1,
        per_page: int = 30,
        search: str = "",
    ) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            if search:
                params: dict = {"q": f"{search} user:{username}" if username else search, "page": page, "per_page": per_page, "sort": "updated"}
                raw = await loop.run_in_executor(None, lambda: _github_request("/search/repositories", token, params))
                repos = raw.get("items", [])
            else:
                params = {"page": page, "per_page": per_page, "sort": "updated", "affiliation": "owner,collaborator,organization_member"}
                repos = await loop.run_in_executor(None, lambda: _github_request("/user/repos", token, params))

            normalized = [
                {
                    "id": r.get("id"),
                    "name": r.get("name", ""),
                    "full_name": r.get("full_name", ""),
                    "clone_url": r.get("clone_url", ""),
                    "ssh_url": r.get("ssh_url", ""),
                    "description": r.get("description") or "",
                    "language": r.get("language") or "",
                    "stars": r.get("stargazers_count", 0),
                    "is_private": r.get("private", False),
                    "updated_at": r.get("updated_at", ""),
                    "default_branch": r.get("default_branch", "main"),
                }
                for r in (repos if isinstance(repos, list) else [])
            ]
            return {"success": True, "repos": normalized, "page": page, "per_page": per_page}
        except HTTPError as exc:
            logger.warning("GitHub API error %s: %s", exc.code, exc.reason)
            return {"success": False, "error": f"GitHub API error {exc.code}: {exc.reason}", "repos": []}
        except URLError as exc:
            logger.warning("GitHub network error: %s", exc.reason)
            return {"success": False, "error": f"Network error: {exc.reason}", "repos": []}
        except Exception as exc:
            logger.exception("Unexpected GitHub error")
            return {"success": False, "error": str(exc), "repos": []}

    async def get_github_user(self, token: str) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: _github_request("/user", token))
            return {"success": True, "login": data.get("login", ""), "name": data.get("name", ""), "avatar_url": data.get("avatar_url", "")}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # GitLab
    # ------------------------------------------------------------------

    async def list_gitlab_repos(
        self,
        token: str,
        gitlab_url: str = "https://gitlab.com",
        username: str = "",
        page: int = 1,
        per_page: int = 30,
        search: str = "",
    ) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            params: dict = {"page": page, "per_page": per_page, "order_by": "last_activity_at", "sort": "desc", "membership": "true"}
            if search:
                params["search"] = search
            # List projects for the authenticated token directly. Relying on a configured
            # username here is brittle: a stale or incorrect username turns repo browsing
            # into a hard 404 even when the token itself is valid.
            repos = await loop.run_in_executor(None, lambda: _gitlab_request("/projects", token, gitlab_url, params))

            normalized = [
                {
                    "id": r.get("id"),
                    "name": r.get("name", ""),
                    "path_with_namespace": r.get("path_with_namespace", ""),
                    "http_url_to_repo": r.get("http_url_to_repo", ""),
                    "ssh_url_to_repo": r.get("ssh_url_to_repo", ""),
                    "description": r.get("description") or "",
                    "language": "",  # GitLab doesn't return language in list endpoint
                    "star_count": r.get("star_count", 0),
                    "visibility": r.get("visibility", "private"),
                    "updated_at": r.get("last_activity_at", ""),
                    "default_branch": r.get("default_branch", "main"),
                }
                for r in (repos if isinstance(repos, list) else [])
            ]
            return {"success": True, "repos": normalized, "page": page, "per_page": per_page}
        except HTTPError as exc:
            logger.warning("GitLab API error %s: %s", exc.code, exc.reason)
            return {"success": False, "error": f"GitLab API error {exc.code}: {exc.reason}", "repos": []}
        except URLError as exc:
            logger.warning("GitLab network error: %s", exc.reason)
            return {"success": False, "error": f"Network error: {exc.reason}", "repos": []}
        except Exception as exc:
            logger.exception("Unexpected GitLab error")
            return {"success": False, "error": str(exc), "repos": []}

    async def get_gitlab_user(self, token: str, gitlab_url: str = "https://gitlab.com") -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: _gitlab_request("/user", token, gitlab_url))
            return {"success": True, "username": data.get("username", ""), "name": data.get("name", ""), "avatar_url": data.get("avatar_url", "")}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Clone
    # ------------------------------------------------------------------

    async def clone_repo(self, remote_url: str, local_path: str, wipe_existing: bool = False) -> dict[str, Any]:
        """Clone a repository to a local path."""
        dest = Path(local_path)
        if wipe_existing and dest.exists():
            try:
                for p in list(dest.iterdir()):
                    if p.is_dir() and not p.is_symlink():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
            except OSError as exc:
                return {"success": False, "error": f"Failed to clear destination '{local_path}': {exc}"}

        if dest.exists() and any(dest.iterdir()):
            ignorable_files = {".DS_Store", "Thumbs.db", "desktop.ini"}
            # Remove harmless OS metadata files so "empty" folders from Finder/Explorer can still be used.
            for p in list(dest.iterdir()):
                if p.is_file() and p.name in ignorable_files:
                    try:
                        p.unlink()
                    except OSError:
                        pass

        if dest.exists() and any(dest.iterdir()):
            entries = [p.name for p in dest.iterdir()]
            # A previous failed clone can leave only `.git`; treat as incomplete, not success.
            if (dest / ".git").exists() and set(entries) == {".git"}:
                return {
                    "success": False,
                    "error": (
                        f"Destination path '{local_path}' contains only .git (incomplete clone). "
                        "Remove the folder and retry."
                    ),
                    "incomplete_clone": True,
                }
            # If already cloned (has .git plus working tree files), treat as success.
            if (dest / ".git").exists():
                ensure_workspace_bootstrap(dest)
                return {"success": True, "message": "Repository already cloned", "already_existed": True}
            preview = ", ".join(sorted(entries)[:8])
            suffix = " ..." if len(entries) > 8 else ""
            return {
                "success": False,
                "error": f"Destination path '{local_path}' exists and is not empty (contains: {preview}{suffix})",
            }

        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", remote_url, str(dest),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    # Never block waiting for terminal credentials in the API worker.
                    "GIT_TERMINAL_PROMPT": "0",
                    "GCM_INTERACTIVE": "Never",
                },
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode == 0:
                ensure_workspace_bootstrap(dest)
                return {"success": True, "message": f"Cloned to {local_path}", "already_existed": False}
            error_msg = stderr.decode().strip() or "Clone failed"
            return {"success": False, "error": error_msg}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Clone timed out after 5 minutes"}
        except FileNotFoundError:
            return {"success": False, "error": "git not found in PATH"}
        except Exception as exc:
            logger.exception("Clone error")
            return {"success": False, "error": str(exc)}
