from __future__ import annotations

import logging
import re
from typing import Any

from app.agent_registry import make_agent_id, mark_agent_end, mark_agent_start
from app.agents_sdd_spec.runtime import run_sdd_spec_agent, sdd_spec_agent_enabled
from app.jira_conversation_state import load_jira_conversation_state
from app.settings_store import get_agent_bypass_settings, get_agent_model
from app.ticket_context import TicketContext

_PLANNER_AGENT_ID = make_agent_id("orchestrator", "Planner Agent")

logger = logging.getLogger(__name__)


def sanitize_pipeline_stream_id(value: str, fallback: str = "chat") -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    sanitized = sanitized.strip("-.")
    if not sanitized:
        sanitized = fallback
    return sanitized[:120]


def normalize_plan_lines(value: Any) -> list[str]:
    raw_items: list[str] = []
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    elif isinstance(value, str):
        raw_items = value.splitlines()

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = " ".join(str(item or "").strip().split())
        text = re.sub(r"^[\-\*\d\.\[\]\(\)\s]+", "", text).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(text)
    return cleaned


def to_checkbox_lines(lines: list[str]) -> list[str]:
    checklist: list[str] = []
    for line in lines:
        text = " ".join(str(line or "").strip().split())
        text = re.sub(r"^\-\s*\[\s*[xX ]?\s*\]\s*", "", text).strip()
        if not text:
            continue
        checklist.append(f"- [ ] {text}")
    return checklist


def next_pipeline_version(workspace: Any, stream_id: str) -> int:
    base_dir = workspace.root / ".assist" / "pipeline" / stream_id
    max_version = 0
    if base_dir.exists():
        for child in base_dir.iterdir():
            if not child.is_dir():
                continue
            match = re.fullmatch(r"v(\d+)", child.name)
            if not match:
                continue
            max_version = max(max_version, int(match.group(1)))
    return max_version + 1


def _extract_primary_ticket_context(
    *,
    conversation_id: str,
    user_message: str,
    workspace: Any,
    selected_ticket_contexts: list[dict[str, Any]] | None = None,
) -> TicketContext | None:
    if selected_ticket_contexts:
        for item in selected_ticket_contexts:
            if isinstance(item, dict):
                ticket_payload = item.get("ticket_context") if isinstance(item.get("ticket_context"), dict) else item
                context = TicketContext.from_dict(ticket_payload)
                if context.ticket_key:
                    return context

    state = load_jira_conversation_state(workspace.root, conversation_id)
    if state.last_ticket_keys:
        key = str(state.last_ticket_keys[0] or "").strip().upper()
        if key:
            summary = str(state.normalized_implementation_brief_summary or "").strip() or user_message
            return TicketContext(
                ticket_key=key,
                title=key,
                description=summary,
            )
    return None


def _extract_tasks_markdown(tasks_path: str) -> str:
    try:
        lines = []
        with open(tasks_path, "r", encoding="utf-8") as handle:
            content = handle.read()
        for line in str(content).splitlines():
            text = line.strip()
            if text.startswith("- [ ]") or text.startswith("- [x]") or text.startswith("- [X]"):
                lines.append(text)
        return "\n".join(lines)
    except Exception:
        return ""


async def delegate_to_sdd_spec_agent(
    engine: Any,
    *,
    conversation_id: str,
    user_message: str,
    memory_text: str,
    workspace: Any,
    selected_ticket_contexts: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    agent_error: str | None = None
    mark_agent_start(_PLANNER_AGENT_ID)
    try:
        return await _delegate_to_sdd_spec_agent(
            engine,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
            selected_ticket_contexts=selected_ticket_contexts,
        )
    except Exception as exc:
        agent_error = str(exc)
        raise
    finally:
        mark_agent_end(_PLANNER_AGENT_ID, agent_error)


async def _delegate_to_sdd_spec_agent(
    engine: Any,
    *,
    conversation_id: str,
    user_message: str,
    memory_text: str,
    workspace: Any,
    selected_ticket_contexts: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    safe_chat_id = sanitize_pipeline_stream_id(conversation_id, fallback="chat")
    version = next_pipeline_version(workspace, safe_chat_id)
    relative_dir = f".assist/pipeline/{safe_chat_id}/v{version}"
    workspace.mkdir(relative_dir)

    if not sdd_spec_agent_enabled():
        return await write_chat_sdd_bundle(
            engine,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
        )

    bypass = get_agent_bypass_settings()
    if bool(bypass.get("sdd_spec")):
        return await write_chat_sdd_bundle(
            engine,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
        )

    ticket_context = _extract_primary_ticket_context(
        conversation_id=conversation_id,
        user_message=user_message,
        workspace=workspace,
        selected_ticket_contexts=selected_ticket_contexts,
    )

    try:
        spec_result = await run_sdd_spec_agent(
            task_prompt=user_message,
            ticket_context=ticket_context,
            workspace_path=str(workspace.root),
            output_dir=str(workspace.resolve_path(relative_dir)),
            model=get_agent_model("sdd_spec"),
            memory_text=memory_text,
        )
    except Exception as exc:
        logger.warning("Planner fallback to legacy SDD bundle after SDD Spec Agent error: %s", exc)
        return await write_chat_sdd_bundle(
            engine,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
        )

    if str(spec_result.get("status") or "").strip().lower() != "success":
        logger.warning(
            "Planner fallback to legacy SDD bundle because SDD Spec Agent returned failure: %s",
            spec_result.get("error"),
        )
        return await write_chat_sdd_bundle(
            engine,
            conversation_id=conversation_id,
            user_message=user_message,
            memory_text=memory_text,
            workspace=workspace,
        )

    tasks_path = str(spec_result.get("tasks_path") or "")
    return {
        "chat_id": safe_chat_id,
        "version": str(version),
        "requirements_path": str(spec_result.get("requirements_path") or ""),
        "design_path": str(spec_result.get("design_path") or ""),
        "tasks_path": tasks_path,
        "tasks_markdown": _extract_tasks_markdown(tasks_path),
    }


async def write_chat_sdd_bundle(
    engine: Any,
    *,
    conversation_id: str,
    user_message: str,
    memory_text: str,
    workspace: Any,
) -> dict[str, str]:
    safe_chat_id = sanitize_pipeline_stream_id(conversation_id, fallback="chat")
    version = next_pipeline_version(workspace, safe_chat_id)
    relative_dir = f".assist/pipeline/{safe_chat_id}/v{version}"
    workspace.mkdir(relative_dir)

    planning_prompt = (
        f"User request:\n{user_message}\n\n"
        f"Recent memory:\n{memory_text or '(none)'}\n\n"
        f"Workspace snapshot:\n{workspace.list_tree('.', max_depth=3)}\n\n"
        "Create a comprehensive Spec-Driven Development planning bundle. "
        "Return JSON only with exactly this schema:\n"
        "{\n"
        '  "requirements": ["..."],\n'
        '  "design": ["..."],\n'
        '  "tasks": ["..."],\n'
        '  "assumptions": ["..."],\n'
        '  "risks": ["..."]\n'
        "}\n"
        "Rules:\n"
        "- requirements: concrete functional + verification requirements.\n"
        "- design: implementation approach, architecture notes, and constraints.\n"
        "- tasks: executable steps that can be turned into a checklist.\n"
        "- Capture unresolved assumptions and key risks."
    )
    planner_output = await engine._call(engine.planner, planning_prompt, conversation_id=conversation_id)
    engine._emit_task_event(
        conversation_id,
        None,
        engine.planner.name,
        "planned",
        planner_output[:1800],
    )

    payload = engine._extract_json(planner_output) or {}
    requirements = normalize_plan_lines(payload.get("requirements"))
    design_notes = normalize_plan_lines(payload.get("design"))
    tasks = normalize_plan_lines(payload.get("tasks"))
    assumptions = normalize_plan_lines(payload.get("assumptions"))
    risks = normalize_plan_lines(payload.get("risks"))

    if not requirements:
        requirements = [
            f"Implement the user request: {user_message}",
            "Preserve existing behavior outside explicit scope.",
            "Validate changes using applicable build/lint/test commands.",
        ]
    if not design_notes:
        design_notes = [
            "Identify impacted files/components before editing.",
            "Apply minimal, reversible changes aligned with repository conventions.",
            "Document assumptions and tradeoffs in execution summary.",
        ]
    if not tasks:
        tasks = [
            "Inspect current implementation and identify required code changes.",
            "Implement scoped code changes end-to-end.",
            "Run build/lint/test checks and resolve failures.",
            "Summarize changes, validation, assumptions, and risks.",
        ]
    if not assumptions:
        assumptions = ["Any unspecified behavior should follow existing project conventions."]

    task_checklist = to_checkbox_lines(tasks)

    requirements_md_lines = [
        "# Requirements",
        "",
        "## Context",
        f"- Chat ID: {conversation_id}",
        f"- Version: v{version}",
        f"- Workspace: {workspace.root}",
        "",
        "## User Request",
        user_message.strip() or "(empty request)",
        "",
        "## Requirements",
    ]
    requirements_md_lines.extend([f"{index}. {item}" for index, item in enumerate(requirements, start=1)])
    requirements_md_lines.extend(["", "## Assumptions"])
    requirements_md_lines.extend([f"- {item}" for item in assumptions])

    design_md_lines = [
        "# Design",
        "",
        "## Scope",
        f"Implementation design for chat request `{conversation_id}` version `v{version}`.",
        "",
        "## Design Notes",
    ]
    design_md_lines.extend([f"{index}. {item}" for index, item in enumerate(design_notes, start=1)])
    design_md_lines.extend(["", "## Risks"])
    if risks:
        design_md_lines.extend([f"- {item}" for item in risks])
    else:
        design_md_lines.append("- No material risks identified during planning.")

    tasks_md_lines = [
        "# Tasks",
        "",
        "## Implementation Checklist",
        *task_checklist,
        "",
        "## Validation Checklist",
        "- [ ] Run affected build/lint/test checks",
        "- [ ] Confirm changed files satisfy requirements.md and design.md",
        "- [ ] Document assumptions and residual risks in final summary",
    ]

    requirements_relative = f"{relative_dir}/requirements.md"
    design_relative = f"{relative_dir}/design.md"
    tasks_relative = f"{relative_dir}/tasks.md"

    engine._write_workspace_file(
        conversation_id,
        None,
        workspace,
        requirements_relative,
        "\n".join(requirements_md_lines).strip() + "\n",
        agent=engine.planner.name,
    )
    engine._write_workspace_file(
        conversation_id,
        None,
        workspace,
        design_relative,
        "\n".join(design_md_lines).strip() + "\n",
        agent=engine.planner.name,
    )
    engine._write_workspace_file(
        conversation_id,
        None,
        workspace,
        tasks_relative,
        "\n".join(tasks_md_lines).strip() + "\n",
        agent=engine.planner.name,
    )

    return {
        "chat_id": safe_chat_id,
        "version": str(version),
        "requirements_path": str(workspace.resolve_path(requirements_relative)),
        "design_path": str(workspace.resolve_path(design_relative)),
        "tasks_path": str(workspace.resolve_path(tasks_relative)),
        "tasks_markdown": "\n".join(task_checklist),
    }


__all__ = [
    "delegate_to_sdd_spec_agent",
    "next_pipeline_version",
    "normalize_plan_lines",
    "sanitize_pipeline_stream_id",
    "to_checkbox_lines",
    "write_chat_sdd_bundle",
]
