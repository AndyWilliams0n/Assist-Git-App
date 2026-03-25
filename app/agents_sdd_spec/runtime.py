from __future__ import annotations

import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Any

from app.agent_registry import (
    AgentDefinition,
    make_agent_id,
    mark_agent_end,
    mark_agent_start,
    register_agent,
)
from app.agents_code_builder.runtime import run_codex_exec
from app.pipeline_store import add_pipeline_log
from app.ticket_context import TicketContext

from .config import CONFIG

logger = logging.getLogger(__name__)
_AGENT_GROUP = "codex"
_SDD_SPEC_AGENT_ID = make_agent_id(_AGENT_GROUP, CONFIG.name)
_CODE_BUILDER_AGENT_ID = make_agent_id(_AGENT_GROUP, "Code Builder Codex")


def sdd_spec_agent_enabled() -> bool:
    value = str(os.getenv("ENABLE_SDD_SPEC_AGENT", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def register_sdd_spec_agent(
    *,
    group: str,
    dependency_ids: list[str] | None = None,
    model: str | None = None,
) -> str:
    agent_id = make_agent_id(group, CONFIG.name)
    register_agent(
        AgentDefinition(
            id=agent_id,
            name=CONFIG.name,
            provider=CONFIG.provider,
            model=model,
            group=group,
            role="sdd_spec",
            kind="subagent",
            dependencies=list(dependency_ids or []),
            source="app/agents_sdd_spec/runtime.py",
            description="Generates requirements.md, design.md, and tasks.md from task and ticket context.",
            capabilities=["sdd", "spec_generation", "codex_cli", "codebase_research"],
        )
    )
    return agent_id


def _ticket_context_to_text(ticket_context: TicketContext | None) -> str:
    if not ticket_context:
        return "(none)"
    return json.dumps(ticket_context.to_dict(), ensure_ascii=False, indent=2)


def _normalize_output_dir(workspace_path: str, output_dir: str) -> Path:
    workspace_root = Path(workspace_path).expanduser().resolve()
    out = Path(output_dir).expanduser()
    if not out.is_absolute():
        out = (workspace_root / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _validate_spec_paths(requirements_path: Path, design_path: Path, tasks_path: Path) -> None:
    missing: list[str] = []
    for path in (requirements_path, design_path, tasks_path):
        if not path.exists() or not path.is_file():
            missing.append(str(path))
    if missing:
        raise RuntimeError("SDD Spec Agent did not create required files: " + ", ".join(missing))


async def run_sdd_spec_agent(
    task_prompt: str,
    ticket_context: TicketContext | None,
    workspace_path: str,
    output_dir: str,
    model: str | None = None,
    *,
    memory_text: str = "",
) -> dict[str, str]:
    """Execute SDD Spec Agent to create a complete SDD bundle."""
    agent_error: str | None = None
    mark_agent_start(_SDD_SPEC_AGENT_ID)
    try:
        workspace_root = Path(workspace_path).expanduser().resolve()
        out_dir = _normalize_output_dir(str(workspace_root), output_dir)

        requirements_path = out_dir / "requirements.md"
        design_path = out_dir / "design.md"
        tasks_path = out_dir / "tasks.md"

        prompt = (
            "You are the SDD Spec Agent running inside the project workspace.\n"
            "Your objective is to produce a comprehensive SDD bundle for implementation.\n\n"
            "Research workflow requirements:\n"
            "- Inspect the repository structure before writing specs.\n"
            "- Identify likely impacted modules, shared components, and tests.\n"
            "- Use fast local search commands (for example: rg --files, rg <pattern>).\n"
            "- If MCP tooling is available in this workspace, use it for deeper codebase understanding.\n\n"
            "Output contract:\n"
            f"- Write requirements to: {requirements_path}\n"
            f"- Write design to: {design_path}\n"
            f"- Write tasks to: {tasks_path}\n"
            "- tasks.md must use markdown checkboxes.\n"
            "- Include ticket-driven acceptance criteria when provided.\n"
            "- Include references to attachments/figma links/local assets when relevant.\n"
            "- Do not ask questions; make reasonable assumptions and record them.\n"
            "- At the end, return JSON only: "
            '{"requirements_path":"...","design_path":"...","tasks_path":"...","status":"success|failed","error":"..."}\n\n'
            f"Task prompt:\n{task_prompt.strip()}\n\n"
            f"Ticket context:\n{_ticket_context_to_text(ticket_context)}\n\n"
            f"Recent memory:\n{(memory_text or '(none)').strip()}\n"
        )

        try:
            result = await asyncio.to_thread(
                run_codex_exec,
                prompt,
                workspace_root,
                model,
                agent_id=_CODE_BUILDER_AGENT_ID,
            )
        except Exception as exc:
            agent_error = str(exc).strip() or type(exc).__name__
            raise

        if int(result.exit_code) != 0:
            stderr_snippet = (result.stderr or "")[:2000]
            logger.warning(
                "SDD Spec Agent codex exec exited non-zero: exit=%s stderr=%s",
                result.exit_code,
                stderr_snippet,
            )
            add_pipeline_log(
                level='warning',
                message=f'SDD Spec Agent codex exec exited non-zero (exit={result.exit_code}): {stderr_snippet}',
            )

        try:
            _validate_spec_paths(requirements_path, design_path, tasks_path)
        except Exception as exc:
            logger.error("SDD Spec Agent failed to generate required files: %s", exc)
            add_pipeline_log(
                level='error',
                message=f'SDD Spec Agent failed to generate required files: {exc}',
            )
            agent_error = str(exc).strip() or type(exc).__name__
            return {
                "requirements_path": str(requirements_path),
                "design_path": str(design_path),
                "tasks_path": str(tasks_path),
                "status": "failed",
                "error": str(exc),
            }

        payload: dict[str, Any] = {}
        raw = str(result.last_message or "").strip()
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}

        status = str(payload.get("status") or "success").strip().lower()
        error = str(payload.get("error") or "").strip()
        if status != "success" and not error:
            error = (result.stderr or "SDD Spec Agent reported failure").strip()[:4000]

        if status != "success" and error:
            agent_error = error

        return {
            "requirements_path": str(requirements_path),
            "design_path": str(design_path),
            "tasks_path": str(tasks_path),
            "status": "success" if status == "success" else "failed",
            "error": error,
        }
    finally:
        mark_agent_end(_SDD_SPEC_AGENT_ID, agent_error or None)


__all__ = [
    "register_sdd_spec_agent",
    "run_sdd_spec_agent",
    "sdd_spec_agent_enabled",
]
