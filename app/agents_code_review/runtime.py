from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.agent_registry import make_agent_id, mark_agent_end, mark_agent_start
from app.db import add_orchestrator_event
from app.agents_code_builder.runtime import run_codex_exec
from app.workspace import run_command

_CODE_REVIEW_AGENT_ID = make_agent_id("agents", "Code Review Agent")


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _normalize_task_text(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\-\s*\[[ xX]\]\s*", "", text)
    text = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    text = " ".join(text.split())
    return text.lower()


def _mark_tasks_checked(tasks_path: str, checked_items: list[str]) -> int:
    path = Path(tasks_path).expanduser()
    if not path.exists() or not path.is_file():
        return 0

    normalized_targets = {_normalize_task_text(item) for item in checked_items if _normalize_task_text(item)}
    if not normalized_targets:
        return 0

    lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    changed_count = 0

    for line in lines:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if not stripped.startswith("- [ ]"):
            updated.append(line)
            continue

        candidate = _normalize_task_text(stripped)
        if candidate in normalized_targets:
            remainder = re.sub(r"^\-\s*\[\s\]\s*", "", stripped)
            updated.append(f"{indent}- [x] {remainder}")
            changed_count += 1
        else:
            updated.append(line)

    if changed_count > 0:
        path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return changed_count


def _extract_error_lines(build_output: str) -> list[str]:
    markers = ("error", "failed", "exception", "traceback", "fatal")
    lines: list[str] = []
    for raw in str(build_output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in markers):
            lines.append(line)
        if len(lines) >= 20:
            break
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return deduped


async def run_code_review_with_codex(
    workspace_path: str,
    spec_paths: dict[str, str],
    build_output: str,
    secondary_workspace_path: str | None = None,
    model: str | None = None,
    max_iterations: int = 3,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Execute Code Review Agent using Codex CLI and optionally update tasks.md."""
    workspace_root = Path(workspace_path).expanduser().resolve()
    tasks_path = str(spec_paths.get("tasks_path") or "").strip()
    requirements_path = str(spec_paths.get("requirements_path") or "").strip()
    design_path = str(spec_paths.get("design_path") or "").strip()
    secondary_workspace = str(secondary_workspace_path or "").strip()
    secondary_workspace_line = f"Secondary workspace root: {secondary_workspace}\n" if secondary_workspace else ""

    prompt = (
        "You are Code Review Codex validating an autonomous build attempt.\n"
        "Treat the secondary workspace as read-only reference context when provided.\n"
        "Review the build output and repository state and return JSON only with this schema:\n"
        '{"passed":true|false,"errors":["..."],"tasks_checked":["..."],"summary":"..."}.\n'
        "Rules:\n"
        "- passed=true only when build and tests are successful and no blocking issues remain.\n"
        "- errors must contain actionable blocking issues when passed=false.\n"
        "- tasks_checked should include only completed checklist items from tasks.md that are verified.\n"
        "- Do not mark uncertain work as complete.\n\n"
        f"Primary workspace root: {workspace_root}\n"
        f"{secondary_workspace_line}"
        f"Requirements file: {requirements_path or '(none)'}\n"
        f"Design file: {design_path or '(none)'}\n"
        f"Tasks file: {tasks_path or '(none)'}\n\n"
        "Build output:\n"
        f"{str(build_output or '')[:16000]}\n"
    )

    result = await asyncio.wait_for(
        asyncio.to_thread(
            run_codex_exec,
            prompt,
            workspace_root,
            model,
            timeout_seconds,
            agent_id=_CODE_REVIEW_AGENT_ID,
        ),
        timeout=float(timeout_seconds),
    )

    raw_payload = _extract_json(str(result.last_message or "")) or _extract_json(str(result.stdout or "")) or {}
    passed = bool(raw_payload.get("passed")) if raw_payload else False
    errors = [str(item).strip() for item in (raw_payload.get("errors") or []) if str(item).strip()] if raw_payload else []
    tasks_checked = [str(item).strip() for item in (raw_payload.get("tasks_checked") or []) if str(item).strip()] if raw_payload else []
    summary = str(raw_payload.get("summary") or "").strip() if raw_payload else ""

    if not raw_payload:
        inferred_errors = _extract_error_lines(build_output)
        passed = int(result.exit_code) == 0 and not inferred_errors
        errors = inferred_errors
        summary = (
            "Fallback review: used heuristic parsing because Code Review Codex did not return valid JSON."
        )

    if int(result.exit_code) != 0 and not errors:
        stderr = str(result.stderr or "").strip()
        if stderr:
            errors.append(stderr[:1000])

    changed_tasks = _mark_tasks_checked(tasks_path, tasks_checked) if tasks_path else 0
    if changed_tasks > 0:
        summary = (summary + f" Updated {changed_tasks} task checkbox(es) in tasks.md.").strip()

    return {
        "passed": passed,
        "errors": errors,
        "tasks_checked": tasks_checked,
        "summary": summary,
        "iteration_count": 1,
        "review_raw": str(result.last_message or result.stdout or ""),
    }


async def review_build_attempt(
    engine: Any,
    *,
    conversation_id: str,
    task_id: str,
    user_message: str,
    workspace: Any,
    combined_output: str,
    code_review_bypass: bool,
    secondary_workspace_path: str | None = None,
    spec_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    agent_error: str | None = None
    mark_agent_start(_CODE_REVIEW_AGENT_ID)
    try:
        return await _review_build_attempt(
            engine,
            conversation_id=conversation_id,
            task_id=task_id,
            user_message=user_message,
            workspace=workspace,
            combined_output=combined_output,
            code_review_bypass=code_review_bypass,
            secondary_workspace_path=secondary_workspace_path,
            spec_paths=spec_paths,
        )
    except Exception as exc:
        agent_error = str(exc)
        raise
    finally:
        mark_agent_end(_CODE_REVIEW_AGENT_ID, agent_error)


async def _review_build_attempt(
    engine: Any,
    *,
    conversation_id: str,
    task_id: str,
    user_message: str,
    workspace: Any,
    combined_output: str,
    code_review_bypass: bool,
    secondary_workspace_path: str | None = None,
    spec_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    git_status = await asyncio.to_thread(run_command, "git status --porcelain", workspace.root, 120, 12000)
    git_diff = await asyncio.to_thread(run_command, "git diff", workspace.root, 120, 36000)

    if code_review_bypass:
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=engine.code_reviewer.name,
            event_type="agent_bypassed",
            content="Code Review Agent bypass is enabled. Request passed to Orchestrator Agent.",
        )
        return {
            "passed": True,
            "notes": "Code Review Agent bypassed. Build output passed directly to orchestrator.",
            "fix_instructions": "",
            "review_raw": "Code Review Agent bypassed. Build output passed directly to orchestrator.",
        }

    # Primary path: Codex CLI-based review for stronger local validation.
    try:
        review_payload = await run_code_review_with_codex(
            workspace_path=str(workspace.root),
            spec_paths=spec_paths or {},
            build_output=(
                f"User request:\n{user_message}\n\n"
                f"CLI execution output:\n{combined_output[:12000]}\n\n"
                f"Git status:\n{git_status.stdout}\n\n"
                f"Git diff:\n{git_diff.stdout}\n{git_diff.stderr}\n"
            ),
            secondary_workspace_path=secondary_workspace_path,
            model=getattr(engine.code_reviewer, "model", None),
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=engine.code_reviewer.name,
            event_type="code_review",
            content=str(review_payload.get("review_raw") or str(review_payload))[:1800],
        )
        passed = bool(review_payload.get("passed"))
        errors = [str(item).strip() for item in (review_payload.get("errors") or []) if str(item).strip()]
        summary = str(review_payload.get("summary") or "").strip()
        return {
            "passed": passed,
            "notes": summary,
            "fix_instructions": "\n".join(errors),
            "review_raw": str(review_payload.get("review_raw") or ""),
        }
    except Exception:
        # Compatibility fallback: use existing LLM review behavior.
        secondary_context_line = (
            f"Secondary workspace root: {str(secondary_workspace_path).strip()}\n\n"
            if secondary_workspace_path
            else ""
        )
        review_prompt = (
            f"User request:\n{user_message}\n\n"
            f"{secondary_context_line}"
            f"CLI execution output:\n{combined_output[:12000]}\n\n"
            f"Git status:\n{git_status.stdout}\n\n"
            f"Git diff:\n{git_diff.stdout}\n{git_diff.stderr}\n\n"
            "Return JSON only."
        )
        review_raw = await engine._call(
            engine.code_reviewer,
            review_prompt,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        review_payload = engine._extract_json(review_raw) or {}
        passed = bool(review_payload.get("passed"))
        notes = str(review_payload.get("notes") or "").strip()
        fix_instructions = str(review_payload.get("fix_instructions") or "").strip()
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task_id,
            agent=engine.code_reviewer.name,
            event_type="code_review",
            content=review_raw[:1800],
        )
        return {
            "passed": passed,
            "notes": notes,
            "fix_instructions": fix_instructions,
            "review_raw": review_raw,
        }


__all__ = ["review_build_attempt", "run_code_review_with_codex"]
