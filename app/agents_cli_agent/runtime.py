from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from app.agent_registry import make_agent_id, mark_agent_end, mark_agent_start
from app.db import (
    add_message,
    add_orchestrator_event,
    create_orchestrator_task,
    list_orchestrator_events,
    list_orchestrator_tasks,
)
from app.workspace import run_command

_CLI_AGENT_ID = make_agent_id("orchestrator", "CLI Agent")

CODEX_CLI_OUTPUT_LOG_CHARS = int(os.getenv("CODEX_CLI_OUTPUT_LOG_CHARS", "32000"))
RUN_COMMAND_TIMEOUT_SECONDS = int(os.getenv("CODEX_RUN_COMMAND_TIMEOUT_SECONDS", "1200"))


def extract_direct_commands(message: str) -> list[str]:
    commands: list[str] = []
    for inline in re.findall(r"`([^`]+)`", message or ""):
        if inline.strip():
            commands.append(inline.strip())

    match = re.search(r"\b(?:run|execute)\b\s+(.+)$", message or "", flags=re.IGNORECASE)
    if match:
        tail = match.group(1).strip()
        if tail and "\n" not in tail:
            commands.append(tail)

    seen: set[str] = set()
    deduped: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped[:6]


async def run_cli_workflow(
    engine: Any,
    conversation_id: str,
    user_message: str,
    workspace: Any,
) -> dict[str, object]:
    agent_error: str | None = None
    mark_agent_start(_CLI_AGENT_ID)
    try:
        return await _run_cli_workflow(engine, conversation_id, user_message, workspace)
    except Exception as exc:
        agent_error = str(exc)
        raise
    finally:
        mark_agent_end(_CLI_AGENT_ID, agent_error)


async def _run_cli_workflow(
    engine: Any,
    conversation_id: str,
    user_message: str,
    workspace: Any,
) -> dict[str, object]:
    plan_prompt = (
        f"User request:\n{user_message}\n\n"
        "Return JSON only as {\"commands\":[\"...\"]}. "
        "Include only safe local commands."
    )
    planner_output = await engine._call(engine.cli_runner, plan_prompt, conversation_id=conversation_id)
    payload = engine._extract_json(planner_output) or {}
    commands = payload.get("commands") if isinstance(payload.get("commands"), list) else []
    commands = [str(command).strip() for command in commands if str(command).strip()]
    if not commands:
        commands = extract_direct_commands(user_message)

    if not commands:
        note = "No runnable command was identified in the request."
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.cli_runner.name,
            event_type="cli_skipped",
            content=note,
        )
        add_message(conversation_id, role="assistant", agent=engine.orchestrator.name, content=note)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type="assistant_message",
            content=note,
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent=engine.orchestrator.name,
            event_type="turn_completed",
            content="Turn complete and response returned to user.",
        )
        return {
            "reply": note,
            "tasks": list_orchestrator_tasks(conversation_id),
            "events": list_orchestrator_events(conversation_id),
        }

    return await run_cli_commands_workflow(
        engine,
        conversation_id=conversation_id,
        user_message=user_message,
        workspace=workspace,
        commands=commands,
        intent_label="run_commands",
    )


async def run_cli_commands_workflow(
    engine: Any,
    *,
    conversation_id: str,
    user_message: str,
    workspace: Any,
    commands: list[str],
    intent_label: str,
) -> dict[str, object]:
    outputs: list[str] = []
    for command in commands:
        task = create_orchestrator_task(
            conversation_id=conversation_id,
            title=f"Run command: {command}",
            details=f"Execute `{command}` in workspace root.",
            owner_agent=engine.cli_runner.name,
        )
        engine._emit_task_event(conversation_id, task["id"], engine.cli_runner.name, "task_created", task)
        engine._set_task_status(conversation_id, task["id"], engine.cli_runner.name, "in_progress")
        result = await asyncio.to_thread(
            run_command,
            command,
            workspace.root,
            RUN_COMMAND_TIMEOUT_SECONDS,
            CODEX_CLI_OUTPUT_LOG_CHARS,
        )
        output = (
            f"command: {command}\n"
            f"exit: {result.exit_code}\n"
            f"stdout:\n{result.stdout}\n\n"
            f"stderr:\n{result.stderr}"
        )
        outputs.append(output)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent=engine.cli_runner.name,
            event_type="cli_run",
            content=f"Ran `{command}` (exit {result.exit_code})",
        )
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=task["id"],
            agent=engine.cli_runner.name,
            event_type="cli_run_output",
            content=engine._truncate_text(output, CODEX_CLI_OUTPUT_LOG_CHARS),
        )
        engine._set_task_status(
            conversation_id,
            task["id"],
            engine.cli_runner.name,
            "done" if result.exit_code == 0 else "blocked",
        )

    summary_prompt = (
        f"User request:\n{user_message}\n\n"
        f"Intent branch: {intent_label}\n\n"
        f"Command execution outputs:\n\n{chr(10).join(outputs)[:12000]}\n\n"
        "Respond to the user now with a concise summary."
    )
    final_reply = await engine._call(engine.orchestrator, summary_prompt, conversation_id=conversation_id)
    add_message(conversation_id, role="assistant", agent=engine.orchestrator.name, content=final_reply)
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent=engine.orchestrator.name,
        event_type="assistant_message",
        content=final_reply,
    )
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent=engine.orchestrator.name,
        event_type="turn_completed",
        content="Turn complete and response returned to user.",
    )
    return {
        "reply": final_reply,
        "tasks": list_orchestrator_tasks(conversation_id),
        "events": list_orchestrator_events(conversation_id),
    }


__all__ = ["extract_direct_commands", "run_cli_commands_workflow", "run_cli_workflow"]

