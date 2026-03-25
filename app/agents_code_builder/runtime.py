from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.agent_registry import mark_agent_end, mark_agent_start
from app.pipeline_store import add_pipeline_log
from app.workspace import ensure_workspace_bootstrap

_LOG_MAX_CHARS = 4000

CODEX_EXEC_TIMEOUT_SECONDS = int(os.getenv("CODEX_EXEC_TIMEOUT_SECONDS", "3600"))
CODEX_EXEC_MAX_OUTPUT = int(os.getenv("CODEX_EXEC_MAX_OUTPUT", "64000"))
CODEX_SKILLS_MAX_CHARS = int(os.getenv("CODEX_SKILLS_MAX_CHARS", "12000"))
CODEX_SKILLS_MAX_FILE_CHARS = int(os.getenv("CODEX_SKILLS_MAX_FILE_CHARS", "4000"))


@dataclass
class CodexExecResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    last_message: str


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _parse_skill_paths(raw_value: str) -> list[Path]:
    raw = str(raw_value or "").strip()
    if not raw:
        return []

    normalized = raw.replace("\n", ",")
    parts = _dedupe_preserving_order(part for part in normalized.split(","))
    paths: list[Path] = []
    cwd = Path.cwd()
    for part in parts:
        candidate = Path(part).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        paths.append(candidate.resolve())
    return paths


def build_codex_skills_prompt(
    raw_paths: str | None = None,
    max_chars: int = CODEX_SKILLS_MAX_CHARS,
    max_chars_per_file: int = CODEX_SKILLS_MAX_FILE_CHARS,
) -> str:
    configured_paths = raw_paths if raw_paths is not None else os.getenv("CODEX_SKILLS_PATHS", "")
    paths = _parse_skill_paths(configured_paths)
    if not paths:
        return ""

    total_limit = max(0, int(max_chars))
    per_file_limit = max(0, int(max_chars_per_file))
    if total_limit <= 0 or per_file_limit <= 0:
        return ""

    blocks: list[str] = []
    remaining = total_limit
    for path in paths:
        if remaining <= 0:
            break
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not content:
            continue
        content_cap = min(per_file_limit, remaining)
        excerpt = _truncate(content, content_cap)
        block = (
            f"### Skill Source: {path}\n"
            f"{excerpt}"
        )
        blocks.append(block)
        remaining -= len(block) + 2

    if not blocks:
        return ""

    return (
        "Project skill context (apply these instructions unless they conflict with higher-priority rules):\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
    )


def run_codex_exec(
    prompt: str,
    cwd: Path,
    model: str | None = None,
    timeout_seconds: int = CODEX_EXEC_TIMEOUT_SECONDS,
    max_output: int = CODEX_EXEC_MAX_OUTPUT,
    agent_id: str | None = None,
    sandbox_mode: str | None = None,
    bypass_approvals_and_sandbox: bool = True,
) -> CodexExecResult:
    start = time.time()
    workspace_cwd = Path(cwd).expanduser().resolve()
    if not workspace_cwd.exists():
        return CodexExecResult(
            command=f"codex exec --cd {workspace_cwd} -",
            exit_code=2,
            stdout="",
            stderr=f"Workspace path does not exist: {workspace_cwd}",
            duration_ms=int((time.time() - start) * 1000),
            last_message="",
        )
    if not workspace_cwd.is_dir():
        return CodexExecResult(
            command=f"codex exec --cd {workspace_cwd} -",
            exit_code=2,
            stdout="",
            stderr=f"Workspace path is not a directory: {workspace_cwd}",
            duration_ms=int((time.time() - start) * 1000),
            last_message="",
        )
    bootstrap = ensure_workspace_bootstrap(workspace_cwd)

    output_file = tempfile.NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False)
    output_file_path = Path(output_file.name)
    output_file.close()

    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(workspace_cwd),
        "--output-last-message",
        str(output_file_path),
        "--color",
        "never",
        "-",
    ]
    if bypass_approvals_and_sandbox:
        cmd.insert(3, "--dangerously-bypass-approvals-and-sandbox")
    elif sandbox_mode and str(sandbox_mode).strip():
        cmd.extend(["--sandbox", str(sandbox_mode).strip()])
    if model and str(model).strip():
        cmd.extend(["--model", str(model).strip()])

    if agent_id:
        mark_agent_start(agent_id)

    try:
        completed = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=workspace_cwd,
            env={
                **os.environ,
                "ASSIST_TEST_DIR": str(bootstrap.assist_test_dir),
                "TMPDIR": str(bootstrap.assist_test_tmp_dir),
                "TMP": str(bootstrap.assist_test_tmp_dir),
                "TEMP": str(bootstrap.assist_test_tmp_dir),
            },
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = int(completed.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        if not stderr:
            stderr = f"codex exec timed out after {timeout_seconds} seconds."
        exit_code = 124
    except FileNotFoundError:
        stdout = ""
        stderr = "codex CLI executable not found on PATH."
        exit_code = 127
    except Exception as exc:
        stdout = ""
        stderr = f"codex exec failed: {exc}"
        exit_code = 1

    last_message = ""
    try:
        if output_file_path.exists():
            last_message = output_file_path.read_text(encoding="utf-8")
    except Exception:
        last_message = ""
    finally:
        try:
            output_file_path.unlink(missing_ok=True)
        except Exception:
            pass

    duration_ms = int((time.time() - start) * 1000)
    command_preview = " ".join(cmd[:-1] + ["-"])
    agent_error = ""
    if int(exit_code) != 0:
        agent_error = str(stderr or f"codex exec exited with code {exit_code}").strip()

    label = agent_id or "codex"

    if last_message.strip():
        try:
            add_pipeline_log(
                level="info",
                message=f"[{label}] {last_message.strip()[:_LOG_MAX_CHARS]}",
            )
        except Exception:
            pass

    if int(exit_code) != 0 and stderr.strip():
        try:
            add_pipeline_log(
                level="error",
                message=f"[{label}] exit={exit_code}: {stderr.strip()[:_LOG_MAX_CHARS]}",
            )
        except Exception:
            pass

    if agent_id:
        mark_agent_end(agent_id, agent_error or None)

    return CodexExecResult(
        command=command_preview,
        exit_code=exit_code,
        stdout=_truncate(stdout, max_output),
        stderr=_truncate(stderr, max_output),
        duration_ms=duration_ms,
        last_message=_truncate(last_message, max_output),
    )
