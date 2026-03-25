from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from app.agents_shared import build_worker_agents
from app.agents_code_builder.runtime import build_codex_skills_prompt, run_codex_exec
from app.agents_code_review.runtime import run_code_review_with_codex
from app.agents_sdd_spec.runtime import register_sdd_spec_agent, run_sdd_spec_agent, sdd_spec_agent_enabled
from app.agents_git import GitAgent
from app.agents_git_content import GitContentAgent
from app.agents_jira_api import JiraApiAgent
from app.agents_slack import SlackAgent
from app.assist_brain_memory import capture_assist_brain, search_assist_brain
from app.db import (
    SPEC_TASK_STATUS_COMPLETE,
    SPEC_TASK_STATUS_FAILED,
    SPEC_TASK_STATUS_PENDING,
    list_jira_fetches,
    list_spec_tasks,
    set_spec_task_status,
)
from app.git_workflow_runtime import ACTIVE_WORKSPACE_BRANCH_VALUE, run_configured_git_action
from app.mcp_client import load_mcp_config
from app.settings_store import get_agent_bypass_settings, get_agent_model, get_git_workflow_settings
from app.ticket_context import TicketContext
from app.workspace import CODE_BUILDER_WORKSPACE_RULES, ensure_workspace_bootstrap
from app.pipeline_store import (
    DEFAULT_REVIEW_FAILURE_MODE,
    DEFAULT_ACTIVE_WINDOW_END,
    DEFAULT_ACTIVE_WINDOW_START,
    DEFAULT_HEARTBEAT_INTERVAL_MINUTES,
    MIN_HEARTBEAT_INTERVAL_MINUTES,
    PIPELINE_RUN_STATUS_COMPLETE,
    PIPELINE_RUN_STATUS_FAILED,
    PIPELINE_RUN_STATUS_STOPPED,
    PIPELINE_STATUS_COMPLETE,
    PIPELINE_STATUS_BACKLOG,
    PIPELINE_STATUS_CURRENT,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_RUNNING,
    PIPELINE_STATUS_STOPPED,
    PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED,
    PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
    PIPELINE_TASK_EXECUTION_STATE_READY,
    PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
    PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF,
    PIPELINE_BYPASS_SOURCE_BRANCH_COHORT,
    PIPELINE_BYPASS_SOURCE_DEPENDENCY,
    PIPELINE_BYPASS_SOURCE_MANUAL,
    PIPELINE_WORKFLOW,
    PIPELINE_TASK_SOURCE_JIRA,
    PIPELINE_TASK_SOURCE_SPEC,
    PIPELINE_TASK_RELATION_TASK,
    PIPELINE_TASK_RELATION_SUBTASK,
    PIPELINE_TASK_RELATIONS,
    REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE,
    REVIEW_FAILURE_MODE_SKIP_ALL,
    REVIEW_FAILURE_MODE_STRICT,
    add_pipeline_log,
    create_pipeline_run,
    ensure_pipeline_schema,
    finalize_pipeline_run,
    add_pipeline_git_handoff,
    get_backlog_item,
    get_pipeline_git_handoff,
    get_pipeline_settings,
    get_shared_max_retries,
    get_pipeline_task,
    has_running_pipeline_task,
    has_unresolved_pipeline_git_handoff,
    list_pipeline_git_handoffs,
    list_pipeline_backlog,
    list_pipeline_logs,
    list_pipeline_runs,
    list_dependency_blocked_current_task_ids,
    list_pipeline_task_dependencies,
    list_pipeline_task_dependents,
    list_pipeline_tasks,
    move_pipeline_task,
    pop_next_current_pipeline_task,
    queue_pipeline_task,
    recover_stale_pipeline_state,
    recover_stale_running_task,
    replace_pipeline_task_dependencies,
    resolve_pipeline_git_handoff,
    reorder_current_pipeline_tasks,
    set_pipeline_task_active_run,
    update_pipeline_task_controls,
    set_pipeline_task_result,
    replace_pipeline_backlog,
    reset_pipeline_task_runtime,
    update_pipeline_run_progress,
    update_pipeline_heartbeat,
    update_pipeline_settings,
)

from .config import (
    AUTONOMY_RULE,
    CODEX_TIMEOUT_SECONDS,
    CONFIG,
    PIPELINE_POLL_SECONDS,
)


@dataclass
class WorkerAgent:
    name: str
    provider: str
    system_prompt: str
    model: str | None = None
    max_tokens: int | None = None
    agent_id: str | None = None


def _normalize_issue_key(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_workflow(value: str | None) -> str:
    return PIPELINE_WORKFLOW


def _normalize_task_source(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == PIPELINE_TASK_SOURCE_SPEC:
        return PIPELINE_TASK_SOURCE_SPEC
    return PIPELINE_TASK_SOURCE_JIRA


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _next_heartbeat_due_at(
    *,
    now_local: datetime,
    interval_minutes: int,
    last_heartbeat_at: datetime | None,
    next_override_at: datetime | None,
) -> datetime | None:
    candidates: list[datetime] = []

    if last_heartbeat_at:
        candidates.append(last_heartbeat_at.astimezone(now_local.tzinfo) + timedelta(minutes=interval_minutes))

    if next_override_at:
        candidates.append(next_override_at.astimezone(now_local.tzinfo))

    if not candidates:
        return None

    return min(candidates)


def _normalize_window_time(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        return fallback
    try:
        hour = int(text[:2])
        minute = int(text[3:5])
    except Exception:
        return fallback
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return f"{hour:02d}:{minute:02d}"


def _time_to_minutes(value: str) -> int:
    normalized = _normalize_window_time(value, "00:00")
    return int(normalized[:2]) * 60 + int(normalized[3:5])


def _minutes_to_time(value: int) -> str:
    normalized = int(value) % (24 * 60)
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def _is_within_window(now_local: datetime, start_minutes: int, end_minutes: int) -> bool:
    now_minutes = now_local.hour * 60 + now_local.minute
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= now_minutes < end_minutes
    return now_minutes >= start_minutes or now_minutes < end_minutes


def _next_window_start(now_local: datetime, start_minutes: int, end_minutes: int) -> datetime:
    active = _is_within_window(now_local, start_minutes, end_minutes)
    if active:
        return now_local

    today_start = now_local.replace(
        hour=start_minutes // 60,
        minute=start_minutes % 60,
        second=0,
        microsecond=0,
    )

    if start_minutes < end_minutes:
        if now_local < today_start:
            return today_start
        return today_start + timedelta(days=1)

    now_minutes = now_local.hour * 60 + now_local.minute
    if end_minutes <= now_minutes < start_minutes:
        return today_start
    return today_start + timedelta(days=1)


def _dedupe_lines(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = " ".join(str(item or "").strip().split())
        if not text:
            continue
        normalized = text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text)
    return deduped


_REVIEW_ACCEPTANCE_HINTS = (
    "acceptance criterion",
    "acceptance criteria",
    "ac-",
    "delivery workflow",
    "open a pr",
    "pr against",
    "backend approval",
    "changelog",
    "pr link",
    "jira",
)

_REVIEW_TECHNICAL_HINTS = (
    "traceback",
    "exception",
    "unit test",
    "integration test",
    "test failed",
    "tests failed",
    "failing test",
    "build failed",
    "compile",
    "lint",
    "typecheck",
    "syntax",
    "security",
    "vulnerability",
)


def _normalize_review_failure_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {
        REVIEW_FAILURE_MODE_STRICT,
        REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE,
        REVIEW_FAILURE_MODE_SKIP_ALL,
    }:
        return normalized
    return DEFAULT_REVIEW_FAILURE_MODE


def _classify_review_failure(errors: list[str], summary: str = "") -> str:
    combined = " ".join([*errors, summary]).lower()
    if not combined:
        return "unknown"

    has_acceptance_hint = any(token in combined for token in _REVIEW_ACCEPTANCE_HINTS)
    has_technical_hint = any(token in combined for token in _REVIEW_TECHNICAL_HINTS)
    if has_acceptance_hint and not has_technical_hint:
        return "acceptance"
    if has_technical_hint:
        return "technical"
    return "unknown"


def _should_skip_review_failure(mode: str, category: str) -> bool:
    normalized_mode = _normalize_review_failure_mode(mode)
    if normalized_mode == REVIEW_FAILURE_MODE_SKIP_ALL:
        return True
    if normalized_mode == REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE and category == "acceptance":
        return True
    return False


def _normalize_checklist_line(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^delivery workflow acceptance criteria?[:\s-]*", "", text)
    text = re.sub(r"^ac-\d+[:\s-]*", "", text)
    text = re.sub(r"^delivery workflow acceptance criterion\s+ac-\d+\s+is\s+not\s+complete[:\s-]*", "", text)
    text = re.sub(r"^\-\s*\[[ xX-]\]\s*", "", text)
    text = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    text = " ".join(text.split())
    return text


def _mark_review_failures_in_tasks(tasks_path: str, review_errors: list[str]) -> dict[str, int]:
    path = Path(str(tasks_path or "").strip()).expanduser()
    if not path.exists() or not path.is_file():
        return {"marked": 0, "added": 0}

    normalized_targets: dict[str, str] = {}
    for item in review_errors:
        raw = str(item or "").strip()
        normalized = _normalize_checklist_line(raw)
        if not normalized:
            continue
        normalized_targets[normalized] = raw
    if not normalized_targets:
        return {"marked": 0, "added": 0}

    lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    matched_targets: set[str] = set()
    changed = False
    marked_count = 0

    for line in lines:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if not stripped.startswith("- [ ]"):
            updated.append(line)
            continue

        checklist_text = _normalize_checklist_line(stripped)
        matched_target_key = ""
        for target_key in normalized_targets:
            if target_key in checklist_text or checklist_text in target_key:
                matched_target_key = target_key
                break
        if not matched_target_key:
            updated.append(line)
            continue

        remainder = re.sub(r"^\-\s*\[\s\]\s*", "", stripped)
        updated.append(f"{indent}- [-] {remainder}")
        changed = True
        marked_count += 1
        matched_targets.add(matched_target_key)

    existing_skip_lines = {
        _normalize_checklist_line(line)
        for line in updated
        if line.lstrip().startswith("- [-]")
    }
    unmatched = [
        normalized_targets[key]
        for key in normalized_targets
        if key not in matched_targets and key not in existing_skip_lines
    ]

    added_count = 0
    if unmatched:
        has_skip_heading = any(line.strip().lower() == "## review skips" for line in updated)
        if updated and updated[-1].strip():
            updated.append("")
        if not has_skip_heading:
            updated.append("## Review Skips")
        for item in unmatched:
            updated.append(f"- [-] {item}")
            added_count += 1
        changed = True

    if changed:
        path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return {"marked": marked_count, "added": added_count}


SECTION_ALIASES = {
    "user story": "user_story",
    "story": "user_story",
    "requirements": "requirements",
    "acceptance criteria": "acceptance_criteria",
    "acceptance": "acceptance_criteria",
    "agent context": "agent_context",
    "agent prompt": "agent_prompt",
}


def _unescape_markdown(text: str) -> str:
    return (
        str(text or "")
        .replace("\\#", "#")
        .replace("\\-", "-")
        .replace("\\*", "*")
        .replace("\\`", "`")
    )


def _strip_list_marker(text: str) -> str:
    return re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", str(text or "").strip()).strip()


def _normalize_section_name(value: str) -> str:
    title = _strip_list_marker(_unescape_markdown(value)).strip().lower().rstrip(":")
    return SECTION_ALIASES.get(title, "")


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
        line = _unescape_markdown(raw).strip()
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


def _description_lines(text: str) -> list[str]:
    source = str(text or "").strip()
    if not source:
        return []
    lines: list[str] = []
    for raw in source.splitlines():
        cleaned = raw.strip().lstrip("-*0123456789. ").strip()
        if not cleaned:
            continue
        chunks = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", cleaned) if chunk.strip()]
        lines.extend(chunks if chunks else [cleaned])
    return _dedupe_lines(lines)


def _ticket_name(ticket: dict[str, Any]) -> str:
    return str(ticket.get("summary") or ticket.get("title") or "Untitled Jira task").strip() or "Untitled Jira task"


def _attachments_for_ticket(ticket: dict[str, Any]) -> list[dict[str, str]]:
    raw = ticket.get("attachments") if isinstance(ticket.get("attachments"), list) else []
    attachments: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("content") or item.get("self") or "").strip()
        if not filename and not url:
            continue
        attachment: dict[str, str] = {"filename": filename, "url": url}
        local_path = str(item.get("local_path") or "").strip()
        relative_path = str(item.get("relative_path") or "").strip()
        if local_path:
            attachment["local_path"] = local_path
        if relative_path:
            attachment["relative_path"] = relative_path
        attachments.append(attachment)
    return attachments


def _safe_attachment_name(filename: str, fallback: str) -> str:
    raw = Path(str(filename or "").strip()).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("._-")
    return cleaned or fallback


def _display_attachment_location(attachment: dict[str, str]) -> str:
    relative_path = str(attachment.get("relative_path") or "").strip()
    if relative_path:
        return relative_path
    return str(attachment.get("local_path") or "").strip()


def _format_attachment_reference(attachment: dict[str, str]) -> str:
    filename = str(attachment.get("filename") or "file").strip() or "file"
    url = str(attachment.get("url") or "").strip()
    local_path = _display_attachment_location(attachment)
    details: list[str] = []
    if url:
        details.append(url)
    if local_path:
        details.append(f"local: {local_path}")
    return f"- {filename}" + (f" ({' | '.join(details)})" if details else "")


def _compact_lines(items: list[str], *, limit: int | None = None) -> list[str]:
    compact = _dedupe_lines([_strip_list_marker(_unescape_markdown(item)) for item in items])
    if limit is None:
        return compact
    return compact[: max(0, limit)]


def _ticket_outline(ticket: dict[str, Any]) -> dict[str, Any]:
    sections = _parse_description_sections(str(ticket.get("description") or ""))
    title = _ticket_name(ticket)
    summary_candidates = [
        *sections["user_story"],
        *sections["details"],
        *sections["requirements"],
        title,
    ]
    summary = _compact_lines(summary_candidates, limit=1)[0]
    return {
        "title": title,
        "summary": summary,
        "details": _compact_lines([*sections["user_story"], *sections["details"]], limit=3),
        "requirements": _compact_lines(sections["requirements"], limit=8),
        "acceptance": _compact_lines(sections["acceptance_criteria"], limit=8),
        "agent_context": _compact_lines(sections["agent_context"], limit=8),
        "agent_prompt": _compact_lines(sections["agent_prompt"], limit=8),
    }


def _is_top_level_task(ticket: dict[str, Any]) -> bool:
    issue_type = str(ticket.get("issue_type") or "").strip().lower()
    normalized_issue_type = re.sub(r"[\s_-]+", "", issue_type)
    return normalized_issue_type in {"story", "task", "subtask", "bug", "issue"}


def _normalize_status_name(value: str) -> str:
    return str(value or "").strip().lower()


def _backlog_column_status_matchers(
    kanban_columns: list[dict[str, Any]] | list[Any] | None,
) -> tuple[set[str], set[str]]:
    if not isinstance(kanban_columns, list):
        return set(), set()

    backlog_column: dict[str, Any] | None = None
    for column in kanban_columns:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip().lower()
        if name == "backlog" or "backlog" in name:
            backlog_column = column
            break

    if not backlog_column:
        return set(), set()

    status_ids: set[str] = set()
    status_names: set[str] = set()
    statuses = backlog_column.get("statuses") if isinstance(backlog_column.get("statuses"), list) else []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        status_id = str(status.get("id") or "").strip()
        status_name = _normalize_status_name(str(status.get("name") or ""))
        if status_id:
            status_ids.add(status_id)
        if status_name:
            status_names.add(status_name)
    return status_ids, status_names


def _ticket_matches_backlog_column(
    ticket: dict[str, Any],
    backlog_status_ids: set[str],
    backlog_status_names: set[str],
) -> bool:
    if not backlog_status_ids and not backlog_status_names:
        return True
    ticket_status_id = str(ticket.get("status_id") or "").strip()
    ticket_status_name = _normalize_status_name(str(ticket.get("status") or ""))
    if ticket_status_id and ticket_status_id in backlog_status_ids:
        return True
    if ticket_status_name and ticket_status_name in backlog_status_names:
        return True
    return False


_MAX_CONCURRENT_PIPELINE_TASKS = int(os.getenv("PIPELINE_MAX_CONCURRENT_TASKS", "2"))
_POST_COMPLETE_TRIGGER_OVERRIDE_MINUTES = 5
_ASSIST_BRAIN_ONBOARDING_QUERY_LIMIT = int(os.getenv("ASSIST_BRAIN_ONBOARDING_QUERY_LIMIT", "5"))
_ASSIST_BRAIN_CONTEXT_MAX_CHARS = int(os.getenv("ASSIST_BRAIN_CONTEXT_MAX_CHARS", "4000"))


class PipelineEngine:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = (workspace_root or Path(os.getenv("WORKSPACE_ROOT", Path.cwd()))).resolve()

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._stop_event = threading.Event()
        self._cycle_lock: asyncio.Lock | None = None
        self._graph_semaphore: asyncio.Semaphore | None = None

        self.ticket_graph = None

        self.jira_api_agent = JiraApiAgent(registry_mode="agents")
        self.git_agent = GitAgent()
        self.git_content_agent = GitContentAgent(registry_mode="agents")
        self.slack_agent = SlackAgent()

        self.worker_agents = build_worker_agents(self._agent_model, WorkerAgent)
        self.planner_agent = self.worker_agents["planner_codex"]
        self.code_builder_agent = self.worker_agents["code_builder_codex"]
        self.sdd_spec_model = self._agent_model("sdd_spec")
        self.sdd_spec_agent_id = make_agent_id("agents", "SDD Spec Agent")

        self.pipeline_agent_id = make_agent_id(CONFIG.group, CONFIG.name)
        self.pipeline_heartbeat_id = make_agent_id(CONFIG.group, CONFIG.heartbeat_name)

        self._register_agents()

    def set_ticket_graph(self, ticket_graph: Any) -> None:
        self.ticket_graph = ticket_graph

    async def _run_git_hook(
        self,
        *,
        stage_id: str,
        workspace_path: str,
        context: dict[str, str],
        workflow_key: str = "pipeline",
        starting_git_branch_override: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        jira_key: str | None = None,
        task_relation: str | None = None,
    ) -> dict[str, Any]:
        is_subtask = str(task_relation or "").strip().lower() == PIPELINE_TASK_RELATION_SUBTASK
        result = await run_configured_git_action(
            stage_id=stage_id,
            workspace_path=workspace_path,
            workflow_key=workflow_key,
            context=context,
            target_branch_override=starting_git_branch_override,
            git_agent=self.git_agent,
            is_subtask=is_subtask,
        )
        add_pipeline_log(
            level="info" if bool(result.get("ok")) else "warning",
            task_id=task_id or "",
            run_id=run_id or "",
            jira_key=jira_key or "",
            message=str(result.get("message") or result.get("reason") or result.get("error") or f"Git hook {stage_id} skipped"),
        )
        if self._git_hook_failed(result):
            self._log_agent_error(
                source_agent=self.git_agent.agent_id or "Git Agent",
                error=self._git_hook_error_text(result),
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                context={
                    "stage": stage_id,
                    "action": str(result.get("action") or ""),
                    "result": result.get("result") if isinstance(result.get("result"), dict) else result,
                },
            )
        return result

    def _log_agent_error(
        self,
        *,
        source_agent: str,
        error: str,
        task_id: str | None = None,
        run_id: str | None = None,
        jira_key: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "logger": "Logging Agent",
            "source_agent": str(source_agent or "unknown"),
            "error": str(error or "").strip()[:4000],
        }
        if context:
            payload["context"] = context
        add_pipeline_log(
            level="error",
            task_id=task_id or None,
            run_id=run_id or None,
            jira_key=jira_key or None,
            message=json.dumps(payload, ensure_ascii=False)[:12000],
        )

    async def _materialize_jira_attachments(
        self,
        *,
        workspace_path: str,
        jira_key: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        workspace_root = Path(workspace_path).expanduser().resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)

        normalized_key = _normalize_issue_key(jira_key)
        download_root = workspace_root / ".assist" / "images" / normalized_key
        targets = [
            item
            for item in [
                details.get("ticket") if isinstance(details.get("ticket"), dict) else None,
                *(
                    details.get("subtasks")
                    if isinstance(details.get("subtasks"), list)
                    else []
                ),
            ]
            if isinstance(item, dict)
        ]

        if not targets:
            return {"downloaded_count": 0, "root_relative": "", "warnings": []}

        attachment_count = sum(len(_attachments_for_ticket(ticket)) for ticket in targets)
        if attachment_count <= 0:
            return {"downloaded_count": 0, "root_relative": "", "warnings": []}

        warnings: list[str] = []
        try:
            self.jira_api_agent._validate_env()
        except Exception as exc:
            return {
                "downloaded_count": 0,
                "root_relative": "",
                "warnings": [
                    "Jira attachments were not downloaded for the pipeline run: "
                    + (str(exc).strip() or type(exc).__name__)
                ],
            }

        download_root.mkdir(parents=True, exist_ok=True)
        base_url = self.jira_api_agent._base_url()
        headers = {
            "Accept": "*/*",
            "User-Agent": self.jira_api_agent._headers().get("User-Agent", "AI-Multi-Agent-Assistant/1.0"),
        }
        downloaded_count = 0

        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for ticket in targets:
                ticket_key = _normalize_issue_key(str(ticket.get("key") or "")) or normalized_key
                raw_attachments = ticket.get("attachments") if isinstance(ticket.get("attachments"), list) else []
                for index, item in enumerate(raw_attachments, start=1):
                    if not isinstance(item, dict):
                        continue
                    source_url = str(
                        item.get("url") or item.get("content") or item.get("self") or ""
                    ).strip()
                    if not source_url:
                        warnings.append(f"{ticket_key}: skipped attachment {index} because no download URL was provided.")
                        continue
                    if source_url.startswith("/") and base_url:
                        source_url = f"{base_url}{source_url}"
                    filename = str(item.get("filename") or item.get("name") or "").strip()
                    safe_name = _safe_attachment_name(filename, f"attachment-{index}")
                    target_path = download_root / f"{ticket_key}-{index:02d}-{safe_name}"
                    try:
                        response = await client.get(
                            source_url,
                            auth=self.jira_api_agent._auth(),
                            headers=headers,
                        )
                        response.raise_for_status()
                        target_path.write_bytes(response.content)
                    except Exception as exc:
                        warnings.append(
                            f"{ticket_key}: failed to download {filename or f'attachment {index}'}"
                            f" ({str(exc).strip() or type(exc).__name__})."
                        )
                        continue

                    downloaded_count += 1
                    item["url"] = source_url
                    item["local_path"] = str(target_path)
                    item["relative_path"] = str(target_path.relative_to(workspace_root))

        root_relative = str(download_root.relative_to(workspace_root)) if downloaded_count > 0 else ""
        if root_relative:
            details["attachment_root_relative"] = root_relative

        return {
            "downloaded_count": downloaded_count,
            "root_relative": root_relative,
            "warnings": warnings,
        }

    @staticmethod
    def _git_hook_failed(result: dict[str, Any]) -> bool:
        if bool(result.get("ok")):
            return False
        reason = str(result.get("reason") or "").strip().lower()
        return reason != "disabled"

    @staticmethod
    def _git_hook_error_text(result: dict[str, Any]) -> str:
        stage = str(result.get("stage") or "").strip() or "unknown"
        action = str(result.get("action") or "").strip() or "unknown"
        reason = str(result.get("reason") or result.get("message") or result.get("error") or "").strip()
        details = result.get("result") if isinstance(result.get("result"), dict) else {}
        error = str(details.get("error") or "").strip()
        step = str(details.get("step") or "").strip()
        parts = [f"Git hook {stage} ({action}) failed"]
        if step:
            parts.append(f"step={step}")
        if error:
            parts.append(error)
        elif reason:
            parts.append(reason)
        return ": ".join([parts[0], " | ".join(parts[1:])]) if len(parts) > 1 else parts[0]

    def _ensure_git_hook_succeeded(self, result: dict[str, Any]) -> None:
        if self._git_hook_failed(result):
            raise RuntimeError(self._git_hook_error_text(result))

    @staticmethod
    def _is_git_checkout_conflict(reason: str) -> bool:
        normalized = str(reason or "").strip().lower()
        if not normalized:
            return False
        return (
            "would be overwritten by checkout" in normalized
            or "please commit your changes or stash them before you switch branches" in normalized
            or "checkout failed" in normalized
        )

    @staticmethod
    def _extract_checkout_conflict_files(reason: str) -> list[str]:
        text = str(reason or "")
        if not text:
            return []
        lowered = text.lower()
        marker = "would be overwritten by checkout:"
        marker_index = lowered.find(marker)
        if marker_index < 0:
            return []
        tail = text[marker_index + len(marker):]
        lines = [line.strip() for line in tail.splitlines()]
        files: list[str] = []
        for line in lines:
            if not line:
                continue
            if line.lower().startswith("please commit your changes"):
                break
            candidate = line.lstrip("-").strip()
            if candidate:
                files.append(candidate)
        deduped: list[str] = []
        seen: set[str] = set()
        for file_path in files:
            if file_path in seen:
                continue
            seen.add(file_path)
            deduped.append(file_path)
        return deduped

    def _effective_pipeline_branch(self, task: dict[str, Any]) -> str:
        override = str(task.get("starting_git_branch_override") or "").strip()
        if override:
            return override

        try:
            workflows = get_git_workflow_settings()
            pipeline_settings = (
                workflows.get("workflows", {}).get("pipeline", {}).get("settings", {})
                if isinstance(workflows.get("workflows"), dict)
                else {}
            )
            configured = str(pipeline_settings.get("defaultBranch") or "main").strip()
        except Exception:
            configured = "main"

        if configured == ACTIVE_WORKSPACE_BRANCH_VALUE:
            payload = task.get("jira_payload")
            if isinstance(payload, dict):
                payload_branch = str(payload.get("current_branch") or "").strip()
                if payload_branch:
                    return payload_branch
            return "main"

        return configured or "main"

    def _create_git_handoff_from_failure(
        self,
        *,
        task: dict[str, Any],
        run_id: str | None,
        reason: str,
    ) -> dict[str, Any] | None:
        task_id = str(task.get("id") or "").strip()
        jira_key = _normalize_issue_key(str(task.get("jira_key") or ""))
        if not task_id or not jira_key:
            return None

        changed_files = self._extract_checkout_conflict_files(reason)
        handoff = add_pipeline_git_handoff(
            task_id=task_id,
            run_id=run_id or None,
            jira_key=jira_key,
            reason=reason,
            strategy="manual_required",
            source_branch=self._effective_pipeline_branch(task),
            target_branch="",
            file_summary=changed_files,
        )
        add_pipeline_log(
            level="warning",
            task_id=task_id,
            run_id=run_id or "",
            jira_key=jira_key,
            message=(
                "Captured pipeline git handoff record "
                f"(strategy={handoff.get('strategy')}, files={len(changed_files)})."
            ),
        )
        return handoff

    def _move_tasks_to_queue_tail(self, prioritized_task_ids: list[str]) -> None:
        requested_ids: list[str] = []
        seen_requested: set[str] = set()
        for task_id in prioritized_task_ids:
            normalized_task_id = str(task_id or "").strip()
            if not normalized_task_id or normalized_task_id in seen_requested:
                continue
            seen_requested.add(normalized_task_id)
            requested_ids.append(normalized_task_id)
        if not requested_ids:
            return

        current_tasks = [
            task
            for task in list_pipeline_tasks()
            if str(task.get("status") or "").strip().lower() == PIPELINE_STATUS_CURRENT
        ]
        current_tasks.sort(key=lambda item: int(item.get("order_index") or 0))

        current_ids: list[str] = []
        for task in current_tasks:
            normalized_task_id = str(task.get("id") or "").strip()
            if normalized_task_id:
                current_ids.append(normalized_task_id)

        if not current_ids:
            return

        tail_ids = [task_id for task_id in requested_ids if task_id in current_ids]
        if not tail_ids:
            return

        ordered_ids = [
            task_id
            for task_id in current_ids
            if task_id not in tail_ids
        ]
        ordered_ids.extend(tail_ids)
        reorder_current_pipeline_tasks(ordered_ids)

    def _cascade_dependency_blocks(
        self,
        *,
        source_task: dict[str, Any],
        reason: str,
        run_id: str | None = None,
    ) -> None:
        source_task_id = str(source_task.get("id") or "").strip()
        source_key = _normalize_issue_key(str(source_task.get("jira_key") or ""))
        if not source_task_id or not source_key:
            return

        blocked_reason = f"Blocked by {source_key}: {reason}".strip()[:1200]
        queue_tail_ids: list[str] = [source_task_id]
        queue: list[str] = [source_task_id]
        visited: set[str] = set()
        while queue:
            parent_id = queue.pop(0)
            for dependent_id in list_pipeline_task_dependents(parent_id):
                normalized_dependent_id = str(dependent_id or "").strip()
                if not normalized_dependent_id or normalized_dependent_id in visited:
                    continue
                visited.add(normalized_dependent_id)
                dependent_task = get_pipeline_task(normalized_dependent_id)
                if not dependent_task:
                    continue
                dependent_status = str(dependent_task.get("status") or "").strip().lower()
                if dependent_status in {PIPELINE_STATUS_COMPLETE, PIPELINE_STATUS_RUNNING, PIPELINE_STATUS_BACKLOG}:
                    continue

                move_pipeline_task(
                    normalized_dependent_id,
                    target_status=PIPELINE_STATUS_CURRENT,
                    increment_version=False,
                )

                update_pipeline_task_controls(
                    normalized_dependent_id,
                    clear_failure_reason=True,
                    is_bypassed=True,
                    bypass_reason=blocked_reason,
                    bypass_source=PIPELINE_BYPASS_SOURCE_DEPENDENCY,
                    bypassed_by="system",
                    is_dependency_blocked=True,
                    dependency_block_reason=blocked_reason,
                    execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                    last_failure_code="dependency_blocked",
                )
                add_pipeline_log(
                    level="warning",
                    task_id=normalized_dependent_id,
                    run_id=run_id or "",
                    jira_key=str(dependent_task.get("jira_key") or ""),
                    message=blocked_reason,
                )
                queue_tail_ids.append(normalized_dependent_id)
                queue.append(normalized_dependent_id)

        self._move_tasks_to_queue_tail(queue_tail_ids)

    def _cascade_shared_branch_blocks(
        self,
        *,
        source_task: dict[str, Any],
        reason: str,
        run_id: str | None = None,
    ) -> None:
        source_task_id = str(source_task.get("id") or "").strip()
        source_key = _normalize_issue_key(str(source_task.get("jira_key") or ""))
        source_branch = self._effective_pipeline_branch(source_task)
        if not source_task_id or not source_key or not source_branch:
            return

        blocked_reason = (
            f"Auto-blocked: shared working branch '{source_branch}' with blocked task {source_key}. "
            f"{reason}"
        ).strip()[:1200]
        for candidate in list_pipeline_tasks():
            candidate_id = str(candidate.get("id") or "").strip()
            if not candidate_id or candidate_id == source_task_id:
                continue
            candidate_status = str(candidate.get("status") or "").strip().lower()
            if candidate_status in {PIPELINE_STATUS_COMPLETE, PIPELINE_STATUS_RUNNING, PIPELINE_STATUS_BACKLOG}:
                continue
            candidate_branch = self._effective_pipeline_branch(candidate)
            if candidate_branch != source_branch:
                continue
            if str(candidate.get("bypass_source") or "").strip() == PIPELINE_BYPASS_SOURCE_DEPENDENCY:
                continue

            if candidate_status != PIPELINE_STATUS_CURRENT:
                move_pipeline_task(
                    candidate_id,
                    target_status=PIPELINE_STATUS_CURRENT,
                    increment_version=False,
                )

            update_pipeline_task_controls(
                candidate_id,
                is_bypassed=True,
                bypass_reason=blocked_reason,
                bypass_source=PIPELINE_BYPASS_SOURCE_BRANCH_COHORT,
                bypassed_by="system",
                is_dependency_blocked=True,
                dependency_block_reason=blocked_reason,
                execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                last_failure_code="shared_branch_blocked",
            )
            add_pipeline_log(
                level="warning",
                task_id=candidate_id,
                run_id=run_id or "",
                jira_key=str(candidate.get("jira_key") or ""),
                message=blocked_reason,
            )

    def _recover_task_to_queue(
        self,
        *,
        task: dict[str, Any],
        run_id: str | None,
        reason: str,
        failure_code: str,
        bypass_source: str,
        bypassed_by: str,
        execution_state: str,
        create_handoff: bool = False,
        apply_shared_branch_block: bool = False,
    ) -> dict[str, Any] | None:
        task_id = str(task.get("id") or "").strip()
        jira_key = _normalize_issue_key(str(task.get("jira_key") or ""))
        if not task_id or not jira_key:
            return None

        moved = move_pipeline_task(
            task_id,
            target_status=PIPELINE_STATUS_CURRENT,
            increment_version=False,
            failure_reason=reason,
            is_bypassed=True,
            bypass_reason=reason,
            bypass_source=bypass_source,
            bypassed_by=bypassed_by,
            execution_state=execution_state,
            last_failure_code=failure_code,
        )
        self._cascade_dependency_blocks(source_task=moved or task, reason=reason, run_id=run_id)
        if apply_shared_branch_block:
            self._cascade_shared_branch_blocks(source_task=moved or task, reason=reason, run_id=run_id)

        if create_handoff:
            self._create_git_handoff_from_failure(task=moved or task, run_id=run_id, reason=reason)

        return get_pipeline_task(task_id)

    def _refresh_dependency_state_for_task(self, task_id: str) -> dict[str, Any] | None:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return None

        task = get_pipeline_task(normalized_task_id)
        if not task:
            return None

        dependencies = list_pipeline_task_dependencies(task_id=normalized_task_id)
        if not dependencies:
            bypass_source = str(task.get("bypass_source") or "").strip().lower()
            if bool(int(task.get("is_dependency_blocked") or 0)) or bypass_source == PIPELINE_BYPASS_SOURCE_DEPENDENCY:
                return update_pipeline_task_controls(
                    normalized_task_id,
                    is_bypassed=False if bypass_source == PIPELINE_BYPASS_SOURCE_DEPENDENCY else None,
                    is_dependency_blocked=False,
                    dependency_block_reason="",
                    execution_state=PIPELINE_TASK_EXECUTION_STATE_READY,
                    last_failure_code="",
                    failure_reason="",
                )
            return task

        blockers: list[str] = []
        for dependency in dependencies:
            depends_on_id = str(dependency.get("depends_on_task_id") or "").strip()
            parent = get_pipeline_task(depends_on_id)
            if not parent:
                blockers.append(f"missing dependency task ({depends_on_id})")
                continue
            parent_key = _normalize_issue_key(str(parent.get("jira_key") or depends_on_id))
            parent_status = str(parent.get("status") or "").strip().lower()
            if parent_status != PIPELINE_STATUS_COMPLETE:
                blockers.append(f"{parent_key} ({parent_status or 'unknown'})")

        if blockers:
            reason = "Dependency blocked: " + " | ".join(blockers[:3])
            return update_pipeline_task_controls(
                normalized_task_id,
                clear_failure_reason=True,
                is_bypassed=True,
                bypass_reason=reason,
                bypass_source=PIPELINE_BYPASS_SOURCE_DEPENDENCY,
                bypassed_by="system",
                is_dependency_blocked=True,
                dependency_block_reason=reason,
                execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                last_failure_code="dependency_blocked",
            )

        bypass_source = str(task.get("bypass_source") or "").strip().lower()
        return update_pipeline_task_controls(
            normalized_task_id,
            is_bypassed=False if bypass_source == PIPELINE_BYPASS_SOURCE_DEPENDENCY else None,
            is_dependency_blocked=False,
            dependency_block_reason="",
            execution_state=PIPELINE_TASK_EXECUTION_STATE_READY,
            last_failure_code="",
            failure_reason="",
        )

    def _extract_spec_dependency_keys(self, payload: dict[str, Any]) -> list[str]:
        parent_spec_name = _normalize_issue_key(str(payload.get("parent_spec_name") or ""))
        raw_depends_on = payload.get("depends_on")
        normalized_depends_on: list[str] = []
        if isinstance(raw_depends_on, list):
            for item in raw_depends_on:
                normalized_key = _normalize_issue_key(str(item or ""))
                if normalized_key:
                    normalized_depends_on.append(normalized_key)

        keys: list[str] = []
        seen: set[str] = set()
        if parent_spec_name:
            keys.append(parent_spec_name)
            seen.add(parent_spec_name)
        for item in normalized_depends_on:
            if item in seen:
                continue
            seen.add(item)
            keys.append(item)
        return keys

    def _resolve_spec_dependency_task_ids(
        self,
        *,
        task_id: str,
        payload: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        dependency_keys = self._extract_spec_dependency_keys(payload)
        if not dependency_keys:
            return [], []

        normalized_task_id = str(task_id or "").strip()
        tasks = list_pipeline_tasks()
        task_id_by_key: dict[str, str] = {}
        for row in tasks:
            candidate_id = str(row.get("id") or "").strip()
            if not candidate_id or candidate_id == normalized_task_id:
                continue
            candidate_key = _normalize_issue_key(str(row.get("jira_key") or ""))
            if not candidate_key:
                continue
            if candidate_key not in task_id_by_key:
                task_id_by_key[candidate_key] = candidate_id

        dependency_task_ids: list[str] = []
        unresolved_keys: list[str] = []
        for dependency_key in dependency_keys:
            dependency_task_id = task_id_by_key.get(dependency_key)
            if not dependency_task_id:
                unresolved_keys.append(dependency_key)
                continue
            if dependency_task_id not in dependency_task_ids:
                dependency_task_ids.append(dependency_task_id)

        return dependency_task_ids, unresolved_keys

    def set_task_bypass(
        self,
        task_id: str,
        *,
        bypassed: bool,
        reason: str | None = None,
        source: str | None = None,
        by: str | None = None,
        resolve_handoffs: bool = False,
    ) -> dict[str, Any]:
        task = get_pipeline_task(task_id)
        if not task:
            raise RuntimeError("Pipeline task not found")

        normalized_task_id = str(task.get("id") or "").strip()
        if not normalized_task_id:
            raise RuntimeError("Pipeline task id is missing")

        normalized_reason = str(reason or "").strip()
        if bypassed:
            updated = update_pipeline_task_controls(
                normalized_task_id,
                is_bypassed=True,
                bypass_reason=normalized_reason or "Bypassed by user.",
                bypass_source=source or PIPELINE_BYPASS_SOURCE_MANUAL,
                bypassed_by=by or "user",
                execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                last_failure_code=(
                    str(task.get("last_failure_code") or "").strip()
                    or "manual_bypass"
                ),
            )
            self._cascade_dependency_blocks(
                source_task=updated if isinstance(updated, dict) else task,
                reason=normalized_reason or "Parent task bypassed by user.",
                run_id=None,
            )
            add_pipeline_log(
                level="warning",
                task_id=normalized_task_id,
                jira_key=str(task.get("jira_key") or ""),
                message=f"Task bypass enabled: {normalized_reason or 'Bypassed by user.'}",
            )
        else:
            if resolve_handoffs:
                unresolved = list_pipeline_git_handoffs(task_id=normalized_task_id, unresolved_only=True, limit=200)
                for handoff in unresolved:
                    resolve_pipeline_git_handoff(
                        str(handoff.get("id") or ""),
                        resolved_by=by or "user",
                        resolution_note="Resolved while re-enabling task.",
                    )

            updated = update_pipeline_task_controls(
                normalized_task_id,
                is_bypassed=False,
                bypass_reason="",
                bypass_source=source or PIPELINE_BYPASS_SOURCE_MANUAL,
                bypassed_by=by or "user",
                is_dependency_blocked=False,
                dependency_block_reason="",
                execution_state=PIPELINE_TASK_EXECUTION_STATE_READY,
                last_failure_code="",
                failure_reason="",
            )
            add_pipeline_log(
                level="info",
                task_id=normalized_task_id,
                jira_key=str(task.get("jira_key") or ""),
                message="Task bypass disabled and task re-enabled.",
            )

        for dependent_id in list_pipeline_task_dependents(normalized_task_id):
            self._refresh_dependency_state_for_task(dependent_id)

        refreshed = get_pipeline_task(normalized_task_id)
        if not refreshed:
            raise RuntimeError("Failed to refresh pipeline task")
        return refreshed

    def list_task_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeError("task_id is required")
        return list_pipeline_task_dependencies(task_id=normalized_task_id)

    def set_task_dependencies(self, task_id: str, depends_on_task_ids: list[str]) -> list[dict[str, Any]]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeError("task_id is required")
        if not get_pipeline_task(normalized_task_id):
            raise RuntimeError("Pipeline task not found")
        for parent_id in depends_on_task_ids:
            normalized_parent_id = str(parent_id or "").strip()
            if not normalized_parent_id:
                continue
            if not get_pipeline_task(normalized_parent_id):
                raise RuntimeError(f"Dependency task not found: {normalized_parent_id}")

        replaced = replace_pipeline_task_dependencies(normalized_task_id, depends_on_task_ids)
        self._refresh_dependency_state_for_task(normalized_task_id)
        add_pipeline_log(
            level="info",
            task_id=normalized_task_id,
            jira_key=str(get_pipeline_task(normalized_task_id).get("jira_key") or ""),
            message=f"Updated task dependencies ({len(replaced)} linked task(s)).",
        )
        return replaced

    def list_task_handoffs(self, task_id: str) -> list[dict[str, Any]]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeError("task_id is required")
        return list_pipeline_git_handoffs(task_id=normalized_task_id, unresolved_only=False, limit=300)

    def resolve_task_handoff(
        self,
        task_id: str,
        handoff_id: str,
        *,
        resolved_by: str | None = None,
        resolution_note: str | None = None,
        reenable_task: bool = False,
    ) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        normalized_handoff_id = str(handoff_id or "").strip()
        if not normalized_task_id or not normalized_handoff_id:
            raise RuntimeError("task_id and handoff_id are required")

        handoff = get_pipeline_git_handoff(normalized_handoff_id)
        if not handoff:
            raise RuntimeError("Pipeline handoff not found")
        if str(handoff.get("task_id") or "") != normalized_task_id:
            raise RuntimeError("Pipeline handoff does not belong to this task")

        resolved = resolve_pipeline_git_handoff(
            normalized_handoff_id,
            resolved_by=resolved_by or "user",
            resolution_note=resolution_note,
        )
        if not resolved:
            raise RuntimeError("Failed to resolve handoff")

        if reenable_task and not has_unresolved_pipeline_git_handoff(normalized_task_id):
            self.set_task_bypass(
                normalized_task_id,
                bypassed=False,
                reason="Handoff resolved.",
                source=PIPELINE_BYPASS_SOURCE_MANUAL,
                by=resolved_by or "user",
                resolve_handoffs=False,
            )

        task = get_pipeline_task(normalized_task_id)
        if task:
            add_pipeline_log(
                level="info",
                task_id=normalized_task_id,
                jira_key=str(task.get("jira_key") or ""),
                message=(
                    f"Resolved git handoff {normalized_handoff_id}"
                    + (" and re-enabled task." if reenable_task else ".")
                ),
            )
        return resolved

    @staticmethod
    def _write_review_failure_report(
        *,
        workspace_path: str,
        jira_key: str,
        task_id: str,
        run_id: str,
        version: int,
        workflow: str,
        mode: str,
        category: str,
        skipped: bool,
        review_errors: list[str],
        review_summary: str,
    ) -> str:
        workspace_root = Path(str(workspace_path or "").strip()).expanduser().resolve()
        report_dir = workspace_root / ".assist" / "review" / _normalize_issue_key(jira_key) / "failures"
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc)
        stamp = timestamp.strftime("%Y%m%d-%H%M%S")
        status_label = "skipped" if skipped else "failed"
        report_path = report_dir / f"{stamp}-{status_label}.md"

        lines = [
            f"# Review Failure ({status_label.upper()})",
            "",
            f"- Task: `{_normalize_issue_key(jira_key)}`",
            f"- Task ID: `{task_id}`",
            f"- Run ID: `{run_id}`",
            f"- Version: `v{int(version)}`",
            f"- Workflow: `{workflow}`",
            f"- Policy mode: `{mode}`",
            f"- Classified as: `{category}`",
            f"- Outcome: `{'pipeline continued' if skipped else 'pipeline failed'}`",
            f"- Recorded at: `{timestamp.isoformat()}`",
            "",
        ]
        if review_summary:
            lines.extend(
                [
                    "## Summary",
                    "",
                    review_summary,
                    "",
                ]
            )
        if review_errors:
            lines.append("## Errors")
            lines.append("")
            for item in review_errors:
                lines.append(f"- {item}")
            lines.append("")

        report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return str(report_path)

    async def _notify_pipeline_build_complete(
        self,
        *,
        jira_key: str,
        workspace_path: str,
        workflow: str,
        success: bool,
        version: int | None = None,
        attempt_count: int | None = None,
        max_retries: int | None = None,
        attempts_running: int | None = None,
        attempts_completed: int | None = None,
        attempts_failed: int | None = None,
        review_blocked: bool | None = None,
        codex_status: str | None = None,
        codex_summary: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if not self.slack_agent.is_configured():
            return

        lines = [
            "Pipeline run",
            f"Task: {jira_key}",
            f"Workflow: {workflow}",
        ]
        if version is not None:
            lines.append(f"Version: v{int(version)}")
        if attempt_count is not None and max_retries is not None:
            lines.append(f"Attempts: {int(attempt_count)}/{int(max_retries)}")
        if attempts_running is not None and attempts_completed is not None and attempts_failed is not None:
            lines.append(
                "Loop states: "
                f"running={int(attempts_running)} completed={int(attempts_completed)} failed={int(attempts_failed)}"
            )
        if workspace_path:
            lines.append(f"Workspace: {workspace_path}")
        if codex_status:
            lines.append(f"Codex status: {codex_status}")
        lines.append(f"Task request met: {'yes' if success else 'no'}")
        if not success and review_blocked is True:
            lines.append("Failure class: review blockers")

        if success:
            built = str(codex_summary or "").strip()
            if built:
                lines.extend(["", "Built:", built[:2000]])
        else:
            failed = str(failure_reason or "").strip()
            context = str(codex_summary or "").strip()
            if failed:
                lines.extend(["", "Task request unmet:", failed[:2000]])
            if context:
                lines.extend(["", "Context:", context[:1500]])

        try:
            await self.slack_agent.notify_build_complete(
                summary="\n".join(lines)[:3500],
                success=success,
            )
        except Exception as exc:
            self._log_agent_error(
                source_agent=self.slack_agent.agent_id or "Slack Agent",
                error=f"Pipeline Slack notification failed: {self._format_exception(exc)}",
                jira_key=jira_key,
                context={"phase": "slack_notify", "workflow": workflow},
            )

    @staticmethod
    def _build_assist_brain_onboarding_query(
        *,
        jira_key: str,
        task_source: str,
        workspace_path: str,
        title: str,
    ) -> str:
        source_label = "SPEC task" if task_source == PIPELINE_TASK_SOURCE_SPEC else "Jira task"
        workspace_label = str(workspace_path or "").strip() or "unknown workspace"
        summary = str(title or "").strip() or jira_key
        return (
            f"Pipeline onboarding context for {source_label} {jira_key}. "
            f"Task summary: {summary}. "
            f"Workspace: {workspace_label}. "
            "Find prior implementation decisions, blockers, failed attempts, and completion notes."
        )

    async def _attach_assist_brain_context(
        self,
        *,
        details: dict[str, Any],
        jira_key: str,
        task_source: str,
        workspace_path: str,
        task_id: str,
        run_id: str,
    ) -> None:
        ticket = details.get("ticket") if isinstance(details.get("ticket"), dict) else {}
        title = str(ticket.get("summary") or ticket.get("title") or "").strip()
        query = self._build_assist_brain_onboarding_query(
            jira_key=jira_key,
            task_source=task_source,
            workspace_path=workspace_path,
            title=title,
        )
        context = await search_assist_brain(
            workspace_path or self.workspace_root,
            query=query,
            limit=_ASSIST_BRAIN_ONBOARDING_QUERY_LIMIT,
        )
        if not context:
            return

        normalized = context.strip()[:_ASSIST_BRAIN_CONTEXT_MAX_CHARS]
        details["assist_brain_context"] = normalized
        add_pipeline_log(
            level="info",
            task_id=task_id or None,
            run_id=run_id or None,
            jira_key=jira_key,
            message="Assist Brain onboarding context loaded for this pipeline run.",
        )

    async def _capture_pipeline_outcome_memory(
        self,
        *,
        jira_key: str,
        task_source: str,
        workspace_path: str,
        workflow: str,
        success: bool,
        version: int,
        attempt_count: int,
        max_retries: int,
        codex_status: str,
        codex_summary: str,
        failure_reason: str,
        task_id: str = "",
        run_id: str = "",
    ) -> None:
        status_text = "completed" if success else "failed"
        source_label = "SPEC task" if task_source == PIPELINE_TASK_SOURCE_SPEC else "Jira task"
        normalized_workspace = str(workspace_path or "").strip() or str(self.workspace_root)
        normalized_summary = str(codex_summary or "").strip()
        normalized_failure = str(failure_reason or "").strip()
        content_lines = [
            f"Pipeline {status_text}: {source_label} {jira_key}.",
            f"Workflow: {workflow}.",
            f"Workspace: {normalized_workspace}.",
            f"Version: v{int(version)}.",
            f"Attempts: {int(attempt_count)}/{max(1, int(max_retries))}.",
            f"Codex status: {str(codex_status or ('success' if success else 'failed')).strip()}.",
        ]
        if normalized_summary:
            content_lines.append("Build/review summary:")
            content_lines.append(normalized_summary[:3000])
        if normalized_failure:
            content_lines.append("Failure reason:")
            content_lines.append(normalized_failure[:2000])
        metadata = {
            "workflow": str(workflow or PIPELINE_WORKFLOW),
            "jira_key": jira_key,
            "task_source": task_source,
            "status": "completed" if success else "failed",
            "task_id": str(task_id or ""),
            "run_id": str(run_id or ""),
        }
        await capture_assist_brain(
            workspace_path or self.workspace_root,
            content="\n".join(content_lines)[:7000],
            metadata=metadata,
        )

    @property
    def started(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._loop is not None

    @staticmethod
    def _agent_model(settings_key: str | None) -> str | None:
        if not settings_key:
            return None
        return get_agent_model(settings_key)

    def _register_agents(self) -> None:
        self.sdd_spec_agent_id = register_sdd_spec_agent(
            group="agents",
            dependency_ids=[self.pipeline_agent_id],
            model=self.sdd_spec_model,
        )
        register_agent(
            AgentDefinition(
                id=self.pipeline_agent_id,
                name=CONFIG.name,
                provider=None,
                model=None,
                group=CONFIG.group,
                role=CONFIG.role,
                kind="agent",
                dependencies=[],
                source="app/agents_pipeline/runtime.py",
                description=CONFIG.description,
                capabilities=["pipeline", "jira", "scheduled_execution", "autonomous_build"],
            )
        )
        register_agent(
            AgentDefinition(
                id=self.pipeline_heartbeat_id,
                name=CONFIG.heartbeat_name,
                provider=None,
                model=None,
                group=CONFIG.group,
                role="heartbeat",
                kind="agent",
                dependencies=[self.pipeline_agent_id],
                source="app/agents_pipeline/runtime.py",
                description="Background heartbeat scheduler for autonomous pipeline execution.",
                capabilities=["scheduler", "time_window", "heartbeat"],
            )
        )

    def start(self) -> None:
        ensure_pipeline_schema()
        recovered_count = recover_stale_pipeline_state()
        if recovered_count > 0:
            add_pipeline_log(
                level="error",
                message=(
                    f"Recovered {recovered_count} pipeline task(s) that were left in running state after restart."
                ),
            )

        self.jira_api_agent.register()
        self.git_content_agent.register()
        self.slack_agent.register()

        if self.started:
            return
        self._stop_event.clear()
        self._loop_ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="pipeline-heartbeat", daemon=True)
        self._thread.start()
        self._loop_ready.wait(timeout=5)

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._cycle_lock = asyncio.Lock()
        self._graph_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PIPELINE_TASKS)
        self._loop_ready.set()
        try:
            loop.run_until_complete(self._heartbeat_loop())
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _heartbeat_loop(self) -> None:
        from app.connection_monitor import connection_monitor

        while not self._stop_event.is_set():
            while not connection_monitor.is_connected() and not self._stop_event.is_set():
                await asyncio.sleep(1.0)

            if self._stop_event.is_set():
                break

            try:
                await self._maybe_run_heartbeat()
            except Exception as exc:
                if not connection_monitor.is_connected():
                    print(
                        f'[pipeline] Heartbeat error while disconnected (skipping log): {exc}',
                        flush=True,
                    )
                else:
                    try:
                        self._log_agent_error(
                            source_agent=self.pipeline_heartbeat_id,
                            error=f"Pipeline heartbeat error: {self._format_exception(exc)}",
                            context={"phase": "heartbeat_loop"},
                        )
                    except Exception as log_exc:
                        print(
                            f'[pipeline] Heartbeat error (DB log also failed): {exc} | log_err: {log_exc}',
                            flush=True,
                        )

            await asyncio.sleep(PIPELINE_POLL_SECONDS)

    async def _maybe_run_heartbeat(self) -> None:
        settings = get_pipeline_settings()
        automation_enabled = bool(int(settings.get("automation_enabled") or 0))
        now_local = datetime.now().astimezone()
        start_time = _normalize_window_time(
            str(settings.get("active_window_start") or ""),
            DEFAULT_ACTIVE_WINDOW_START,
        )
        end_time = _normalize_window_time(
            str(settings.get("active_window_end") or ""),
            DEFAULT_ACTIVE_WINDOW_END,
        )
        start_minutes = _time_to_minutes(start_time)
        end_minutes = _time_to_minutes(end_time)

        if not _is_within_window(now_local, start_minutes, end_minutes):
            return

        interval_minutes = int(settings.get("heartbeat_interval_minutes") or DEFAULT_HEARTBEAT_INTERVAL_MINUTES)
        interval_minutes = max(MIN_HEARTBEAT_INTERVAL_MINUTES, interval_minutes)

        last_heartbeat_at = _parse_iso_datetime(str(settings.get("last_heartbeat_at") or ""))
        next_heartbeat_override_at = _parse_iso_datetime(str(settings.get("next_heartbeat_override_at") or ""))
        if not automation_enabled and next_heartbeat_override_at is None:
            return
        next_due_at = _next_heartbeat_due_at(
            now_local=now_local,
            interval_minutes=interval_minutes,
            last_heartbeat_at=last_heartbeat_at,
            next_override_at=next_heartbeat_override_at,
        )
        due = next_due_at is None or now_local >= next_due_at

        if not due:
            return

        # Do not advance heartbeat timing or perform scheduler work while a task
        # is already executing. The next cycle should wait for that task to finish.
        if has_running_pipeline_task():
            return

        # Recover any task that has been stuck in running state beyond the execution timeout.
        recovered_stale = recover_stale_running_task(CODEX_TIMEOUT_SECONDS)
        if recovered_stale > 0:
            add_pipeline_log(
                level="warn",
                message=(
                    f"Recovered {recovered_stale} pipeline task(s) stuck in running state "
                    f"after exceeding the {CODEX_TIMEOUT_SECONDS}s timeout (e.g. network dropout)."
                ),
            )

        # Refresh dependency state for any currently-blocked tasks so that tasks
        # whose parent has since completed are unblocked automatically.
        for blocked_task_id in list_dependency_blocked_current_task_ids():
            self._refresh_dependency_state_for_task(blocked_task_id)

        if not self._cycle_lock:
            self._cycle_lock = asyncio.Lock()
        if self._cycle_lock.locked():
            return

        mark_agent_start(self.pipeline_heartbeat_id)
        try:
            update_pipeline_heartbeat(
                last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
                next_heartbeat_override_at="",
            )
            async with self._cycle_lock:
                await self._run_cycle()
        finally:
            mark_agent_end(self.pipeline_heartbeat_id)

    async def _run_cycle(self) -> None:
        if has_running_pipeline_task():
            return

        task = pop_next_current_pipeline_task()
        if not task:
            return

        task_id = str(task.get("id") or "")
        jira_key = _normalize_issue_key(str(task.get("jira_key") or ""))
        task_source = _normalize_task_source(str(task.get("task_source") or ""))
        task_relation = str(task.get("task_relation") or PIPELINE_TASK_RELATION_TASK) if str(task.get("task_relation") or "").strip().lower() in PIPELINE_TASK_RELATIONS else PIPELINE_TASK_RELATION_TASK
        workspace_path = str(task.get("workspace_path") or "").strip()
        starting_git_branch_override = str(task.get("starting_git_branch_override") or "").strip()
        workflow = _normalize_workflow(str(task.get("workflow") or ""))
        version = int(task.get("version") or 1)

        run = create_pipeline_run(
            task_id=task_id,
            jira_key=jira_key,
            task_source=task_source,
            version=version,
            workspace_path=workspace_path,
            workflow=workflow,
        )
        run_id = str(run.get("id") or "")
        set_pipeline_task_active_run(task_id, run_id)
        update_pipeline_heartbeat(last_cycle_at=datetime.now(timezone.utc).isoformat())

        add_pipeline_log(
            level="info",
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=f"Heartbeat triggered execution for {jira_key} (v{version}, workflow={workflow}).",
        )
        workspace_root = Path(workspace_path).expanduser().resolve()
        bootstrap = ensure_workspace_bootstrap(workspace_root) if workspace_root.exists() and workspace_root.is_dir() else None
        if bootstrap and bootstrap.gitignore_created:
            add_pipeline_log(
                level="info",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message="Created root .gitignore from the standard template before pipeline git actions.",
            )
        initial_git_hook = await self._run_git_hook(
            stage_id="initial",
            workspace_path=workspace_path,
            context={
                "description": jira_key,
                "ticket": jira_key,
                "summary": str(task.get("title") or ""),
                "type": "pipeline_spec" if task_source == PIPELINE_TASK_SOURCE_SPEC else "pipeline",
            },
            workflow_key="pipeline_spec" if task_source == PIPELINE_TASK_SOURCE_SPEC else "pipeline",
            starting_git_branch_override=starting_git_branch_override,
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            task_relation=task_relation,
        )
        if self._git_hook_failed(initial_git_hook):
            reason = self._git_hook_error_text(initial_git_hook)
            is_checkout_conflict = self._is_git_checkout_conflict(reason)
            failure_code = "git_checkout_dirty_conflict" if is_checkout_conflict else "initial_git_hook_failed"
            finalize_pipeline_run(
                run_id,
                status=PIPELINE_RUN_STATUS_FAILED,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                attempts_failed=1,
                attempts_completed=0,
                current_activity="Failed before execution.",
                failure_reason=reason,
            )
            recovered_task = self._recover_task_to_queue(
                task=task,
                run_id=run_id,
                reason=reason,
                failure_code=failure_code,
                bypass_source=(
                    PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF
                    if is_checkout_conflict
                    else PIPELINE_BYPASS_SOURCE_AUTO_FAILURE
                ),
                bypassed_by="system",
                execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                create_handoff=is_checkout_conflict,
                apply_shared_branch_block=is_checkout_conflict,
            )
            self._set_spec_task_status_for_pipeline_task(
                task=recovered_task if isinstance(recovered_task, dict) else task,
                status=SPEC_TASK_STATUS_FAILED,
                context="run:initial-git-hook-failed",
                sync_backlog=True,
            )
            set_pipeline_task_active_run(task_id, None)
            add_pipeline_log(
                level="error",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=(
                    "Pipeline run failed before execution and was returned to Task Queue as blocked. "
                    + reason
                ),
            )
            await self._capture_pipeline_outcome_memory(
                jira_key=jira_key,
                task_source=task_source,
                workspace_path=workspace_path,
                workflow=workflow,
                success=False,
                version=version,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                codex_status="failed",
                codex_summary="Pipeline stopped before build stage due to initial git hook failure.",
                failure_reason=reason,
                task_id=task_id,
                run_id=run_id,
            )
            await self._notify_pipeline_build_complete(
                jira_key=jira_key,
                workspace_path=workspace_path,
                workflow=workflow,
                success=False,
                version=version,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                attempts_running=0,
                attempts_completed=0,
                attempts_failed=1,
                failure_reason=reason,
            )
            update_pipeline_heartbeat(last_heartbeat_at=datetime.now(timezone.utc).isoformat())
            return

        if self.ticket_graph is not None:
            asyncio.create_task(
                self._dispatch_task_to_graph(task, run)
            )
            return

        mark_agent_start(self.pipeline_agent_id)
        try:
            execution = await self._execute_task_run(task, run)
            latest = get_pipeline_task(task_id) or {}
            latest_status = str(latest.get("status") or "").strip().lower()
            manual_stop_requested = (
                latest_status == PIPELINE_STATUS_CURRENT
                and bool(int(latest.get("is_bypassed") or 0))
                and str(latest.get("last_failure_code") or "").strip().lower() == "manual_stop_requested"
            )

            # User may have manually stopped or removed this task while execution was in flight.
            if latest_status in {PIPELINE_STATUS_STOPPED, PIPELINE_STATUS_BACKLOG} or manual_stop_requested:
                halted_status = PIPELINE_STATUS_STOPPED if latest_status == PIPELINE_STATUS_STOPPED or manual_stop_requested else PIPELINE_STATUS_BACKLOG
                finalize_pipeline_run(
                    run_id,
                    status=PIPELINE_RUN_STATUS_STOPPED if halted_status == PIPELINE_STATUS_STOPPED else PIPELINE_RUN_STATUS_FAILED,
                    attempt_count=int(execution.get("attempt_count") or 0),
                    max_retries=int(execution.get("max_retries") or 0),
                    attempts_failed=int(execution.get("attempts_failed") or 0),
                    attempts_completed=int(execution.get("attempts_completed") or 0),
                    current_activity=(
                        "Stopped by user."
                        if halted_status == PIPELINE_STATUS_STOPPED
                        else "Moved to backlog while running."
                    ),
                    failure_reason=(
                        str(latest.get("failure_reason") or "").strip()
                        or ("Stopped by user." if halted_status == PIPELINE_STATUS_STOPPED else "Moved to backlog while running.")
                    ),
                )
                halted_spec_status = (
                    SPEC_TASK_STATUS_FAILED
                    if halted_status == PIPELINE_STATUS_STOPPED
                    else SPEC_TASK_STATUS_PENDING
                )
                self._set_spec_task_status_for_pipeline_task(
                    task=latest if isinstance(latest, dict) else task,
                    status=halted_spec_status,
                    context=f"run:halted:{halted_status}",
                    sync_backlog=True,
                )
                set_pipeline_task_active_run(task_id, None)
                add_pipeline_log(
                    level="info",
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    message=f"Pipeline run halted for {jira_key}; task status changed to {halted_status}.",
                )
                return

            success = bool(execution.get("success"))
            failure_reason = str(execution.get("failure_reason") or "").strip()

            finalize_pipeline_run(
                run_id,
                status=PIPELINE_RUN_STATUS_COMPLETE if success else PIPELINE_RUN_STATUS_FAILED,
                attempt_count=int(execution.get("attempt_count") or 0),
                max_retries=int(execution.get("max_retries") or 0),
                attempts_failed=int(execution.get("attempts_failed") or 0),
                attempts_completed=int(execution.get("attempts_completed") or 0),
                current_activity=(
                    "Repair loop completed successfully."
                    if success
                    else "Repair loop exhausted with remaining blockers."
                ),
                brief_path=str(execution.get("brief_path") or ""),
                spec_path=str(execution.get("spec_path") or ""),
                task_path=str(execution.get("task_path") or ""),
                codex_status=str(execution.get("codex_status") or ""),
                codex_summary=str(execution.get("codex_summary") or ""),
                failure_reason=failure_reason,
            )
            if success:
                updated_task = set_pipeline_task_result(
                    task_id,
                    status=PIPELINE_STATUS_COMPLETE,
                    failure_reason=None,
                )
                update_pipeline_heartbeat(
                    next_heartbeat_override_at=(
                        datetime.now(timezone.utc) + timedelta(minutes=_POST_COMPLETE_TRIGGER_OVERRIDE_MINUTES)
                    ).isoformat()
                )
            else:
                is_checkout_conflict = self._is_git_checkout_conflict(failure_reason)
                if is_checkout_conflict:
                    updated_task = self._recover_task_to_queue(
                        task=task,
                        run_id=run_id,
                        reason=failure_reason or "Git checkout conflict blocked pipeline execution.",
                        failure_code="git_checkout_dirty_conflict",
                        bypass_source=PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF,
                        bypassed_by="system",
                        execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                        create_handoff=True,
                        apply_shared_branch_block=True,
                    )
                else:
                    updated_task = set_pipeline_task_result(
                        task_id,
                        status=PIPELINE_STATUS_FAILED,
                        failure_reason=failure_reason,
                    )

            updated_task_id = str(task_id).strip()
            if isinstance(updated_task, dict):
                candidate_task_id = str(updated_task.get("id") or "").strip()
                if candidate_task_id:
                    updated_task_id = candidate_task_id

            for dependent_id in list_pipeline_task_dependents(updated_task_id):
                self._refresh_dependency_state_for_task(dependent_id)

            self._set_spec_task_status_for_pipeline_task(
                task=updated_task if isinstance(updated_task, dict) else task,
                status=SPEC_TASK_STATUS_COMPLETE if success else SPEC_TASK_STATUS_FAILED,
                context="run:result",
                sync_backlog=True,
            )
            set_pipeline_task_active_run(task_id, None)

            if (
                success
                and isinstance(updated_task, dict)
                and _normalize_task_source(str(updated_task.get("task_source") or "")) != PIPELINE_TASK_SOURCE_SPEC
            ):
                await self._move_completed_jira_ticket_to_selected_column(
                    task=updated_task,
                    jira_key=jira_key,
                    task_id=task_id,
                    run_id=run_id,
                )

            add_pipeline_log(
                level="info" if success else "error",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=(
                    f"Pipeline run {'completed' if success else 'failed'} for {jira_key} v{version}."
                    + (f" Reason: {failure_reason}" if (failure_reason and not success) else "")
                ),
            )
            await self._capture_pipeline_outcome_memory(
                jira_key=jira_key,
                task_source=task_source,
                workspace_path=workspace_path,
                workflow=workflow,
                success=success,
                version=version,
                attempt_count=int(execution.get("attempt_count") or 0),
                max_retries=int(execution.get("max_retries") or 0),
                codex_status=str(execution.get("codex_status") or ""),
                codex_summary=str(execution.get("codex_summary") or ""),
                failure_reason=failure_reason,
                task_id=task_id,
                run_id=run_id,
            )
            await self._notify_pipeline_build_complete(
                jira_key=jira_key,
                workspace_path=workspace_path,
                workflow=workflow,
                success=success,
                version=version,
                attempt_count=int(execution.get("attempt_count") or 0) or None,
                max_retries=int(execution.get("max_retries") or 0) or None,
                attempts_running=int(execution.get("attempts_running") or 0),
                attempts_completed=int(execution.get("attempts_completed") or 0) or None,
                attempts_failed=int(execution.get("attempts_failed") or 0) or None,
                review_blocked=bool(execution.get("review_blocked")) if not success else None,
                codex_status=str(execution.get("codex_status") or ""),
                codex_summary=str(execution.get("codex_summary") or ""),
                failure_reason=failure_reason,
            )
        except Exception as exc:
            reason = self._format_exception(exc)
            is_checkout_conflict = self._is_git_checkout_conflict(reason)
            failure_code = "git_checkout_dirty_conflict" if is_checkout_conflict else "runtime_exception"
            self._log_agent_error(
                source_agent=self.pipeline_agent_id,
                error=reason,
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                context={"phase": "run_cycle"},
            )
            finalize_pipeline_run(
                run_id,
                status=PIPELINE_RUN_STATUS_FAILED,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                attempts_failed=1,
                attempts_completed=0,
                current_activity="Pipeline run failed with exception.",
                failure_reason=reason,
            )
            recovered_task = self._recover_task_to_queue(
                task=task,
                run_id=run_id,
                reason=reason,
                failure_code=failure_code,
                bypass_source=(
                    PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF
                    if is_checkout_conflict
                    else PIPELINE_BYPASS_SOURCE_AUTO_FAILURE
                ),
                bypassed_by="system",
                execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                create_handoff=is_checkout_conflict,
                apply_shared_branch_block=is_checkout_conflict,
            )
            self._set_spec_task_status_for_pipeline_task(
                task=recovered_task if isinstance(recovered_task, dict) else task,
                status=SPEC_TASK_STATUS_FAILED,
                context="run:exception",
                sync_backlog=True,
            )
            set_pipeline_task_active_run(task_id, None)
            add_pipeline_log(
                level="error",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f"Pipeline run failed with exception: {reason}",
            )
            await self._capture_pipeline_outcome_memory(
                jira_key=jira_key,
                task_source=task_source,
                workspace_path=workspace_path,
                workflow=workflow,
                success=False,
                version=version,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                codex_status="failed",
                codex_summary="Pipeline runtime exception before successful completion.",
                failure_reason=reason,
                task_id=task_id,
                run_id=run_id,
            )
            await self._notify_pipeline_build_complete(
                jira_key=jira_key,
                workspace_path=workspace_path,
                workflow=workflow,
                success=False,
                version=version,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                attempts_running=0,
                attempts_completed=0,
                attempts_failed=1,
                failure_reason=reason,
            )
        finally:
            update_pipeline_heartbeat(last_heartbeat_at=datetime.now(timezone.utc).isoformat())
            mark_agent_end(self.pipeline_agent_id)

    async def _dispatch_task_to_graph(self, task: dict[str, Any], run: dict[str, Any]) -> None:
        task_id = str(task.get("id") or "")
        jira_key = _normalize_issue_key(str(task.get("jira_key") or ""))
        task_source = _normalize_task_source(str(task.get("task_source") or ""))
        workspace_path = str(task.get("workspace_path") or "").strip()
        workflow = _normalize_workflow(str(task.get("workflow") or ""))
        version = int(task.get("version") or 1)
        run_id = str(run.get("id") or "")

        initial_state = {
            "task_id": task_id,
            "jira_key": jira_key,
            "pipeline_id": str(task.get("version") or "1"),
            "task_source": _normalize_task_source(str(task.get("task_source") or "")),
            "task_relation": str(task.get("task_relation") or PIPELINE_TASK_RELATION_TASK) if str(task.get("task_relation") or "").strip().lower() in PIPELINE_TASK_RELATIONS else PIPELINE_TASK_RELATION_TASK,
            "starting_git_branch_override": str(task.get("starting_git_branch_override") or "").strip(),
            "ticket_context": {},
            "workspace_path": str(task.get("workspace_path") or "").strip(),
            "plan": "",
            "sdd_bundle_path": "{}",
            "build_result": {},
            "review_passed": False,
            "review_reason": "",
            "git_result": {},
            "attempt": 0,
            "max_retries": get_shared_max_retries(),
            "status": "running",
            "failure_reason": None,
            "run_id": run_id,
        }
        graph_config = {"configurable": {"thread_id": task_id}}

        semaphore = self._graph_semaphore
        if semaphore is None:
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PIPELINE_TASKS)
            self._graph_semaphore = semaphore

        mark_agent_start(self.pipeline_agent_id)
        try:
            async with semaphore:
                await self.ticket_graph.ainvoke(initial_state, config=graph_config)
        except Exception as exc:
            error_msg = f"TicketPipelineGraph failed for {jira_key}: {self._format_exception(exc)}"

            self._log_agent_error(
                source_agent=self.pipeline_agent_id,
                error=error_msg,
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                context={"phase": "graph_dispatch"},
            )

            latest = get_pipeline_task(task_id) or {}
            latest_status = str(latest.get("status") or "").strip().lower()
            if latest_status == PIPELINE_STATUS_COMPLETE:
                add_pipeline_log(
                    level="warning",
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    message=(
                        "TicketPipelineGraph emitted a post-completion error; "
                        "preserving complete task state. "
                        + error_msg
                    ),
                )
                return

            await self._capture_pipeline_outcome_memory(
                jira_key=jira_key,
                task_source=task_source,
                workspace_path=workspace_path,
                workflow=workflow,
                success=False,
                version=version,
                attempt_count=0,
                max_retries=get_shared_max_retries(),
                codex_status="failed",
                codex_summary="TicketPipelineGraph dispatch failed before pipeline completion.",
                failure_reason=error_msg,
                task_id=task_id,
                run_id=run_id,
            )
            try:
                finalize_pipeline_run(
                    run_id,
                    status=PIPELINE_RUN_STATUS_FAILED,
                    attempt_count=0,
                    max_retries=get_shared_max_retries(),
                    attempts_failed=1,
                    attempts_completed=0,
                    current_activity="Graph dispatch failed.",
                    failure_reason=error_msg,
                )

                self._recover_task_to_queue(
                    task=task,
                    run_id=run_id,
                    reason=error_msg,
                    failure_code="graph_dispatch_failed",
                    bypass_source=PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
                    bypassed_by="system",
                    execution_state=PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                )
            except Exception as recovery_exc:
                self._log_agent_error(
                    source_agent=self.pipeline_agent_id,
                    error=f"Failed to recover {jira_key} after graph dispatch failure: {self._format_exception(recovery_exc)}",
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    context={"phase": "graph_dispatch_recovery"},
                )
        finally:
            mark_agent_end(self.pipeline_agent_id)
            set_pipeline_task_active_run(task_id, None)
            update_pipeline_heartbeat(last_heartbeat_at=datetime.now(timezone.utc).isoformat())

    async def _execute_task_run(self, task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        jira_key = _normalize_issue_key(str(task.get("jira_key") or ""))
        task_source = _normalize_task_source(str(task.get("task_source") or ""))
        task_relation = (
            str(task.get("task_relation") or PIPELINE_TASK_RELATION_TASK)
            if str(task.get("task_relation") or "").strip().lower() in PIPELINE_TASK_RELATIONS
            else PIPELINE_TASK_RELATION_TASK
        )
        is_spec_task = task_source == PIPELINE_TASK_SOURCE_SPEC
        version = int(task.get("version") or 1)
        workspace_path = str(task.get("workspace_path") or "").strip()
        workflow = PIPELINE_WORKFLOW
        starting_git_branch_override = str(task.get("starting_git_branch_override") or "").strip()
        git_workflow_key = "pipeline_spec" if is_spec_task else "pipeline"
        task_context_type = "pipeline_spec" if is_spec_task else "pipeline"

        if is_spec_task:
            details = self._build_spec_task_details(task, jira_key)
            sdd_bundle = self._resolve_existing_spec_bundle(
                task=task,
                workspace_path=workspace_path,
                spec_key=jira_key,
            )
            add_pipeline_log(
                level="info",
                task_id=str(task.get("id") or ""),
                run_id=str(run.get("id") or ""),
                jira_key=jira_key,
                message=f"Using curated SDD bundle for SPEC task {jira_key}.",
            )
        else:
            details = await self._fetch_jira_task_details(jira_key)
            attachment_download = await self._materialize_jira_attachments(
                workspace_path=workspace_path,
                jira_key=jira_key,
                details=details,
            )
            if attachment_download["warnings"]:
                existing_warnings = details.get("warnings") if isinstance(details.get("warnings"), list) else []
                details["warnings"] = [*existing_warnings, *attachment_download["warnings"]]
            if int(attachment_download.get("downloaded_count") or 0) > 0:
                add_pipeline_log(
                    level="info",
                    task_id=str(task.get("id") or ""),
                    run_id=str(run.get("id") or ""),
                    jira_key=jira_key,
                    message=(
                        f"Downloaded {attachment_download['downloaded_count']} Jira attachment(s) for {jira_key}"
                        + (
                            f" into {attachment_download['root_relative']}"
                            if str(attachment_download.get("root_relative") or "").strip()
                            else ""
                        )
                    ),
                )
            sdd_bundle = await self._delegate_to_sdd_spec_agent(
                jira_key=jira_key,
                version=version,
                workspace_path=workspace_path,
                details=details,
            )

        await self._attach_assist_brain_context(
            details=details,
            jira_key=jira_key,
            task_source=task_source,
            workspace_path=workspace_path,
            task_id=str(task.get("id") or ""),
            run_id=str(run.get("id") or ""),
        )

        ticket_summary = _ticket_name(details.get("ticket") if isinstance(details.get("ticket"), dict) else {})
        ticket_description = str(details.get("ticket", {}).get("summary") if isinstance(details.get("ticket"), dict) else "")
        planning_git_hook = await self._run_git_hook(
            stage_id="planning",
            workspace_path=workspace_path,
            context={
                "description": ticket_summary,
                "ticket": jira_key,
                "summary": ticket_description,
                "type": task_context_type,
            },
            workflow_key=git_workflow_key,
            starting_git_branch_override=starting_git_branch_override,
            task_id=str(task.get("id") or ""),
            run_id=str(run.get("id") or ""),
            jira_key=jira_key,
            task_relation=task_relation,
        )
        self._ensure_git_hook_succeeded(planning_git_hook)

        task_id = str(task.get("id") or "")
        run_id = str(run.get("id") or "")
        bypass = get_agent_bypass_settings()
        pipeline_settings = get_pipeline_settings()
        review_failure_mode = _normalize_review_failure_mode(
            str(pipeline_settings.get("review_failure_mode") or "")
        )
        max_retries = get_shared_max_retries()
        previous_runs = [
            item
            for item in list_pipeline_runs(task_id=task_id, limit=8)
            if str(item.get("id") or "") != run_id
        ]
        previous_failure_reason = ""
        for item in previous_runs:
            reason = str(item.get("failure_reason") or "").strip()
            if reason:
                previous_failure_reason = reason
                break

        feedback_items: list[str] = []
        if previous_failure_reason:
            feedback_items.append(
                "Previous pipeline failure to address while preserving original spec context:\n"
                f"{previous_failure_reason}"
            )

        codex_result: dict[str, str] = {
            "status": "failed",
            "summary": "",
            "error": "",
        }
        review_summary = ""
        failure_reason = ""
        success = False
        review_blocked = False
        attempt_count = 0
        attempts_failed = 0
        attempts_completed = 0
        attempt_summaries: list[str] = []

        for attempt in range(1, max_retries + 1):
            attempt_count = attempt
            attempt_review_state = "bypassed" if bool(bypass.get("code_review")) else "pending"
            update_pipeline_run_progress(
                run_id,
                attempt_count=attempt_count,
                max_retries=max_retries,
                attempts_failed=attempts_failed,
                attempts_completed=attempts_completed,
                current_activity=f"Attempt {attempt}/{max_retries}: building and validating",
            )
            add_pipeline_log(
                level="info",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f"Repair attempt {attempt}/{max_retries} started for {jira_key}.",
            )
            repair_feedback = "\n\n".join(_dedupe_lines(feedback_items)).strip()
            try:
                codex_result = await self._run_codex_builder(
                    workspace_path=workspace_path,
                    task_key=jira_key,
                    task_source=task_source,
                    sdd_bundle=sdd_bundle,
                    details=details,
                    repair_feedback=repair_feedback,
                    previous_failure_reason=previous_failure_reason,
                    attempt_number=attempt,
                    max_attempts=max_retries,
                )
            except Exception as exc:
                self._log_agent_error(
                    source_agent=self.code_builder_agent.agent_id or "Code Builder Codex",
                    error=self._format_exception(exc),
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    context={"stage": "build", "phase": "codex_exec", "attempt": attempt},
                )
                codex_result = {
                    "status": "failed",
                    "summary": "",
                    "error": self._format_exception(exc),
                }

            build_git_hook = await self._run_git_hook(
                stage_id="build",
                workspace_path=workspace_path,
                context={
                    "description": ticket_summary,
                    "ticket": jira_key,
                    "summary": str(codex_result.get("summary") or ""),
                    "type": task_context_type,
                },
                workflow_key=git_workflow_key,
                starting_git_branch_override=starting_git_branch_override,
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                task_relation=task_relation,
            )
            self._ensure_git_hook_succeeded(build_git_hook)

            success = codex_result["status"] == "success"
            failure_reason = str(codex_result.get("error") or "").strip()[:3000]
            review_summary = ""
            current_feedback: list[str] = []

            if codex_result["status"] != "success":
                current_feedback.append(
                    "Builder execution failed; resolve runtime/build/test blockers before retrying."
                )

            if not bool(bypass.get("code_review")):
                try:
                    review_payload = await run_code_review_with_codex(
                        workspace_path=workspace_path,
                        spec_paths=sdd_bundle,
                        build_output=str(codex_result.get("summary") or codex_result.get("error") or ""),
                        model=get_agent_model("code_review"),
                    )
                    review_passed = bool(review_payload.get("passed"))
                    attempt_review_state = "passed" if review_passed else "failed"
                    review_errors = [
                        str(item).strip()
                        for item in (review_payload.get("errors") or [])
                        if str(item).strip()
                    ]
                    review_summary = str(review_payload.get("summary") or "").strip()
                    add_pipeline_log(
                        level="info" if review_passed else "warning",
                        task_id=task_id,
                        run_id=run_id,
                        jira_key=jira_key,
                        message=(
                            "Code Review Agent validation passed."
                            if review_passed
                            else "Code Review Agent reported issues: " + "; ".join(review_errors[:5])
                        ),
                    )
                    if not review_passed:
                        review_failure_category = _classify_review_failure(review_errors, review_summary)
                        skip_review_failure = _should_skip_review_failure(
                            review_failure_mode,
                            review_failure_category,
                        )
                        review_report_path = self._write_review_failure_report(
                            workspace_path=workspace_path,
                            jira_key=jira_key,
                            task_id=task_id,
                            run_id=run_id,
                            version=version,
                            workflow=workflow,
                            mode=review_failure_mode,
                            category=review_failure_category,
                            skipped=skip_review_failure,
                            review_errors=review_errors,
                            review_summary=review_summary,
                        )
                        workspace_root = Path(workspace_path).expanduser().resolve()
                        report_relative_path = str(Path(review_report_path).resolve().relative_to(workspace_root))
                        if skip_review_failure:
                            skipped_task_updates = _mark_review_failures_in_tasks(
                                str(sdd_bundle.get("tasks_path") or ""),
                                review_errors,
                            )
                            note = (
                                "Code Review Agent issues were skipped by policy "
                                f"({review_failure_mode}, category={review_failure_category}). "
                                f"Failure report: {report_relative_path}."
                            )
                            if skipped_task_updates["marked"] or skipped_task_updates["added"]:
                                note += (
                                    " tasks.md updates: "
                                    f"marked={skipped_task_updates['marked']}, added={skipped_task_updates['added']}."
                                )
                            add_pipeline_log(
                                level="warning",
                                task_id=task_id,
                                run_id=run_id,
                                jira_key=jira_key,
                                message=note,
                            )
                            if codex_result["status"] == "success":
                                success = True
                                failure_reason = ""
                                review_blocked = False
                            codex_result["summary"] = (
                                str(codex_result.get("summary") or "") + "\n\n" + note
                            ).strip()
                        else:
                            review_blocked = True
                            success = False
                            if not failure_reason:
                                failure_reason = "; ".join(review_errors)[:3000] or "Code review validation failed."
                            add_pipeline_log(
                                level="error",
                                task_id=task_id,
                                run_id=run_id,
                                jira_key=jira_key,
                                message=(
                                    "Code Review Agent issues are blocking under the current policy "
                                    f"({review_failure_mode}, category={review_failure_category}). "
                                    f"Failure report: {report_relative_path}."
                                ),
                            )
                            current_feedback.append(
                                f"Code review blockers ({review_failure_category}): "
                                + ("; ".join(review_errors[:8]) or review_summary or "Unknown review issue.")
                            )
                    elif review_summary:
                        codex_result["summary"] = (str(codex_result.get("summary") or "") + "\n\n" + review_summary).strip()
                except Exception as exc:
                    attempt_review_state = "error"
                    review_blocked = True
                    success = False
                    failure_reason = self._format_exception(exc)[:3000]
                    add_pipeline_log(
                        level="error",
                        task_id=task_id,
                        run_id=run_id,
                        jira_key=jira_key,
                        message="Code Review Agent execution failed: " + failure_reason,
                    )
                    current_feedback.append(
                        "Code Review Agent execution failed; stabilize review path and address reported errors."
                    )
            else:
                add_pipeline_log(
                    level="info",
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    message="Code Review Agent bypass enabled for pipeline run.",
                )

            attempt_summaries.append(
                (
                    f"Attempt {attempt}/{max_retries}: "
                    f"builder={str(codex_result.get('status') or 'failed')}, "
                    f"review={attempt_review_state}, success={success}."
                )
            )
            if success:
                attempts_completed = 1
            else:
                attempts_failed += 1

            update_pipeline_run_progress(
                run_id,
                attempt_count=attempt_count,
                max_retries=max_retries,
                attempts_failed=attempts_failed,
                attempts_completed=attempts_completed,
                current_activity=(
                    f"Attempt {attempt}/{max_retries} passed review."
                    if success
                    else f"Attempt {attempt}/{max_retries} failed; awaiting retry."
                ),
            )
            if success:
                break
            if bool(bypass.get("code_builder")):
                break

            feedback_items.extend(current_feedback)
            if attempt < max_retries and not bool(bypass.get("code_builder")):
                add_pipeline_log(
                    level="warning",
                    task_id=task_id,
                    run_id=run_id,
                    jira_key=jira_key,
                    message=f"Attempt {attempt}/{max_retries} failed; retrying with review feedback.",
                )

        if attempt_summaries:
            codex_result["summary"] = (
                (str(codex_result.get("summary") or "").strip() + "\n\n" + "Repair loop summary:\n" + "\n".join(attempt_summaries))
            ).strip()

        if not success and not failure_reason:
            failure_reason = "Repair loop exhausted without reaching a passing review outcome."

        add_pipeline_log(
            level="info" if success else "warning",
            task_id=task_id,
            run_id=run_id,
            jira_key=jira_key,
            message=(
                f"Repair loop result: attempts_used={attempt_count}/{max_retries}, "
                f"running=0, completed={attempts_completed}, failed={attempts_failed}."
            ),
        )

        if success:
            review_git_hook = await self._run_git_hook(
                stage_id="review",
                workspace_path=workspace_path,
                context={
                    "description": ticket_summary,
                    "ticket": jira_key,
                    "summary": review_summary or str(codex_result.get("summary") or ""),
                    "type": task_context_type,
                },
                workflow_key=git_workflow_key,
                starting_git_branch_override=starting_git_branch_override,
                task_id=str(task.get("id") or ""),
                run_id=str(run.get("id") or ""),
                jira_key=jira_key,
                task_relation=task_relation,
            )
            self._ensure_git_hook_succeeded(review_git_hook)

        return {
            "success": success,
            "workflow": workflow,
            "attempt_count": attempt_count,
            "max_retries": max_retries,
            "attempts_running": 0,
            "attempts_failed": attempts_failed,
            "attempts_completed": attempts_completed,
            "review_blocked": review_blocked,
            # Backward-compatible pipeline run fields mapped to SDD artifacts.
            "brief_path": sdd_bundle["requirements_path"],
            "spec_path": sdd_bundle["design_path"],
            "task_path": sdd_bundle["tasks_path"],
            "requirements_path": sdd_bundle["requirements_path"],
            "design_path": sdd_bundle["design_path"],
            "tasks_path": sdd_bundle["tasks_path"],
            "codex_status": codex_result["status"],
            "codex_summary": codex_result.get("summary") or "",
            "failure_reason": failure_reason,
        }

    async def refresh_backlog(self) -> dict[str, Any]:
        latest_rows = list_jira_fetches(1)
        if latest_rows:
            latest = latest_rows[0]
            try:
                cached_tickets = json.loads(str(latest.get("tickets_json") or "[]"))
            except Exception:
                cached_tickets = []
            try:
                cached_kanban_columns = json.loads(str(latest.get("kanban_columns_json") or "[]"))
            except Exception:
                cached_kanban_columns = []
            refreshed = self.refresh_backlog_from_tickets(
                cached_tickets if isinstance(cached_tickets, list) else [],
                kanban_columns=cached_kanban_columns if isinstance(cached_kanban_columns, list) else [],
                fetched_at=str(latest.get("created_at") or ""),
            )
            if refreshed["count"] > 0:
                add_pipeline_log(level="info", message="Backlog refreshed from latest Jira fetch cache.")
                return refreshed

        spec_only_backlog = self.refresh_backlog_from_tickets(
            [],
            kanban_columns=[],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        if spec_only_backlog["count"] > 0:
            add_pipeline_log(level="info", message="Backlog refreshed from SPEC tasks.")
            return spec_only_backlog

        from app.settings_store import get_jira_settings
        stored = get_jira_settings()
        has_project_key = bool(str(stored.get("project_key") or "").strip())
        has_board_id = bool(str(stored.get("board_id") or "").strip())

        if not has_project_key or not has_board_id:
            add_pipeline_log(
                level="info",
                message="Skipping live Jira fetch — Project and Board not configured in Workflow Tasks.",
            )
            return {"count": 0}

        fetched = await self.jira_api_agent.fetch_backlog_tickets(self.workspace_root)
        refreshed = self.refresh_backlog_from_tickets(
            fetched.get("tickets") if isinstance(fetched.get("tickets"), list) else [],
            kanban_columns=fetched.get("kanban_columns") if isinstance(fetched.get("kanban_columns"), list) else [],
            fetched_at=str(fetched.get("fetched_at") or ""),
        )
        add_pipeline_log(level="info", message=f"Backlog refreshed with {refreshed['count']} pipeline task(s).")
        return refreshed

    @staticmethod
    def _latest_cached_jira_tickets() -> list[dict[str, Any]]:
        latest_rows = list_jira_fetches(1)
        if not latest_rows:
            return []
        latest = latest_rows[0]
        try:
            parsed = json.loads(str(latest.get("tickets_json") or "[]"))
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _latest_cached_kanban_columns() -> list[dict[str, Any]]:
        latest_rows = list_jira_fetches(1)
        if not latest_rows:
            return []
        latest = latest_rows[0]
        try:
            parsed = json.loads(str(latest.get("kanban_columns_json") or "[]"))
        except Exception:
            parsed = []
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

    def _sync_backlog_cache_from_latest_fetch(self) -> dict[str, Any]:
        latest_rows = list_jira_fetches(1)
        if latest_rows:
            latest = latest_rows[0]
            try:
                parsed_tickets = json.loads(str(latest.get("tickets_json") or "[]"))
            except Exception:
                parsed_tickets = []
            try:
                parsed_columns = json.loads(str(latest.get("kanban_columns_json") or "[]"))
            except Exception:
                parsed_columns = []
            tickets = parsed_tickets if isinstance(parsed_tickets, list) else []
            kanban_columns = parsed_columns if isinstance(parsed_columns, list) else []
            return self.refresh_backlog_from_tickets(
                tickets,
                kanban_columns=kanban_columns,
                fetched_at=str(latest.get("created_at") or ""),
            )

        return self.refresh_backlog_from_tickets(
            [],
            kanban_columns=[],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    def _set_spec_task_status_for_pipeline_task(
        self,
        *,
        task: dict[str, Any] | None,
        status: str,
        context: str,
        sync_backlog: bool = False,
    ) -> None:
        if not isinstance(task, dict):
            return

        if _normalize_task_source(str(task.get("task_source") or "")) != PIPELINE_TASK_SOURCE_SPEC:
            return

        spec_name = _normalize_issue_key(str(task.get("jira_key") or ""))
        if not spec_name:
            return

        workspace_path = str(task.get("workspace_path") or "").strip() or None
        task_id = str(task.get("id") or "")
        try:
            updated = set_spec_task_status(
                spec_name=spec_name,
                status=status,
                workspace_path=workspace_path,
            )
            if not updated:
                add_pipeline_log(
                    level="warning",
                    task_id=task_id or None,
                    jira_key=spec_name,
                    message=(
                        f"SPEC status update skipped for {spec_name}; no matching spec task row "
                        f"found during {context}."
                    ),
                )
                return

            add_pipeline_log(
                level="info",
                task_id=task_id or None,
                jira_key=spec_name,
                message=f"SPEC status set to {status} during {context}.",
            )
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            add_pipeline_log(
                level="warning",
                task_id=task_id or None,
                jira_key=spec_name,
                message=f"Failed to persist SPEC status for {spec_name} during {context}: {reason}",
            )
            return

        if not sync_backlog:
            return

        try:
            self._sync_backlog_cache_from_latest_fetch()
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            add_pipeline_log(
                level="warning",
                task_id=task_id or None,
                jira_key=spec_name,
                message=f"SPEC backlog sync failed after {context}: {reason}",
            )

    async def _move_completed_jira_ticket_to_selected_column(
        self,
        *,
        task: dict[str, Any],
        jira_key: str,
        task_id: str,
        run_id: str,
    ) -> None:
        target_column = str(task.get("jira_complete_column_name") or "").strip()
        if not target_column:
            return

        kanban_columns = self._latest_cached_kanban_columns()
        if not kanban_columns:
            add_pipeline_log(
                level="warning",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=(
                    f"Skipped Jira move for {jira_key}: no cached Jira board column metadata found. "
                    "Fetch Workflow Tasks to refresh kanban columns."
                ),
            )
            return

        try:
            transitioned = await self.jira_api_agent.transition_issue_to_board_column(
                issue_key=jira_key,
                column_name=target_column,
                kanban_columns=kanban_columns,
            )
            add_pipeline_log(
                level="info",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=(
                    f"Moved Jira ticket {jira_key} to board column "
                    f"{transitioned.get('column_name') or target_column} "
                    f"(status: {transitioned.get('to_status_name') or 'n/a'}) via Jira REST API."
                ),
            )
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            add_pipeline_log(
                level="warning",
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                message=f"Jira move failed for {jira_key} -> {target_column}: {reason}",
            )
            self._log_agent_error(
                source_agent=self.jira_api_agent.agent_id,
                error=reason,
                task_id=task_id,
                run_id=run_id,
                jira_key=jira_key,
                context={
                    "phase": "jira_complete_column_transition",
                    "target_column": target_column,
                },
            )

    def refresh_backlog_from_tickets(
        self,
        tickets: list[dict[str, Any]] | list[Any],
        *,
        kanban_columns: list[dict[str, Any]] | list[Any] | None = None,
        fetched_at: str | None = None,
    ) -> dict[str, Any]:
        filtered: list[dict[str, Any]] = []
        backlog_status_ids, backlog_status_names = _backlog_column_status_matchers(kanban_columns)
        seen_keys: set[str] = set()

        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue
            if not _is_top_level_task(ticket):
                continue
            if not _ticket_matches_backlog_column(ticket, backlog_status_ids, backlog_status_names):
                continue
            key = _normalize_issue_key(str(ticket.get("key") or ""))
            if not key:
                continue
            if key in seen_keys:
                continue

            payload_json = json.dumps(ticket, ensure_ascii=False)
            filtered.append(
                {
                    "key": key,
                    "summary": _ticket_name(ticket),
                    "issue_type": str(ticket.get("issue_type") or "Task"),
                    "status": str(ticket.get("status") or ""),
                    "priority": str(ticket.get("priority") or ""),
                    "assignee": str(ticket.get("assignee") or ""),
                    "updated": str(ticket.get("updated") or ""),
                    "payload_json": payload_json,
                    "task_source": PIPELINE_TASK_SOURCE_JIRA,
                    "task_reference": key,
                }
            )
            seen_keys.add(key)

        for spec_task in list_spec_tasks(limit=2000):
            if not isinstance(spec_task, dict):
                continue
            key = _normalize_issue_key(str(spec_task.get("spec_name") or ""))
            if not key or key in seen_keys:
                continue

            spec_status = str(spec_task.get("status") or "").strip().lower()
            if spec_status != SPEC_TASK_STATUS_PENDING:
                continue

            payload = {
                "source": PIPELINE_TASK_SOURCE_SPEC,
                "spec_name": str(spec_task.get("spec_name") or key),
                "workspace_path": str(spec_task.get("workspace_path") or ""),
                "spec_path": str(spec_task.get("spec_path") or ""),
                "requirements_path": str(spec_task.get("requirements_path") or ""),
                "design_path": str(spec_task.get("design_path") or ""),
                "tasks_path": str(spec_task.get("tasks_path") or ""),
                "summary": str(spec_task.get("summary") or ""),
                "status": spec_status,
                "parent_spec_name": str(spec_task.get("parent_spec_name") or ""),
                "parent_spec_task_id": str(spec_task.get("parent_spec_task_id") or ""),
                "dependency_mode": str(spec_task.get("dependency_mode") or "independent"),
                "depends_on": list(spec_task.get("depends_on") or []),
                "updated_at": str(spec_task.get("updated_at") or ""),
                "created_at": str(spec_task.get("created_at") or ""),
            }
            filtered.append(
                {
                    "key": key,
                    "summary": str(spec_task.get("summary") or f"SDD spec task for {key}"),
                    "issue_type": "Spec",
                    "status": "Pending",
                    "priority": "Spec",
                    "assignee": "",
                    "updated": str(spec_task.get("updated_at") or ""),
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                    "task_source": PIPELINE_TASK_SOURCE_SPEC,
                    "task_reference": key,
                }
            )
            seen_keys.add(key)

        normalized_fetched_at = str(fetched_at or datetime.now(timezone.utc).isoformat())
        replace_pipeline_backlog(filtered, normalized_fetched_at)
        return {
            "count": len(filtered),
            "fetched_at": normalized_fetched_at,
            "tickets": filtered,
        }

    def queue_ticket(
        self,
        jira_key: str,
        workspace_path: str,
        workflow: str,
        jira_complete_column_name: str | None = None,
        starting_git_branch_override: str | None = None,
        depends_on_task_ids: list[str] | None = None,
        task_relation: str | None = None,
    ) -> dict[str, Any]:
        normalized_workflow = _normalize_workflow(workflow)
        backlog_item = get_backlog_item(jira_key)
        if not backlog_item:
            raise RuntimeError(f"Pipeline task {jira_key} not found in backlog cache. Refresh backlog first.")

        task_source = _normalize_task_source(str(backlog_item.get("task_source") or ""))
        payload_json = str(backlog_item.get("payload_json") or "{}")
        parsed_payload: dict[str, Any] = {}
        try:
            raw_payload = json.loads(payload_json)
        except Exception:
            raw_payload = {}
        if isinstance(raw_payload, dict):
            parsed_payload = raw_payload
        resolved_workspace_path = str(workspace_path or "").strip()
        if not resolved_workspace_path and task_source == PIPELINE_TASK_SOURCE_SPEC:
            resolved_workspace_path = str(parsed_payload.get("workspace_path") or "").strip()

        title = str(backlog_item.get("title") or _normalize_issue_key(jira_key))
        task = queue_pipeline_task(
            jira_key=_normalize_issue_key(jira_key),
            task_source=task_source,
            task_relation=task_relation,
            title=title,
            workspace_path=resolved_workspace_path,
            jira_complete_column_name=jira_complete_column_name,
            starting_git_branch_override=starting_git_branch_override,
            workflow=normalized_workflow,
            jira_payload_json=payload_json,
        )

        if task_source == PIPELINE_TASK_SOURCE_SPEC:
            self._set_spec_task_status_for_pipeline_task(
                task=task,
                status=SPEC_TASK_STATUS_PENDING,
                context="queue",
                sync_backlog=True,
            )

        display_task_type = "SPEC task" if task_source == PIPELINE_TASK_SOURCE_SPEC else "Jira task"
        dependency_task_ids = depends_on_task_ids
        if dependency_task_ids is None and task_source == PIPELINE_TASK_SOURCE_SPEC:
            inferred_dependency_task_ids, unresolved_dependency_keys = self._resolve_spec_dependency_task_ids(
                task_id=str(task.get("id") or ""),
                payload=parsed_payload,
            )
            if inferred_dependency_task_ids:
                dependency_task_ids = inferred_dependency_task_ids
            if unresolved_dependency_keys:
                add_pipeline_log(
                    level="warning",
                    task_id=str(task.get("id") or ""),
                    jira_key=str(task.get("jira_key") or ""),
                    message=(
                        "SPEC dependency links are not yet queued in pipeline: "
                        + ", ".join(unresolved_dependency_keys)
                    ),
                )

        if dependency_task_ids is not None:
            self.set_task_dependencies(str(task.get("id") or ""), dependency_task_ids)
            task = get_pipeline_task(str(task.get("id") or "")) or task
        add_pipeline_log(
            level="info",
            task_id=str(task.get("id") or ""),
            jira_key=str(task.get("jira_key") or ""),
            message=(
                f"Queued {display_task_type} {task.get('jira_key')} in Task Queue with workspace "
                f"{task.get('workspace_path')} (workflow={task.get('workflow') or normalized_workflow})"
                + (
                    f", jira_complete_column={task.get('jira_complete_column_name')}"
                    if str(task.get("jira_complete_column_name") or "").strip()
                    else ""
                )
                + (
                    f", starting_git_branch_override={task.get('starting_git_branch_override')}"
                    if str(task.get("starting_git_branch_override") or "").strip()
                    else ""
                )
                + "."
            ),
        )
        return task

    def move_task(
        self,
        task_id: str,
        target_status: str,
        workspace_path: str | None = None,
        workflow: str | None = None,
        jira_complete_column_name: str | None = None,
        starting_git_branch_override: str | None = None,
        depends_on_task_ids: list[str] | None = None,
        task_relation: str | None = None,
    ) -> dict[str, Any]:
        existing = get_pipeline_task(task_id)
        if not existing:
            raise RuntimeError("Pipeline task not found")
        normalized_status = str(target_status or "").strip().lower()
        resolved_status = (
            PIPELINE_STATUS_CURRENT
            if normalized_status in {PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED}
            else normalized_status
        )
        current_status = str(existing.get("status") or "").strip().lower()
        is_spec_task = _normalize_task_source(str(existing.get("task_source") or "")) == PIPELINE_TASK_SOURCE_SPEC
        increment = False
        if resolved_status == PIPELINE_STATUS_CURRENT:
            increment = (
                current_status in {PIPELINE_STATUS_COMPLETE, PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED}
                or bool(int(existing.get("is_bypassed") or 0))
                or str(existing.get("execution_state") or "").strip().lower() != PIPELINE_TASK_EXECUTION_STATE_READY
                or bool(str(existing.get("failure_reason") or "").strip())
            )
            if not workspace_path:
                workspace_path = str(existing.get("workspace_path") or "")
            if not workflow:
                workflow = str(existing.get("workflow") or PIPELINE_WORKFLOW)

        move_kwargs: dict[str, Any] = {
            "workspace_path": workspace_path,
            "jira_complete_column_name": jira_complete_column_name,
            "starting_git_branch_override": starting_git_branch_override,
            "workflow": workflow,
            "task_relation": task_relation,
            "increment_version": increment,
        }
        if normalized_status == PIPELINE_STATUS_STOPPED:
            move_kwargs.update(
                {
                    "failure_reason": "Stopped by user.",
                    "is_bypassed": True,
                    "bypass_reason": "Stopped by user.",
                    "bypass_source": PIPELINE_BYPASS_SOURCE_MANUAL,
                    "bypassed_by": "user",
                    "is_dependency_blocked": False,
                    "dependency_block_reason": "",
                    "execution_state": PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED,
                    "last_failure_code": "manual_stop_requested",
                }
            )
        elif normalized_status == PIPELINE_STATUS_FAILED:
            move_kwargs.update(
                {
                    "failure_reason": str(existing.get("failure_reason") or "").strip() or "Task failed.",
                    "is_bypassed": True,
                    "bypass_reason": str(existing.get("failure_reason") or "").strip() or "Task failed.",
                    "bypass_source": PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
                    "bypassed_by": "system",
                    "is_dependency_blocked": False,
                    "dependency_block_reason": "",
                    "execution_state": PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                    "last_failure_code": "task_failed",
                }
            )
        elif resolved_status == PIPELINE_STATUS_CURRENT:
            move_kwargs.update(
                {
                    "failure_reason": "",
                    "is_bypassed": False,
                    "bypass_reason": "",
                    "bypass_source": PIPELINE_BYPASS_SOURCE_MANUAL,
                    "bypassed_by": "",
                    "is_dependency_blocked": False,
                    "dependency_block_reason": "",
                    "execution_state": PIPELINE_TASK_EXECUTION_STATE_READY,
                    "last_failure_code": "",
                }
            )

        moved = move_pipeline_task(
            task_id,
            target_status=resolved_status,
            **move_kwargs,
        )
        if not moved:
            raise RuntimeError("Failed to move pipeline task")

        add_pipeline_log(
            level="info",
            task_id=task_id,
            jira_key=str(moved.get("jira_key") or ""),
            message=(
                f"Moved {moved.get('jira_key')} to {resolved_status}"
                + (
                    f" (workflow={moved.get('workflow')})"
                    if resolved_status == PIPELINE_STATUS_CURRENT
                    else ""
                )
                + (
                    f" (jira_complete_column={moved.get('jira_complete_column_name')})"
                    if resolved_status == PIPELINE_STATUS_CURRENT and str(moved.get("jira_complete_column_name") or "").strip()
                    else ""
                )
                + (
                    f" (starting_git_branch_override={moved.get('starting_git_branch_override')})"
                    if resolved_status == PIPELINE_STATUS_CURRENT and str(moved.get("starting_git_branch_override") or "").strip()
                    else ""
                )
                + "."
            ),
        )

        if is_spec_task:
            next_spec_status = SPEC_TASK_STATUS_PENDING
            if normalized_status == PIPELINE_STATUS_COMPLETE:
                next_spec_status = SPEC_TASK_STATUS_COMPLETE
            elif normalized_status in {PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED}:
                next_spec_status = SPEC_TASK_STATUS_FAILED
            elif resolved_status == PIPELINE_STATUS_BACKLOG:
                if current_status == PIPELINE_STATUS_COMPLETE:
                    next_spec_status = SPEC_TASK_STATUS_COMPLETE
                elif current_status in {PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED}:
                    next_spec_status = SPEC_TASK_STATUS_FAILED
                else:
                    next_spec_status = SPEC_TASK_STATUS_PENDING

            self._set_spec_task_status_for_pipeline_task(
                task=moved,
                status=next_spec_status,
                context=f"move:{normalized_status or resolved_status}",
                sync_backlog=True,
            )

        dependency_task_ids = depends_on_task_ids
        if dependency_task_ids is None and is_spec_task and resolved_status == PIPELINE_STATUS_CURRENT:
            payload_json = str(moved.get("jira_payload_json") or "{}")
            parsed_payload: dict[str, Any] = {}
            try:
                raw_payload = json.loads(payload_json)
            except Exception:
                raw_payload = {}
            if isinstance(raw_payload, dict):
                parsed_payload = raw_payload
            inferred_dependency_task_ids, unresolved_dependency_keys = self._resolve_spec_dependency_task_ids(
                task_id=task_id,
                payload=parsed_payload,
            )
            if inferred_dependency_task_ids:
                dependency_task_ids = inferred_dependency_task_ids
            if unresolved_dependency_keys:
                add_pipeline_log(
                    level="warning",
                    task_id=task_id,
                    jira_key=str(moved.get("jira_key") or ""),
                    message=(
                        "SPEC dependency links are not yet queued in pipeline: "
                        + ", ".join(unresolved_dependency_keys)
                    ),
                )

        if dependency_task_ids is not None:
            self.set_task_dependencies(task_id, dependency_task_ids)
            moved = get_pipeline_task(task_id) or moved

        return moved

    def reorder_current(self, ordered_task_ids: list[str]) -> None:
        reorder_current_pipeline_tasks(ordered_task_ids)
        add_pipeline_log(level="info", message="Updated Task Queue pipeline ordering.")

    def update_settings(
        self,
        *,
        active_window_start: str | None,
        active_window_end: str | None,
        heartbeat_interval_minutes: int | None,
        automation_enabled: bool | None = None,
        max_retries: int | None = None,
        review_failure_mode: str | None = None,
    ) -> dict[str, Any]:
        start = _normalize_window_time(active_window_start or "", DEFAULT_ACTIVE_WINDOW_START)
        end = _normalize_window_time(active_window_end or "", DEFAULT_ACTIVE_WINDOW_END)
        interval = int(heartbeat_interval_minutes or DEFAULT_HEARTBEAT_INTERVAL_MINUTES)
        interval = max(MIN_HEARTBEAT_INTERVAL_MINUTES, interval)
        mode = _normalize_review_failure_mode(review_failure_mode) if review_failure_mode is not None else None
        updated = update_pipeline_settings(
            active_window_start=start,
            active_window_end=end,
            heartbeat_interval_minutes=interval,
            automation_enabled=automation_enabled,
            max_retries=max_retries,
            review_failure_mode=mode,
        )
        # Reset heartbeat scheduling so new settings are applied immediately on next poll.
        update_pipeline_heartbeat(last_heartbeat_at="", last_cycle_at="", next_heartbeat_override_at="")
        add_pipeline_log(
            level="info",
            message=(
                f"Pipeline settings updated: window {start}-{end}, "
                "heartbeat "
                f"{interval} minutes, review_failure_mode="
                f"{updated.get('review_failure_mode') or DEFAULT_REVIEW_FAILURE_MODE}, "
                f"max_retries={int(updated.get('max_retries') or get_shared_max_retries())}. "
                f"automation_enabled={bool(int(updated.get('automation_enabled') or 0))}. "
                "Heartbeat timer reset."
            ),
        )
        return updated

    def trigger_heartbeat_soon(self, delay_seconds: int = 10) -> dict[str, Any]:
        delay = max(0, min(int(delay_seconds or 0), 300))
        trigger_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        update_pipeline_heartbeat(next_heartbeat_override_at=trigger_at)
        add_pipeline_log(
            level="info",
            message=f"Manual heartbeat scheduled for {trigger_at} (in {delay}s).",
        )
        return {
            "scheduled": True,
            "delay_seconds": delay,
            "next_heartbeat_override_at": trigger_at,
        }

    async def _run_manual_cycle_once(self) -> None:
        if not self._cycle_lock:
            self._cycle_lock = asyncio.Lock()

        if self._cycle_lock.locked():
            add_pipeline_log(
                level="warning",
                message="Manual trigger ignored because a pipeline cycle is already running.",
            )
            return

        if has_running_pipeline_task():
            add_pipeline_log(
                level="warning",
                message="Manual trigger ignored because a pipeline task is already running.",
            )
            return

        mark_agent_start(self.pipeline_heartbeat_id)
        try:
            update_pipeline_heartbeat(
                last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
                next_heartbeat_override_at="",
            )
            async with self._cycle_lock:
                await self._run_cycle()
        finally:
            mark_agent_end(self.pipeline_heartbeat_id)

    def trigger_next_task_now(self) -> dict[str, Any]:
        if not self.started or self._loop is None:
            raise RuntimeError("Pipeline heartbeat is not running")

        def schedule_cycle() -> None:
            if not self._loop:
                return
            self._loop.create_task(self._run_manual_cycle_once())

        self._loop.call_soon_threadsafe(schedule_cycle)
        add_pipeline_log(level="info", message="Manual next-task trigger accepted.")
        return {"queued": True}

    def admin_force_reset_spec_task(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeError("task_id is required")

        existing = get_pipeline_task(normalized_task_id)
        if not existing:
            raise RuntimeError("Pipeline task not found")

        if _normalize_task_source(str(existing.get("task_source") or "")) != PIPELINE_TASK_SOURCE_SPEC:
            raise RuntimeError("Force reset is only supported for SPEC tasks")

        reset_task = reset_pipeline_task_runtime(
            normalized_task_id,
            clear_dependencies=True,
            clear_task_logs=False,
        )
        if not reset_task:
            raise RuntimeError("Failed to reset pipeline task")

        self._set_spec_task_status_for_pipeline_task(
            task=reset_task,
            status=SPEC_TASK_STATUS_PENDING,
            context="admin:force-reset",
            sync_backlog=True,
        )
        add_pipeline_log(
            level="warning",
            task_id=normalized_task_id,
            jira_key=str(reset_task.get("jira_key") or ""),
            message="Admin force reset applied. Task moved back to Task Queue and runtime state cleared.",
        )
        return get_pipeline_task(normalized_task_id) or reset_task

    def admin_force_complete_task(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeError("task_id is required")

        existing = get_pipeline_task(normalized_task_id)
        if not existing:
            raise RuntimeError("Pipeline task not found")

        current_status = str(existing.get("status") or "").strip().lower()
        if current_status != PIPELINE_STATUS_CURRENT:
            raise RuntimeError("Force complete can only be applied to Task Queue cards")

        moved = move_pipeline_task(
            normalized_task_id,
            target_status=PIPELINE_STATUS_COMPLETE,
            increment_version=False,
            failure_reason="",
            is_bypassed=False,
            bypass_reason="",
            bypass_source=PIPELINE_BYPASS_SOURCE_MANUAL,
            bypassed_by="user",
            is_dependency_blocked=False,
            dependency_block_reason="",
            execution_state=PIPELINE_TASK_EXECUTION_STATE_READY,
            last_failure_code="admin_force_complete",
        )
        if not moved:
            raise RuntimeError("Failed to mark pipeline task complete")

        self._set_spec_task_status_for_pipeline_task(
            task=moved,
            status=SPEC_TASK_STATUS_COMPLETE,
            context="admin:force-complete",
            sync_backlog=True,
        )
        add_pipeline_log(
            level="warning",
            task_id=normalized_task_id,
            jira_key=str(moved.get("jira_key") or ""),
            message="Admin marked task as complete from Task Queue.",
        )
        return moved

    def snapshot_state(self) -> dict[str, Any]:
        settings = get_pipeline_settings()
        tasks = list_pipeline_tasks()
        runs = list_pipeline_runs(limit=300)
        logs = list_pipeline_logs(limit=500)
        backlog = list_pipeline_backlog(limit=600)
        dependencies = list_pipeline_task_dependencies()
        handoffs = list_pipeline_git_handoffs(limit=1000)

        runs_by_task: dict[str, list[dict[str, Any]]] = {}
        for run in runs:
            task_id = str(run.get("task_id") or "")
            if not task_id:
                continue
            runs_by_task.setdefault(task_id, []).append(run)

        logs_by_task: dict[str, list[dict[str, Any]]] = {}
        for log in logs:
            task_id = str(log.get("task_id") or "")
            if not task_id:
                continue
            logs_by_task.setdefault(task_id, []).append(log)

        dependencies_by_task: dict[str, list[dict[str, Any]]] = {}
        dependents_by_task: dict[str, list[str]] = {}
        for dependency in dependencies:
            dependency_task_id = str(dependency.get("task_id") or "")
            depends_on_task_id = str(dependency.get("depends_on_task_id") or "")
            if dependency_task_id:
                dependencies_by_task.setdefault(dependency_task_id, []).append(dependency)
            if depends_on_task_id and dependency_task_id:
                dependents_by_task.setdefault(depends_on_task_id, []).append(dependency_task_id)

        task_meta_by_id: dict[str, dict[str, Any]] = {
            str(task.get("id") or ""): task
            for task in tasks
            if str(task.get("id") or "")
        }

        active_pipeline_statuses = {PIPELINE_STATUS_CURRENT, PIPELINE_STATUS_RUNNING}
        inactive_task_ids = {
            task_id
            for task_id, task in task_meta_by_id.items()
            if str(task.get("status") or "").strip().lower() not in active_pipeline_statuses
        }

        unresolved_handoffs: list[dict[str, Any]] = []
        unresolved_handoffs_by_task: dict[str, list[dict[str, Any]]] = {}
        for handoff in handoffs:
            task_id = str(handoff.get("task_id") or "")
            if not task_id:
                continue
            resolved = bool(int(handoff.get("resolved") or 0))
            if resolved:
                continue
            task_meta = task_meta_by_id.get(task_id, {})
            enriched = dict(handoff)
            enriched["task_status"] = str(task_meta.get("status") or "")
            enriched["task_is_bypassed"] = bool(int(task_meta.get("is_bypassed") or 0))
            unresolved_handoffs_by_task.setdefault(task_id, []).append(enriched)
            if task_id not in inactive_task_ids:
                unresolved_handoffs.append(enriched)

        mapped_tasks: list[dict[str, Any]] = []
        for task in tasks:
            payload_text = str(task.get("jira_payload_json") or "{}")
            try:
                jira_payload = json.loads(payload_text)
            except Exception:
                jira_payload = {}
            item = dict(task)
            raw_status = str(item.get("status") or "").strip().lower()
            if raw_status in {PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED}:
                item["status"] = PIPELINE_STATUS_CURRENT
                if str(item.get("execution_state") or "").strip().lower() not in {
                    PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
                    PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED,
                }:
                    item["execution_state"] = (
                        PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED
                        if raw_status == PIPELINE_STATUS_STOPPED
                        else PIPELINE_TASK_EXECUTION_STATE_BLOCKED
                    )
                if not bool(int(item.get("is_bypassed") or 0)):
                    item["is_bypassed"] = 1
                if not str(item.get("last_failure_code") or "").strip():
                    item["last_failure_code"] = (
                        "manual_stop_requested"
                        if raw_status == PIPELINE_STATUS_STOPPED
                        else "task_failed"
                    )
            item["jira_payload"] = jira_payload if isinstance(jira_payload, dict) else {}
            item["runs"] = runs_by_task.get(str(task.get("id") or ""), [])[:30]
            item["logs"] = logs_by_task.get(str(task.get("id") or ""), [])[:120]
            item["dependencies"] = dependencies_by_task.get(str(task.get("id") or ""), [])
            item["dependent_task_ids"] = dependents_by_task.get(str(task.get("id") or ""), [])
            item["unresolved_handoffs"] = unresolved_handoffs_by_task.get(str(task.get("id") or ""), [])
            item["unresolved_handoff_count"] = len(item["unresolved_handoffs"])
            mapped_tasks.append(item)

        columns = {
            "current": [item for item in mapped_tasks if str(item.get("status") or "") == PIPELINE_STATUS_CURRENT],
            "running": [item for item in mapped_tasks if str(item.get("status") or "") == PIPELINE_STATUS_RUNNING],
            "complete": [item for item in mapped_tasks if str(item.get("status") or "") == PIPELINE_STATUS_COMPLETE],
        }
        columns["current"].sort(key=lambda item: int(item.get("order_index") or 0))

        backlog_items: list[dict[str, Any]] = []
        for row in backlog:
            payload_text = str(row.get("payload_json") or "{}")
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = {}
            backlog_items.append(
                {
                    "key": str(row.get("jira_key") or ""),
                    "task_source": _normalize_task_source(str(row.get("task_source") or "")),
                    "task_reference": str(row.get("task_reference") or row.get("jira_key") or ""),
                    "title": str(row.get("title") or ""),
                    "issue_type": str(row.get("issue_type") or ""),
                    "status": str(row.get("status") or ""),
                    "priority": str(row.get("priority") or ""),
                    "assignee": str(row.get("assignee") or ""),
                    "updated": str(row.get("updated") or ""),
                    "fetched_at": str(row.get("fetched_at") or ""),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )

        heartbeat = self._heartbeat_snapshot(settings)

        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "settings": {
                "active_window_start": heartbeat["active_window_start"],
                "active_window_end": heartbeat["active_window_end"],
                "heartbeat_interval_minutes": heartbeat["heartbeat_interval_minutes"],
                "automation_enabled": bool(int(settings.get("automation_enabled") or 0)),
                "max_retries": int(settings.get("max_retries") or get_shared_max_retries()),
                "review_failure_mode": str(settings.get("review_failure_mode") or DEFAULT_REVIEW_FAILURE_MODE),
                "last_heartbeat_at": heartbeat["last_heartbeat_at"],
                "last_cycle_at": heartbeat["last_cycle_at"],
            },
            "heartbeat": heartbeat,
            "columns": columns,
            "backlog": backlog_items,
            "handoffs": {
                "unresolved_count": len(unresolved_handoffs),
                "unresolved": unresolved_handoffs[:200],
            },
        }

    def _heartbeat_snapshot(self, settings: dict[str, Any]) -> dict[str, Any]:
        now_local = datetime.now().astimezone()
        start_text = _normalize_window_time(
            str(settings.get("active_window_start") or ""),
            DEFAULT_ACTIVE_WINDOW_START,
        )
        end_text = _normalize_window_time(
            str(settings.get("active_window_end") or ""),
            DEFAULT_ACTIVE_WINDOW_END,
        )
        start_minutes = _time_to_minutes(start_text)
        end_minutes = _time_to_minutes(end_text)
        active = _is_within_window(now_local, start_minutes, end_minutes)

        interval_minutes = int(settings.get("heartbeat_interval_minutes") or DEFAULT_HEARTBEAT_INTERVAL_MINUTES)
        interval_minutes = max(MIN_HEARTBEAT_INTERVAL_MINUTES, interval_minutes)
        automation_enabled = bool(int(settings.get("automation_enabled") or 0))
        has_running_task = has_running_pipeline_task()

        if has_running_task:
            return {
                "active_window_start": _minutes_to_time(start_minutes),
                "active_window_end": _minutes_to_time(end_minutes),
                "heartbeat_interval_minutes": interval_minutes,
                "active_window_state": "active" if active else "inactive",
                "is_active": active,
                "next_heartbeat_at": "",
                "countdown_seconds": 0,
                "last_heartbeat_at": str(settings.get("last_heartbeat_at") or ""),
                "last_cycle_at": str(settings.get("last_cycle_at") or ""),
            }

        last_heartbeat_at = _parse_iso_datetime(str(settings.get("last_heartbeat_at") or ""))
        next_heartbeat_override_at = _parse_iso_datetime(str(settings.get("next_heartbeat_override_at") or ""))
        if not automation_enabled and next_heartbeat_override_at is None:
            return {
                "active_window_start": _minutes_to_time(start_minutes),
                "active_window_end": _minutes_to_time(end_minutes),
                "heartbeat_interval_minutes": interval_minutes,
                "active_window_state": "inactive",
                "is_active": False,
                "next_heartbeat_at": "",
                "countdown_seconds": 0,
                "last_heartbeat_at": str(settings.get("last_heartbeat_at") or ""),
                "last_cycle_at": str(settings.get("last_cycle_at") or ""),
            }

        next_heartbeat_at: datetime
        if active:
            next_due_at = _next_heartbeat_due_at(
                now_local=now_local,
                interval_minutes=interval_minutes,
                last_heartbeat_at=last_heartbeat_at,
                next_override_at=next_heartbeat_override_at,
            )
            if next_due_at is None:
                next_heartbeat_at = now_local
            else:
                next_heartbeat_at = max(next_due_at, now_local)
        else:
            next_heartbeat_at = _next_window_start(now_local, start_minutes, end_minutes)

        countdown_seconds = max(0, int((next_heartbeat_at - now_local).total_seconds()))
        return {
            "active_window_start": _minutes_to_time(start_minutes),
            "active_window_end": _minutes_to_time(end_minutes),
            "heartbeat_interval_minutes": interval_minutes,
            "active_window_state": "active" if active else "inactive",
            "is_active": active,
            "next_heartbeat_at": next_heartbeat_at.astimezone(timezone.utc).isoformat(),
            "countdown_seconds": countdown_seconds,
            "last_heartbeat_at": str(settings.get("last_heartbeat_at") or ""),
            "last_cycle_at": str(settings.get("last_cycle_at") or ""),
        }

    async def _fetch_jira_task_details(self, jira_key: str) -> dict[str, Any]:
        key = _normalize_issue_key(jira_key)
        config = load_mcp_config(self.workspace_root)
        tooling = config.tooling.get("jira") if config and config.tooling else {}
        jira_tooling = tooling if isinstance(tooling, dict) else {}
        backlog_url = str(jira_tooling.get("backlog_url") or "").strip()
        try:
            max_results = int(str(jira_tooling.get("max_results") or "100"))
        except Exception:
            max_results = 100

        parent_ticket: dict[str, Any] | None = None
        subtasks: list[dict[str, Any]] = []
        warnings: list[str] = []

        try:
            self.jira_api_agent._validate_env()
        except Exception as exc:
            warnings.append(
                "Direct Jira REST detail fetch skipped: "
                + (str(exc).strip() or type(exc).__name__)
            )
        else:
            timeout = httpx.Timeout(20.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                try:
                    parent_ticket = await self.jira_api_agent._get_issue(
                        client,
                        key,
                        backlog_url,
                        include_activity=True,
                    )
                except Exception as exc:
                    warnings.append(
                        f"Direct Jira REST issue fetch failed for {key}: {str(exc).strip() or type(exc).__name__}."
                    )

                if parent_ticket:
                    try:
                        subtask_keys = await self.jira_api_agent._find_subtask_keys(
                            client,
                            [key],
                            backlog_url,
                            max_results,
                        )
                        if subtask_keys:
                            subtask_results = await asyncio.gather(
                                *[
                                    self.jira_api_agent._get_issue(
                                        client,
                                        subtask_key,
                                        backlog_url,
                                        include_activity=True,
                                    )
                                    for subtask_key in subtask_keys
                                ],
                                return_exceptions=True,
                            )
                            for subtask_key, result in zip(subtask_keys, subtask_results, strict=False):
                                if isinstance(result, Exception):
                                    warnings.append(
                                        "Direct Jira REST subtask fetch failed for "
                                        f"{subtask_key}: {str(result).strip() or type(result).__name__}."
                                    )
                                    continue
                                subtasks.append(result)
                    except Exception as exc:
                        warnings.append(
                            f"Direct Jira REST subtask lookup failed for {key}: {str(exc).strip() or type(exc).__name__}."
                        )

        if not parent_ticket:
            tickets = self._latest_cached_jira_tickets()
            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue
                if _normalize_issue_key(str(ticket.get("key") or "")) == key:
                    parent_ticket = ticket
                    break
            if parent_ticket and not subtasks:
                subtasks = [
                    ticket
                    for ticket in tickets
                    if isinstance(ticket, dict)
                    and _normalize_issue_key(str(ticket.get("parent_key") or "")) == key
                ]
            if parent_ticket:
                warnings.append("Fell back to the latest cached Jira fetch for ticket details.")

        if not parent_ticket:
            backlog = await self.jira_api_agent.fetch_backlog_tickets(self.workspace_root)
            tickets = backlog.get("tickets") if isinstance(backlog.get("tickets"), list) else []
            for ticket in tickets:
                if not isinstance(ticket, dict):
                    continue
                if _normalize_issue_key(str(ticket.get("key") or "")) == key:
                    parent_ticket = ticket
                    break
            if parent_ticket and not subtasks:
                subtasks = [
                    ticket
                    for ticket in tickets
                    if isinstance(ticket, dict)
                    and _normalize_issue_key(str(ticket.get("parent_key") or "")) == key
                ]
            warnings.append("Fell back to a fresh Jira backlog fetch for ticket details.")

        if not parent_ticket:
            raise RuntimeError(f"Unable to fetch Jira task details for {key}.")

        subtasks_sorted = sorted(
            [ticket for ticket in subtasks if isinstance(ticket, dict)],
            key=lambda item: _normalize_issue_key(str(item.get("key") or "")),
        )
        return {
            "ticket": parent_ticket,
            "subtasks": subtasks_sorted,
            "warnings": _dedupe_lines(warnings),
        }

    @staticmethod
    def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
        payload_text = str(task.get("jira_payload_json") or "{}")
        try:
            payload = json.loads(payload_text)
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _build_spec_task_details(self, task: dict[str, Any], spec_key: str) -> dict[str, Any]:
        payload = self._task_payload(task)
        spec_name = str(payload.get("spec_name") or spec_key).strip() or spec_key
        summary = str(payload.get("summary") or task.get("title") or "").strip() or f"SDD spec task for {spec_name}"
        workspace_path = str(payload.get("workspace_path") or task.get("workspace_path") or "").strip()
        ticket = {
            "key": spec_name,
            "summary": summary,
            "status": str(payload.get("status") or "Ready"),
            "priority": str(payload.get("priority") or "Spec"),
            "description": summary,
        }
        return {
            "ticket": ticket,
            "subtasks": [],
            "warnings": [],
            "spec": {
                "spec_name": spec_name,
                "workspace_path": workspace_path,
                "spec_path": str(payload.get("spec_path") or ""),
                "requirements_path": str(payload.get("requirements_path") or ""),
                "design_path": str(payload.get("design_path") or ""),
                "tasks_path": str(payload.get("tasks_path") or ""),
            },
        }

    def _resolve_existing_spec_bundle(
        self,
        *,
        task: dict[str, Any],
        workspace_path: str,
        spec_key: str,
    ) -> dict[str, str]:
        payload = self._task_payload(task)
        spec_name = str(payload.get("spec_name") or spec_key).strip() or spec_key
        explicit_requirements = str(payload.get("requirements_path") or "").strip()
        explicit_design = str(payload.get("design_path") or "").strip()
        explicit_tasks = str(payload.get("tasks_path") or "").strip()

        if explicit_requirements and explicit_design and explicit_tasks:
            requirements_path = Path(explicit_requirements).expanduser().resolve()
            design_path = Path(explicit_design).expanduser().resolve()
            tasks_path = Path(explicit_tasks).expanduser().resolve()
            if requirements_path.exists() and design_path.exists() and tasks_path.exists():
                return {
                    "requirements_path": str(requirements_path),
                    "design_path": str(design_path),
                    "tasks_path": str(tasks_path),
                }

        candidate_dirs: list[Path] = []
        spec_path = str(payload.get("spec_path") or "").strip()
        if spec_path:
            candidate_dirs.append(Path(spec_path).expanduser().resolve())

        workspace_root = Path(workspace_path).expanduser().resolve()
        candidate_dirs.append((workspace_root / ".assist" / "specs" / spec_name).resolve())

        payload_workspace = str(payload.get("workspace_path") or "").strip()
        if payload_workspace:
            payload_workspace_root = Path(payload_workspace).expanduser().resolve()
            candidate_dirs.append((payload_workspace_root / ".assist" / "specs" / spec_name).resolve())

        for candidate_dir in candidate_dirs:
            requirements_path = (candidate_dir / "requirements.md").resolve()
            design_path = (candidate_dir / "design.md").resolve()
            tasks_path = (candidate_dir / "tasks.md").resolve()
            if requirements_path.exists() and design_path.exists() and tasks_path.exists():
                return {
                    "requirements_path": str(requirements_path),
                    "design_path": str(design_path),
                    "tasks_path": str(tasks_path),
                }

        raise RuntimeError(
            f"Curated SDD bundle files were not found for {spec_name}. "
            "Add the spec from Create A Spec and ensure requirements.md, design.md, and tasks.md exist."
        )

    async def _delegate_to_sdd_spec_agent(
        self,
        *,
        jira_key: str,
        version: int,
        workspace_path: str,
        details: dict[str, Any],
    ) -> dict[str, str]:
        if not sdd_spec_agent_enabled():
            return self._write_sdd_bundle(
                jira_key=jira_key,
                version=version,
                workspace_path=workspace_path,
                details=details,
            )

        bypass = get_agent_bypass_settings()
        if bool(bypass.get("sdd_spec")):
            return self._write_sdd_bundle(
                jira_key=jira_key,
                version=version,
                workspace_path=workspace_path,
                details=details,
            )

        ticket = details.get("ticket") if isinstance(details.get("ticket"), dict) else {}
        subtasks = details.get("subtasks") if isinstance(details.get("subtasks"), list) else []
        ticket_context = TicketContext.from_jira_ticket(ticket, ticket_key=jira_key)
        if str(details.get("attachment_root_relative") or "").strip():
            ticket_context.agent_context = _dedupe_lines(
                [*ticket_context.agent_context, f"Local Jira attachments root: {details['attachment_root_relative']}"]
            )

        subtask_lines = [
            f"- {_normalize_issue_key(str(item.get('key') or ''))}: {_ticket_name(item)}"
            for item in subtasks
            if isinstance(item, dict)
        ]
        task_prompt_lines = [
            f"Implement Jira ticket {jira_key}: {_ticket_name(ticket)}",
            "Use the parent ticket requirements and subtask breakdown.",
        ]
        if subtask_lines:
            task_prompt_lines.extend(["Subtasks:", *subtask_lines])
        task_prompt = "\n".join(task_prompt_lines)

        output_dir = str(
            Path(workspace_path).expanduser().resolve() / ".assist" / "pipeline" / jira_key / f"v{version}"
        )
        try:
            spec_result = await run_sdd_spec_agent(
                task_prompt=task_prompt,
                ticket_context=ticket_context,
                workspace_path=workspace_path,
                output_dir=output_dir,
                model=self.sdd_spec_model,
            )
            if str(spec_result.get("status") or "").strip().lower() != "success":
                raise RuntimeError(str(spec_result.get("error") or "unknown SDD Spec Agent failure"))
            return {
                "requirements_path": str(spec_result.get("requirements_path") or ""),
                "design_path": str(spec_result.get("design_path") or ""),
                "tasks_path": str(spec_result.get("tasks_path") or ""),
            }
        except Exception as exc:
            add_pipeline_log(
                level="warning",
                jira_key=jira_key,
                message=(
                    "Falling back to Pipeline Agent SDD bundle generation after SDD Spec Agent failure: "
                    + (str(exc).strip() or type(exc).__name__)
                ),
            )
            return self._write_sdd_bundle(
                jira_key=jira_key,
                version=version,
                workspace_path=workspace_path,
                details=details,
            )

    def _write_sdd_bundle(
        self,
        *,
        jira_key: str,
        version: int,
        workspace_path: str,
        details: dict[str, Any],
    ) -> dict[str, str]:
        workspace_root = Path(workspace_path).expanduser().resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        out_dir = workspace_root / ".assist" / "pipeline" / jira_key / f"v{version}"
        out_dir.mkdir(parents=True, exist_ok=True)

        ticket = details.get("ticket") if isinstance(details.get("ticket"), dict) else {}
        subtasks = details.get("subtasks") if isinstance(details.get("subtasks"), list) else []
        attachment_root_relative = str(details.get("attachment_root_relative") or "").strip()
        parent_outline = _ticket_outline(ticket)
        parent_attachments = _attachments_for_ticket(ticket)

        subtask_rows: list[str] = []
        subtask_sections: list[str] = []
        checklist_items = [f"- [ ] {jira_key}: {_ticket_name(ticket)}"]
        attachment_sections: list[str] = []

        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            sub_key = _normalize_issue_key(str(subtask.get("key") or ""))
            sub_title = _ticket_name(subtask)
            sub_status = str(subtask.get("status") or "").strip() or "n/a"
            sub_attachments = _attachments_for_ticket(subtask)
            sub_outline = _ticket_outline(subtask)

            subtask_rows.append(
                f"| {sub_key or '-'} | {sub_title} | {sub_status} | {len(sub_attachments)} |"
            )
            checklist_items.append(f"- [ ] {sub_key}: {sub_title}")

            section_lines = [
                f"### {sub_key}: {sub_title}",
                f"- Status: {sub_status}",
                f"- Outcome: {sub_outline['summary']}",
            ]
            deliverables = sub_outline["requirements"] or sub_outline["details"]
            if deliverables:
                section_lines.append("- Deliverables:")
                section_lines.extend([f"  - {line}" for line in deliverables[:3]])
            done_when = sub_outline["acceptance"]
            if done_when:
                section_lines.append("- Done when:")
                section_lines.extend([f"  - {line}" for line in done_when[:2]])
            subtask_sections.append("\n".join(section_lines))

            if sub_attachments:
                attachment_sections.append(f"### {sub_key} Attachments")
                attachment_sections.extend([_format_attachment_reference(attachment) for attachment in sub_attachments])

        if len(checklist_items) == 1:
            checklist_items.append("- [ ] Validate implementation with available project checks")

        functional_requirements = parent_outline["requirements"] or parent_outline["details"]
        if not functional_requirements:
            functional_requirements = [
                _ticket_name(subtask)
                for subtask in subtasks
                if isinstance(subtask, dict)
            ]
        functional_requirements = _compact_lines(functional_requirements, limit=10)
        acceptance_criteria = parent_outline["acceptance"]
        if not acceptance_criteria:
            acceptance_criteria = _compact_lines(
                [
                    line
                    for subtask in subtasks
                    if isinstance(subtask, dict)
                    for line in _ticket_outline(subtask)["acceptance"]
                ],
                limit=8,
            )

        agent_context_lines = parent_outline["agent_context"]
        if attachment_root_relative and not any(attachment_root_relative in line for line in agent_context_lines):
            agent_context_lines = [
                *agent_context_lines,
                f"Local Jira attachments root: {attachment_root_relative}",
            ]
        if not agent_context_lines:
            agent_context_lines = [f"Workspace root: {workspace_root}"]

        agent_prompt_lines = parent_outline["agent_prompt"]
        if not agent_prompt_lines:
            agent_prompt_lines = [
                f"Implement Jira task {jira_key} in `{workspace_root}`.",
                "Use the requirements, design, and tasks files as the working contract.",
            ]

        assumptions: list[str] = []
        if not parent_outline["details"] and not parent_outline["requirements"]:
            assumptions.append("The parent ticket description was sparse, so the scope is inferred from the summary and subtasks.")
        if not subtasks:
            assumptions.append("No Jira subtasks were returned, so the checklist only tracks the parent task.")
        if not assumptions:
            assumptions.append("Any remaining ambiguity should be resolved with conservative implementation choices and documented in the final output.")

        requirements_lines = [
            "# Requirements",
            "",
            "## Context",
            f"- Jira Key: {jira_key}",
            f"- Title: {_ticket_name(ticket)}",
            f"- Status: {str(ticket.get('status') or 'n/a')}",
            f"- Priority: {str(ticket.get('priority') or 'n/a')}",
            f"- Workspace: {workspace_root}",
            f"- Version: v{version}",
            "",
            "## Objective",
            f"- {parent_outline['summary']}",
        ]
        if parent_outline["details"]:
            requirements_lines.extend([f"- {line}" for line in parent_outline["details"][1:3]])

        requirements_lines.extend(["", "## Functional Requirements"])
        if functional_requirements:
            for index, requirement in enumerate(functional_requirements, start=1):
                requirements_lines.append(f"{index}. {requirement}")
        else:
            requirements_lines.append("1. Implement the parent Jira task using the subtask breakdown in tasks.md.")

        requirements_lines.extend(["", "## Acceptance Criteria"])
        if acceptance_criteria:
            for index, criterion in enumerate(acceptance_criteria, start=1):
                requirements_lines.append(f"{index}. {criterion}")
        else:
            requirements_lines.append("1. The implementation matches the Jira ticket intent and passes the available project checks.")

        requirements_lines.extend(["", "## Task Breakdown"])
        if subtask_rows:
            requirements_lines.extend(
                [
                    "| Key | Title | Status | Attachments |",
                    "| --- | --- | --- | --- |",
                    *subtask_rows,
                ]
            )
        else:
            requirements_lines.append(f"- {jira_key}: {_ticket_name(ticket)}")

        warnings = details.get("warnings") if isinstance(details.get("warnings"), list) else []
        if warnings:
            requirements_lines.extend(["", "## Jira Retrieval Notes"])
            requirements_lines.extend([f"- {str(item)}" for item in warnings if str(item).strip()])

        requirements_lines.extend(["", "## Assumptions"])
        requirements_lines.extend([f"- {item}" for item in assumptions])

        design_lines = [
            "# Design",
            "",
            "## Delivery Approach",
            f"- Start with the parent ticket `{jira_key}` and then complete each subtask in key order.",
            "- Keep the implementation local to the affected route, components, styling, and supporting assets.",
            "- Avoid duplicating work already captured in the parent ticket requirements or agent guidance.",
            "",
            "## Execution Order",
            f"### {jira_key}: {_ticket_name(ticket)}",
            f"- Outcome: {parent_outline['summary']}",
        ]
        if parent_outline["requirements"]:
            design_lines.append("- Key requirements:")
            design_lines.extend([f"  - {line}" for line in parent_outline["requirements"][:4]])

        if subtask_sections:
            design_lines.extend(["", "## Subtask Plan", *subtask_sections])
        else:
            design_lines.extend(["", "## Subtask Plan", "No Jira subtasks were available for this task."])

        design_lines.extend(["", "## Agent Context"])
        design_lines.extend([f"- {line}" for line in agent_context_lines])

        design_lines.extend(["", "## Agent Prompt"])
        design_lines.extend([f"- {line}" for line in agent_prompt_lines])

        design_lines.extend(["", "## Attachment Inventory"])
        if parent_attachments:
            design_lines.append(f"### {jira_key} Parent Attachments")
            design_lines.extend([_format_attachment_reference(attachment) for attachment in parent_attachments])
        if attachment_sections:
            design_lines.extend(attachment_sections)
        if not parent_attachments and not attachment_sections:
            design_lines.append("No Jira attachments were available for this task.")

        if attachment_root_relative:
            design_lines.extend(
                [
                    "",
                    "## Local Attachment Access",
                    f"Downloaded Jira attachments are available under `{attachment_root_relative}` within the workspace.",
                ]
            )

        design_lines.extend(["", "## Ambiguity Handling"])
        design_lines.append("If implementation details remain ambiguous, apply reasonable assumptions and document them in execution output.")

        tasks_lines = [
            "# Tasks",
            "",
            "## Implementation Checklist",
            *checklist_items,
            "",
            "## Validation",
            "- [ ] Run project build/lint/test commands where available",
            "- [ ] Verify all affected files compile and meet task scope",
            "- [ ] Document assumptions made during implementation",
            "",
            "## Constraints",
            f"- Execute autonomously for Jira task {jira_key}",
            "- Start with the parent task before moving through subtasks",
            "- Do not block on clarifying questions",
            "- Capture assumptions and continue execution",
        ]

        requirements_path = out_dir / "requirements.md"
        design_path = out_dir / "design.md"
        tasks_path = out_dir / "tasks.md"
        requirements_path.write_text("\n".join(requirements_lines).strip() + "\n", encoding="utf-8")
        design_path.write_text("\n".join(design_lines).strip() + "\n", encoding="utf-8")
        tasks_path.write_text("\n".join(tasks_lines).strip() + "\n", encoding="utf-8")

        return {
            "requirements_path": str(requirements_path),
            "design_path": str(design_path),
            "tasks_path": str(tasks_path),
        }

    async def _run_codex_builder(
        self,
        *,
        workspace_path: str,
        task_key: str,
        task_source: str,
        sdd_bundle: dict[str, str],
        details: dict[str, Any],
        repair_feedback: str = "",
        previous_failure_reason: str = "",
        attempt_number: int = 1,
        max_attempts: int = 1,
    ) -> dict[str, str]:
        normalized_task_source = _normalize_task_source(task_source)
        is_spec_task = normalized_task_source == PIPELINE_TASK_SOURCE_SPEC
        task_label = "SPEC task" if is_spec_task else "Jira task"

        bypass = get_agent_bypass_settings()
        if bool(bypass["code_builder"]):
            return {
                "status": "success",
                "summary": (
                    f"Code Builder Codex bypass enabled. Skipped Codex execution for {task_label} {task_key} "
                    "and passed pipeline task to result processing."
                ),
                "error": "",
            }

        workspace_root = Path(workspace_path).expanduser().resolve()
        if not workspace_root.exists():
            workspace_root.mkdir(parents=True, exist_ok=True)

        subtasks = details.get("subtasks") if isinstance(details.get("subtasks"), list) else []
        task_summary_header = _ticket_name(details.get("ticket") if isinstance(details.get("ticket"), dict) else {})
        attachment_root_relative = str(details.get("attachment_root_relative") or "").strip()
        task_summary_lines = [f"- {task_key}: {task_summary_header}"]
        if not is_spec_task:
            task_summary_lines.extend(
                [
                    f"- {_normalize_issue_key(str(item.get('key') or ''))}: {_ticket_name(item)}"
                    for item in subtasks
                    if isinstance(item, dict)
                ]
            )
        task_summary = "\n".join([line for line in task_summary_lines if str(line).strip()])
        if not task_summary:
            task_summary = f"- {task_key}"

        attachment_prompt = ""
        if not is_spec_task and attachment_root_relative:
            attachment_prompt = (
                "Local Jira attachments:\n"
                f"- Root: {attachment_root_relative}\n"
                "- Review the downloaded local attachment files when the ticket references images or other assets.\n\n"
            )

        assist_brain_context = str(details.get("assist_brain_context") or "").strip()
        assist_brain_prompt = ""
        if assist_brain_context:
            assist_brain_prompt = (
                "Assist Brain prior context (use this before planning edits):\n"
                f"{assist_brain_context[:_ASSIST_BRAIN_CONTEXT_MAX_CHARS]}\n\n"
            )

        spec_bundle_note = (
            "This run uses a curated SDD bundle selected by the user. "
            "Do not generate or overwrite requirements.md, design.md, or tasks.md; use them as fixed input context.\n\n"
            if is_spec_task
            else ""
        )
        normalized_repair_feedback = str(repair_feedback or "").strip()
        normalized_previous_failure_reason = str(previous_failure_reason or "").strip()
        additional_repair_context = ""
        if normalized_previous_failure_reason:
            additional_repair_context += (
                "Previous failure context (address this while preserving original spec intent):\n"
                f"{normalized_previous_failure_reason[:3000]}\n\n"
            )
        if normalized_repair_feedback:
            additional_repair_context += (
                "Additional review-driven fixes (additive to the original spec scope):\n"
                f"{normalized_repair_feedback[:5000]}\n\n"
            )

        prompt = (
            "You are Code Builder Codex running inside an autonomous pipeline task.\n"
            f"{AUTONOMY_RULE}\n\n"
            f"{CODE_BUILDER_WORKSPACE_RULES}\n"
            f"{build_codex_skills_prompt()}"
            f"{task_label}: {task_key}\n"
            f"Workspace: {workspace_root}\n"
            f"Requirements file: {sdd_bundle['requirements_path']}\n"
            f"Design file: {sdd_bundle['design_path']}\n"
            f"Tasks file: {sdd_bundle['tasks_path']}\n\n"
            f"{spec_bundle_note}"
            f"Attempt: {attempt_number}/{max(1, max_attempts)}\n"
            "Subtask coverage:\n"
            f"{task_summary}\n\n"
            f"{attachment_prompt}"
            f"{assist_brain_prompt}"
            f"{additional_repair_context}"
            "Execution requirements:\n"
            "- Implement the requested changes end-to-end in this workspace.\n"
            "- Run required setup/build/lint/test commands where applicable.\n"
            "- Treat requirements.md, design.md, and tasks.md as the primary implementation contract and source of truth.\n"
            "- Keep the original task context intact; apply repair feedback only as additional constraints.\n"
            "- If assumptions are required, document them explicitly in your final message.\n"
            "- Do not ask clarifying questions.\n"
            "- Keep running until task is complete or a hard blocker occurs.\n"
        )

        result = await asyncio.to_thread(
            run_codex_exec,
            prompt,
            workspace_root,
            self.code_builder_agent.model,
            CODEX_TIMEOUT_SECONDS,
            agent_id=self.code_builder_agent.agent_id or make_agent_id("agents", "Code Builder Codex"),
        )

        combined = (
            f"command: {result.command}\n"
            f"exit_code: {result.exit_code}\n"
            f"duration_ms: {result.duration_ms}\n\n"
            f"last_message:\n{result.last_message}\n\n"
            f"stderr:\n{result.stderr}\n"
        )
        if result.exit_code == 0:
            return {
                "status": "success",
                "summary": combined[:12000],
                "error": "",
            }
        return {
            "status": "failed",
            "summary": combined[:12000],
            "error": (result.stderr or result.last_message or f"Codex exit code {result.exit_code}")[:3000],
        }

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        text = str(exc).strip()
        if text:
            return text
        return f"{type(exc).__name__}: {repr(exc)}"


__all__ = ["PipelineEngine"]
