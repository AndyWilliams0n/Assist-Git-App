from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

JSON_BLOCK_RE = re.compile(r"```json\s*(?P<body>\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _sanitize_segment(value: str, fallback: str = "conversation") -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    sanitized = sanitized.strip("-.")
    return sanitized[:120] or fallback


@dataclass
class JiraConversationState:
    conversation_id: str = ""
    updated_at: str = ""
    last_intended_jira_create_request: str = ""
    last_referenced_attachments: list[dict[str, str]] = field(default_factory=list)
    last_ticket_keys: list[str] = field(default_factory=list)
    requested_operation_mode: str = ""
    project_key: str = ""
    board_id: str = ""
    backlog_url: str = ""
    workspace_root: str = ""
    relevant_files: list[str] = field(default_factory=list)
    normalized_implementation_brief_summary: str = ""
    pending_clarification_action: str = ""
    pending_clarification_question: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "JiraConversationState":
        attachments_raw = payload.get("last_referenced_attachments")
        attachments: list[dict[str, str]] = []
        if isinstance(attachments_raw, list):
            for item in attachments_raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                path = str(item.get("path") or "").strip()
                if not name and not path:
                    continue
                attachments.append({"name": name, "path": path})

        ticket_keys_raw = payload.get("last_ticket_keys")
        ticket_keys = []
        if isinstance(ticket_keys_raw, list):
            for item in ticket_keys_raw:
                key = str(item or "").strip().upper()
                if key and key not in ticket_keys:
                    ticket_keys.append(key)

        relevant_files_raw = payload.get("relevant_files")
        relevant_files = []
        if isinstance(relevant_files_raw, list):
            for item in relevant_files_raw:
                text = str(item or "").strip()
                if text and text not in relevant_files:
                    relevant_files.append(text)

        return cls(
            conversation_id=str(payload.get("conversation_id") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
            last_intended_jira_create_request=str(payload.get("last_intended_jira_create_request") or "").strip(),
            last_referenced_attachments=attachments,
            last_ticket_keys=ticket_keys,
            requested_operation_mode=str(payload.get("requested_operation_mode") or "").strip(),
            project_key=str(payload.get("project_key") or "").strip().upper(),
            board_id=str(payload.get("board_id") or "").strip(),
            backlog_url=str(payload.get("backlog_url") or "").strip(),
            workspace_root=str(payload.get("workspace_root") or "").strip(),
            relevant_files=relevant_files,
            normalized_implementation_brief_summary=str(
                payload.get("normalized_implementation_brief_summary") or ""
            ).strip(),
            pending_clarification_action=str(payload.get("pending_clarification_action") or "").strip().lower(),
            pending_clarification_question=str(payload.get("pending_clarification_question") or "").strip(),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "conversation_id": self.conversation_id,
            "updated_at": self.updated_at,
            "last_intended_jira_create_request": self.last_intended_jira_create_request,
            "last_referenced_attachments": self.last_referenced_attachments,
            "last_ticket_keys": self.last_ticket_keys,
            "requested_operation_mode": self.requested_operation_mode,
            "project_key": self.project_key,
            "board_id": self.board_id,
            "backlog_url": self.backlog_url,
            "workspace_root": self.workspace_root,
            "relevant_files": self.relevant_files,
            "normalized_implementation_brief_summary": self.normalized_implementation_brief_summary,
            "pending_clarification_action": self.pending_clarification_action,
            "pending_clarification_question": self.pending_clarification_question,
        }


def jira_conversation_state_path(workspace_root: Path, conversation_id: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    safe_conversation_id = _sanitize_segment(conversation_id, fallback="conversation")
    return root / ".assist" / "conversations" / safe_conversation_id / "jira-state.md"


def load_jira_conversation_state(workspace_root: Path, conversation_id: str | None) -> JiraConversationState:
    if not conversation_id:
        return JiraConversationState()

    state_path = jira_conversation_state_path(workspace_root, conversation_id)
    if not state_path.exists():
        return JiraConversationState(conversation_id=str(conversation_id or "").strip())

    try:
        text = state_path.read_text(encoding="utf-8")
    except Exception:
        return JiraConversationState(conversation_id=str(conversation_id or "").strip())

    match = JSON_BLOCK_RE.search(text)
    if not match:
        return JiraConversationState(conversation_id=str(conversation_id or "").strip())

    try:
        payload = json.loads(str(match.group("body") or "{}"))
    except Exception:
        return JiraConversationState(conversation_id=str(conversation_id or "").strip())
    if not isinstance(payload, dict):
        return JiraConversationState(conversation_id=str(conversation_id or "").strip())
    state = JiraConversationState.from_payload(payload)
    if not state.conversation_id:
        state.conversation_id = str(conversation_id or "").strip()
    return state


def save_jira_conversation_state(
    workspace_root: Path,
    conversation_id: str | None,
    state: JiraConversationState,
) -> Path | None:
    if not conversation_id:
        return None

    normalized_state = JiraConversationState.from_payload(state.to_payload())
    normalized_state.conversation_id = str(conversation_id or "").strip()
    normalized_state.updated_at = datetime.now(timezone.utc).isoformat()
    state_path = jira_conversation_state_path(workspace_root, normalized_state.conversation_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    ticket_keys_text = ", ".join(normalized_state.last_ticket_keys) if normalized_state.last_ticket_keys else "n/a"
    attachments_lines = [
        f"- {item.get('name') or 'attachment'}"
        + (f" ({item.get('path')})" if item.get("path") else "")
        for item in normalized_state.last_referenced_attachments
        if isinstance(item, dict)
    ] or ["- n/a"]
    relevant_files_lines = [f"- {item}" for item in normalized_state.relevant_files] or ["- n/a"]
    request_text = normalized_state.last_intended_jira_create_request or "n/a"
    summary_text = normalized_state.normalized_implementation_brief_summary or "n/a"

    content = "\n".join(
        [
            "# Jira Conversation State",
            "",
            f"- Conversation ID: {normalized_state.conversation_id}",
            f"- Updated At: {normalized_state.updated_at}",
            f"- Requested Operation Mode: {normalized_state.requested_operation_mode or 'n/a'}",
            f"- Last Ticket Keys: {ticket_keys_text}",
            f"- Project Key: {normalized_state.project_key or 'n/a'}",
            f"- Board ID: {normalized_state.board_id or 'n/a'}",
            f"- Backlog URL: {normalized_state.backlog_url or 'n/a'}",
            f"- Pending Clarification Action: {normalized_state.pending_clarification_action or 'n/a'}",
            "",
            "## Normalized Summary",
            summary_text,
            "",
            "## Last Intended Jira Create Request",
            request_text,
            "",
            "## Pending Clarification Question",
            normalized_state.pending_clarification_question or "n/a",
            "",
            "## Last Referenced Attachments",
            *attachments_lines,
            "",
            "## Relevant Files",
            *relevant_files_lines,
            "",
            "## Structured State",
            "```json",
            json.dumps(normalized_state.to_payload(), indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    state_path.write_text(content, encoding="utf-8")
    return state_path


__all__ = [
    "JiraConversationState",
    "jira_conversation_state_path",
    "load_jira_conversation_state",
    "save_jira_conversation_state",
]
