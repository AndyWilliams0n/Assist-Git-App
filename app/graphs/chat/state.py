"""ChatState TypedDict for the chat graph."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ChatState(TypedDict):
    conversation_id: str
    messages: Annotated[list[dict], operator.add]
    intent: str
    intent_confidence: float
    intent_source: str
    workspace_path: str
    secondary_workspace_path: str
    workflow_mode: str
    attachment_context: str
    selected_ticket_keys: list[str]
    selected_ticket_contexts: list[dict]
    result: str
    research_task_id: str | None
