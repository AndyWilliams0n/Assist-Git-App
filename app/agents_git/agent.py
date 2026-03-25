from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

from app.agent_registry import AgentDefinition, make_agent_id, register_agent


class GitAgent:
    def __init__(self) -> None:
        self.agent_id: str | None = None
        self._registered = False

    # ── Registration ────────────────────────────────────────────────────────

    def register(self) -> None:
        if self._registered:
            return
        agent_id = make_agent_id("agents", "Git Agent")
        self.agent_id = agent_id
        register_agent(
            AgentDefinition(
                id=agent_id,
                name="Git Agent",
                provider=None,
                model=None,
                group="agents",
                role="git_ops",
                kind="worker",
                enabled=self._git_available(),
                dependencies=[],
                source="app/agents_git/agent.py",
                description=(
                    "Manages git operations: detection, branching, commits, and PR/MR creation "
                    "via CLI (git, gh, glab)."
                ),
                capabilities=["git", "github", "gitlab", "version-control", "pull-request"],
            )
        )
        self._registered = True

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _git_available(self) -> bool:
        return shutil.which("git") is not None

    async def _run(
        self,
        cmd: list[str],
        cwd: str | None = None,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        """Run a subprocess command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        input_bytes = input_text.encode() if input_text is not None else None
        stdout, stderr = await proc.communicate(input_bytes)
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    def _platform_from_remote(self, remote_url: str) -> str:
        """Detect git platform from remote URL."""
        if "github.com" in remote_url:
            return "github"
        if "gitlab.com" in remote_url or "gitlab" in remote_url:
            return "gitlab"
        if "bitbucket" in remote_url:
            return "bitbucket"
        return "unknown"

    def _gh_available(self) -> bool:
        return shutil.which("gh") is not None

    def _glab_available(self) -> bool:
        return shutil.which("glab") is not None

    async def _build_untracked_diff(self, workspace: str) -> tuple[str, str | None]:
        list_code, list_out, list_err = await self._run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=workspace,
        )
        if list_code != 0:
            return "", list_err or "Failed to list untracked files"

        untracked_paths = [
            str(path or "").strip()
            for path in list_out.split("\0")
            if str(path or "").strip()
        ]
        if not untracked_paths:
            return "", None

        patches: list[str] = []
        for untracked_path in untracked_paths:
            diff_code, diff_out, diff_err = await self._run(
                ["git", "diff", "--no-index", "--", "/dev/null", untracked_path],
                cwd=workspace,
            )
            if diff_code not in (0, 1):
                return "", diff_err or f"Failed to generate diff for untracked file '{untracked_path}'"
            if diff_out:
                patches.append(diff_out)

        return "\n\n".join(patches), None

    async def _collect_outgoing_paths(
        self,
        workspace: str,
        remote: str,
        branch: str,
    ) -> tuple[list[str], str | None]:
        upstream_code, upstream_out, _ = await self._run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=workspace,
        )

        log_cmd: list[str]
        upstream_ref = str(upstream_out or "").strip()
        if upstream_code == 0 and upstream_ref:
            log_cmd = ["git", "log", "--name-only", "--pretty=format:", f"{upstream_ref}..HEAD"]
        else:
            remote_branch_ref = f"refs/remotes/{remote}/{branch}"
            remote_exists_code, _, _ = await self._run(
                ["git", "show-ref", "--verify", "--quiet", remote_branch_ref],
                cwd=workspace,
            )
            if remote_exists_code == 0:
                log_cmd = ["git", "log", "--name-only", "--pretty=format:", f"{remote}/{branch}..HEAD"]
            else:
                log_cmd = ["git", "log", "--name-only", "--pretty=format:", "HEAD", "--not", f"--remotes={remote}"]

        log_code, log_out, log_err = await self._run(log_cmd, cwd=workspace)
        if log_code != 0:
            return [], log_err or "Failed to inspect outgoing commit paths"

        outgoing_paths = sorted(
            {
                str(line or "").strip()
                for line in log_out.splitlines()
                if str(line or "").strip()
            }
        )
        return outgoing_paths, None

    async def _find_ignored_paths_in_outgoing_commits(
        self,
        workspace: str,
        remote: str,
        branch: str,
    ) -> tuple[list[str], str | None]:
        outgoing_paths, outgoing_err = await self._collect_outgoing_paths(workspace, remote, branch)
        if outgoing_err:
            return [], outgoing_err
        if not outgoing_paths:
            return [], None

        check_code, check_out, check_err = await self._run(
            ["git", "check-ignore", "--no-index", "--stdin"],
            cwd=workspace,
            input_text="\n".join(outgoing_paths),
        )
        if check_code not in (0, 1):
            return [], check_err or "Failed to evaluate .gitignore rules for outgoing commits"

        ignored_outgoing_paths = sorted(
            {
                str(line or "").strip()
                for line in check_out.splitlines()
                if str(line or "").strip()
            }
        )
        return ignored_outgoing_paths, None

    # ── Git Detection ─────────────────────────────────────────────────────────

    async def detect_git(self, workspace: str) -> dict[str, Any]:
        """Check whether the workspace is a git repository."""
        if not workspace:
            return {"is_git_repo": False, "error": "No workspace specified"}

        code, out, err = await self._run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=workspace
        )
        is_repo = code == 0 and out == "true"

        if not is_repo:
            return {"is_git_repo": False, "workspace": workspace}

        _, root, _ = await self._run(["git", "rev-parse", "--show-toplevel"], cwd=workspace)
        return {"is_git_repo": True, "workspace": workspace, "root": root}

    # ── Git Status ────────────────────────────────────────────────────────────

    async def get_status(self, workspace: str) -> dict[str, Any]:
        """Return full git status for the workspace."""
        detection = await self.detect_git(workspace)
        if not detection.get("is_git_repo"):
            return {**detection, "status": "not_a_git_repo"}

        # Current branch
        _, branch, _ = await self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
        )

        # Porcelain status
        _, porcelain, _ = await self._run(
            ["git", "status", "--porcelain"], cwd=workspace
        )
        modified = staged = untracked = 0
        for line in porcelain.splitlines():
            if not line:
                continue

            xy = line[:2]
            if xy[0] not in (" ", "?") and xy[0] != "!":
                staged += 1
            if xy[1] == "M" or xy[0] == "M":
                modified += 1
            if xy == "??":
                untracked += 1

        # Ahead/behind
        _, ahead_behind, _ = await self._run(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...@{{u}}"],
            cwd=workspace,
        )
        ahead = behind = 0
        if ahead_behind and "\t" in ahead_behind:
            parts = ahead_behind.split("\t")
            if len(parts) == 2:
                try:
                    ahead, behind = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

        # Remotes
        _, remote_out, _ = await self._run(["git", "remote", "-v"], cwd=workspace)
        remotes: list[dict[str, str]] = []
        seen: set[str] = set()
        for line in remote_out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in seen:
                seen.add(parts[0])
                remotes.append({"name": parts[0], "url": parts[1]})

        remote_url = remotes[0]["url"] if remotes else ""
        platform = self._platform_from_remote(remote_url)

        # Last commit
        _, log_out, _ = await self._run(
            ["git", "log", "-1", "--pretty=format:%H|%s|%an|%ar"], cwd=workspace
        )
        last_commit: dict[str, str] = {}
        if log_out:
            parts_log = log_out.split("|", 3)
            if len(parts_log) == 4:
                last_commit = {
                    "hash": parts_log[0][:8],
                    "message": parts_log[1],
                    "author": parts_log[2],
                    "when": parts_log[3],
                }

        return {
            "is_git_repo": True,
            "workspace": workspace,
            "branch": branch,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "ahead": ahead,
            "behind": behind,
            "remotes": remotes,
            "remote_url": remote_url,
            "platform": platform,
            "last_commit": last_commit,
            "gh_available": self._gh_available(),
            "glab_available": self._glab_available(),
        }

    # ── Branch Management ─────────────────────────────────────────────────────

    async def get_branches(self, workspace: str) -> dict[str, Any]:
        """List all local and remote branches."""
        _, local_out, _ = await self._run(
            ["git", "branch", "--format=%(refname:short)"], cwd=workspace
        )
        _, remote_out, _ = await self._run(
            ["git", "branch", "-r", "--format=%(refname:short)"], cwd=workspace
        )
        _, current, _ = await self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
        )

        local = [b.strip() for b in local_out.splitlines() if b.strip()]
        remote = [b.strip() for b in remote_out.splitlines() if b.strip()]

        return {
            "current": current,
            "local": local,
            "remote": remote,
        }

    async def create_branch(
        self,
        workspace: str,
        branch_name: str,
        base_branch: str | None = None,
        checkout: bool = True,
        reuse_existing: bool = True,
    ) -> dict[str, Any]:
        """Create a new branch, or reuse an existing one by checking it out."""
        # Idempotent branch setup is safer for pipeline reruns (e.g. branch pattern "{ticket}").
        # If the branch already exists locally, switch to it and continue.
        _, current_branch, _ = await self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
        )
        if reuse_existing and current_branch == branch_name:
            return {
                "success": True,
                "branch": branch_name,
                "created": False,
                "checked_out": True,
                "already_exists": True,
                "output": f"Already on branch '{branch_name}'",
                "error": None,
            }

        exists_code, _, _ = await self._run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=workspace,
        )
        if reuse_existing and exists_code == 0:
            if checkout:
                switch = await self.switch_branch(workspace, branch_name)
                return {
                    **switch,
                    "created": False,
                    "checked_out": bool(switch.get("success")),
                    "already_exists": True,
                }
            return {
                "success": True,
                "branch": branch_name,
                "created": False,
                "checked_out": False,
                "already_exists": True,
                "output": f"Branch '{branch_name}' already exists",
                "error": None,
            }

        if base_branch:
            cmd = ["git", "checkout", "-b", branch_name, base_branch]
        elif checkout:
            cmd = ["git", "checkout", "-b", branch_name]
        else:
            cmd = ["git", "branch", branch_name]

        code, out, err = await self._run(cmd, cwd=workspace)
        return {
            "success": code == 0,
            "branch": branch_name,
            "created": code == 0,
            "checked_out": bool(checkout and code == 0),
            "already_exists": False,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def switch_branch(self, workspace: str, branch_name: str) -> dict[str, Any]:
        """Switch to an existing branch."""
        code, out, err = await self._run(
            ["git", "checkout", branch_name], cwd=workspace
        )
        return {
            "success": code == 0,
            "branch": branch_name,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def delete_branch(
        self, workspace: str, branch_name: str, force: bool = False
    ) -> dict[str, Any]:
        """Delete a branch."""
        flag = "-D" if force else "-d"
        code, out, err = await self._run(
            ["git", "branch", flag, branch_name], cwd=workspace
        )
        return {
            "success": code == 0,
            "branch": branch_name,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def delete_remote_branch(
        self, workspace: str, branch_name: str, remote: str = "origin"
    ) -> dict[str, Any]:
        """Delete a branch from the remote."""
        normalized_remote = str(remote or "origin").strip() or "origin"
        normalized_branch = str(branch_name or "").strip()

        prefix = f"{normalized_remote}/"
        if normalized_branch.startswith(prefix):
            normalized_branch = normalized_branch[len(prefix):]

        if not normalized_branch:
            return {
                "success": False,
                "branch": normalized_branch,
                "remote": normalized_remote,
                "output": "",
                "error": "branch is required",
            }

        code, out, err = await self._run(
            ["git", "push", normalized_remote, "--delete", normalized_branch],
            cwd=workspace,
        )
        return {
            "success": code == 0,
            "branch": normalized_branch,
            "remote": normalized_remote,
            "output": out,
            "error": err if code != 0 else None,
        }

    # ── Stash ─────────────────────────────────────────────────────────────────

    async def stash(self, workspace: str, message: str | None = None) -> dict[str, Any]:
        """Stash uncommitted changes (including untracked files)."""
        cmd = ["git", "stash", "push", "--include-untracked"]

        if message:
            cmd += ["--message", message]

        code, out, err = await self._run(cmd, cwd=workspace)
        return {
            "success": code == 0,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def stash_pop(self, workspace: str) -> dict[str, Any]:
        """Pop the most recent stash entry."""
        code, out, err = await self._run(["git", "stash", "pop"], cwd=workspace)
        return {
            "success": code == 0,
            "output": out,
            "error": err if code != 0 else None,
        }

    # ── Commit ────────────────────────────────────────────────────────────────

    async def stage_all(self, workspace: str) -> dict[str, Any]:
        """Stage all changes."""
        code, out, err = await self._run(["git", "add", "."], cwd=workspace)
        return {
            "success": code == 0,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def commit(
        self,
        workspace: str,
        message: str,
        add_all: bool = True,
    ) -> dict[str, Any]:
        """Stage and commit changes."""
        if add_all:
            stage_result = await self.stage_all(workspace)
            if not stage_result["success"]:
                return stage_result

        # Treat an empty staged diff as a no-op success for idempotent pipeline reruns.
        # This avoids failing the ticket when the branch already contains the same changes.
        diff_code, _, diff_err = await self._run(
            ["git", "diff", "--cached", "--quiet", "--exit-code"], cwd=workspace
        )
        if diff_code == 0:
            return {
                "success": True,
                "message": message,
                "skipped": True,
                "reason": "nothing_to_commit",
                "output": "No staged changes to commit (working tree already committed).",
                "error": None,
            }
        if diff_code not in (0, 1):
            return {
                "success": False,
                "message": message,
                "output": "",
                "error": diff_err or "Failed to inspect staged changes before commit",
            }

        code, out, err = await self._run(
            ["git", "commit", "-m", message], cwd=workspace
        )
        return {
            "success": code == 0,
            "message": message,
            "skipped": False,
            "output": out,
            "error": err if code != 0 else None,
        }

    # ── Pull / Push / Rebase ──────────────────────────────────────────────────

    async def fetch(
        self,
        workspace: str,
        remote: str = "origin",
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Fetch latest refs from remote without mutating local working tree."""
        cmd = ["git", "fetch"]
        if remote:
            cmd.append(remote)
        if branch:
            cmd.append(branch)

        code, out, err = await self._run(cmd, cwd=workspace)
        return {
            "success": code == 0,
            "remote": remote,
            "branch": branch,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def pull(
        self,
        workspace: str,
        remote: str = "origin",
        branch: str | None = None,
        *,
        ff_only: bool = True,
        rebase: bool = False,
    ) -> dict[str, Any]:
        """Pull latest changes from a remote branch (or upstream branch)."""
        cmd = ["git", "pull"]
        if rebase:
            cmd.append("--rebase")
        elif ff_only:
            cmd.append("--ff-only")
        if remote:
            cmd.append(remote)
        if branch:
            cmd.append(branch)

        code, out, err = await self._run(cmd, cwd=workspace)
        return {
            "success": code == 0,
            "remote": remote,
            "branch": branch,
            "ff_only": ff_only and not rebase,
            "rebase": rebase,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def force_sync(
        self,
        workspace: str,
        remote: str = "origin",
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Force local branch to match remote by deleting untracked files and hard-resetting."""
        resolved_branch = str(branch or "").strip()
        if not resolved_branch:
            branch_code, branch_out, branch_err = await self._run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
            )
            if branch_code != 0:
                return {
                    "success": False,
                    "remote": remote,
                    "branch": "",
                    "step": "resolve_branch",
                    "output": branch_out,
                    "error": branch_err or "Failed to resolve current branch",
                }
            resolved_branch = branch_out.strip()

        fetch_code, fetch_out, fetch_err = await self._run(
            ["git", "fetch", remote, resolved_branch], cwd=workspace
        )
        if fetch_code != 0:
            return {
                "success": False,
                "remote": remote,
                "branch": resolved_branch,
                "step": "fetch",
                "output": fetch_out,
                "error": fetch_err or "Failed to fetch remote branch",
            }

        clean_code, clean_out, clean_err = await self._run(
            ["git", "clean", "-fd"], cwd=workspace
        )
        if clean_code != 0:
            return {
                "success": False,
                "remote": remote,
                "branch": resolved_branch,
                "step": "clean",
                "output": clean_out,
                "error": clean_err or "Failed to remove untracked files",
                "fetch": {"success": True, "output": fetch_out, "error": None},
            }

        reset_code, reset_out, reset_err = await self._run(
            ["git", "reset", "--hard", f"{remote}/{resolved_branch}"], cwd=workspace
        )
        return {
            "success": reset_code == 0,
            "remote": remote,
            "branch": resolved_branch,
            "step": "reset",
            "fetch": {"success": True, "output": fetch_out, "error": None},
            "clean": {"success": True, "output": clean_out, "error": None},
            "output": reset_out,
            "error": reset_err if reset_code != 0 else None,
        }

    async def rebase(
        self,
        workspace: str,
        *,
        base_branch: str = "main",
        remote: str = "origin",
        fetch_first: bool = True,
    ) -> dict[str, Any]:
        """Fetch the target branch and rebase the current branch onto it."""
        fetch_result: dict[str, Any] | None = None
        if fetch_first:
            fetch_code, fetch_out, fetch_err = await self._run(
                ["git", "fetch", remote, base_branch], cwd=workspace
            )
            fetch_result = {
                "success": fetch_code == 0,
                "remote": remote,
                "branch": base_branch,
                "output": fetch_out,
                "error": fetch_err if fetch_code != 0 else None,
            }
            if fetch_code != 0:
                return {
                    "success": False,
                    "remote": remote,
                    "base_branch": base_branch,
                    "step": "fetch",
                    "fetch": fetch_result,
                    "error": fetch_result.get("error"),
                    "output": fetch_result.get("output"),
                }

        code, out, err = await self._run(
            ["git", "rebase", f"{remote}/{base_branch}"], cwd=workspace
        )
        return {
            "success": code == 0,
            "remote": remote,
            "base_branch": base_branch,
            "fetch_first": fetch_first,
            "fetch": fetch_result,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def push(
        self,
        workspace: str,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = True,
    ) -> dict[str, Any]:
        """Push the current branch to remote."""
        resolved_branch = str(branch or "").strip()
        if not resolved_branch:
            branch_code, branch_out, branch_err = await self._run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
            )
            if branch_code != 0:
                return {
                    "success": False,
                    "remote": remote,
                    "branch": resolved_branch,
                    "step": "resolve_branch",
                    "output": branch_out,
                    "error": branch_err or "Failed to resolve current branch",
                }
            resolved_branch = str(branch_out or "").strip()

        ignored_paths, ignored_paths_err = await self._find_ignored_paths_in_outgoing_commits(
            workspace,
            remote,
            resolved_branch,
        )
        if ignored_paths_err:
            return {
                "success": False,
                "remote": remote,
                "branch": resolved_branch,
                "step": "validate_push",
                "output": "",
                "error": ignored_paths_err,
            }
        if ignored_paths:
            preview = ", ".join(ignored_paths[:5])
            extra_count = len(ignored_paths) - 5
            suffix = f" (+{extra_count} more)" if extra_count > 0 else ""
            return {
                "success": False,
                "remote": remote,
                "branch": resolved_branch,
                "step": "validate_push",
                "ignored_paths": ignored_paths,
                "output": "",
                "error": (
                    "Push blocked: outgoing commits include paths matched by .gitignore "
                    f"({preview}{suffix}). Remove these files from commit history before pushing."
                ),
            }

        cmd = ["git", "push", remote, resolved_branch]
        if set_upstream:
            cmd = ["git", "push", "-u", remote, resolved_branch]

        code, out, err = await self._run(cmd, cwd=workspace)
        return {
            "success": code == 0,
            "remote": remote,
            "branch": resolved_branch,
            "output": out,
            "error": err if code != 0 else None,
        }

    async def set_branch_description(
        self,
        workspace: str,
        description: str,
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Set the local git branch description in repository config."""
        resolved_branch = str(branch or "").strip()
        if not resolved_branch:
            branch_code, branch_out, branch_err = await self._run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace
            )
            if branch_code != 0:
                return {
                    "success": False,
                    "branch": resolved_branch,
                    "step": "resolve_branch",
                    "output": branch_out,
                    "error": branch_err or "Failed to resolve current branch",
                }
            resolved_branch = str(branch_out or "").strip()

        normalized_description = str(description or "").strip()
        if not normalized_description:
            return {
                "success": False,
                "branch": resolved_branch,
                "step": "validate_description",
                "output": "",
                "error": "Branch description is empty",
            }

        code, out, err = await self._run(
            ["git", "config", f"branch.{resolved_branch}.description", normalized_description],
            cwd=workspace,
        )
        return {
            "success": code == 0,
            "branch": resolved_branch,
            "output": out,
            "error": err if code != 0 else None,
        }

    # ── PR / MR Management ────────────────────────────────────────────────────

    async def list_prs(
        self, workspace: str, platform: str = "auto"
    ) -> dict[str, Any]:
        """List open PRs or MRs for the current repo."""
        resolved = await self._resolve_platform(workspace, platform)

        if resolved == "github" and self._gh_available():
            code, out, err = await self._run(
                ["gh", "pr", "list", "--json", "number,title,headRefName,baseRefName,state,url"],
                cwd=workspace,
            )
            if code == 0:
                import json

                try:
                    prs = json.loads(out)
                    return {"success": True, "platform": "github", "prs": prs}
                except Exception:
                    pass
            return {"success": False, "platform": "github", "error": err}

        if resolved == "gitlab" and self._glab_available():
            code, out, err = await self._run(
                ["glab", "mr", "list", "--output", "json"], cwd=workspace
            )
            if code == 0:
                import json

                try:
                    mrs = json.loads(out)
                    return {"success": True, "platform": "gitlab", "prs": mrs}
                except Exception:
                    pass
            return {"success": False, "platform": "gitlab", "error": err}

        return {
            "success": False,
            "platform": resolved,
            "error": f"CLI tool not available for platform '{resolved}'. Install gh or glab.",
        }

    async def create_pr(
        self,
        workspace: str,
        title: str,
        body: str = "",
        target_branch: str = "main",
        draft: bool = False,
        push_first: bool = True,
        platform: str = "auto",
        remote: str = "origin",
    ) -> dict[str, Any]:
        """Create a Pull Request (GitHub) or Merge Request (GitLab)."""
        resolved = await self._resolve_platform(workspace, platform)

        if push_first:
            push_result = await self.push(workspace, remote=remote)
            if not push_result["success"]:
                return {**push_result, "step": "push"}

        if resolved == "github" and self._gh_available():
            cmd = [
                "gh", "pr", "create",
                "--title", title,
                "--body", body,
                "--base", target_branch,
            ]
            if draft:
                cmd.append("--draft")
            code, out, err = await self._run(cmd, cwd=workspace)
            return {
                "success": code == 0,
                "platform": "github",
                "pr_url": out if code == 0 else None,
                "error": err if code != 0 else None,
            }

        if resolved == "gitlab" and self._glab_available():
            cmd = [
                "glab", "mr", "create",
                "--title", title,
                "--description", body,
                "--target-branch", target_branch,
                "--yes",
            ]
            if draft:
                cmd.append("--draft")
            code, out, err = await self._run(cmd, cwd=workspace)
            return {
                "success": code == 0,
                "platform": "gitlab",
                "mr_url": out if code == 0 else None,
                "error": err if code != 0 else None,
            }

        return {
            "success": False,
            "platform": resolved,
            "error": f"CLI tool not available for platform '{resolved}'. Install gh or glab.",
        }

    # ── Git Log / Diff ────────────────────────────────────────────────────────

    async def get_log(self, workspace: str, limit: int = 10) -> dict[str, Any]:
        """Return recent git log entries."""
        _, out, _ = await self._run(
            ["git", "log", f"-{limit}", "--pretty=format:%H|%s|%an|%ar|%d"],
            cwd=workspace,
        )
        commits = []
        for line in out.splitlines():
            parts = line.split("|", 4)
            if len(parts) >= 4:
                commits.append(
                    {
                        "hash": parts[0][:8],
                        "message": parts[1],
                        "author": parts[2],
                        "when": parts[3],
                        "refs": parts[4].strip() if len(parts) > 4 else "",
                    }
                )
        return {"commits": commits}

    async def get_diff(self, workspace: str, staged: bool = False) -> dict[str, Any]:
        """Return current diff output."""
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")

        _, out, _ = await self._run(cmd, cwd=workspace)

        if staged:
            return {"diff": out, "staged": staged}

        untracked_diff, untracked_err = await self._build_untracked_diff(workspace)
        if untracked_err:
            return {"diff": out, "staged": staged, "warning": untracked_err}

        combined_parts = [part for part in [out, untracked_diff] if part]
        return {"diff": "\n\n".join(combined_parts), "staged": staged}

    # ── External Tooling ──────────────────────────────────────────────────────

    async def open_in_cursor(self, workspace: str) -> dict[str, Any]:
        """Open the workspace path in Cursor."""
        normalized_workspace = str(workspace or "").strip()
        if not normalized_workspace:
            return {
                "success": False,
                "workspace": normalized_workspace,
                "error": "workspace is required",
            }

        workspace_path = Path(normalized_workspace).expanduser().resolve()
        if not workspace_path.exists() or not workspace_path.is_dir():
            return {
                "success": False,
                "workspace": str(workspace_path),
                "error": "workspace path does not exist or is not a directory",
            }

        commands: list[tuple[str, list[str]]] = []
        cursor_cli = shutil.which("cursor")
        if cursor_cli:
            commands.append(("cursor-cli", [cursor_cli, str(workspace_path)]))

        if sys.platform == "darwin":
            commands.append(("mac-open", ["open", "-a", "Cursor", str(workspace_path)]))

        if sys.platform.startswith("win"):
            commands.append(("windows-start", ["cmd", "/c", "start", "", "cursor", str(workspace_path)]))

        if not commands:
            return {
                "success": False,
                "workspace": str(workspace_path),
                "error": "Cursor launcher not found. Install the Cursor CLI or ensure Cursor is installed.",
            }

        attempted_methods: list[str] = []
        last_error = ""
        for method, command in commands:
            attempted_methods.append(method)
            code, _, err = await self._run(command, cwd=str(workspace_path))
            if code == 0:
                return {
                    "success": True,
                    "workspace": str(workspace_path),
                    "method": method,
                    "attempted_methods": attempted_methods,
                }
            if err:
                last_error = err

        return {
            "success": False,
            "workspace": str(workspace_path),
            "error": last_error or "Failed to open workspace in Cursor",
            "attempted_methods": attempted_methods,
        }

    async def open_in_files(self, workspace: str) -> dict[str, Any]:
        """Open the workspace path in Finder (macOS) or File Explorer (Windows)."""
        normalized_workspace = str(workspace or "").strip()
        if not normalized_workspace:
            return {
                "success": False,
                "workspace": normalized_workspace,
                "error": "workspace is required",
            }

        workspace_path = Path(normalized_workspace).expanduser().resolve()
        if not workspace_path.exists() or not workspace_path.is_dir():
            return {
                "success": False,
                "workspace": str(workspace_path),
                "error": "workspace path does not exist or is not a directory",
            }

        if sys.platform == "darwin":
            code, _, err = await self._run(["open", str(workspace_path)], cwd=str(workspace_path))
            if code == 0:
                return {
                    "success": True,
                    "workspace": str(workspace_path),
                    "method": "mac-open",
                }
            return {
                "success": False,
                "workspace": str(workspace_path),
                "error": err or "Failed to open Finder",
                "method": "mac-open",
            }

        if sys.platform.startswith("win"):
            code, _, err = await self._run(["explorer", str(workspace_path)], cwd=str(workspace_path))
            if code == 0:
                return {
                    "success": True,
                    "workspace": str(workspace_path),
                    "method": "windows-explorer",
                }
            return {
                "success": False,
                "workspace": str(workspace_path),
                "error": err or "Failed to open File Explorer",
                "method": "windows-explorer",
            }

        return {
            "success": False,
            "workspace": str(workspace_path),
            "error": "Open in Files is supported only on macOS and Windows",
            "method": "unsupported-platform",
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _resolve_platform(self, workspace: str, platform: str) -> str:
        """Resolve 'auto' platform by inspecting remote URL."""
        if platform != "auto":
            return platform

        _, remote_out, _ = await self._run(
            ["git", "remote", "get-url", "origin"], cwd=workspace
        )
        remote_url = str(remote_out or "").strip()

        if not remote_url:
            _, remotes_out, _ = await self._run(["git", "remote"], cwd=workspace)
            first_remote = next(
                (line.strip() for line in remotes_out.splitlines() if line.strip()),
                "",
            )
            if first_remote:
                _, fallback_remote_out, _ = await self._run(
                    ["git", "remote", "get-url", first_remote], cwd=workspace
                )
                remote_url = str(fallback_remote_out or "").strip()

        return self._platform_from_remote(remote_url)
