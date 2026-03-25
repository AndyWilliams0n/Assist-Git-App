from __future__ import annotations

import json
from typing import Any

from app.db import add_orchestrator_event


def log_agent_error_event(
    *,
    conversation_id: str,
    logger_agent: str,
    source_agent: str,
    error: str,
    task_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "source_agent": str(source_agent or "unknown"),
        "error": str(error or "").strip()[:4000],
    }
    if context:
        payload["context"] = context
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=task_id,
        agent=logger_agent,
        event_type="agent_error",
        content=json.dumps(payload, ensure_ascii=False)[:12000],
    )


__all__ = ["log_agent_error_event"]
