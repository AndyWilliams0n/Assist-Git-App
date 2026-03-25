from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from app.agent_registry import (
    AgentDefinition,
    make_agent_id,
    mark_agent_end,
    mark_agent_start,
    register_agent,
)
from app.agents_jira.config import CONFIG
from app.db import list_jira_fetches
from app.llm import LLMClient
from app.mcp_client import MCPClient, MCPConfig, load_mcp_config
from app.settings_store import get_llm_function_settings

DEFAULT_BACKLOG_URL = ""
BACKLOG_URL_RE = re.compile(
    r"/projects/(?P<project>[A-Za-z0-9_]+)/boards/(?P<board>\d+)/backlog",
    re.IGNORECASE,
)
ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
CREATE_SUMMARY_RE = re.compile(
    r"\b(?:create|add|new)\b.*?\b(?:ticket|issue)\b[:\s-]*(?P<summary>.+)$",
    re.IGNORECASE,
)
CREATE_ABOUT_ITEM_RE = re.compile(
    r"\babout\s+(?P<topic>.*?)"
    r"(?=(?:\s*(?:,|and)\s+(?:another|one)\s+about\b)|[.?!]|$)",
    re.IGNORECASE,
)
CREATE_FOR_ITEM_RE = re.compile(
    r"\b(?:subtask|ticket|issue)\s+for\s+(?P<topic>.*?)"
    r"(?=(?:\s*(?:,|and)\s+(?:another|one)\s+(?:for|about)\b)|[.?!]|$)",
    re.IGNORECASE,
)
CREATE_COUNT_RE = re.compile(
    r"\b(?:create|add|open|raise|log)\b[\w\s]{0,30}\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b[\w\s]{0,15}\b(subtasks|child issues|tickets|issues|tasks)\b",
    re.IGNORECASE,
)
EDIT_SUMMARY_RE = re.compile(
    r"\b(?:summary|title)\b\s*(?:to|=|:)\s*(?P<summary>.+)$",
    re.IGNORECASE,
)
PRIORITY_INLINE_RE = re.compile(
    r"\b(?:priority|severity)\b\s*(?:to|=|:)\s*(?P<priority>[^.;,\n]+)",
    re.IGNORECASE,
)
PRIORITY_SUFFIX_RE = re.compile(
    r"\bto\s+(?P<priority>[^.;,\n]+?)\s+(?:priority|severity)\b",
    re.IGNORECASE,
)
EDIT_FIELD_ASSIGNMENT_RE = re.compile(
    r"\b(?P<field>"
    r"summary|title|priority|severity|assignee|reporter|labels?|"
    r"due(?:\s|-)?date|start(?:\s|-)?date|sprint|story\s*points?|storypoints|team"
    r")\b\s*(?:to|=|:)\s*(?P<value>.*?)"
    r"(?=(?:\s+\band\s+(?:summary|title|priority|severity|assignee|reporter|labels?|"
    r"due(?:\s|-)?date|start(?:\s|-)?date|sprint|story\s*points?|storypoints|team)\b\s*(?:to|=|:))|$)",
    re.IGNORECASE,
)
GENERIC_EDIT_SET_RE = re.compile(
    r"\b(?:set|change|update|edit)\s+(?P<field>[A-Za-z][A-Za-z0-9_\s-]{1,48}?)\s+(?:to|=)\s*(?P<value>[^;\n]+)",
    re.IGNORECASE,
)
DEFAULT_RESULT_FIELDS = [
    "summary",
    "description",
    "status",
    "assignee",
    "reporter",
    "priority",
    "labels",
    "duedate",
    "startdate",
    "sprint",
    "story points",
    "Story Points",
    "updated",
    "created",
    "issuetype",
    "parent",
    "attachment",
    "comment",
    "customfield_10020",  # common sprint field id
    "customfield_10016",  # common story points field id
    "customfield_10026",  # alternate story points field id
    "customfield_10015",  # common start date field id
    "customfield_10001",  # common team field id
]
DEFAULT_ACTIVITY_ENRICH_LIMIT = 25
DESCRIPTION_UPDATE_TOKENS = ("description", "acceptance criteria", "criteria", "details", "scope")
PARENT_UPDATE_TOKENS = (
    "parent ticket",
    "main ticket",
    "top-level ticket",
    "top level ticket",
    "include parent",
    "including parent",
    "also update parent",
    "update the parent",
    "update parent",
    "and parent",
)
DESCRIPTION_SECTION_TITLES = (
    "User Story",
    "Background",
    "Scope (In / Out)",
    "Requirements",
    "Acceptance Criteria",
    "Technical Notes",
    "Definition of Done",
    "Agent Context",
    "Agent Prompt",
)
ATTACHMENT_CONTEXT_MARKER = "Attachment context for this conversation:"


def _persist_raw_result(workspace_root: Path, raw_result_json: str) -> str | None:
    try:
        raw_dir = workspace_root / ".assist" / "jira" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        raw_path = raw_dir / f"{timestamp}.json"
        raw_path.write_text(raw_result_json, encoding="utf-8")
        return str(raw_path)
    except Exception:
        return None


def _tool_name(value: dict[str, Any]) -> str:
    return str(value.get("name") or "").strip()


def _extract_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if isinstance(tools, list):
        return [tool for tool in tools if isinstance(tool, dict)]
    return []


def _parse_backlog_url(backlog_url: str) -> tuple[str | None, str | None]:
    match = BACKLOG_URL_RE.search(backlog_url)
    if not match:
        return (None, None)
    project_key = str(match.group("project") or "").strip().upper() or None
    board_id = str(match.group("board") or "").strip() or None
    return (project_key, board_id)


def _stringify_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("name", "displayName", "value", "title", "text"):
            nested = value.get(key)
            text = _stringify_scalar(nested)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = _stringify_scalar(item)
            if text:
                return text
    return ""


def _extract_attachments(value: Any) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    if not isinstance(value, list):
        return attachments
    for item in value:
        if not isinstance(item, dict):
            continue
        filename = _stringify_scalar(item.get("filename")) or _stringify_scalar(item.get("name"))
        url = (
            _stringify_scalar(item.get("content"))
            or _stringify_scalar(item.get("url"))
            or _stringify_scalar(item.get("self"))
        )
        if not filename and not url:
            continue
        attachments.append({"filename": filename, "url": url})
    return attachments


def _extract_comments(value: Any) -> list[dict[str, str]]:
    comments_root = value
    if isinstance(value, dict) and isinstance(value.get("comments"), list):
        comments_root = value.get("comments")
    if not isinstance(comments_root, list):
        return []
    comments: list[dict[str, str]] = []
    for item in comments_root:
        if not isinstance(item, dict):
            continue
        author_field = item.get("author") if isinstance(item.get("author"), dict) else item.get("author")
        author = _stringify_scalar(
            author_field.get("displayName") if isinstance(author_field, dict) else author_field
        )
        body = _adf_to_text(item.get("body")) or _stringify_scalar(item.get("body"))
        created = _stringify_scalar(item.get("created"))
        updated = _stringify_scalar(item.get("updated"))
        comment_id = _stringify_scalar(item.get("id"))
        if not any((author, body, created, updated, comment_id)):
            continue
        comments.append(
            {
                "id": comment_id,
                "author": author,
                "body": body,
                "created": created,
                "updated": updated,
            }
        )
    return comments


def _extract_history(value: Any) -> list[dict[str, Any]]:
    histories_root = value
    if isinstance(value, dict) and isinstance(value.get("histories"), list):
        histories_root = value.get("histories")
    if not isinstance(histories_root, list):
        return []
    history_rows: list[dict[str, Any]] = []
    for entry in histories_root:
        if not isinstance(entry, dict):
            continue
        author_field = entry.get("author") if isinstance(entry.get("author"), dict) else entry.get("author")
        author = _stringify_scalar(
            author_field.get("displayName") if isinstance(author_field, dict) else author_field
        )
        created = _stringify_scalar(entry.get("created"))
        history_id = _stringify_scalar(entry.get("id"))
        changes: list[dict[str, str]] = []
        items = entry.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                field = _stringify_scalar(item.get("field"))
                from_value = _stringify_scalar(item.get("fromString") or item.get("from"))
                to_value = _stringify_scalar(item.get("toString") or item.get("to"))
                if not any((field, from_value, to_value)):
                    continue
                changes.append(
                    {
                        "field": field,
                        "from": from_value,
                        "to": to_value,
                    }
                )
        if not any((author, created, history_id, changes)):
            continue
        history_rows.append(
            {
                "id": history_id,
                "author": author,
                "created": created,
                "changes": changes,
            }
        )
    return history_rows


def _extract_field_value(fields: dict[str, Any], *names: str) -> Any:
    if not isinstance(fields, dict):
        return None
    lowered_lookup = {str(key).lower(): key for key in fields.keys()}
    for name in names:
        lowered = str(name).lower()
        actual = lowered_lookup.get(lowered)
        if not actual:
            continue
        value = fields.get(actual)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def _adf_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        chunks = [_adf_to_text(item) for item in value]
        normalized = [chunk for chunk in chunks if chunk]
        return "\n".join(normalized).strip()
    if isinstance(value, dict):
        node_type = str(value.get("type") or "").strip().lower()
        if node_type == "text":
            return str(value.get("text") or "").strip()
        direct_text = _stringify_scalar(value.get("text"))
        if direct_text:
            return direct_text
        chunks: list[str] = []
        content = value.get("content")
        if isinstance(content, list):
            for item in content:
                item_text = _adf_to_text(item)
                if item_text:
                    chunks.append(item_text)
        for key in ("value", "title", "name"):
            nested = _stringify_scalar(value.get(key))
            if nested:
                chunks.append(nested)
        normalized = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
        return "\n".join(normalized).strip()
    return ""


def _extract_string_list(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = _stringify_scalar(item) or _adf_to_text(item)
            if not text:
                continue
            if text not in values:
                values.append(text)
    elif value is not None:
        text = _stringify_scalar(value) or _adf_to_text(value)
        if text:
            values.append(text)
    return values


def _extract_sprint_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _stringify_scalar(item.get("name")) or _stringify_scalar(item.get("title"))
                if name and name not in names:
                    names.append(name)
                    continue
            text = _stringify_scalar(item)
            if not text:
                continue
            match = re.search(r"name=([^,\]]+)", text, re.IGNORECASE)
            parsed = match.group(1).strip() if match else text
            if parsed and parsed not in names:
                names.append(parsed)
    elif isinstance(value, dict):
        name = _stringify_scalar(value.get("name")) or _stringify_scalar(value.get("title"))
        if name:
            names.append(name)
    elif value is not None:
        text = _stringify_scalar(value)
        if text:
            match = re.search(r"name=([^,\]]+)", text, re.IGNORECASE)
            parsed = match.group(1).strip() if match else text
            if parsed:
                names.append(parsed)
    return names


def _extract_sprint_entries(value: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    def add_entry(entry: dict[str, Any]) -> None:
        normalized = {
            "id": _stringify_scalar(entry.get("id")),
            "name": _stringify_scalar(entry.get("name")) or _stringify_scalar(entry.get("title")),
            "state": _stringify_scalar(entry.get("state")),
            "goal": _stringify_scalar(entry.get("goal")),
            "start_date": _stringify_scalar(entry.get("startDate") or entry.get("start_date")),
            "end_date": _stringify_scalar(entry.get("endDate") or entry.get("end_date")),
            "complete_date": _stringify_scalar(entry.get("completeDate") or entry.get("complete_date")),
            "board_id": _stringify_scalar(
                entry.get("rapidViewId") or entry.get("boardId") or entry.get("board_id") or entry.get("originBoardId")
            ),
        }
        if not any(normalized.values()):
            return
        dedupe_key = "|".join(
            (
                normalized["id"],
                normalized["name"],
                normalized["state"],
                normalized["start_date"],
                normalized["end_date"],
            )
        )
        if any(
            "|".join(
                (
                    item.get("id", ""),
                    item.get("name", ""),
                    item.get("state", ""),
                    item.get("start_date", ""),
                    item.get("end_date", ""),
                )
            )
            == dedupe_key
            for item in entries
        ):
            return
        entries.append(normalized)

    if isinstance(value, list):
        for item in value:
            entries.extend(_extract_sprint_entries(item))
        return entries
    if isinstance(value, dict):
        add_entry(value)
        return entries
    if value is None:
        return entries

    text = _stringify_scalar(value)
    if not text:
        return entries
    if "name=" not in text and "state=" not in text and "id=" not in text:
        if text:
            add_entry({"name": text})
        return entries
    parsed: dict[str, str] = {}
    for key, raw_value in re.findall(r"([A-Za-z][A-Za-z0-9]*)=([^,\]]*)", text):
        normalized_key = key.strip().lower()
        parsed[normalized_key] = raw_value.strip()
    add_entry(
        {
            "id": parsed.get("id", ""),
            "name": parsed.get("name", ""),
            "state": parsed.get("state", ""),
            "goal": parsed.get("goal", ""),
            "startDate": parsed.get("startdate", ""),
            "endDate": parsed.get("enddate", ""),
            "completeDate": parsed.get("completedate", ""),
            "rapidViewId": parsed.get("rapidviewid", ""),
        }
    )
    return entries


def _extract_sprint_entries_from_result(result: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    def extend_unique(candidates: list[dict[str, str]]) -> None:
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            marker = (
                str(candidate.get("id") or ""),
                str(candidate.get("name") or ""),
                str(candidate.get("state") or ""),
                str(candidate.get("start_date") or ""),
                str(candidate.get("end_date") or ""),
            )
            if any(
                (
                    str(existing.get("id") or ""),
                    str(existing.get("name") or ""),
                    str(existing.get("state") or ""),
                    str(existing.get("start_date") or ""),
                    str(existing.get("end_date") or ""),
                )
                == marker
                for existing in entries
            ):
                continue
            entries.append(candidate)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                lowered = str(key).strip().lower()
                if lowered in {"sprint", "sprints", "customfield_10020"}:
                    extend_unique(_extract_sprint_entries(nested))
                walk(nested)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    for payload in _extract_json_payloads_from_content(result):
        walk(payload)
    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)):
        walk(structured)
    return entries


def _select_current_sprint_entry(entries: list[dict[str, str]]) -> dict[str, str] | None:
    if not entries:
        return None
    state_rank = {
        "active": 0,
        "open": 0,
        "current": 0,
        "future": 1,
        "closed": 2,
        "complete": 2,
        "completed": 2,
    }

    def rank(entry: dict[str, str]) -> tuple[int, str, str]:
        state = str(entry.get("state") or "").strip().lower()
        return (
            state_rank.get(state, 3),
            str(entry.get("end_date") or ""),
            str(entry.get("start_date") or ""),
        )

    return sorted(entries, key=rank)[0]


def _build_ticket_count_rows(tickets: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        name = _stringify_scalar(ticket.get(field)) or "Unknown"
        counts[name] = counts.get(name, 0) + 1
    rows = [
        {"name": name, "ticket_count": count}
        for name, count in counts.items()
    ]
    rows.sort(key=lambda item: (-int(item.get("ticket_count") or 0), str(item.get("name") or "").lower()))
    return rows


def _dedupe_tickets_by_key(*ticket_groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for group in ticket_groups:
        if not isinstance(group, list):
            continue
        for ticket in group:
            if not isinstance(ticket, dict):
                continue
            key = str(ticket.get("key") or "").strip().upper()
            if not ISSUE_KEY_RE.fullmatch(key):
                continue
            if key not in by_key:
                by_key[key] = ticket
                continue
            existing = by_key[key]
            for field in ("status", "summary", "updated", "priority", "assignee"):
                if not existing.get(field) and ticket.get(field):
                    existing[field] = ticket.get(field)
    return list(by_key.values())


def _build_current_sprint_payload(
    result: dict[str, Any],
    tickets: list[dict[str, Any]],
    fallback_board_id: str | None = None,
) -> dict[str, Any] | None:
    sprint_entries = _extract_sprint_entries_from_result(result)
    selected = _select_current_sprint_entry(sprint_entries) or {}

    if not selected and tickets:
        first_ticket_sprints = tickets[0].get("sprints") if isinstance(tickets[0].get("sprints"), list) else []
        derived_name = _stringify_scalar(first_ticket_sprints[0]) if first_ticket_sprints else ""
        if derived_name:
            selected = {"name": derived_name}

    if not selected and not tickets:
        return None

    return {
        "id": _stringify_scalar(selected.get("id")),
        "name": _stringify_scalar(selected.get("name")),
        "state": _stringify_scalar(selected.get("state")),
        "goal": _stringify_scalar(selected.get("goal")),
        "start_date": _stringify_scalar(selected.get("start_date")),
        "end_date": _stringify_scalar(selected.get("end_date")),
        "complete_date": _stringify_scalar(selected.get("complete_date")),
        "board_id": _stringify_scalar(selected.get("board_id")) or _stringify_scalar(fallback_board_id),
        "ticket_count": len([ticket for ticket in tickets if isinstance(ticket, dict)]),
        "tickets": [ticket for ticket in tickets if isinstance(ticket, dict)],
        "counts_by_status": _build_ticket_count_rows(tickets, "status"),
    }


def _build_kanban_columns_payload(tickets: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    rows = _build_ticket_count_rows(tickets, "status")
    total = sum(int(item.get("ticket_count") or 0) for item in rows)
    max_count = max((int(item.get("ticket_count") or 0) for item in rows), default=0)
    payload: list[dict[str, Any]] = []
    for item in rows:
        count = int(item.get("ticket_count") or 0)
        payload.append(
            {
                "name": _stringify_scalar(item.get("name")) or "Unknown",
                "ticket_count": count,
                "source": source,
                "share_of_total": round((count / total), 4) if total else 0,
                "relative_width": round((count / max_count), 4) if max_count else 0,
            }
        )
    return payload


def _extract_story_points(fields: dict[str, Any]) -> str:
    raw = _extract_field_value(
        fields,
        "story points",
        "Story Points",
        "story_point_estimate",
        "storyPointEstimate",
        "customfield_10016",
        "customfield_10026",
    )
    if raw is None:
        return ""
    text = _stringify_scalar(raw)
    if text:
        return text
    if isinstance(raw, (int, float)):
        return str(raw)
    return ""


def _extract_development_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    for key in ("branches", "commits", "pullRequests", "pullrequests", "reviews", "builds"):
        raw = value.get(key)
        if isinstance(raw, (int, float)):
            parts.append(f"{key}:{int(raw)}")
        elif isinstance(raw, dict):
            count = raw.get("count")
            if isinstance(count, (int, float)):
                parts.append(f"{key}:{int(count)}")
    return ", ".join(parts)


def _is_subtask(issue_type: str, parent_key: str) -> bool:
    lowered = (issue_type or "").strip().lower()
    if parent_key:
        return True
    return "sub-task" in lowered or "subtask" in lowered


def _extract_ticket_from_mapping(payload: dict[str, Any]) -> dict[str, Any] | None:
    key_candidates = [
        payload.get("key"),
        payload.get("issueKey"),
        payload.get("issue_key"),
        payload.get("jiraKey"),
        payload.get("ticketKey"),
    ]
    key = ""
    for candidate in key_candidates:
        text = _stringify_scalar(candidate).upper()
        if ISSUE_KEY_RE.fullmatch(text):
            key = text
            break
    if not key:
        return None

    summary = _stringify_scalar(payload.get("summary")) or _stringify_scalar(payload.get("title"))
    description = _adf_to_text(payload.get("description")) or _stringify_scalar(payload.get("descriptionText"))
    status = _stringify_scalar(payload.get("status"))
    status_id = _stringify_scalar(payload.get("status_id")) or _stringify_scalar(payload.get("statusId"))
    assignee = _stringify_scalar(payload.get("assignee")) or _stringify_scalar(payload.get("owner"))
    reporter = _stringify_scalar(payload.get("reporter"))
    priority = _stringify_scalar(payload.get("priority"))
    updated = _stringify_scalar(payload.get("updated")) or _stringify_scalar(payload.get("updatedAt"))
    due_date = _stringify_scalar(payload.get("duedate")) or _stringify_scalar(payload.get("due_date"))
    start_date = _stringify_scalar(payload.get("startdate")) or _stringify_scalar(payload.get("start_date"))
    labels = _extract_string_list(payload.get("labels"))
    sprints = _extract_sprint_names(payload.get("sprint") or payload.get("sprints"))
    story_points = _stringify_scalar(payload.get("story_points")) or _stringify_scalar(payload.get("storyPointEstimate"))
    team = _stringify_scalar(payload.get("team"))
    development = _extract_development_summary(payload.get("development"))
    issue_type = _stringify_scalar(payload.get("issue_type")) or _stringify_scalar(payload.get("issuetype"))
    if not issue_type:
        issue_type = _stringify_scalar(payload.get("issueType"))
    parent_key = _stringify_scalar(payload.get("parent_key")).upper()
    parent_summary = _stringify_scalar(payload.get("parent_summary"))
    parent_description = _adf_to_text(payload.get("parent_description")) or _stringify_scalar(
        payload.get("parent_description")
    )
    if not parent_key:
        parent = payload.get("parent")
        if isinstance(parent, dict):
            parent_key = _stringify_scalar(parent.get("key")).upper()
            parent_fields = parent.get("fields") if isinstance(parent.get("fields"), dict) else {}
            if not parent_summary:
                parent_summary = _stringify_scalar(parent_fields.get("summary"))
            if not parent_description:
                parent_description = _adf_to_text(parent_fields.get("description")) or _stringify_scalar(
                    parent_fields.get("description")
                )
        else:
            parent_key = _stringify_scalar(parent).upper()
    attachments = _extract_attachments(payload.get("attachments"))
    if not attachments:
        attachments = _extract_attachments(payload.get("attachment"))
    comments = _extract_comments(payload.get("comments"))
    if not comments:
        comments = _extract_comments(payload.get("comment"))
    history = _extract_history(payload.get("history"))
    if not history:
        history = _extract_history(payload.get("changelog"))
    ticket_url = (
        _stringify_scalar(payload.get("url"))
        or _stringify_scalar(payload.get("self"))
        or _stringify_scalar(payload.get("browseUrl"))
    )

    ticket: dict[str, Any] = {
        "key": key,
        "summary": summary,
        "description": description,
        "status": status,
        "status_id": status_id,
        "assignee": assignee,
        "reporter": reporter,
        "priority": priority,
        "updated": updated,
        "due_date": due_date,
        "start_date": start_date,
        "labels": labels,
        "sprints": sprints,
        "story_points": story_points,
        "team": team,
        "development": development,
        "issue_type": issue_type,
        "parent_key": parent_key,
        "parent_summary": parent_summary,
        "parent_description": parent_description,
        "is_subtask": _is_subtask(issue_type, parent_key),
        "attachments": attachments,
        "attachments_count": len(attachments),
        "comments": comments,
        "history": history,
        "url": ticket_url,
    }
    return ticket


def _extract_ticket_text(result: dict[str, Any]) -> str:
    text_chunks: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str):
                text = text_value.strip()
            else:
                text = _stringify_scalar(text_value)
            if text:
                text_chunks.append(text)
    structured = result.get("structuredContent")
    if structured is not None:
        if isinstance(structured, str):
            text_chunks.append(structured)
        else:
            text_chunks.append(json.dumps(structured, ensure_ascii=False))
    return "\n".join(chunk for chunk in text_chunks if chunk).strip()


def _parse_json_value(value: str) -> Any:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_json_payloads_from_content(result: dict[str, Any]) -> list[Any]:
    payloads: list[Any] = []
    content = result.get("content")
    if not isinstance(content, list):
        return payloads
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        parsed = _parse_json_value(text)
        if parsed is not None:
            payloads.append(parsed)
    return payloads


def _extract_result_error_message(result: dict[str, Any]) -> str | None:
    if not isinstance(result, dict):
        return None

    for payload in _extract_json_payloads_from_content(result):
        if not isinstance(payload, dict):
            continue
        if bool(payload.get("error")):
            message = _stringify_scalar(payload.get("message")) or _stringify_scalar(payload.get("errorMessage"))
            if message:
                return message
            return json.dumps(payload, ensure_ascii=False)[:500]
        error_messages = payload.get("errorMessages")
        if isinstance(error_messages, list):
            normalized = [_stringify_scalar(item) for item in error_messages if _stringify_scalar(item)]
            if normalized:
                return "; ".join(normalized)
        errors_map = payload.get("errors")
        if isinstance(errors_map, dict) and errors_map:
            pairs: list[str] = []
            for key, value in errors_map.items():
                text = _stringify_scalar(value) or str(value)
                label = str(key).strip()
                pairs.append(f"{label}: {text}" if label else text)
            if pairs:
                return "; ".join(pairs)

    if bool(result.get("isError")):
        text = _extract_ticket_text(result)
        if text:
            return text[:700]
        return "MCP tool returned isError=true."
    return None


def _extract_resources(result: dict[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for payload in _extract_json_payloads_from_content(result):
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    resources.append(item)
        elif isinstance(payload, dict):
            nested = payload.get("resources")
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        resources.append(item)
    return resources


def _extract_jira_issues(result: dict[str, Any]) -> list[dict[str, Any]]:
    tickets: list[dict[str, Any]] = []

    def parse_issue(issue: dict[str, Any]) -> dict[str, Any] | None:
        key = _stringify_scalar(issue.get("key")).upper()
        if not ISSUE_KEY_RE.fullmatch(key):
            return None
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        status_field = fields.get("status") if isinstance(fields, dict) else None
        assignee_field = fields.get("assignee") if isinstance(fields, dict) else None
        reporter_field = fields.get("reporter") if isinstance(fields, dict) else None
        priority_field = fields.get("priority") if isinstance(fields, dict) else None
        summary = _stringify_scalar(fields.get("summary")) or _stringify_scalar(issue.get("summary"))
        description = _adf_to_text(fields.get("description")) or _stringify_scalar(issue.get("description"))
        status = _stringify_scalar(status_field.get("name") if isinstance(status_field, dict) else status_field)
        status_id = _stringify_scalar(status_field.get("id") if isinstance(status_field, dict) else None)
        assignee = _stringify_scalar(
            assignee_field.get("displayName") if isinstance(assignee_field, dict) else assignee_field
        )
        reporter = _stringify_scalar(
            reporter_field.get("displayName") if isinstance(reporter_field, dict) else reporter_field
        )
        priority = _stringify_scalar(priority_field.get("name") if isinstance(priority_field, dict) else priority_field)
        updated = _stringify_scalar(fields.get("updated") if isinstance(fields, dict) else None)
        due_date = _stringify_scalar(_extract_field_value(fields, "duedate", "dueDate"))
        start_date = _stringify_scalar(_extract_field_value(fields, "startdate", "startDate", "customfield_10015"))
        labels = _extract_string_list(_extract_field_value(fields, "labels"))
        sprints = _extract_sprint_names(_extract_field_value(fields, "sprint", "sprints", "customfield_10020"))
        story_points = _extract_story_points(fields)
        team_raw = _extract_field_value(fields, "team", "customfield_10001")
        team = _stringify_scalar(team_raw) or _adf_to_text(team_raw)
        development = _extract_development_summary(_extract_field_value(fields, "development"))
        issue_type = _stringify_scalar(
            fields.get("issuetype", {}).get("name")
            if isinstance(fields.get("issuetype"), dict)
            else fields.get("issuetype")
        )
        parent_field = fields.get("parent") if isinstance(fields.get("parent"), dict) else {}
        parent_fields = parent_field.get("fields") if isinstance(parent_field.get("fields"), dict) else {}
        parent_key = _stringify_scalar(
            parent_field.get("key") if isinstance(parent_field, dict) else fields.get("parent")
        ).upper()
        parent_summary = _stringify_scalar(parent_fields.get("summary"))
        parent_description = _adf_to_text(parent_fields.get("description")) or _stringify_scalar(
            parent_fields.get("description")
        )
        attachments = _extract_attachments(fields.get("attachment"))
        comments = _extract_comments(fields.get("comment"))
        history = _extract_history(issue.get("changelog"))
        ticket_url = _stringify_scalar(issue.get("self")) or _stringify_scalar(issue.get("url"))
        return {
            "key": key,
            "summary": summary,
            "description": description,
            "status": status,
            "status_id": status_id,
            "assignee": assignee,
            "reporter": reporter,
            "priority": priority,
            "updated": updated,
            "due_date": due_date,
            "start_date": start_date,
            "labels": labels,
            "sprints": sprints,
            "story_points": story_points,
            "team": team,
            "development": development,
            "issue_type": issue_type,
            "parent_key": parent_key,
            "parent_summary": parent_summary,
            "parent_description": parent_description,
            "is_subtask": _is_subtask(issue_type, parent_key),
            "attachments": attachments,
            "attachments_count": len(attachments),
            "comments": comments,
            "history": history,
            "url": ticket_url,
        }

    for payload in _extract_json_payloads_from_content(result):
        if not isinstance(payload, dict):
            continue
        issues = payload.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                ticket = parse_issue(issue)
                if ticket:
                    tickets.append(ticket)
            continue
        single_issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else payload
        if isinstance(single_issue, dict):
            ticket = parse_issue(single_issue)
            if ticket:
                tickets.append(ticket)
    return tickets


def _extract_tickets(result: dict[str, Any]) -> list[dict[str, Any]]:
    issue_tickets = _extract_jira_issues(result)
    if issue_tickets:
        return issue_tickets

    by_key: dict[str, dict[str, Any]] = {}

    def merge_ticket(ticket: dict[str, Any]) -> None:
        key = ticket.get("key", "").strip().upper()
        if not key:
            return
        existing = by_key.get(key)
        if not existing:
            by_key[key] = ticket
            return
        for field in (
            "summary",
            "description",
            "status",
            "status_id",
            "assignee",
            "reporter",
            "priority",
            "updated",
            "due_date",
            "start_date",
            "story_points",
            "team",
            "development",
            "url",
            "issue_type",
            "parent_key",
            "parent_summary",
            "parent_description",
        ):
            if not existing.get(field) and ticket.get(field):
                existing[field] = ticket[field]
        for list_field in ("labels", "sprints"):
            existing_values = existing.get(list_field) if isinstance(existing.get(list_field), list) else []
            incoming_values = ticket.get(list_field) if isinstance(ticket.get(list_field), list) else []
            if not existing_values and incoming_values:
                existing[list_field] = incoming_values
        for list_field in ("comments", "history"):
            existing_values = existing.get(list_field) if isinstance(existing.get(list_field), list) else []
            incoming_values = ticket.get(list_field) if isinstance(ticket.get(list_field), list) else []
            if not existing_values and incoming_values:
                existing[list_field] = incoming_values
        existing_attachments = existing.get("attachments") if isinstance(existing.get("attachments"), list) else []
        incoming_attachments = ticket.get("attachments") if isinstance(ticket.get("attachments"), list) else []
        if not existing_attachments and incoming_attachments:
            existing["attachments"] = incoming_attachments
            existing["attachments_count"] = len(incoming_attachments)
        if not existing.get("is_subtask"):
            existing["is_subtask"] = bool(ticket.get("is_subtask"))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            parsed = _extract_ticket_from_mapping(value)
            if parsed:
                merge_ticket(parsed)
            for nested in value.values():
                walk(nested)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)

    text = _extract_ticket_text(result)
    for match in ISSUE_KEY_RE.findall(text):
        normalized = match.upper()
        if normalized not in by_key:
            by_key[normalized] = {
                "key": normalized,
                "summary": "",
                "description": "",
                "status": "",
                "assignee": "",
                "reporter": "",
                "priority": "",
                "updated": "",
                "due_date": "",
                "start_date": "",
                "labels": [],
                "sprints": [],
                "story_points": "",
                "team": "",
                "development": "",
                "issue_type": "",
                "parent_key": "",
                "parent_summary": "",
                "parent_description": "",
                "is_subtask": False,
                "attachments": [],
                "attachments_count": 0,
                "comments": [],
                "history": [],
                "url": "",
            }

    return list(by_key.values())


class JiraMCPAgent:
    def __init__(self, registry_mode: str = "codex") -> None:
        self.registry_mode = "agents"
        self._make_agent_id = make_agent_id
        self._register_agent = register_agent
        self._mark_agent_start = mark_agent_start
        self._mark_agent_end = mark_agent_end
        self.agent_id = self._make_agent_id(CONFIG.group, CONFIG.name)
        self.llm = LLMClient()

    def register(self) -> None:
        self._register_agent(
            AgentDefinition(
                id=self.agent_id,
                name=CONFIG.name,
                provider=None,
                model=None,
                group=CONFIG.group,
                role=CONFIG.role,
                kind="agent",
                dependencies=[],
                source="app/agents_jira/runtime.py",
                description=CONFIG.description,
                capabilities=[
                    "jira",
                    "mcp",
                    "ticket_fetch",
                    "ticket_list",
                    "ticket_view",
                    "ticket_create",
                    "ticket_edit",
                ],
            )
        )

    @staticmethod
    def _resolve_server(config: MCPConfig) -> str:
        tooling = config.tooling.get("jira") if config.tooling else None
        configured = str(tooling.get("server") or "").strip() if isinstance(tooling, dict) else ""
        if configured and configured in config.servers:
            return configured
        for name in config.servers:
            if "atlassian" in name.lower() or "jira" in name.lower():
                return name
        if not config.servers:
            raise RuntimeError("No MCP servers configured.")
        return next(iter(config.servers.keys()))

    @staticmethod
    def _resolve_tooling(config: MCPConfig) -> dict[str, str]:
        tooling = config.tooling.get("jira") if config.tooling else None
        if not isinstance(tooling, dict):
            return {}
        return {str(key): str(value) for key, value in tooling.items()}

    @staticmethod
    def _pick_tool(tools: list[dict[str, Any]], configured_tool: str | None = None) -> str:
        if not tools:
            raise RuntimeError("No MCP tools available on the selected server.")
        if configured_tool:
            for tool in tools:
                if _tool_name(tool) == configured_tool:
                    return configured_tool
        names = [_tool_name(tool) for tool in tools if _tool_name(tool)]
        if "searchJiraIssuesUsingJql" in names:
            return "searchJiraIssuesUsingJql"
        if "search" in names:
            return "search"

        scored: list[tuple[int, str]] = []
        for tool in tools:
            name = _tool_name(tool)
            if not name:
                continue
            lowered_name = name.lower()
            description = str(tool.get("description") or "").lower()
            score = 0
            for keyword, points in (
                ("jira", 5),
                ("issue", 5),
                ("ticket", 5),
                ("backlog", 5),
                ("search", 4),
                ("query", 4),
                ("jql", 4),
                ("list", 2),
            ):
                if keyword in lowered_name:
                    score += points
                if keyword in description:
                    score += 1
            scored.append((score, name))
        if not scored:
            raise RuntimeError("No usable MCP tool names found.")
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _convert_value_for_schema(value: Any, schema: dict[str, Any]) -> Any:
        value_type = str(schema.get("type") or "").lower()
        if value_type == "integer":
            try:
                return int(str(value))
            except Exception:
                return value
        if value_type == "number":
            try:
                return float(str(value))
            except Exception:
                return value
        if value_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        if value_type == "array":
            if isinstance(value, list):
                return value
            return [value]
        if value_type == "object":
            if isinstance(value, dict):
                return value
            return {"value": value}
        return value

    @staticmethod
    def _infer_action(user_message: str) -> str:
        primary_text = JiraMCPAgent._primary_user_text(user_message)
        lowered = primary_text.lower()
        if JiraMCPAgent._has_explicit_create_intent(primary_text):
            return "create"
        if JiraMCPAgent._has_overwhelming_edit_intent(primary_text):
            return "edit"
        if ISSUE_KEY_RE.search(primary_text or "") and any(
            token in lowered for token in ("view", "show", "open", "read", "details", "status", "summary")
        ):
            return "view"
        if any(token in lowered for token in ("list", "all tickets", "backlog", "search", "find", "jql")):
            return "list"
        if ISSUE_KEY_RE.search(primary_text or ""):
            return "view"
        return "list"

    @staticmethod
    def _has_explicit_create_intent(user_message: str) -> bool:
        lowered = JiraMCPAgent._primary_user_text(user_message).lower()
        if any(
            re.search(pattern, lowered)
            for pattern in (
                r"\bcreate\b[\w\s]{0,24}\b(ticket|issue|subtask|subtasks|child issue|child issues)\b",
                r"\bnew\s+(ticket|issue|subtask|subtasks|child issue|child issues)\b",
                r"\badd\b\s+(?:a\s+|an\s+)?(?:new\s+)?(ticket|issue|subtask|subtasks|child issue|child issues)\b",
                r"\b(open|raise|log)\b\s+(?:a\s+|an\s+)?(?:new\s+)?(ticket|issue)\b",
                r"\bcreate\s+(?:me\s+)?(?:a\s+|an\s+)?(?:brand[-\s]+new\s+|new\s+|another\s+|separate\s+)(ticket|issue|task|story|bug)\b",
                r"\b(?:brand[-\s]+new|another|separate)\s+(ticket|issue|task|story|bug)\b",
                r"\bcreate\s+(?:it|one)\b",
            )
        ):
            return True
        return False

    @staticmethod
    def _has_overwhelming_edit_intent(user_message: str) -> bool:
        primary_text = JiraMCPAgent._primary_user_text(user_message)
        lowered = primary_text.lower()
        has_issue_key = bool(ISSUE_KEY_RE.search(primary_text))
        references_existing_ticket = has_issue_key or any(token in lowered for token in ("ticket", "issue", "this"))

        if any(
            token in lowered
            for token in (
                "add comment",
                "comment on",
                "comment ",
                "transition ",
                "move to ",
                "move ticket",
                "assign ",
                "set status",
                "status to ",
                "mark as ",
            )
        ):
            return True

        if JiraMCPAgent._is_description_update_request(primary_text) and references_existing_ticket:
            return True

        if JiraMCPAgent._extract_edit_field_updates(primary_text):
            return True

        if references_existing_ticket and re.search(r"\b(update|edit|change|modify|revise|rename|retitle)\b", lowered):
            return True

        return False

    @staticmethod
    def _is_terse_create_follow_up(user_message: str) -> bool:
        primary_text = JiraMCPAgent._primary_user_text(user_message).strip()
        if not primary_text or not JiraMCPAgent._has_explicit_create_intent(primary_text):
            return False
        if any(
            re.fullmatch(pattern, primary_text, re.IGNORECASE)
            for pattern in (
                r"(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?create\s+(?:me\s+)?(?:a\s+|an\s+)?(?:brand[-\s]+new\s+|new\s+|another\s+|separate\s+)?(?:jira\s+)?(?:ticket|issue|task)\.?",
                r"(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?create\s+(?:it|one)\.?",
                r"(?:please\s+)?(?:add|open|raise)\s+(?:a\s+|an\s+)?(?:brand[-\s]+new\s+|new\s+)?(?:jira\s+)?(?:ticket|issue)\.?",
            )
        ):
            return True

        titles = JiraMCPAgent._extract_create_titles(primary_text)
        if titles:
            return False

        summary = JiraMCPAgent._extract_primary_create_summary(primary_text).strip().lower()
        return summary in {"new jira ticket", "new ticket", "jira ticket", "ticket", "issue", "task"}

    @staticmethod
    def _extract_issue_key(user_message: str) -> str | None:
        keys = JiraMCPAgent._extract_issue_keys(user_message)
        return keys[0] if keys else None

    @staticmethod
    def _extract_issue_keys(user_message: str) -> list[str]:
        matches = ISSUE_KEY_RE.findall(user_message or "")
        ordered: list[str] = []
        for raw in matches:
            key = str(raw or "").strip().upper()
            if not key or key in ordered:
                continue
            ordered.append(key)
        return ordered

    @staticmethod
    def _requests_subtask_updates(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        return any(token in lowered for token in ("subtask", "subtasks", "child issue", "child issues"))

    @staticmethod
    def _requests_parent_ticket_update(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        if any(token in lowered for token in PARENT_UPDATE_TOKENS):
            return True
        if ("subtask" in lowered or "child issue" in lowered) and re.search(
            r"\b(?:update|edit|change)\s+[A-Z][A-Z0-9]+-\d+\b",
            user_message or "",
            re.IGNORECASE,
        ):
            return True
        return bool(re.search(r"\balso\s+update\b", lowered))

    @staticmethod
    def _is_description_update_request(user_message: str) -> bool:
        primary_text = JiraMCPAgent._primary_user_text(user_message)
        lowered = primary_text.lower()
        if not lowered:
            return False

        if any(token in lowered for token in DESCRIPTION_UPDATE_TOKENS) or JiraMCPAgent._is_ticket_rewrite_request(
            primary_text
        ):
            return True

        if JiraMCPAgent._is_comment_request(primary_text) or JiraMCPAgent._is_transition_request(primary_text):
            return False

        references_existing_ticket = bool(ISSUE_KEY_RE.search(primary_text)) or any(
            token in lowered
            for token in (
                "ticket",
                "issue",
                "story",
                "task",
                "this ticket",
                "this issue",
                "that ticket",
                "that issue",
            )
        )
        if not references_existing_ticket:
            return False

        natural_content_update_patterns = (
            r"\bkeep\b.*\b(?:existing|current)\b.*\b(?:content|description|details|scope)\b",
            r"\b(?:just|also)\s+add\b.*\b(?:addition|details?|scope|requirements?|acceptance criteria|content)\b",
            r"\b(?:add|include|append|incorporate|expand|extend|augment)\b.*\b(?:details?|scope|requirements?|acceptance criteria|content)\b",
        )
        return any(re.search(pattern, lowered) for pattern in natural_content_update_patterns)

    @staticmethod
    def _is_ticket_rewrite_request(user_message: str) -> bool:
        lowered = JiraMCPAgent._primary_user_text(user_message).lower()
        if not lowered:
            return False

        rewrite_verbs = ("rewrite", "reword", "revise", "repurpose", "replace", "refresh", "overhaul")
        rewrite_subjects = (
            "ticket",
            "issue",
            "story",
            "task",
            "description",
            "summary",
            "content",
            "requirements",
            "acceptance criteria",
            "scope",
            "details",
        )
        if any(verb in lowered for verb in rewrite_verbs):
            if any(subject in lowered for subject in rewrite_subjects):
                return True
            if re.search(r"\b(?:rewrite|reword|revise|repurpose|replace|refresh|overhaul)\b.*\bthis\b", lowered):
                return True

        return bool(
            re.search(
                r"\b(?:make|turn)\b.*\b(?:this|the)\s+(?:ticket|issue|story|task)\b.*\binto\b",
                lowered,
            )
        )

    @staticmethod
    def _reduce_to_primary_issue_for_singular_mutation(
        user_message: str,
        requested_issue_keys: list[str],
    ) -> tuple[list[str], list[str]]:
        target_keys = JiraMCPAgent._normalize_issue_keys(requested_issue_keys)
        if len(target_keys) <= 1 or JiraMCPAgent._requests_subtask_updates(user_message):
            return target_keys, []

        lowered = JiraMCPAgent._primary_user_text(user_message).lower()
        plural_markers = (
            "both",
            "all tickets",
            "all issues",
            "each ticket",
            "each issue",
            "these tickets",
            "these issues",
            "tickets",
            "issues",
            "subtasks",
            "child issues",
        )
        singular_markers = (
            "this ticket",
            "this issue",
            "this story",
            "this task",
            "the ticket",
            "the issue",
            "the story",
            "the task",
        )

        if any(marker in lowered for marker in plural_markers):
            return target_keys, []

        if not any(marker in lowered for marker in singular_markers) and not JiraMCPAgent._is_ticket_rewrite_request(
            user_message
        ):
            return target_keys, []

        contextual_keys = target_keys[1:]
        warning = (
            f"Multiple Jira keys were referenced, so the request was applied only to {target_keys[0]}; "
            f"treated as context only: {', '.join(contextual_keys)}."
        )
        return [target_keys[0]], [warning]

    @staticmethod
    def _has_direct_field_update_intent(user_message: str) -> bool:
        if JiraMCPAgent._is_description_update_request(user_message):
            return True
        return bool(JiraMCPAgent._extract_edit_field_updates(user_message))

    @staticmethod
    def _normalize_priority_name(raw_priority: str) -> str:
        normalized = " ".join(str(raw_priority or "").strip().split())
        if not normalized:
            return ""

        lowered = normalized.lower()
        aliases = {
            "highest": "Highest",
            "highest priority": "Highest",
            "critical": "Highest",
            "blocker": "Highest",
            "urgent": "Highest",
            "high": "High",
            "medium": "Medium",
            "med": "Medium",
            "normal": "Medium",
            "low": "Low",
            "lowest": "Lowest",
            "trivial": "Lowest",
            "minor": "Low",
        }
        if lowered in aliases:
            return aliases[lowered]
        if re.fullmatch(r"p[0-5]", lowered):
            return lowered.upper()
        return normalized[:60]

    @staticmethod
    def _extract_priority_name(user_message: str) -> str:
        text = str(user_message or "").strip()
        if not text:
            return ""

        for pattern in (PRIORITY_INLINE_RE, PRIORITY_SUFFIX_RE):
            match = pattern.search(text)
            if not match:
                continue
            candidate = str(match.group("priority") or "").strip(" \t'\"")
            if not candidate:
                continue
            lowered_candidate = candidate.lower()
            stop_tokens = (" on ", " for ", " in ", " with ", " and ")
            for token in stop_tokens:
                if token in lowered_candidate:
                    split_index = lowered_candidate.find(token)
                    candidate = candidate[:split_index].strip()
                    break
            if candidate:
                return JiraMCPAgent._normalize_priority_name(candidate)
        return ""

    @staticmethod
    def _normalize_edit_field_name(raw_field: str) -> str:
        normalized = " ".join(str(raw_field or "").strip().lower().replace("-", " ").split())
        if not normalized:
            return ""
        aliases = {
            "summary": "summary",
            "title": "summary",
            "priority": "priority",
            "severity": "priority",
            "assignee": "assignee",
            "reporter": "reporter",
            "label": "labels",
            "labels": "labels",
            "due date": "duedate",
            "duedate": "duedate",
            "start date": "startdate",
            "startdate": "startdate",
            "sprint": "sprint",
            "story point": "story_points",
            "story points": "story_points",
            "storypoints": "story_points",
            "team": "team",
        }
        if normalized in aliases:
            return aliases[normalized]
        compact = normalized.replace(" ", "")
        if compact in aliases:
            return aliases[compact]
        if re.fullmatch(r"customfield_\d+", compact):
            return compact
        if " " not in normalized and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", normalized):
            return normalized
        return ""

    @staticmethod
    def _sanitize_assignment_value(raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""
        value = re.split(
            r"\s+\band\s+(?=(?:summary|title|priority|severity|assignee|reporter|labels?|"
            r"due(?:\s|-)?date|start(?:\s|-)?date|sprint|story\s*points?|storypoints|team)\b)",
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        value = re.split(r"\s+\bon\s+[A-Z][A-Z0-9]+-\d+\b", value, maxsplit=1)[0]
        return value.strip().strip("'\"").rstrip(".,")

    @staticmethod
    def _coerce_edit_field_value(field_name: str, raw_value: str) -> Any:
        value = JiraMCPAgent._sanitize_assignment_value(raw_value)
        if not value:
            return ""
        if field_name == "summary":
            return value[:180]
        if field_name == "priority":
            normalized = JiraMCPAgent._normalize_priority_name(value)
            return {"name": normalized} if normalized else ""
        if field_name == "labels":
            labels: list[str] = []
            for chunk in re.split(r"[,\n]", value):
                cleaned = str(chunk).strip()
                if cleaned and cleaned not in labels:
                    labels.append(cleaned)
            return labels
        if field_name == "story_points":
            numeric = value.replace(",", "")
            try:
                as_float = float(numeric)
            except ValueError:
                return value
            if as_float.is_integer():
                return int(as_float)
            return as_float
        return value

    @staticmethod
    def _extract_edit_field_updates(user_message: str) -> dict[str, Any]:
        text = str(user_message or "").strip()
        if not text:
            return {}

        updates: dict[str, Any] = {}

        for match in EDIT_FIELD_ASSIGNMENT_RE.finditer(text):
            raw_field = str(match.group("field") or "").strip()
            raw_value = str(match.group("value") or "").strip()
            field_name = JiraMCPAgent._normalize_edit_field_name(raw_field)
            if not field_name or field_name == "description":
                continue
            coerced = JiraMCPAgent._coerce_edit_field_value(field_name, raw_value)
            if coerced is None:
                continue
            if isinstance(coerced, str) and not coerced.strip():
                continue
            if isinstance(coerced, list) and not coerced:
                continue
            updates[field_name] = coerced

        for match in GENERIC_EDIT_SET_RE.finditer(text):
            raw_field = str(match.group("field") or "").strip()
            raw_value = str(match.group("value") or "").strip()
            lowered_raw_field = raw_field.lower()
            if ISSUE_KEY_RE.search(raw_field):
                continue
            if any(token in lowered_raw_field for token in ("jira", "ticket", "issue")):
                continue
            field_name = JiraMCPAgent._normalize_edit_field_name(raw_field)
            if not field_name or field_name == "description" or field_name in updates:
                continue
            coerced = JiraMCPAgent._coerce_edit_field_value(field_name, raw_value)
            if coerced is None:
                continue
            if isinstance(coerced, str) and not coerced.strip():
                continue
            if isinstance(coerced, list) and not coerced:
                continue
            updates[field_name] = coerced

        return updates

    @staticmethod
    def _truncate_text(value: str, max_chars: int = 280) -> str:
        text = " ".join((value or "").strip().split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _primary_user_text(user_message: str) -> str:
        text = str(user_message or "")
        marker_index = text.find(ATTACHMENT_CONTEXT_MARKER)
        if marker_index < 0:
            return text
        return text[:marker_index]

    @staticmethod
    def _normalize_similarity_text(value: str) -> str:
        text = ISSUE_KEY_RE.sub(" ", str(value or "").lower())
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _similarity_tokens(value: str) -> set[str]:
        stop_words = {
            "a",
            "an",
            "and",
            "attached",
            "attachment",
            "change",
            "create",
            "file",
            "for",
            "image",
            "issue",
            "jira",
            "match",
            "new",
            "page",
            "please",
            "style",
            "that",
            "the",
            "ticket",
            "this",
            "too",
            "ui",
            "want",
            "with",
        }
        return {
            token
            for token in JiraMCPAgent._normalize_similarity_text(value).split()
            if len(token) >= 3 and token not in stop_words and not token.isdigit()
        }

    @staticmethod
    def _allows_duplicate_create(user_message: str) -> bool:
        lowered = str(user_message or "").lower()
        if JiraMCPAgent._is_terse_create_follow_up(user_message):
            return True
        return any(
            re.search(pattern, lowered)
            for pattern in (
                r"\banother\s+(ticket|issue|task|story|bug)\b",
                r"\bseparate\s+(ticket|issue|task|story|bug)\b",
                r"\bbrand[-\s]+new\s+(ticket|issue|task|story|bug)\b",
                r"\bcreate\s+(?:a\s+|an\s+)?(another|separate|new|brand[-\s]+new)\s+(ticket|issue|task|story|bug)\b",
                r"\bcreate\s+anyway\b",
                r"\bduplicate\b",
                r"\beven if\b.*\bexists\b",
                r"\bdo not\b.*\b(reuse|dedup(?:e|lication)|update|edit)\b",
            )
        )

    @staticmethod
    def _find_duplicate_ticket_for_create(
        requested_summary: str,
        candidate_tickets: list[dict[str, Any]],
        *,
        user_message: str,
    ) -> dict[str, Any] | None:
        if JiraMCPAgent._allows_duplicate_create(user_message):
            return None

        requested_norm = JiraMCPAgent._normalize_similarity_text(requested_summary)
        requested_tokens = JiraMCPAgent._similarity_tokens(requested_summary)
        if not requested_norm:
            return None

        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for ticket in candidate_tickets:
            if not isinstance(ticket, dict):
                continue
            candidate_summary = str(ticket.get("summary") or "").strip()
            candidate_norm = JiraMCPAgent._normalize_similarity_text(candidate_summary)
            if not candidate_norm:
                continue

            sequence_ratio = SequenceMatcher(None, requested_norm, candidate_norm).ratio()
            candidate_tokens = JiraMCPAgent._similarity_tokens(candidate_summary)
            shared_tokens = requested_tokens & candidate_tokens
            union_tokens = requested_tokens | candidate_tokens
            token_ratio = (len(shared_tokens) / len(union_tokens)) if union_tokens else 0.0

            is_duplicate = (
                requested_norm == candidate_norm
                or sequence_ratio >= 0.88
                or (
                    len(shared_tokens) >= 4
                    and token_ratio >= 0.6
                )
            )
            if not is_duplicate:
                continue

            score = max(sequence_ratio, token_ratio)
            if score > best_score:
                best_score = score
                best_match = ticket

        return best_match

    @staticmethod
    def _extract_parent_constraints(parent_description: str, max_items: int = 4) -> list[str]:
        text = str(parent_description or "")
        if not text.strip():
            return []
        constraints: list[str] = []
        for raw_line in text.splitlines():
            cleaned = raw_line.strip().lstrip("-*").strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in {
                "user story",
                "description",
                "acceptance criteria",
                "background",
                "scope",
                "requirements",
            }:
                continue
            if any(token in lowered for token in ("must", "should", "include", "use", "made using")):
                if cleaned not in constraints:
                    constraints.append(cleaned)
            if len(constraints) >= max_items:
                break
        return constraints

    @staticmethod
    def _build_issue_specific_description(section_content_by_title: dict[str, str]) -> str:
        lines: list[str] = []
        for title in DESCRIPTION_SECTION_TITLES:
            content = str(section_content_by_title.get(title) or "").strip()
            if not content:
                continue
            lines.append(f"## {title}")
            lines.append(content)
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_generated_description(raw_description: str) -> str | None:
        text = str(raw_description or "").strip()
        if not text:
            return None

        heading_pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(text))
        if not matches:
            return None

        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            title = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if title in DESCRIPTION_SECTION_TITLES and content:
                sections[title] = content

        if any(not sections.get(title) for title in DESCRIPTION_SECTION_TITLES):
            return None
        return JiraMCPAgent._build_issue_specific_description(sections)

    async def _generate_issue_specific_description(
        self,
        user_message: str,
        issue_key: str,
        issue_summary: str,
        existing_description: str = "",
        parent_key: str = "",
        parent_summary: str = "",
        parent_description: str = "",
    ) -> str:
        summary = issue_summary.strip() or issue_key.strip() or "this subtask"
        normalized_issue_key = issue_key.strip().upper()
        normalized_parent_key = parent_key.strip().upper()
        normalized_parent_summary = parent_summary.strip()
        parent_label = (
            f"{normalized_parent_key}: {normalized_parent_summary}"
            if normalized_parent_key and normalized_parent_summary
            else normalized_parent_key or normalized_parent_summary or "Not specified"
        )
        request_text = self._truncate_text(user_message, 500)
        parent_context = self._truncate_text(parent_description, 700)
        existing_excerpt = self._truncate_text(existing_description, 500)
        parent_constraints = self._extract_parent_constraints(parent_description)
        headings = "\n".join(f"- {title}" for title in DESCRIPTION_SECTION_TITLES)

        system_prompt = (
            "You write Jira issue descriptions. "
            "Return markdown only. "
            "Use exactly the required headings in the required order and generate substantive, ticket-specific content."
        )
        user_prompt_lines = [
            "Generate a Jira description with exactly these headings in this exact order:",
            headings,
            "",
            "Rules:",
            "- Output markdown only.",
            "- Use each heading exactly once as `## <Heading>`.",
            "- Do not include additional headings.",
            "- Do not include placeholders or template tokens.",
            "- Keep details specific to the ticket and user request.",
            "",
            "Context:",
            f"- Ticket key: {normalized_issue_key or 'n/a'}",
            f"- Ticket summary: {summary}",
            f"- Parent: {parent_label}",
            f"- User request: {request_text or 'n/a'}",
            f"- Parent description/context: {parent_context or 'n/a'}",
            f"- Existing description excerpt: {existing_excerpt or 'n/a'}",
        ]
        if parent_constraints:
            user_prompt_lines.append(f"- Parent constraints to honor: {'; '.join(parent_constraints[:6])}")
        user_prompt = "\n".join(user_prompt_lines).strip()

        llm_errors: list[str] = []
        generated_text = ""
        function_settings = get_llm_function_settings("jira_description_generation")
        openai_model = str(function_settings.get("openai_model") or "").strip()
        anthropic_model = str(function_settings.get("anthropic_model") or "").strip()
        if self.llm.openai_api_key and openai_model:
            try:
                generated_text = await self.llm.openai_response(
                    system_prompt,
                    user_prompt,
                    model=openai_model,
                )
            except Exception as exc:
                llm_errors.append(f"OpenAI: {str(exc).strip() or type(exc).__name__}")
        if not generated_text and self.llm.anthropic_api_key and anthropic_model:
            try:
                generated_text = await self.llm.anthropic_response(
                    system_prompt,
                    user_prompt,
                    model=anthropic_model,
                )
            except Exception as exc:
                llm_errors.append(f"Anthropic: {str(exc).strip() or type(exc).__name__}")

        normalized_generated = self._normalize_generated_description(generated_text)
        if normalized_generated:
            return normalized_generated

        if generated_text:
            preview = self._truncate_text(generated_text, 240)
            raise RuntimeError(
                "LLM description generation returned invalid markdown heading structure. "
                f"Preview: {preview}"
            )
        if llm_errors:
            raise RuntimeError("LLM description generation unavailable: " + " | ".join(llm_errors[:2]))
        raise RuntimeError("LLM description generation unavailable: no provider API key configured.")

    @staticmethod
    def _is_field_edit_request(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        if any(
            token in lowered
            for token in (
                "transition",
                "set status",
                "move to ",
                "assign ",
                "comment",
                "worklog",
            )
        ):
            return False
        return True

    @staticmethod
    def _is_comment_request(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        return "comment" in lowered

    @staticmethod
    def _is_transition_request(user_message: str) -> bool:
        lowered = (user_message or "").lower()
        return any(
            token in lowered
            for token in (
                "transition",
                "move to ",
                "set status",
                "status to ",
                "mark as ",
                "move ticket",
            )
        )

    @staticmethod
    def _extract_comment_body(user_message: str) -> str:
        text = (user_message or "").strip()
        if not text:
            return "Automated update from workflow agent."
        match = re.search(r"\bcomment\b\s*(?:on|for)?\s*[:\-]\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
        if match:
            body = str(match.group(1) or "").strip()
            if body:
                return body[:3000]
        return f"Automated update request: {text[:280]}"

    @staticmethod
    def _extract_transition_target(user_message: str) -> str | None:
        lowered = (user_message or "").lower()
        for token, normalized in (
            ("in progress", "in progress"),
            ("to do", "to do"),
            ("done", "done"),
            ("review", "review"),
            ("qa", "qa"),
            ("blocked", "blocked"),
            ("ready", "ready"),
        ):
            if token in lowered:
                return normalized
        match = re.search(r"(?:move|transition|status(?:\\s+to)?)\\s+(?:to\\s+)?([A-Za-z][A-Za-z\\s-]{1,40})", user_message or "", re.IGNORECASE)
        if match:
            candidate = str(match.group(1) or "").strip()
            if candidate:
                return candidate.lower()
        return None

    @staticmethod
    def _looks_like_attachment_filename(value: str) -> bool:
        candidate = str(value or "").strip().strip("'\"")
        if not candidate or "/" in candidate or "\\" in candidate:
            return False
        return bool(re.fullmatch(r".+\.(?:png|jpe?g|gif|webp|svg|pdf|fig|sketch|xd)$", candidate, re.IGNORECASE))

    @staticmethod
    def _clean_create_title_candidate(raw: str) -> str:
        value = " ".join(str(raw or "").strip().split())
        if not value:
            return ""
        value = re.sub(
            r"\b(?:can you|could you|would you|please|thanks|thank you)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(r"\bon\s+[A-Z][A-Z0-9]+-\d+\b$", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"\bfor\s+[A-Z][A-Z0-9]+-\d+\b$", "", value, flags=re.IGNORECASE).strip()
        value = value.strip(" \t-,:.;")
        lowered = value.lower()
        if lowered.startswith("adding "):
            value = "Add " + value[7:]
        elif lowered.startswith("to add "):
            value = "Add " + value[7:]
        elif lowered.startswith("add "):
            value = "Add " + value[4:]
        elif lowered.startswith("qa"):
            value = "QA " + value[2:].strip() if len(value) > 2 else "QA"
        value = " ".join(value.split()).strip(" \t-,:.;")
        if not value or JiraMCPAgent._looks_like_attachment_filename(value):
            return ""
        if value.lower() in {
            "this",
            "that",
            "it",
            "one",
            "same",
            "same one",
            "ticket",
            "issue",
            "task",
            "jira ticket",
            "new ticket",
            "new jira ticket",
        }:
            return ""
        if value.islower() or re.match(r"^(create|add|implement|allow|enable|support|build)\b", value, re.IGNORECASE):
            value = value[0].upper() + value[1:]
        return value[:180]

    @staticmethod
    def _requests_create_parent_with_subtasks(user_message: str) -> bool:
        primary_text = JiraMCPAgent._primary_user_text(user_message)
        lowered = primary_text.lower()
        if ISSUE_KEY_RE.search(primary_text):
            return False
        return bool(
            re.search(
                r"\b(ticket|issue)\b[\w\s]{0,30}\b(?:and|with)\b[\w\s]{0,10}\b(subtasks|child issues)\b",
                lowered,
            )
            or re.search(
                r"\b(subtasks|child issues)\b[\w\s]{0,30}\b(?:and|with)\b[\w\s]{0,10}\b(ticket|issue)\b",
                lowered,
            )
        )

    @staticmethod
    def _extract_primary_create_summary(user_message: str) -> str:
        titles = JiraMCPAgent._extract_create_titles(user_message)
        if titles:
            return titles[0]

        text = JiraMCPAgent._primary_user_text(user_message).strip()
        if not text:
            return "New Jira ticket"

        singular_colon_match = re.search(
            r"\b(?:create|add|open|raise|log)\b[\w\s]{0,40}\b(ticket|issue|task|story|bug)\s*:\s*(?P<body>[^\n]+)",
            text,
            re.IGNORECASE,
        )
        if singular_colon_match:
            body = str(singular_colon_match.group("body") or "").strip()
            if body:
                first_clause = re.split(r"[.;]", body, maxsplit=1)[0]
                cleaned = JiraMCPAgent._clean_create_title_candidate(first_clause)
                if cleaned:
                    return cleaned

        task_match = re.search(r"\btask\s*:\s*(?P<body>.+)$", text, re.IGNORECASE | re.DOTALL)
        if task_match:
            body = str(task_match.group("body") or "").strip()
            for line in body.splitlines():
                cleaned = JiraMCPAgent._clean_create_title_candidate(line)
                if cleaned:
                    return cleaned

        for line in text.splitlines():
            cleaned = JiraMCPAgent._clean_create_title_candidate(line)
            lowered = cleaned.lower()
            if cleaned and not lowered.startswith(("please create", "create a new jira ticket", "create a jira ticket")):
                return cleaned

        summary = JiraMCPAgent._extract_summary_hint(user_message).strip()
        if JiraMCPAgent._looks_like_attachment_filename(summary):
            return "New Jira ticket"
        return summary[:180] or "New Jira ticket"

    @staticmethod
    def _extract_create_titles(user_message: str) -> list[str]:
        def dedupe(items: list[str]) -> list[str]:
            seen: list[str] = []
            for item in items:
                cleaned = JiraMCPAgent._clean_create_title_candidate(item)
                if not cleaned:
                    continue
                if cleaned in seen:
                    continue
                seen.append(cleaned)
            return seen[:20]

        def is_explicit_multi_title_prefix(prefix: str) -> bool:
            normalized_prefix = " ".join(str(prefix or "").strip().split()).lower()
            if not normalized_prefix:
                return False
            if not re.search(r"\b(tickets|issues|tasks|stories|bugs|subtasks|child issues)\b", normalized_prefix):
                return False
            return bool(
                re.search(r"\b(create|add|open|raise|log|list|titles?|summaries?)\b", normalized_prefix)
            )

        text = JiraMCPAgent._primary_user_text(user_message).strip()
        if not text:
            return []
        if JiraMCPAgent._requests_create_parent_with_subtasks(text):
            return []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        bullet_titles: list[str] = []
        for line in lines:
            cleaned = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()
            if cleaned != line and len(cleaned) >= 3:
                bullet_titles.append(cleaned[:180])
        if bullet_titles:
            return dedupe(bullet_titles)

        sequence_matches = list(
            re.finditer(
                r"\b(first|second|third|then|next|finally)\b[:,-]?",
                text,
                re.IGNORECASE,
            )
        )
        if len(sequence_matches) >= 2:
            sequence_titles: list[str] = []
            for index, match in enumerate(sequence_matches):
                start = match.end()
                end = sequence_matches[index + 1].start() if index + 1 < len(sequence_matches) else len(text)
                candidate = text[start:end].strip(" \t\n\r,.;:-")
                if candidate:
                    sequence_titles.append(candidate)
            if sequence_titles:
                return dedupe(sequence_titles)

        if ":" in text:
            prefix, tail = text.split(":", 1)
            if is_explicit_multi_title_prefix(prefix):
                parts = [part.strip() for part in re.split(r"[,;]", tail) if part.strip()]
                if len(parts) >= 2:
                    return dedupe(parts)
        contextual_titles: list[str] = []
        for pattern in (CREATE_ABOUT_ITEM_RE, CREATE_FOR_ITEM_RE):
            for match in pattern.finditer(text):
                contextual_titles.append(str(match.group("topic") or ""))
        if contextual_titles:
            return dedupe(contextual_titles)
        return []

    @staticmethod
    def _extract_requested_create_count(user_message: str) -> int:
        text = JiraMCPAgent._primary_user_text(user_message).strip()
        if not text:
            return 0
        match = CREATE_COUNT_RE.search(text)
        if not match:
            return 0
        raw_count = str(match.group("count") or "").strip().lower()
        word_to_int = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        if raw_count.isdigit():
            return max(0, min(int(raw_count), 20))
        return int(word_to_int.get(raw_count) or 0)

    @staticmethod
    def _normalize_issue_keys(values: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in values:
            key = str(item or "").strip().upper()
            if not ISSUE_KEY_RE.fullmatch(key):
                continue
            if key in normalized:
                continue
            normalized.append(key)
        return normalized

    @staticmethod
    def _is_issue_type_validation_error(detail: str) -> bool:
        lowered = str(detail or "").lower()
        if "issuetype" not in lowered:
            return False
        return any(
            token in lowered
            for token in (
                "valid issue type",
                "invalid issue type",
                "specify a valid issue type",
            )
        )

    def _resolve_create_issue_type_candidates(self, create_is_subtask: bool) -> list[str]:
        counts: dict[str, int] = {}
        cached = self._load_latest_cached_fetch()
        if cached:
            tickets = cached.get("tickets") if isinstance(cached.get("tickets"), list) else []
            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue
                if bool(ticket.get("is_subtask")) != create_is_subtask:
                    continue
                issue_type = str(ticket.get("issue_type") or "").strip()
                if not issue_type:
                    continue
                counts[issue_type] = int(counts.get(issue_type) or 0) + 1

        ranked_cached = sorted(
            counts.items(),
            key=lambda item: (-int(item[1] or 0), str(item[0]).lower()),
        )
        defaults = ["Subtask", "Sub-task", "Sub Task"] if create_is_subtask else ["Task", "Story", "Bug"]
        candidates = list(defaults)
        for name, _ in ranked_cached:
            if not name:
                continue
            if not create_is_subtask and name.strip().lower() == "epic":
                continue
            if name in candidates:
                continue
            candidates.append(name)
        return candidates

    @staticmethod
    def _extract_transitions(result: dict[str, Any]) -> list[dict[str, str]]:
        transitions: list[dict[str, str]] = []

        def collect_from(value: Any) -> None:
            if isinstance(value, dict):
                if "transitions" in value and isinstance(value.get("transitions"), list):
                    collect_from(value.get("transitions"))
                transition_id = _stringify_scalar(value.get("id"))
                transition_name = _stringify_scalar(value.get("name"))
                to_name = ""
                to_field = value.get("to")
                if isinstance(to_field, dict):
                    to_name = _stringify_scalar(to_field.get("name"))
                if transition_id and (transition_name or to_name):
                    transitions.append({"id": transition_id, "name": transition_name or to_name, "to_name": to_name})
                for nested in value.values():
                    if nested is value.get("transitions"):
                        continue
                    collect_from(nested)
            elif isinstance(value, list):
                for item in value:
                    collect_from(item)

        collect_from(result)
        deduped: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in transitions:
            key = str(item.get("id") or "").strip()
            if not key or key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _is_jira_tool(tool: dict[str, Any]) -> bool:
        name = _tool_name(tool).lower()
        description = str(tool.get("description") or "").lower()
        text = f"{name} {description}"
        if any(token in text for token in ("confluence", "compass", "wiki", "page", "space", "cql")):
            return False
        if "jira" in text:
            return True
        if any(token in text for token in ("issue", "ticket", "jql", "transition")):
            return True
        return False

    @staticmethod
    def _pick_transition(
        transitions: list[dict[str, str]],
        target_status: str | None,
    ) -> tuple[str | None, str]:
        if not transitions:
            return None, "No transitions are available for this issue."
        if not target_status:
            return None, "No target status was parsed from the request."

        target = str(target_status).strip().lower()
        if not target:
            return None, "No target status was parsed from the request."

        for transition in transitions:
            transition_id = str(transition.get("id") or "").strip()
            name = str(transition.get("name") or "").strip().lower()
            to_name = str(transition.get("to_name") or "").strip().lower()
            if not transition_id:
                continue
            if target == name or target == to_name:
                return transition_id, ""

        for transition in transitions:
            transition_id = str(transition.get("id") or "").strip()
            name = str(transition.get("name") or "").strip().lower()
            to_name = str(transition.get("to_name") or "").strip().lower()
            if not transition_id:
                continue
            if target in name or target in to_name:
                return transition_id, ""

        available = [
            str(item.get("to_name") or item.get("name") or "").strip()
            for item in transitions
            if str(item.get("id") or "").strip()
        ]
        available = [item for item in available if item]
        if available:
            return None, f"Requested status `{target_status}` not found. Available: {', '.join(available[:8])}"
        return None, f"Requested status `{target_status}` not found."

    def _set_tool_argument(
        self,
        args: dict[str, Any],
        properties: dict[str, Any],
        names: list[str],
        value: Any,
    ) -> bool:
        if value is None or value == "":
            return False
        property_lookup = {str(key).lower(): str(key) for key in properties}
        for name in names:
            actual = property_lookup.get(str(name).lower())
            if not actual or actual in args:
                continue
            schema_value = properties.get(actual)
            if isinstance(schema_value, dict):
                args[actual] = self._convert_value_for_schema(value, schema_value)
            else:
                args[actual] = value
            return True
        return False

    @staticmethod
    def _summarize_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "by_type": {},
        }
        for item in operations:
            if not isinstance(item, dict):
                continue
            summary["total"] += 1
            status = str(item.get("status") or "").strip().lower()
            operation = str(item.get("operation") or "").strip().lower() or "unknown"
            by_type = summary.get("by_type")
            if isinstance(by_type, dict):
                counts = by_type.get(operation)
                if not isinstance(counts, dict):
                    counts = {"success": 0, "failed": 0, "skipped": 0}
                    by_type[operation] = counts
                if status in {"success", "failed", "skipped"}:
                    counts[status] = int(counts.get(status) or 0) + 1
            if status in {"success", "failed", "skipped"}:
                summary[status] = int(summary.get(status) or 0) + 1
        return summary

    def _ensure_action_target_keys(
        self,
        user_message: str,
        requested_issue_keys: list[str],
        action: str,
        client: MCPClient,
        server_name: str,
        cloud_id: str | None,
        project_key: str | None,
        max_results: int,
        tool_lookup: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        target_keys = self._normalize_issue_keys(requested_issue_keys)
        subtask_keys: list[str] = []
        warnings: list[str] = []

        if self._requests_subtask_updates(user_message):
            resolved_targets, resolved_subtasks, resolved_warnings = self._resolve_target_keys_for_edit(
                user_message=user_message,
                requested_issue_keys=target_keys,
                client=client,
                server_name=server_name,
                cloud_id=cloud_id,
                project_key=project_key,
                max_results=max_results,
                tool_lookup=tool_lookup,
            )
            target_keys = self._normalize_issue_keys(resolved_targets)
            subtask_keys = self._normalize_issue_keys(resolved_subtasks)
            warnings.extend(resolved_warnings)
            return target_keys, subtask_keys, warnings

        target_keys, singular_target_warnings = self._reduce_to_primary_issue_for_singular_mutation(
            user_message,
            target_keys,
        )
        warnings.extend(singular_target_warnings)

        if action in {"edit", "comment", "transition"} and not target_keys:
            raise RuntimeError(
                "No Jira issue keys were detected for a mutating request. "
                "Include ticket keys (for example, DEV-10) or explicitly ask for subtasks."
            )
        return target_keys, subtask_keys, warnings

    def _apply_subtask_parent_guard(
        self,
        user_message: str,
        target_keys: list[str],
        subtask_keys: list[str],
        ticket_context_by_key: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        if not self._requests_subtask_updates(user_message):
            return target_keys, [], []
        if self._requests_parent_ticket_update(user_message):
            return target_keys, [], []

        filtered_targets: list[str] = []
        skipped_parent_keys: list[str] = []
        for key in target_keys:
            context = ticket_context_by_key.get(key) if isinstance(ticket_context_by_key, dict) else None
            is_subtask = bool(context.get("is_subtask")) if isinstance(context, dict) else False
            if key in subtask_keys or is_subtask:
                filtered_targets.append(key)
            else:
                skipped_parent_keys.append(key)

        deduped_filtered = self._normalize_issue_keys(filtered_targets)
        warnings: list[str] = []
        if skipped_parent_keys:
            warnings.append(
                "Skipped parent/top-level ticket(s) unless explicitly requested: "
                + ", ".join(skipped_parent_keys)
            )
        if not deduped_filtered:
            raise RuntimeError(
                "Subtask update request detected, but no subtasks were found. Parent tickets were not edited."
            )
        return deduped_filtered, self._normalize_issue_keys(skipped_parent_keys), warnings

    @staticmethod
    def _extract_summary_hint(user_message: str) -> str:
        message = JiraMCPAgent._primary_user_text(user_message).strip()
        if not message:
            return "New Jira ticket"
        match = CREATE_SUMMARY_RE.search(message)
        summary = str(match.group("summary") or "").strip() if match else ""
        if not summary:
            task_match = re.search(r"\btask\s*:\s*(?P<body>.+)$", message, re.IGNORECASE | re.DOTALL)
            if task_match:
                body = str(task_match.group("body") or "").strip()
                for line in body.splitlines():
                    cleaned = JiraMCPAgent._clean_create_title_candidate(line)
                    if cleaned:
                        return cleaned
        if not summary:
            summary = message
        return summary[:180]

    @staticmethod
    def _tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        return schema if isinstance(schema, dict) else {}

    @staticmethod
    def _tool_properties(tool: dict[str, Any]) -> dict[str, Any]:
        schema = JiraMCPAgent._tool_schema(tool)
        props = schema.get("properties")
        return props if isinstance(props, dict) else {}

    @staticmethod
    def _tool_requires_cloud_id(tool: dict[str, Any]) -> bool:
        schema = JiraMCPAgent._tool_schema(tool)
        props = JiraMCPAgent._tool_properties(tool)
        required = schema.get("required")
        required_names = (
            [str(item).lower() for item in required if item is not None]
            if isinstance(required, list)
            else []
        )
        prop_names = [str(name).lower() for name in props.keys()]
        candidates = required_names + prop_names
        return any(name in {"cloudid", "cloud_id"} or "cloud" in name for name in candidates)

    @staticmethod
    def _score_tool_for_action(tool: dict[str, Any], action: str) -> int:
        name = _tool_name(tool)
        lowered_name = name.lower()
        description = str(tool.get("description") or "").lower()
        text = f"{lowered_name} {description}"

        score = 0
        for keyword, points in (
            ("jira", 3),
            ("issue", 3),
            ("ticket", 3),
            ("atlassian", 2),
        ):
            if keyword in text:
                score += points

        action_keywords: dict[str, tuple[tuple[str, int], ...]] = {
            "list": (
                ("search", 8),
                ("list", 8),
                ("jql", 7),
                ("query", 6),
                ("backlog", 5),
                ("find", 4),
            ),
            "view": (
                ("get", 8),
                ("read", 7),
                ("fetch", 7),
                ("issue", 6),
                ("detail", 5),
                ("search", 4),
            ),
            "create": (
                ("create", 10),
                ("new", 8),
                ("add", 7),
                ("issue", 4),
                ("ticket", 4),
            ),
            "edit": (
                ("update", 10),
                ("edit", 9),
                ("transition", 8),
                ("assign", 7),
                ("comment", 6),
                ("set", 5),
                ("move", 4),
            ),
        }
        for keyword, points in action_keywords.get(action, ()):
            if keyword in text:
                score += points
        return score

    def _rank_tools_for_action(
        self,
        tools: list[dict[str, Any]],
        action: str,
        configured_tool: str | None,
    ) -> list[str]:
        preferred_by_action: dict[str, tuple[str, ...]] = {
            "list": ("searchJiraIssuesUsingJql", "search", "getJiraIssue"),
            "view": ("getJiraIssue", "searchJiraIssuesUsingJql", "search"),
            "create": ("createJiraIssue",),
            "edit": ("editJiraIssue", "transitionJiraIssue", "addCommentToJiraIssue"),
        }
        known_names = {_tool_name(tool) for tool in tools if _tool_name(tool)}
        preferred = [name for name in preferred_by_action.get(action, ()) if name in known_names]

        ranked: list[tuple[int, str]] = []
        for tool in tools:
            name = _tool_name(tool)
            if not name:
                continue
            score = self._score_tool_for_action(tool, action)
            if configured_tool and name == configured_tool:
                score += 12
            lowered_name = name.lower()
            if name in preferred:
                score += 20
            if lowered_name in {"fetch", "search"}:
                description = str(tool.get("description") or "").lower()
                if "jira" not in description and "issue" not in description and "ticket" not in description:
                    score -= 15
            ranked.append((score, name))
        ranked.sort(key=lambda item: item[0], reverse=True)
        deduped: list[str] = []
        for name in preferred:
            if name not in deduped:
                deduped.append(name)
        for _, name in ranked:
            if name in deduped:
                continue
            deduped.append(name)
        return deduped

    @staticmethod
    def _build_fields_payload(
        action: str,
        user_message: str,
        summary_hint: str,
        issue_key: str | None,
        project_key: str | None,
        ticket_context: dict[str, Any] | None = None,
        parent_context: dict[str, Any] | None = None,
        generated_description: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if action == "create":
            if not generated_description:
                raise RuntimeError("Description generation failed: no model-generated description was provided.")
            fields["summary"] = summary_hint
            fields["description"] = generated_description
            fields["issuetype"] = {"name": "Task"}
            if project_key:
                fields["project"] = {"key": project_key}
            return fields

        if action == "edit":
            extracted_updates = JiraMCPAgent._extract_edit_field_updates(user_message)
            if extracted_updates:
                fields.update(extracted_updates)
            edit_summary_match = EDIT_SUMMARY_RE.search(user_message or "")
            edit_summary = str(edit_summary_match.group("summary") or "").strip() if edit_summary_match else ""
            if edit_summary and "summary" not in fields:
                fields["summary"] = edit_summary[:180]
            priority_name = JiraMCPAgent._extract_priority_name(user_message)
            if priority_name and "priority" not in fields:
                fields["priority"] = {"name": priority_name}
            should_update_description = JiraMCPAgent._is_description_update_request(user_message)
            if should_update_description:
                if not generated_description:
                    raise RuntimeError("Description generation failed: no model-generated description was provided.")
                fields["description"] = generated_description
            return fields

        if issue_key:
            fields["key"] = issue_key
        return fields

    def _build_arguments(
        self,
        tool: dict[str, Any],
        backlog_url: str,
        project_key: str | None,
        board_id: str | None,
        cloud_id: str | None,
        max_results: int,
    ) -> dict[str, Any]:
        query_text = (
            "List all Jira tickets currently in backlog for "
            f"project {project_key or '(unknown)'} "
            f"on board {board_id or '(unknown)'} at {backlog_url}. "
            "Return key, summary, description, status, assignee, reporter, priority, labels, due date, start date, sprint, story points, and updated timestamp."
        )
        jql = f"project = {project_key} AND statusCategory != Done ORDER BY updated DESC" if project_key else ""

        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict) or not properties:
            return {"query": query_text}

        property_lookup = {str(key).lower(): str(key) for key in properties}
        args: dict[str, Any] = {}

        def set_any(names: list[str], value: Any) -> bool:
            for name in names:
                actual = property_lookup.get(name.lower())
                if not actual:
                    continue
                if actual in args or value is None or value == "":
                    continue
                schema_value = properties.get(actual)
                if isinstance(schema_value, dict):
                    args[actual] = self._convert_value_for_schema(value, schema_value)
                else:
                    args[actual] = value
                return True
            return False

        set_any(["query", "q", "text", "input", "prompt", "search", "search_query"], query_text)
        set_any(["jql"], jql)
        set_any(["url", "uri", "backlog_url", "backlogUrl"], backlog_url)
        set_any(["project_key", "projectKey", "project"], project_key)
        set_any(["board_id", "boardId", "board"], board_id)
        set_any(["cloud_id", "cloudId"], cloud_id)
        set_any(["fields"], list(DEFAULT_RESULT_FIELDS))
        set_any(["limit", "count", "max_results", "maxResults", "num_results", "numResults"], max_results)

        required = schema.get("required") if isinstance(schema, dict) else None
        if isinstance(required, list):
            for item in required:
                key = str(item)
                if key in args:
                    continue
                lowered_key = key.lower()
                key_schema = properties.get(key)
                key_type = str(key_schema.get("type") or "").lower() if isinstance(key_schema, dict) else ""
                if key_type in {"string", ""}:
                    if lowered_key in {
                        "query",
                        "q",
                        "text",
                        "input",
                        "prompt",
                        "search",
                        "search_query",
                    }:
                        args[key] = query_text
                    elif lowered_key == "jql" and jql:
                        args[key] = jql
                elif key_type in {"integer", "number"}:
                    args[key] = max_results
                elif key_type == "boolean":
                    args[key] = True

        return args

    def _build_jql_query_arguments(
        self,
        tool: dict[str, Any],
        *,
        jql: str,
        query_text: str,
        backlog_url: str,
        project_key: str | None,
        board_id: str | None,
        cloud_id: str | None,
        max_results: int,
    ) -> dict[str, Any]:
        properties = self._tool_properties(tool)
        if not properties:
            fallback: dict[str, Any] = {
                "jql": jql,
                "query": query_text,
                "fields": list(DEFAULT_RESULT_FIELDS),
                "maxResults": max_results,
            }
            if cloud_id:
                fallback["cloudId"] = cloud_id
            if backlog_url:
                fallback["backlogUrl"] = backlog_url
            if project_key:
                fallback["projectKey"] = project_key
            if board_id:
                fallback["boardId"] = board_id
            return fallback

        property_lookup = {str(key).lower(): str(key) for key in properties}
        args: dict[str, Any] = {}

        def set_any(names: list[str], value: Any) -> bool:
            for name in names:
                actual = property_lookup.get(name.lower())
                if not actual:
                    continue
                if actual in args or value is None or value == "":
                    continue
                schema_value = properties.get(actual)
                if isinstance(schema_value, dict):
                    args[actual] = self._convert_value_for_schema(value, schema_value)
                else:
                    args[actual] = value
                return True
            return False

        set_any(["query", "q", "text", "input", "prompt", "search", "search_query"], query_text)
        set_any(["jql"], jql)
        set_any(["url", "uri", "backlog_url", "backlogUrl"], backlog_url)
        set_any(["project_key", "projectKey", "project"], project_key)
        set_any(["board_id", "boardId", "board"], board_id)
        set_any(["cloud_id", "cloudId"], cloud_id)
        set_any(["fields"], list(DEFAULT_RESULT_FIELDS))
        set_any(["limit", "count", "max_results", "maxResults", "num_results", "numResults"], max_results)

        required = self._tool_schema(tool).get("required")
        if isinstance(required, list):
            for item in required:
                key = str(item)
                if key in args:
                    continue
                lowered_key = key.lower()
                key_schema = properties.get(key)
                key_type = str(key_schema.get("type") or "").lower() if isinstance(key_schema, dict) else ""
                if key_type in {"string", ""}:
                    if lowered_key == "jql":
                        args[key] = jql
                    elif lowered_key in {
                        "query",
                        "q",
                        "text",
                        "input",
                        "prompt",
                        "search",
                        "search_query",
                    }:
                        args[key] = query_text
                elif key_type in {"integer", "number"}:
                    args[key] = max_results
                elif key_type == "boolean":
                    args[key] = True

        return args

    def _search_jira_tickets_with_jql(
        self,
        client: MCPClient,
        server_name: str,
        tool: dict[str, Any],
        *,
        backlog_url: str,
        project_key: str | None,
        board_id: str | None,
        cloud_id: str | None,
        max_results: int,
        jql: str,
        query_text: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str | None]:
        arguments = self._build_jql_query_arguments(
            tool,
            jql=jql,
            query_text=query_text,
            backlog_url=backlog_url,
            project_key=project_key,
            board_id=board_id,
            cloud_id=cloud_id,
            max_results=max_results,
        )
        result = client.call_tool(server_name, _tool_name(tool), arguments)
        result_dict = result if isinstance(result, dict) else {}
        error = _extract_result_error_message(result_dict)
        tickets = _extract_tickets(result_dict) if not error else []
        self._apply_backlog_origin(backlog_url, tickets)
        return tickets, result_dict, arguments, error

    def _build_action_arguments(
        self,
        tool: dict[str, Any],
        action: str,
        user_message: str,
        backlog_url: str,
        project_key: str | None,
        board_id: str | None,
        cloud_id: str | None,
        max_results: int,
        issue_key: str | None,
        fields_payload_override: dict[str, Any] | None = None,
        ticket_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        properties = self._tool_properties(tool)
        if not properties:
            return {"query": user_message}

        property_lookup = {str(key).lower(): str(key) for key in properties}
        site_url = backlog_url
        try:
            parsed_backlog = urlparse(backlog_url)
            if parsed_backlog.scheme and parsed_backlog.netloc:
                site_url = f"{parsed_backlog.scheme}://{parsed_backlog.netloc}"
        except Exception:
            site_url = backlog_url
        args: dict[str, Any] = {}
        summary_hint = self._extract_summary_hint(user_message)
        priority_name = self._extract_priority_name(user_message) if action == "edit" else ""
        priority_for_args = priority_name
        fields_payload = (
            fields_payload_override
            if isinstance(fields_payload_override, dict)
            else self._build_fields_payload(
                action,
                user_message,
                summary_hint,
                issue_key,
                project_key,
                ticket_context=ticket_context,
            )
        )
        create_description_for_args = ""
        create_issue_type_name = "Task"
        create_parent_key = ""
        if action == "create" and isinstance(fields_payload, dict):
            create_summary = _stringify_scalar(fields_payload.get("summary"))
            if create_summary:
                summary_hint = create_summary[:180]
            create_description_for_args = _adf_to_text(fields_payload.get("description")) or _stringify_scalar(
                fields_payload.get("description")
            )
            issue_type_field = fields_payload.get("issuetype")
            create_issue_type_name = (
                _stringify_scalar(issue_type_field.get("name"))
                if isinstance(issue_type_field, dict)
                else _stringify_scalar(issue_type_field)
            ) or "Task"
            parent_field = fields_payload.get("parent")
            create_parent_key = (
                _stringify_scalar(parent_field.get("key"))
                if isinstance(parent_field, dict)
                else _stringify_scalar(parent_field)
            ).upper()

        if action == "view" and issue_key:
            jql = f"key = {issue_key}"
        elif action == "edit" and issue_key:
            jql = f"key = {issue_key}"
        elif project_key:
            jql = f"project = {project_key} ORDER BY updated DESC"
        else:
            jql = ""

        query_text = user_message
        if action == "list" and project_key:
            query_text = (
                f"List Jira tickets for project {project_key}. "
                "Include key, summary, description, status, assignee, reporter, priority, labels, due date, start date, sprint, story points, and updated."
            )
        elif action == "view" and issue_key:
            query_text = f"Show Jira issue {issue_key} with full details."
        elif action == "create":
            query_text = f"Create Jira issue with summary '{summary_hint}'."
        elif action == "edit" and issue_key:
            query_text = f"Update Jira issue {issue_key} using this request: {user_message}"

        def set_any(names: list[str], value: Any) -> bool:
            for name in names:
                actual = property_lookup.get(name.lower())
                if not actual:
                    continue
                if actual in args or value is None or value == "":
                    continue
                schema_value = properties.get(actual)
                if isinstance(schema_value, dict):
                    args[actual] = self._convert_value_for_schema(value, schema_value)
                else:
                    args[actual] = value
                return True
            return False

        set_any(["query", "q", "text", "prompt", "search", "search_query"], query_text)
        if action in {"list", "view"}:
            set_any(["input"], query_text)
        else:
            set_any(["input"], user_message)
        set_any(["instructions", "instruction", "request"], user_message)
        if issue_key:
            set_any(["key", "issue_key", "issueKey", "ticket_key", "ticketKey"], issue_key)
            set_any(["issue", "ticket"], issue_key)
        set_any(["jql"], jql)
        set_any(["summary", "title", "name"], summary_hint)
        if action == "edit":
            extracted_fields = fields_payload if isinstance(fields_payload, dict) else {}
            priority_value = extracted_fields.get("priority")
            priority_for_args = (
                _stringify_scalar(priority_value.get("name"))
                if isinstance(priority_value, dict)
                else _stringify_scalar(priority_value)
            ) or priority_name
            set_any(["priority", "priority_name", "priorityName"], priority_for_args)
            set_any(["assignee", "assignee_name", "assigneeName"], extracted_fields.get("assignee"))
            set_any(["reporter", "reporter_name", "reporterName"], extracted_fields.get("reporter"))
            set_any(["labels", "label"], extracted_fields.get("labels"))
            set_any(["dueDate", "due_date", "duedate"], extracted_fields.get("duedate"))
            set_any(["startDate", "start_date", "startdate"], extracted_fields.get("startdate"))
            set_any(["sprint"], extracted_fields.get("sprint"))
            set_any(
                ["storyPoints", "story_points", "storypoints"],
                extracted_fields.get("story_points"),
            )
            set_any(["team"], extracted_fields.get("team"))
        if action == "create":
            set_any(["description", "body", "details", "content"], create_description_for_args or user_message)
        if action == "create":
            set_any(["issueTypeName", "issue_type_name", "issueType", "issue_type"], create_issue_type_name)
            set_any(
                ["parent", "parentKey", "parent_key", "parentIssueKey", "parent_issue_key", "parentId", "parent_id"],
                create_parent_key,
            )
        fields_key = property_lookup.get("fields")
        if fields_key and fields_key not in args:
            field_schema = properties.get(fields_key)
            field_type = (
                str(field_schema.get("type") or "").lower()
                if isinstance(field_schema, dict)
                else ""
            )
            if action in {"list", "view"}:
                if field_type == "array":
                    args[fields_key] = list(DEFAULT_RESULT_FIELDS)
                elif field_type == "string":
                    args[fields_key] = ",".join(DEFAULT_RESULT_FIELDS)
            else:
                if field_type == "array":
                    args[fields_key] = list(DEFAULT_RESULT_FIELDS)
                elif field_type == "string":
                    args[fields_key] = ",".join(DEFAULT_RESULT_FIELDS)
                elif field_type == "object":
                    args[fields_key] = fields_payload
        if action in {"create", "edit"}:
            set_any(["update", "payload", "data"], fields_payload)
        set_any(["project_key", "projectKey", "project"], project_key)
        set_any(["board_id", "boardId", "board"], board_id)
        set_any(["backlog_url", "backlogUrl"], backlog_url)
        set_any(["site_url", "siteUrl", "base_url", "baseUrl", "url", "uri"], site_url)
        set_any(["cloud_id", "cloudId"], cloud_id)
        set_any(["limit", "count", "max_results", "maxResults", "num_results", "numResults"], max_results)

        required = self._tool_schema(tool).get("required")
        if isinstance(required, list):
            for item in required:
                key = str(item)
                if key in args:
                    continue
                lowered_key = key.lower()
                key_schema = properties.get(key)
                key_type = str(key_schema.get("type") or "").lower() if isinstance(key_schema, dict) else ""
                if key_type in {"integer", "number"}:
                    args[key] = max_results
                    continue
                if key_type == "boolean":
                    args[key] = True
                    continue
                if key_type == "object":
                    if action in {"create", "edit"}:
                        args[key] = fields_payload
                    else:
                        args[key] = {"query": query_text}
                    continue
                if key_type == "array":
                    if "field" in lowered_key:
                        args[key] = list(DEFAULT_RESULT_FIELDS)
                    else:
                        args[key] = [summary_hint]
                    continue
                if lowered_key in {"jql"} and jql:
                    args[key] = jql
                elif lowered_key in {"cloudid", "cloud_id"} and cloud_id:
                    args[key] = cloud_id
                elif any(token in lowered_key for token in ("url", "uri", "host", "domain")):
                    args[key] = site_url
                elif lowered_key in {"key", "issue_key", "issuekey", "ticket_key", "ticketkey"} and issue_key:
                    args[key] = issue_key
                elif (
                    any(token in lowered_key for token in ("issue", "ticket"))
                    and "type" not in lowered_key
                    and issue_key
                ):
                    args[key] = issue_key
                elif lowered_key in {"project", "project_key", "projectkey"} and project_key:
                    args[key] = project_key
                elif lowered_key in {"summary", "title", "name"}:
                    args[key] = summary_hint
                elif lowered_key in {"priority", "priority_name", "priorityname"} and priority_for_args:
                    args[key] = priority_for_args
                elif lowered_key in {"description", "body", "details"}:
                    if action == "create":
                        args[key] = create_description_for_args or user_message
                    else:
                        args[key] = user_message
                elif (
                    lowered_key
                    in {"parent", "parentkey", "parent_key", "parentissuekey", "parent_issue_key", "parentid", "parent_id"}
                    and create_parent_key
                ):
                    args[key] = create_parent_key
                elif lowered_key == "input":
                    args[key] = user_message if action in {"create", "edit"} else query_text
                else:
                    args[key] = query_text
        return args

    def _resolve_cloud_id(
        self,
        client: MCPClient,
        server_name: str,
        backlog_url: str,
    ) -> str | None:
        resources_result = client.call_tool(server_name, "getAccessibleAtlassianResources", {})
        resources = _extract_resources(resources_result if isinstance(resources_result, dict) else {})
        if not resources:
            return None

        backlog_host = ""
        try:
            backlog_host = urlparse(backlog_url).hostname or ""
        except Exception:
            backlog_host = ""

        if backlog_host:
            for resource in resources:
                url_value = _stringify_scalar(resource.get("url"))
                if not url_value:
                    continue
                try:
                    host = urlparse(url_value).hostname or ""
                except Exception:
                    host = ""
                if host and host.lower() == backlog_host.lower():
                    cloud_id = _stringify_scalar(resource.get("id"))
                    if cloud_id:
                        return cloud_id

        for resource in resources:
            cloud_id = _stringify_scalar(resource.get("id"))
            if cloud_id:
                return cloud_id
        return None

    def _find_subtask_keys(
        self,
        client: MCPClient,
        server_name: str,
        cloud_id: str,
        parent_keys: list[str],
        max_results: int,
    ) -> list[str]:
        if not cloud_id:
            return []
        keys: list[str] = []
        for parent_key in parent_keys:
            normalized_parent = str(parent_key or "").strip().upper()
            if not ISSUE_KEY_RE.fullmatch(normalized_parent):
                continue
            arguments: dict[str, Any] = {
                "cloudId": cloud_id,
                "jql": f"parent = {normalized_parent} ORDER BY priority DESC, updated DESC",
                "maxResults": max(5, min(max_results, 100)),
                "fields": list(DEFAULT_RESULT_FIELDS),
            }
            try:
                result = client.call_tool(server_name, "searchJiraIssuesUsingJql", arguments)
            except Exception:
                continue
            result_dict = result if isinstance(result, dict) else {}
            if _extract_result_error_message(result_dict):
                continue
            tickets = _extract_tickets(result_dict)
            text = _extract_ticket_text(result_dict)
            issue_keys = self._collect_issue_keys(tickets, text)
            for key in issue_keys:
                normalized_key = str(key or "").strip().upper()
                if not ISSUE_KEY_RE.fullmatch(normalized_key):
                    continue
                if normalized_key == normalized_parent or normalized_key in keys:
                    continue
                keys.append(normalized_key)
        return keys

    def _fetch_tickets_by_keys(
        self,
        client: MCPClient,
        server_name: str,
        cloud_id: str,
        issue_keys: list[str],
        max_results: int,
    ) -> dict[str, dict[str, Any]]:
        normalized_keys: list[str] = []
        for item in issue_keys:
            key = str(item or "").strip().upper()
            if not ISSUE_KEY_RE.fullmatch(key):
                continue
            if key in normalized_keys:
                continue
            normalized_keys.append(key)
        if not cloud_id or not normalized_keys:
            return {}

        jql = f"key in ({', '.join(normalized_keys)}) ORDER BY updated DESC"
        arguments: dict[str, Any] = {
            "cloudId": cloud_id,
            "jql": jql,
            "maxResults": max(5, min(max(max_results, len(normalized_keys)), 100)),
            "fields": list(DEFAULT_RESULT_FIELDS),
        }
        try:
            result = client.call_tool(server_name, "searchJiraIssuesUsingJql", arguments)
        except Exception:
            return {}
        result_dict = result if isinstance(result, dict) else {}
        if _extract_result_error_message(result_dict):
            return {}
        tickets = _extract_tickets(result_dict)
        by_key: dict[str, dict[str, Any]] = {}
        for ticket in tickets:
            key = str(ticket.get("key") or "").strip().upper()
            if not key:
                continue
            by_key[key] = ticket
        return by_key

    def _fetch_parent_ticket_contexts(
        self,
        client: MCPClient,
        server_name: str,
        cloud_id: str,
        ticket_context_by_key: dict[str, dict[str, Any]],
        max_results: int,
    ) -> dict[str, dict[str, Any]]:
        parent_keys: list[str] = []
        for context in ticket_context_by_key.values():
            if not isinstance(context, dict):
                continue
            parent_key = str(context.get("parent_key") or "").strip().upper()
            if not ISSUE_KEY_RE.fullmatch(parent_key):
                continue
            if parent_key in parent_keys:
                continue
            parent_keys.append(parent_key)
        if not parent_keys:
            return {}
        return self._fetch_tickets_by_keys(
            client=client,
            server_name=server_name,
            cloud_id=cloud_id,
            issue_keys=parent_keys,
            max_results=max_results,
        )

    def _find_project_subtask_keys(
        self,
        client: MCPClient,
        server_name: str,
        cloud_id: str,
        project_key: str | None,
        max_results: int,
    ) -> list[str]:
        if not cloud_id:
            return []
        jql_parts = []
        if project_key:
            jql_parts.append(f"project = {project_key}")
        jql_parts.append("parent is not EMPTY")
        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
        arguments: dict[str, Any] = {
            "cloudId": cloud_id,
            "jql": jql,
            "maxResults": max(5, min(max_results, 100)),
            "fields": list(DEFAULT_RESULT_FIELDS),
        }
        try:
            result = client.call_tool(server_name, "searchJiraIssuesUsingJql", arguments)
        except Exception:
            return []
        result_dict = result if isinstance(result, dict) else {}
        if _extract_result_error_message(result_dict):
            return []
        tickets = _extract_tickets(result_dict)
        return [str(ticket.get("key") or "").strip().upper() for ticket in tickets if ticket.get("key")]

    def _resolve_target_keys_for_edit(
        self,
        user_message: str,
        requested_issue_keys: list[str],
        client: MCPClient,
        server_name: str,
        cloud_id: str | None,
        project_key: str | None,
        max_results: int,
        tool_lookup: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        target_keys = self._normalize_issue_keys(requested_issue_keys)
        warnings: list[str] = []
        subtask_keys: list[str] = []
        if not self._requests_subtask_updates(user_message):
            return target_keys, subtask_keys, warnings

        if target_keys and cloud_id and "searchJiraIssuesUsingJql" in tool_lookup:
            subtask_keys = self._find_subtask_keys(
                client,
                server_name,
                cloud_id,
                target_keys,
                max_results,
            )
            for key in subtask_keys:
                if key not in target_keys:
                    target_keys.append(key)
            return self._normalize_issue_keys(target_keys), self._normalize_issue_keys(subtask_keys), warnings

        if not target_keys:
            cached = self._load_latest_cached_fetch()
            if cached:
                cached_tickets = cached.get("tickets") if isinstance(cached.get("tickets"), list) else []
                cached_subtasks = [
                    str(ticket.get("key") or "").strip().upper()
                    for ticket in cached_tickets
                    if isinstance(ticket, dict) and bool(ticket.get("is_subtask"))
                ]
                target_keys = self._normalize_issue_keys(cached_subtasks)
                if target_keys:
                    warnings.append(
                        "No explicit Jira key provided; applied request to subtasks from latest cached backlog fetch."
                    )

        if not target_keys and cloud_id and "searchJiraIssuesUsingJql" in tool_lookup:
            project_subtasks = self._find_project_subtask_keys(
                client,
                server_name,
                cloud_id,
                project_key,
                max_results,
            )
            target_keys = self._normalize_issue_keys(project_subtasks)
            if target_keys:
                warnings.append(
                    "No explicit Jira key provided; applied request to recent project subtasks."
                )

        return target_keys, self._normalize_issue_keys(subtask_keys), warnings

    def _enrich_tickets_with_activity(
        self,
        client: MCPClient,
        server_name: str,
        cloud_id: str | None,
        tools: list[dict[str, Any]],
        tickets: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        if not cloud_id or not tickets:
            return tickets, [], {}

        get_issue_tool = next((tool for tool in tools if _tool_name(tool) == "getJiraIssue"), None)
        if not get_issue_tool:
            return tickets, ["Jira activity enrichment skipped: getJiraIssue MCP tool unavailable."], {}

        try:
            limit = int(str(os.getenv("JIRA_ACTIVITY_ENRICH_LIMIT", str(DEFAULT_ACTIVITY_ENRICH_LIMIT))))
        except Exception:
            limit = DEFAULT_ACTIVITY_ENRICH_LIMIT
        limit = max(1, min(limit, 100))

        targets = [ticket for ticket in tickets if str(ticket.get("key") or "").strip()]
        warnings: list[str] = []
        if len(targets) > limit:
            warnings.append(
                f"Activity enrichment limited to first {limit} tickets (set JIRA_ACTIVITY_ENRICH_LIMIT to change)."
            )
            targets = targets[:limit]

        props = self._tool_properties(get_issue_tool)
        property_lookup = {str(key).lower(): str(key) for key in props}
        detail_results: dict[str, Any] = {}
        by_key = {str(ticket.get('key') or '').strip().upper(): ticket for ticket in tickets}

        for ticket in targets:
            key = str(ticket.get("key") or "").strip().upper()
            if not key:
                continue

            args: dict[str, Any] = {}

            def set_any(names: list[str], value: Any) -> None:
                for name in names:
                    actual = property_lookup.get(name.lower())
                    if not actual:
                        continue
                    if actual in args or value is None or value == "":
                        continue
                    schema_value = props.get(actual)
                    if isinstance(schema_value, dict):
                        args[actual] = self._convert_value_for_schema(value, schema_value)
                    else:
                        args[actual] = value
                    return

            set_any(["cloudId", "cloud_id"], cloud_id)
            set_any(["issueIdOrKey", "issue_key", "issueKey", "key", "ticket_key", "ticketKey"], key)
            set_any(["fields"], list(DEFAULT_RESULT_FIELDS))
            set_any(["expand"], "changelog")

            try:
                result = client.call_tool(server_name, "getJiraIssue", args)
            except Exception as exc:
                warnings.append(f"Activity enrichment failed for {key}: {str(exc).strip() or type(exc).__name__}")
                continue

            result_dict = result if isinstance(result, dict) else {}
            error_text = _extract_result_error_message(result_dict)
            if error_text:
                warnings.append(f"Activity enrichment failed for {key}: {error_text}")
                continue

            detail_results[key] = result_dict
            parsed = _extract_tickets(result_dict)
            enhanced = next(
                (item for item in parsed if str(item.get("key") or "").strip().upper() == key),
                None,
            )
            if not isinstance(enhanced, dict):
                continue
            target = by_key.get(key)
            if not isinstance(target, dict):
                continue
            for field in (
                "summary",
                "description",
                "status",
                "assignee",
                "reporter",
                "priority",
                "updated",
                "due_date",
                "start_date",
                "story_points",
                "team",
                "development",
                "issue_type",
                "parent_key",
                "url",
            ):
                if not target.get(field) and enhanced.get(field):
                    target[field] = enhanced.get(field)
            for list_field in ("labels", "sprints", "attachments", "comments", "history"):
                existing_values = target.get(list_field) if isinstance(target.get(list_field), list) else []
                incoming_values = enhanced.get(list_field) if isinstance(enhanced.get(list_field), list) else []
                if not existing_values and incoming_values:
                    target[list_field] = incoming_values
            if not target.get("attachments_count") and enhanced.get("attachments_count"):
                target["attachments_count"] = enhanced.get("attachments_count")

        return tickets, warnings[:12], detail_results

    @staticmethod
    def _apply_backlog_origin(backlog_url: str, tickets: list[dict[str, Any]]) -> None:
        backlog_origin = ""
        try:
            parsed_backlog = urlparse(backlog_url)
            if parsed_backlog.scheme and parsed_backlog.netloc:
                backlog_origin = f"{parsed_backlog.scheme}://{parsed_backlog.netloc}"
        except Exception:
            backlog_origin = ""
        if not backlog_origin:
            return
        for ticket in tickets:
            key = str(ticket.get("key") or "").strip()
            raw_url = str(ticket.get("url") or "").strip()
            if key and (not raw_url or "api.atlassian.com/ex/jira" in raw_url):
                ticket["url"] = f"{backlog_origin}/browse/{key}"

    @staticmethod
    def _collect_issue_keys(tickets: list[dict[str, Any]], result_text: str) -> list[str]:
        keys = {str(ticket.get("key") or "").strip().upper() for ticket in tickets if ticket.get("key")}
        keys.update(match.upper() for match in ISSUE_KEY_RE.findall(result_text or ""))
        return sorted(key for key in keys if key)

    @staticmethod
    def _load_latest_cached_fetch() -> dict[str, Any] | None:
        rows = list_jira_fetches(1)
        if not rows:
            return None
        row = rows[0] if isinstance(rows[0], dict) else {}
        try:
            tickets_raw = json.loads(str(row.get("tickets_json") or "[]"))
        except Exception:
            tickets_raw = []
        tickets = [item for item in tickets_raw if isinstance(item, dict)]
        if not tickets:
            return None
        return {
            "tickets": tickets,
            "created_at": str(row.get("created_at") or ""),
            "server": str(row.get("server") or ""),
            "tool": str(row.get("tool") or ""),
            "backlog_url": str(row.get("backlog_url") or ""),
        }

    @staticmethod
    def format_chat_reply(result: dict[str, Any], max_tickets: int = 20) -> str:
        action = str(result.get("action") or "list")
        tickets = result.get("tickets") if isinstance(result.get("tickets"), list) else []
        warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        operations = result.get("operations") if isinstance(result.get("operations"), list) else []
        operation_summary = (
            result.get("operation_summary") if isinstance(result.get("operation_summary"), dict) else {}
        )
        issue_keys = result.get("issue_keys") if isinstance(result.get("issue_keys"), list) else []
        requested_issue_keys = (
            result.get("requested_issue_keys") if isinstance(result.get("requested_issue_keys"), list) else []
        )
        updated_issue_keys = (
            result.get("updated_issue_keys") if isinstance(result.get("updated_issue_keys"), list) else []
        )
        failed_issue_keys = result.get("failed_issue_keys") if isinstance(result.get("failed_issue_keys"), list) else []
        issue_key = str(result.get("issue_key") or "").strip().upper()
        server = str(result.get("server") or "")
        tool = str(result.get("tool") or "")
        result_preview = str(result.get("result_text_preview") or "").strip()
        created_issue_keys = (
            result.get("created_issue_keys") if isinstance(result.get("created_issue_keys"), list) else []
        )
        reused_issue_keys = (
            result.get("reused_issue_keys") if isinstance(result.get("reused_issue_keys"), list) else []
        )

        action_label = {
            "list": "Listed Jira tickets",
            "view": "Viewed Jira ticket",
            "create": "Created Jira ticket",
            "edit": "Updated Jira ticket",
        }.get(action, "Executed Jira action")
        if action == "create":
            if reused_issue_keys and not created_issue_keys:
                action_label = "Matched existing Jira ticket"
            elif reused_issue_keys and created_issue_keys:
                action_label = "Resolved Jira ticket request"

        lines: list[str] = [f"{action_label}.", f"Server: `{server}` | Tool: `{tool}`"]

        if action == "list":
            lines.append(f"Tickets found: {len(tickets)}")
            if not tickets:
                lines.append(
                    "No tickets were found in the configured backlog. "
                    "Please check your Project key and Board number in the Workflow Tasks page."
                )
            for ticket in tickets[:max_tickets]:
                key = str(ticket.get("key") or "").strip() or "UNKNOWN"
                status = str(ticket.get("status") or "").strip() or "n/a"
                assignee = str(ticket.get("assignee") or "").strip() or "unassigned"
                issue_type = str(ticket.get("issue_type") or "").strip() or "n/a"
                parent_key = str(ticket.get("parent_key") or "").strip() or "-"
                is_subtask = bool(ticket.get("is_subtask"))
                attachments_count = int(ticket.get("attachments_count") or 0)
                summary = str(ticket.get("summary") or "").strip() or "(no summary)"
                subtask_label = "subtask" if is_subtask else "top-level"
                lines.append(
                    f"- {key} | {status} | {assignee} | {issue_type} | {subtask_label} | "
                    f"parent:{parent_key} | attachments:{attachments_count} | {summary}"
                )
        elif action == "edit":
            requested = [str(item).strip().upper() for item in requested_issue_keys if str(item).strip()]
            updated = [str(item).strip().upper() for item in updated_issue_keys if str(item).strip()]
            failed = [str(item).strip().upper() for item in failed_issue_keys if str(item).strip()]
            if issue_key and issue_key not in requested:
                requested.insert(0, issue_key)
            if requested:
                lines.append(f"Requested: {', '.join(requested)}")
            if updated:
                lines.append(f"Updated: {', '.join(updated)}")
            if failed:
                lines.append(f"Failed: {', '.join(failed)}")
            if not updated and not failed:
                lines.append("No Jira issue update was confirmed.")
            if operations:
                success_count = int(operation_summary.get("success") or 0)
                failed_count = int(operation_summary.get("failed") or 0)
                skipped_count = int(operation_summary.get("skipped") or 0)
                lines.append(
                    "Operation summary: "
                    f"success={success_count}, failed={failed_count}, skipped={skipped_count}"
                )
                for item in operations[:max_tickets]:
                    if not isinstance(item, dict):
                        continue
                    op_key = str(item.get("issue_key") or "").strip() or "-"
                    op_name = str(item.get("operation") or "edit").strip().lower()
                    op_status = str(item.get("status") or "").strip().lower() or "unknown"
                    op_detail = str(item.get("detail") or "").strip()
                    detail_text = op_detail if op_detail else "n/a"
                    lines.append(f"- {op_key} | {op_name} | {op_status} | {detail_text}")
        elif action == "view":
            target = issue_key or (str(issue_keys[0]) if issue_keys else "")
            selected = None
            if target:
                selected = next((ticket for ticket in tickets if str(ticket.get("key") or "").upper() == target), None)
            if not selected and tickets:
                selected = tickets[0]
            if selected:
                lines.append(f"Ticket: {selected.get('key') or target or 'n/a'}")
                lines.append(f"Summary: {selected.get('summary') or 'n/a'}")
                lines.append(f"Description: {selected.get('description') or 'n/a'}")
                lines.append(f"Status: {selected.get('status') or 'n/a'}")
                lines.append(f"Assignee: {selected.get('assignee') or 'n/a'}")
                lines.append(f"Reporter: {selected.get('reporter') or 'n/a'}")
                lines.append(f"Priority: {selected.get('priority') or 'n/a'}")
                labels = selected.get("labels") if isinstance(selected.get("labels"), list) else []
                sprints = selected.get("sprints") if isinstance(selected.get("sprints"), list) else []
                lines.append(f"Labels: {', '.join(str(item) for item in labels) if labels else 'n/a'}")
                lines.append(f"Team: {selected.get('team') or 'n/a'}")
                lines.append(f"Sprint: {', '.join(str(item) for item in sprints) if sprints else 'n/a'}")
                lines.append(f"Story Points: {selected.get('story_points') or 'n/a'}")
                lines.append(f"Start Date: {selected.get('start_date') or 'n/a'}")
                lines.append(f"Due Date: {selected.get('due_date') or 'n/a'}")
                lines.append(f"Type: {selected.get('issue_type') or 'n/a'}")
                lines.append(f"Parent: {selected.get('parent_key') or 'n/a'}")
                lines.append(f"Subtask: {'yes' if bool(selected.get('is_subtask')) else 'no'}")
                lines.append(f"Attachments: {int(selected.get('attachments_count') or 0)}")
                if selected.get("url"):
                    lines.append(f"URL: {selected.get('url')}")
            elif issue_keys:
                lines.append(f"Detected ticket key(s): {', '.join(str(key) for key in issue_keys)}")
        elif action == "create":
            if created_issue_keys:
                lines.append(f"Created ticket key(s): {', '.join(str(key) for key in created_issue_keys)}")
            if reused_issue_keys:
                lines.append(f"Matched existing ticket key(s): {', '.join(str(key) for key in reused_issue_keys)}")
            if not created_issue_keys and not reused_issue_keys and issue_keys:
                lines.append(f"Created ticket key(s): {', '.join(str(key) for key in issue_keys)}")
            else:
                if not created_issue_keys and not reused_issue_keys and not issue_keys:
                    lines.append("Create operation executed, but no Jira key was parsed from the response.")
            if operations:
                success_count = int(operation_summary.get("success") or 0)
                failed_count = int(operation_summary.get("failed") or 0)
                skipped_count = int(operation_summary.get("skipped") or 0)
                lines.append(
                    "Operation summary: "
                    f"success={success_count}, failed={failed_count}, skipped={skipped_count}"
                )
                for item in operations[:max_tickets]:
                    if not isinstance(item, dict):
                        continue
                    op_key = str(item.get("issue_key") or "").strip() or "-"
                    op_name = str(item.get("operation") or "create").strip().lower()
                    op_status = str(item.get("status") or "").strip().lower() or "unknown"
                    op_detail = str(item.get("detail") or "").strip()
                    detail_text = op_detail if op_detail else "n/a"
                    lines.append(f"- {op_key} | {op_name} | {op_status} | {detail_text}")
        else:
            if issue_keys:
                lines.append(f"Ticket key(s): {', '.join(str(key) for key in issue_keys)}")
            elif tickets:
                lines.append(f"Ticket key(s): {', '.join(str(ticket.get('key') or '') for ticket in tickets if ticket.get('key'))}")
            else:
                lines.append("Operation executed, but no Jira key was parsed from the response.")

        if warnings:
            lines.append("Warnings: " + " ".join(str(item) for item in warnings))
        if result_preview and not tickets:
            lines.append("Result preview:")
            lines.append(result_preview)
        return "\n".join(lines).strip()

    async def fetch_backlog_tickets(
        self,
        workspace_root: Path,
        backlog_url_override: str | None = None,
    ) -> dict[str, Any]:
        self._mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            config = load_mcp_config(workspace_root)
            if not config or not config.servers:
                raise RuntimeError(
                    "MCP is not configured. Add app/mcp.json with an Atlassian MCP server."
                )

            tooling = self._resolve_tooling(config)
            backlog_url = (
                str(backlog_url_override or "").strip()
                or str(tooling.get("backlog_url") or "").strip()
                or DEFAULT_BACKLOG_URL
            )
            project_key = str(tooling.get("project_key") or "").strip().upper() or None
            board_id = str(tooling.get("board_id") or "").strip() or None
            if not project_key or not board_id:
                parsed_project, parsed_board = _parse_backlog_url(backlog_url)
                project_key = project_key or parsed_project
                board_id = board_id or parsed_board
            cloud_id = str(tooling.get("cloud_id") or tooling.get("cloudId") or "").strip() or None
            try:
                max_results = int(str(tooling.get("max_results") or "100"))
            except Exception:
                max_results = 100

            server_name = self._resolve_server(config)
            client = MCPClient(config)
            tools_payload = await asyncio.to_thread(client.list_tools, server_name)
            tools = _extract_tools(tools_payload)
            available_tools = [_tool_name(tool) for tool in tools if _tool_name(tool)]
            tool_lookup = {_tool_name(tool): tool for tool in tools if _tool_name(tool)}
            tool_name = self._pick_tool(tools, tooling.get("tool"))

            tool_schema = next((tool for tool in tools if _tool_name(tool) == tool_name), {"name": tool_name})
            if tool_name == "searchJiraIssuesUsingJql" and not cloud_id:
                cloud_id = await asyncio.to_thread(
                    self._resolve_cloud_id,
                    client,
                    server_name,
                    backlog_url,
                )
            arguments = self._build_arguments(
                tool_schema,
                backlog_url,
                project_key,
                board_id,
                cloud_id,
                max_results,
            )
            result = await asyncio.to_thread(client.call_tool, server_name, tool_name, arguments)

            tickets = _extract_tickets(result if isinstance(result, dict) else {})
            self._apply_backlog_origin(backlog_url, tickets)
            warnings: list[str] = []
            activity_detail_results: dict[str, Any] = {}
            if tickets:
                tickets, activity_warnings, activity_detail_results = await asyncio.to_thread(
                    self._enrich_tickets_with_activity,
                    client,
                    server_name,
                    cloud_id,
                    tools,
                    tickets,
                )
                if activity_warnings:
                    warnings.extend(activity_warnings)
            current_sprint: dict[str, Any] | None = None
            current_sprint_result: dict[str, Any] = {}
            current_sprint_arguments: dict[str, Any] = {}
            if "searchJiraIssuesUsingJql" in tool_lookup and cloud_id:
                sprint_jql_parts = []
                if project_key:
                    sprint_jql_parts.append(f"project = {project_key}")
                sprint_jql_parts.append("sprint in openSprints()")
                sprint_jql = " AND ".join(sprint_jql_parts) + " ORDER BY updated DESC"
                sprint_query_text = (
                    f"List Jira issues in the current active sprint for project {project_key or '(unknown)'} "
                    f"on board {board_id or '(unknown)'}."
                )
                try:
                    sprint_tickets, sprint_result_dict, sprint_arguments, sprint_error = await asyncio.to_thread(
                        self._search_jira_tickets_with_jql,
                        client,
                        server_name,
                        tool_lookup["searchJiraIssuesUsingJql"],
                        backlog_url=backlog_url,
                        project_key=project_key,
                        board_id=board_id,
                        cloud_id=cloud_id,
                        max_results=max_results,
                        jql=sprint_jql,
                        query_text=sprint_query_text,
                    )
                    current_sprint_result = sprint_result_dict
                    current_sprint_arguments = sprint_arguments
                    if sprint_error:
                        warnings.append(f"Current sprint fetch failed: {sprint_error}")
                    else:
                        current_sprint = _build_current_sprint_payload(
                            sprint_result_dict,
                            sprint_tickets,
                            fallback_board_id=board_id,
                        )
                except Exception as sprint_exc:
                    warnings.append(
                        f"Current sprint fetch failed: {str(sprint_exc).strip() or type(sprint_exc).__name__}"
                    )
            elif "searchJiraIssuesUsingJql" not in tool_lookup:
                warnings.append("Current sprint fetch skipped: searchJiraIssuesUsingJql MCP tool unavailable.")
            elif not cloud_id:
                warnings.append("Current sprint fetch skipped: Jira cloud id could not be resolved.")

            sprint_kanban_tickets = (
                current_sprint.get("tickets")
                if isinstance(current_sprint, dict) and isinstance(current_sprint.get("tickets"), list)
                else []
            )
            kanban_source_tickets = _dedupe_tickets_by_key(
                [item for item in tickets if isinstance(item, dict)],
                [item for item in sprint_kanban_tickets if isinstance(item, dict)],
            )
            kanban_source = "observed_backlog_and_current_sprint_statuses"
            kanban_columns = _build_kanban_columns_payload(
                [item for item in kanban_source_tickets if isinstance(item, dict)],
                source=kanban_source,
            )
            raw_result_json = json.dumps(
                {
                    "list_result": result,
                    "activity_detail_results": activity_detail_results,
                    "tickets": tickets,
                    "current_sprint_result": current_sprint_result,
                    "current_sprint_arguments": current_sprint_arguments,
                    "current_sprint": current_sprint,
                    "kanban_columns": kanban_columns,
                },
                indent=2,
                ensure_ascii=False,
            )
            raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
            if not tickets:
                warnings.append("MCP call succeeded but no issue keys were parsed from the response.")

            return {
                "action": "list",
                "agent": CONFIG.name,
                "workspace_root": str(workspace_root),
                "backlog_url": backlog_url,
                "project_key": project_key,
                "board_id": board_id,
                "server": server_name,
                "tool": tool_name,
                "available_tools": available_tools,
                "arguments": arguments,
                "ticket_count": len(tickets),
                "tickets": tickets,
                "current_sprint": current_sprint,
                "kanban_columns": kanban_columns,
                "warnings": warnings,
                "raw_result_json": raw_result_json,
                "raw_result_path": raw_result_path,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                self._mark_agent_end(self.agent_id, error_text)
            else:
                self._mark_agent_end(self.agent_id)

    async def handle_ticket_request(
        self,
        workspace_root: Path,
        user_message: str,
    ) -> dict[str, Any]:
        self._mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            config = load_mcp_config(workspace_root)
            if not config or not config.servers:
                raise RuntimeError(
                    "MCP is not configured. Add app/mcp.json with an Atlassian MCP server."
                )

            tooling = self._resolve_tooling(config)
            backlog_url = str(tooling.get("backlog_url") or "").strip() or DEFAULT_BACKLOG_URL
            project_key = str(tooling.get("project_key") or "").strip().upper() or None
            board_id = str(tooling.get("board_id") or "").strip() or None
            cloud_id = str(tooling.get("cloud_id") or tooling.get("cloudId") or "").strip() or None
            if not project_key or not board_id:
                parsed_project, parsed_board = _parse_backlog_url(backlog_url)
                project_key = project_key or parsed_project
                board_id = board_id or parsed_board
            try:
                max_results = int(str(tooling.get("max_results") or "100"))
            except Exception:
                max_results = 100

            action = self._infer_action(user_message)
            requested_issue_keys = self._extract_issue_keys(user_message)
            issue_key = requested_issue_keys[0] if requested_issue_keys else None

            server_name = self._resolve_server(config)
            client = MCPClient(config)
            tools_payload = await asyncio.to_thread(client.list_tools, server_name)
            tools_all = _extract_tools(tools_payload)
            jira_tools = [tool for tool in tools_all if self._is_jira_tool(tool)]
            if not jira_tools:
                raise RuntimeError("No Jira MCP tools were returned by the configured server.")
            available_tools = [_tool_name(tool) for tool in jira_tools if _tool_name(tool)]
            candidate_tool_names = self._rank_tools_for_action(jira_tools, action, tooling.get("tool"))

            tool_lookup = {str(_tool_name(tool)): tool for tool in jira_tools if _tool_name(tool)}
            errors: list[str] = []

            if action == "create" and "createJiraIssue" in tool_lookup:
                create_schema = tool_lookup.get("createJiraIssue", {"name": "createJiraIssue"})
                cloud_for_create = cloud_id
                if not cloud_for_create and self._tool_requires_cloud_id(create_schema):
                    cloud_for_create = await asyncio.to_thread(
                        self._resolve_cloud_id,
                        client,
                        server_name,
                        backlog_url,
                    )
                create_is_subtask = self._requests_subtask_updates(user_message)
                create_issue_type_candidates = self._resolve_create_issue_type_candidates(create_is_subtask)
                if not create_issue_type_candidates:
                    create_issue_type_candidates = ["Subtask"] if create_is_subtask else ["Task"]
                create_parent_key = issue_key if create_is_subtask and issue_key else ""
                if create_is_subtask and not create_parent_key:
                    raise RuntimeError(
                        "Subtask creation requested, but no parent Jira key was detected. "
                        "Include a parent key like DEV-8."
                    )
                create_summaries = self._extract_create_titles(user_message)
                if not create_summaries:
                    fallback_summary = self._extract_summary_hint(user_message).strip()
                    if len(fallback_summary) > 120:
                        fallback_summary = ""
                    if not fallback_summary or ISSUE_KEY_RE.search(fallback_summary):
                        fallback_summary = "New subtask" if create_is_subtask else "New Jira ticket"
                    create_summaries = [fallback_summary]
                create_summaries = [item.strip() for item in create_summaries if item.strip()][:20]
                if not create_summaries:
                    create_summaries = ["New subtask" if create_is_subtask else "New Jira ticket"]

                created_issue_keys: list[str] = []
                failed_issue_keys: list[str] = []
                warnings: list[str] = []
                tickets: list[dict[str, Any]] = []
                preview_lines: list[str] = []
                operations: list[dict[str, Any]] = []
                per_issue_arguments: dict[str, dict[str, Any]] = {}
                per_issue_results: dict[str, dict[str, Any]] = {}
                parent_context: dict[str, Any] = {}
                if create_parent_key and cloud_for_create and "searchJiraIssuesUsingJql" in tool_lookup:
                    parent_contexts = await asyncio.to_thread(
                        self._fetch_tickets_by_keys,
                        client,
                        server_name,
                        cloud_for_create,
                        [create_parent_key],
                        max_results,
                    )
                    parent_context = parent_contexts.get(create_parent_key, {})

                for index, summary in enumerate(create_summaries):
                    pseudo_key = f"create-{index + 1}"
                    try:
                        generated_description = await self._generate_issue_specific_description(
                            user_message=user_message,
                            issue_key="",
                            issue_summary=summary,
                            existing_description="",
                            parent_key=create_parent_key,
                            parent_summary=_stringify_scalar(parent_context.get("summary")),
                            parent_description=(
                                _adf_to_text(parent_context.get("description"))
                                or _stringify_scalar(parent_context.get("description"))
                            ),
                        )
                    except Exception as exc:
                        detail = str(exc).strip() or type(exc).__name__
                        failed_issue_keys.append(pseudo_key)
                        operations.append(
                            {
                                "issue_key": "",
                                "operation": "create",
                                "status": "failed",
                                "tool": "createJiraIssue",
                                "detail": f"{summary}: description generation failed: {detail}",
                            }
                        )
                        continue
                    fields_payload_override = self._build_fields_payload(
                        action="create",
                        user_message=user_message,
                        summary_hint=summary,
                        issue_key=None,
                        project_key=project_key,
                        generated_description=generated_description,
                    )
                    created_for_summary = False
                    last_issue_type_error = ""
                    for type_index, create_issue_type_name in enumerate(create_issue_type_candidates):
                        fields_payload_for_type = dict(fields_payload_override)
                        fields_payload_for_type["summary"] = summary
                        fields_payload_for_type["issuetype"] = {"name": create_issue_type_name}
                        if create_parent_key:
                            fields_payload_for_type["parent"] = {"key": create_parent_key}

                        arguments = self._build_action_arguments(
                            create_schema,
                            "create",
                            user_message,
                            backlog_url,
                            project_key,
                            board_id,
                            cloud_for_create,
                            max_results,
                            None,
                            fields_payload_override=fields_payload_for_type,
                        )
                        props = self._tool_properties(create_schema)
                        self._set_tool_argument(arguments, props, ["summary", "title", "name"], summary)
                        self._set_tool_argument(
                            arguments,
                            props,
                            ["description", "body", "details", "content"],
                            generated_description,
                        )
                        self._set_tool_argument(
                            arguments,
                            props,
                            ["fields", "payload", "update", "data"],
                            fields_payload_for_type,
                        )
                        self._set_tool_argument(
                            arguments,
                            props,
                            ["issueTypeName", "issue_type_name", "issueType", "issue_type"],
                            create_issue_type_name,
                        )
                        if create_parent_key:
                            self._set_tool_argument(
                                arguments,
                                props,
                                ["parent", "parentKey", "parent_key", "parentIssueKey", "parent_issue_key", "parentId", "parent_id"],
                                create_parent_key,
                            )
                        attempt_key = f"{pseudo_key}:{create_issue_type_name}"
                        per_issue_arguments[attempt_key] = arguments

                        try:
                            result = await asyncio.to_thread(client.call_tool, server_name, "createJiraIssue", arguments)
                        except Exception as exc:
                            detail = str(exc).strip() or type(exc).__name__
                            if self._is_issue_type_validation_error(detail) and type_index + 1 < len(create_issue_type_candidates):
                                last_issue_type_error = detail
                                continue
                            last_issue_type_error = ""
                            failed_issue_keys.append(pseudo_key)
                            operations.append(
                                {
                                    "issue_key": "",
                                    "operation": "create",
                                    "status": "failed",
                                    "tool": "createJiraIssue",
                                    "detail": f"{summary}: {detail}",
                                }
                            )
                            break

                        result_dict = result if isinstance(result, dict) else {}
                        per_issue_results[attempt_key] = result_dict
                        tool_error = _extract_result_error_message(result_dict)
                        if tool_error:
                            if self._is_issue_type_validation_error(tool_error) and type_index + 1 < len(create_issue_type_candidates):
                                last_issue_type_error = tool_error
                                continue
                            last_issue_type_error = ""
                            failed_issue_keys.append(pseudo_key)
                            operations.append(
                                {
                                    "issue_key": "",
                                    "operation": "create",
                                    "status": "failed",
                                    "tool": "createJiraIssue",
                                    "detail": f"{summary}: {tool_error}",
                                }
                            )
                            break

                        parsed_tickets = _extract_tickets(result_dict)
                        self._apply_backlog_origin(backlog_url, parsed_tickets)
                        if parsed_tickets:
                            tickets.extend(parsed_tickets)
                        result_text = _extract_ticket_text(result_dict)
                        parsed_keys = self._collect_issue_keys(parsed_tickets, result_text)
                        created_key = parsed_keys[0] if parsed_keys else ""
                        if created_key:
                            created_issue_keys.append(created_key)
                            operations.append(
                                {
                                    "issue_key": created_key,
                                    "operation": "create",
                                    "status": "success",
                                    "tool": "createJiraIssue",
                                    "detail": f"Created from summary: {summary} (type: {create_issue_type_name})",
                                }
                            )
                            compact_preview = result_text.strip()
                            if compact_preview:
                                if len(compact_preview) > 200:
                                    compact_preview = compact_preview[:200] + "... (truncated)"
                                preview_lines.append(f"{summary}: {compact_preview}")
                            created_for_summary = True
                            break

                        failed_issue_keys.append(pseudo_key)
                        operations.append(
                            {
                                "issue_key": "",
                                "operation": "create",
                                "status": "failed",
                                "tool": "createJiraIssue",
                                "detail": (
                                    f"{summary}: MCP call succeeded but no Jira key was parsed from the response."
                                ),
                            }
                        )
                        last_issue_type_error = ""
                        break

                    if not created_for_summary and last_issue_type_error:
                        failed_issue_keys.append(pseudo_key)
                        operations.append(
                            {
                                "issue_key": "",
                                "operation": "create",
                                "status": "failed",
                                "tool": "createJiraIssue",
                                "detail": (
                                    f"{summary}: issue type was rejected for all candidates "
                                    f"({', '.join(create_issue_type_candidates)}). Last error: {last_issue_type_error}"
                                ),
                            }
                        )

                operation_summary = self._summarize_operations(operations)
                if int(operation_summary.get("success") or 0) == 0:
                    failure_details = [
                        str(item.get("detail") or "")
                        for item in operations
                        if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed"
                    ]
                    details = "; ".join(item for item in failure_details[:5] if item) or "No tickets were created."
                    raise RuntimeError(f"Jira create failed. {details}")

                raw_result_json = json.dumps(
                    {
                        "requested_summaries": create_summaries,
                        "created_issue_keys": created_issue_keys,
                        "failed_issue_keys": failed_issue_keys,
                        "per_issue_arguments": per_issue_arguments,
                        "per_issue_results": per_issue_results,
                        "operations": operations,
                        "tickets": tickets,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
                preview = "\n".join(preview_lines).strip()
                if len(preview) > 700:
                    preview = preview[:700] + "... (truncated)"

                return {
                    "action": "create",
                    "agent": CONFIG.name,
                    "workspace_root": str(workspace_root),
                    "server": server_name,
                    "tool": "createJiraIssue",
                    "available_tools": available_tools,
                    "arguments": {"per_issue": per_issue_arguments},
                    "issue_key": created_issue_keys[0] if created_issue_keys else "",
                    "issue_keys": created_issue_keys,
                    "requested_issue_keys": [],
                    "updated_issue_keys": created_issue_keys,
                    "failed_issue_keys": failed_issue_keys,
                    "ticket_count": len(tickets),
                    "tickets": tickets,
                    "warnings": warnings,
                    "operations": operations,
                    "operation_summary": operation_summary,
                    "result_text_preview": preview,
                    "raw_result_json": raw_result_json,
                    "raw_result_path": raw_result_path,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }

            should_run_comment = (
                action == "edit"
                and self._is_comment_request(user_message)
                and "addCommentToJiraIssue" in tool_lookup
            )
            if should_run_comment:
                comment_schema = tool_lookup.get("addCommentToJiraIssue", {"name": "addCommentToJiraIssue"})
                cloud_for_comment = cloud_id
                if not cloud_for_comment and self._tool_requires_cloud_id(comment_schema):
                    cloud_for_comment = await asyncio.to_thread(
                        self._resolve_cloud_id,
                        client,
                        server_name,
                        backlog_url,
                    )
                target_keys, subtask_keys, warnings = await asyncio.to_thread(
                    self._ensure_action_target_keys,
                    user_message,
                    requested_issue_keys,
                    "comment",
                    client,
                    server_name,
                    cloud_for_comment,
                    project_key,
                    max_results,
                    tool_lookup,
                )

                ticket_context_by_key: dict[str, dict[str, Any]] = {}
                if cloud_for_comment and "searchJiraIssuesUsingJql" in tool_lookup and target_keys:
                    ticket_context_by_key = await asyncio.to_thread(
                        self._fetch_tickets_by_keys,
                        client,
                        server_name,
                        cloud_for_comment,
                        target_keys,
                        max_results,
                    )

                skipped_parent_keys: list[str] = []
                if target_keys and self._requests_subtask_updates(user_message):
                    target_keys, skipped_parent_keys, parent_guard_warnings = self._apply_subtask_parent_guard(
                        user_message,
                        target_keys,
                        subtask_keys,
                        ticket_context_by_key,
                    )
                    warnings.extend(parent_guard_warnings)

                comment_body = self._extract_comment_body(user_message)
                updated_issue_keys: list[str] = []
                failed_issue_keys: list[str] = []
                per_issue_arguments: dict[str, dict[str, Any]] = {}
                per_issue_results: dict[str, dict[str, Any]] = {}
                operations: list[dict[str, Any]] = []
                preview_lines: list[str] = []

                for target_key in target_keys:
                    arguments = self._build_action_arguments(
                        comment_schema,
                        "edit",
                        user_message,
                        backlog_url,
                        project_key,
                        board_id,
                        cloud_for_comment,
                        max_results,
                        target_key,
                    )
                    props = self._tool_properties(comment_schema)
                    self._set_tool_argument(arguments, props, ["cloudId", "cloud_id"], cloud_for_comment)
                    self._set_tool_argument(
                        arguments,
                        props,
                        ["issueIdOrKey", "issue_key", "issueKey", "ticketKey", "ticket_key", "key"],
                        target_key,
                    )
                    self._set_tool_argument(
                        arguments,
                        props,
                        ["commentBody", "comment_body", "body", "comment", "message", "text"],
                        comment_body,
                    )
                    per_issue_arguments[target_key] = arguments

                    try:
                        result = await asyncio.to_thread(client.call_tool, server_name, "addCommentToJiraIssue", arguments)
                    except Exception as exc:
                        detail = str(exc).strip() or type(exc).__name__
                        failed_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "comment",
                                "status": "failed",
                                "tool": "addCommentToJiraIssue",
                                "detail": detail,
                            }
                        )
                        continue

                    result_dict = result if isinstance(result, dict) else {}
                    per_issue_results[target_key] = result_dict
                    tool_error = _extract_result_error_message(result_dict)
                    if tool_error:
                        failed_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "comment",
                                "status": "failed",
                                "tool": "addCommentToJiraIssue",
                                "detail": tool_error,
                            }
                        )
                        continue

                    updated_issue_keys.append(target_key)
                    operations.append(
                        {
                            "issue_key": target_key,
                            "operation": "comment",
                            "status": "success",
                            "tool": "addCommentToJiraIssue",
                            "detail": "Comment added.",
                        }
                    )
                    result_text = _extract_ticket_text(result_dict).strip()
                    if result_text:
                        compact_preview = (
                            result_text[:200] + "... (truncated)" if len(result_text) > 200 else result_text
                        )
                        preview_lines.append(f"{target_key}: {compact_preview}")

                operation_summary = self._summarize_operations(operations)
                if int(operation_summary.get("success") or 0) == 0:
                    details = "; ".join(
                        str(item.get("detail") or "")
                        for item in operations
                        if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed"
                    )
                    raise RuntimeError(f"Jira comment update failed. {details[:600]}")
                if skipped_parent_keys:
                    warnings.append(
                        "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                    )

                raw_result_json = json.dumps(
                    {
                        "requested_issue_keys": target_keys,
                        "updated_issue_keys": updated_issue_keys,
                        "failed_issue_keys": failed_issue_keys,
                        "skipped_parent_issue_keys": skipped_parent_keys,
                        "per_issue_arguments": per_issue_arguments,
                        "per_issue_results": per_issue_results,
                        "operations": operations,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
                preview = "\n".join(preview_lines).strip()
                if len(preview) > 700:
                    preview = preview[:700] + "... (truncated)"

                return {
                    "action": "edit",
                    "agent": CONFIG.name,
                    "workspace_root": str(workspace_root),
                    "server": server_name,
                    "tool": "addCommentToJiraIssue",
                    "available_tools": available_tools,
                    "arguments": {"per_issue": per_issue_arguments},
                    "issue_key": issue_key,
                    "issue_keys": updated_issue_keys,
                    "requested_issue_keys": target_keys,
                    "updated_issue_keys": updated_issue_keys,
                    "failed_issue_keys": failed_issue_keys,
                    "ticket_count": 0,
                    "tickets": [],
                    "warnings": warnings,
                    "operations": operations,
                    "operation_summary": operation_summary,
                    "result_text_preview": preview,
                    "raw_result_json": raw_result_json,
                    "raw_result_path": raw_result_path,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }

            should_run_transition = (
                action == "edit"
                and self._is_transition_request(user_message)
                and "transitionJiraIssue" in tool_lookup
            )
            if should_run_transition:
                transition_schema = tool_lookup.get("transitionJiraIssue", {"name": "transitionJiraIssue"})
                transition_target = self._extract_transition_target(user_message)
                cloud_for_transition = cloud_id
                if not cloud_for_transition and self._tool_requires_cloud_id(transition_schema):
                    cloud_for_transition = await asyncio.to_thread(
                        self._resolve_cloud_id,
                        client,
                        server_name,
                        backlog_url,
                    )
                target_keys, subtask_keys, warnings = await asyncio.to_thread(
                    self._ensure_action_target_keys,
                    user_message,
                    requested_issue_keys,
                    "transition",
                    client,
                    server_name,
                    cloud_for_transition,
                    project_key,
                    max_results,
                    tool_lookup,
                )
                ticket_context_by_key: dict[str, dict[str, Any]] = {}
                if cloud_for_transition and "searchJiraIssuesUsingJql" in tool_lookup and target_keys:
                    ticket_context_by_key = await asyncio.to_thread(
                        self._fetch_tickets_by_keys,
                        client,
                        server_name,
                        cloud_for_transition,
                        target_keys,
                        max_results,
                    )

                skipped_parent_keys: list[str] = []
                if target_keys and self._requests_subtask_updates(user_message):
                    target_keys, skipped_parent_keys, parent_guard_warnings = self._apply_subtask_parent_guard(
                        user_message,
                        target_keys,
                        subtask_keys,
                        ticket_context_by_key,
                    )
                    warnings.extend(parent_guard_warnings)

                updated_issue_keys: list[str] = []
                failed_issue_keys: list[str] = []
                operations: list[dict[str, Any]] = []
                per_issue_arguments: dict[str, dict[str, Any]] = {}
                per_issue_results: dict[str, dict[str, Any]] = {}
                preview_lines: list[str] = []

                get_transitions_tool = tool_lookup.get("getTransitionsForJiraIssue")
                if not get_transitions_tool:
                    warnings.append(
                        "Jira transition lookup tool is unavailable; transition ids could not be discovered."
                    )
                for target_key in target_keys:
                    transitions: list[dict[str, str]] = []
                    if get_transitions_tool:
                        get_transitions_props = self._tool_properties(get_transitions_tool)
                        get_args: dict[str, Any] = {}
                        self._set_tool_argument(get_args, get_transitions_props, ["cloudId", "cloud_id"], cloud_for_transition)
                        self._set_tool_argument(
                            get_args,
                            get_transitions_props,
                            ["issueIdOrKey", "issue_key", "issueKey", "ticketKey", "ticket_key", "key"],
                            target_key,
                        )
                        per_issue_arguments[f"{target_key}:getTransitions"] = get_args
                        try:
                            transitions_result = await asyncio.to_thread(
                                client.call_tool,
                                server_name,
                                "getTransitionsForJiraIssue",
                                get_args,
                            )
                        except Exception as exc:
                            detail = str(exc).strip() or type(exc).__name__
                            failed_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "transition",
                                    "status": "failed",
                                    "tool": "getTransitionsForJiraIssue",
                                    "detail": detail,
                                }
                            )
                            continue
                        transitions_result_dict = transitions_result if isinstance(transitions_result, dict) else {}
                        per_issue_results[f"{target_key}:getTransitions"] = transitions_result_dict
                        transitions_error = _extract_result_error_message(transitions_result_dict)
                        if transitions_error:
                            failed_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "transition",
                                    "status": "failed",
                                    "tool": "getTransitionsForJiraIssue",
                                    "detail": transitions_error,
                                }
                            )
                            continue
                        transitions = self._extract_transitions(transitions_result_dict)

                    transition_id, transition_error = self._pick_transition(transitions, transition_target)
                    if not transition_id:
                        failed_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "transition",
                                "status": "failed",
                                "tool": "transitionJiraIssue",
                                "detail": transition_error or "No transition id could be resolved.",
                            }
                        )
                        continue

                    args = self._build_action_arguments(
                        transition_schema,
                        "edit",
                        user_message,
                        backlog_url,
                        project_key,
                        board_id,
                        cloud_for_transition,
                        max_results,
                        target_key,
                    )
                    transition_props = self._tool_properties(transition_schema)
                    self._set_tool_argument(args, transition_props, ["cloudId", "cloud_id"], cloud_for_transition)
                    self._set_tool_argument(
                        args,
                        transition_props,
                        ["issueIdOrKey", "issue_key", "issueKey", "ticketKey", "ticket_key", "key"],
                        target_key,
                    )
                    transition_payload = {"id": transition_id}
                    if not self._set_tool_argument(args, transition_props, ["transition"], transition_payload):
                        self._set_tool_argument(
                            args,
                            transition_props,
                            ["transitionId", "transition_id", "id"],
                            transition_id,
                        )
                    per_issue_arguments[target_key] = args
                    try:
                        result = await asyncio.to_thread(client.call_tool, server_name, "transitionJiraIssue", args)
                    except Exception as exc:
                        detail = str(exc).strip() or type(exc).__name__
                        failed_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "transition",
                                "status": "failed",
                                "tool": "transitionJiraIssue",
                                "detail": detail,
                            }
                        )
                        continue

                    result_dict = result if isinstance(result, dict) else {}
                    per_issue_results[target_key] = result_dict
                    tool_error = _extract_result_error_message(result_dict)
                    if tool_error:
                        failed_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "transition",
                                "status": "failed",
                                "tool": "transitionJiraIssue",
                                "detail": tool_error,
                            }
                        )
                        continue
                    updated_issue_keys.append(target_key)
                    operations.append(
                        {
                            "issue_key": target_key,
                            "operation": "transition",
                            "status": "success",
                            "tool": "transitionJiraIssue",
                            "detail": f"Moved to {transition_target or transition_id}.",
                        }
                    )
                    result_text = _extract_ticket_text(result_dict).strip()
                    if result_text:
                        compact_preview = (
                            result_text[:200] + "... (truncated)" if len(result_text) > 200 else result_text
                        )
                        preview_lines.append(f"{target_key}: {compact_preview}")

                operation_summary = self._summarize_operations(operations)
                if int(operation_summary.get("success") or 0) == 0:
                    details = "; ".join(
                        str(item.get("detail") or "")
                        for item in operations
                        if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed"
                    )
                    raise RuntimeError(f"Jira transition failed. {details[:600]}")
                if skipped_parent_keys:
                    warnings.append(
                        "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                    )

                raw_result_json = json.dumps(
                    {
                        "requested_issue_keys": target_keys,
                        "updated_issue_keys": updated_issue_keys,
                        "failed_issue_keys": failed_issue_keys,
                        "skipped_parent_issue_keys": skipped_parent_keys,
                        "transition_target": transition_target,
                        "per_issue_arguments": per_issue_arguments,
                        "per_issue_results": per_issue_results,
                        "operations": operations,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
                preview = "\n".join(preview_lines).strip()
                if len(preview) > 700:
                    preview = preview[:700] + "... (truncated)"

                return {
                    "action": "edit",
                    "agent": CONFIG.name,
                    "workspace_root": str(workspace_root),
                    "server": server_name,
                    "tool": "transitionJiraIssue",
                    "available_tools": available_tools,
                    "arguments": {"per_issue": per_issue_arguments},
                    "issue_key": issue_key,
                    "issue_keys": updated_issue_keys,
                    "requested_issue_keys": target_keys,
                    "updated_issue_keys": updated_issue_keys,
                    "failed_issue_keys": failed_issue_keys,
                    "ticket_count": 0,
                    "tickets": [],
                    "warnings": warnings,
                    "operations": operations,
                    "operation_summary": operation_summary,
                    "result_text_preview": preview,
                    "raw_result_json": raw_result_json,
                    "raw_result_path": raw_result_path,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }

            should_run_direct_edit = (
                action == "edit"
                and self._is_field_edit_request(user_message)
                and self._has_direct_field_update_intent(user_message)
                and "editJiraIssue" in tool_lookup
            )
            if should_run_direct_edit:
                edit_schema = tool_lookup.get("editJiraIssue", {"name": "editJiraIssue"})
                cloud_for_edit = cloud_id
                if not cloud_for_edit and self._tool_requires_cloud_id(edit_schema):
                    cloud_for_edit = await asyncio.to_thread(
                        self._resolve_cloud_id,
                        client,
                        server_name,
                        backlog_url,
                    )
                target_keys, subtask_keys, warnings = await asyncio.to_thread(
                    self._ensure_action_target_keys,
                    user_message,
                    requested_issue_keys,
                    "edit",
                    client,
                    server_name,
                    cloud_for_edit,
                    project_key,
                    max_results,
                    tool_lookup,
                )

                ticket_context_by_key: dict[str, dict[str, Any]] = {}
                if cloud_for_edit and "searchJiraIssuesUsingJql" in tool_lookup and target_keys:
                    ticket_context_by_key = await asyncio.to_thread(
                        self._fetch_tickets_by_keys,
                        client,
                        server_name,
                        cloud_for_edit,
                        target_keys,
                        max_results,
                    )
                skipped_parent_keys: list[str] = []
                if target_keys and self._requests_subtask_updates(user_message):
                    target_keys, skipped_parent_keys, parent_guard_warnings = self._apply_subtask_parent_guard(
                        user_message,
                        target_keys,
                        subtask_keys,
                        ticket_context_by_key,
                    )
                    warnings.extend(parent_guard_warnings)

                parent_context_by_key: dict[str, dict[str, Any]] = {}
                if cloud_for_edit and target_keys:
                    scoped_ticket_context = {
                        key: ticket_context_by_key.get(key, {})
                        for key in target_keys
                    }
                    parent_context_by_key = await asyncio.to_thread(
                        self._fetch_parent_ticket_contexts,
                        client,
                        server_name,
                        cloud_for_edit,
                        scoped_ticket_context,
                        max_results,
                    )

                updated_issue_keys: list[str] = []
                failed_issue_keys: list[str] = []
                failed_issue_messages: list[str] = []
                tickets: list[dict[str, Any]] = []
                preview_lines: list[str] = []
                per_issue_arguments: dict[str, dict[str, Any]] = {}
                per_issue_results: dict[str, dict[str, Any]] = {}
                operations: list[dict[str, Any]] = []
                summary_hint_for_edit = self._extract_summary_hint(user_message)
                should_update_description = self._is_description_update_request(user_message)

                for target_key in target_keys:
                    ticket_context = ticket_context_by_key.get(target_key, {})
                    parent_key = str(ticket_context.get("parent_key") or "").strip().upper()
                    parent_context = parent_context_by_key.get(parent_key, {}) if parent_key else {}
                    generated_description: str | None = None
                    if should_update_description:
                        issue_summary = _stringify_scalar(ticket_context.get("summary")) or summary_hint_for_edit
                        existing_description = _stringify_scalar(ticket_context.get("description")) or _adf_to_text(
                            ticket_context.get("description")
                        )
                        parent_summary = (
                            _stringify_scalar(parent_context.get("summary"))
                            or _stringify_scalar(ticket_context.get("parent_summary"))
                        )
                        parent_description = (
                            _adf_to_text(parent_context.get("description"))
                            or _stringify_scalar(parent_context.get("description"))
                            or _adf_to_text(ticket_context.get("parent_description"))
                            or _stringify_scalar(ticket_context.get("parent_description"))
                        )
                        try:
                            generated_description = await self._generate_issue_specific_description(
                                user_message=user_message,
                                issue_key=target_key,
                                issue_summary=issue_summary,
                                existing_description=existing_description,
                                parent_key=parent_key,
                                parent_summary=parent_summary,
                                parent_description=parent_description,
                            )
                        except Exception as exc:
                            detail = str(exc).strip() or type(exc).__name__
                            failed_issue_keys.append(target_key)
                            failed_issue_messages.append(f"{target_key}: description generation failed: {detail}")
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "edit",
                                    "status": "failed",
                                    "tool": "editJiraIssue",
                                    "detail": f"description generation failed: {detail}",
                                }
                            )
                            continue
                    fields_payload_override = self._build_fields_payload(
                        action="edit",
                        user_message=user_message,
                        summary_hint=summary_hint_for_edit,
                        issue_key=target_key,
                        project_key=project_key,
                        ticket_context=ticket_context,
                        parent_context=parent_context,
                        generated_description=generated_description,
                    )
                    if not fields_payload_override:
                        failed_issue_keys.append(target_key)
                        failed_issue_messages.append(
                            f"{target_key}: no editable fields were derived from the request."
                        )
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "edit",
                                "status": "failed",
                                "tool": "editJiraIssue",
                                "detail": "No editable fields were derived from the request.",
                            }
                        )
                        continue
                    arguments = self._build_action_arguments(
                        edit_schema,
                        "edit",
                        user_message,
                        backlog_url,
                        project_key,
                        board_id,
                        cloud_for_edit,
                        max_results,
                        target_key,
                        fields_payload_override=fields_payload_override,
                        ticket_context=ticket_context,
                    )
                    props = self._tool_properties(edit_schema)
                    self._set_tool_argument(arguments, props, ["summary", "title", "name"], fields_payload_override.get("summary"))
                    self._set_tool_argument(
                        arguments,
                        props,
                        ["description", "body", "details", "content"],
                        generated_description,
                    )
                    self._set_tool_argument(
                        arguments,
                        props,
                        ["fields", "payload", "update", "data"],
                        fields_payload_override,
                    )
                    priority_field_value = fields_payload_override.get("priority")
                    priority_name = (
                        _stringify_scalar(priority_field_value.get("name"))
                        if isinstance(priority_field_value, dict)
                        else _stringify_scalar(priority_field_value)
                    )
                    self._set_tool_argument(
                        arguments,
                        props,
                        ["priority", "priority_name", "priorityName"],
                        priority_name,
                    )
                    per_issue_arguments[target_key] = arguments
                    try:
                        result = await asyncio.to_thread(client.call_tool, server_name, "editJiraIssue", arguments)
                    except Exception as exc:
                        detail = str(exc).strip() or type(exc).__name__
                        failed_issue_keys.append(target_key)
                        failed_issue_messages.append(f"{target_key}: {detail}")
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "edit",
                                "status": "failed",
                                "tool": "editJiraIssue",
                                "detail": detail,
                            }
                        )
                        continue

                    result_dict = result if isinstance(result, dict) else {}
                    per_issue_results[target_key] = result_dict
                    tool_error = _extract_result_error_message(result_dict)
                    if tool_error:
                        failed_issue_keys.append(target_key)
                        failed_issue_messages.append(f"{target_key}: {tool_error}")
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "edit",
                                "status": "failed",
                                "tool": "editJiraIssue",
                                "detail": tool_error,
                            }
                        )
                        continue

                    parsed_tickets = _extract_tickets(result_dict)
                    self._apply_backlog_origin(backlog_url, parsed_tickets)
                    if parsed_tickets:
                        tickets.extend(parsed_tickets)
                    result_text = _extract_ticket_text(result_dict)
                    parsed_keys = self._collect_issue_keys(parsed_tickets, result_text)
                    if target_key in parsed_keys:
                        updated_issue_keys.append(target_key)
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "edit",
                                "status": "success",
                                "tool": "editJiraIssue",
                                "detail": "Ticket updated.",
                            }
                        )
                    else:
                        failed_issue_keys.append(target_key)
                        detail = "MCP call succeeded but no Jira key was parsed from the response."
                        failed_issue_messages.append(f"{target_key}: {detail}")
                        operations.append(
                            {
                                "issue_key": target_key,
                                "operation": "edit",
                                "status": "failed",
                                "tool": "editJiraIssue",
                                "detail": detail,
                            }
                        )

                    compact_preview = result_text.strip()
                    if compact_preview:
                        if len(compact_preview) > 200:
                            compact_preview = compact_preview[:200] + "... (truncated)"
                        preview_lines.append(f"{target_key}: {compact_preview}")

                unresolved_keys = [key for key in target_keys if key not in updated_issue_keys]
                if failed_issue_messages:
                    warnings.append("Failed updates: " + " | ".join(failed_issue_messages[:5]))
                if unresolved_keys:
                    warnings.append("Requested keys not confirmed as updated: " + ", ".join(unresolved_keys))
                if skipped_parent_keys:
                    warnings.append(
                        "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                    )

                operation_summary = self._summarize_operations(operations)
                if int(operation_summary.get("success") or 0) == 0:
                    details = "; ".join(failed_issue_messages[:5]) if failed_issue_messages else "No updates were applied."
                    raise RuntimeError(f"Jira edit failed. {details}")

                raw_result_json = json.dumps(
                    {
                        "requested_issue_keys": target_keys,
                        "updated_issue_keys": updated_issue_keys,
                        "failed_issue_keys": failed_issue_keys,
                        "failed_updates": failed_issue_messages,
                        "skipped_parent_issue_keys": skipped_parent_keys,
                        "per_issue_arguments": per_issue_arguments,
                        "per_issue_results": per_issue_results,
                        "operations": operations,
                        "tickets": tickets,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
                preview = "\n".join(preview_lines).strip()
                if len(preview) > 700:
                    preview = preview[:700] + "... (truncated)"

                return {
                    "action": "edit",
                    "agent": CONFIG.name,
                    "workspace_root": str(workspace_root),
                    "server": server_name,
                    "tool": "editJiraIssue",
                    "available_tools": available_tools,
                    "arguments": {"per_issue": per_issue_arguments},
                    "issue_key": issue_key,
                    "issue_keys": updated_issue_keys,
                    "requested_issue_keys": target_keys,
                    "updated_issue_keys": updated_issue_keys,
                    "failed_issue_keys": unresolved_keys,
                    "ticket_count": len(tickets),
                    "tickets": tickets,
                    "warnings": warnings,
                    "operations": operations,
                    "operation_summary": operation_summary,
                    "result_text_preview": preview,
                    "raw_result_json": raw_result_json,
                    "raw_result_path": raw_result_path,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }

            for tool_name in candidate_tool_names[:8]:
                tool_schema = tool_lookup.get(tool_name, {"name": tool_name})
                cloud_for_tool = cloud_id
                if not cloud_for_tool and self._tool_requires_cloud_id(tool_schema):
                    cloud_for_tool = await asyncio.to_thread(
                        self._resolve_cloud_id,
                        client,
                        server_name,
                        backlog_url,
                    )

                arguments = self._build_action_arguments(
                    tool_schema,
                    action,
                    user_message,
                    backlog_url,
                    project_key,
                    board_id,
                    cloud_for_tool,
                    max_results,
                    issue_key,
                )
                lowered_tool_name = tool_name.lower()
                is_mutating_tool = any(
                    token in lowered_tool_name
                    for token in ("create", "new", "update", "edit", "transition", "assign", "comment")
                )
                if action == "edit" and is_mutating_tool and not issue_key and not requested_issue_keys:
                    errors.append(
                        f"{tool_name}: skipped mutating tool because no Jira issue key was detected in the request."
                    )
                    continue
                try:
                    result = await asyncio.to_thread(client.call_tool, server_name, tool_name, arguments)
                except Exception as exc:
                    call_error_text = str(exc).strip() or type(exc).__name__
                    lowered_error = call_error_text.lower()
                    has_field_args = any("field" in str(key).lower() for key in arguments.keys())
                    can_retry_without_fields = has_field_args and (
                        "-32602" in lowered_error
                        or "invalid argument" in lowered_error
                        or "field" in lowered_error
                        or "expected type" in lowered_error
                    )
                    if can_retry_without_fields:
                        retry_arguments = {
                            key: value
                            for key, value in arguments.items()
                            if "field" not in str(key).lower()
                        }
                        try:
                            result = await asyncio.to_thread(
                                client.call_tool,
                                server_name,
                                tool_name,
                                retry_arguments,
                            )
                            arguments = retry_arguments
                        except Exception as retry_exc:
                            retry_text = str(retry_exc).strip() or type(retry_exc).__name__
                            errors.append(f"{tool_name}: {call_error_text} | retry(no fields): {retry_text}")
                            continue
                    else:
                        errors.append(f"{tool_name}: {call_error_text}")
                        continue

                result_dict = result if isinstance(result, dict) else {}
                tool_error_message = _extract_result_error_message(result_dict)
                if tool_error_message:
                    errors.append(f"{tool_name}: {tool_error_message}")
                    continue
                tickets = _extract_tickets(result_dict)
                self._apply_backlog_origin(backlog_url, tickets)
                result_text = _extract_ticket_text(result_dict)
                issue_keys = self._collect_issue_keys(tickets, result_text)
                warnings: list[str] = []
                if action in {"create", "edit"} and not any(
                    token in lowered_tool_name
                    for token in ("create", "new", "update", "edit", "transition", "assign", "comment")
                ):
                    warnings.append(
                        f"Selected tool `{tool_name}` may be non-mutating; verify Jira MCP exposes create/update tools."
                    )
                if action in {"view", "edit"} and issue_key and issue_key not in issue_keys and not tickets:
                    warnings.append(f"Requested ticket `{issue_key}` was not found in parsed results.")
                if not tickets and not issue_keys:
                    warnings.append("MCP call succeeded but no Jira keys were parsed from the response.")
                if action == "list" and not tickets:
                    cached = self._load_latest_cached_fetch()
                    if cached:
                        cached_tickets = cached.get("tickets") if isinstance(cached.get("tickets"), list) else []
                        tickets = [ticket for ticket in cached_tickets if isinstance(ticket, dict)]
                        issue_keys = self._collect_issue_keys(tickets, result_text)
                        cache_time = str(cached.get("created_at") or "").strip() or "an earlier run"
                        warnings.append(
                            f"Live Jira query returned 0 tickets; returned latest cached fetch from {cache_time}."
                        )

                raw_result_json = json.dumps(result_dict, indent=2, ensure_ascii=False)
                raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
                preview = result_text.strip()
                if len(preview) > 700:
                    preview = preview[:700] + "... (truncated)"
                updated_issue_keys: list[str] = []
                failed_issue_keys: list[str] = []
                operations: list[dict[str, Any]] = []
                if action == "edit":
                    if issue_key and (
                        issue_key in issue_keys
                        or any(str(ticket.get("key") or "").upper() == issue_key for ticket in tickets)
                    ):
                        updated_issue_keys.append(issue_key)
                        operations.append(
                            {
                                "issue_key": issue_key,
                                "operation": "edit",
                                "status": "success",
                                "tool": tool_name,
                                "detail": "Mutation completed.",
                            }
                        )
                    if issue_key and issue_key not in updated_issue_keys:
                        failed_issue_keys.append(issue_key)
                        operations.append(
                            {
                                "issue_key": issue_key,
                                "operation": "edit",
                                "status": "failed",
                                "tool": tool_name,
                                "detail": "Requested key was not confirmed in tool response.",
                            }
                        )
                operation_summary = self._summarize_operations(operations)
                return {
                    "action": action,
                    "agent": CONFIG.name,
                    "workspace_root": str(workspace_root),
                    "server": server_name,
                    "tool": tool_name,
                    "available_tools": available_tools,
                    "arguments": arguments,
                    "issue_key": issue_key,
                    "issue_keys": issue_keys,
                    "requested_issue_keys": [issue_key] if issue_key else [],
                    "updated_issue_keys": updated_issue_keys,
                    "failed_issue_keys": failed_issue_keys,
                    "ticket_count": len(tickets),
                    "tickets": tickets,
                    "warnings": warnings,
                    "operations": operations,
                    "operation_summary": operation_summary,
                    "result_text_preview": preview,
                    "raw_result_json": raw_result_json,
                    "raw_result_path": raw_result_path,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }

            if action == "list":
                cached = self._load_latest_cached_fetch()
                if cached:
                    cached_tickets = cached.get("tickets") if isinstance(cached.get("tickets"), list) else []
                    tickets = [ticket for ticket in cached_tickets if isinstance(ticket, dict)]
                    cache_time = str(cached.get("created_at") or "").strip() or "an earlier run"
                    return {
                        "action": action,
                        "agent": CONFIG.name,
                        "workspace_root": str(workspace_root),
                        "server": str(cached.get("server") or server_name),
                        "tool": str(cached.get("tool") or "cached_jira_fetch"),
                        "available_tools": available_tools,
                        "arguments": {},
                        "issue_key": issue_key,
                        "issue_keys": self._collect_issue_keys(tickets, ""),
                        "ticket_count": len(tickets),
                        "tickets": tickets,
                        "warnings": [
                            f"Live Jira query failed; returned latest cached fetch from {cache_time}.",
                            *errors[:3],
                        ],
                        "result_text_preview": "",
                        "raw_result_json": "",
                        "raw_result_path": "",
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    }

            details = "; ".join(errors[:5]) if errors else "No tool could satisfy the request."
            raise RuntimeError(f"Jira MCP tool execution failed. {details}")
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                self._mark_agent_end(self.agent_id, error_text)
            else:
                self._mark_agent_end(self.agent_id)
