from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.agent_registry import (
    AgentDefinition,
    make_agent_id,
    mark_agent_end,
    mark_agent_start,
    register_agent,
)
from app.agents_jira.runtime import (
    DEFAULT_BACKLOG_URL,
    JiraMCPAgent,
    _adf_to_text,
    _extract_attachments,
    _extract_comments,
    _extract_development_summary,
    _extract_field_value,
    _extract_history,
    _extract_sprint_names,
    _extract_story_points,
    _extract_string_list,
    _is_subtask,
    _stringify_scalar,
)
from app.agents_jira_content import JiraContentAgent
from app.agents_jira_api.config import CONFIG
from app.db import list_jira_fetches
from app.jira_conversation_state import (
    JiraConversationState,
    load_jira_conversation_state,
    save_jira_conversation_state,
)
from app.llm import LLMClient
from app.mcp_client import load_mcp_config
from app.settings_store import get_jira_settings, get_llm_function_settings

BACKLOG_URL_RE = re.compile(
    r"/projects/(?P<project>[A-Za-z0-9_]+)/boards/(?P<board>\d+)/backlog",
    re.IGNORECASE,
)

WORKFLOW_PAGE_FIELDS = [
    "summary",
    "description",
    "status",
    "assignee",
    "reporter",
    "priority",
    "labels",
    "duedate",
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

ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
ATTACHMENT_PATH_RE = re.compile(r"path=(?P<path>[^)\n]+)")
ATTACHMENT_CONTEXT_MARKER = "Attachment context for this conversation:"
FENCED_BLOCK_RE = re.compile(r"```(?:[^\n`]*)\n?(?P<body>.*?)```", re.DOTALL)
DESCRIPTION_CLEAR_RE = re.compile(
    r"(?:\b(?:wipe|clear|remove|delete|blank|empty)\b.*\bdescription\b)|(?:\bdescription\b.*\b(?:wipe|clear|remove|delete|blank|empty)\b)",
    re.IGNORECASE,
)
EDIT_FIELD_ASSIGNMENT_RE = re.compile(
    r"\b(?P<field>summary|title|priority|labels?|description|due(?:\s|-)?date|start(?:\s|-)?date)\b\s*(?:to|=|:)\s*(?P<value>.*?)"
    r"(?=(?:\s+\band\s+(?:summary|title|priority|labels?|description|due(?:\s|-)?date|start(?:\s|-)?date)\b\s*(?:to|=|:))|$)",
    re.IGNORECASE,
)
PRIORITY_INLINE_RE = re.compile(
    r"\b(?:priority|severity)\b\s*(?:to|=|:)\s*(?P<priority>[^.;,\n]+)",
    re.IGNORECASE,
)
DESCRIPTION_SECTION_TITLES = (
    "User Story",
    "Requirements",
    "Acceptance Criteria",
    "Agent Context",
    "Agent Prompt",
)
WORKSPACE_CONTEXT_SKIP_DIRS = {
    ".git",
    ".idea",
    ".next",
    ".nuxt",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "venv",
}
WORKSPACE_CONTEXT_ALLOWED_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".less",
    ".md",
    ".mjs",
    ".sass",
    ".scss",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}


def _stringify(value: Any) -> str:
    return _stringify_scalar(value)


def _parse_backlog_url(backlog_url: str | None) -> tuple[str | None, str | None]:
    text = str(backlog_url or "").strip()
    if not text:
        return (None, None)
    match = BACKLOG_URL_RE.search(text)
    if not match:
        return (None, None)
    project_key = str(match.group("project") or "").strip().upper() or None
    board_id = str(match.group("board") or "").strip() or None
    return (project_key, board_id)


def _parse_board_id_from_backlog_url(backlog_url: str | None) -> str | None:
    _project, board_id = _parse_backlog_url(backlog_url)
    return board_id


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


def _dedupe_tickets_by_key(*ticket_groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for group in ticket_groups:
        if not isinstance(group, list):
            continue
        for ticket in group:
            if not isinstance(ticket, dict):
                continue
            key = str(ticket.get("key") or "").strip().upper()
            if not key:
                continue
            if key not in by_key:
                by_key[key] = ticket
                continue
            existing = by_key[key]
            for field in (
                "status",
                "status_id",
                "summary",
                "updated",
                "priority",
                "assignee",
                "reporter",
                "issue_type",
            ):
                if not existing.get(field) and ticket.get(field):
                    existing[field] = ticket.get(field)
    return list(by_key.values())


def _normalized_status_name(text: str) -> str:
    return str(text or "").strip().lower()


def _normalized_status_id(text: str) -> str:
    return str(text or "").strip()


def _build_ticket_count_rows(tickets: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        name = _stringify(ticket.get(field)) or "Unknown"
        counts[name] = counts.get(name, 0) + 1
    rows = [{"name": name, "ticket_count": count} for name, count in counts.items()]
    rows.sort(key=lambda item: (-int(item.get("ticket_count") or 0), str(item.get("name") or "").lower()))
    return rows


def _normalize_transition_target(value: str) -> str:
    return str(value or "").strip().lower()


def _pick_column_by_name(kanban_columns: list[dict[str, Any]] | list[Any], column_name: str) -> dict[str, Any] | None:
    target = str(column_name or "").strip().lower()
    if not target or not isinstance(kanban_columns, list):
        return None
    for column in kanban_columns:
        if not isinstance(column, dict):
            continue
        if str(column.get("name") or "").strip().lower() == target:
            return column
    for column in kanban_columns:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip().lower()
        if name and target in name:
            return column
    return None


class JiraApiAgent:
    def __init__(self, registry_mode: str = "codex") -> None:
        self.registry_mode = registry_mode
        self.agent_id = make_agent_id(registry_mode, CONFIG.name)
        self._registered = False
        self.llm = LLMClient()
        self.content_agent = JiraContentAgent(registry_mode=registry_mode)

    def register(self) -> None:
        if self._registered:
            return
        self.content_agent.register()
        register_agent(
            AgentDefinition(
                id=self.agent_id,
                name=CONFIG.name,
                provider=None,
                model=None,
                group=CONFIG.group,
                role=CONFIG.role,
                kind="agent",
                dependencies=[self.content_agent.agent_id],
                source="app/agents_jira_api/runtime.py",
                description=CONFIG.description,
                capabilities=[
                    "jira",
                    "rest_api",
                    "agile_board",
                    "kanban_columns",
                    "ticket_fetch",
                    "ticket_list",
                    "ticket_view",
                    "ticket_create",
                    "ticket_edit",
                    "ticket_delete",
                    "ticket_attachment",
                    "delegated_ticket_content",
                ],
            )
        )
        self._registered = True

    @staticmethod
    def _base_url() -> str:
        value = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
        for suffix in ("/rest/api/3", "/rest/api/2", "/rest/agile/1.0"):
            if value.lower().endswith(suffix):
                return value[: -len(suffix)].rstrip("/")
        return value

    @staticmethod
    def _email() -> str:
        return str(os.getenv("JIRA_EMAIL") or "").strip()

    @staticmethod
    def _token() -> str:
        return str(os.getenv("JIRA_API_TOKEN") or "").strip()

    @classmethod
    def _validate_env(cls) -> None:
        missing: list[str] = []
        if not cls._base_url():
            missing.append("JIRA_BASE_URL")
        if not cls._email():
            missing.append("JIRA_EMAIL")
        if not cls._token():
            missing.append("JIRA_API_TOKEN")
        if missing:
            raise RuntimeError(f"Missing Jira REST env var(s): {', '.join(missing)}")

    @classmethod
    def _resolve_board_id(cls, board_id: str | None, backlog_url: str | None) -> str:
        resolved = str(board_id or "").strip() or str(_parse_board_id_from_backlog_url(backlog_url) or "").strip()
        if not resolved:
            raise RuntimeError("Jira board id is required to fetch board configuration.")
        if not resolved.isdigit():
            raise RuntimeError(f"Invalid Jira board id '{resolved}'.")
        return resolved

    @classmethod
    def _auth(cls) -> httpx.BasicAuth:
        return httpx.BasicAuth(cls._email(), cls._token())

    @classmethod
    def _headers(cls) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "AI-Multi-Agent-Assistant/1.0",
        }

    @staticmethod
    def _normalize_issue(issue: dict[str, Any], backlog_url: str) -> dict[str, Any] | None:
        key = _stringify(issue.get("key")).upper()
        if not key:
            return None
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        status_field = fields.get("status") if isinstance(fields, dict) else None
        assignee_field = fields.get("assignee") if isinstance(fields, dict) else None
        reporter_field = fields.get("reporter") if isinstance(fields, dict) else None
        priority_field = fields.get("priority") if isinstance(fields, dict) else None

        summary = _stringify(fields.get("summary")) or _stringify(issue.get("summary"))
        description = _adf_to_text(fields.get("description")) or _stringify(fields.get("description"))
        status = _stringify(status_field.get("name") if isinstance(status_field, dict) else status_field)
        status_id = _stringify(status_field.get("id") if isinstance(status_field, dict) else None)
        assignee = _stringify(assignee_field.get("displayName") if isinstance(assignee_field, dict) else assignee_field)
        reporter = _stringify(reporter_field.get("displayName") if isinstance(reporter_field, dict) else reporter_field)
        priority = _stringify(priority_field.get("name") if isinstance(priority_field, dict) else priority_field)
        updated = _stringify(fields.get("updated"))
        due_date = _stringify(_extract_field_value(fields, "duedate", "dueDate"))
        start_date = _stringify(_extract_field_value(fields, "startdate", "startDate", "customfield_10015"))
        labels = _extract_string_list(_extract_field_value(fields, "labels"))
        sprints = _extract_sprint_names(_extract_field_value(fields, "sprint", "sprints", "customfield_10020"))
        story_points = _extract_story_points(fields)
        team_raw = _extract_field_value(fields, "team", "customfield_10001")
        team = _stringify(team_raw) or _adf_to_text(team_raw)
        development = _extract_development_summary(_extract_field_value(fields, "development"))
        attachments = _extract_attachments(_extract_field_value(fields, "attachment"))
        comments = _extract_comments(_extract_field_value(fields, "comment"))
        history = _extract_history(issue.get("changelog"))
        issue_type = _stringify(
            fields.get("issuetype", {}).get("name") if isinstance(fields.get("issuetype"), dict) else fields.get("issuetype")
        )

        parent_field = fields.get("parent") if isinstance(fields.get("parent"), dict) else {}
        parent_fields = parent_field.get("fields") if isinstance(parent_field.get("fields"), dict) else {}
        parent_key = _stringify(parent_field.get("key") if isinstance(parent_field, dict) else fields.get("parent")).upper()
        parent_summary = _stringify(parent_fields.get("summary"))
        parent_description = _adf_to_text(parent_fields.get("description")) or _stringify(parent_fields.get("description"))

        ticket_url = _stringify(issue.get("self")) or _stringify(issue.get("url"))
        if not ticket_url and backlog_url:
            try:
                base = backlog_url.split("/jira/software/")[0].rstrip("/")
                if base:
                    ticket_url = f"{base}/browse/{key}"
            except Exception:
                ticket_url = ""

        start_date_field = next(
            (
                name
                for name in ("startdate", "startDate", "customfield_10015")
                if name in fields
            ),
            "",
        )
        story_points_field = next(
            (
                name
                for name in ("customfield_10016", "customfield_10026")
                if name in fields
            ),
            "",
        )
        team_field = next((name for name in ("team", "customfield_10001") if name in fields), "")
        sprint_field = next((name for name in ("sprint", "sprints", "customfield_10020") if name in fields), "")

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
            "start_date_field": start_date_field,
            "story_points_field": story_points_field,
            "team_field": team_field,
            "sprint_field": sprint_field,
            "url": ticket_url,
        }

    @classmethod
    def _build_status_lookups(
        cls,
        tickets: list[dict[str, Any]],
    ) -> tuple[dict[str, int], dict[str, int]]:
        by_status_name: dict[str, int] = {}
        by_status_id: dict[str, int] = {}
        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue
            status_name = _normalized_status_name(_stringify(ticket.get("status")))
            status_id = _normalized_status_id(_stringify(ticket.get("status_id")))
            if status_name:
                by_status_name[status_name] = by_status_name.get(status_name, 0) + 1
            if status_id:
                by_status_id[status_id] = by_status_id.get(status_id, 0) + 1
        return by_status_name, by_status_id

    @classmethod
    def _build_column_payload(
        cls,
        raw_columns: list[dict[str, Any]],
        ticket_union: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_status_name, by_status_id = cls._build_status_lookups(ticket_union)
        payload: list[dict[str, Any]] = []
        for index, column in enumerate(raw_columns):
            if not isinstance(column, dict):
                continue
            column_name = _stringify(column.get("name")) or f"Column {index + 1}"
            statuses_raw = column.get("statuses") if isinstance(column.get("statuses"), list) else []
            statuses: list[dict[str, str]] = []
            status_count = 0
            for status in statuses_raw:
                if not isinstance(status, dict):
                    continue
                status_id = _stringify(status.get("id"))
                status_name = _stringify(status.get("name")) or _stringify(status.get("status")) or _stringify(status.get("displayName"))
                if status_id:
                    status_count += by_status_id.get(status_id, 0)
                elif status_name:
                    status_count += by_status_name.get(_normalized_status_name(status_name), 0)
                statuses.append({"id": status_id, "name": status_name})
            payload.append(
                {
                    "name": column_name,
                    "ticket_count": status_count,
                    "source": "jira_rest_board_configuration",
                    "statuses": statuses,
                    "status_count": len(statuses),
                    "configured_index": index,
                    "min": column.get("min"),
                    "max": column.get("max"),
                }
            )
        total = sum(int(item.get("ticket_count") or 0) for item in payload)
        max_count = max((int(item.get("ticket_count") or 0) for item in payload), default=0)
        for item in payload:
            count = int(item.get("ticket_count") or 0)
            item["share_of_total"] = round((count / total), 4) if total else 0
            item["relative_width"] = round((count / max_count), 4) if max_count else 0
        return payload

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url()}{path}"
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            auth=self._auth(),
            headers=self._headers(),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = _stringify(payload.get("errorMessages")) or _stringify(payload.get("message"))
            except Exception:
                detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST {method} {path} failed ({response.status_code})" + (f": {detail}" if detail else "")
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected Jira REST response for {path}")
        return payload

    async def _search_issues_jql(
        self,
        client: httpx.AsyncClient,
        *,
        jql: str,
        max_results: int,
        fields: list[str],
        backlog_url: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        next_page_token: str | None = None
        page_size = max(1, min(max_results, 100))
        target_total = max(1, max_results)

        while len(normalized) < target_total:
            request_body: dict[str, Any] = {
                "jql": jql,
                "maxResults": min(page_size, target_total - len(normalized)),
                "fields": fields,
            }
            if next_page_token:
                request_body["nextPageToken"] = next_page_token

            payload = await self._request_json(
                client,
                "POST",
                "/rest/api/3/search/jql",
                json_body=request_body,
            )
            raw_pages.append(payload)
            issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
            if not issues:
                break
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                ticket = self._normalize_issue(issue, backlog_url)
                if ticket:
                    normalized.append(ticket)
            is_last = bool(payload.get("isLast"))
            token_value = payload.get("nextPageToken")
            next_page_token = str(token_value).strip() if token_value is not None else ""
            if is_last or not next_page_token:
                break
        return normalized, raw_pages

    @staticmethod
    def _primary_user_text(user_message: str) -> str:
        text = str(user_message or "")
        marker_index = text.find(ATTACHMENT_CONTEXT_MARKER)
        if marker_index < 0:
            return text
        return text[:marker_index]

    @staticmethod
    def _infer_action(user_message: str) -> str:
        primary_text = JiraApiAgent._primary_user_text(user_message)
        lowered = primary_text.lower()
        has_issue_key = bool(ISSUE_KEY_RE.search(primary_text))
        if any(token in lowered for token in ("delete", "remove")) and (
            has_issue_key or any(token in lowered for token in ("ticket", "issue", "story", "task"))
        ):
            return "delete"
        if has_issue_key and (
            "attach" in lowered
            or "attachment" in lowered
            or "screenshot" in lowered
            or ("upload" in lowered and ("file" in lowered or "image" in lowered))
        ):
            return "attach"
        return JiraMCPAgent._infer_action(primary_text)

    @staticmethod
    def _extract_issue_keys(user_message: str) -> list[str]:
        matches = ISSUE_KEY_RE.findall(user_message or "")
        ordered: list[str] = []
        for raw in matches:
            key = str(raw or "").strip().upper()
            if key and key not in ordered:
                ordered.append(key)
        return ordered

    @classmethod
    def _extract_latest_issue_key_from_memory(cls, memory: list[dict[str, str]] | None) -> str | None:
        if not memory:
            return None
        for entry in reversed(memory):
            content = str(entry.get("content") or "")
            keys = cls._extract_issue_keys(content)
            if keys:
                return keys[-1]
        return None

    @classmethod
    def _looks_like_create_follow_up_with_context(
        cls,
        user_message: str,
        state: JiraConversationState | None = None,
    ) -> bool:
        text = cls._primary_user_text(user_message).strip()
        if not text:
            return False
        lowered = text.lower()
        if JiraMCPAgent._has_explicit_create_intent(text):
            return True

        mentions_ticket_target = any(
            token in lowered
            for token in (
                "subtask",
                "subtasks",
                "child issue",
                "child issues",
                "ticket",
                "issue",
                "task",
                "another",
                "second",
                "third",
                "next one",
                "what about",
            )
        )
        if not mentions_ticket_target:
            return False

        requested_mode = str(state.requested_operation_mode or "").strip().lower() if isinstance(state, JiraConversationState) else ""
        return requested_mode in {"create", "create_new"}

    def _resolve_create_parent_key(
        self,
        *,
        issue_keys: list[str],
        selected_ticket_keys: list[str],
        conversation_memory: list[dict[str, str]] | None,
        conversation_state: JiraConversationState,
    ) -> str:
        explicit_keys = self._normalize_issue_keys(issue_keys)
        if explicit_keys:
            return explicit_keys[0]

        normalized_selected = self._normalize_issue_keys(selected_ticket_keys)
        if len(normalized_selected) == 1:
            return normalized_selected[0]

        state_keys = self._normalize_issue_keys(
            list(conversation_state.last_ticket_keys if isinstance(conversation_state.last_ticket_keys, list) else [])
        )
        if len(state_keys) == 1:
            return state_keys[0]

        latest_from_memory = self._extract_latest_issue_key_from_memory(conversation_memory)
        latest_candidates = self._normalize_issue_keys([latest_from_memory] if latest_from_memory else [])
        if len(latest_candidates) == 1:
            return latest_candidates[0]
        return ""

    @staticmethod
    def _split_conjoined_subtask_summary(summary: str) -> list[str]:
        text = str(summary or "").strip()
        if not text:
            return []
        match = re.match(
            r"^(?P<first>.+?)\s+(?:and|then)\s+(?P<second>(?:add|allow|create|implement|support|enable|build)\b.+)$",
            text,
            re.IGNORECASE,
        )
        if not match:
            return []
        first = JiraMCPAgent._clean_create_title_candidate(str(match.group("first") or "").strip())
        second = JiraMCPAgent._clean_create_title_candidate(str(match.group("second") or "").strip())
        if not first or not second:
            return []
        if first == second:
            return [first]
        return [first, second]

    @classmethod
    def _looks_like_create_request_line(cls, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        return bool(
            re.match(
                r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:create|add|open|raise|log)\b.*\b(ticket|issue|task|story|bug|subtask|subtasks|child issue|child issues)\b",
                text,
                re.IGNORECASE,
            )
        )

    @classmethod
    def _looks_like_generated_ticket_content(cls, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        lowered = text.lower()
        heading_hits = sum(
            1
            for heading in (
                "## user story",
                "## requirements",
                "## acceptance criteria",
                "## agent context",
                "## agent prompt",
            )
            if heading in lowered
        )
        if heading_hits >= 3:
            return True
        if "workspace root:" in lowered and "relevant files:" in lowered:
            return True
        if "agent context" in lowered and "agent prompt" in lowered:
            return True
        return False

    @classmethod
    def _extract_create_request_context_from_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        candidates: list[str] = []
        for match in FENCED_BLOCK_RE.finditer(text):
            body = str(match.group("body") or "").strip()
            if body:
                candidates.append(body)
        candidates.append(text)

        stop_prefixes = (
            "view thinking process",
            "matched existing jira ticket",
            "created jira ticket",
            "server:",
            "operation summary:",
            "warnings:",
            "task / ",
            "description",
            "acceptance criteria",
            "agent context",
            "agent prompt",
            "open in jira",
            "back",
        )

        def normalize(lines: list[str]) -> str:
            cleaned: list[str] = []
            previous_blank = False
            for raw_line in lines:
                line = raw_line.rstrip()
                if not line.strip():
                    if previous_blank:
                        continue
                    cleaned.append("")
                    previous_blank = True
                    continue
                cleaned.append(line.strip())
                previous_blank = False
            return "\n".join(cleaned).strip()

        for candidate in candidates:
            lines = candidate.splitlines()
            collected: list[str] = []
            started = False
            for raw_line in lines:
                line = raw_line.strip()
                lowered = line.lower()

                if not started:
                    if cls._looks_like_create_request_line(line):
                        started = True
                        collected.append(line)
                        continue
                    if lowered == "task:" and collected:
                        collected.append(line)
                        continue
                    if lowered == "task:":
                        started = True
                        collected.append(line)
                        continue
                    continue

                if lowered.startswith(stop_prefixes):
                    break

                if ISSUE_KEY_RE.search(line) and ("| create |" in lowered or "| attach |" in lowered):
                    break

                collected.append(line)

            normalized = normalize(collected)
            if cls._looks_like_generated_ticket_content(normalized):
                continue
            if normalized and (
                JiraMCPAgent._has_explicit_create_intent(normalized)
                or JiraMCPAgent._requests_create_parent_with_subtasks(normalized)
                or JiraMCPAgent._extract_create_titles(normalized)
                or "task:" in normalized.lower()
            ):
                return normalized

        return ""

    @classmethod
    def _extract_recent_user_create_context(
        cls,
        memory: list[dict[str, str]] | None,
        *,
        exclude_text: str = "",
    ) -> str:
        if not memory:
            return ""

        normalized_exclude = " ".join(cls._primary_user_text(exclude_text).lower().split())
        for entry in reversed(memory):
            if str(entry.get("role") or "").strip().lower() != "user":
                continue
            content = cls._primary_user_text(str(entry.get("content") or "")).strip()
            if not content:
                continue
            extracted_context = cls._extract_create_request_context_from_text(content) or content
            normalized = " ".join(extracted_context.lower().split())
            if normalized and normalized == normalized_exclude:
                continue
            if cls._looks_like_generated_ticket_content(extracted_context):
                continue
            if JiraMCPAgent._is_terse_create_follow_up(extracted_context):
                continue
            if (
                JiraMCPAgent._has_explicit_create_intent(extracted_context)
                or JiraMCPAgent._requests_create_parent_with_subtasks(extracted_context)
                or JiraMCPAgent._extract_create_titles(extracted_context)
                or "task:" in extracted_context.lower()
            ):
                return extracted_context
        return ""

    @classmethod
    def _build_create_message_with_state(
        cls,
        user_message: str,
        state: JiraConversationState | None,
    ) -> tuple[str, str]:
        primary_text = cls._primary_user_text(user_message).strip()
        if not JiraMCPAgent._is_terse_create_follow_up(primary_text):
            return user_message, user_message
        if not isinstance(state, JiraConversationState):
            return user_message, user_message

        prior_context = str(state.last_intended_jira_create_request or "").strip()
        if not prior_context or cls._looks_like_generated_ticket_content(prior_context):
            return user_message, user_message

        combined_message = (
            f"{user_message.strip()}\n\n"
            "Persisted Jira conversation state for this conversation:\n"
            f"{prior_context}"
        ).strip()
        return combined_message, prior_context

    @classmethod
    def _build_create_message_with_memory(
        cls,
        user_message: str,
        memory: list[dict[str, str]] | None,
        state: JiraConversationState | None = None,
    ) -> tuple[str, str]:
        primary_text = cls._primary_user_text(user_message).strip()
        if not JiraMCPAgent._is_terse_create_follow_up(primary_text):
            return user_message, user_message

        state_message, state_summary = cls._build_create_message_with_state(user_message, state)
        if state_message != user_message and state_summary != user_message:
            return state_message, state_summary

        prior_context = cls._extract_recent_user_create_context(memory, exclude_text=primary_text)
        if not prior_context:
            return user_message, user_message

        combined_message = (
            f"{user_message.strip()}\n\n"
            "Previous user request context for this new ticket:\n"
            f"{prior_context.strip()}"
        ).strip()
        return combined_message, prior_context

    @classmethod
    def _infer_action_with_memory(
        cls,
        user_message: str,
        memory: list[dict[str, str]] | None,
        state: JiraConversationState | None = None,
    ) -> str:
        action = cls._infer_action(user_message)
        if action != "list":
            return action

        primary_text = cls._primary_user_text(user_message).strip()
        if not primary_text:
            return action

        if JiraMCPAgent._is_terse_create_follow_up(primary_text):
            state_request = str(state.last_intended_jira_create_request or "").strip() if isinstance(state, JiraConversationState) else ""
            if state_request and not cls._looks_like_generated_ticket_content(state_request):
                return "create"
            prior_context = cls._extract_recent_user_create_context(memory, exclude_text=primary_text)
            if prior_context and JiraMCPAgent._has_explicit_create_intent(prior_context):
                return "create"
        if cls._looks_like_create_follow_up_with_context(primary_text, state):
            return "create"
        return action

    @staticmethod
    def _requires_issue_key(action: str) -> bool:
        return str(action or "").strip().lower() in {"view", "edit", "attach", "delete"}

    @staticmethod
    def _looks_like_generic_create_request(user_message: str) -> bool:
        primary_text = JiraApiAgent._primary_user_text(user_message).strip()
        if not primary_text:
            return False
        if re.fullmatch(
            r"(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:create|add|open|raise)\s+"
            r"(?:me\s+)?(?:a\s+|an\s+)?(?:new\s+|another\s+|separate\s+|brand[-\s]+new\s+)?"
            r"(?:jira\s+)?(?:ticket|issue|task)(?:\s+for\s+(?:this|that|it))?[.?!]?",
            primary_text,
            re.IGNORECASE,
        ):
            return True
        if JiraMCPAgent._is_terse_create_follow_up(primary_text):
            return True
        if JiraMCPAgent._extract_create_titles(primary_text):
            return False
        if "task:" in primary_text.lower():
            return False
        summary_hint = JiraMCPAgent._extract_primary_create_summary(primary_text).strip().lower()
        return summary_hint in {
            "",
            "new jira ticket",
            "new ticket",
            "jira ticket",
            "ticket",
            "issue",
            "task",
            "this",
            "that",
            "it",
            "one",
            "?",
            "for this",
            "for that",
            "for it",
        }

    @staticmethod
    def _looks_like_clarification_follow_up(user_message: str, pending_action: str) -> bool:
        text = JiraApiAgent._primary_user_text(user_message).strip()
        if not text:
            return False

        lowered = text.lower().strip(" .!?")
        if lowered in {
            "yes",
            "yeah",
            "yep",
            "ok",
            "okay",
            "sure",
            "thanks",
            "thank you",
            "no",
            "nope",
            "nah",
            "cancel",
            "stop",
            "never mind",
            "nevermind",
        }:
            return False

        if str(pending_action or "").strip().lower() == "create":
            if JiraMCPAgent._has_explicit_create_intent(text) and JiraApiAgent._looks_like_generic_create_request(text):
                return False
            return bool(ISSUE_KEY_RE.search(text) or "\n" in text or len(re.findall(r"[A-Za-z0-9]+", text)) >= 4)

        return bool(ISSUE_KEY_RE.search(text) or len(re.findall(r"[A-Za-z0-9]+", text)) >= 2)

    @staticmethod
    def _apply_pending_clarification_context(user_message: str, pending_action: str) -> str:
        primary_text = JiraApiAgent._primary_user_text(user_message).strip()
        attachment_context = ""
        marker_index = str(user_message or "").find(ATTACHMENT_CONTEXT_MARKER)
        if marker_index >= 0:
            attachment_context = str(user_message or "")[marker_index:].strip()

        action = str(pending_action or "").strip().lower()
        if action == "create" and primary_text and not JiraMCPAgent._has_explicit_create_intent(primary_text):
            parts = [
                "Please create a new Jira ticket for this request.",
                "",
                primary_text,
            ]
            if attachment_context:
                parts.extend(["", attachment_context])
            return "\n".join(parts).strip()
        return user_message

    @classmethod
    def _clarification_question_for_request(
        cls,
        *,
        user_message: str,
        action: str,
        issue_keys: list[str],
        attachment_paths: list[Path],
    ) -> str:
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "create" and cls._looks_like_generic_create_request(user_message):
            return "Can you provide a description of what you want the Jira ticket to cover?"

        if normalized_action == "delete" and not issue_keys:
            return "Can you provide the Jira ticket key you want to delete?"

        if normalized_action == "view" and not issue_keys:
            return "Can you provide the Jira ticket key you want me to view?"

        if normalized_action == "attach":
            if not issue_keys:
                return "Can you provide the Jira ticket key you want the attachment added to?"
            if not attachment_paths:
                return "Can you attach the file and tell me which Jira ticket it should be added to?"

        if normalized_action != "edit":
            return ""

        if cls._is_comment_request(user_message):
            if not issue_keys:
                return "Can you provide the Jira ticket key and the comment you want to add?"
            return ""

        if cls._is_transition_request(user_message):
            if not issue_keys:
                return "Can you provide the Jira ticket key and the status you want it moved to?"
            if not cls._extract_transition_target(user_message):
                return "Can you tell me which status you want the Jira ticket moved to?"
            return ""

        requested_updates = cls._extract_edit_field_updates(user_message)
        should_update_description = (
            cls._is_description_update_request(user_message)
            and "description" not in requested_updates
            and not DESCRIPTION_CLEAR_RE.search(user_message)
        )
        if not issue_keys:
            return "Can you provide the Jira ticket key and what you want changed?"
        if not requested_updates and not should_update_description and not DESCRIPTION_CLEAR_RE.search(user_message):
            return "Can you tell me what you want changed on that Jira ticket?"
        return ""

    @staticmethod
    def _clarification_result(
        *,
        workspace_root: Path,
        action: str,
        project_key: str | None,
        board_id: str | None,
        backlog_url: str,
        question: str,
    ) -> dict[str, Any]:
        return {
            "action": "clarify",
            "agent": CONFIG.name,
            "workspace_root": str(workspace_root),
            "backlog_url": backlog_url,
            "project_key": project_key,
            "board_id": board_id,
            "server": "jira_rest_api",
            "tool": "clarification_request",
            "available_tools": [],
            "arguments": {"question": question},
            "ticket_count": 0,
            "tickets": [],
            "issue_key": "",
            "issue_keys": [],
            "requested_issue_keys": [],
            "updated_issue_keys": [],
            "failed_issue_keys": [],
            "operations": [],
            "operation_summary": {"success": 0, "failed": 0, "skipped": 0, "by_type": {}},
            "warnings": [],
            "raw_result_json": json.dumps(
                {
                    "mode": "jira_rest_handle_request",
                    "action": "clarify",
                    "pending_action": action,
                    "question": question,
                },
                indent=2,
                ensure_ascii=False,
            ),
            "raw_result_path": None,
            "attachments_uploaded_count": 0,
            "created_issue_keys": [],
            "reused_issue_keys": [],
            "clarification_question": question,
            "pending_action": action,
        }

    @staticmethod
    def _operation_mode_for_state(user_message: str, action: str) -> str:
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "create":
            primary_text = JiraApiAgent._primary_user_text(user_message).strip()
            if JiraMCPAgent._allows_duplicate_create(primary_text) or JiraMCPAgent._has_explicit_create_intent(primary_text):
                return "create_new"
            return "create"
        if normalized_action == "edit":
            return "edit_existing"
        if normalized_action == "attach":
            return "attach_existing"
        if normalized_action == "delete":
            return "delete_existing"
        if normalized_action == "view":
            return "view_existing"
        if normalized_action == "clarify":
            return "clarify"
        return normalized_action or "unknown"

    @staticmethod
    def _extract_summary_hint(user_message: str) -> str:
        return JiraMCPAgent._extract_summary_hint(user_message)

    @staticmethod
    def _normalize_priority_name(raw_priority: str) -> str:
        return JiraMCPAgent._normalize_priority_name(raw_priority)

    @staticmethod
    def _extract_priority_name(user_message: str) -> str:
        return JiraMCPAgent._extract_priority_name(user_message)

    @staticmethod
    def _extract_edit_field_updates(user_message: str) -> dict[str, Any]:
        updates = JiraMCPAgent._extract_edit_field_updates(user_message)
        text = str(user_message or "").strip()
        if not text:
            return updates
        if DESCRIPTION_CLEAR_RE.search(text):
            return {"description": ""}
        for match in EDIT_FIELD_ASSIGNMENT_RE.finditer(text):
            raw_field = str(match.group("field") or "").strip()
            raw_value = str(match.group("value") or "").strip()
            if JiraMCPAgent._normalize_edit_field_name(raw_field) != "description":
                continue
            updates["description"] = JiraMCPAgent._sanitize_assignment_value(raw_value)
        return updates

    @staticmethod
    def _extract_attachment_paths(user_message: str) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for match in ATTACHMENT_PATH_RE.finditer(str(user_message or "")):
            raw_path = str(match.group("path") or "").strip()
            if not raw_path:
                continue
            # Attachment context appends lines with "path=/...)".
            cleaned = raw_path.rstrip(" )\t\r\n")
            if not cleaned:
                continue
            normalized = str(Path(cleaned))
            if normalized in seen:
                continue
            path = Path(cleaned)
            if not path.exists() or not path.is_file():
                continue
            seen.add(normalized)
            paths.append(path)
        return paths

    @staticmethod
    def _workspace_context_keywords(requested_summary: str, user_message: str) -> list[str]:
        text = " ".join(
            part
            for part in (
                str(requested_summary or "").strip(),
                JiraApiAgent._primary_user_text(user_message).strip(),
            )
            if part
        ).lower()
        stop_words = {
            "a",
            "an",
            "and",
            "all",
            "app",
            "attached",
            "attachment",
            "could",
            "change",
            "create",
            "design",
            "file",
            "for",
            "image",
            "look",
            "match",
            "new",
            "page",
            "please",
            "replace",
            "public",
            "ref",
            "reference",
            "relevant",
            "styles",
            "style",
            "that",
            "the",
            "ticket",
            "this",
            "to",
            "too",
            "ui",
            "update",
            "using",
            "want",
            "with",
            "within",
            "you",
        }
        keywords: list[str] = []
        for token in re.findall(r"[a-z0-9]{3,}", text):
            if token in stop_words or token.isdigit():
                continue
            if token not in keywords:
                keywords.append(token)
        return keywords[:8]

    @staticmethod
    def _score_workspace_path(relative_path: str, keywords: list[str]) -> int:
        normalized = relative_path.lower()
        parts = [part for part in re.split(r"[\\/._-]+", normalized) if part]
        score = 0
        for keyword in keywords:
            if keyword in parts:
                score += 5
            elif keyword in normalized:
                score += 2
        if any(token in normalized for token in ("landing", "hero", "header", "footer", "home")):
            score += 2
        if any(token in normalized for token in ("theme", "style", "styles", "token", "tokens")):
            score += 2
        if any(token in normalized for token in ("asset", "assets", "public", "image")):
            score += 1
        if normalized.startswith("src/"):
            score += 2
        if any(token in normalized for token in ("/components/", "/layouts/", "/features/", "/shared/")):
            score += 1
        if any(token in normalized for token in ("test", "tests/", ".test.", ".spec.", "stories", "storybook")):
            score -= 4
        return score

    @classmethod
    def _find_relevant_workspace_files(
        cls,
        workspace_root: Path,
        *,
        requested_summary: str,
        user_message: str,
    ) -> list[str]:
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return []

        keywords = cls._workspace_context_keywords(requested_summary, user_message)
        candidate_paths: list[tuple[int, str]] = []
        scanned_files = 0
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [
                name
                for name in dir_names
                if name not in WORKSPACE_CONTEXT_SKIP_DIRS and not name.startswith(".")
            ]
            for file_name in file_names:
                if file_name.startswith("."):
                    continue
                suffix = Path(file_name).suffix.lower()
                if suffix and suffix not in WORKSPACE_CONTEXT_ALLOWED_SUFFIXES:
                    continue
                absolute_path = Path(current_root) / file_name
                try:
                    relative_path = absolute_path.relative_to(root).as_posix()
                except Exception:
                    continue
                scanned_files += 1
                score = cls._score_workspace_path(relative_path, keywords)
                if score > 0:
                    candidate_paths.append((score, relative_path))
                if scanned_files >= 5000:
                    break
            if scanned_files >= 5000:
                break

        candidate_paths.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        relevant_files: list[str] = []
        for _score, relative_path in candidate_paths:
            if relative_path not in relevant_files:
                relevant_files.append(relative_path)
            if len(relevant_files) >= 6:
                break

        if not relevant_files:
            fallback_files: list[str] = []
            for name in ("src", "app", "components", "pages", "public", "assets", "styles"):
                candidate = root / name
                if candidate.exists():
                    fallback_files.append(f"{name}/" if candidate.is_dir() else name)
            relevant_files = fallback_files[:4]

        return relevant_files

    @classmethod
    def _build_workspace_context(
        cls,
        workspace_root: Path,
        *,
        requested_summary: str,
        user_message: str,
    ) -> str:
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return "N/A"

        relevant_files = cls._find_relevant_workspace_files(
            root,
            requested_summary=requested_summary,
            user_message=user_message,
        )

        lines = [
            f"Workspace root: {root}",
        ]
        if relevant_files:
            lines.append("Relevant files:")
            lines.extend(f"- {item}" for item in relevant_files)
        else:
            lines.append("Relevant files:")
            lines.append("- No relevant files were found in the selected workspace.")
        return "\n".join(lines).strip()

    @staticmethod
    def _infer_workspace_scope(relevant_files: list[str]) -> str:
        if not relevant_files:
            return "/"
        top_level_counts: dict[str, int] = {}
        for path in relevant_files:
            first = str(path).split("/", 1)[0].strip()
            if not first:
                continue
            top_level_counts[first] = int(top_level_counts.get(first) or 0) + 1
        if not top_level_counts:
            return "/"
        best = sorted(top_level_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return f"/{best}"

    @classmethod
    def _build_agent_prompt(
        cls,
        *,
        requested_summary: str,
        user_message: str,
        relevant_files: list[str],
        attachment_paths: list[Path],
    ) -> str:
        scope = cls._infer_workspace_scope(relevant_files)
        attachment_name = attachment_paths[0].name if attachment_paths else "the attached design reference"
        lines = [
            f"Update the UI styling in `{scope}` to match `{attachment_name}`.",
            "Keep the scope to styling and layout changes only; do not change unrelated logic or behavior.",
        ]
        if relevant_files:
            lines.append("Focus on these files first:")
            lines.extend(f"- `{path}`" for path in relevant_files)
        lines.append("Only modify files that are relevant to the style update.")
        lines.append("Use shared styling tokens/components where possible and keep the implementation consistent across the app.")
        return "\n".join(lines).strip()

    @staticmethod
    def _text_to_adf(text: str) -> dict[str, Any]:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        content: list[dict[str, Any]] = []
        for line in lines:
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": line}],
                }
            )
        if not content:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": ""}]})
        return {"type": "doc", "version": 1, "content": content}

    @staticmethod
    def _build_structured_description(user_message: str, summary: str) -> str:
        clean_summary = str(summary or "Ticket request").strip() or "Ticket request"
        section_content = {
            "User Story": f"As a team member, I need {clean_summary} so that the requested work is completed.",
            "Requirements": f"Implement work described by the ticket summary: {clean_summary}.",
            "Acceptance Criteria": "Requested behavior is implemented and verifiable in the target environment.",
            "Agent Context": "Generated by Jira REST API Agent in AI-Multi-Agent-Assistant.",
            "Agent Prompt": "",
        }
        lines: list[str] = []
        for title in DESCRIPTION_SECTION_TITLES:
            lines.append(f"## {title}")
            lines.append(str(section_content.get(title) or "").strip())
            lines.append("")
        return "\n".join(lines).strip()

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
    def _normalize_issue_keys(values: list[str]) -> list[str]:
        return JiraMCPAgent._normalize_issue_keys(values)

    @staticmethod
    def _requests_subtask_updates(user_message: str) -> bool:
        return JiraMCPAgent._requests_subtask_updates(user_message)

    @staticmethod
    def _requests_parent_ticket_update(user_message: str) -> bool:
        return JiraMCPAgent._requests_parent_ticket_update(user_message)

    @staticmethod
    def _is_description_update_request(user_message: str) -> bool:
        return JiraMCPAgent._is_description_update_request(user_message)

    @staticmethod
    def _is_ticket_rewrite_request(user_message: str) -> bool:
        return JiraMCPAgent._is_ticket_rewrite_request(user_message)

    @staticmethod
    def _reduce_to_primary_issue_for_singular_mutation(
        user_message: str,
        requested_issue_keys: list[str],
    ) -> tuple[list[str], list[str]]:
        return JiraMCPAgent._reduce_to_primary_issue_for_singular_mutation(user_message, requested_issue_keys)

    @staticmethod
    def _has_direct_field_update_intent(user_message: str) -> bool:
        return JiraMCPAgent._has_direct_field_update_intent(user_message)

    @staticmethod
    def _is_comment_request(user_message: str) -> bool:
        return JiraMCPAgent._is_comment_request(user_message)

    @staticmethod
    def _is_transition_request(user_message: str) -> bool:
        return JiraMCPAgent._is_transition_request(user_message)

    @staticmethod
    def _extract_comment_body(user_message: str) -> str:
        return JiraMCPAgent._extract_comment_body(user_message)

    @staticmethod
    def _extract_transition_target(user_message: str) -> str | None:
        return JiraMCPAgent._extract_transition_target(user_message)

    @staticmethod
    def _extract_create_titles(user_message: str) -> list[str]:
        return JiraMCPAgent._extract_create_titles(user_message)

    @staticmethod
    def _extract_primary_create_summary(user_message: str) -> str:
        return JiraMCPAgent._extract_primary_create_summary(user_message)

    @staticmethod
    def _extract_requested_create_count(user_message: str) -> int:
        return JiraMCPAgent._extract_requested_create_count(user_message)

    @staticmethod
    def _requests_create_parent_with_subtasks(user_message: str) -> bool:
        return JiraMCPAgent._requests_create_parent_with_subtasks(user_message)

    @staticmethod
    def _is_issue_type_validation_error(detail: str) -> bool:
        return JiraMCPAgent._is_issue_type_validation_error(detail)

    @staticmethod
    def _allows_duplicate_create(user_message: str) -> bool:
        return JiraMCPAgent._allows_duplicate_create(user_message)

    @staticmethod
    def _find_duplicate_ticket_for_create(
        requested_summary: str,
        candidate_tickets: list[dict[str, Any]],
        *,
        user_message: str,
    ) -> dict[str, Any] | None:
        return JiraMCPAgent._find_duplicate_ticket_for_create(
            requested_summary,
            candidate_tickets,
            user_message=user_message,
        )

    @staticmethod
    def _summarize_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
        return JiraMCPAgent._summarize_operations(operations)

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
        for name, _count in ranked_cached:
            if not name:
                continue
            if not create_is_subtask and name.strip().lower() == "epic":
                continue
            if name in candidates:
                continue
            candidates.append(name)
        return candidates

    async def _generate_issue_specific_description(
        self,
        *,
        user_message: str,
        issue_key: str,
        issue_summary: str,
        existing_description: str = "",
        parent_key: str = "",
        parent_summary: str = "",
        parent_description: str = "",
    ) -> str:
        summary = issue_summary.strip() or issue_key.strip() or "this Jira issue"
        normalized_issue_key = issue_key.strip().upper()
        normalized_parent_key = parent_key.strip().upper()
        normalized_parent_summary = parent_summary.strip()
        parent_label = (
            f"{normalized_parent_key}: {normalized_parent_summary}"
            if normalized_parent_key and normalized_parent_summary
            else normalized_parent_key or normalized_parent_summary or "Not specified"
        )
        request_text = JiraMCPAgent._truncate_text(user_message, 500)
        parent_context = JiraMCPAgent._truncate_text(parent_description, 700)
        existing_excerpt = JiraMCPAgent._truncate_text(existing_description, 500)
        parent_constraints = JiraMCPAgent._extract_parent_constraints(parent_description)
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

        normalized_generated = JiraMCPAgent._normalize_generated_description(generated_text)
        if normalized_generated:
            return normalized_generated
        if generated_text:
            return self._build_structured_description(generated_text, summary)
        if llm_errors:
            return self._build_structured_description(user_message, summary)
        return self._build_structured_description(user_message, summary)

    async def _get_issue_payload(
        self,
        client: httpx.AsyncClient,
        issue_key: str,
        *,
        include_activity: bool = False,
    ) -> dict[str, Any]:
        normalized_key = str(issue_key or "").strip().upper()
        if not normalized_key:
            raise RuntimeError("Issue key is required.")
        params: dict[str, Any] = {"fields": ",".join(WORKFLOW_PAGE_FIELDS)}
        if include_activity:
            params["expand"] = "changelog"
        payload = await self._request_json(
            client,
            "GET",
            f"/rest/api/3/issue/{normalized_key}",
            params=params,
        )
        return payload

    async def _get_issue(
        self,
        client: httpx.AsyncClient,
        issue_key: str,
        backlog_url: str,
        *,
        include_activity: bool = False,
    ) -> dict[str, Any]:
        payload = await self._get_issue_payload(
            client,
            issue_key,
            include_activity=include_activity,
        )
        ticket = self._normalize_issue(payload, backlog_url)
        if not ticket:
            raise RuntimeError(f"Issue {str(issue_key or '').strip().upper()} not found.")
        return ticket

    async def _create_issue(
        self,
        client: httpx.AsyncClient,
        *,
        project_key: str,
        summary: str,
        description_markdown: str,
        issue_type: str = "Task",
        priority_name: str = "",
        parent_key: str = "",
    ) -> str:
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": str(summary or "").strip()[:180] or "New Jira ticket",
            "description": self._text_to_adf(description_markdown),
        }
        if priority_name:
            fields["priority"] = {"name": priority_name}
        if parent_key:
            fields["parent"] = {"key": str(parent_key or "").strip().upper()}
        response = await client.post(
            f"{self._base_url()}/rest/api/3/issue",
            auth=self._auth(),
            headers=self._headers(),
            json={"fields": fields},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST create issue failed ({response.status_code})" + (f": {detail}" if detail else "")
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Jira REST create issue response.")
        key = _stringify(payload.get("key")).upper()
        if not key:
            raise RuntimeError("Jira issue create succeeded but no issue key was returned.")
        return key

    async def _edit_issue(self, client: httpx.AsyncClient, issue_key: str, fields: dict[str, Any]) -> None:
        normalized_key = str(issue_key or "").strip().upper()
        if not normalized_key:
            raise RuntimeError("Issue key is required for edit.")
        if not fields:
            raise RuntimeError("No Jira fields were provided for edit.")

        payload_fields = dict(fields)
        if isinstance(payload_fields.get("description"), str):
            payload_fields["description"] = self._text_to_adf(str(payload_fields.get("description") or ""))
        response = await client.put(
            f"{self._base_url()}/rest/api/3/issue/{normalized_key}",
            auth=self._auth(),
            headers=self._headers(),
            json={"fields": payload_fields},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST edit issue failed for {normalized_key} ({response.status_code})"
                + (f": {detail}" if detail else "")
            ) from exc

    async def _delete_issue(self, client: httpx.AsyncClient, issue_key: str) -> None:
        normalized_key = str(issue_key or "").strip().upper()
        if not normalized_key:
            raise RuntimeError("Issue key is required for delete.")

        response = await client.delete(
            f"{self._base_url()}/rest/api/3/issue/{normalized_key}",
            auth=self._auth(),
            headers=self._headers(),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST delete issue failed for {normalized_key} ({response.status_code})"
                + (f": {detail}" if detail else "")
            ) from exc

    async def _add_comment_to_issue(
        self,
        client: httpx.AsyncClient,
        issue_key: str,
        comment_body: str,
    ) -> None:
        normalized_key = str(issue_key or "").strip().upper()
        if not normalized_key:
            raise RuntimeError("Issue key is required for comment.")
        response = await client.post(
            f"{self._base_url()}/rest/api/3/issue/{normalized_key}/comment",
            auth=self._auth(),
            headers=self._headers(),
            json={"body": self._text_to_adf(comment_body)},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST add comment failed for {normalized_key} ({response.status_code})"
                + (f": {detail}" if detail else "")
            ) from exc

    async def _search_users(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self._base_url()}/rest/api/3/user/search",
            auth=self._auth(),
            headers=self._headers(),
            params={"query": str(query or "").strip(), "maxResults": 25},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST user search failed ({response.status_code})" + (f": {detail}" if detail else "")
            ) from exc
        payload = response.json()
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    async def _resolve_user_account_id(
        self,
        client: httpx.AsyncClient,
        raw_value: Any,
        *,
        allow_clear: bool = False,
    ) -> str | None:
        value = str(raw_value or "").strip()
        if not value:
            return "" if allow_clear else None
        lowered = value.lower()
        if allow_clear and lowered in {"none", "clear", "unassigned", "nobody", "null"}:
            return ""

        users = await self._search_users(client, value)
        if not users:
            raise RuntimeError(f"No Jira user matched '{value}'.")

        exact_matches = [
            item
            for item in users
            if str(item.get("displayName") or "").strip().lower() == lowered
            or str(item.get("emailAddress") or "").strip().lower() == lowered
            or str(item.get("accountId") or "").strip() == value
        ]
        selected = exact_matches[0] if exact_matches else users[0]
        account_id = _stringify(selected.get("accountId"))
        if not account_id:
            raise RuntimeError(f"Matched Jira user for '{value}', but no accountId was returned.")
        return account_id

    async def _resolve_sprint_id(
        self,
        client: httpx.AsyncClient,
        board_id: str | None,
        sprint_value: Any,
    ) -> str:
        resolved_board_id = self._resolve_board_id(board_id, None)
        raw_target = str(sprint_value or "").strip()
        if not raw_target:
            raise RuntimeError("Sprint value is required.")
        if raw_target.isdigit():
            return raw_target

        payload = await self._request_json(
            client,
            "GET",
            f"/rest/agile/1.0/board/{resolved_board_id}/sprint",
            params={"state": "active,future,closed", "maxResults": 100},
        )
        values = payload.get("values") if isinstance(payload.get("values"), list) else []
        target = raw_target.lower()
        for item in values:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name.lower() == target:
                sprint_id = _stringify(item.get("id"))
                if sprint_id:
                    return sprint_id
        for item in values:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if target in name.lower():
                sprint_id = _stringify(item.get("id"))
                if sprint_id:
                    return sprint_id
        raise RuntimeError(f"No Jira sprint matched '{raw_target}' on board {resolved_board_id}.")

    async def _move_issues_to_sprint(
        self,
        client: httpx.AsyncClient,
        sprint_id: str,
        issue_keys: list[str],
    ) -> None:
        normalized_keys = self._normalize_issue_keys(issue_keys)
        if not sprint_id or not normalized_keys:
            raise RuntimeError("Sprint id and issue keys are required.")
        response = await client.post(
            f"{self._base_url()}/rest/agile/1.0/sprint/{sprint_id}/issue",
            auth=self._auth(),
            headers=self._headers(),
            json={"issues": normalized_keys},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST sprint update failed ({response.status_code})" + (f": {detail}" if detail else "")
            ) from exc

    async def _prepare_edit_fields(
        self,
        client: httpx.AsyncClient,
        *,
        issue_context: dict[str, Any],
        requested_updates: dict[str, Any],
        user_message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload_fields: dict[str, Any] = {}
        extra_actions: dict[str, Any] = {}
        for field_name, raw_value in requested_updates.items():
            if field_name == "summary":
                payload_fields["summary"] = str(raw_value or "").strip()[:180]
                continue
            if field_name == "priority":
                payload_fields["priority"] = raw_value if isinstance(raw_value, dict) else {"name": str(raw_value or "").strip()}
                continue
            if field_name == "labels":
                payload_fields["labels"] = raw_value if isinstance(raw_value, list) else [str(raw_value or "").strip()]
                continue
            if field_name == "duedate":
                payload_fields["duedate"] = str(raw_value or "").strip()
                continue
            if field_name == "startdate":
                target_field = str(issue_context.get("start_date_field") or "customfield_10015").strip()
                payload_fields[target_field] = str(raw_value or "").strip()
                continue
            if field_name == "story_points":
                target_field = str(issue_context.get("story_points_field") or "customfield_10016").strip()
                payload_fields[target_field] = raw_value
                continue
            if field_name == "team":
                target_field = str(issue_context.get("team_field") or "customfield_10001").strip()
                payload_fields[target_field] = raw_value
                continue
            if field_name == "sprint":
                extra_actions["sprint"] = raw_value
                continue
            if field_name == "assignee":
                account_id = await self._resolve_user_account_id(client, raw_value, allow_clear=True)
                payload_fields["assignee"] = {"accountId": account_id} if account_id else None
                continue
            if field_name == "reporter":
                account_id = await self._resolve_user_account_id(client, raw_value)
                if not account_id:
                    raise RuntimeError("Reporter accountId could not be resolved.")
                payload_fields["reporter"] = {"accountId": account_id}
                continue
            if re.fullmatch(r"customfield_\d+", field_name):
                payload_fields[field_name] = raw_value
                continue
            payload_fields[field_name] = raw_value

        if DESCRIPTION_CLEAR_RE.search(user_message):
            payload_fields["description"] = ""
        return payload_fields, extra_actions

    async def _fetch_tickets_by_keys(
        self,
        client: httpx.AsyncClient,
        issue_keys: list[str],
        backlog_url: str,
        max_results: int,
    ) -> dict[str, dict[str, Any]]:
        normalized_keys = self._normalize_issue_keys(issue_keys)
        if not normalized_keys:
            return {}
        quoted = ", ".join(f"'{key}'" for key in normalized_keys)
        tickets, _raw_pages = await self._search_issues_jql(
            client,
            jql=f"key in ({quoted}) ORDER BY updated DESC",
            max_results=max(max_results, len(normalized_keys)),
            fields=list(WORKFLOW_PAGE_FIELDS),
            backlog_url=backlog_url,
        )
        return {
            str(ticket.get("key") or "").strip().upper(): ticket
            for ticket in tickets
            if isinstance(ticket, dict) and str(ticket.get("key") or "").strip()
        }

    async def _find_subtask_keys(
        self,
        client: httpx.AsyncClient,
        parent_keys: list[str],
        backlog_url: str,
        max_results: int,
    ) -> list[str]:
        keys: list[str] = []
        for parent_key in self._normalize_issue_keys(parent_keys):
            tickets, _raw_pages = await self._search_issues_jql(
                client,
                jql=f"parent = {parent_key} ORDER BY priority DESC, updated DESC",
                max_results=max(5, min(max_results, 100)),
                fields=list(WORKFLOW_PAGE_FIELDS),
                backlog_url=backlog_url,
            )
            for ticket in tickets:
                key = str(ticket.get("key") or "").strip().upper()
                if key and key != parent_key and key not in keys:
                    keys.append(key)
        return keys

    async def _find_project_subtask_keys(
        self,
        client: httpx.AsyncClient,
        project_key: str | None,
        backlog_url: str,
        max_results: int,
    ) -> list[str]:
        jql_parts = []
        if project_key:
            jql_parts.append(f"project = {project_key}")
        jql_parts.append("parent is not EMPTY")
        tickets, _raw_pages = await self._search_issues_jql(
            client,
            jql=" AND ".join(jql_parts) + " ORDER BY updated DESC",
            max_results=max(5, min(max_results, 100)),
            fields=list(WORKFLOW_PAGE_FIELDS),
            backlog_url=backlog_url,
        )
        return [
            str(ticket.get("key") or "").strip().upper()
            for ticket in tickets
            if isinstance(ticket, dict) and str(ticket.get("key") or "").strip()
        ]

    async def _resolve_target_keys_for_edit(
        self,
        client: httpx.AsyncClient,
        *,
        user_message: str,
        requested_issue_keys: list[str],
        project_key: str | None,
        backlog_url: str,
        max_results: int,
    ) -> tuple[list[str], list[str], list[str]]:
        target_keys = self._normalize_issue_keys(requested_issue_keys)
        warnings: list[str] = []
        subtask_keys: list[str] = []
        if not self._requests_subtask_updates(user_message):
            return target_keys, subtask_keys, warnings

        if target_keys:
            subtask_keys = await self._find_subtask_keys(
                client,
                target_keys,
                backlog_url,
                max_results,
            )
            for key in subtask_keys:
                if key not in target_keys:
                    target_keys.append(key)
            return self._normalize_issue_keys(target_keys), self._normalize_issue_keys(subtask_keys), warnings

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
                return target_keys, [], warnings

        project_subtasks = await self._find_project_subtask_keys(
            client,
            project_key,
            backlog_url,
            max_results,
        )
        target_keys = self._normalize_issue_keys(project_subtasks)
        if target_keys:
            warnings.append("No explicit Jira key provided; applied request to recent project subtasks.")
        return target_keys, [], warnings

    async def _ensure_action_target_keys(
        self,
        client: httpx.AsyncClient,
        *,
        user_message: str,
        requested_issue_keys: list[str],
        action: str,
        project_key: str | None,
        backlog_url: str,
        max_results: int,
    ) -> tuple[list[str], list[str], list[str]]:
        target_keys = self._normalize_issue_keys(requested_issue_keys)
        subtask_keys: list[str] = []
        warnings: list[str] = []

        if self._requests_subtask_updates(user_message):
            target_keys, subtask_keys, warnings = await self._resolve_target_keys_for_edit(
                client,
                user_message=user_message,
                requested_issue_keys=target_keys,
                project_key=project_key,
                backlog_url=backlog_url,
                max_results=max_results,
            )
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

    async def _add_attachments_to_issue(
        self,
        client: httpx.AsyncClient,
        issue_key: str,
        attachment_paths: list[Path],
    ) -> int:
        normalized_key = str(issue_key or "").strip().upper()
        if not normalized_key:
            raise RuntimeError("Issue key is required for attachments.")
        if not attachment_paths:
            raise RuntimeError("No attachment files were provided.")

        files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
        for path in attachment_paths:
            filename = path.name or "attachment.bin"
            content = path.read_bytes()
            files_payload.append(("file", (filename, content, "application/octet-stream")))

        response = await client.post(
            f"{self._base_url()}/rest/api/3/issue/{normalized_key}/attachments",
            auth=self._auth(),
            headers={**self._headers(), "X-Atlassian-Token": "no-check"},
            files=files_payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Jira REST add attachment failed for {normalized_key} ({response.status_code})"
                + (f": {detail}" if detail else "")
            ) from exc

        payload = response.json()
        if isinstance(payload, list):
            return len(payload)
        return 0

    @staticmethod
    def format_chat_reply(result: dict[str, Any], max_tickets: int = 20) -> str:
        action = str(result.get("action") or "").strip().lower() or "list"
        updated_issue_keys = result.get("updated_issue_keys") if isinstance(result.get("updated_issue_keys"), list) else []

        if action == "clarify":
            return str(result.get("clarification_question") or "Can you provide more detail about the Jira request?").strip()
        if action == "attach":
            warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
            attached = [str(item).strip().upper() for item in updated_issue_keys if str(item).strip()]
            total_attachments = int(result.get("attachments_uploaded_count") or 0)
            lines: list[str] = []
            lines.append(
                "Added attachment(s) to Jira ticket(s): "
                + (", ".join(attached) if attached else "no tickets were updated.")
            )
            lines.append(f"Attachments uploaded: {total_attachments}")
            if warnings:
                lines.append("Warnings: " + " ".join(str(item) for item in warnings))
            return "\n".join(lines).strip()
        if action == "delete":
            deleted = [str(item).strip().upper() for item in updated_issue_keys if str(item).strip()]
            if deleted:
                return "Deleted Jira ticket(s): " + ", ".join(deleted)
            return "No Jira tickets were deleted."
        return JiraMCPAgent.format_chat_reply(result, max_tickets=max_tickets)

    async def handle_ticket_request(
        self,
        workspace_root: Path,
        user_message: str,
        conversation_memory: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
        selected_ticket_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            self._validate_env()
            conversation_state = load_jira_conversation_state(workspace_root, conversation_id)
            config = load_mcp_config(workspace_root)
            tooling = config.tooling.get("jira") if config and config.tooling else {}
            jira_tooling = tooling if isinstance(tooling, dict) else {}

            backlog_url = str(jira_tooling.get("backlog_url") or "").strip() or DEFAULT_BACKLOG_URL
            project_key = str(jira_tooling.get("project_key") or "").strip().upper() or None
            board_id = str(jira_tooling.get("board_id") or "").strip() or None
            parsed_project, parsed_board = _parse_backlog_url(backlog_url)
            project_key = project_key or parsed_project
            board_id = board_id or parsed_board

            # Fall back to DB-stored config (set via the Workflow Tasks UI)
            if not project_key or not board_id:
                stored = get_jira_settings()
                project_key = project_key or str(stored.get("project_key") or "").strip().upper() or None
                board_id = board_id or str(stored.get("board_id") or "").strip() or None

            jira_base_url = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
            if not backlog_url and project_key and board_id and jira_base_url:
                backlog_url = f"{jira_base_url}/jira/software/projects/{project_key}/boards/{board_id}/backlog"

            max_results = int(str(jira_tooling.get("max_results") or "100") or "100")
            max_results = max(1, min(max_results, 200))

            action = self._infer_action_with_memory(user_message, conversation_memory, conversation_state)
            pending_action = str(conversation_state.pending_clarification_action or "").strip().lower()
            used_pending_clarification = False
            if pending_action and action == "list" and self._looks_like_clarification_follow_up(user_message, pending_action):
                action = pending_action
                user_message = self._apply_pending_clarification_context(user_message, pending_action)
                used_pending_clarification = True

            normalized_selected_ticket_keys = self._normalize_issue_keys(list(selected_ticket_keys or []))
            used_selected_ticket_key_scope = False
            issue_keys = self._extract_issue_keys(user_message)
            if (
                not issue_keys
                and normalized_selected_ticket_keys
                and action in {"create", "view", "edit", "attach", "delete"}
            ):
                issue_keys = list(normalized_selected_ticket_keys)
                used_selected_ticket_key_scope = True
            requested_issue_keys = list(issue_keys)
            warnings: list[str] = []
            if used_selected_ticket_key_scope:
                warnings.append("Used selected Jira ticket key(s) from chat context.")
            requested_summary_for_state = ""
            relevant_files_for_state: list[str] = []
            attachment_paths = self._extract_attachment_paths(user_message)

            clarification_question = self._clarification_question_for_request(
                user_message=user_message,
                action=action,
                issue_keys=issue_keys,
                attachment_paths=attachment_paths,
            )
            if clarification_question:
                conversation_state.pending_clarification_action = action
                conversation_state.pending_clarification_question = clarification_question
                conversation_state.project_key = str(project_key or "").strip().upper()
                conversation_state.board_id = str(board_id or "").strip()
                conversation_state.backlog_url = backlog_url
                conversation_state.workspace_root = str(workspace_root)
                state_path = save_jira_conversation_state(workspace_root, conversation_id, conversation_state)
                result = self._clarification_result(
                    workspace_root=workspace_root,
                    action=action,
                    project_key=project_key,
                    board_id=board_id,
                    backlog_url=backlog_url,
                    question=clarification_question,
                )
                if state_path:
                    result["warnings"] = [f"Saved Jira conversation state to {state_path}."]
                return result

            if not project_key or not board_id:
                return {
                    "action": "list",
                    "tickets": [],
                    "message": (
                        "Jira is not configured yet. "
                        "Go to Workflow Tasks, enter your Project key and Board number, "
                        "and click Fetch Tasks to get started."
                    ),
                    "warnings": [],
                }

            cached_fetches = list_jira_fetches(limit=1)
            if cached_fetches:
                row = cached_fetches[0]
                prefetch_result: dict[str, Any] = {
                    "tickets": json.loads(row.get("tickets_json") or "[]"),
                    "current_sprint": json.loads(row.get("current_sprint_json") or "{}") or {},
                    "kanban_columns": json.loads(row.get("kanban_columns_json") or "[]"),
                    "server": row.get("server") or "jira_rest_api",
                    "tool": "cache",
                    "backlog_url": row.get("backlog_url") or backlog_url,
                    "ticket_count": int(row.get("ticket_count") or 0),
                    "warnings": json.loads(row.get("warnings_json") or "[]"),
                    "fetched_at": str(row.get("created_at") or ""),
                }
            else:
                prefetch_result = {
                    "tickets": [],
                    "current_sprint": {},
                    "kanban_columns": [],
                    "server": "jira_rest_api",
                    "tool": "cache",
                    "backlog_url": backlog_url,
                    "ticket_count": 0,
                    "warnings": [],
                    "fetched_at": "",
                }

            prefetch_count = int(prefetch_result.get("ticket_count") or 0)
            fetched_at = str(prefetch_result.get("fetched_at") or "")
            cache_note = f" (cached {fetched_at})" if fetched_at else " (from cache)"
            warnings.append(f"Using {prefetch_count} cached Jira ticket(s){cache_note}.")
            prefetch_warnings = prefetch_result.get("warnings") if isinstance(prefetch_result.get("warnings"), list) else []

            for warning in prefetch_warnings:
                text = str(warning or "").strip()

                if text:
                    warnings.append(f"Cache: {text}")
            if used_pending_clarification:
                warnings.append("Used the previous Jira clarification prompt to interpret this follow-up.")
            tickets: list[dict[str, Any]] = []
            updated_issue_keys: list[str] = []
            failed_issue_keys: list[str] = []
            operations: list[dict[str, Any]] = []
            created_issue_keys: list[str] = []
            reused_issue_keys: list[str] = []
            relevant_files_for_state: list[str] = []
            requested_summary_for_state: str = ""

            timeout = httpx.Timeout(20.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                if action == "list":
                    cached_tickets: list[dict[str, Any]] = prefetch_result.get("tickets") or []

                    if not cached_tickets:
                        return {
                            "action": "list",
                            "tickets": [],
                            "server": prefetch_result.get("server") or "jira_rest_api",
                            "tool": "cache",
                            "ticket_count": 0,
                            "message": (
                                "No tickets found in cache. "
                                "Please go to Workflow Tasks and click 'Fetch Tasks' to load your tickets."
                            ),
                            "warnings": warnings,
                        }

                    if issue_keys:
                        key_set = {k.upper() for k in issue_keys}
                        tickets = [t for t in cached_tickets if str(t.get("key") or "").upper() in key_set]
                    else:
                        tickets = list(cached_tickets)
                elif action == "view":
                    if not issue_keys:
                        raise RuntimeError("No Jira issue key detected for view request.")
                    ticket = await self._get_issue(client, issue_keys[0], backlog_url, include_activity=True)
                    tickets = [ticket]
                elif action == "create":
                    if not project_key:
                        raise RuntimeError("Unable to resolve Jira project key for create operation.")
                    create_user_message, create_summary_source = self._build_create_message_with_memory(
                        user_message,
                        conversation_memory,
                        conversation_state,
                    )
                    if create_user_message != user_message:
                        warnings.append("Used previous conversation context to scope this create request.")
                    create_parent_with_subtasks = self._requests_create_parent_with_subtasks(create_summary_source)
                    create_is_subtask = self._requests_subtask_updates(create_summary_source) and not create_parent_with_subtasks
                    parent_key = (
                        self._resolve_create_parent_key(
                            issue_keys=issue_keys,
                            selected_ticket_keys=normalized_selected_ticket_keys,
                            conversation_memory=conversation_memory,
                            conversation_state=conversation_state,
                        )
                        if create_is_subtask
                        else ""
                    )
                    if create_is_subtask and not parent_key:
                        raise RuntimeError(
                            "Subtask creation requested, but no parent Jira key was detected. Include a parent key like DEV-8."
                        )

                    create_summaries = self._extract_create_titles(create_summary_source)
                    if create_parent_with_subtasks:
                        create_summaries = [self._extract_primary_create_summary(create_summary_source)]
                    elif not create_summaries:
                        create_summaries = [self._extract_summary_hint(create_summary_source)]
                    create_summaries = [item.strip() for item in create_summaries if item.strip()][:20]
                    if not create_summaries:
                        create_summaries = ["New subtask" if create_is_subtask else "New Jira ticket"]
                    requested_create_count = (
                        self._extract_requested_create_count(create_summary_source) if create_is_subtask else 0
                    )
                    if requested_create_count > 0:
                        if len(create_summaries) > requested_create_count:
                            create_summaries = create_summaries[:requested_create_count]
                        elif len(create_summaries) == 1 and requested_create_count == 2:
                            expanded = self._split_conjoined_subtask_summary(create_summaries[0])
                            if len(expanded) == 2:
                                create_summaries = expanded
                        if len(create_summaries) < requested_create_count:
                            warnings.append(
                                f"Requested {requested_create_count} subtasks, but only derived {len(create_summaries)} title(s) from the message."
                            )

                    priority_name = self._extract_priority_name(create_user_message)
                    parent_context: dict[str, Any] = {}
                    if parent_key:
                        parent_context = await self._get_issue(
                            client,
                            parent_key,
                            backlog_url,
                            include_activity=True,
                        )
                    requested_summary = (
                        self._extract_primary_create_summary(create_summary_source)
                        if create_parent_with_subtasks
                        else (create_summaries[0] if create_summaries else self._extract_summary_hint(create_summary_source))
                    )
                    requested_summary_for_state = requested_summary
                    workspace_context = self._build_workspace_context(
                        workspace_root,
                        requested_summary=requested_summary,
                        user_message=create_user_message,
                    )
                    relevant_files = self._find_relevant_workspace_files(
                        workspace_root,
                        requested_summary=requested_summary,
                        user_message=create_user_message,
                    )
                    relevant_files_for_state = list(relevant_files)
                    agent_prompt = self._build_agent_prompt(
                        requested_summary=requested_summary,
                        user_message=create_user_message,
                        relevant_files=relevant_files,
                        attachment_paths=attachment_paths,
                    )

                    failed_issue_keys = []
                    candidate_existing_tickets = [
                        ticket
                        for ticket in (prefetch_result.get("tickets") if isinstance(prefetch_result.get("tickets"), list) else [])
                        if isinstance(ticket, dict)
                    ]
                    async def create_requested_issues(
                        summaries: list[str],
                        *,
                        parent_issue_key: str = "",
                        parent_issue_context: dict[str, Any] | None = None,
                        issue_type_candidates: list[str],
                        allow_duplicate_reuse: bool,
                        attachment_paths_for_create: list[Path] | None,
                    ) -> list[str]:
                        resolved_keys: list[str] = []
                        issue_parent_context = parent_issue_context or {}
                        for summary in summaries:
                            generated_content = await self.content_agent.generate_create_ticket_content(
                                user_message=create_user_message,
                                requested_summary=summary,
                                project_key=project_key or "",
                                parent_key=parent_issue_key,
                                parent_summary=str(issue_parent_context.get("summary") or ""),
                                parent_description=str(issue_parent_context.get("description") or ""),
                                workspace_context=workspace_context,
                                agent_prompt=agent_prompt,
                            )
                            generated_summary = str(generated_content.get("summary") or "").strip() or summary
                            description = str(generated_content.get("description") or "").strip()
                            duplicate_ticket = None
                            if allow_duplicate_reuse:
                                duplicate_ticket = self._find_duplicate_ticket_for_create(
                                    generated_summary,
                                    candidate_existing_tickets,
                                    user_message=user_message,
                                )
                            if duplicate_ticket:
                                matched_key = str(duplicate_ticket.get("key") or "").strip().upper()
                                if matched_key:
                                    reused_issue_keys.append(matched_key)
                                    resolved_keys.append(matched_key)
                                    operations.append(
                                        {
                                            "issue_key": matched_key,
                                            "operation": "create",
                                            "status": "skipped",
                                            "detail": (
                                                "Skipped creating a duplicate because a similar open ticket already exists: "
                                                f"{matched_key}."
                                            ),
                                        }
                                    )
                                    warnings.append(
                                        f"Reused existing open Jira ticket {matched_key} for similar request `{generated_summary}`."
                                    )
                                    if all(
                                        str(item.get("key") or "").strip().upper() != matched_key
                                        for item in tickets
                                        if isinstance(item, dict)
                                    ):
                                        tickets.append(duplicate_ticket)
                                    continue
                            created = False
                            last_issue_type_error = ""
                            for issue_type_name in issue_type_candidates:
                                try:
                                    created_key = await self._create_issue(
                                        client,
                                        project_key=project_key,
                                        summary=generated_summary,
                                        description_markdown=description,
                                        issue_type=issue_type_name,
                                        priority_name=priority_name,
                                        parent_key=parent_issue_key,
                                    )
                                except Exception as exc:
                                    detail = str(exc).strip() or type(exc).__name__
                                    if self._is_issue_type_validation_error(detail):
                                        last_issue_type_error = detail
                                        continue
                                    failed_issue_keys.append(f"create:{summary}")
                                    operations.append(
                                        {
                                            "issue_key": "",
                                            "operation": "create",
                                            "status": "failed",
                                            "detail": f"{generated_summary}: {detail}",
                                        }
                                    )
                                    break

                                created = True
                                created_issue_keys.append(created_key)
                                updated_issue_keys.append(created_key)
                                resolved_keys.append(created_key)
                                operations.append(
                                    {
                                        "issue_key": created_key,
                                        "operation": "create",
                                        "status": "success",
                                        "detail": f"Created from summary: {generated_summary} (type: {issue_type_name})",
                                    }
                                )
                                if attachment_paths_for_create:
                                    try:
                                        uploaded_count = await self._add_attachments_to_issue(
                                            client,
                                            created_key,
                                            attachment_paths_for_create,
                                        )
                                        operations.append(
                                            {
                                                "issue_key": created_key,
                                                "operation": "attach",
                                                "status": "success",
                                                "uploaded_count": uploaded_count,
                                                "detail": f"Uploaded {uploaded_count} attachment(s).",
                                            }
                                        )
                                    except Exception as exc:
                                        operations.append(
                                            {
                                                "issue_key": created_key,
                                                "operation": "attach",
                                                "status": "failed",
                                                "detail": str(exc).strip() or type(exc).__name__,
                                            }
                                        )
                                ticket = await self._get_issue(
                                    client,
                                    created_key,
                                    backlog_url,
                                    include_activity=True,
                                )
                                tickets.append(ticket)
                                candidate_existing_tickets.append(ticket)
                                break

                            if not created and last_issue_type_error:
                                failed_issue_keys.append(f"create:{summary}")
                                operations.append(
                                    {
                                        "issue_key": "",
                                        "operation": "create",
                                        "status": "failed",
                                        "detail": (
                                            f"{summary}: issue type was rejected for all candidates "
                                            f"({', '.join(issue_type_candidates)}). Last error: {last_issue_type_error}"
                                        ),
                                    }
                                )
                        return resolved_keys

                    issue_type_candidates = self._resolve_create_issue_type_candidates(create_is_subtask)
                    resolved_parent_keys = await create_requested_issues(
                        create_summaries,
                        parent_issue_key=parent_key,
                        parent_issue_context=parent_context,
                        issue_type_candidates=issue_type_candidates,
                        allow_duplicate_reuse=not create_is_subtask,
                        attachment_paths_for_create=attachment_paths,
                    )

                    if create_parent_with_subtasks:
                        parent_issue_key = resolved_parent_keys[0] if resolved_parent_keys else ""
                        parent_ticket = next(
                            (
                                ticket
                                for ticket in tickets
                                if isinstance(ticket, dict)
                                and str(ticket.get("key") or "").strip().upper() == parent_issue_key
                            ),
                            {},
                        )
                        if not parent_issue_key:
                            raise RuntimeError("Jira create failed. No parent ticket was created for subtask planning.")
                        try:
                            subtask_summaries = await self.content_agent.generate_subtask_summaries(
                                user_message=user_message,
                                parent_summary=str(parent_ticket.get("summary") or requested_summary),
                                parent_description=str(parent_ticket.get("description") or ""),
                            )
                        except Exception as exc:
                            warnings.append(
                                f"Created parent ticket {parent_issue_key}, but subtask planning failed: "
                                f"{str(exc).strip() or type(exc).__name__}."
                            )
                            subtask_summaries = []
                        subtask_summaries = [item.strip() for item in subtask_summaries if item.strip()][:8]
                        if subtask_summaries:
                            await create_requested_issues(
                                subtask_summaries,
                                parent_issue_key=parent_issue_key,
                                parent_issue_context=parent_ticket if isinstance(parent_ticket, dict) else {},
                                issue_type_candidates=self._resolve_create_issue_type_candidates(True),
                                allow_duplicate_reuse=False,
                                attachment_paths_for_create=[],
                            )
                        else:
                            warnings.append(
                                f"Created parent ticket {parent_issue_key}, but no subtask titles were generated."
                            )

                    issue_keys = self._normalize_issue_keys(created_issue_keys + reused_issue_keys)
                    requested_issue_keys = []
                    if not created_issue_keys and not reused_issue_keys:
                        raise RuntimeError("Jira create failed. No tickets were created.")
                elif action == "edit" and self._is_comment_request(user_message):
                    target_keys, subtask_keys, target_warnings = await self._ensure_action_target_keys(
                        client,
                        user_message=user_message,
                        requested_issue_keys=issue_keys,
                        action="comment",
                        project_key=project_key,
                        backlog_url=backlog_url,
                        max_results=max_results,
                    )
                    warnings.extend(target_warnings)
                    ticket_context_by_key = await self._fetch_tickets_by_keys(
                        client,
                        target_keys,
                        backlog_url,
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
                    for target_key in target_keys:
                        try:
                            ticket_context = ticket_context_by_key.get(target_key, {})
                            if not re.search(r"\bcomment\b\s*(?:on|for)?\s*[:\-]\s*", user_message, re.IGNORECASE):
                                comment_body = await self.content_agent.generate_ticket_comment(
                                    user_message=user_message,
                                    issue_key=target_key,
                                    issue_summary=str(ticket_context.get("summary") or ""),
                                    issue_description=str(ticket_context.get("description") or ""),
                                    comments=(
                                        ticket_context.get("comments")
                                        if isinstance(ticket_context.get("comments"), list)
                                        else []
                                    ),
                                )
                            await self._add_comment_to_issue(client, target_key, comment_body)
                            updated_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "comment",
                                    "status": "success",
                                    "detail": "Comment added.",
                                }
                            )
                        except Exception as exc:
                            failed_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "comment",
                                    "status": "failed",
                                    "detail": str(exc).strip() or type(exc).__name__,
                                }
                            )
                    if skipped_parent_keys:
                        warnings.append(
                            "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                        )
                    issue_keys = updated_issue_keys
                    requested_issue_keys = target_keys
                    if not updated_issue_keys:
                        raise RuntimeError("Jira comment update failed. No comments were added.")
                elif action == "edit" and self._is_transition_request(user_message):
                    transition_target = self._extract_transition_target(user_message)
                    if not transition_target:
                        raise RuntimeError("No target Jira status was parsed from the request.")
                    target_keys, subtask_keys, target_warnings = await self._ensure_action_target_keys(
                        client,
                        user_message=user_message,
                        requested_issue_keys=issue_keys,
                        action="transition",
                        project_key=project_key,
                        backlog_url=backlog_url,
                        max_results=max_results,
                    )
                    warnings.extend(target_warnings)
                    ticket_context_by_key = await self._fetch_tickets_by_keys(
                        client,
                        target_keys,
                        backlog_url,
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

                    kanban_columns: list[dict[str, Any]] = []
                    if board_id:
                        try:
                            board_result = await self.fetch_kanban_board_columns(
                                board_id=board_id,
                                backlog_url=backlog_url,
                                tickets=list(ticket_context_by_key.values()),
                            )
                            kanban_columns = (
                                board_result.get("kanban_columns")
                                if isinstance(board_result.get("kanban_columns"), list)
                                else []
                            )
                        except Exception:
                            kanban_columns = []

                    for target_key in target_keys:
                        try:
                            transition_result = await self.transition_issue_to_status(
                                issue_key=target_key,
                                target_status_name=transition_target,
                            )
                            updated_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "transition",
                                    "status": "success",
                                    "detail": f"Moved to {transition_result.get('to_status_name') or transition_target}.",
                                }
                            )
                        except Exception as exc:
                            if kanban_columns:
                                try:
                                    fallback_transition = await self.transition_issue_to_board_column(
                                        issue_key=target_key,
                                        column_name=transition_target,
                                        kanban_columns=kanban_columns,
                                    )
                                    updated_issue_keys.append(target_key)
                                    operations.append(
                                        {
                                            "issue_key": target_key,
                                            "operation": "transition",
                                            "status": "success",
                                            "detail": (
                                                f"Moved to {fallback_transition.get('column_name') or transition_target}."
                                            ),
                                        }
                                    )
                                    continue
                                except Exception:
                                    pass
                            failed_issue_keys.append(target_key)
                            operations.append(
                                {
                                    "issue_key": target_key,
                                    "operation": "transition",
                                    "status": "failed",
                                    "detail": str(exc).strip() or type(exc).__name__,
                                }
                            )
                    if skipped_parent_keys:
                        warnings.append(
                            "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                        )
                    issue_keys = updated_issue_keys
                    requested_issue_keys = target_keys
                    if not updated_issue_keys:
                        raise RuntimeError("Jira transition failed. No issues were transitioned.")
                elif action == "edit":
                    target_keys, subtask_keys, target_warnings = await self._ensure_action_target_keys(
                        client,
                        user_message=user_message,
                        requested_issue_keys=issue_keys,
                        action="edit",
                        project_key=project_key,
                        backlog_url=backlog_url,
                        max_results=max_results,
                    )
                    warnings.extend(target_warnings)
                    requested_updates = self._extract_edit_field_updates(user_message)
                    rewrite_ticket_content = self._is_ticket_rewrite_request(user_message)
                    should_update_description = (
                        self._is_description_update_request(user_message)
                        and "description" not in requested_updates
                        and not DESCRIPTION_CLEAR_RE.search(user_message)
                    )
                    if not requested_updates and not should_update_description and not DESCRIPTION_CLEAR_RE.search(user_message):
                        raise RuntimeError(
                            "No supported Jira field updates found. Use syntax like `summary to ...`, `priority to ...`, `assignee to ...`, or `labels: ...`."
                        )

                    ticket_context_by_key = await self._fetch_tickets_by_keys(
                        client,
                        target_keys,
                        backlog_url,
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
                    parent_keys = [
                        str(ticket_context_by_key.get(key, {}).get("parent_key") or "").strip().upper()
                        for key in target_keys
                    ]
                    parent_context_by_key = await self._fetch_tickets_by_keys(
                        client,
                        [key for key in parent_keys if key],
                        backlog_url,
                        max_results,
                    )

                    for issue_key in target_keys:
                        try:
                            ticket_context = ticket_context_by_key.get(issue_key, {})
                            if not requested_summary_for_state:
                                requested_summary_for_state = str(ticket_context.get("summary") or issue_key)
                            parent_key = str(ticket_context.get("parent_key") or "").strip().upper()
                            parent_context = parent_context_by_key.get(parent_key, {}) if parent_key else {}
                            workspace_context = self._build_workspace_context(
                                workspace_root,
                                requested_summary=str(ticket_context.get("summary") or issue_key),
                                user_message=user_message,
                            )
                            relevant_files = self._find_relevant_workspace_files(
                                workspace_root,
                                requested_summary=str(ticket_context.get("summary") or issue_key),
                                user_message=user_message,
                            )
                            if not relevant_files_for_state:
                                relevant_files_for_state = list(relevant_files)
                            agent_prompt = self._build_agent_prompt(
                                requested_summary=str(ticket_context.get("summary") or issue_key),
                                user_message=user_message,
                                relevant_files=relevant_files,
                                attachment_paths=attachment_paths,
                            )
                            generated_description: str | None = None
                            generated_summary: str | None = None
                            if should_update_description:
                                generated_content = await self.content_agent.generate_edit_ticket_content(
                                    user_message=user_message,
                                    issue_key=issue_key,
                                    existing_summary=str(ticket_context.get("summary") or ""),
                                    existing_description=str(ticket_context.get("description") or ""),
                                    parent_key=parent_key,
                                    parent_summary=str(parent_context.get("summary") or ""),
                                    parent_description=str(parent_context.get("description") or ""),
                                    workspace_context=workspace_context,
                                    agent_prompt=agent_prompt,
                                )
                                generated_summary = str(generated_content.get("summary") or "").strip() or None
                                generated_description = str(generated_content.get("description") or "").strip()

                            payload_fields, extra_actions = await self._prepare_edit_fields(
                                client,
                                issue_context=ticket_context,
                                requested_updates=requested_updates,
                                user_message=user_message,
                            )
                            if generated_description is not None:
                                payload_fields["description"] = generated_description
                            if rewrite_ticket_content and generated_summary and "summary" not in payload_fields:
                                payload_fields["summary"] = generated_summary

                            if not payload_fields and not extra_actions:
                                raise RuntimeError("No editable Jira fields were derived from the request.")

                            if payload_fields:
                                await self._edit_issue(client, issue_key, payload_fields)
                                operations.append(
                                    {
                                        "issue_key": issue_key,
                                        "operation": "edit",
                                        "status": "success",
                                        "detail": "Ticket fields updated.",
                                    }
                                )
                            sprint_value = extra_actions.get("sprint")
                            if sprint_value is not None:
                                sprint_id = await self._resolve_sprint_id(client, board_id, sprint_value)
                                await self._move_issues_to_sprint(client, sprint_id, [issue_key])
                                operations.append(
                                    {
                                        "issue_key": issue_key,
                                        "operation": "sprint",
                                        "status": "success",
                                        "detail": f"Moved to sprint {sprint_value}.",
                                    }
                                )

                            updated_issue_keys.append(issue_key)
                            with_issue = await self._get_issue(
                                client,
                                issue_key,
                                backlog_url,
                                include_activity=True,
                            )
                            tickets.append(with_issue)
                        except Exception as exc:
                            failed_issue_keys.append(issue_key)
                            operations.append(
                                {
                                    "issue_key": issue_key,
                                    "operation": "edit",
                                    "status": "failed",
                                    "detail": str(exc).strip() or type(exc).__name__,
                                }
                            )
                    if skipped_parent_keys:
                        warnings.append(
                            "Skipped parent/top-level ticket(s): " + ", ".join(self._normalize_issue_keys(skipped_parent_keys))
                        )
                    issue_keys = updated_issue_keys
                    requested_issue_keys = target_keys
                    if not updated_issue_keys:
                        raise RuntimeError("Edit operation failed for all requested issue keys.")
                elif action == "attach":
                    if not issue_keys:
                        raise RuntimeError("No Jira issue key detected for attachment request.")
                    attachment_paths = self._extract_attachment_paths(user_message)
                    if not attachment_paths:
                        raise RuntimeError(
                            "No uploaded attachment files were found in this request. Attach file(s) in chat and retry."
                        )
                    for issue_key in issue_keys:
                        try:
                            uploaded_count = await self._add_attachments_to_issue(client, issue_key, attachment_paths)
                            updated_issue_keys.append(issue_key)
                            operations.append(
                                {
                                    "issue_key": issue_key,
                                    "operation": "attach",
                                    "status": "success",
                                    "uploaded_count": uploaded_count,
                                }
                            )
                        except Exception as exc:
                            failed_issue_keys.append(issue_key)
                            operations.append(
                                {
                                    "issue_key": issue_key,
                                    "operation": "attach",
                                    "status": "failed",
                                    "detail": str(exc).strip() or type(exc).__name__,
                                }
                            )
                    if updated_issue_keys:
                        for issue_key in updated_issue_keys:
                            with_issue = await self._get_issue(client, issue_key, backlog_url, include_activity=True)
                            tickets.append(with_issue)
                    if not updated_issue_keys:
                        raise RuntimeError("Attachment operation failed for all requested issue keys.")
                elif action == "delete":
                    if not issue_keys:
                        raise RuntimeError("No Jira issue key detected for delete request.")
                    for issue_key in issue_keys:
                        try:
                            await self._delete_issue(client, issue_key)
                            updated_issue_keys.append(issue_key)
                            operations.append(
                                {
                                    "issue_key": issue_key,
                                    "operation": "delete",
                                    "status": "success",
                                    "detail": "Ticket deleted.",
                                }
                            )
                        except Exception as exc:
                            failed_issue_keys.append(issue_key)
                            operations.append(
                                {
                                    "issue_key": issue_key,
                                    "operation": "delete",
                                    "status": "failed",
                                    "detail": str(exc).strip() or type(exc).__name__,
                                }
                            )
                    issue_keys = updated_issue_keys
                    requested_issue_keys = self._normalize_issue_keys(requested_issue_keys)
                    if not updated_issue_keys:
                        raise RuntimeError("Delete operation failed for all requested issue keys.")
                else:
                    raise RuntimeError(f"Unsupported Jira action '{action}'.")

            operation_summary = self._summarize_operations(operations)
            raw_result_json = json.dumps(
                {
                    "mode": "jira_rest_handle_request",
                    "action": action,
                    "issue_keys": issue_keys,
                    "created_issue_keys": created_issue_keys if action == "create" else [],
                    "reused_issue_keys": reused_issue_keys if action == "create" else [],
                    "requested_issue_keys": requested_issue_keys,
                    "updated_issue_keys": updated_issue_keys,
                    "failed_issue_keys": failed_issue_keys,
                    "ticket_count": len(tickets),
                    "operations": operations,
                },
                indent=2,
                ensure_ascii=False,
            )
            raw_result_path = _persist_raw_result(workspace_root, raw_result_json)
            attachments_uploaded_count = sum(
                int(item.get("uploaded_count") or 0)
                for item in operations
                if isinstance(item, dict) and str(item.get("operation") or "") == "attach"
            )

            next_ticket_keys_source = list(created_issue_keys) + list(reused_issue_keys)
            if action != "delete":
                next_ticket_keys_source.extend(list(updated_issue_keys) + list(issue_keys))
            next_ticket_keys = self._normalize_issue_keys(next_ticket_keys_source)
            if action == "create":
                last_create_request = str(create_summary_source if "create_summary_source" in locals() else user_message).strip()
                if last_create_request and not self._looks_like_generated_ticket_content(last_create_request):
                    conversation_state.last_intended_jira_create_request = last_create_request
            attachment_refs = [
                {"name": path.name, "path": str(path)}
                for path in attachment_paths
                if isinstance(path, Path)
            ]
            if attachment_refs:
                conversation_state.last_referenced_attachments = attachment_refs
            conversation_state.last_ticket_keys = next_ticket_keys
            conversation_state.requested_operation_mode = self._operation_mode_for_state(user_message, action)
            conversation_state.project_key = str(project_key or "").strip().upper()
            conversation_state.board_id = str(board_id or "").strip()
            conversation_state.backlog_url = backlog_url
            conversation_state.workspace_root = str(workspace_root)
            conversation_state.pending_clarification_action = ""
            conversation_state.pending_clarification_question = ""
            if relevant_files_for_state:
                conversation_state.relevant_files = list(relevant_files_for_state)
            if requested_summary_for_state:
                conversation_state.normalized_implementation_brief_summary = requested_summary_for_state.strip()
            state_path = save_jira_conversation_state(workspace_root, conversation_id, conversation_state)
            if state_path:
                warnings.append(f"Saved Jira conversation state to {state_path}.")

            return {
                "action": action,
                "agent": CONFIG.name,
                "workspace_root": str(workspace_root),
                "backlog_url": backlog_url,
                "project_key": project_key,
                "board_id": board_id,
                "server": "jira_rest_api",
                "tool": "rest_api_request_router",
                "available_tools": [
                    "/rest/api/3/search/jql",
                    "/rest/api/3/issue",
                    "/rest/api/3/issue/{key}",
                    "/rest/api/3/issue/{key}/comment",
                    "/rest/api/3/issue/{key} (DELETE)",
                    "/rest/api/3/issue/{key}/transitions",
                    "/rest/api/3/user/search",
                    "/rest/agile/1.0/sprint/{id}/issue",
                ],
                "arguments": {"message": user_message[:500]},
                "ticket_count": len(tickets),
                "tickets": tickets,
                "issue_key": issue_keys[0] if issue_keys else "",
                "issue_keys": issue_keys,
                "created_issue_keys": created_issue_keys if action == "create" else [],
                "reused_issue_keys": reused_issue_keys if action == "create" else [],
                "requested_issue_keys": requested_issue_keys,
                "updated_issue_keys": updated_issue_keys,
                "failed_issue_keys": failed_issue_keys,
                "attachments_uploaded_count": attachments_uploaded_count,
                "operations": operations,
                "operation_summary": operation_summary,
                "result_text_preview": "",
                "warnings": warnings,
                "raw_result_json": raw_result_json,
                "raw_result_path": raw_result_path,
                "conversation_state_path": str(state_path) if 'state_path' in locals() and state_path else "",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def _fetch_active_sprint(
        self,
        client: httpx.AsyncClient,
        *,
        board_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        payload = await self._request_json(
            client,
            "GET",
            f"/rest/agile/1.0/board/{board_id}/sprint",
            params={"state": "active", "maxResults": 50},
        )
        values = payload.get("values") if isinstance(payload.get("values"), list) else []
        active = next(
            (
                item
                for item in values
                if isinstance(item, dict) and str(item.get("state") or "").strip().lower() in {"active", "open"}
            ),
            None,
        )
        return active, payload

    async def _fetch_kanban_board_columns_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        board_id: str,
        tickets: list[dict[str, Any]],
        sprint_tickets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = await self._request_json(
            client,
            "GET",
            f"/rest/agile/1.0/board/{board_id}/configuration",
        )
        column_config = payload.get("columnConfig") if isinstance(payload, dict) else {}
        raw_columns = column_config.get("columns") if isinstance(column_config, dict) else []
        columns = raw_columns if isinstance(raw_columns, list) else []
        if not columns:
            raise RuntimeError("Jira board configuration returned no columns.")

        ticket_union = _dedupe_tickets_by_key(tickets, sprint_tickets)
        kanban_columns = self._build_column_payload(columns, ticket_union)
        return {
            "board_id": board_id,
            "board_name": _stringify(payload.get("name")),
            "board_url": _stringify(payload.get("self")),
            "kanban_columns": kanban_columns,
            "raw_board_config": payload,
        }

    async def fetch_kanban_board_columns(
        self,
        *,
        board_id: str | None,
        backlog_url: str | None = None,
        tickets: list[dict[str, Any]] | None = None,
        sprint_tickets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            self._validate_env()
            resolved_board_id = self._resolve_board_id(board_id, backlog_url)
            timeout = httpx.Timeout(15.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                result = await self._fetch_kanban_board_columns_with_client(
                    client,
                    board_id=resolved_board_id,
                    tickets=tickets if isinstance(tickets, list) else [],
                    sprint_tickets=sprint_tickets if isinstance(sprint_tickets, list) else [],
                )
            result["fetched_at"] = datetime.now(timezone.utc).isoformat()
            return result
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def get_issue_transitions(self, issue_key: str) -> list[dict[str, str]]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            self._validate_env()
            normalized_key = str(issue_key or "").strip().upper()
            if not normalized_key:
                raise RuntimeError("Issue key is required to fetch transitions.")

            timeout = httpx.Timeout(15.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                payload = await self._request_json(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{normalized_key}/transitions",
                )

            transitions_raw = payload.get("transitions") if isinstance(payload.get("transitions"), list) else []
            transitions: list[dict[str, str]] = []
            for item in transitions_raw:
                if not isinstance(item, dict):
                    continue
                to_field = item.get("to") if isinstance(item.get("to"), dict) else {}
                transitions.append(
                    {
                        "id": _stringify(item.get("id")),
                        "name": _stringify(item.get("name")),
                        "to_name": _stringify(to_field.get("name")),
                        "to_id": _stringify(to_field.get("id")),
                    }
                )
            return [item for item in transitions if item.get("id")]
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    @staticmethod
    def _pick_transition_by_status(
        transitions: list[dict[str, str]],
        *,
        status_names: list[str] | None = None,
        status_ids: list[str] | None = None,
    ) -> dict[str, str] | None:
        candidate_ids = {str(item or "").strip() for item in (status_ids or []) if str(item or "").strip()}
        candidate_names = {
            _normalize_transition_target(str(item or ""))
            for item in (status_names or [])
            if _normalize_transition_target(str(item or ""))
        }
        if not candidate_ids and not candidate_names:
            return None

        for transition in transitions:
            if not isinstance(transition, dict):
                continue
            to_id = str(transition.get("to_id") or "").strip()
            to_name = _normalize_transition_target(str(transition.get("to_name") or ""))
            if to_id and to_id in candidate_ids:
                return transition
            if to_name and to_name in candidate_names:
                return transition
        return None

    async def transition_issue_to_status(
        self,
        *,
        issue_key: str,
        target_status_name: str | None = None,
        target_status_id: str | None = None,
    ) -> dict[str, Any]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            self._validate_env()
            normalized_key = str(issue_key or "").strip().upper()
            if not normalized_key:
                raise RuntimeError("Issue key is required to transition Jira issue.")
            if not str(target_status_name or "").strip() and not str(target_status_id or "").strip():
                raise RuntimeError("Target Jira status is required.")

            timeout = httpx.Timeout(15.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                payload = await self._request_json(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{normalized_key}/transitions",
                )
                transitions_raw = payload.get("transitions") if isinstance(payload.get("transitions"), list) else []
                transitions: list[dict[str, str]] = []
                for item in transitions_raw:
                    if not isinstance(item, dict):
                        continue
                    to_field = item.get("to") if isinstance(item.get("to"), dict) else {}
                    transitions.append(
                        {
                            "id": _stringify(item.get("id")),
                            "name": _stringify(item.get("name")),
                            "to_name": _stringify(to_field.get("name")),
                            "to_id": _stringify(to_field.get("id")),
                        }
                    )
                chosen = self._pick_transition_by_status(
                    transitions,
                    status_names=[str(target_status_name or "")],
                    status_ids=[str(target_status_id or "")],
                )
                if not chosen:
                    available = ", ".join(
                        f"{item.get('to_name') or item.get('name') or item.get('id')}"
                        for item in transitions[:12]
                        if isinstance(item, dict)
                    )
                    raise RuntimeError(
                        f"Requested Jira status '{target_status_name or target_status_id}' not available for {normalized_key}."
                        + (f" Available: {available}" if available else "")
                    )

                response = await client.post(
                    f"{self._base_url()}/rest/api/3/issue/{normalized_key}/transitions",
                    auth=self._auth(),
                    headers=self._headers(),
                    json={"transition": {"id": str(chosen.get("id") or "")}},
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = response.text[:500]
                    raise RuntimeError(
                        f"Jira REST transition failed for {normalized_key} ({response.status_code})"
                        + (f": {detail}" if detail else "")
                    ) from exc

            return {
                "issue_key": normalized_key,
                "transition_id": str(chosen.get("id") or ""),
                "transition_name": str(chosen.get("name") or ""),
                "to_status_name": str(chosen.get("to_name") or target_status_name or ""),
                "to_status_id": str(chosen.get("to_id") or target_status_id or ""),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            error_text = str(exc).strip() or type(exc).__name__
            raise
        finally:
            if error_text:
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def transition_issue_to_board_column(
        self,
        *,
        issue_key: str,
        column_name: str,
        kanban_columns: list[dict[str, Any]] | list[Any],
    ) -> dict[str, Any]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        target_column_name = str(column_name or "").strip()
        if not normalized_issue_key:
            raise RuntimeError("Issue key is required.")
        if not target_column_name:
            raise RuntimeError("Jira board column name is required.")

        column = _pick_column_by_name(kanban_columns, target_column_name)
        if not column:
            available = ", ".join(
                str(item.get("name") or "").strip()
                for item in kanban_columns
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            )
            raise RuntimeError(
                f"Jira board column '{target_column_name}' not found."
                + (f" Available: {available}" if available else "")
            )

        statuses = column.get("statuses") if isinstance(column.get("statuses"), list) else []
        candidate_status_names = [
            str(item.get("name") or "").strip()
            for item in statuses
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        candidate_status_ids = [
            str(item.get("id") or "").strip()
            for item in statuses
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        if not candidate_status_names and not candidate_status_ids:
            raise RuntimeError(f"Jira board column '{target_column_name}' has no mapped statuses.")

        timeout = httpx.Timeout(15.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = await self._request_json(
                client,
                "GET",
                f"/rest/api/3/issue/{normalized_issue_key}/transitions",
            )
            transitions_raw = payload.get("transitions") if isinstance(payload.get("transitions"), list) else []
            transitions: list[dict[str, str]] = []
            for item in transitions_raw:
                if not isinstance(item, dict):
                    continue
                to_field = item.get("to") if isinstance(item.get("to"), dict) else {}
                transitions.append(
                    {
                        "id": _stringify(item.get("id")),
                        "name": _stringify(item.get("name")),
                        "to_name": _stringify(to_field.get("name")),
                        "to_id": _stringify(to_field.get("id")),
                    }
                )

            chosen = self._pick_transition_by_status(
                transitions,
                status_names=candidate_status_names,
                status_ids=candidate_status_ids,
            )
            if not chosen:
                available = ", ".join(
                    f"{item.get('to_name') or item.get('name') or item.get('id')}"
                    for item in transitions[:12]
                    if isinstance(item, dict)
                )
                mapped = ", ".join(candidate_status_names or candidate_status_ids)
                raise RuntimeError(
                    f"No available Jira transition from {normalized_issue_key} to board column '{target_column_name}'"
                    f" (mapped statuses: {mapped})."
                    + (f" Available transitions: {available}" if available else "")
                )

            response = await client.post(
                f"{self._base_url()}/rest/api/3/issue/{normalized_issue_key}/transitions",
                auth=self._auth(),
                headers=self._headers(),
                json={"transition": {"id": str(chosen.get('id') or '')}},
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Jira REST transition failed for {normalized_issue_key} ({response.status_code})"
                    + (f": {detail}" if detail else "")
                ) from exc

        return {
            "issue_key": normalized_issue_key,
            "column_name": str(column.get("name") or target_column_name),
            "transition_id": str(chosen.get("id") or ""),
            "transition_name": str(chosen.get("name") or ""),
            "to_status_name": str(chosen.get("to_name") or ""),
            "to_status_id": str(chosen.get("to_id") or ""),
            "mapped_statuses": [
                {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
                for item in statuses
                if isinstance(item, dict)
            ],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    async def fetch_backlog_tickets(
        self,
        workspace_root: Path,
        backlog_url_override: str | None = None,
    ) -> dict[str, Any]:
        mark_agent_start(self.agent_id)
        error_text: str | None = None
        try:
            self._validate_env()

            config = load_mcp_config(workspace_root)
            tooling = config.tooling.get("jira") if config and config.tooling else {}
            jira_tooling = tooling if isinstance(tooling, dict) else {}

            backlog_url = (
                str(backlog_url_override or "").strip()
                or str(jira_tooling.get("backlog_url") or "").strip()
                or DEFAULT_BACKLOG_URL
            )
            project_key = str(jira_tooling.get("project_key") or "").strip().upper() or None
            board_id = str(jira_tooling.get("board_id") or "").strip() or None
            parsed_project, parsed_board = _parse_backlog_url(backlog_url)
            project_key = project_key or parsed_project

            board_id = board_id or parsed_board

            # Fall back to DB-stored config (set via the Workflow Tasks UI)
            if not project_key or not board_id:
                stored = get_jira_settings()
                project_key = project_key or str(stored.get("project_key") or "").strip().upper() or None
                board_id = board_id or str(stored.get("board_id") or "").strip() or None

            try:
                max_results = int(str(jira_tooling.get("max_results") or "100"))
            except Exception:
                max_results = 100
            max_results = max(1, min(max_results, 500))

            if not project_key:
                raise RuntimeError(
                    "No Jira project key configured. "
                    "Set the Project and Board Number in Workflow Tasks and fetch once."
                )

            if not board_id:
                raise RuntimeError(
                    "No Jira board ID configured. "
                    "Set the Project and Board Number in Workflow Tasks and fetch once."
                )

            warnings: list[str] = []
            raw_backlog_pages: list[dict[str, Any]] = []
            raw_sprint_pages: list[dict[str, Any]] = []
            raw_active_sprints: dict[str, Any] = {}
            current_sprint: dict[str, Any] | None = None
            kanban_columns: list[dict[str, Any]] = []
            kanban_board_name = ""

            timeout = httpx.Timeout(20.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                backlog_jql = f"project = {project_key} AND statusCategory != Done ORDER BY updated DESC"
                tickets, raw_backlog_pages = await self._search_issues_jql(
                    client,
                    jql=backlog_jql,
                    max_results=max_results,
                    fields=list(WORKFLOW_PAGE_FIELDS),
                    backlog_url=backlog_url,
                )

                sprint_tickets: list[dict[str, Any]] = []
                active_sprint_meta: dict[str, Any] | None = None

                sprint_jql = f"project = {project_key} AND sprint in openSprints() ORDER BY updated DESC"
                try:
                    sprint_tickets, raw_sprint_pages = await self._search_issues_jql(
                        client,
                        jql=sprint_jql,
                        max_results=max_results,
                        fields=list(WORKFLOW_PAGE_FIELDS),
                        backlog_url=backlog_url,
                    )
                except Exception as sprint_exc:
                    warnings.append(
                        f"Current sprint ticket fetch failed (Jira REST API): {str(sprint_exc).strip() or type(sprint_exc).__name__}"
                    )

                if board_id:
                    try:
                        active_sprint_meta, raw_active_sprints = await self._fetch_active_sprint(client, board_id=board_id)
                    except Exception as sprint_meta_exc:
                        warnings.append(
                            f"Current sprint metadata fetch failed (Jira REST API): {str(sprint_meta_exc).strip() or type(sprint_meta_exc).__name__}"
                        )
                else:
                    warnings.append("Current sprint metadata fetch skipped: board id unavailable.")

                if active_sprint_meta or sprint_tickets:
                    current_sprint = {
                        "id": _stringify(active_sprint_meta.get("id") if isinstance(active_sprint_meta, dict) else ""),
                        "name": _stringify(active_sprint_meta.get("name") if isinstance(active_sprint_meta, dict) else "")
                        or (_stringify((sprint_tickets[0].get("sprints") or [""])[0]) if sprint_tickets else ""),
                        "state": _stringify(active_sprint_meta.get("state") if isinstance(active_sprint_meta, dict) else ""),
                        "goal": _stringify(active_sprint_meta.get("goal") if isinstance(active_sprint_meta, dict) else ""),
                        "start_date": _stringify(active_sprint_meta.get("startDate") if isinstance(active_sprint_meta, dict) else ""),
                        "end_date": _stringify(active_sprint_meta.get("endDate") if isinstance(active_sprint_meta, dict) else ""),
                        "complete_date": _stringify(active_sprint_meta.get("completeDate") if isinstance(active_sprint_meta, dict) else ""),
                        "board_id": str(board_id or ""),
                        "ticket_count": len([ticket for ticket in sprint_tickets if isinstance(ticket, dict)]),
                        "tickets": [ticket for ticket in sprint_tickets if isinstance(ticket, dict)],
                        "counts_by_status": _build_ticket_count_rows(sprint_tickets, "status"),
                    }

                if board_id:
                    try:
                        board_result = await self._fetch_kanban_board_columns_with_client(
                            client,
                            board_id=board_id,
                            tickets=[ticket for ticket in tickets if isinstance(ticket, dict)],
                            sprint_tickets=[ticket for ticket in sprint_tickets if isinstance(ticket, dict)],
                        )
                        kanban_columns = (
                            board_result.get("kanban_columns")
                            if isinstance(board_result.get("kanban_columns"), list)
                            else []
                        )
                        kanban_board_name = _stringify(board_result.get("board_name"))
                    except Exception as board_exc:
                        warnings.append(
                            f"Kanban board configuration fetch failed (Jira REST API): {str(board_exc).strip() or type(board_exc).__name__}"
                        )
                else:
                    warnings.append("Kanban board configuration fetch skipped: board id unavailable.")

            raw_result_json = json.dumps(
                {
                    "mode": "jira_rest_workflow_fetch",
                    "backlog_url": backlog_url,
                    "project_key": project_key,
                    "board_id": board_id,
                    "ticket_count": len(tickets),
                    "current_sprint_ticket_count": (
                        int(current_sprint.get("ticket_count") or 0) if isinstance(current_sprint, dict) else 0
                    ),
                    "kanban_column_count": len(kanban_columns),
                    "raw_backlog_pages": raw_backlog_pages,
                    "raw_sprint_pages": raw_sprint_pages,
                    "raw_active_sprints": raw_active_sprints,
                },
                indent=2,
                ensure_ascii=False,
            )
            raw_result_path = _persist_raw_result(workspace_root, raw_result_json)

            return {
                "action": "list",
                "agent": CONFIG.name,
                "workspace_root": str(workspace_root),
                "backlog_url": backlog_url,
                "project_key": project_key,
                "board_id": board_id,
                "server": "jira_rest_api",
                "tool": "rest_api_search",
                "available_tools": ["/rest/api/3/search", "/rest/agile/1.0/board/{id}/configuration"],
                "arguments": {
                    "backlog_jql": backlog_jql,
                    "sprint_jql": sprint_jql,
                    "max_results": max_results,
                    "fields": list(WORKFLOW_PAGE_FIELDS),
                },
                "ticket_count": len(tickets),
                "tickets": [ticket for ticket in tickets if isinstance(ticket, dict)],
                "current_sprint": current_sprint,
                "kanban_columns": kanban_columns,
                "kanban_board_name": kanban_board_name,
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
                mark_agent_end(self.agent_id, error_text)
            else:
                mark_agent_end(self.agent_id)

    async def get_assignable_users(self, project_key: str | None = None) -> list[dict[str, Any]]:
        self._validate_env()
        async with httpx.AsyncClient(timeout=30) as client:
            if project_key:
                response = await client.get(
                    f"{self._base_url()}/rest/api/3/user/assignable/search",
                    auth=self._auth(),
                    headers=self._headers(),
                    params={"project": project_key.strip().upper(), "maxResults": 100},
                )
            else:
                response = await client.get(
                    f"{self._base_url()}/rest/api/3/users/search",
                    auth=self._auth(),
                    headers=self._headers(),
                    params={"maxResults": 100},
                )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Jira user fetch failed ({response.status_code})" + (f": {detail}" if detail else "")
                ) from exc

            payload = response.json()
            return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
