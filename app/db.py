from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from app.db_client import get_conn

SPEC_TASK_STATUS_GENERATING = "generating"
SPEC_TASK_STATUS_GENERATED = "generated"
SPEC_TASK_STATUS_PENDING = "pending"
SPEC_TASK_STATUS_COMPLETE = "complete"
SPEC_TASK_STATUS_FAILED = "failed"
SPEC_TASK_STATUSES = {
    SPEC_TASK_STATUS_GENERATING,
    SPEC_TASK_STATUS_GENERATED,
    SPEC_TASK_STATUS_PENDING,
    SPEC_TASK_STATUS_COMPLETE,
    SPEC_TASK_STATUS_FAILED,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_spec_task_status(value: str | None, *, fallback: str = SPEC_TASK_STATUS_PENDING) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SPEC_TASK_STATUSES:
        return normalized
    return fallback


def normalize_spec_dependency_mode(value: str | None, *, fallback: str = "independent") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"independent", "parent", "subtask"}:
        return normalized
    return fallback


def _normalize_spec_depends_on(value: list[Any] | None) -> list[str]:
    normalized_depends_on = [
        str(item or "").strip()
        for item in (value or [])
        if str(item or "").strip()
    ]
    deduped_depends_on: list[str] = []
    seen_depends_on: set[str] = set()
    for item in normalized_depends_on:
        if item in seen_depends_on:
            continue
        seen_depends_on.add(item)
        deduped_depends_on.append(item)
    return deduped_depends_on


def _parse_spec_depends_on_json(value: str | None) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        return []
    return _normalize_spec_depends_on(parsed)


def _serialize_spec_task_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["status"] = normalize_spec_task_status(str(payload.get("status") or ""))
    payload["parent_spec_name"] = str(payload.get("parent_spec_name") or "")
    payload["parent_spec_task_id"] = str(payload.get("parent_spec_task_id") or "")
    payload["dependency_mode"] = normalize_spec_dependency_mode(str(payload.get("dependency_mode") or ""))
    payload["depends_on"] = _parse_spec_depends_on_json(str(payload.get("depends_on_json") or "[]"))
    payload["depends_on_json"] = json.dumps(payload["depends_on"], ensure_ascii=False)
    return payload



def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                agent TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                details TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orchestrator_tasks (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                owner_agent TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS orchestrator_events (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                task_id TEXT,
                agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS jira_fetches (
                id TEXT PRIMARY KEY,
                backlog_url TEXT NOT NULL,
                server TEXT NOT NULL,
                tool TEXT NOT NULL,
                ticket_count INTEGER NOT NULL,
                tickets_json TEXT NOT NULL,
                current_sprint_json TEXT,
                kanban_columns_json TEXT,
                warnings_json TEXT,
                raw_result_json TEXT NOT NULL,
                raw_result_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS spec_tasks (
                id TEXT PRIMARY KEY,
                spec_name TEXT NOT NULL UNIQUE,
                workspace_path TEXT NOT NULL,
                spec_path TEXT NOT NULL,
                requirements_path TEXT NOT NULL,
                design_path TEXT NOT NULL,
                tasks_path TEXT NOT NULL,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                parent_spec_name TEXT,
                parent_spec_task_id TEXT,
                dependency_mode TEXT NOT NULL DEFAULT 'independent',
                depends_on_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_attachments (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                message_event_id TEXT,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                description TEXT,
                is_active SMALLINT DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workspace_projects (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                name TEXT NOT NULL,
                remote_url TEXT NOT NULL,
                platform TEXT NOT NULL,
                local_path TEXT NOT NULL,
                is_cloned SMALLINT DEFAULT 0,
                branch TEXT,
                description TEXT,
                language TEXT,
                stars INTEGER DEFAULT 0,
                cloned_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS active_workspace_config (
                primary_workspace_id TEXT,
                secondary_workspace_id TEXT
            );

            CREATE TABLE IF NOT EXISTS jira_config (
                id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL DEFAULT '',
                board_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        attachment_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(chat_attachments)").fetchall()
        }
        if "message_event_id" not in attachment_columns:
            conn.execute("ALTER TABLE chat_attachments ADD COLUMN message_event_id TEXT")
        jira_fetch_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jira_fetches)").fetchall()
        }
        if "current_sprint_json" not in jira_fetch_columns:
            conn.execute("ALTER TABLE jira_fetches ADD COLUMN current_sprint_json TEXT")
        if "kanban_columns_json" not in jira_fetch_columns:
            conn.execute("ALTER TABLE jira_fetches ADD COLUMN kanban_columns_json TEXT")
        spec_task_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(spec_tasks)").fetchall()
        }
        if "summary" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN summary TEXT")
        if "status" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
        if "parent_spec_name" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN parent_spec_name TEXT")
        if "parent_spec_task_id" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN parent_spec_task_id TEXT")
        if "dependency_mode" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN dependency_mode TEXT NOT NULL DEFAULT 'independent'")
        if "depends_on_json" not in spec_task_columns:
            conn.execute("ALTER TABLE spec_tasks ADD COLUMN depends_on_json TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            "UPDATE spec_tasks SET status = ? WHERE status IS NULL OR TRIM(status) = ''",
            (SPEC_TASK_STATUS_PENDING,),
        )
        conn.execute(
            """
            UPDATE spec_tasks
            SET status = ?
            WHERE LOWER(TRIM(status)) NOT IN (
                'generating', 'generated', 'pending', 'complete', 'failed'
            )
            """,
            (SPEC_TASK_STATUS_PENDING,),
        )
        conn.execute(
            """
            UPDATE spec_tasks
            SET dependency_mode = 'independent'
            WHERE COALESCE(TRIM(dependency_mode), '') = ''
            OR LOWER(TRIM(dependency_mode)) NOT IN ('independent', 'parent', 'subtask')
            """,
        )
        conn.execute(
            """
            UPDATE spec_tasks
            SET depends_on_json = '[]'
            WHERE COALESCE(TRIM(depends_on_json), '') = ''
            """,
        )
        jira_config_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jira_config)").fetchall()
        }
        if "project_key" not in jira_config_columns:
            conn.execute("ALTER TABLE jira_config ADD COLUMN project_key TEXT NOT NULL DEFAULT ''")
        if "board_id" not in jira_config_columns:
            conn.execute("ALTER TABLE jira_config ADD COLUMN board_id TEXT NOT NULL DEFAULT ''")
        if "assignee_filter" not in jira_config_columns:
            conn.execute("ALTER TABLE jira_config ADD COLUMN assignee_filter TEXT NOT NULL DEFAULT ''")
        if "jira_users_json" not in jira_config_columns:
            conn.execute("ALTER TABLE jira_config ADD COLUMN jira_users_json TEXT NOT NULL DEFAULT '[]'")

        # Migrate jira_config to TEXT primary key if the table is empty (PostgreSQL INTEGER PK
        # does not auto-generate, so the table would be empty from failed inserts).
        try:
            row_count_row = conn.execute("SELECT COUNT(*) AS cnt FROM jira_config").fetchone()
            row_count = int(row_count_row["cnt"] or 0) if row_count_row else 0

            if row_count == 0:
                conn.execute("DROP TABLE IF EXISTS jira_config")
                conn.execute(
                    "CREATE TABLE jira_config ("
                    "id TEXT PRIMARY KEY, "
                    "project_key TEXT NOT NULL DEFAULT '', "
                    "board_id TEXT NOT NULL DEFAULT '', "
                    "assignee_filter TEXT NOT NULL DEFAULT '', "
                    "jira_users_json TEXT NOT NULL DEFAULT '[]', "
                    "updated_at TEXT NOT NULL"
                    ")"
                )
        except Exception:
            pass

        conn.commit()
    finally:
        conn.close()


def ensure_conversation(conversation_id: str | None) -> str:
    conn = get_conn()
    try:
        now = _utc_now()
        if conversation_id:
            row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if row:
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
                conn.commit()
                return conversation_id

        new_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
            (new_id, now, now),
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def add_message(conversation_id: str, role: str, content: str, agent: str | None = None) -> None:
    conn = get_conn()
    try:
        now = _utc_now()
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, agent, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), conversation_id, role, agent, content, now),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
    finally:
        conn.close()


def recent_messages(conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT role, COALESCE(agent, '') AS agent, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        return [
            {"role": row["role"], "agent": row["agent"], "content": row["content"]}
            for row in reversed(rows)
        ]
    finally:
        conn.close()


def conversation_messages(conversation_id: str) -> list[dict[str, str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT role, COALESCE(agent, '') AS agent, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
        return [
            {
                "role": row["role"],
                "agent": row["agent"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def add_chat_attachment(
    conversation_id: str,
    message_event_id: str | None,
    original_name: str,
    stored_name: str,
    stored_path: str,
    mime_type: str,
    size_bytes: int,
) -> dict[str, str | int]:
    conn = get_conn()
    try:
        now = _utc_now()
        attachment_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO chat_attachments (
                id, conversation_id, message_event_id, original_name, stored_name, stored_path, mime_type, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment_id,
                conversation_id,
                message_event_id,
                original_name,
                stored_name,
                stored_path,
                mime_type,
                int(size_bytes),
                now,
            ),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
        return {
            "id": attachment_id,
            "conversation_id": conversation_id,
            "message_event_id": message_event_id or "",
            "original_name": original_name,
            "stored_name": stored_name,
            "stored_path": stored_path,
            "mime_type": mime_type,
            "size_bytes": int(size_bytes),
            "created_at": now,
        }
    finally:
        conn.close()


def list_chat_attachments(conversation_id: str, limit: int = 40) -> list[dict[str, str | int]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, conversation_id, COALESCE(message_event_id, '') AS message_event_id, original_name, stored_name, stored_path, mime_type, size_bytes, created_at
            FROM chat_attachments
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_conversations(limit: int = 100) -> list[dict[str, str | int | None]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.created_at,
                c.updated_at,
                (
                    SELECT content
                    FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT role
                    FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_role,
                (
                    SELECT created_at
                    FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_message_at,
                (
                    SELECT COUNT(*)
                    FROM messages m
                    WHERE m.conversation_id = c.id
                ) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_orchestrator_task(conversation_id: str, title: str, details: str, owner_agent: str) -> dict[str, str]:
    conn = get_conn()
    try:
        now = _utc_now()
        task_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO orchestrator_tasks (
                id, conversation_id, title, details, owner_agent, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, conversation_id, title, details, owner_agent, "todo", now, now),
        )
        conn.commit()
        return {
            "id": task_id,
            "conversation_id": conversation_id,
            "title": title,
            "details": details,
            "owner_agent": owner_agent,
            "status": "todo",
            "created_at": now,
            "updated_at": now,
        }
    finally:
        conn.close()


def update_orchestrator_task_status(task_id: str, status: str) -> dict[str, str] | None:
    conn = get_conn()
    try:
        now = _utc_now()
        conn.execute(
            "UPDATE orchestrator_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, task_id),
        )
        if conn.total_changes == 0:
            return None

        row = conn.execute(
            """
            SELECT id, conversation_id, title, details, owner_agent, status, created_at, updated_at
            FROM orchestrator_tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def list_orchestrator_tasks(conversation_id: str) -> list[dict[str, str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, conversation_id, title, details, owner_agent, status, created_at, updated_at
            FROM orchestrator_tasks
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_orchestrator_event(
    conversation_id: str,
    task_id: str | None,
    agent: str,
    event_type: str,
    content: str,
) -> dict[str, str]:
    conn = get_conn()
    try:
        now = _utc_now()
        event_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO orchestrator_events (id, conversation_id, task_id, agent, event_type, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, conversation_id, task_id, agent, event_type, content, now),
        )
        conn.commit()
        return {
            "id": event_id,
            "conversation_id": conversation_id,
            "task_id": task_id or "",
            "agent": agent,
            "event_type": event_type,
            "content": content,
            "created_at": now,
        }
    finally:
        conn.close()


def delete_conversations(conversation_ids: Iterable[str]) -> int:
    cleaned = [conversation_id for conversation_id in conversation_ids if conversation_id]
    if not cleaned:
        return 0
    placeholders = ",".join(["?"] * len(cleaned))
    conn = get_conn()
    try:
        conn.execute(
            f"DELETE FROM messages WHERE conversation_id IN ({placeholders})",
            cleaned,
        )
        conn.execute(
            f"DELETE FROM orchestrator_tasks WHERE conversation_id IN ({placeholders})",
            cleaned,
        )
        conn.execute(
            f"DELETE FROM orchestrator_events WHERE conversation_id IN ({placeholders})",
            cleaned,
        )
        cursor = conn.execute(
            f"DELETE FROM conversations WHERE id IN ({placeholders})",
            cleaned,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def list_orchestrator_events(conversation_id: str, limit: int = 200) -> list[dict[str, str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, conversation_id, COALESCE(task_id, '') AS task_id, agent, event_type, content, created_at
            FROM orchestrator_events
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
    finally:
        conn.close()


def list_orchestrator_events_since(conversation_id: str, since: str) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for _attempt in range(2):
        conn = get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT id, conversation_id, COALESCE(task_id, '') AS task_id, agent, event_type, content, created_at
                FROM orchestrator_events
                WHERE conversation_id = ? AND created_at > ?
                ORDER BY created_at ASC
                """,
                (conversation_id, since),
            )
            rows = cursor.fetchall()
            close_cursor = getattr(cursor, 'close', None)
            if callable(close_cursor):
                close_cursor()
            return [dict(row) for row in rows]
        except Exception as exc:
            last_error = exc
            message = str(exc).strip().lower()
            retryable = any(
                fragment in message
                for fragment in (
                    'cursor already closed',
                    'connection already closed',
                    'connection not open',
                    'server closed the connection unexpectedly',
                )
            )
            if not retryable:
                raise
        finally:
            conn.close()
    if last_error is not None:
        raise last_error
    return []


def list_tasks() -> list[dict[str, str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, COALESCE(details, '') AS details, status, created_at, updated_at FROM tasks ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_task(title: str, details: str = "") -> dict[str, str]:
    conn = get_conn()
    try:
        now = _utc_now()
        task_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tasks (id, title, details, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, title, details, "todo", now, now),
        )
        conn.commit()
        return {
            "id": task_id,
            "title": title,
            "details": details,
            "status": "todo",
            "created_at": now,
            "updated_at": now,
        }
    finally:
        conn.close()


def update_task_status(task_id: str, status: str) -> dict[str, str] | None:
    conn = get_conn()
    try:
        now = _utc_now()
        conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, now, task_id))
        if conn.total_changes == 0:
            return None
        row = conn.execute(
            "SELECT id, title, COALESCE(details, '') AS details, status, created_at, updated_at FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def seed_tasks_if_empty(items: Iterable[tuple[str, str]]) -> None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM tasks").fetchone()
        if row and row["count"] > 0:
            return
        now = _utc_now()
        for title, details in items:
            conn.execute(
                "INSERT INTO tasks (id, title, details, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), title, details, "todo", now, now),
            )
        conn.commit()
    finally:
        conn.close()


def add_jira_fetch(
    backlog_url: str,
    server: str,
    tool: str,
    ticket_count: int,
    tickets_json: str,
    current_sprint_json: str,
    kanban_columns_json: str,
    warnings_json: str,
    raw_result_json: str,
    raw_result_path: str | None,
) -> dict[str, Any]:
    conn = get_conn()
    try:
        now = _utc_now()
        fetch_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO jira_fetches (
                id, backlog_url, server, tool, ticket_count, tickets_json, current_sprint_json, kanban_columns_json, warnings_json, raw_result_json, raw_result_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fetch_id,
                backlog_url,
                server,
                tool,
                int(ticket_count),
                tickets_json,
                current_sprint_json,
                kanban_columns_json,
                warnings_json,
                raw_result_json,
                raw_result_path,
                now,
            ),
        )
        conn.commit()
        return {
            "id": fetch_id,
            "created_at": now,
        }
    finally:
        conn.close()


def list_jira_fetches(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                backlog_url,
                server,
                tool,
                ticket_count,
                tickets_json,
                current_sprint_json,
                kanban_columns_json,
                warnings_json,
                raw_result_json,
                raw_result_path,
                created_at
            FROM jira_fetches
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def upsert_spec_task(
    *,
    spec_name: str,
    workspace_path: str,
    spec_path: str,
    requirements_path: str,
    design_path: str,
    tasks_path: str,
    summary: str = "",
    status: str | None = None,
    parent_spec_name: str | None = None,
    parent_spec_task_id: str | None = None,
    dependency_mode: str | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    normalized_spec_name = str(spec_name or "").strip()
    normalized_workspace_path = str(workspace_path or "").strip()
    normalized_spec_path = str(spec_path or "").strip()
    normalized_requirements_path = str(requirements_path or "").strip()
    normalized_design_path = str(design_path or "").strip()
    normalized_tasks_path = str(tasks_path or "").strip()
    normalized_summary = str(summary or "").strip()
    normalized_status = normalize_spec_task_status(status)
    normalized_parent_spec_name = str(parent_spec_name or "").strip() or None
    normalized_parent_spec_task_id = str(parent_spec_task_id or "").strip() or None
    normalized_dependency_mode = normalize_spec_dependency_mode(str(dependency_mode or "").strip().lower())
    deduped_depends_on = _normalize_spec_depends_on(depends_on)
    depends_on_json = json.dumps(deduped_depends_on, ensure_ascii=False)
    if not normalized_spec_name:
        raise ValueError("spec_name is required")
    if not normalized_workspace_path:
        raise ValueError("workspace_path is required")
    if normalized_status != SPEC_TASK_STATUS_GENERATING:
        if not normalized_spec_path:
            raise ValueError("spec_path is required")
        if not normalized_requirements_path:
            raise ValueError("requirements_path is required")
        if not normalized_design_path:
            raise ValueError("design_path is required")
        if not normalized_tasks_path:
            raise ValueError("tasks_path is required")

    conn = get_conn()
    try:
        now = _utc_now()
        existing = conn.execute(
            "SELECT id, created_at, COALESCE(status, '') AS status FROM spec_tasks WHERE spec_name = ?",
            (normalized_spec_name,),
        ).fetchone()

        if existing:
            spec_task_id = str(existing["id"])
            created_at = str(existing["created_at"] or now)
            resolved_status = (
                normalized_status
                if status is not None
                else normalize_spec_task_status(str(existing["status"] or ""))
            )
            conn.execute(
                """
                UPDATE spec_tasks
                SET workspace_path = ?,
                    spec_path = ?,
                    requirements_path = ?,
                    design_path = ?,
                    tasks_path = ?,
                    summary = ?,
                    status = ?,
                    parent_spec_name = ?,
                    parent_spec_task_id = ?,
                    dependency_mode = ?,
                    depends_on_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_workspace_path,
                    normalized_spec_path,
                    normalized_requirements_path,
                    normalized_design_path,
                    normalized_tasks_path,
                    normalized_summary,
                    resolved_status,
                    normalized_parent_spec_name,
                    normalized_parent_spec_task_id,
                    normalized_dependency_mode,
                    depends_on_json,
                    now,
                    spec_task_id,
                ),
            )
        else:
            spec_task_id = str(uuid.uuid4())
            created_at = now
            resolved_status = normalized_status
            conn.execute(
                """
                INSERT INTO spec_tasks (
                    id,
                    spec_name,
                    workspace_path,
                    spec_path,
                    requirements_path,
                    design_path,
                    tasks_path,
                    summary,
                    status,
                    parent_spec_name,
                    parent_spec_task_id,
                    dependency_mode,
                    depends_on_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec_task_id,
                    normalized_spec_name,
                    normalized_workspace_path,
                    normalized_spec_path,
                    normalized_requirements_path,
                    normalized_design_path,
                    normalized_tasks_path,
                    normalized_summary,
                    resolved_status,
                    normalized_parent_spec_name,
                    normalized_parent_spec_task_id,
                    normalized_dependency_mode,
                    depends_on_json,
                    created_at,
                    now,
                ),
            )

        conn.commit()
        return {
            "id": spec_task_id,
            "spec_name": normalized_spec_name,
            "workspace_path": normalized_workspace_path,
            "spec_path": normalized_spec_path,
            "requirements_path": normalized_requirements_path,
            "design_path": normalized_design_path,
            "tasks_path": normalized_tasks_path,
            "summary": normalized_summary,
            "status": resolved_status,
            "parent_spec_name": normalized_parent_spec_name or "",
            "parent_spec_task_id": normalized_parent_spec_task_id or "",
            "dependency_mode": normalized_dependency_mode,
            "depends_on_json": depends_on_json,
            "depends_on": deduped_depends_on,
            "created_at": created_at,
            "updated_at": now,
        }
    finally:
        conn.close()


def list_spec_tasks(limit: int = 500) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 2000))
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                spec_name,
                workspace_path,
                spec_path,
                requirements_path,
                design_path,
                tasks_path,
                COALESCE(summary, '') AS summary,
                COALESCE(status, 'pending') AS status,
                COALESCE(parent_spec_name, '') AS parent_spec_name,
                COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                COALESCE(dependency_mode, 'independent') AS dependency_mode,
                COALESCE(depends_on_json, '[]') AS depends_on_json,
                created_at,
                updated_at
            FROM spec_tasks
            ORDER BY updated_at DESC, spec_name ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_serialize_spec_task_row(row) for row in rows]
    finally:
        conn.close()


def update_spec_task_dependencies(
    *,
    spec_name: str,
    dependency_mode: str | None,
    parent_spec_name: str | None = None,
    parent_spec_task_id: str | None = None,
    depends_on: list[str] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any] | None:
    normalized_spec_name = str(spec_name or "").strip()
    normalized_workspace_path = str(workspace_path or "").strip()
    normalized_parent_spec_name = str(parent_spec_name or "").strip()
    normalized_parent_spec_task_id = str(parent_spec_task_id or "").strip()
    normalized_dependency_mode = normalize_spec_dependency_mode(dependency_mode)
    normalized_depends_on = _normalize_spec_depends_on(depends_on)
    normalized_depends_on_json = json.dumps(normalized_depends_on, ensure_ascii=False)
    if not normalized_spec_name:
        raise ValueError("spec_name is required")

    conn = get_conn()
    try:
        now = _utc_now()
        cursor: Any
        if normalized_workspace_path:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET parent_spec_name = ?,
                    parent_spec_task_id = ?,
                    dependency_mode = ?,
                    depends_on_json = ?,
                    updated_at = ?
                WHERE spec_name = ? AND workspace_path = ?
                """,
                (
                    normalized_parent_spec_name or None,
                    normalized_parent_spec_task_id or None,
                    normalized_dependency_mode,
                    normalized_depends_on_json,
                    now,
                    normalized_spec_name,
                    normalized_workspace_path,
                ),
            )
            if int(cursor.rowcount or 0) <= 0:
                cursor = conn.execute(
                    """
                    UPDATE spec_tasks
                    SET parent_spec_name = ?,
                        parent_spec_task_id = ?,
                        dependency_mode = ?,
                        depends_on_json = ?,
                        updated_at = ?
                    WHERE spec_name = ?
                    """,
                    (
                        normalized_parent_spec_name or None,
                        normalized_parent_spec_task_id or None,
                        normalized_dependency_mode,
                        normalized_depends_on_json,
                        now,
                        normalized_spec_name,
                    ),
                )
        else:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET parent_spec_name = ?,
                    parent_spec_task_id = ?,
                    dependency_mode = ?,
                    depends_on_json = ?,
                    updated_at = ?
                WHERE spec_name = ?
                """,
                (
                    normalized_parent_spec_name or None,
                    normalized_parent_spec_task_id or None,
                    normalized_dependency_mode,
                    normalized_depends_on_json,
                    now,
                    normalized_spec_name,
                ),
            )

        row = conn.execute(
            """
            SELECT
                id,
                spec_name,
                workspace_path,
                spec_path,
                requirements_path,
                design_path,
                tasks_path,
                COALESCE(summary, '') AS summary,
                COALESCE(status, 'pending') AS status,
                COALESCE(parent_spec_name, '') AS parent_spec_name,
                COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                COALESCE(dependency_mode, 'independent') AS dependency_mode,
                COALESCE(depends_on_json, '[]') AS depends_on_json,
                created_at,
                updated_at
            FROM spec_tasks
            WHERE spec_name = ?
            LIMIT 1
            """,
            (normalized_spec_name,),
        ).fetchone()

        conn.commit()
        if int(cursor.rowcount or 0) <= 0:
            return None
        return _serialize_spec_task_row(row) if row else None
    finally:
        conn.close()


def set_spec_task_status(
    *,
    spec_name: str,
    status: str,
    workspace_path: str | None = None,
) -> dict[str, Any] | None:
    normalized_spec_name = str(spec_name or "").strip()
    normalized_status = normalize_spec_task_status(status)
    normalized_workspace_path = str(workspace_path or "").strip()
    if not normalized_spec_name:
        raise ValueError("spec_name is required")

    conn = get_conn()
    try:
        now = _utc_now()
        cursor: Any
        if normalized_workspace_path:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET status = ?, updated_at = ?
                WHERE spec_name = ? AND workspace_path = ?
                """,
                (normalized_status, now, normalized_spec_name, normalized_workspace_path),
            )
            if int(cursor.rowcount or 0) <= 0:
                cursor = conn.execute(
                    """
                    UPDATE spec_tasks
                    SET status = ?, updated_at = ?
                    WHERE spec_name = ?
                    """,
                    (normalized_status, now, normalized_spec_name),
                )
        else:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET status = ?, updated_at = ?
                WHERE spec_name = ?
                """,
                (normalized_status, now, normalized_spec_name),
            )

        row = conn.execute(
            """
            SELECT
                id,
                spec_name,
                workspace_path,
                spec_path,
                requirements_path,
                design_path,
                tasks_path,
                COALESCE(summary, '') AS summary,
                COALESCE(status, 'pending') AS status,
                COALESCE(parent_spec_name, '') AS parent_spec_name,
                COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                COALESCE(dependency_mode, 'independent') AS dependency_mode,
                COALESCE(depends_on_json, '[]') AS depends_on_json,
                created_at,
                updated_at
            FROM spec_tasks
            WHERE spec_name = ?
            LIMIT 1
            """,
            (normalized_spec_name,),
        ).fetchone()

        conn.commit()
        if int(cursor.rowcount or 0) <= 0:
            return None
        return _serialize_spec_task_row(row) if row else None
    finally:
        conn.close()


def delete_spec_task_by_id(spec_task_id: str) -> bool:
    normalized_spec_task_id = str(spec_task_id or "").strip()
    if not normalized_spec_task_id:
        raise ValueError("spec_task_id is required")

    conn = get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM spec_tasks WHERE id = ?",
            (normalized_spec_task_id,),
        )
        conn.commit()
        return int(cursor.rowcount or 0) > 0
    finally:
        conn.close()


def create_generating_spec_task(
    *,
    spec_name: str,
    workspace_path: str,
) -> dict[str, Any]:
    """Creates a spec_task row at the start of async generation. Status is 'generating', file paths are empty."""
    return upsert_spec_task(
        spec_name=spec_name,
        workspace_path=workspace_path,
        spec_path="",
        requirements_path="",
        design_path="",
        tasks_path="",
        summary="",
        status=SPEC_TASK_STATUS_GENERATING,
    )


def mark_spec_task_generated(
    *,
    spec_name: str,
    workspace_path: str,
    spec_path: str,
    requirements_path: str,
    design_path: str,
    tasks_path: str,
) -> dict[str, Any] | None:
    """Called once all 3 files are written. Flips status to 'generated' and writes file paths."""
    normalized_spec_name = str(spec_name or "").strip()
    normalized_workspace_path = str(workspace_path or "").strip()
    if not normalized_spec_name:
        raise ValueError("spec_name is required")

    conn = get_conn()
    try:
        now = _utc_now()
        cursor = conn.execute(
            """
            UPDATE spec_tasks
            SET spec_path = ?,
                requirements_path = ?,
                design_path = ?,
                tasks_path = ?,
                status = ?,
                updated_at = ?
            WHERE spec_name = ? AND workspace_path = ?
            """,
            (
                str(spec_path or "").strip(),
                str(requirements_path or "").strip(),
                str(design_path or "").strip(),
                str(tasks_path or "").strip(),
                SPEC_TASK_STATUS_GENERATED,
                now,
                normalized_spec_name,
                normalized_workspace_path,
            ),
        )
        if int(cursor.rowcount or 0) <= 0:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET spec_path = ?,
                    requirements_path = ?,
                    design_path = ?,
                    tasks_path = ?,
                    status = ?,
                    updated_at = ?
                WHERE spec_name = ?
                """,
                (
                    str(spec_path or "").strip(),
                    str(requirements_path or "").strip(),
                    str(design_path or "").strip(),
                    str(tasks_path or "").strip(),
                    SPEC_TASK_STATUS_GENERATED,
                    now,
                    normalized_spec_name,
                ),
            )

        row = conn.execute(
            """
            SELECT
                id, spec_name, workspace_path, spec_path,
                requirements_path, design_path, tasks_path,
                COALESCE(summary, '') AS summary,
                COALESCE(status, 'generated') AS status,
                COALESCE(parent_spec_name, '') AS parent_spec_name,
                COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                COALESCE(dependency_mode, 'independent') AS dependency_mode,
                COALESCE(depends_on_json, '[]') AS depends_on_json,
                created_at, updated_at
            FROM spec_tasks
            WHERE spec_name = ?
            LIMIT 1
            """,
            (normalized_spec_name,),
        ).fetchone()

        conn.commit()
        if int(cursor.rowcount or 0) <= 0:
            return None
        return _serialize_spec_task_row(row) if row else None
    finally:
        conn.close()


def promote_spec_task_to_pending(
    *,
    spec_name: str,
    workspace_path: str,
    summary: str,
) -> dict[str, Any] | None:
    """Called when the user clicks 'Add To Tasks'. Updates status from 'generated' to 'pending' and sets summary."""
    normalized_spec_name = str(spec_name or "").strip()
    normalized_workspace_path = str(workspace_path or "").strip()
    normalized_summary = str(summary or "").strip()
    if not normalized_spec_name:
        raise ValueError("spec_name is required")

    conn = get_conn()
    try:
        now = _utc_now()
        cursor = conn.execute(
            """
            UPDATE spec_tasks
            SET summary = ?, status = ?, updated_at = ?
            WHERE spec_name = ? AND workspace_path = ?
            """,
            (
                normalized_summary,
                SPEC_TASK_STATUS_PENDING,
                now,
                normalized_spec_name,
                normalized_workspace_path,
            ),
        )
        if int(cursor.rowcount or 0) <= 0:
            cursor = conn.execute(
                """
                UPDATE spec_tasks
                SET summary = ?, status = ?, updated_at = ?
                WHERE spec_name = ?
                """,
                (normalized_summary, SPEC_TASK_STATUS_PENDING, now, normalized_spec_name),
            )

        row = conn.execute(
            """
            SELECT
                id, spec_name, workspace_path, spec_path,
                requirements_path, design_path, tasks_path,
                COALESCE(summary, '') AS summary,
                COALESCE(status, 'pending') AS status,
                COALESCE(parent_spec_name, '') AS parent_spec_name,
                COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                COALESCE(dependency_mode, 'independent') AS dependency_mode,
                COALESCE(depends_on_json, '[]') AS depends_on_json,
                created_at, updated_at
            FROM spec_tasks
            WHERE spec_name = ?
            LIMIT 1
            """,
            (normalized_spec_name,),
        ).fetchone()

        conn.commit()
        if int(cursor.rowcount or 0) <= 0:
            return None
        return _serialize_spec_task_row(row) if row else None
    finally:
        conn.close()


def get_spec_task_by_name(
    *,
    spec_name: str,
    workspace_path: str | None = None,
) -> dict[str, Any] | None:
    """Returns a single spec_task by spec_name, optionally scoped to a workspace."""
    normalized_spec_name = str(spec_name or "").strip()
    normalized_workspace_path = str(workspace_path or "").strip()
    if not normalized_spec_name:
        raise ValueError("spec_name is required")

    conn = get_conn()
    try:
        if normalized_workspace_path:
            row = conn.execute(
                """
                SELECT
                    id, spec_name, workspace_path, spec_path,
                    requirements_path, design_path, tasks_path,
                    COALESCE(summary, '') AS summary,
                    COALESCE(status, 'pending') AS status,
                    COALESCE(parent_spec_name, '') AS parent_spec_name,
                    COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                    COALESCE(dependency_mode, 'independent') AS dependency_mode,
                    COALESCE(depends_on_json, '[]') AS depends_on_json,
                    created_at, updated_at
                FROM spec_tasks
                WHERE spec_name = ? AND workspace_path = ?
                LIMIT 1
                """,
                (normalized_spec_name, normalized_workspace_path),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT
                        id, spec_name, workspace_path, spec_path,
                        requirements_path, design_path, tasks_path,
                        COALESCE(summary, '') AS summary,
                        COALESCE(status, 'pending') AS status,
                        COALESCE(parent_spec_name, '') AS parent_spec_name,
                        COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                        COALESCE(dependency_mode, 'independent') AS dependency_mode,
                        COALESCE(depends_on_json, '[]') AS depends_on_json,
                        created_at, updated_at
                    FROM spec_tasks
                    WHERE spec_name = ?
                    LIMIT 1
                    """,
                    (normalized_spec_name,),
                ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    id, spec_name, workspace_path, spec_path,
                    requirements_path, design_path, tasks_path,
                    COALESCE(summary, '') AS summary,
                    COALESCE(status, 'pending') AS status,
                    COALESCE(parent_spec_name, '') AS parent_spec_name,
                    COALESCE(parent_spec_task_id, '') AS parent_spec_task_id,
                    COALESCE(dependency_mode, 'independent') AS dependency_mode,
                    COALESCE(depends_on_json, '[]') AS depends_on_json,
                    created_at, updated_at
                FROM spec_tasks
                WHERE spec_name = ?
                LIMIT 1
                """,
                (normalized_spec_name,),
            ).fetchone()

        return _serialize_spec_task_row(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

def get_active_workspace_config() -> dict[str, str | None]:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT primary_workspace_id, secondary_workspace_id
            FROM active_workspace_config
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {
                "primary_workspace_id": None,
                "secondary_workspace_id": None,
            }
        return {
            "primary_workspace_id": str(row["primary_workspace_id"] or "").strip() or None,
            "secondary_workspace_id": str(row["secondary_workspace_id"] or "").strip() or None,
        }
    finally:
        conn.close()


def set_active_workspace_config(primary_workspace_id: str, secondary_workspace_id: str | None = None) -> dict[str, str | None]:
    conn = get_conn()
    try:
        primary_id = str(primary_workspace_id or "").strip() or None
        secondary_id = str(secondary_workspace_id or "").strip() or None
        conn.execute("DELETE FROM active_workspace_config")
        conn.execute(
            """
            INSERT INTO active_workspace_config (primary_workspace_id, secondary_workspace_id)
            VALUES (?, ?)
            """,
            (primary_id, secondary_id),
        )
        conn.commit()
        return {
            "primary_workspace_id": primary_id,
            "secondary_workspace_id": secondary_id,
        }
    finally:
        conn.close()


def list_workspaces() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, path, COALESCE(description,'') AS description, is_active, created_at, updated_at FROM workspaces ORDER BY created_at ASC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_workspace(name: str, path: str, description: str = "") -> dict[str, Any]:
    conn = get_conn()
    try:
        now = _utc_now()
        ws_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO workspaces (id, name, path, description, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (ws_id, name, path, description, now, now),
        )
        conn.commit()
        return {"id": ws_id, "name": name, "path": path, "description": description, "is_active": 0, "created_at": now, "updated_at": now}
    finally:
        conn.close()


def update_workspace(workspace_id: str, name: str | None = None, path: str | None = None, description: str | None = None) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        now = _utc_now()
        row = conn.execute("SELECT id, name, path, COALESCE(description,'') AS description, is_active, created_at FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if not row:
            return None
        new_name = name if name is not None else row["name"]
        new_path = path if path is not None else row["path"]
        new_desc = description if description is not None else row["description"]
        conn.execute(
            "UPDATE workspaces SET name = ?, path = ?, description = ?, updated_at = ? WHERE id = ?",
            (new_name, new_path, new_desc, now, workspace_id),
        )
        conn.commit()
        return {"id": workspace_id, "name": new_name, "path": new_path, "description": new_desc or "", "is_active": row["is_active"], "created_at": row["created_at"], "updated_at": now}
    finally:
        conn.close()


def delete_workspace(workspace_id: str) -> bool:
    conn = get_conn()
    try:
        config_row = conn.execute(
            """
            SELECT primary_workspace_id, secondary_workspace_id
            FROM active_workspace_config
            LIMIT 1
            """
        ).fetchone()
        conn.execute("DELETE FROM workspace_projects WHERE workspace_id = ?", (workspace_id,))
        cursor = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        if cursor.rowcount > 0 and config_row:
            current_primary = str(config_row["primary_workspace_id"] or "").strip() or None
            current_secondary = str(config_row["secondary_workspace_id"] or "").strip() or None
            next_primary = current_primary
            next_secondary = current_secondary
            if current_primary == workspace_id:
                next_primary = None
            if current_secondary == workspace_id:
                next_secondary = None
            conn.execute("DELETE FROM active_workspace_config")
            conn.execute(
                """
                INSERT INTO active_workspace_config (primary_workspace_id, secondary_workspace_id)
                VALUES (?, ?)
                """,
                (next_primary, next_secondary),
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_active_workspace(workspace_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        secondary_workspace_id: str | None = None
        existing_config = conn.execute(
            """
            SELECT secondary_workspace_id
            FROM active_workspace_config
            LIMIT 1
            """
        ).fetchone()
        if existing_config:
            secondary_workspace_id = str(existing_config["secondary_workspace_id"] or "").strip() or None

        now = _utc_now()
        conn.execute("UPDATE workspaces SET is_active = 0, updated_at = ?", (now,))
        conn.execute("UPDATE workspaces SET is_active = 1, updated_at = ? WHERE id = ?", (now, workspace_id))
        conn.execute("DELETE FROM active_workspace_config")
        conn.execute(
            """
            INSERT INTO active_workspace_config (primary_workspace_id, secondary_workspace_id)
            VALUES (?, ?)
            """,
            (str(workspace_id or "").strip() or None, secondary_workspace_id),
        )
        conn.commit()
        row = conn.execute("SELECT id, name, path, COALESCE(description,'') AS description, is_active, created_at, updated_at FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Workspace Projects
# ---------------------------------------------------------------------------

def list_workspace_projects(workspace_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, workspace_id, name, remote_url, platform, local_path,
                   is_cloned, COALESCE(branch,'') AS branch,
                   COALESCE(description,'') AS description,
                   COALESCE(language,'') AS language, stars,
                   COALESCE(cloned_at,'') AS cloned_at, created_at, updated_at
            FROM workspace_projects WHERE workspace_id = ? ORDER BY created_at ASC
            """,
            (workspace_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_workspace_project(
    workspace_id: str,
    name: str,
    remote_url: str,
    platform: str,
    local_path: str,
    description: str = "",
    language: str = "",
    stars: int = 0,
) -> dict[str, Any]:
    conn = get_conn()
    try:
        now = _utc_now()
        proj_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO workspace_projects
              (id, workspace_id, name, remote_url, platform, local_path, is_cloned, description, language, stars, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (proj_id, workspace_id, name, remote_url, platform, local_path, description, language, stars, now, now),
        )
        conn.commit()
        return {
            "id": proj_id, "workspace_id": workspace_id, "name": name, "remote_url": remote_url,
            "platform": platform, "local_path": local_path, "is_cloned": 0, "branch": "", "description": description,
            "language": language, "stars": stars, "cloned_at": "", "created_at": now, "updated_at": now,
        }
    finally:
        conn.close()


def update_workspace_project(project_id: str, **kwargs: Any) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        now = _utc_now()
        allowed = {"name", "remote_url", "platform", "local_path", "is_cloned", "branch", "description", "language", "stars", "cloned_at"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            row = conn.execute("SELECT * FROM workspace_projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row) if row else None
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [now, project_id]
        conn.execute(f"UPDATE workspace_projects SET {set_clause}, updated_at = ? WHERE id = ?", values)
        conn.commit()
        row = conn.execute(
            """
            SELECT id, workspace_id, name, remote_url, platform, local_path,
                   is_cloned, COALESCE(branch,'') AS branch,
                   COALESCE(description,'') AS description,
                   COALESCE(language,'') AS language, stars,
                   COALESCE(cloned_at,'') AS cloned_at, created_at, updated_at
            FROM workspace_projects WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_workspace_project(project_id: str) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM workspace_projects WHERE id = ?", (project_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_jira_config() -> dict[str, object]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT project_key, board_id, assignee_filter, jira_users_json FROM jira_config ORDER BY id LIMIT 1"
        ).fetchone()

        if row:
            try:
                jira_users = json.loads(row["jira_users_json"] or "[]")
                jira_users = jira_users if isinstance(jira_users, list) else []
            except Exception:
                jira_users = []

            return {
                "project_key": str(row["project_key"] or "").strip(),
                "board_id": str(row["board_id"] or "").strip(),
                "assignee_filter": str(row["assignee_filter"] or "").strip(),
                "jira_users": jira_users,
            }

        return {"project_key": "", "board_id": "", "assignee_filter": "", "jira_users": []}
    finally:
        conn.close()


def save_jira_config(
    project_key: str | None = None,
    board_id: str | None = None,
    assignee_filter: str | None = None,
    jira_users: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id, project_key, board_id, assignee_filter, jira_users_json FROM jira_config ORDER BY id LIMIT 1"
        ).fetchone()
        now = _utc_now()

        if existing:
            next_project_key = str(project_key or existing["project_key"] or "").strip().upper()
            next_board_id = str(board_id or existing["board_id"] or "").strip()
            next_assignee_filter = (
                assignee_filter.strip()
                if assignee_filter is not None
                else str(existing["assignee_filter"] or "").strip()
            )
            next_jira_users_json = (
                json.dumps(jira_users)
                if jira_users is not None
                else str(existing["jira_users_json"] or "[]")
            )
            conn.execute(
                "UPDATE jira_config SET project_key = ?, board_id = ?, assignee_filter = ?, jira_users_json = ?, updated_at = ? WHERE id = ?",
                (next_project_key, next_board_id, next_assignee_filter, next_jira_users_json, now, existing["id"]),
            )
        else:
            next_project_key = str(project_key or "").strip().upper()
            next_board_id = str(board_id or "").strip()
            next_assignee_filter = str(assignee_filter or "").strip()
            next_jira_users_json = json.dumps(jira_users or [])
            conn.execute(
                "INSERT INTO jira_config (id, project_key, board_id, assignee_filter, jira_users_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), next_project_key, next_board_id, next_assignee_filter, next_jira_users_json, now),
            )

        conn.commit()

        try:
            saved_users = json.loads(next_jira_users_json)
            saved_users = saved_users if isinstance(saved_users, list) else []
        except Exception:
            saved_users = []

        return {
            "project_key": next_project_key,
            "board_id": next_board_id,
            "assignee_filter": next_assignee_filter,
            "jira_users": saved_users,
        }
    finally:
        conn.close()
