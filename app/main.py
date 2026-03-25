from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import shutil
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

import httpx
from dotenv import load_dotenv

# Load .env automatically for local development before agent clients initialize.
load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent_registry import AgentDefinition, build_agent_snapshot, make_agent_id, register_agent, register_agent_listener
from app.agents_sdd_planner.sdd_planner_agent import SDDPlannerAgent, normalize_spec_name
from app.assist_brain_memory import capture_assist_brain_sync
from app.fs_browser import (
    create_directory,
    delete_empty_directory,
    list_directory,
    list_tree_columns,
    rename_entry,
    search_tree_entries,
)
from app.db import (
    SPEC_TASK_STATUS_PENDING,
    add_jira_fetch,
    add_message,
    add_chat_attachment,
    add_orchestrator_event,
    conversation_messages,
    list_conversations,
    create_task,
    delete_conversations,
    ensure_conversation,
    init_db,
    list_orchestrator_events,
    list_orchestrator_events_since,
    list_orchestrator_tasks,
    list_jira_fetches,
    list_chat_attachments,
    list_tasks,
    seed_tasks_if_empty,
    update_task_status,
    list_workspaces,
    create_workspace,
    update_workspace,
    delete_workspace,
    set_active_workspace,
    get_active_workspace_config,
    set_active_workspace_config,
    list_workspace_projects,
    create_workspace_project,
    update_workspace_project,
    delete_workspace_project,
    SPEC_TASK_STATUS_GENERATING,
    SPEC_TASK_STATUS_GENERATED,
    create_generating_spec_task,
    mark_spec_task_generated,
    promote_spec_task_to_pending,
    get_spec_task_by_name,
    set_spec_task_status,
    delete_spec_task_by_id,
    list_spec_tasks,
    upsert_spec_task,
    update_spec_task_dependencies as update_spec_task_dependencies_in_db,
)
from app.db_client import get_conn, init_pool, release_conn, reset_pool, validate_database_config
from app.connection_monitor import connection_monitor
from app.agents_git import GitAgent
from app.agents_jira_api import JiraApiAgent
from app.agents_slack import SlackAgent
from app.agents_workspace.agent import WorkspaceAgent
from app.agents_orchestrator.runtime import OrchestratorEngine
from app.graphs.checkpointer import close_checkpointer, get_checkpointer
from app.graphs.chat.graph import build_chat_graph
from app.graphs.spec_pipeline.graph import build_spec_pipeline_graph
from app.graphs.ticket_pipeline.graph import build_ticket_pipeline_graph
from app.llm import LLMClient
from app.mcp_client import MCPClient, load_mcp_config
from app.workflows import workflow_list
from app.agents_pipeline import PipelineEngine
from app.pipeline_store import MIN_HEARTBEAT_INTERVAL_MINUTES, ensure_pipeline_schema, list_pipeline_logs, list_pipeline_logs_since
from app.ticket_context import TicketContext
from app.settings_store import (
    ensure_settings_file_exists,
    get_agent_bypass_settings,
    get_vision_settings,
    set_agent_bypass_settings,
    get_github_settings,
    get_github_token,
    get_github_username,
    update_github_settings,
    get_gitlab_settings,
    get_gitlab_token,
    get_gitlab_url,
    get_gitlab_username,
    update_gitlab_settings,
    get_git_workflow_settings,
    update_git_workflow_settings,
    get_jira_settings,
    update_jira_settings,
)
from app.stitch_service import (
    StitchServiceError,
    download_workspace_screen_assets,
    generate_workspace_screens,
    link_workspace_project,
    load_workspace_design_system,
    list_workspace_screens,
    stitch_workspace_status,
)

app = FastAPI(title="Multi-Agent Personal Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator_engine = OrchestratorEngine()
sdd_planner_agent = SDDPlannerAgent()
git_agent = GitAgent()
workspace_agent = WorkspaceAgent()
jira_api_agent = JiraApiAgent(registry_mode="agents")
slack_agent = SlackAgent()
pipeline_engine = PipelineEngine()
provider_health_client = LLMClient()
static_dir = Path(__file__).resolve().parent.parent / "static"
_has_static = static_dir.exists()
if _has_static:
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
chat_images_dir = Path(__file__).resolve().parent / "images"
chat_images_dir.mkdir(parents=True, exist_ok=True)

_provider_health_cache: dict[str, object] | None = None
_provider_health_cache_at: datetime | None = None
_provider_health_cache_ttl = timedelta(seconds=30)
_provider_health_fetch_timeout_seconds = float(os.getenv("PROVIDER_HEALTH_FETCH_TIMEOUT_SECONDS", "3"))
_mcp_startup_report: dict[str, object] | None = None
_available_tickets_cache: list[dict[str, object]] | None = None
_available_tickets_cache_at: datetime | None = None
_shutdown_streams = threading.Event()
_shutdown_signal_handlers_installed = False
_previous_signal_handlers: dict[int, object] = {}


def _install_shutdown_signal_handlers() -> None:
    global _shutdown_signal_handlers_installed
    if _shutdown_signal_handlers_installed:
        return

    def _handle_shutdown_signal(signum: int, _frame: object) -> None:
        _shutdown_streams.set()
        previous = _previous_signal_handlers.get(signum)
        if callable(previous):
            previous(signum, _frame)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            _previous_signal_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _handle_shutdown_signal)
        except Exception:
            continue

    _shutdown_signal_handlers_installed = True


def _stream_shutdown_requested() -> bool:
    return _shutdown_streams.is_set()
_available_tickets_cache_ttl = timedelta(minutes=5)
_ticket_details_cache: dict[str, tuple[datetime, dict[str, object]]] = {}
_ticket_details_cache_ttl = timedelta(minutes=10)


def _normalize_ticket_key(value: str) -> str:
    return str(value or "").strip().upper()


def _dedupe_ticket_keys(keys: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in keys:
        key = _normalize_ticket_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _safe_json_loads(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _cached_jira_tickets(limit_fetches: int = 5) -> list[dict[str, object]]:
    rows = list_jira_fetches(max(1, min(limit_fetches, 25)))
    ticket_by_key: dict[str, dict[str, object]] = {}
    for row in rows:
        raw = str(row.get("tickets_json") or "[]")
        tickets = _safe_json_loads(raw, [])
        if not isinstance(tickets, list):
            continue
        for item in tickets:
            if not isinstance(item, dict):
                continue
            key = _normalize_ticket_key(str(item.get("key") or ""))
            if not key:
                continue
            existing = ticket_by_key.get(key)
            if not existing:
                ticket_by_key[key] = item
                continue
            for field in ("summary", "status", "priority", "assignee", "updated", "description", "attachments", "url"):
                if not existing.get(field) and item.get(field):
                    existing[field] = item[field]
    return list(ticket_by_key.values())


def _ticket_available_item(ticket: dict[str, object], source: str) -> dict[str, object]:
    return {
        "key": _normalize_ticket_key(str(ticket.get("key") or "")),
        "title": str(ticket.get("summary") or ticket.get("title") or "Untitled Jira task"),
        "status": str(ticket.get("status") or ""),
        "priority": str(ticket.get("priority") or ""),
        "assignee": str(ticket.get("assignee") or ""),
        "updated": str(ticket.get("updated") or ""),
        "source": source,
    }


async def _fetch_ticket_from_jira(ticket_key: str, workspace_root: Path) -> dict[str, object] | None:
    key = _normalize_ticket_key(ticket_key)
    if not key:
        return None

    try:
        jira_api_agent._validate_env()
    except Exception:
        return None

    try:
        config = load_mcp_config(workspace_root)
        tooling = config.tooling.get("jira") if config and config.tooling else {}
        jira_tooling = tooling if isinstance(tooling, dict) else {}
        backlog_url = str(jira_tooling.get("backlog_url") or "").strip()

        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            ticket = await jira_api_agent._get_issue(
                client,
                key,
                backlog_url,
                include_activity=True,
            )
            return ticket if isinstance(ticket, dict) else None
    except Exception:
        return None


async def _load_ticket_by_key(ticket_key: str, workspace_root: Path) -> dict[str, object] | None:
    key = _normalize_ticket_key(ticket_key)
    if not key:
        return None

    cached_entry = _ticket_details_cache.get(key)
    now = datetime.now(timezone.utc)
    if cached_entry and now - cached_entry[0] < _ticket_details_cache_ttl:
        return cached_entry[1]

    for ticket in _cached_jira_tickets(limit_fetches=10):
        if _normalize_ticket_key(str(ticket.get("key") or "")) == key:
            payload = dict(ticket)
            _ticket_details_cache[key] = (now, payload)
            return payload

    ticket = await _fetch_ticket_from_jira(key, workspace_root)
    if ticket:
        payload = dict(ticket)
        _ticket_details_cache[key] = (now, payload)
        return payload

    return None


async def _available_tickets_cached(workspace_root: Path) -> list[dict[str, object]]:
    global _available_tickets_cache, _available_tickets_cache_at

    now = datetime.now(timezone.utc)
    if _available_tickets_cache is not None and _available_tickets_cache_at is not None:
        if now - _available_tickets_cache_at < _available_tickets_cache_ttl:
            return _available_tickets_cache

    deduped: dict[str, dict[str, object]] = {}
    for ticket in _cached_jira_tickets(limit_fetches=5):
        item = _ticket_available_item(ticket, "jira_cache")
        key = str(item.get("key") or "")
        if key:
            deduped[key] = item

    if not deduped:
        try:
            backlog = pipeline_engine.snapshot_state().get("backlog")
            rows = backlog if isinstance(backlog, list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = _normalize_ticket_key(str(row.get("jira_key") or ""))
                if not key:
                    continue
                deduped[key] = {
                    "key": key,
                    "title": str(row.get("title") or "Untitled Jira task"),
                    "status": str(row.get("status") or ""),
                    "priority": str(row.get("priority") or ""),
                    "assignee": str(row.get("assignee") or ""),
                    "updated": str(row.get("updated") or ""),
                    "source": "pipeline_backlog",
                }
        except Exception:
            pass

    items = sorted(
        deduped.values(),
        key=lambda item: (str(item.get("key") or ""), str(item.get("title") or "")),
    )
    _available_tickets_cache = items
    _available_tickets_cache_at = now
    return items


def _ticket_to_context_payload(ticket: dict[str, object]) -> dict[str, object]:
    context = TicketContext.from_jira_ticket(ticket)
    return {
        "ticket_key": context.ticket_key,
        "title": context.title,
        "status": str(ticket.get("status") or ""),
        "priority": str(ticket.get("priority") or ""),
        "url": str(ticket.get("url") or ""),
        "ticket": ticket,
        "ticket_context": context.to_dict(),
    }


async def _load_selected_ticket_contexts(
    selected_ticket_keys: list[str],
    workspace_root: Path,
) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for key in _dedupe_ticket_keys(selected_ticket_keys):
        try:
            ticket = await _load_ticket_by_key(key, workspace_root)
        except Exception:
            ticket = None
        if not ticket:
            continue
        contexts.append(_ticket_to_context_payload(ticket))
    return contexts


def _safe_attachment_extension(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix and len(suffix) <= 10 and all(ch.isalnum() or ch == "." for ch in suffix):
        return suffix
    if content_type:
        normalized = content_type.lower().strip()
        if normalized == "image/png":
            return ".png"
        if normalized in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if normalized == "image/gif":
            return ".gif"
        if normalized == "image/webp":
            return ".webp"
        if normalized == "image/svg+xml":
            return ".svg"
    return ".bin"


def _persist_chat_attachments(
    conversation_id: str,
    message_event_id: str | None,
    files: list[UploadFile],
) -> list[dict[str, str | int]]:
    saved: list[dict[str, str | int]] = []
    for index, upload in enumerate(files):
        filename = (upload.filename or f"attachment-{index + 1}").strip() or f"attachment-{index + 1}"
        extension = _safe_attachment_extension(filename, upload.content_type)
        stamp = int(time.time() * 1000)
        stored_name = f"{conversation_id}-{stamp}-{index}{extension}"
        target = chat_images_dir / stored_name
        payload = upload.file.read()
        target.write_bytes(payload)
        record = add_chat_attachment(
            conversation_id=conversation_id,
            message_event_id=message_event_id,
            original_name=filename,
            stored_name=stored_name,
            stored_path=str(target),
            mime_type=(upload.content_type or "application/octet-stream"),
            size_bytes=len(payload),
        )
        saved.append(record)
    return saved


def _serialize_attachment(attachment: dict[str, object]) -> dict[str, object]:
    attachment_id = str(attachment.get("id") or "")
    return {
        "id": attachment_id,
        "message_event_id": str(attachment.get("message_event_id") or ""),
        "original_name": str(attachment.get("original_name") or ""),
        "mime_type": str(attachment.get("mime_type") or "application/octet-stream"),
        "size_bytes": int(attachment.get("size_bytes") or 0),
        "created_at": str(attachment.get("created_at") or ""),
        "url": f"/api/chat/attachments/{attachment_id}" if attachment_id else "",
    }


def _build_attachment_context(
    conversation_id: str,
    new_attachments: list[dict[str, str | int]],
    image_summaries: list[str] | None = None,
) -> str:
    history = list_chat_attachments(conversation_id, limit=12)
    if not new_attachments and not history:
        return ""
    lines = [
        "Attachment context for this conversation:",
    ]
    if new_attachments:
        lines.append("New attachments included with this message:")
        for attachment in new_attachments:
            lines.append(
                "- "
                f"{attachment.get('original_name', 'attachment')} "
                f"(mime={attachment.get('mime_type', 'unknown')}, "
                f"bytes={attachment.get('size_bytes', 0)}, "
                f"path={attachment.get('stored_path', '')})"
            )
    if history:
        lines.append("Recent chat attachments in this conversation:")
        for attachment in history:
            lines.append(
                "- "
                f"{attachment.get('original_name', 'attachment')} "
                f"(stored={attachment.get('stored_name', '')}, "
                f"path={attachment.get('stored_path', '')})"
            )
    if image_summaries:
        lines.append("Image analysis summaries:")
        lines.extend(f"- {summary}" for summary in image_summaries if summary.strip())
    lines.append("Use these files as context when relevant to the user's request across all workflows.")
    return "\n".join(lines)


async def _summarize_uploaded_images(
    attachments: list[dict[str, str | int]],
) -> list[str]:
    if not attachments:
        return []

    settings = get_vision_settings()
    max_images = int(settings["max_images_per_turn"])
    max_bytes = int(settings["max_image_bytes"])
    per_image_timeout_seconds = float(settings["timeout_seconds"])
    vision_model = str(settings["model"] or "").strip()
    image_attachments = [
        attachment
        for attachment in attachments
        if str(attachment.get("mime_type") or "").lower().startswith("image/")
    ][: max(0, max_images)]

    if not image_attachments:
        return []

    summaries: list[str] = []
    for attachment in image_attachments:
        name = str(attachment.get("original_name") or "image")
        stored_path = str(attachment.get("stored_path") or "").strip()
        if not stored_path:
            continue
        try:
            image_bytes = Path(stored_path).read_bytes()
            if len(image_bytes) > max_bytes:
                summaries.append(f"{name}: skipped analysis (file too large).")
                continue
            description = await asyncio.wait_for(
                provider_health_client.openai_vision_response(
                    prompt=(
                        "Describe this image for an engineering assistant. "
                        "Focus on visible UI elements, text, states, errors, and likely user intent. "
                        "Keep it concise."
                    ),
                    image_bytes=image_bytes,
                    mime_type=str(attachment.get("mime_type") or "image/png"),
                    model=vision_model,
                ),
                timeout=per_image_timeout_seconds,
            )
            if description.strip():
                summaries.append(f"{name}: {description.strip()}")
        except Exception as exc:
            summaries.append(f"{name}: image analysis unavailable ({str(exc).strip() or 'unknown error'}).")
    return summaries


chat_graph = None
spec_graph = None

_active_graph_tasks: dict[str, asyncio.Task] = {}


def _truncate_error_text(value: str, limit: int = 1800) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unknown error."
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _finalize_chat_graph_task(conversation_id: str, task: asyncio.Task) -> None:
    _active_graph_tasks.pop(conversation_id, None)

    if task.cancelled():
        reply = "Stopped by user request."
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent="Orchestrator Agent",
            event_type="turn_cancelled",
            content="Execution stopped by user request.",
        )
        add_message(conversation_id, role="assistant", agent="Orchestrator Agent", content=reply)
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent="Orchestrator Agent",
            event_type="assistant_message",
            content=reply,
        )
        return

    error = task.exception()
    if error is None:
        return

    error_text = _truncate_error_text(str(error))
    reply = f"Sorry — I hit an internal error while processing that request: {error_text}"
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent="Orchestrator Agent",
        event_type="turn_error",
        content=error_text,
    )
    add_message(conversation_id, role="assistant", agent="Orchestrator Agent", content=reply)
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent="Orchestrator Agent",
        event_type="assistant_message",
        content=reply,
    )


def _build_chat_initial_state(
    *,
    conversation_id: str,
    user_message: str,
    workspace_root: str | None,
    secondary_workspace_root: str | None,
    workflow_mode: str,
    attachment_context: str,
    selected_ticket_keys: list[str],
    selected_ticket_contexts: list[dict],
) -> dict:
    return {
        "conversation_id": conversation_id,
        "messages": [{"role": "user", "content": user_message}],
        "intent": "",
        "intent_confidence": 0.0,
        "intent_source": "",
        "workspace_path": str(workspace_root or ""),
        "secondary_workspace_path": str(secondary_workspace_root or ""),
        "workflow_mode": str(workflow_mode or "auto"),
        "attachment_context": attachment_context,
        "selected_ticket_keys": selected_ticket_keys,
        "selected_ticket_contexts": selected_ticket_contexts,
        "result": "",
        "research_task_id": None,
    }


async def _handle_stitch_generation_turn(
    *,
    conversation_id: str,
    user_message: str,
    workspace_root: str | None,
) -> None:
    resolved_workspace = str(workspace_root or '').strip()

    if not resolved_workspace:
        raise StitchServiceError('A workspace is required for Stitch generation mode')

    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent='Stitch Agent',
        event_type='turn_started',
        content='',
    )

    try:
        generation = generate_workspace_screens(
            workspace_root=resolved_workspace,
            prompt=user_message,
        )
        screens = generation.get('screens') if isinstance(generation.get('screens'), list) else []

        if not screens:
            reply = 'Stitch generation completed, but no screens were returned.'
        else:
            lines = [
                f"Generated {len(screens)} screen{'s' if len(screens) != 1 else ''} in Stitch.",
                '',
            ]

            for index, item in enumerate(screens, start=1):
                if not isinstance(item, dict):
                    continue

                screen_id = str(item.get('screen_id') or '').strip()
                title = str(item.get('title') or screen_id or f'Screen {index}').strip()

                downloaded = await download_workspace_screen_assets(
                    workspace_root=resolved_workspace,
                    screen_id=screen_id,
                    title=title,
                )
                screenshot_url = str(item.get('screenshot_url') or downloaded.get('image_url') or '').strip()
                image_path = str(downloaded.get('image_path') or '').strip()
                code_path = str(downloaded.get('code_path') or '').strip()

                lines.append(f'{index}. {title}')

                if screenshot_url:
                    lines.append(f'![{title}]({screenshot_url})')

                if image_path:
                    lines.append(f'Image saved: `{image_path}`')

                if code_path:
                    lines.append(f'HTML saved: `{code_path}`')

                lines.append('')

            reply = '\n'.join(lines).strip()
    except StitchServiceError as exc:
        reply = f'Stitch generation failed: {str(exc).strip() or type(exc).__name__}'
    except Exception as exc:
        reply = f'Stitch generation failed: {str(exc).strip() or type(exc).__name__}'

    add_message(conversation_id, role='assistant', agent='Stitch Agent', content=reply)
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent='Stitch Agent',
        event_type='assistant_message',
        content=reply,
    )
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent='Stitch Agent',
        event_type='turn_completed',
        content='',
    )


class OrchestratorChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    workspace_root: str | None = Field(default=None, max_length=500)
    secondary_workspace_root: str | None = Field(default=None, max_length=500)
    workflow_mode: Literal["auto", "jira", "code_review", "code", "research", "stitch_generation"] = "code_review"
    selected_ticket_keys: list[str] = Field(default_factory=list)


class StitchLinkRequest(BaseModel):
    workspace_root: str = Field(..., min_length=1, max_length=2000)
    project_id: str | None = Field(default=None, max_length=255)


class StitchGenerateRequest(BaseModel):
    workspace_root: str = Field(..., min_length=1, max_length=2000)
    prompt: str = Field(..., min_length=1, max_length=8000)
    device_type: str = Field(default='DESKTOP', max_length=32)


class StitchDownloadRequest(BaseModel):
    workspace_root: str = Field(..., min_length=1, max_length=2000)
    screen_id: str = Field(..., min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)


class PromptHistoryEntry(BaseModel):
    id: str
    timestamp: str
    message: str
    type: Literal["user", "system"] = "system"


class SDDPromptContextItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["file", "folder", "snippet", "image"]
    path: str | None = Field(default=None, max_length=2000)
    workspace_role: Literal["primary", "secondary"] = "primary"
    absolute_path: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=20000)
    line_start: int | None = Field(default=None, ge=1, le=200000)
    line_end: int | None = Field(default=None, ge=1, le=200000)
    mime_type: str | None = Field(default=None, max_length=200)
    data_url: str | None = Field(default=None, max_length=8_000_000)


class SDDCurrentBundle(BaseModel):
    requirements: str = Field(default="")
    design: str = Field(default="")
    tasks: str = Field(default="")


class SDDPlanRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000, description="User prompt for SDD generation")
    raw_prompt: str | None = Field(default=None, max_length=8000, description="Raw prompt text from input box")
    prompt_context: list[SDDPromptContextItem] = Field(default_factory=list, description="Referenced files/folders context")
    workspace_path: str = Field(..., min_length=1, max_length=2000, description="Current workspace root path")
    file_tree: dict[str, object] = Field(default_factory=dict, description="Workspace file tree structure")
    secondary_workspace_path: str | None = Field(default=None, max_length=2000, description="Optional secondary workspace root path")
    secondary_file_tree: dict[str, object] | None = Field(default=None, description="Secondary workspace file tree structure")
    spec_name: str | None = Field(default=None, max_length=128, description="Optional spec name")
    mode: Literal["create", "edit"] = Field(default="create", description="Create a new bundle or edit existing bundle")
    current_bundle: SDDCurrentBundle | None = Field(default=None, description="Current 3-file SDD bundle for edit mode")


class SDDPlanResponse(BaseModel):
    spec_name: str
    requirements: str
    design: str
    tasks: str
    history: list[PromptHistoryEntry]


class SDDSpecSummary(BaseModel):
    spec_name: str
    updated_at: str
    files: list[str]
    has_full_bundle: bool


class SDDSpecListResponse(BaseModel):
    specs: list[SDDSpecSummary]


class SDDSpecBundleResponse(BaseModel):
    spec_name: str
    requirements: str
    design: str
    tasks: str
    history: list[PromptHistoryEntry]
    updated_at: str


class SDDSaveRequest(BaseModel):
    spec_name: str = Field(..., min_length=1, max_length=128, description="Spec folder name")
    file_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="File to save: requirements.md, design.md, or tasks.md",
    )
    content: str = Field(..., description="File content to save")
    workspace_path: str | None = Field(default=None, max_length=2000, description="Workspace root path")


class SDDSaveResponse(BaseModel):
    success: bool
    file_path: str
    error: str | None = None


class SDDBundleImportRequest(BaseModel):
    bundle_path: str = Field(..., min_length=1, max_length=4000, description="Path containing requirements.md, design.md, tasks.md")
    spec_name: str = Field(..., min_length=1, max_length=128, description="Target spec folder name")
    workspace_path: str | None = Field(default=None, max_length=2000, description="Workspace root path")
    summary: str | None = Field(default=None, max_length=1000, description="Optional summary override for the task")


class SDDSpecDeleteResponse(BaseModel):
    success: bool
    spec_name: str
    deleted_path: str
    error: str | None = None


class SpecTaskCreateRequest(BaseModel):
    spec_name: str = Field(..., min_length=1, max_length=128, description="Spec folder name")
    workspace_path: str | None = Field(default=None, max_length=2000, description="Workspace root path")
    summary: str | None = Field(default=None, max_length=1000, description="Optional summary override for the task")


class SpecTaskDependenciesUpdateRequest(BaseModel):
    dependency_mode: Literal["independent", "parent", "subtask"] = "independent"
    parent_spec_name: str | None = Field(default=None, min_length=1, max_length=128)
    depends_on: list[str] = Field(default_factory=list, max_length=200)


class SpecTaskStatusUpdateRequest(BaseModel):
    status: Literal["pending", "complete"] = "pending"


class SpecTaskResponse(BaseModel):
    id: str
    spec_name: str
    workspace_path: str
    spec_path: str
    requirements_path: str
    design_path: str
    tasks_path: str
    summary: str
    status: Literal["generating", "generated", "pending", "complete", "failed"]
    parent_spec_name: str | None = None
    parent_spec_task_id: str | None = None
    dependency_mode: Literal["independent", "parent", "subtask"] | None = None
    depends_on: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class SDDGenerateAsyncRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    raw_prompt: str | None = Field(default=None, max_length=8000)
    prompt_context: list[SDDPromptContextItem] = Field(default_factory=list)
    workspace_path: str = Field(..., min_length=1, max_length=2000)
    file_tree: dict[str, object] = Field(default_factory=dict)
    secondary_workspace_path: str | None = Field(default=None, max_length=2000)
    secondary_file_tree: dict[str, object] | None = Field(default=None)
    spec_name: str = Field(..., min_length=1, max_length=128)
    mode: Literal["create", "edit"] = Field(default="create")
    current_bundle: SDDCurrentBundle | None = Field(default=None)


class SDDGenerateAsyncResponse(BaseModel):
    spec_name: str
    spec_task_id: str
    status: Literal["generating"]


class SpecTaskListResponse(BaseModel):
    spec_tasks: list[SpecTaskResponse]


class SpecTaskDeleteResponse(BaseModel):
    success: bool
    id: str
    spec_name: str
    workspace_path: str
    deleted: bool
    error: str | None = None


class OrchestratorStopRequest(BaseModel):
    conversation_id: str | None = None


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(default="", max_length=4000)


class TaskStatusRequest(BaseModel):
    status: Literal["todo", "in_progress", "done"]


class FsMkdirRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=255)


class FsRenameRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=255)


class FsDeleteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)


class DeleteConversationsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class JiraFetchRequest(BaseModel):
    project_key: str | None = Field(default=None, max_length=100)
    board_id: str | None = Field(default=None, max_length=50)
    workspace_root: str | None = Field(default=None, max_length=500)


class JiraConfigUpdateRequest(BaseModel):
    project_key: str | None = Field(default=None, max_length=100)
    board_id: str | None = Field(default=None, max_length=50)
    assignee_filter: str | None = Field(default=None, max_length=255)


class PipelineSettingsRequest(BaseModel):
    active_window_start: str | None = Field(default=None, max_length=5)
    active_window_end: str | None = Field(default=None, max_length=5)
    heartbeat_interval_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    automation_enabled: bool | None = None
    max_retries: int | None = Field(default=None, ge=1, le=12)
    review_failure_mode: Literal["strict", "skip_acceptance", "skip_all"] | None = None


class PipelineHeartbeatTriggerRequest(BaseModel):
    delay_seconds: int = Field(default=10, ge=0, le=300)


class PipelineAutomationRequest(BaseModel):
    enabled: bool


class PipelineQueueRequest(BaseModel):
    jira_key: str = Field(min_length=3, max_length=40)
    workspace_path: str = Field(min_length=1, max_length=2000)
    jira_complete_column_name: str | None = Field(default=None, max_length=255)
    starting_git_branch_override: str | None = Field(default=None, max_length=255)
    workflow: Literal["codex"] = "codex"
    task_relation: Literal["task", "subtask"] | None = None
    depends_on_task_ids: list[str] | None = Field(default=None)


class PipelineMoveRequest(BaseModel):
    target_status: Literal["current", "running", "complete", "failed", "stopped", "backlog"]
    workspace_path: str | None = Field(default=None, max_length=2000)
    jira_complete_column_name: str | None = Field(default=None, max_length=255)
    starting_git_branch_override: str | None = Field(default=None, max_length=255)
    workflow: Literal["codex"] | None = None
    task_relation: Literal["task", "subtask"] | None = None
    depends_on_task_ids: list[str] | None = Field(default=None)


class PipelineReorderRequest(BaseModel):
    ordered_task_ids: list[str] = Field(default_factory=list, max_length=500)


class PipelineTaskBypassRequest(BaseModel):
    bypassed: bool
    reason: str | None = Field(default=None, max_length=2000)
    resolve_handoffs: bool = False


class PipelineTaskDependenciesRequest(BaseModel):
    depends_on_task_ids: list[str] = Field(default_factory=list, max_length=200)


class PipelineTaskHandoffResolveRequest(BaseModel):
    reenable_task: bool = False
    resolution_note: str | None = Field(default=None, max_length=2000)


class AgentsBypassRequest(BaseModel):
    jira_api_bypass: bool | None = None
    sdd_spec_bypass: bool | None = None
    code_builder_bypass: bool | None = None
    code_review_bypass: bool | None = None


def _apply_agent_bypass(snapshot: dict[str, object]) -> dict[str, object]:
    bypass = get_agent_bypass_settings()
    agents = snapshot.get("agents")
    if not isinstance(agents, list):
        return snapshot

    for agent in agents:
        if not isinstance(agent, dict):
            continue
        role = str(agent.get("role") or "").strip().lower()
        if role == "jira_api":
            enabled = not bypass["jira_api"]
            agent["enabled"] = enabled
            agent["bypassed"] = bypass["jira_api"]
            if not enabled:
                agent["is_active"] = False
                agent["status"] = "bypassed"
        elif role == "sdd_spec":
            enabled = not bypass["sdd_spec"]
            agent["enabled"] = enabled
            agent["bypassed"] = bypass["sdd_spec"]
            if not enabled:
                agent["is_active"] = False
                agent["status"] = "bypassed"
        elif role == "code_builder":
            enabled = not bypass["code_builder"]
            agent["enabled"] = enabled
            agent["bypassed"] = bypass["code_builder"]
            if not enabled:
                agent["is_active"] = False
                agent["status"] = "bypassed"
        elif role == "code_review":
            enabled = not bypass["code_review"]
            agent["enabled"] = enabled
            agent["bypassed"] = bypass["code_review"]
            if not enabled:
                agent["is_active"] = False
                agent["status"] = "bypassed"

    snapshot["bypass"] = {
        "jira_api_bypass": bypass["jira_api"],
        "sdd_spec_bypass": bypass["sdd_spec"],
        "code_builder_bypass": bypass["code_builder"],
        "code_review_bypass": bypass["code_review"],
    }
    return snapshot


def _on_agent_event(event: str, agent_id: str, agent_name: str | None, error: str | None) -> None:
    from app.pipeline_store import add_pipeline_log

    label = agent_name or agent_id

    if event == "start":
        level = "info"
        message = f"[{label}] started"
    elif error:
        level = "error"
        message = f"[{label}] failed: {error}"
    else:
        level = "info"
        message = f"[{label}] completed"

    try:
        add_pipeline_log(level=level, message=message)
    except Exception:
        pass

    if event == "start":
        return

    status = "failed" if error else "completed"
    lowered_label = label.lower()
    if status == "completed" and "heartbeat" in lowered_label:
        return

    timestamp = datetime.now(timezone.utc).isoformat()
    workspace_root = Path(os.getenv("WORKSPACE_ROOT", Path.cwd())).resolve()

    content_lines = [
        f"Agent {status}: {label}.",
        f"Agent ID: {agent_id}.",
        f"Timestamp: {timestamp}.",
    ]
    if error:
        content_lines.append(f"Error: {str(error).strip()[:2000]}")

    metadata = {
        "event_type": "agent_lifecycle",
        "agent_id": str(agent_id),
        "agent_name": str(label),
        "status": status,
    }

    def _capture_agent_event() -> None:
        try:
            capture_assist_brain_sync(
                workspace_root,
                content="\n".join(content_lines)[:4000],
                metadata=metadata,
            )
        except Exception:
            return

    threading.Thread(
        target=_capture_agent_event,
        name=f"assist-brain-agent-event-{agent_id}",
        daemon=True,
    ).start()


@app.on_event("startup")
async def startup() -> None:
    global _mcp_startup_report
    global chat_graph, spec_graph
    ensure_settings_file_exists()
    validate_database_config()
    _shutdown_streams.clear()
    _install_shutdown_signal_handlers()
    init_pool()
    init_db()
    ensure_pipeline_schema()
    register_agent_listener(_on_agent_event)
    checkpointer = await get_checkpointer()
    chat_graph = build_chat_graph(checkpointer, orchestrator_engine)
    spec_graph = build_spec_pipeline_graph(checkpointer)
    ticket_graph = build_ticket_pipeline_graph(checkpointer, pipeline_engine)
    pipeline_engine.set_ticket_graph(ticket_graph)

    register_agent(
        AgentDefinition(
            id=make_agent_id('graphs', 'Chat Graph'),
            name='Chat Graph',
            provider=None,
            model=None,
            group='graphs',
            role='chat_graph',
            kind='graph',
            source='app/graphs/chat/graph.py',
            description='Routes chat, jira, research, filesystem, commands, slack and build intents.',
            capabilities=['routing', 'chat', 'research', 'jira', 'filesystem', 'slack', 'build'],
        )
    )

    register_agent(
        AgentDefinition(
            id=make_agent_id('graphs', 'Ticket Pipeline Graph'),
            name='Ticket Pipeline Graph',
            provider=None,
            model=None,
            group='graphs',
            role='ticket_pipeline_graph',
            kind='graph',
            source='app/graphs/ticket_pipeline/graph.py',
            description='Handles fetch, SDD spec, build, review and git handoff with retry loop.',
            capabilities=['pipeline', 'retry', 'checkpointing'],
        )
    )

    register_agent(
        AgentDefinition(
            id=make_agent_id('graphs', 'Spec Pipeline Graph'),
            name='Spec Pipeline Graph',
            provider=None,
            model=None,
            group='graphs',
            role='spec_pipeline_graph',
            kind='graph',
            source='app/graphs/spec_pipeline/graph.py',
            description='Parallel SDD spec bundle generation via Send fan-out.',
            capabilities=['sdd_spec', 'parallel', 'fan_out'],
        )
    )
    seed_tasks_if_empty(
        [
            ("Add API keys", "Set OPENAI_API_KEY and ANTHROPIC_API_KEY in your deployment environment."),
            ("Connect deployment", "Pick Render, Fly, or Railway and deploy from your repo."),
        ]
    )
    connection_monitor.on_disconnect(reset_pool)
    connection_monitor.on_reconnect(reset_pool)
    connection_monitor.start()
    pipeline_engine.start()
    git_agent.register()
    workspace_agent.register()
    jira_api_agent.register()
    slack_agent.register()
    if os.getenv("MCP_STARTUP_PROBE", "true").strip().lower() in {"0", "false", "no", "off"}:
        _mcp_startup_report = {
            "status": "disabled",
            "configured": False,
            "servers": [],
            "errors": ["startup probe disabled by MCP_STARTUP_PROBE"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        print("[MCP] Startup probe disabled by MCP_STARTUP_PROBE.")
        return
    _mcp_startup_report = {
        "status": "scheduled",
        "configured": False,
        "servers": [],
        "errors": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    asyncio.create_task(_probe_mcp_tools_on_startup())


@app.on_event("shutdown")
async def shutdown() -> None:
    _shutdown_streams.set()
    pipeline_engine.stop()
    connection_monitor.stop()
    await close_checkpointer()


async def _probe_mcp_tools_on_startup() -> None:
    global _mcp_startup_report
    workspace_root = Path(os.getenv("WORKSPACE_ROOT", Path.cwd())).resolve()
    timeout_seconds = float(os.getenv("MCP_STARTUP_PROBE_TIMEOUT_SECONDS", "8"))
    report: dict[str, object] = {
        "status": "running",
        "workspace_root": str(workspace_root),
        "configured": False,
        "servers": [],
        "errors": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    config = load_mcp_config(workspace_root)
    if not config or not config.servers:
        reason = "app/mcp.json not found or no servers configured"
        print(f"[MCP] Startup probe skipped: {reason}.")
        report["errors"] = [reason]
        report["status"] = "complete"
        _mcp_startup_report = report
        return

    report["configured"] = True
    client = MCPClient(config)
    for server_name, server in config.servers.items():
        lowered = server_name.lower()
        if "atlassian" in lowered or "jira" in lowered:
            print(f"[MCP] Startup probe: skipping '{server_name}' (interactive OAuth server).")
            cast_servers = report["servers"]
            if isinstance(cast_servers, list):
                cast_servers.append(
                    {
                        "server": server_name,
                        "disabled": False,
                        "count": 0,
                        "tools": [],
                        "skipped": "interactive_oauth",
                    }
                )
            continue
        if "assist" in lowered and "brain" in lowered and str(getattr(server, "transport", "")).lower() == "http":
            headers = {str(key).lower(): str(value) for key, value in (getattr(server, "headers", {}) or {}).items()}
            if not str(headers.get("x-brain-key") or "").strip():
                print(f"[MCP] Startup probe: skipping '{server_name}' (missing x-brain-key).")
                cast_servers = report["servers"]
                if isinstance(cast_servers, list):
                    cast_servers.append(
                        {
                            "server": server_name,
                            "disabled": False,
                            "count": 0,
                            "tools": [],
                            "skipped": "missing_access_key",
                        }
                    )
                continue
        if server.disabled:
            print(f"[MCP] Startup probe: server '{server_name}' is disabled.")
            cast_servers = report["servers"]
            if isinstance(cast_servers, list):
                cast_servers.append({"server": server_name, "disabled": True, "count": 0, "tools": []})
            continue
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(client.list_tools, server_name),
                timeout=timeout_seconds,
            )
            raw_tools = payload.get("tools") if isinstance(payload, dict) else []
            tools = [tool for tool in raw_tools if isinstance(tool, dict)]
            tool_names = [str(tool.get("name") or "") for tool in tools if str(tool.get("name") or "").strip()]
            print(f"[MCP] Startup tools from '{server_name}' ({len(tool_names)}): {', '.join(tool_names)}")
            cast_servers = report["servers"]
            if isinstance(cast_servers, list):
                cast_servers.append(
                    {
                        "server": server_name,
                        "disabled": False,
                        "count": len(tool_names),
                        "tools": tool_names,
                    }
                )
        except asyncio.TimeoutError:
            error = f"{server_name}: timed out after {timeout_seconds:.1f}s"
            print(f"[MCP] Startup probe failed for '{server_name}': {error}")
            cast_errors = report["errors"]
            if isinstance(cast_errors, list):
                cast_errors.append(error)
            cast_servers = report["servers"]
            if isinstance(cast_servers, list):
                cast_servers.append({"server": server_name, "disabled": False, "count": 0, "tools": []})
        except Exception as exc:
            error = f"{server_name}: {str(exc).strip() or type(exc).__name__}"
            print(f"[MCP] Startup probe failed for '{server_name}': {error}")
            cast_errors = report["errors"]
            if isinstance(cast_errors, list):
                cast_errors.append(error)
            cast_servers = report["servers"]
            if isinstance(cast_servers, list):
                cast_servers.append({"server": server_name, "disabled": False, "count": 0, "tools": []})
    report["status"] = "complete"
    _mcp_startup_report = report


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _connectivity_marker_event(online: bool) -> str:
    payload = json.dumps({'type': 'connectivity', 'online': online})
    return f"data: {payload}\n\n"


async def _provider_health_cached() -> dict[str, object]:
    global _provider_health_cache, _provider_health_cache_at
    now = datetime.now(timezone.utc)
    if _provider_health_cache and _provider_health_cache_at:
        if now - _provider_health_cache_at < _provider_health_cache_ttl:
            return _provider_health_cache
    try:
        _provider_health_cache = await asyncio.wait_for(
            provider_health_client.providers_health(),
            timeout=_provider_health_fetch_timeout_seconds,
        )
        _provider_health_cache_at = now
    except asyncio.TimeoutError:
        if _provider_health_cache:
            return _provider_health_cache
        return {}
    except Exception:
        if _provider_health_cache:
            return _provider_health_cache
        return {}
    return _provider_health_cache or {}


@app.get("/api/providers/health")
async def providers_health() -> dict[str, object]:
    if not connection_monitor.is_connected():
        raise HTTPException(status_code=503, detail='Internet connection unavailable.')
    return await provider_health_client.providers_health()


@app.get("/api/mcp/startup-report")
def mcp_startup_report() -> dict[str, object]:
    return _mcp_startup_report or {
        "configured": False,
        "servers": [],
        "errors": ["startup report unavailable"],
    }


def _resolve_workspace_root(workspace_root: str | None) -> Path:
    if workspace_root and workspace_root.strip():
        return Path(workspace_root).resolve()
    return Path(os.getenv("WORKSPACE_ROOT", Path.cwd())).resolve()


@app.get("/api/jira/config")
async def jira_config(workspace_root: str | None = None) -> dict[str, object]:
    resolved = _resolve_workspace_root(workspace_root)
    config = load_mcp_config(resolved)
    tooling = config.tooling.get("jira") if config and config.tooling else {}
    jira_tooling = tooling if isinstance(tooling, dict) else {}
    saved_settings = get_jira_settings()
    jira_base_url = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
    project_key = (
        saved_settings.get("project_key")
        or str(jira_tooling.get("project_key") or "").strip().upper()
    )
    board_id = (
        saved_settings.get("board_id")
        or str(jira_tooling.get("board_id") or "").strip()
    )
    backlog_url = ""
    if jira_base_url and project_key and board_id:
        backlog_url = f"{jira_base_url}/jira/software/projects/{project_key}/boards/{board_id}/backlog"

    return {
        "workspace_root": str(resolved),
        "server": str(jira_tooling.get("server") or "atlassian"),
        "jira_base_url": jira_base_url,
        "backlog_url": backlog_url,
        "project_key": project_key,
        "board_id": board_id,
        "max_results": str(jira_tooling.get("max_results") or "100"),
        "configured": bool(config and config.servers),
        "assignee_filter": str(saved_settings.get("assignee_filter") or ""),
        "jira_users": saved_settings.get("jira_users") or [],
    }


@app.patch("/api/jira/config")
async def update_jira_config(payload: JiraConfigUpdateRequest) -> dict[str, object]:
    project_key = str(payload.project_key or "").strip().upper() or None
    board_id = str(payload.board_id or "").strip() or None
    assignee_filter = payload.assignee_filter
    saved = update_jira_settings(project_key=project_key, board_id=board_id, assignee_filter=assignee_filter)
    jira_base_url = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
    backlog_url = ""
    if jira_base_url and saved.get("project_key") and saved.get("board_id"):
        backlog_url = f"{jira_base_url}/jira/software/projects/{saved['project_key']}/boards/{saved['board_id']}/backlog"

    return {
        "project_key": saved.get("project_key", ""),
        "board_id": saved.get("board_id", ""),
        "assignee_filter": saved.get("assignee_filter", ""),
        "jira_users": saved.get("jira_users") or [],
        "jira_base_url": jira_base_url,
        "backlog_url": backlog_url,
    }


@app.get("/api/jira/users")
async def jira_get_users() -> dict[str, object]:
    jira_base_url = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
    if not jira_base_url:
        raise HTTPException(status_code=400, detail="JIRA_BASE_URL is not configured in the environment.")

    try:
        saved_settings = get_jira_settings()
        project_key = str(saved_settings.get("project_key") or "").strip()
        users = await jira_api_agent.get_assignable_users(project_key=project_key)
        normalized = [
            {
                "accountId": str(u.get("accountId") or ""),
                "displayName": str(u.get("displayName") or ""),
                "emailAddress": str(u.get("emailAddress") or ""),
            }
            for u in users
            if u.get("accountId")
        ]
        update_jira_settings(jira_users=normalized)
        return {"users": normalized}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc


@app.post("/api/jira/tickets/fetch")
async def jira_fetch_tickets(payload: JiraFetchRequest) -> dict[str, object]:
    global _available_tickets_cache, _available_tickets_cache_at
    resolved = _resolve_workspace_root(payload.workspace_root)
    jira_base_url = str(os.getenv("JIRA_BASE_URL") or "").strip().rstrip("/")
    project_key = str(payload.project_key or "").strip().upper()
    board_id = str(payload.board_id or "").strip()

    if not jira_base_url:
        raise HTTPException(status_code=400, detail="JIRA_BASE_URL is not configured in the environment.")

    if not project_key or not board_id:
        raise HTTPException(status_code=400, detail="project_key and board_id are required.")

    backlog_url = f"{jira_base_url}/jira/software/projects/{project_key}/boards/{board_id}/backlog"

    update_jira_settings(project_key=project_key, board_id=board_id)

    try:
        result = await jira_api_agent.fetch_backlog_tickets(resolved, backlog_url)
        saved = add_jira_fetch(
            backlog_url=str(result.get("backlog_url") or ""),
            server=str(result.get("server") or ""),
            tool=str(result.get("tool") or ""),
            ticket_count=int(result.get("ticket_count") or 0),
            tickets_json=json.dumps(result.get("tickets") or [], ensure_ascii=False),
            current_sprint_json=json.dumps(result.get("current_sprint") or {}, ensure_ascii=False),
            kanban_columns_json=json.dumps(result.get("kanban_columns") or [], ensure_ascii=False),
            warnings_json=json.dumps(result.get("warnings") or [], ensure_ascii=False),
            raw_result_json=str(result.get("raw_result_json") or ""),
            raw_result_path=str(result.get("raw_result_path") or "") or None,
        )
        result["db_id"] = str(saved.get("id") or "")
        result["saved_at"] = str(saved.get("created_at") or "")
        try:
            pipeline_engine.refresh_backlog_from_tickets(
                result.get("tickets") if isinstance(result.get("tickets"), list) else [],
                kanban_columns=result.get("kanban_columns") if isinstance(result.get("kanban_columns"), list) else [],
                fetched_at=str(result.get("fetched_at") or result.get("saved_at") or ""),
            )
        except Exception as sync_exc:
            warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
            warnings.append(f"Pipeline backlog sync failed: {str(sync_exc).strip() or type(sync_exc).__name__}")
            result["warnings"] = warnings
        _available_tickets_cache = None
        _available_tickets_cache_at = None
        _ticket_details_cache.clear()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc


@app.get("/api/jira/fetches")
async def jira_fetches(limit: int = 20, include_raw: bool = False) -> dict[str, object]:
    safe_limit = max(1, min(limit, 200))
    rows = list_jira_fetches(safe_limit)
    fetches: list[dict[str, object]] = []
    for row in rows:
        try:
            tickets = json.loads(str(row.get("tickets_json") or "[]"))
        except Exception:
            tickets = []
        try:
            warnings = json.loads(str(row.get("warnings_json") or "[]"))
        except Exception:
            warnings = []
        try:
            current_sprint = json.loads(str(row.get("current_sprint_json") or "{}"))
        except Exception:
            current_sprint = {}
        try:
            kanban_columns = json.loads(str(row.get("kanban_columns_json") or "[]"))
        except Exception:
            kanban_columns = []
        item: dict[str, object] = {
            "id": row.get("id"),
            "created_at": row.get("created_at"),
            "backlog_url": row.get("backlog_url"),
            "server": row.get("server"),
            "tool": row.get("tool"),
            "ticket_count": row.get("ticket_count"),
            "tickets": tickets,
            "current_sprint": current_sprint,
            "kanban_columns": kanban_columns,
            "warnings": warnings,
            "raw_result_path": row.get("raw_result_path"),
        }
        if include_raw:
            item["raw_result_json"] = row.get("raw_result_json") or ""
        fetches.append(item)
    return {"fetches": fetches}


@app.get("/api/tickets/available")
async def list_available_tickets(workspace_root: str | None = None) -> dict[str, object]:
    resolved = _resolve_workspace_root(workspace_root)
    tickets = await _available_tickets_cached(resolved)
    return {
        "tickets": tickets,
        "count": len(tickets),
        "cached": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/tickets/{ticket_key}")
async def get_ticket_details(ticket_key: str, workspace_root: str | None = None) -> dict[str, object]:
    resolved = _resolve_workspace_root(workspace_root)
    normalized_key = _normalize_ticket_key(ticket_key)
    if not normalized_key:
        raise HTTPException(status_code=400, detail="ticket_key is required")

    ticket = await _load_ticket_by_key(normalized_key, resolved)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {normalized_key} was not found")
    return _ticket_to_context_payload(ticket)


@app.get("/api/pipelines/state")
def pipelines_state() -> dict[str, object]:
    return pipeline_engine.snapshot_state()


@app.post("/api/pipelines/spec-batch")
async def pipelines_spec_batch(payload: dict) -> dict[str, object]:
    """Run parallel SDD spec generation for a batch of spec requests via SpecPipelineGraph."""
    import uuid
    from app.graphs.spec_pipeline.state import SpecRequest

    raw_requests = payload.get("spec_requests") or []
    if not isinstance(raw_requests, list) or not raw_requests:
        raise HTTPException(status_code=422, detail="spec_requests must be a non-empty list.")

    spec_requests: list[SpecRequest] = [
        {
            "spec_name": str(item.get("spec_name") or ""),
            "workspace_path": str(item.get("workspace_path") or ""),
            "spec_path": str(item.get("spec_path") or ""),
            "ticket_context": item.get("ticket_context") or {},
        }
        for item in raw_requests
        if isinstance(item, dict)
    ]

    batch_id = str(uuid.uuid4())
    initial_state = {
        "batch_id": batch_id,
        "spec_requests": spec_requests,
        "results": [],
    }
    graph_config = {"configurable": {"thread_id": batch_id}}
    final_state = await spec_graph.ainvoke(initial_state, config=graph_config)

    return {
        "batch_id": batch_id,
        "results": final_state.get("results") or [],
    }


@app.get("/api/pipelines/stream")
async def pipelines_stream() -> StreamingResponse:
    async def event_generator():
        try:
            while True:
                if _stream_shutdown_requested():
                    break
                payload = json.dumps(pipeline_engine.snapshot_state())
                yield f"data: {payload}\n\n"
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/pipelines/backlog/refresh")
async def pipelines_backlog_refresh() -> dict[str, object]:
    try:
        return await pipeline_engine.refresh_backlog()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc


@app.post("/api/pipelines/tasks/queue")
def pipelines_queue_task(payload: PipelineQueueRequest) -> dict[str, object]:
    try:
        task = pipeline_engine.queue_ticket(
            payload.jira_key,
            payload.workspace_path,
            payload.workflow,
            payload.jira_complete_column_name,
            payload.starting_git_branch_override,
            depends_on_task_ids=payload.depends_on_task_ids,
            task_relation=payload.task_relation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task": task}


@app.post("/api/pipelines/tasks/{task_id}/move")
def pipelines_move_task(task_id: str, payload: PipelineMoveRequest) -> dict[str, object]:
    try:
        task = pipeline_engine.move_task(
            task_id,
            payload.target_status,
            payload.workspace_path,
            payload.workflow,
            payload.jira_complete_column_name,
            payload.starting_git_branch_override,
            depends_on_task_ids=payload.depends_on_task_ids,
            task_relation=payload.task_relation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task": task}


@app.post("/api/pipelines/tasks/reorder")
def pipelines_reorder_tasks(payload: PipelineReorderRequest) -> dict[str, object]:
    pipeline_engine.reorder_current(payload.ordered_task_ids)
    return {"ok": True}


@app.patch("/api/pipelines/settings")
def pipelines_update_settings(payload: PipelineSettingsRequest) -> dict[str, object]:
    interval = payload.heartbeat_interval_minutes
    if interval is not None and interval < MIN_HEARTBEAT_INTERVAL_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"Heartbeat interval must be at least {MIN_HEARTBEAT_INTERVAL_MINUTES} minutes.",
        )
    try:
        settings = pipeline_engine.update_settings(
            active_window_start=payload.active_window_start,
            active_window_end=payload.active_window_end,
            heartbeat_interval_minutes=payload.heartbeat_interval_minutes,
            automation_enabled=payload.automation_enabled,
            max_retries=payload.max_retries,
            review_failure_mode=payload.review_failure_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"settings": settings}


@app.patch("/api/pipelines/automation")
def pipelines_toggle_automation(payload: PipelineAutomationRequest) -> dict[str, object]:
    try:
        settings = pipeline_engine.update_settings(
            active_window_start=None,
            active_window_end=None,
            heartbeat_interval_minutes=None,
            automation_enabled=payload.enabled,
            max_retries=None,
            review_failure_mode=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"settings": settings}


@app.post("/api/pipelines/heartbeat/trigger")
def pipelines_trigger_heartbeat(payload: PipelineHeartbeatTriggerRequest) -> dict[str, object]:
    try:
        result = pipeline_engine.trigger_heartbeat_soon(delay_seconds=payload.delay_seconds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return result


@app.post("/api/pipelines/tasks/trigger-next")
def pipelines_trigger_next_task() -> dict[str, object]:
    try:
        result = pipeline_engine.trigger_next_task_now()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return result


@app.patch("/api/pipelines/tasks/{task_id}/bypass")
def pipelines_set_task_bypass(task_id: str, payload: PipelineTaskBypassRequest) -> dict[str, object]:
    try:
        task = pipeline_engine.set_task_bypass(
            task_id,
            bypassed=payload.bypassed,
            reason=payload.reason,
            source=None,
            by="user",
            resolve_handoffs=payload.resolve_handoffs,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task": task}


@app.put("/api/pipelines/tasks/{task_id}/dependencies")
def pipelines_set_task_dependencies(task_id: str, payload: PipelineTaskDependenciesRequest) -> dict[str, object]:
    try:
        dependencies = pipeline_engine.set_task_dependencies(task_id, payload.depends_on_task_ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task_id": task_id, "dependencies": dependencies}


@app.get("/api/pipelines/tasks/{task_id}/handoffs")
def pipelines_list_task_handoffs(task_id: str) -> dict[str, object]:
    try:
        handoffs = pipeline_engine.list_task_handoffs(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task_id": task_id, "handoffs": handoffs}


@app.post("/api/pipelines/tasks/{task_id}/handoffs/{handoff_id}/resolve")
def pipelines_resolve_task_handoff(
    task_id: str,
    handoff_id: str,
    payload: PipelineTaskHandoffResolveRequest,
) -> dict[str, object]:
    try:
        handoff = pipeline_engine.resolve_task_handoff(
            task_id,
            handoff_id,
            resolved_by="user",
            resolution_note=payload.resolution_note,
            reenable_task=payload.reenable_task,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task_id": task_id, "handoff": handoff}


@app.post("/api/pipelines/tasks/{task_id}/admin/reset")
def pipelines_admin_force_reset(task_id: str) -> dict[str, object]:
    try:
        task = pipeline_engine.admin_force_reset_spec_task(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task": task}


@app.post("/api/pipelines/tasks/{task_id}/admin/complete")
def pipelines_admin_force_complete(task_id: str) -> dict[str, object]:
    try:
        task = pipeline_engine.admin_force_complete_task(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or type(exc).__name__) from exc
    return {"task": task}


@app.get("/api/agents")
async def get_agents() -> dict[str, object]:
    provider_health = _provider_health_cache or {}
    if connection_monitor.is_connected():
        provider_health = await _provider_health_cached()
    return _apply_agent_bypass(build_agent_snapshot(provider_health))

@app.get("/api/workflows")
def get_workflows() -> dict[str, object]:
    return {"workflows": workflow_list()}


@app.get("/api/agents/stream")
async def agents_stream(request: Request) -> StreamingResponse:
    async def event_generator():
        last_online: bool | None = None
        try:
            while True:
                if _stream_shutdown_requested():
                    break
                if await request.is_disconnected():
                    break
                is_connected = connection_monitor.is_connected()
                if is_connected != last_online:
                    last_online = is_connected
                    yield _connectivity_marker_event(is_connected)
                if not is_connected:
                    yield ': offline\n\n'
                    await asyncio.sleep(1)
                    continue
                provider_health = await _provider_health_cached()
                payload = json.dumps(_apply_agent_bypass(build_agent_snapshot(provider_health)))
                yield f"data: {payload}\n\n"
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/logs")
async def get_logs(limit: int = 200) -> dict[str, object]:
    logs = list_pipeline_logs(limit=limit)
    return {"logs": logs}


@app.get("/api/logs/stream")
async def logs_stream(request: Request) -> StreamingResponse:
    async def event_generator():
        last_online: bool | None = None
        try:
            history_sent = False
            last_id = None

            while True:
                if _stream_shutdown_requested():
                    break
                if await request.is_disconnected():
                    break

                is_connected = connection_monitor.is_connected()
                if is_connected != last_online:
                    last_online = is_connected
                    yield _connectivity_marker_event(is_connected)
                if not is_connected:
                    yield ': offline\n\n'
                    await asyncio.sleep(1)
                    continue

                try:
                    if not history_sent:
                        history = list_pipeline_logs(limit=200)
                        history_asc = list(reversed(history))
                        yield f"data: {json.dumps({'type': 'history', 'logs': history_asc})}\n\n"
                        last_id = history_asc[-1]["id"] if history_asc else None
                        history_sent = True

                    new_logs = list_pipeline_logs_since(after_id=last_id, limit=100)
                except Exception:
                    await asyncio.sleep(1)
                    continue

                for log in new_logs:
                    yield f"data: {json.dumps({'type': 'log', 'log': log})}\n\n"

                if new_logs:
                    last_id = new_logs[-1]["id"]

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/connection/stream")
async def connection_stream(request: Request) -> StreamingResponse:
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[bool] = asyncio.Queue()

    def on_change(is_connected: bool) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, is_connected)
        except Exception:
            pass

    unsubscribe = connection_monitor.subscribe(on_change)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'connected': connection_monitor.is_connected()})}\n\n"

            while True:
                if _stream_shutdown_requested():
                    break
                if await request.is_disconnected():
                    break

                try:
                    is_connected = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {json.dumps({'connected': is_connected})}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return
        finally:
            unsubscribe()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/agents/bypass")
def get_agents_bypass() -> dict[str, object]:
    bypass = get_agent_bypass_settings()
    return {
        "jira_api_bypass": bypass["jira_api"],
        "sdd_spec_bypass": bypass["sdd_spec"],
        "code_builder_bypass": bypass["code_builder"],
        "code_review_bypass": bypass["code_review"],
    }


@app.patch("/api/agents/bypass")
def patch_agents_bypass(payload: AgentsBypassRequest) -> dict[str, object]:
    bypass = set_agent_bypass_settings(
        jira_api=payload.jira_api_bypass,
        sdd_spec=payload.sdd_spec_bypass,
        code_builder=payload.code_builder_bypass,
        code_review=payload.code_review_bypass,
    )
    return {
        "jira_api_bypass": bypass["jira_api"],
        "sdd_spec_bypass": bypass["sdd_spec"],
        "code_builder_bypass": bypass["code_builder"],
        "code_review_bypass": bypass["code_review"],
    }

@app.get("/api/conversations")
def get_conversations(limit: int = 100) -> dict[str, object]:
    safe_limit = max(1, min(limit, 200))
    return {"conversations": list_conversations(safe_limit)}


@app.post("/api/conversations/delete")
def delete_conversation_batch(payload: DeleteConversationsRequest) -> dict[str, object]:
    deleted = delete_conversations(payload.ids)
    return {"deleted": deleted}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, object]:
    deleted = delete_conversations([conversation_id])
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": deleted}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "messages": conversation_messages(conversation_id),
    }


@app.get("/api/orchestrator/{conversation_id}")
def get_orchestrator_state(conversation_id: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "tasks": list_orchestrator_tasks(conversation_id),
        "events": list_orchestrator_events(conversation_id),
        "attachments": [
            _serialize_attachment(attachment)
            for attachment in list_chat_attachments(conversation_id)
        ],
    }

@app.get("/api/orchestrator/stream/{conversation_id}")
async def orchestrator_stream(request: Request, conversation_id: str, since: str | None = None) -> StreamingResponse:
    start_cursor = since or datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()

    async def event_generator():
        cursor = start_cursor
        last_online: bool | None = None
        try:
            while True:
                if _stream_shutdown_requested():
                    break
                if await request.is_disconnected():
                    break
                is_connected = connection_monitor.is_connected()
                if is_connected != last_online:
                    last_online = is_connected
                    yield _connectivity_marker_event(is_connected)
                if not is_connected:
                    yield ': offline\n\n'
                    await asyncio.sleep(1)
                    continue
                try:
                    events = list_orchestrator_events_since(conversation_id, cursor)
                except Exception:
                    await asyncio.sleep(1.0)
                    continue
                for event in events:
                    cursor = event["created_at"]
                    payload = json.dumps(event)
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.75)
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/")
def index() -> FileResponse:
    index_path = static_dir / "index.html"
    if _has_static and index_path.exists():
        return FileResponse(index_path)
    return PlainTextResponse("UI not built. Static assets not found.")


@app.get("/api/chat/attachments/{attachment_id}")
def get_chat_attachment(attachment_id: str) -> FileResponse:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, original_name, stored_path, mime_type
            FROM chat_attachments
            WHERE id = ?
            LIMIT 1
            """,
            (attachment_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Attachment not found")
        stored_path = str(row["stored_path"] or "")
        path = Path(stored_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Attachment file missing")
        return FileResponse(
            path=str(path),
            media_type=str(row["mime_type"] or "application/octet-stream"),
            filename=str(row["original_name"] or path.name),
        )
    finally:
        if conn is not None:
            release_conn(conn)


@app.post("/api/orchestrator/submit")
async def orchestrator_submit(
    request: Request,
    message: str | None = Form(default=None),
    conversation_id: str | None = Form(default=None),
    workspace_root: str | None = Form(default=None),
    secondary_workspace_root: str | None = Form(default=None),
    workflow_mode: Literal["auto", "jira", "code_review", "code", "research", "stitch_generation"] = Form(default="code_review"),
    selected_ticket_keys: str | None = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
) -> dict[str, object]:
    payload_message = message
    payload_conversation_id = conversation_id
    payload_workspace_root = workspace_root
    payload_secondary_workspace_root = secondary_workspace_root
    payload_workflow_mode: Literal["auto", "jira", "code_review", "code", "research", "stitch_generation"] = workflow_mode
    payload_selected_ticket_keys: list[str] = []
    uploaded_files = files

    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        body = await request.json()
        payload = OrchestratorChatRequest.model_validate(body)
        payload_message = payload.message
        payload_conversation_id = payload.conversation_id
        payload_workspace_root = payload.workspace_root
        payload_secondary_workspace_root = payload.secondary_workspace_root
        payload_workflow_mode = payload.workflow_mode
        payload_selected_ticket_keys = list(payload.selected_ticket_keys or [])
        uploaded_files = []
    elif selected_ticket_keys and str(selected_ticket_keys).strip():
        raw_ticket_keys = str(selected_ticket_keys).strip()
        parsed_ticket_keys = _safe_json_loads(raw_ticket_keys, raw_ticket_keys)
        if isinstance(parsed_ticket_keys, list):
            payload_selected_ticket_keys = [str(item) for item in parsed_ticket_keys if str(item).strip()]
        else:
            payload_selected_ticket_keys = [item.strip() for item in raw_ticket_keys.split(",") if item.strip()]

    if not payload_message or not payload_message.strip():
        raise HTTPException(status_code=422, detail="message is required")

    conversation_id = ensure_conversation(payload_conversation_id)
    add_message(conversation_id, role="user", agent=None, content=payload_message)
    user_message_event = add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent="User",
        event_type="user_message",
        content=payload_message,
    )

    persisted_attachments = _persist_chat_attachments(
        conversation_id,
        user_message_event.get("id"),
        uploaded_files,
    )
    serialized_attachments = [_serialize_attachment(attachment) for attachment in persisted_attachments]
    if serialized_attachments:
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent="User",
            event_type="user_attachments",
            content=json.dumps(
                {
                    "message_event_id": user_message_event.get("id", ""),
                    "attachments": serialized_attachments,
                }
            ),
        )
    image_summaries = await _summarize_uploaded_images(persisted_attachments)
    attachment_context = _build_attachment_context(
        conversation_id,
        persisted_attachments,
        image_summaries=image_summaries,
    )
    resolved_workspace = _resolve_workspace_root(payload_workspace_root)
    selected_keys = _dedupe_ticket_keys(payload_selected_ticket_keys)
    selected_ticket_contexts = await _load_selected_ticket_contexts(selected_keys, resolved_workspace)
    if selected_keys:
        add_orchestrator_event(
            conversation_id=conversation_id,
            task_id=None,
            agent="User",
            event_type="selected_tickets",
            content=json.dumps(
                {
                    "selected_ticket_keys": selected_keys,
                    "loaded_ticket_contexts": [str(item.get("ticket_key") or "") for item in selected_ticket_contexts],
                }
            ),
        )

    if payload_workflow_mode == 'stitch_generation':
        task = asyncio.create_task(
            _handle_stitch_generation_turn(
                conversation_id=conversation_id,
                user_message=payload_message,
                workspace_root=payload_workspace_root,
            )
        )
        _active_graph_tasks[conversation_id] = task
        task.add_done_callback(
            lambda completed_task: _finalize_chat_graph_task(conversation_id, completed_task)
        )

        return {
            "conversation_id": conversation_id,
            "uploaded_attachments": serialized_attachments,
            "selected_ticket_keys": selected_keys,
        }

    initial_state = _build_chat_initial_state(
        conversation_id=conversation_id,
        user_message=payload_message,
        workspace_root=payload_workspace_root,
        secondary_workspace_root=payload_secondary_workspace_root,
        workflow_mode=payload_workflow_mode,
        attachment_context=attachment_context,
        selected_ticket_keys=selected_keys,
        selected_ticket_contexts=selected_ticket_contexts,
    )
    graph_config = {"configurable": {"thread_id": conversation_id}}
    task = asyncio.create_task(chat_graph.ainvoke(initial_state, config=graph_config))
    _active_graph_tasks[conversation_id] = task
    task.add_done_callback(
        lambda completed_task: _finalize_chat_graph_task(conversation_id, completed_task)
    )

    return {
        "conversation_id": conversation_id,
        "uploaded_attachments": serialized_attachments,
        "selected_ticket_keys": selected_keys,
    }


@app.post("/api/orchestrator/stop")
async def orchestrator_stop(payload: OrchestratorStopRequest) -> dict[str, object]:
    requested_conversation = (payload.conversation_id or "").strip()
    if not requested_conversation:
        return {
            "cancelled": 0,
            "conversations": [],
            "note": "No conversation_id provided.",
        }
    add_orchestrator_event(
        conversation_id=requested_conversation,
        task_id=None,
        agent="Orchestrator Agent",
        event_type="turn_stop_requested",
        content="Stop requested by user.",
    )
    active_task = _active_graph_tasks.pop(requested_conversation, None)
    cancelled = 0

    if active_task and not active_task.done():
        active_task.cancel()
        cancelled = 1

    return {
        "cancelled": cancelled,
        "conversations": [requested_conversation],
    }


@app.post("/api/orchestrator/chat")
async def orchestrator_chat(payload: OrchestratorChatRequest) -> dict[str, object]:
    conversation_id = ensure_conversation(payload.conversation_id)
    add_message(conversation_id, role="user", agent=None, content=payload.message)
    selected_keys = _dedupe_ticket_keys(list(payload.selected_ticket_keys or []))
    resolved_workspace = _resolve_workspace_root(payload.workspace_root)
    selected_ticket_contexts = await _load_selected_ticket_contexts(selected_keys, resolved_workspace)

    initial_state = _build_chat_initial_state(
        conversation_id=conversation_id,
        user_message=payload.message,
        workspace_root=payload.workspace_root,
        secondary_workspace_root=payload.secondary_workspace_root,
        workflow_mode=payload.workflow_mode,
        attachment_context="",
        selected_ticket_keys=selected_keys,
        selected_ticket_contexts=selected_ticket_contexts,
    )
    graph_config = {"configurable": {"thread_id": conversation_id}}
    final_state = await chat_graph.ainvoke(initial_state, config=graph_config)

    return {
        "conversation_id": conversation_id,
        "reply": str(final_state.get("result") or ""),
        "tasks": list_orchestrator_tasks(conversation_id),
        "events": list_orchestrator_events(conversation_id),
    }


@app.get("/api/tasks")
def get_tasks() -> dict[str, object]:
    return {"tasks": list_tasks()}


@app.post("/api/tasks")
def post_task(payload: TaskCreateRequest) -> dict[str, object]:
    return {"task": create_task(payload.title, payload.details)}


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: str, payload: TaskStatusRequest) -> dict[str, object]:
    updated = update_task_status(task_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": updated}


_ALLOWED_SDD_FILES = {"requirements.md", "design.md", "tasks.md"}
_SDD_HISTORY_FILENAME = ".history.json"
_SDD_MANIFEST_FILENAME = ".spec.json"


def _resolve_sdd_workspace(workspace_path: str | None) -> Path:
    if workspace_path and workspace_path.strip():
        resolved = Path(workspace_path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Workspace path is not a directory: {resolved}")
        return resolved
    return _resolve_workspace_root(None)


def _sdd_specs_root(workspace_root: Path) -> Path:
    return (workspace_root / ".assist" / "specs").resolve()


def _sdd_history_path(spec_dir: Path) -> Path:
    return (spec_dir / _SDD_HISTORY_FILENAME).resolve()


def _sdd_manifest_path(spec_dir: Path) -> Path:
    return (spec_dir / _SDD_MANIFEST_FILENAME).resolve()


def _utc_iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _prompt_history_entry(
    *,
    message: str,
    entry_type: Literal["user", "system"] = "system",
    timestamp: str | None = None,
    entry_id: str | None = None,
) -> PromptHistoryEntry:
    return PromptHistoryEntry(
        id=entry_id or f"sdd-{uuid4()}",
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        message=str(message or "").strip(),
        type=entry_type,
    )


def _normalize_prompt_history_entries(entries: list[object]) -> list[PromptHistoryEntry]:
    normalized: list[PromptHistoryEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            normalized.append(PromptHistoryEntry(**entry))
            continue
        except Exception:
            pass

        message = str(entry.get("message") or "").strip()
        if not message:
            continue
        entry_type = "user" if str(entry.get("type") or "").strip().lower() == "user" else "system"
        normalized.append(
            _prompt_history_entry(
                message=message,
                entry_type=entry_type,
                timestamp=str(entry.get("timestamp") or "").strip() or None,
                entry_id=str(entry.get("id") or "").strip() or None,
            )
        )
    return normalized


def _read_sdd_history(spec_dir: Path) -> list[PromptHistoryEntry]:
    path = _sdd_history_path(spec_dir)
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return _normalize_prompt_history_entries(payload)


def _append_sdd_history(spec_dir: Path, entries: list[PromptHistoryEntry]) -> None:
    if not entries:
        return

    history_path = _sdd_history_path(spec_dir)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_sdd_history(spec_dir)
    merged = [*existing, *entries]
    payload = [entry.model_dump() if hasattr(entry, "model_dump") else entry.dict() for entry in merged]
    history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_sdd_spec_file(spec_dir: Path, filename: str) -> str:
    path = (spec_dir / filename).resolve()
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _derive_spec_task_summary(
    *,
    spec_name: str,
    requirements: str,
    design: str,
    tasks: str,
) -> str:
    for content in (requirements, design, tasks):
        lines = str(content or "").splitlines()
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            if text.startswith("#"):
                continue
            normalized = text.lstrip("-*").strip()
            if normalized:
                return normalized[:280]
    return f"SDD spec task for {spec_name}"


def _spec_updated_at_iso(spec_dir: Path) -> str:
    candidates: list[Path] = [spec_dir]
    candidates.extend((spec_dir / file_name).resolve() for file_name in _ALLOWED_SDD_FILES)
    candidates.append(_sdd_history_path(spec_dir))
    candidates.append(_sdd_manifest_path(spec_dir))

    latest_ts = 0.0
    for path in candidates:
        if not path.exists():
            continue
        try:
            latest_ts = max(latest_ts, path.stat().st_mtime)
        except Exception:
            continue

    if latest_ts <= 0:
        return datetime.now(timezone.utc).isoformat()
    return _utc_iso_from_timestamp(latest_ts)


def _list_sdd_specs(workspace_root: Path) -> list[SDDSpecSummary]:
    specs_root = _sdd_specs_root(workspace_root)
    if not specs_root.exists() or not specs_root.is_dir():
        return []

    summaries: list[SDDSpecSummary] = []
    for entry in specs_root.iterdir():
        if not entry.is_dir():
            continue
        file_names = sorted(
            file_name
            for file_name in _ALLOWED_SDD_FILES
            if (entry / file_name).exists()
        )
        has_history = _sdd_history_path(entry).exists()
        has_manifest = _sdd_manifest_path(entry).exists()
        if not file_names and not has_history and not has_manifest:
            continue

        summaries.append(
            SDDSpecSummary(
                spec_name=entry.name,
                updated_at=_spec_updated_at_iso(entry),
                files=file_names,
                has_full_bundle=len(file_names) == len(_ALLOWED_SDD_FILES),
            )
        )

    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries


def _normalize_sdd_prompt_context(items: list[SDDPromptContextItem]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in items:
        name = str(item.name or "").strip()
        context_type = str(item.type or "").strip().lower()
        if not name or context_type not in {"file", "folder", "snippet", "image"}:
            continue
        workspace_role = (
            "secondary"
            if str(item.workspace_role or "").strip().lower() == "secondary"
            else "primary"
        )

        if context_type in {"file", "folder"}:
            path = str(item.path or "").strip()
            absolute_path = str(item.absolute_path or "").strip()
            if not path:
                continue
            dedupe_key = (context_type, path, workspace_role)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(
                {
                    "name": name,
                    "type": context_type,
                    "path": path,
                    "workspace_role": workspace_role,
                }
            )
            if absolute_path:
                normalized[-1]["absolute_path"] = absolute_path
            continue

        if context_type == "snippet":
            content = str(item.content or "").strip()
            if not content:
                continue
            line_start = int(item.line_start) if isinstance(item.line_start, int) else None
            line_end = int(item.line_end) if isinstance(item.line_end, int) else None
            dedupe_key = ("snippet", name, content[:400])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            payload: dict[str, object] = {
                "name": name,
                "type": "snippet",
                "content": content,
            }
            if isinstance(line_start, int):
                payload["line_start"] = line_start
            if isinstance(line_end, int):
                payload["line_end"] = line_end
            normalized.append(payload)
            continue

        mime_type = str(item.mime_type or "image/png").strip() or "image/png"
        data_url = str(item.data_url or "").strip()
        dedupe_key = ("image", name, data_url[:400])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        payload = {
            "name": name,
            "type": "image",
            "mime_type": mime_type,
        }
        if data_url:
            payload["data_url"] = data_url
        normalized.append(payload)

    return normalized


def _decode_sdd_image_data_url(data_url: str) -> tuple[str, bytes]:
    value = str(data_url or "").strip()
    if not value.startswith("data:"):
        raise ValueError("Image context does not contain a valid data URL.")
    if "," not in value:
        raise ValueError("Image context data URL is malformed.")

    header, encoded = value.split(",", 1)
    normalized_header = header.lower()
    if ";base64" not in normalized_header:
        raise ValueError("Only base64-encoded image data URLs are supported.")
    mime_type = header[5:].split(";")[0].strip() or "image/png"
    image_bytes = base64.b64decode(encoded, validate=True)
    return mime_type, image_bytes


async def _summarize_sdd_prompt_images(context_items: list[dict[str, object]]) -> list[str]:
    if not context_items:
        return []

    settings = get_vision_settings()
    max_images = int(settings["max_images_per_turn"])
    max_bytes = int(settings["max_image_bytes"])
    per_image_timeout_seconds = float(settings["timeout_seconds"])
    vision_model = str(settings["model"] or "").strip()

    image_items = [
        item
        for item in context_items
        if str(item.get("type") or "").lower() == "image"
    ][: max(0, max_images)]

    if not image_items:
        return []

    summaries: list[str] = []
    for image_item in image_items:
        name = str(image_item.get("name") or "image")
        data_url = str(image_item.get("data_url") or "").strip()
        if not data_url:
            summaries.append(f"{name}: no image data provided.")
            continue

        try:
            mime_type, image_bytes = _decode_sdd_image_data_url(data_url)
            if len(image_bytes) > max_bytes:
                summaries.append(f"{name}: skipped analysis (file too large).")
                continue
            description = await asyncio.wait_for(
                provider_health_client.openai_vision_response(
                    prompt=(
                        "Describe this image for an engineering assistant. "
                        "Focus on visible UI elements, text, states, errors, and likely user intent. "
                        "Keep it concise."
                    ),
                    image_bytes=image_bytes,
                    mime_type=str(image_item.get("mime_type") or mime_type or "image/png"),
                    model=vision_model,
                ),
                timeout=per_image_timeout_seconds,
            )
            if description.strip():
                summaries.append(f"{name}: {description.strip()}")
        except Exception as exc:
            summaries.append(f"{name}: image analysis unavailable ({str(exc).strip() or 'unknown error'}).")
    return summaries


@app.post("/api/sdd/plan", response_model=SDDPlanResponse)
async def sdd_plan(payload: SDDPlanRequest) -> SDDPlanResponse:
    try:
        workspace_root = _resolve_sdd_workspace(payload.workspace_path)
        if payload.mode == "edit" and not str(payload.spec_name or "").strip():
            raise ValueError("spec_name is required for edit mode.")
        if payload.mode == "edit" and payload.current_bundle is None:
            raise ValueError("current_bundle is required for edit mode.")

        normalized_context = _normalize_sdd_prompt_context(payload.prompt_context)
        image_summaries = await _summarize_sdd_prompt_images(normalized_context)

        planner_context = [
            {key: value for key, value in item.items() if key != "data_url"}
            for item in normalized_context
        ]
        result = await sdd_planner_agent.process_prompt(
            prompt=payload.prompt,
            raw_prompt=payload.raw_prompt,
            prompt_context=planner_context,
            workspace_path=str(workspace_root),
            file_tree=payload.file_tree,
            secondary_workspace_path=payload.secondary_workspace_path,
            secondary_file_tree=payload.secondary_file_tree,
            spec_name=payload.spec_name,
            mode=payload.mode,
            current_bundle=payload.current_bundle.model_dump() if payload.current_bundle else None,
            image_summaries=image_summaries,
        )
        resolved_spec_name = str(result.get("spec_name") or "").strip()
        spec_dir = (_sdd_specs_root(workspace_root) / resolved_spec_name).resolve()
        specs_root = _sdd_specs_root(workspace_root)
        if spec_dir.parent != specs_root:
            raise ValueError("Invalid generated spec path.")

        history_entries = [
            PromptHistoryEntry(**entry)
            for entry in (result.get("history") if isinstance(result.get("history"), list) else [])
            if isinstance(entry, dict)
        ]

        persisted_history = [
            _prompt_history_entry(
                message=payload.prompt,
                entry_type="user",
            ),
            *history_entries,
        ]
        _append_sdd_history(spec_dir, persisted_history)

        return SDDPlanResponse(
            spec_name=resolved_spec_name,
            requirements=str(result.get("requirements") or ""),
            design=str(result.get("design") or ""),
            tasks=str(result.get("tasks") or ""),
            history=history_entries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD plan request.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to generate SDD plan.") from exc


async def _run_sdd_generation_background(
    spec_name: str,
    workspace_path: str,
    payload: SDDGenerateAsyncRequest,
) -> None:
    """
    Runs SDDPlannerAgent.process_prompt() as a background task.
    On success: marks the spec_task as 'generated' with file paths.
    On failure: sets status to 'failed'.
    """
    def _task_still_exists(target_spec_name: str) -> bool:
        try:
            existing = get_spec_task_by_name(
                spec_name=target_spec_name,
                workspace_path=workspace_path,
            )
            return existing is not None
        except Exception:
            return True

    try:
        workspace_root = Path(workspace_path)
        if not _task_still_exists(spec_name):
            return

        normalized_context = _normalize_sdd_prompt_context(payload.prompt_context)
        image_summaries = await _summarize_sdd_prompt_images(normalized_context)
        planner_context = [
            {key: value for key, value in item.items() if key != "data_url"}
            for item in normalized_context
        ]
        result = await sdd_planner_agent.process_prompt(
            prompt=payload.prompt,
            raw_prompt=payload.raw_prompt,
            prompt_context=planner_context,
            workspace_path=str(workspace_root),
            file_tree=payload.file_tree,
            secondary_workspace_path=payload.secondary_workspace_path,
            secondary_file_tree=payload.secondary_file_tree,
            spec_name=payload.spec_name,
            mode=payload.mode,
            current_bundle=payload.current_bundle.model_dump() if payload.current_bundle else None,
            image_summaries=image_summaries,
        )
        resolved_spec_name = str(result.get("spec_name") or "").strip()
        specs_root = _sdd_specs_root(workspace_root)
        spec_dir = (specs_root / resolved_spec_name).resolve()
        if spec_dir.parent != specs_root:
            raise ValueError("Invalid generated spec path.")

        if not _task_still_exists(spec_name) and not _task_still_exists(resolved_spec_name):
            if spec_dir.exists() and spec_dir.is_dir():
                shutil.rmtree(spec_dir, ignore_errors=True)
            return

        history_entries = [
            PromptHistoryEntry(**entry)
            for entry in (result.get("history") if isinstance(result.get("history"), list) else [])
            if isinstance(entry, dict)
        ]
        persisted_history = [
            _prompt_history_entry(message=payload.prompt, entry_type="user"),
            *history_entries,
        ]
        _append_sdd_history(spec_dir, persisted_history)

        requirements_path = spec_dir / "requirements.md"
        design_path = spec_dir / "design.md"
        tasks_path = spec_dir / "tasks.md"

        mark_spec_task_generated(
            spec_name=resolved_spec_name,
            workspace_path=str(workspace_root),
            spec_path=str(spec_dir),
            requirements_path=str(requirements_path),
            design_path=str(design_path),
            tasks_path=str(tasks_path),
        )
    except Exception:
        if not _task_still_exists(spec_name):
            return
        set_spec_task_status(spec_name=spec_name, status="failed", workspace_path=workspace_path)


@app.post("/api/sdd/generate-async", response_model=SDDGenerateAsyncResponse)
async def sdd_generate_async(
    payload: SDDGenerateAsyncRequest,
    background_tasks: BackgroundTasks,
) -> SDDGenerateAsyncResponse:
    """
    Creates a spec_tasks DB entry immediately (status='generating'), kicks off generation
    as a background task, and returns straight away. The frontend should poll
    GET /api/spec-tasks/{spec_name} to track status.
    """
    try:
        workspace_root = _resolve_sdd_workspace(payload.workspace_path)
        resolved_spec_name = normalize_spec_name(payload.spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid request.") from exc

    if payload.mode == "edit" and payload.current_bundle is None:
        raise HTTPException(status_code=400, detail="current_bundle is required for edit mode.")

    existing = get_spec_task_by_name(
        spec_name=resolved_spec_name,
        workspace_path=str(workspace_root),
    )
    if existing and existing.get("status") == SPEC_TASK_STATUS_GENERATING:
        raise HTTPException(status_code=409, detail=f"Spec '{resolved_spec_name}' is already generating.")

    try:
        task_row = create_generating_spec_task(
            spec_name=resolved_spec_name,
            workspace_path=str(workspace_root),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to create spec task.") from exc

    background_tasks.add_task(
        _run_sdd_generation_background,
        resolved_spec_name,
        str(workspace_root),
        payload,
    )

    return SDDGenerateAsyncResponse(
        spec_name=resolved_spec_name,
        spec_task_id=str(task_row["id"]),
        status="generating",
    )


@app.post("/api/sdd/save", response_model=SDDSaveResponse)
async def sdd_save(payload: SDDSaveRequest) -> SDDSaveResponse:
    try:
        workspace_root = _resolve_sdd_workspace(payload.workspace_path)
        spec_name = normalize_spec_name(payload.spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD save request.") from exc

    file_name = str(payload.file_name or "").strip()
    if file_name not in _ALLOWED_SDD_FILES:
        raise HTTPException(status_code=400, detail="file_name must be requirements.md, design.md, or tasks.md")

    spec_dir = (workspace_root / ".assist" / "specs" / spec_name).resolve()
    spec_dir.mkdir(parents=True, exist_ok=True)
    target_path = (spec_dir / file_name).resolve()
    if target_path.parent != spec_dir:
        raise HTTPException(status_code=400, detail="Invalid target path.")

    try:
        target_path.write_text(payload.content, encoding="utf-8")
        _append_sdd_history(
            spec_dir,
            [
                _prompt_history_entry(
                    message=f"Saved to file: {file_name}",
                    entry_type="system",
                )
            ],
        )
    except Exception as exc:
        return SDDSaveResponse(success=False, file_path=str(target_path), error=str(exc).strip() or "File save failed.")

    return SDDSaveResponse(success=True, file_path=str(target_path), error=None)


@app.post("/api/sdd/import-bundle", response_model=SpecTaskResponse)
async def sdd_import_bundle(payload: SDDBundleImportRequest) -> SpecTaskResponse:
    try:
        workspace_root = _resolve_sdd_workspace(payload.workspace_path)
        resolved_spec_name = normalize_spec_name(payload.spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD import request.") from exc

    source_dir = Path(payload.bundle_path).expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(status_code=400, detail="Bundle path must be an existing directory.")

    files_content: dict[str, str] = {}
    missing_files: list[str] = []
    for file_name in ("requirements.md", "design.md", "tasks.md"):
        source_file = (source_dir / file_name).resolve()
        if source_file.parent != source_dir or not source_file.exists() or not source_file.is_file():
            missing_files.append(file_name)
            continue
        try:
            files_content[file_name] = source_file.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read {file_name}: {str(exc).strip() or 'read error'}") from exc

    if missing_files:
        joined = ", ".join(missing_files)
        raise HTTPException(status_code=400, detail=f"Bundle is missing required files: {joined}.")

    specs_root = _sdd_specs_root(workspace_root)
    spec_dir = (specs_root / resolved_spec_name).resolve()
    if spec_dir.parent != specs_root:
        raise HTTPException(status_code=400, detail="Invalid spec path.")
    create_task_request = SpecTaskCreateRequest(
        spec_name=resolved_spec_name,
        workspace_path=str(workspace_root),
        summary=payload.summary,
    )
    if spec_dir.exists():
        if not spec_dir.is_dir():
            raise HTTPException(status_code=400, detail="Spec path exists but is not a directory.")
        try:
            is_same_bundle_dir = source_dir.samefile(spec_dir)
        except OSError:
            is_same_bundle_dir = source_dir == spec_dir

        if not is_same_bundle_dir:
            raise HTTPException(status_code=409, detail=f"Spec '{resolved_spec_name}' already exists.")

        return await create_spec_task(create_task_request)

    spec_dir.mkdir(parents=True, exist_ok=False)

    try:
        for file_name in ("requirements.md", "design.md", "tasks.md"):
            target_file = (spec_dir / file_name).resolve()
            if target_file.parent != spec_dir:
                raise HTTPException(status_code=400, detail="Invalid target path.")
            target_file.write_text(files_content[file_name], encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to save imported bundle.") from exc

    _append_sdd_history(
        spec_dir,
        [
            _prompt_history_entry(
                message=f"Imported spec bundle from: {source_dir}",
                entry_type="system",
            )
        ],
    )

    return await create_spec_task(create_task_request)


@app.delete("/api/sdd/specs/{spec_name}", response_model=SDDSpecDeleteResponse)
async def sdd_delete_spec(spec_name: str, workspace_path: str | None = None) -> SDDSpecDeleteResponse:
    try:
        workspace_root = _resolve_sdd_workspace(workspace_path)
        resolved_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD delete request.") from exc

    specs_root = _sdd_specs_root(workspace_root)
    spec_dir = (specs_root / resolved_spec_name).resolve()
    if spec_dir.parent != specs_root:
        raise HTTPException(status_code=400, detail="Invalid spec path.")
    if not spec_dir.exists() or not spec_dir.is_dir():
        raise HTTPException(status_code=404, detail="SDD spec not found.")

    try:
        shutil.rmtree(spec_dir)
    except Exception as exc:
        return SDDSpecDeleteResponse(
            success=False,
            spec_name=resolved_spec_name,
            deleted_path=str(spec_dir),
            error=str(exc).strip() or "Failed to delete SDD spec bundle.",
        )

    return SDDSpecDeleteResponse(
        success=True,
        spec_name=resolved_spec_name,
        deleted_path=str(spec_dir),
        error=None,
    )


@app.get("/api/sdd/specs", response_model=SDDSpecListResponse)
async def sdd_specs(workspace_path: str | None = None) -> SDDSpecListResponse:
    try:
        workspace_root = _resolve_sdd_workspace(workspace_path)
        return SDDSpecListResponse(specs=_list_sdd_specs(workspace_root))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to list SDD specs.") from exc


@app.get("/api/sdd/specs/{spec_name}", response_model=SDDSpecBundleResponse)
async def sdd_spec_bundle(spec_name: str, workspace_path: str | None = None) -> SDDSpecBundleResponse:
    try:
        workspace_root = _resolve_sdd_workspace(workspace_path)
        resolved_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD spec request.") from exc

    specs_root = _sdd_specs_root(workspace_root)
    spec_dir = (specs_root / resolved_spec_name).resolve()
    if spec_dir.parent != specs_root:
        raise HTTPException(status_code=400, detail="Invalid spec path.")
    if not spec_dir.exists() or not spec_dir.is_dir():
        raise HTTPException(status_code=404, detail="SDD spec not found.")

    requirements = _read_sdd_spec_file(spec_dir, "requirements.md")
    design = _read_sdd_spec_file(spec_dir, "design.md")
    tasks = _read_sdd_spec_file(spec_dir, "tasks.md")
    if not requirements and not design and not tasks:
        raise HTTPException(status_code=404, detail="SDD spec bundle files are missing.")

    history = _read_sdd_history(spec_dir)
    if not history:
        history = [
            _prompt_history_entry(
                message=f"Loaded existing spec bundle: {resolved_spec_name}",
                entry_type="system",
            )
        ]

    return SDDSpecBundleResponse(
        spec_name=resolved_spec_name,
        requirements=requirements,
        design=design,
        tasks=tasks,
        history=history,
        updated_at=_spec_updated_at_iso(spec_dir),
    )


@app.get("/api/sdd/specs/{spec_name}/files/{file_name}")
async def sdd_spec_file(
    spec_name: str,
    file_name: str,
    workspace_path: str | None = None,
) -> FileResponse:
    try:
        workspace_root = _resolve_sdd_workspace(workspace_path)
        resolved_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid SDD spec file request.") from exc

    normalized_file_name = str(file_name or "").strip()
    if normalized_file_name not in _ALLOWED_SDD_FILES:
        raise HTTPException(status_code=400, detail="file_name must be requirements.md, design.md, or tasks.md")

    specs_root = _sdd_specs_root(workspace_root)
    spec_dir = (specs_root / resolved_spec_name).resolve()
    if spec_dir.parent != specs_root:
        raise HTTPException(status_code=400, detail="Invalid spec path.")
    if not spec_dir.exists() or not spec_dir.is_dir():
        raise HTTPException(status_code=404, detail="SDD spec not found.")

    target_path = (spec_dir / normalized_file_name).resolve()
    if target_path.parent != spec_dir:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="SDD spec file not found.")

    return FileResponse(
        path=str(target_path),
        media_type="text/markdown",
        headers={"Content-Disposition": "inline"},
    )


@app.post("/api/spec-tasks", response_model=SpecTaskResponse)
async def create_spec_task(payload: SpecTaskCreateRequest) -> SpecTaskResponse:
    """
    Promotes a generated spec to 'pending' (i.e. added to workflow tasks).
    If a DB row already exists (created during async generation), updates it.
    Falls back to creating a new row for legacy compatibility.
    """
    try:
        workspace_root = _resolve_sdd_workspace(payload.workspace_path)
        resolved_spec_name = normalize_spec_name(payload.spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task request.") from exc

    specs_root = _sdd_specs_root(workspace_root)
    spec_dir = (specs_root / resolved_spec_name).resolve()
    if spec_dir.parent != specs_root:
        raise HTTPException(status_code=400, detail="Invalid spec path.")
    if not spec_dir.exists() or not spec_dir.is_dir():
        raise HTTPException(status_code=404, detail="SDD spec not found.")

    requirements = _read_sdd_spec_file(spec_dir, "requirements.md")
    design = _read_sdd_spec_file(spec_dir, "design.md")
    tasks = _read_sdd_spec_file(spec_dir, "tasks.md")
    if not requirements and not design and not tasks:
        raise HTTPException(status_code=404, detail="SDD spec bundle files are missing.")

    requirements_path = (spec_dir / "requirements.md").resolve()
    design_path = (spec_dir / "design.md").resolve()
    tasks_path = (spec_dir / "tasks.md").resolve()
    if not requirements_path.exists() or not design_path.exists() or not tasks_path.exists():
        raise HTTPException(status_code=404, detail="SDD spec bundle files are missing.")

    normalized_summary = str(payload.summary or "").strip()
    summary = normalized_summary or _derive_spec_task_summary(
        spec_name=resolved_spec_name,
        requirements=requirements,
        design=design,
        tasks=tasks,
    )

    existing = get_spec_task_by_name(
        spec_name=resolved_spec_name,
        workspace_path=str(workspace_root),
    )

    try:
        if existing:
            spec_task = promote_spec_task_to_pending(
                spec_name=resolved_spec_name,
                workspace_path=str(workspace_root),
                summary=summary,
            )
            if spec_task is None:
                raise ValueError("Failed to promote spec task to pending.")
        else:
            spec_task = upsert_spec_task(
                spec_name=resolved_spec_name,
                workspace_path=str(workspace_root),
                spec_path=str(spec_dir),
                requirements_path=str(requirements_path),
                design_path=str(design_path),
                tasks_path=str(tasks_path),
                summary=summary,
                status=SPEC_TASK_STATUS_PENDING,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task request.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to save spec task.") from exc

    try:
        latest_rows = list_jira_fetches(1)
        latest_tickets: list[dict[str, object]] = []
        latest_kanban_columns: list[dict[str, object]] = []
        latest_fetched_at = ""
        if latest_rows:
            latest = latest_rows[0]
            latest_fetched_at = str(latest.get("created_at") or "")
            try:
                parsed_tickets = json.loads(str(latest.get("tickets_json") or "[]"))
                if isinstance(parsed_tickets, list):
                    latest_tickets = [item for item in parsed_tickets if isinstance(item, dict)]
            except Exception:
                latest_tickets = []
            try:
                parsed_columns = json.loads(str(latest.get("kanban_columns_json") or "[]"))
                if isinstance(parsed_columns, list):
                    latest_kanban_columns = [item for item in parsed_columns if isinstance(item, dict)]
            except Exception:
                latest_kanban_columns = []

        pipeline_engine.refresh_backlog_from_tickets(
            latest_tickets,
            kanban_columns=latest_kanban_columns,
            fetched_at=latest_fetched_at or datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        # Spec task persistence succeeded; backlog sync can be retried from Pipelines page.
        pass

    return SpecTaskResponse(**spec_task)


@app.get("/api/spec-tasks", response_model=SpecTaskListResponse)
async def get_spec_tasks(
    workspace_path: str | None = None,
    status: str | None = None,
) -> SpecTaskListResponse:
    rows = list_spec_tasks(limit=1000)

    if workspace_path and workspace_path.strip():
        try:
            target_workspace = str(_resolve_sdd_workspace(workspace_path))
            filtered: list[dict[str, object]] = []
            for row in rows:
                row_workspace = str(row.get("workspace_path") or "").strip()
                if not row_workspace:
                    continue
                try:
                    normalized_row_workspace = str(Path(row_workspace).expanduser().resolve())
                except Exception:
                    normalized_row_workspace = row_workspace
                if normalized_row_workspace == target_workspace:
                    filtered.append(row)
            rows = filtered
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc

    if status and status.strip():
        normalized_status_filter = str(status).strip().lower()
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == normalized_status_filter]

    return SpecTaskListResponse(spec_tasks=[SpecTaskResponse(**row) for row in rows])


@app.get("/api/spec-tasks/{spec_name}", response_model=SpecTaskResponse)
async def get_spec_task(
    spec_name: str,
    workspace_path: str | None = None,
) -> SpecTaskResponse:
    """Returns a single spec_task by spec_name. Used by the frontend to poll generation status."""
    try:
        resolved_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec name.") from exc

    resolved_workspace: str | None = None
    if workspace_path and workspace_path.strip():
        try:
            resolved_workspace = str(_resolve_sdd_workspace(workspace_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc

    row = get_spec_task_by_name(spec_name=resolved_spec_name, workspace_path=resolved_workspace)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Spec task '{resolved_spec_name}' not found.")

    return SpecTaskResponse(**row)


@app.patch("/api/spec-tasks/{spec_name}/status", response_model=SpecTaskResponse)
async def patch_spec_task_status(
    spec_name: str,
    payload: SpecTaskStatusUpdateRequest,
    workspace_path: str | None = None,
) -> SpecTaskResponse:
    try:
        normalized_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task status request.") from exc

    target_workspace = ""
    if workspace_path and workspace_path.strip():
        try:
            target_workspace = str(_resolve_sdd_workspace(workspace_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc

    existing = get_spec_task_by_name(
        spec_name=normalized_spec_name,
        workspace_path=target_workspace or None,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Spec task not found.")

    updated = set_spec_task_status(
        spec_name=normalized_spec_name,
        status=payload.status,
        workspace_path=target_workspace or None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Spec task not found.")

    return SpecTaskResponse(**updated)


@app.patch("/api/spec-tasks/{spec_name}/dependencies", response_model=SpecTaskResponse)
async def patch_spec_task_dependencies(
    spec_name: str,
    payload: SpecTaskDependenciesUpdateRequest,
    workspace_path: str | None = None,
) -> SpecTaskResponse:
    try:
        normalized_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task dependency request.") from exc

    target_workspace = ""
    if workspace_path and workspace_path.strip():
        try:
            target_workspace = str(_resolve_sdd_workspace(workspace_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc

    normalized_dependency_mode = str(payload.dependency_mode or "independent").strip().lower()

    normalized_parent_spec_name = ""
    if payload.parent_spec_name and str(payload.parent_spec_name).strip():
        try:
            normalized_parent_spec_name = normalize_spec_name(payload.parent_spec_name, "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid parent spec name.") from exc

    normalized_depends_on: list[str] = []
    seen_depends_on: set[str] = set()
    for item in payload.depends_on:
        normalized_key = str(item or "").strip().upper()
        if not normalized_key or normalized_key in seen_depends_on:
            continue
        if normalized_key == normalized_spec_name:
            continue
        seen_depends_on.add(normalized_key)
        normalized_depends_on.append(normalized_key)

    if normalized_dependency_mode == "subtask":
        if normalized_parent_spec_name and normalized_parent_spec_name == normalized_spec_name:
            raise HTTPException(status_code=400, detail="Spec task cannot depend on itself.")
        if normalized_parent_spec_name and normalized_parent_spec_name not in seen_depends_on:
            normalized_depends_on.insert(0, normalized_parent_spec_name)
        if not normalized_depends_on:
            raise HTTPException(status_code=400, detail="depends_on must include at least one dependency for subtasks.")
    else:
        normalized_parent_spec_name = ""
        normalized_depends_on = []

    try:
        updated = update_spec_task_dependencies_in_db(
            spec_name=normalized_spec_name,
            workspace_path=target_workspace or None,
            dependency_mode=normalized_dependency_mode,
            parent_spec_name=normalized_parent_spec_name or None,
            parent_spec_task_id=None,
            depends_on=normalized_depends_on,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task dependency request.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to update spec task dependencies.") from exc

    if not updated:
        raise HTTPException(status_code=404, detail="Spec task not found.")

    return SpecTaskResponse(**updated)


@app.delete("/api/spec-tasks/{spec_name}", response_model=SpecTaskDeleteResponse)
async def delete_spec_task(spec_name: str, workspace_path: str | None = None) -> SpecTaskDeleteResponse:
    try:
        normalized_spec_name = normalize_spec_name(spec_name, "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task delete request.") from exc

    target_workspace = ""
    if workspace_path and workspace_path.strip():
        try:
            target_workspace = str(_resolve_sdd_workspace(workspace_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid workspace path.") from exc

    matching_task: dict[str, object] | None = None
    for row in list_spec_tasks(limit=2000):
        row_spec_name = str(row.get("spec_name") or "").strip()
        if row_spec_name != normalized_spec_name:
            continue

        if target_workspace:
            row_workspace = str(row.get("workspace_path") or "").strip()
            if not row_workspace:
                continue
            try:
                normalized_row_workspace = str(Path(row_workspace).expanduser().resolve())
            except Exception:
                normalized_row_workspace = row_workspace
            if normalized_row_workspace != target_workspace:
                continue

        matching_task = row
        break

    if not matching_task:
        raise HTTPException(status_code=404, detail="Spec task not found.")

    spec_task_id = str(matching_task.get("id") or "").strip()
    if not spec_task_id:
        raise HTTPException(status_code=500, detail="Spec task id is missing.")

    try:
        deleted = delete_spec_task_by_id(spec_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Invalid spec task id.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc).strip() or "Failed to delete spec task.") from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Spec task not found.")

    try:
        latest_rows = list_jira_fetches(1)
        latest_tickets: list[dict[str, object]] = []
        latest_kanban_columns: list[dict[str, object]] = []
        latest_fetched_at = ""
        if latest_rows:
            latest = latest_rows[0]
            latest_fetched_at = str(latest.get("created_at") or "")
            try:
                parsed_tickets = json.loads(str(latest.get("tickets_json") or "[]"))
                if isinstance(parsed_tickets, list):
                    latest_tickets = [item for item in parsed_tickets if isinstance(item, dict)]
            except Exception:
                latest_tickets = []
            try:
                parsed_columns = json.loads(str(latest.get("kanban_columns_json") or "[]"))
                if isinstance(parsed_columns, list):
                    latest_kanban_columns = [item for item in parsed_columns if isinstance(item, dict)]
            except Exception:
                latest_kanban_columns = []

        pipeline_engine.refresh_backlog_from_tickets(
            latest_tickets,
            kanban_columns=latest_kanban_columns,
            fetched_at=latest_fetched_at or datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        # Spec task deletion succeeded; backlog sync can be retried from Pipelines page.
        pass

    return SpecTaskDeleteResponse(
        success=True,
        id=spec_task_id,
        spec_name=normalized_spec_name,
        workspace_path=str(matching_task.get("workspace_path") or ""),
        deleted=True,
        error=None,
    )


@app.get("/api/fs/browse")
def fs_browse(path: str | None = None) -> dict[str, object]:
    try:
        return list_directory(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/fs/tree")
def fs_tree(
    path: str | None = None,
    include_files: bool = True,
    show_hidden: bool = False,
) -> dict[str, object]:
    try:
        return list_tree_columns(path, include_files=include_files, show_hidden=show_hidden)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/fs/search")
def fs_search(
    path: str | None = None,
    query: str = "",
    limit: int = 25,
    include_files: bool = True,
    show_hidden: bool = False,
) -> dict[str, object]:
    try:
        return search_tree_entries(
            path=path,
            query=query,
            limit=limit,
            include_files=include_files,
            show_hidden=show_hidden,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/fs/mkdir")
def fs_mkdir(payload: FsMkdirRequest) -> dict[str, object]:
    try:
        return {"directory": create_directory(payload.path, payload.name)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/rename")
def fs_rename(payload: FsRenameRequest) -> dict[str, object]:
    try:
        return {"entry": rename_entry(payload.path, payload.name)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/fs/rmdir")
def fs_rmdir(payload: FsDeleteRequest) -> dict[str, object]:
    try:
        return {"entry": delete_empty_directory(payload.path)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Slack integration
# ---------------------------------------------------------------------------

_SLACK_BOT_USER_ID = os.getenv("SLACK_BOT_USER_ID", "")


async def _handle_slack_event_background(
    text: str,
    channel: str,
    thread_ts: str | None,
    sender_user_id: str,
) -> None:
    """Submit Slack message to the orchestrator and reply in the same channel."""
    conversation_id = ensure_conversation(None)
    add_message(conversation_id, role="user", agent=None, content=text)
    add_orchestrator_event(
        conversation_id=conversation_id,
        task_id=None,
        agent="Slack Bot",
        event_type="slack_inbound_message",
        content=json.dumps({"channel": channel, "user": sender_user_id, "text": text}),
    )
    initial_state = _build_chat_initial_state(
        conversation_id=conversation_id,
        user_message=text,
        workspace_root=None,
        secondary_workspace_root=None,
        workflow_mode="auto",
        attachment_context="",
        selected_ticket_keys=[],
        selected_ticket_contexts=[],
    )
    graph_config = {"configurable": {"thread_id": conversation_id}}
    try:
        final_state = await chat_graph.ainvoke(initial_state, config=graph_config)
        reply_text = str(final_state.get("result") or "")
    except Exception as exc:
        reply_text = f"Sorry, I encountered an error: {str(exc).strip() or type(exc).__name__}"

    if reply_text:
        try:
            await slack_agent.post_message(channel, reply_text, thread_ts=thread_ts)
        except Exception as exc:
            print(f"[Slack] Failed to post reply to channel {channel!r}: {exc}")


@app.get("/api/slack/status")
def slack_status() -> dict[str, object]:
    return {
        "configured": slack_agent.is_configured(),
        "bot_user_id": _SLACK_BOT_USER_ID or None,
        "default_channel": os.getenv("SLACK_DEFAULT_CHANNEL", ""),
        "build_channel": os.getenv("SLACK_BUILD_NOTIFICATIONS_CHANNEL", ""),
    }


@app.post("/api/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict[str, object]:
    body = await request.body()

    # Verify Slack request signature when signing secret is configured.
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if slack_agent.client.signing_secret:
        if not slack_agent.client.verify_signature(body, timestamp, signature):
            raise HTTPException(status_code=403, detail="Invalid Slack signature")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Slack URL verification challenge (sent during app setup).
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event", {})
    event_type = event.get("type", "")

    # Only handle direct messages and app_mention events; ignore bot messages.
    if event_type not in {"message", "app_mention"}:
        return {"ok": True}
    if event.get("bot_id") or event.get("subtype"):
        return {"ok": True}

    text: str = str(event.get("text") or "").strip()
    channel: str = str(event.get("channel") or "").strip()
    thread_ts: str | None = event.get("thread_ts") or event.get("ts") or None
    sender_user_id: str = str(event.get("user") or "").strip()

    # Strip the bot mention prefix if present (e.g. "<@U12345> hello" → "hello").
    if _SLACK_BOT_USER_ID and text.startswith(f"<@{_SLACK_BOT_USER_ID}>"):
        text = text[len(f"<@{_SLACK_BOT_USER_ID}>"):].strip()

    if not text or not channel:
        return {"ok": True}

    background_tasks.add_task(
        _handle_slack_event_background,
        text,
        channel,
        thread_ts,
        sender_user_id,
    )
    return {"ok": True}


# ── Git API ───────────────────────────────────────────────────────────────────


class GitBranchBody(BaseModel):
    workspace: str
    branch_name: str
    base_branch: str | None = None


class GitSwitchBranchBody(BaseModel):
    workspace: str
    branch: str


PROTECTED_GIT_BRANCHES: set[str] = {"main", "master", "develop", "development", "dev"}


class GitFetchBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None


class GitPullBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None
    ff_only: bool = True
    rebase: bool = False


class GitPushBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None
    set_upstream: bool = True


class GitForceSyncBody(BaseModel):
    workspace: str
    remote: str = "origin"
    branch: str | None = None


class GitCommitBody(BaseModel):
    workspace: str
    message: str
    add_all: bool = True


class GitStashBody(BaseModel):
    workspace: str
    message: str | None = None


class GitOpenInCursorBody(BaseModel):
    workspace: str


class GitOpenInFilesBody(BaseModel):
    workspace: str


class GitPrBody(BaseModel):
    workspace: str
    title: str
    body: str = ""
    target_branch: str = "main"
    draft: bool = False
    push_first: bool = True
    platform: str = "auto"


class GitWorkflowConfigBody(BaseModel):
    workflows: dict[str, dict[str, object]] | None = None
    workflow_key: Literal["chat", "pipeline", "pipeline_spec"] | None = None
    phases: list[dict[str, object]] | None = None
    settings: dict[str, object] | None = None


@app.get("/api/git/status")
async def git_status(workspace: str = "") -> dict:
    """Return git status for the given workspace path."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_status(workspace)


@app.get("/api/git/status/stream")
async def git_status_stream(workspace: str = "") -> StreamingResponse:
    """Stream git status updates for the given workspace path."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")

    async def event_generator():
        last_payload = ""
        last_online: bool | None = None
        try:
            while True:
                if _stream_shutdown_requested():
                    break
                is_connected = connection_monitor.is_connected()
                if is_connected != last_online:
                    last_online = is_connected
                    yield _connectivity_marker_event(is_connected)
                if not is_connected:
                    yield ': offline\n\n'
                    await asyncio.sleep(1)
                    continue
                payload = json.dumps(await git_agent.get_status(workspace), sort_keys=True)
                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
                else:
                    # Keep the SSE connection alive for clients/proxies between updates.
                    yield ": keep-alive\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/git/workflow-config")
async def git_workflow_config_get() -> dict[str, object]:
    return get_git_workflow_settings()


@app.put("/api/git/workflow-config")
async def git_workflow_config_put(body: GitWorkflowConfigBody) -> dict[str, object]:
    return update_git_workflow_settings(
        workflows=body.workflows,
        workflow_key=body.workflow_key,
        phases=body.phases,
        workflow_settings=body.settings,
    )


@app.get("/api/git/branches")
async def git_branches(workspace: str = "") -> dict:
    """List all branches for the given workspace path."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")
    return await git_agent.get_branches(workspace)


@app.post("/api/git/branch")
async def git_create_branch(body: GitBranchBody) -> dict:
    """Create a new branch in the given workspace."""
    return await git_agent.create_branch(
        body.workspace, body.branch_name, body.base_branch
    )


@app.patch("/api/git/branch")
async def git_switch_branch(body: GitSwitchBranchBody) -> dict:
    """Switch the active branch in the given workspace."""
    workspace = body.workspace.strip()
    branch = body.branch.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")
    if not branch:
        raise HTTPException(status_code=400, detail="branch is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.switch_branch(workspace, branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to switch branch")

    return {"ok": True, "git": result}


@app.delete("/api/git/branch")
async def git_delete_branch(
    workspace: str = "",
    branch: str = "",
    remote: bool = False,
    force: bool = False,
    remote_name: str = "origin",
) -> dict:
    """Delete a local or remote branch in the given workspace."""
    normalized_workspace = workspace.strip()
    normalized_branch = branch.strip()
    normalized_remote_name = remote_name.strip() or "origin"

    if not normalized_workspace:
        raise HTTPException(status_code=400, detail="workspace is required")
    if not normalized_branch:
        raise HTTPException(status_code=400, detail="branch is required")

    if remote and normalized_branch.startswith(f"{normalized_remote_name}/"):
        normalized_branch = normalized_branch[len(normalized_remote_name) + 1 :]

    if not normalized_branch:
        raise HTTPException(status_code=400, detail="branch is required")

    if normalized_branch.lower() in PROTECTED_GIT_BRANCHES:
        raise HTTPException(
            status_code=400,
            detail="Protected branches cannot be deleted from this view",
        )

    detection = await git_agent.detect_git(normalized_workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    current_branch = str(detection.get("branch") or "").strip()
    if normalized_branch == current_branch:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the currently checked-out branch",
        )

    if remote:
        result = await git_agent.delete_remote_branch(
            normalized_workspace,
            normalized_branch,
            remote=normalized_remote_name,
        )
    else:
        result = await git_agent.delete_branch(
            normalized_workspace,
            normalized_branch,
            force=force,
        )

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or "Failed to delete branch",
        )

    return {"ok": True, "git": result}


@app.post("/api/git/fetch")
async def git_fetch(body: GitFetchBody) -> dict:
    """Fetch latest refs from remote without mutating local working tree."""
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.fetch(
        workspace=workspace,
        remote=remote,
        branch=branch,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to fetch latest changes")

    return {"ok": True, "git": result}


@app.post("/api/git/pull")
async def git_pull(body: GitPullBody) -> dict:
    """Pull latest changes for the current workspace branch."""
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.pull(
        workspace=workspace,
        remote=remote,
        branch=branch,
        ff_only=bool(body.ff_only),
        rebase=bool(body.rebase),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to pull latest changes")

    return {"ok": True, "git": result}


@app.post("/api/git/push")
async def git_push(body: GitPushBody) -> dict:
    """Push local commits for the current workspace branch."""
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.push(
        workspace=workspace,
        remote=remote,
        branch=branch,
        set_upstream=bool(body.set_upstream),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to push branch")

    return {"ok": True, "git": result}


@app.post("/api/git/force-sync")
async def git_force_sync(body: GitForceSyncBody) -> dict:
    """Force the local branch to match the remote branch, discarding local changes."""
    workspace = body.workspace.strip()
    remote = body.remote.strip() or "origin"
    branch = body.branch.strip() if isinstance(body.branch, str) and body.branch.strip() else None
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    detection = await git_agent.detect_git(workspace)
    if not detection.get("is_git_repo"):
        raise HTTPException(status_code=422, detail="Workspace is not a git repository")

    result = await git_agent.force_sync(
        workspace=workspace,
        remote=remote,
        branch=branch,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to force sync branch")

    return {"ok": True, "git": result}


@app.post("/api/git/commit")
async def git_commit(body: GitCommitBody) -> dict:
    """Stage and commit changes in the workspace."""
    return await git_agent.commit(body.workspace, body.message, body.add_all)


@app.post("/api/git/stash")
async def git_stash(body: GitStashBody) -> dict:
    """Stash uncommitted changes (including untracked files) in the workspace."""
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.stash(workspace, body.message)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to stash changes")

    return {"ok": True, **result}


@app.post("/api/git/stash/pop")
async def git_stash_pop(body: GitStashBody) -> dict:
    """Pop the most recent stash entry in the workspace."""
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.stash_pop(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to pop stash")

    return {"ok": True, **result}


@app.post("/api/git/open-in-cursor")
async def git_open_in_cursor(body: GitOpenInCursorBody) -> dict:
    """Open the provided workspace in Cursor."""
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.open_in_cursor(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to open workspace in Cursor")

    return {"ok": True, **result}


@app.post("/api/git/open-in-files")
async def git_open_in_files(body: GitOpenInFilesBody) -> dict:
    """Open the provided workspace in Finder (macOS) or File Explorer (Windows)."""
    workspace = body.workspace.strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace is required")

    result = await git_agent.open_in_files(workspace)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to open workspace in Files")

    return {"ok": True, **result}


@app.get("/api/git/prs")
async def git_list_prs(workspace: str = "", platform: str = "auto") -> dict:
    """List open PRs/MRs for the workspace repository."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.list_prs(workspace, platform)


@app.post("/api/git/pr")
async def git_create_pr(body: GitPrBody) -> dict:
    """Create a PR (GitHub) or MR (GitLab) for the workspace."""
    return await git_agent.create_pr(
        workspace=body.workspace,
        title=body.title,
        body=body.body,
        target_branch=body.target_branch,
        draft=body.draft,
        push_first=body.push_first,
        platform=body.platform,
    )


@app.get("/api/git/log")
async def git_log(workspace: str = "", limit: int = 10) -> dict:
    """Return recent git log for the workspace."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_log(workspace, limit)


@app.get("/api/git/diff")
async def git_diff(workspace: str = "", staged: bool = False) -> dict:
    """Return current diff for the workspace."""
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")
    return await git_agent.get_diff(workspace, staged)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

class WorkspaceCreateBody(BaseModel):
    name: str
    path: str
    description: str = ""


class WorkspaceUpdateBody(BaseModel):
    name: str | None = None
    path: str | None = None
    description: str | None = None


class ActiveWorkspaceConfigBody(BaseModel):
    primary_workspace_id: str
    secondary_workspace_id: str | None = None


class WorkspaceProjectCreateBody(BaseModel):
    remote_url: str
    local_path: str
    platform: str
    name: str
    description: str = ""
    language: str = ""
    stars: int = 0


class WorkspaceProjectSwitchBranchBody(BaseModel):
    branch: str


class WorkspaceProjectCloneBody(BaseModel):
    wipe_existing: bool = False


@app.get("/api/workspaces")
async def workspaces_list() -> dict:
    return {
        "workspaces": list_workspaces(),
        "active_workspace_config": get_active_workspace_config(),
    }


@app.get("/api/workspaces/active-config")
async def workspaces_active_config() -> dict:
    return get_active_workspace_config()


@app.put("/api/workspaces/active-config")
async def workspaces_set_active_config(body: ActiveWorkspaceConfigBody) -> dict:
    primary_workspace_id = str(body.primary_workspace_id or "").strip()
    if not primary_workspace_id:
        raise HTTPException(status_code=400, detail="primary_workspace_id is required")

    workspaces = list_workspaces()
    known_ids = {str(workspace.get("id") or "") for workspace in workspaces}
    if primary_workspace_id not in known_ids:
        raise HTTPException(status_code=404, detail="Primary workspace not found")

    secondary_workspace_id = str(body.secondary_workspace_id or "").strip() or None
    if secondary_workspace_id and secondary_workspace_id not in known_ids:
        raise HTTPException(status_code=404, detail="Secondary workspace not found")

    if secondary_workspace_id == primary_workspace_id:
        raise HTTPException(status_code=400, detail="Secondary workspace must be different from primary workspace")

    set_active_workspace(primary_workspace_id)
    return set_active_workspace_config(primary_workspace_id, secondary_workspace_id)


@app.post("/api/workspaces")
async def workspaces_create(body: WorkspaceCreateBody) -> dict:
    ws = create_workspace(name=body.name.strip(), path=body.path.strip(), description=body.description.strip())
    return ws


@app.put("/api/workspaces/{workspace_id}")
async def workspaces_update(workspace_id: str, body: WorkspaceUpdateBody) -> dict:
    ws = update_workspace(workspace_id, name=body.name, path=body.path, description=body.description)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.delete("/api/workspaces/{workspace_id}")
async def workspaces_delete(workspace_id: str) -> dict:
    ok = delete_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"ok": True}


@app.patch("/api/workspaces/{workspace_id}/activate")
async def workspaces_activate(workspace_id: str) -> dict:
    ws = set_active_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.get("/api/workspaces/{workspace_id}/projects")
async def workspace_projects_list(workspace_id: str) -> dict:
    return {"projects": list_workspace_projects(workspace_id)}


@app.post("/api/workspaces/{workspace_id}/projects")
async def workspace_projects_create(workspace_id: str, body: WorkspaceProjectCreateBody) -> dict:
    proj = create_workspace_project(
        workspace_id=workspace_id,
        name=body.name.strip(),
        remote_url=body.remote_url.strip(),
        platform=body.platform.strip(),
        local_path=body.local_path.strip(),
        description=body.description.strip(),
        language=body.language.strip(),
        stars=body.stars,
    )
    return proj


@app.delete("/api/workspaces/{workspace_id}/projects/{project_id}")
async def workspace_projects_delete(workspace_id: str, project_id: str) -> dict:
    ok = delete_workspace_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


@app.post("/api/workspaces/{workspace_id}/projects/{project_id}/clone")
async def workspace_projects_clone(workspace_id: str, project_id: str, body: WorkspaceProjectCloneBody | None = None) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    clone_url = str(proj["remote_url"])
    platform = str(proj.get("platform") or "").lower()

    # Use configured tokens for non-interactive HTTPS clones to avoid hanging on credential prompts.
    if clone_url.startswith("https://"):
        if platform == "github":
            token = get_github_token()
            if token and "github.com" in clone_url:
                clone_url = clone_url.replace("https://", f"https://x-access-token:{quote(token, safe='')}@", 1)
        elif platform == "gitlab":
            token = get_gitlab_token()
            if token:
                clone_url = clone_url.replace("https://", f"https://oauth2:{quote(token, safe='')}@", 1)

    result = await workspace_agent.clone_repo(clone_url, proj["local_path"], wipe_existing=bool(body and body.wipe_existing))
    if result.get("success"):
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        detected_branch = ""
        try:
            git_status_result = await git_agent.get_status(proj["local_path"])
            if git_status_result.get("is_git_repo"):
                detected_branch = str(git_status_result.get("branch") or "")
        except Exception:
            detected_branch = ""
        updated = update_workspace_project(project_id, is_cloned=1, cloned_at=now, branch=detected_branch)
        return {"ok": True, "project": updated, "message": result.get("message", "")}
    return {"ok": False, "error": result.get("error", "Clone failed")}


@app.get("/api/workspaces/{workspace_id}/projects/{project_id}/branches")
async def workspace_projects_branches(workspace_id: str, project_id: str) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("is_cloned"):
        raise HTTPException(status_code=422, detail="Project is not cloned")
    branches = await git_agent.get_branches(proj["local_path"])
    return branches


@app.patch("/api/workspaces/{workspace_id}/projects/{project_id}/branch")
async def workspace_projects_switch_branch(workspace_id: str, project_id: str, body: WorkspaceProjectSwitchBranchBody) -> dict:
    projects = list_workspace_projects(workspace_id)
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if not proj.get("is_cloned"):
        raise HTTPException(status_code=422, detail="Project is not cloned")

    result = await git_agent.switch_branch(proj["local_path"], body.branch.strip())
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to switch branch")

    updated = update_workspace_project(project_id, branch=body.branch.strip())
    return {"ok": True, "project": updated, "git": result}


# ---------------------------------------------------------------------------
# Stitch
# ---------------------------------------------------------------------------

@app.get("/api/stitch/status")
async def stitch_status(workspace: str = "") -> dict[str, object]:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")

    return stitch_workspace_status(workspace)


@app.post("/api/stitch/link")
async def stitch_link(body: StitchLinkRequest) -> dict[str, object]:
    try:
        linked = link_workspace_project(
            workspace_root=body.workspace_root,
            project_id=body.project_id,
            create_if_missing=True,
        )
    except StitchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Failed to link Stitch project") from exc

    return {"ok": True, **linked}


@app.get("/api/stitch/screens")
async def stitch_screens(workspace: str = "") -> dict[str, object]:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")

    try:
        screens = list_workspace_screens(workspace)
    except StitchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Failed to load Stitch screens") from exc

    return screens


@app.post("/api/stitch/screens/download")
async def stitch_screen_download(body: StitchDownloadRequest) -> dict[str, object]:
    try:
        result = await download_workspace_screen_assets(
            workspace_root=body.workspace_root,
            screen_id=body.screen_id,
            title=body.title,
        )
    except StitchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Failed to download Stitch screen assets") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc).strip() or "Failed to fetch Stitch asset URLs") from exc

    return {"ok": True, **result}


@app.get("/api/stitch/design-system")
async def stitch_design_system(workspace: str = "", refresh: bool = False) -> dict[str, object]:
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace query parameter is required")

    try:
        design_system = await load_workspace_design_system(workspace_root=workspace, force_refresh=refresh)
    except StitchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Failed to load Stitch design system") from exc

    return design_system


@app.post("/api/stitch/generate")
async def stitch_generate(body: StitchGenerateRequest) -> dict[str, object]:
    try:
        generation = generate_workspace_screens(
            workspace_root=body.workspace_root,
            prompt=body.prompt,
            device_type=body.device_type,
        )
    except StitchServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip() or "Failed to generate Stitch screen") from exc

    return generation


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

class GitHubSettingsBody(BaseModel):
    token: str | None = None
    username: str | None = None


@app.get("/api/github/settings")
async def github_get_settings() -> dict:
    return get_github_settings()


@app.put("/api/github/settings")
async def github_update_settings(body: GitHubSettingsBody) -> dict:
    return update_github_settings(token=body.token, username=body.username)


@app.get("/api/github/repos")
async def github_list_repos(page: int = 1, per_page: int = 30, search: str = "") -> dict:
    token = get_github_token()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub token not configured. Set GITHUB_TOKEN or GIT_SHARED_PAT, or configure via /api/github/settings.",
        )
    username = get_github_username()
    return await workspace_agent.list_github_repos(token=token, username=username, page=page, per_page=per_page, search=search)


@app.get("/api/github/user")
async def github_get_user() -> dict:
    token = get_github_token()
    if not token:
        return {"success": False, "error": "GitHub token not configured"}
    return await workspace_agent.get_github_user(token)


# ---------------------------------------------------------------------------
# GitLab API
# ---------------------------------------------------------------------------

class GitLabSettingsBody(BaseModel):
    token: str | None = None
    url: str | None = None
    username: str | None = None


@app.get("/api/gitlab/settings")
async def gitlab_get_settings() -> dict:
    return get_gitlab_settings()


@app.put("/api/gitlab/settings")
async def gitlab_update_settings(body: GitLabSettingsBody) -> dict:
    return update_gitlab_settings(token=body.token, url=body.url, username=body.username)


@app.get("/api/gitlab/repos")
async def gitlab_list_repos(page: int = 1, per_page: int = 30, search: str = "") -> dict:
    token = get_gitlab_token()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitLab token not configured. Set GITLAB_TOKEN or GIT_SHARED_PAT, or configure via /api/gitlab/settings.",
        )
    gitlab_url = get_gitlab_url()
    username = get_gitlab_username()
    return await workspace_agent.list_gitlab_repos(token=token, gitlab_url=gitlab_url, username=username, page=page, per_page=per_page, search=search)


@app.get("/api/gitlab/user")
async def gitlab_get_user() -> dict:
    token = get_gitlab_token()
    if not token:
        return {"success": False, "error": "GitLab token not configured"}
    gitlab_url = get_gitlab_url()
    return await workspace_agent.get_gitlab_user(token, gitlab_url)
