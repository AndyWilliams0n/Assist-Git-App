from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

_SECTION_ALIASES = {
    "user story": "user_story",
    "story": "user_story",
    "requirements": "requirements",
    "acceptance criteria": "acceptance_criteria",
    "acceptance": "acceptance_criteria",
    "agent context": "agent_context",
    "agent prompt": "agent_prompt",
}


def _dedupe_lines(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = " ".join(str(item or "").strip().split())
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(text)
    return deduped


def _strip_list_marker(text: str) -> str:
    return re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", str(text or "").strip()).strip()


def _normalize_section_name(value: str) -> str:
    title = _strip_list_marker(str(value or "")).strip().lower().rstrip(":")
    return _SECTION_ALIASES.get(title, "")


def _parse_description_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "details": [],
        "user_story": [],
        "requirements": [],
        "acceptance_criteria": [],
        "agent_context": [],
        "agent_prompt": [],
    }
    source = str(text or "").strip()
    if not source:
        return sections

    current_section = "details"
    for raw in source.splitlines():
        line = str(raw or "").strip()
        if not line or line == "```":
            continue

        heading_match = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading_match:
            current_section = _normalize_section_name(heading_match.group(1)) or "details"
            continue

        cleaned = _strip_list_marker(line)
        if not cleaned:
            continue
        sections.setdefault(current_section, []).append(cleaned)

    for key, values in sections.items():
        sections[key] = _dedupe_lines(values)
    return sections


def _normalize_ticket_key(value: str) -> str:
    return str(value or "").strip().upper()


@dataclass
class AttachmentMetadata:
    filename: str
    url: str
    local_path: str | None = None
    relative_path: str | None = None

    def __post_init__(self) -> None:
        self.filename = str(self.filename or "").strip()
        self.url = str(self.url or "").strip()
        self.local_path = str(self.local_path or "").strip() or None
        self.relative_path = str(self.relative_path or "").strip() or None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "filename": self.filename,
            "url": self.url,
        }
        if self.local_path:
            payload["local_path"] = self.local_path
        if self.relative_path:
            payload["relative_path"] = self.relative_path
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AttachmentMetadata":
        return cls(
            filename=str(data.get("filename") or data.get("name") or "").strip(),
            url=str(data.get("url") or data.get("content") or data.get("self") or "").strip(),
            local_path=str(data.get("local_path") or "").strip() or None,
            relative_path=str(data.get("relative_path") or "").strip() or None,
        )


@dataclass
class TicketContext:
    ticket_key: str
    title: str
    description: str = ""
    requirements: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    attachments: list[AttachmentMetadata] = field(default_factory=list)
    agent_context: list[str] = field(default_factory=list)
    agent_prompt: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.ticket_key = _normalize_ticket_key(self.ticket_key)
        self.title = str(self.title or "").strip()
        self.description = str(self.description or "").strip()
        self.requirements = _dedupe_lines(self.requirements)
        self.acceptance_criteria = _dedupe_lines(self.acceptance_criteria)
        self.agent_context = _dedupe_lines(self.agent_context)
        self.agent_prompt = _dedupe_lines(self.agent_prompt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_key": self.ticket_key,
            "title": self.title,
            "description": self.description,
            "requirements": list(self.requirements),
            "acceptance_criteria": list(self.acceptance_criteria),
            "attachments": [attachment.to_dict() for attachment in self.attachments],
            "agent_context": list(self.agent_context),
            "agent_prompt": list(self.agent_prompt),
        }

    @classmethod
    def empty(cls) -> "TicketContext":
        return cls(ticket_key="", title="")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TicketContext":
        try:
            attachments_raw = data.get("attachments") if isinstance(data.get("attachments"), list) else []
            attachments = [
                AttachmentMetadata.from_dict(item)
                for item in attachments_raw
                if isinstance(item, Mapping)
            ]
            return cls(
                ticket_key=str(data.get("ticket_key") or data.get("key") or "").strip(),
                title=str(data.get("title") or data.get("summary") or "").strip(),
                description=str(data.get("description") or "").strip(),
                requirements=[str(item) for item in (data.get("requirements") or []) if str(item).strip()],
                acceptance_criteria=[
                    str(item)
                    for item in (data.get("acceptance_criteria") or data.get("acceptance") or [])
                    if str(item).strip()
                ],
                attachments=attachments,
                agent_context=[str(item) for item in (data.get("agent_context") or []) if str(item).strip()],
                agent_prompt=[str(item) for item in (data.get("agent_prompt") or []) if str(item).strip()],
            )
        except Exception as exc:
            logger.warning("Failed to deserialize TicketContext: %s", exc)
            return cls.empty()

    @classmethod
    def from_jira_ticket(cls, ticket: Mapping[str, Any], *, ticket_key: str | None = None) -> "TicketContext":
        resolved_key = ticket_key or str(ticket.get("key") or ticket.get("ticket_key") or "").strip()
        title = str(ticket.get("summary") or ticket.get("title") or "Untitled Jira task").strip() or "Untitled Jira task"
        description = str(ticket.get("description") or "").strip()
        sections = _parse_description_sections(description)

        requirements = sections["requirements"]
        acceptance = sections["acceptance_criteria"]
        agent_context = sections["agent_context"]
        agent_prompt = sections["agent_prompt"]

        attachments_raw = ticket.get("attachments") if isinstance(ticket.get("attachments"), list) else []
        attachments = [
            AttachmentMetadata.from_dict(item)
            for item in attachments_raw
            if isinstance(item, Mapping)
        ]

        return cls(
            ticket_key=resolved_key,
            title=title,
            description=description,
            requirements=requirements,
            acceptance_criteria=acceptance,
            attachments=attachments,
            agent_context=agent_context,
            agent_prompt=agent_prompt,
        )


def serialize_ticket_contexts(contexts: Iterable[TicketContext]) -> str:
    try:
        payload = [context.to_dict() for context in contexts]
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to serialize ticket contexts: %s", exc)
        return "[]"


def deserialize_ticket_contexts(raw: str | bytes) -> list[TicketContext]:
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("Failed to parse ticket contexts JSON: %s", exc)
        return []

    if not isinstance(parsed, list):
        return []

    contexts: list[TicketContext] = []
    for item in parsed:
        if isinstance(item, Mapping):
            contexts.append(TicketContext.from_dict(item))
    return contexts


__all__ = [
    "AttachmentMetadata",
    "TicketContext",
    "deserialize_ticket_contexts",
    "serialize_ticket_contexts",
]
