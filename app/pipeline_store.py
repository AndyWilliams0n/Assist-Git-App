from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db_client import get_conn

PIPELINE_ID = "default"

PIPELINE_STATUS_CURRENT = "current"
PIPELINE_STATUS_RUNNING = "running"
PIPELINE_STATUS_COMPLETE = "complete"
PIPELINE_STATUS_FAILED = "failed"
PIPELINE_STATUS_STOPPED = "stopped"
PIPELINE_STATUS_BACKLOG = "backlog"
PIPELINE_TASK_EXECUTION_STATE_READY = "ready"
PIPELINE_TASK_EXECUTION_STATE_BLOCKED = "blocked"
PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED = "attention_required"
PIPELINE_TASK_EXECUTION_STATES = {
    PIPELINE_TASK_EXECUTION_STATE_READY,
    PIPELINE_TASK_EXECUTION_STATE_BLOCKED,
    PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED,
}
PIPELINE_BYPASS_SOURCE_MANUAL = "manual"
PIPELINE_BYPASS_SOURCE_AUTO_FAILURE = "auto_failure"
PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF = "auto_handoff"
PIPELINE_BYPASS_SOURCE_DEPENDENCY = "dependency"
PIPELINE_BYPASS_SOURCE_BRANCH_COHORT = "branch_cohort"
PIPELINE_BYPASS_SOURCES = {
    PIPELINE_BYPASS_SOURCE_MANUAL,
    PIPELINE_BYPASS_SOURCE_AUTO_FAILURE,
    PIPELINE_BYPASS_SOURCE_AUTO_HANDOFF,
    PIPELINE_BYPASS_SOURCE_DEPENDENCY,
    PIPELINE_BYPASS_SOURCE_BRANCH_COHORT,
}

PIPELINE_RUN_STATUS_RUNNING = "running"
PIPELINE_RUN_STATUS_COMPLETE = "complete"
PIPELINE_RUN_STATUS_FAILED = "failed"
PIPELINE_RUN_STATUS_STOPPED = "stopped"

PIPELINE_WORKFLOW = "codex"
PIPELINE_TASK_SOURCE_JIRA = "jira"
PIPELINE_TASK_SOURCE_SPEC = "spec"
PIPELINE_TASK_SOURCES = {
    PIPELINE_TASK_SOURCE_JIRA,
    PIPELINE_TASK_SOURCE_SPEC,
}

PIPELINE_TASK_RELATION_TASK = "task"
PIPELINE_TASK_RELATION_SUBTASK = "subtask"
PIPELINE_TASK_RELATIONS = {
    PIPELINE_TASK_RELATION_TASK,
    PIPELINE_TASK_RELATION_SUBTASK,
}

DEFAULT_ACTIVE_WINDOW_START = "18:00"
DEFAULT_ACTIVE_WINDOW_END = "06:00"
DEFAULT_HEARTBEAT_INTERVAL_MINUTES = 5
MIN_HEARTBEAT_INTERVAL_MINUTES = 5
DEFAULT_MAX_RETRIES = 4
MIN_MAX_RETRIES = 1
MAX_MAX_RETRIES = 12
REVIEW_FAILURE_MODE_STRICT = "strict"
REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE = "skip_acceptance"
REVIEW_FAILURE_MODE_SKIP_ALL = "skip_all"
DEFAULT_REVIEW_FAILURE_MODE = REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE
REVIEW_FAILURE_MODES = {
    REVIEW_FAILURE_MODE_STRICT,
    REVIEW_FAILURE_MODE_SKIP_ACCEPTANCE,
    REVIEW_FAILURE_MODE_SKIP_ALL,
}


def _normalize_review_failure_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in REVIEW_FAILURE_MODES:
        return normalized
    return DEFAULT_REVIEW_FAILURE_MODE


def _normalize_max_retries(value: Any, *, fallback: int = DEFAULT_MAX_RETRIES) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(fallback)
    return max(MIN_MAX_RETRIES, min(MAX_MAX_RETRIES, parsed))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_workflow(value: str | None, fallback: str = PIPELINE_WORKFLOW) -> str:
    return PIPELINE_WORKFLOW


def _normalize_task_source(value: str | None, fallback: str = PIPELINE_TASK_SOURCE_JIRA) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PIPELINE_TASK_SOURCES:
        return normalized
    return fallback


def _normalize_task_relation(value: str | None, fallback: str = PIPELINE_TASK_RELATION_TASK) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PIPELINE_TASK_RELATIONS:
        return normalized
    return fallback


def _normalize_execution_state(value: str | None, *, fallback: str = PIPELINE_TASK_EXECUTION_STATE_READY) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PIPELINE_TASK_EXECUTION_STATES:
        return normalized
    return fallback


def _normalize_bypass_source(value: str | None, *, fallback: str = PIPELINE_BYPASS_SOURCE_MANUAL) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PIPELINE_BYPASS_SOURCES:
        return normalized
    return fallback


def _to_bool_int(value: Any, *, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return 1
    if text in {"0", "false", "no", "off"}:
        return 0
    return 1 if int(fallback) != 0 else 0



def ensure_pipeline_schema() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipeline_settings (
                id TEXT PRIMARY KEY,
                active_window_start TEXT NOT NULL,
                active_window_end TEXT NOT NULL,
                heartbeat_interval_minutes INTEGER NOT NULL,
                automation_enabled SMALLINT NOT NULL DEFAULT 1,
                max_retries INTEGER NOT NULL DEFAULT 4,
                review_failure_mode TEXT NOT NULL DEFAULT 'skip_acceptance',
                last_heartbeat_at TEXT,
                last_cycle_at TEXT,
                next_heartbeat_override_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pipeline_backlog (
                jira_key TEXT PRIMARY KEY,
                task_source TEXT NOT NULL DEFAULT 'jira',
                task_reference TEXT,
                title TEXT NOT NULL,
                issue_type TEXT,
                status TEXT,
                priority TEXT,
                assignee TEXT,
                updated TEXT,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pipeline_tasks (
                id TEXT PRIMARY KEY,
                jira_key TEXT NOT NULL UNIQUE,
                task_source TEXT NOT NULL DEFAULT 'jira',
                task_relation TEXT NOT NULL DEFAULT 'task',
                title TEXT NOT NULL,
                workspace_path TEXT NOT NULL,
                jira_complete_column_name TEXT,
                starting_git_branch_override TEXT,
                workflow TEXT NOT NULL DEFAULT 'codex',
                status TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                version INTEGER NOT NULL,
                failure_reason TEXT,
                is_bypassed SMALLINT NOT NULL DEFAULT 0,
                bypass_reason TEXT,
                bypass_source TEXT,
                bypassed_at TEXT,
                bypassed_by TEXT,
                is_dependency_blocked SMALLINT NOT NULL DEFAULT 0,
                dependency_block_reason TEXT,
                execution_state TEXT NOT NULL DEFAULT 'ready',
                last_failure_code TEXT,
                jira_payload_json TEXT NOT NULL,
                active_run_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_status_order
            ON pipeline_tasks(status, order_index, updated_at);

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                jira_key TEXT NOT NULL,
                task_source TEXT NOT NULL DEFAULT 'jira',
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                workspace_path TEXT NOT NULL,
                workflow TEXT NOT NULL DEFAULT 'codex',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 0,
                attempts_failed INTEGER NOT NULL DEFAULT 0,
                attempts_completed INTEGER NOT NULL DEFAULT 0,
                current_activity TEXT,
                brief_path TEXT,
                spec_path TEXT,
                task_path TEXT,
                codex_status TEXT,
                codex_summary TEXT,
                failure_reason TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES pipeline_tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_task
            ON pipeline_runs(task_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS pipeline_logs (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                run_id TEXT,
                jira_key TEXT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES pipeline_tasks(id),
                FOREIGN KEY(run_id) REFERENCES pipeline_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_logs_task
            ON pipeline_logs(task_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS pipeline_task_dependencies (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                depends_on_task_id TEXT NOT NULL,
                dependency_type TEXT NOT NULL DEFAULT 'hard',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES pipeline_tasks(id),
                FOREIGN KEY(depends_on_task_id) REFERENCES pipeline_tasks(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_task_dependencies_unique
            ON pipeline_task_dependencies(task_id, depends_on_task_id);

            CREATE INDEX IF NOT EXISTS idx_pipeline_task_dependencies_task
            ON pipeline_task_dependencies(task_id);

            CREATE INDEX IF NOT EXISTS idx_pipeline_task_dependencies_depends_on
            ON pipeline_task_dependencies(depends_on_task_id);

            CREATE TABLE IF NOT EXISTS pipeline_git_handoffs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                run_id TEXT,
                jira_key TEXT NOT NULL,
                strategy TEXT NOT NULL,
                stash_ref TEXT,
                commit_sha TEXT,
                source_branch TEXT,
                target_branch TEXT,
                file_summary_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                resolved SMALLINT NOT NULL DEFAULT 0,
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES pipeline_tasks(id),
                FOREIGN KEY(run_id) REFERENCES pipeline_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_git_handoffs_task
            ON pipeline_git_handoffs(task_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_pipeline_git_handoffs_unresolved
            ON pipeline_git_handoffs(task_id, resolved, updated_at DESC);
            """
        )
        task_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(pipeline_tasks)").fetchall()}
        backlog_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(pipeline_backlog)").fetchall()}
        if "task_source" not in backlog_columns:
            conn.execute(
                "ALTER TABLE pipeline_backlog ADD COLUMN task_source TEXT NOT NULL DEFAULT 'jira'"
            )
        if "task_reference" not in backlog_columns:
            conn.execute(
                "ALTER TABLE pipeline_backlog ADD COLUMN task_reference TEXT"
            )
        if "workflow" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN workflow TEXT NOT NULL DEFAULT 'codex'"
            )
        if "task_source" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN task_source TEXT NOT NULL DEFAULT 'jira'"
            )
        if "jira_complete_column_name" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN jira_complete_column_name TEXT"
            )
        if "starting_git_branch_override" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN starting_git_branch_override TEXT"
            )
        if "is_bypassed" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN is_bypassed SMALLINT NOT NULL DEFAULT 0"
            )
        if "bypass_reason" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN bypass_reason TEXT"
            )
        if "bypass_source" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN bypass_source TEXT"
            )
        if "bypassed_at" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN bypassed_at TEXT"
            )
        if "bypassed_by" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN bypassed_by TEXT"
            )
        if "is_dependency_blocked" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN is_dependency_blocked SMALLINT NOT NULL DEFAULT 0"
            )
        if "dependency_block_reason" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN dependency_block_reason TEXT"
            )
        if "execution_state" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN execution_state TEXT NOT NULL DEFAULT 'ready'"
            )
        if "last_failure_code" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN last_failure_code TEXT"
            )
        if "task_relation" not in task_columns:
            conn.execute(
                "ALTER TABLE pipeline_tasks ADD COLUMN task_relation TEXT NOT NULL DEFAULT 'task'"
            )
        run_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
        if "workflow" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN workflow TEXT NOT NULL DEFAULT 'codex'"
            )
        if "task_source" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN task_source TEXT NOT NULL DEFAULT 'jira'"
            )
        if "attempt_count" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        if "max_retries" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 0"
            )
        if "attempts_failed" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN attempts_failed INTEGER NOT NULL DEFAULT 0"
            )
        if "attempts_completed" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN attempts_completed INTEGER NOT NULL DEFAULT 0"
            )
        if "current_activity" not in run_columns:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN current_activity TEXT"
            )
        settings_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(pipeline_settings)").fetchall()}
        if "automation_enabled" not in settings_columns:
            conn.execute(
                "ALTER TABLE pipeline_settings ADD COLUMN automation_enabled SMALLINT NOT NULL DEFAULT 1"
            )
        if "max_retries" not in settings_columns:
            conn.execute(
                "ALTER TABLE pipeline_settings ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 4"
            )
        if "review_failure_mode" not in settings_columns:
            conn.execute(
                "ALTER TABLE pipeline_settings ADD COLUMN review_failure_mode TEXT NOT NULL DEFAULT 'skip_acceptance'"
            )
        if "next_heartbeat_override_at" not in settings_columns:
            conn.execute(
                "ALTER TABLE pipeline_settings ADD COLUMN next_heartbeat_override_at TEXT"
            )
        conn.execute(
            """
            UPDATE pipeline_settings
            SET automation_enabled = CASE
                WHEN automation_enabled IS NULL OR automation_enabled = 0 THEN 0
                ELSE 1
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_settings
            SET max_retries = ?
            WHERE max_retries IS NULL OR max_retries < ?
            """,
            (DEFAULT_MAX_RETRIES, MIN_MAX_RETRIES),
        )
        conn.execute(
            """
            UPDATE pipeline_settings
            SET max_retries = ?
            WHERE max_retries > ?
            """,
            (MAX_MAX_RETRIES, MAX_MAX_RETRIES),
        )
        conn.execute(
            (
                "UPDATE pipeline_tasks SET workflow = ? "
                "WHERE COALESCE(TRIM(workflow), '') = '' OR LOWER(TRIM(workflow)) = 'assist'"
            ),
            (PIPELINE_WORKFLOW,),
        )
        conn.execute(
            (
                "UPDATE pipeline_backlog SET task_source = ? "
                "WHERE COALESCE(TRIM(task_source), '') = '' "
                "OR LOWER(TRIM(task_source)) NOT IN ('jira', 'spec')"
            ),
            (PIPELINE_TASK_SOURCE_JIRA,),
        )
        conn.execute(
            """
            UPDATE pipeline_backlog
            SET task_reference = jira_key
            WHERE COALESCE(TRIM(task_reference), '') = ''
            """,
        )
        conn.execute(
            (
                "UPDATE pipeline_tasks SET task_source = ? "
                "WHERE COALESCE(TRIM(task_source), '') = '' "
                "OR LOWER(TRIM(task_source)) NOT IN ('jira', 'spec')"
            ),
            (PIPELINE_TASK_SOURCE_JIRA,),
        )
        conn.execute(
            (
                "UPDATE pipeline_runs SET workflow = ? "
                "WHERE COALESCE(TRIM(workflow), '') = '' OR LOWER(TRIM(workflow)) = 'assist'"
            ),
            (PIPELINE_WORKFLOW,),
        )
        conn.execute(
            (
                "UPDATE pipeline_runs SET task_source = ? "
                "WHERE COALESCE(TRIM(task_source), '') = '' "
                "OR LOWER(TRIM(task_source)) NOT IN ('jira', 'spec')"
            ),
            (PIPELINE_TASK_SOURCE_JIRA,),
        )
        conn.execute(
            """
            UPDATE pipeline_runs
            SET attempt_count = CASE
                WHEN attempt_count IS NULL OR attempt_count < 0 THEN 0
                ELSE attempt_count
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_runs
            SET max_retries = CASE
                WHEN max_retries IS NULL OR max_retries < 0 THEN 0
                ELSE max_retries
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_runs
            SET attempts_failed = CASE
                WHEN attempts_failed IS NULL OR attempts_failed < 0 THEN 0
                ELSE attempts_failed
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_runs
            SET attempts_completed = CASE
                WHEN attempts_completed IS NULL OR attempts_completed < 0 THEN 0
                ELSE attempts_completed
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_settings
            SET review_failure_mode = ?
            WHERE COALESCE(TRIM(review_failure_mode), '') = ''
            """,
            (DEFAULT_REVIEW_FAILURE_MODE,),
        )
        conn.execute(
            """
            UPDATE pipeline_settings
            SET review_failure_mode = ?
            WHERE LOWER(TRIM(review_failure_mode)) NOT IN ('strict', 'skip_acceptance', 'skip_all')
            """,
            (DEFAULT_REVIEW_FAILURE_MODE,),
        )
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET is_bypassed = CASE
                WHEN is_bypassed IS NULL OR is_bypassed = 0 THEN 0
                ELSE 1
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET is_dependency_blocked = CASE
                WHEN is_dependency_blocked IS NULL OR is_dependency_blocked = 0 THEN 0
                ELSE 1
            END
            """,
        )
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET execution_state = ?
            WHERE COALESCE(TRIM(execution_state), '') = ''
            OR LOWER(TRIM(execution_state)) NOT IN ('ready', 'blocked', 'attention_required')
            """,
            (PIPELINE_TASK_EXECUTION_STATE_READY,),
        )
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET bypass_source = NULL
            WHERE COALESCE(TRIM(bypass_source), '') <> ''
            AND LOWER(TRIM(bypass_source)) NOT IN ('manual', 'auto_failure', 'auto_handoff', 'dependency', 'branch_cohort')
            """,
        )

        migration_rows = conn.execute(
            """
            SELECT id, status, COALESCE(failure_reason, '') AS failure_reason, updated_at
            FROM pipeline_tasks
            WHERE status IN ('failed', 'stopped')
            ORDER BY updated_at ASC
            """
        ).fetchall()
        if migration_rows:
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(order_index), -1) AS max_order
                FROM pipeline_tasks
                WHERE status = ? AND order_index >= 0
                """,
                (PIPELINE_STATUS_CURRENT,),
            ).fetchone()
            next_order = int(max_row["max_order"] or -1) + 1 if max_row else 0
            now = _utc_now()
            for row in migration_rows:
                task_status = str(row["status"] or "").strip().lower()
                failure_reason = str(row["failure_reason"] or "").strip()
                if task_status == PIPELINE_STATUS_STOPPED:
                    execution_state = PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED
                    bypass_source = PIPELINE_BYPASS_SOURCE_MANUAL
                    last_failure_code = "manual_stop_requested"
                    bypass_reason = failure_reason or "Stopped by user."
                else:
                    execution_state = PIPELINE_TASK_EXECUTION_STATE_BLOCKED
                    bypass_source = PIPELINE_BYPASS_SOURCE_AUTO_FAILURE
                    last_failure_code = "legacy_failed_status"
                    bypass_reason = failure_reason or "Task failed and requires user attention."

                conn.execute(
                    """
                    UPDATE pipeline_tasks
                    SET status = ?,
                        order_index = ?,
                        is_bypassed = 1,
                        bypass_reason = ?,
                        bypass_source = ?,
                        bypassed_at = COALESCE(bypassed_at, ?),
                        bypassed_by = COALESCE(NULLIF(TRIM(COALESCE(bypassed_by, '')), ''), 'system'),
                        is_dependency_blocked = CASE
                            WHEN COALESCE(is_dependency_blocked, 0) = 1 THEN 1
                            ELSE 0
                        END,
                        execution_state = ?,
                        last_failure_code = COALESCE(NULLIF(TRIM(COALESCE(last_failure_code, '')), ''), ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        PIPELINE_STATUS_CURRENT,
                        next_order,
                        bypass_reason,
                        bypass_source,
                        now,
                        execution_state,
                        last_failure_code,
                        now,
                        str(row["id"]),
                    ),
                )
                next_order += 1

        current_reindex_rows = conn.execute(
            """
            SELECT id
            FROM pipeline_tasks
            WHERE status = ?
            ORDER BY
                CASE WHEN order_index >= 0 THEN 0 ELSE 1 END,
                order_index ASC,
                updated_at ASC
            """,
            (PIPELINE_STATUS_CURRENT,),
        ).fetchall()
        for index, row in enumerate(current_reindex_rows):
            conn.execute(
                """
                UPDATE pipeline_tasks
                SET order_index = ?, updated_at = ?
                WHERE id = ?
                """,
                (index, _utc_now(), str(row["id"])),
            )
        row = conn.execute(
            "SELECT id FROM pipeline_settings WHERE id = ?",
            (PIPELINE_ID,),
        ).fetchone()
        if not row:
            now = _utc_now()
            conn.execute(
                """
                INSERT INTO pipeline_settings (
                    id,
                    active_window_start,
                    active_window_end,
                    heartbeat_interval_minutes,
                    automation_enabled,
                    max_retries,
                    review_failure_mode,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PIPELINE_ID,
                    DEFAULT_ACTIVE_WINDOW_START,
                    DEFAULT_ACTIVE_WINDOW_END,
                    DEFAULT_HEARTBEAT_INTERVAL_MINUTES,
                    1,
                    DEFAULT_MAX_RETRIES,
                    DEFAULT_REVIEW_FAILURE_MODE,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_pipeline_settings() -> dict[str, Any]:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                active_window_start,
                active_window_end,
                heartbeat_interval_minutes,
                COALESCE(automation_enabled, 1) AS automation_enabled,
                COALESCE(max_retries, 4) AS max_retries,
                COALESCE(review_failure_mode, 'skip_acceptance') AS review_failure_mode,
                COALESCE(last_heartbeat_at, '') AS last_heartbeat_at,
                COALESCE(last_cycle_at, '') AS last_cycle_at,
                COALESCE(next_heartbeat_override_at, '') AS next_heartbeat_override_at,
                created_at,
                updated_at
            FROM pipeline_settings
            WHERE id = ?
            """,
            (PIPELINE_ID,),
        ).fetchone()
        if row:
            payload = dict(row)
            payload["automation_enabled"] = 1 if int(payload.get("automation_enabled") or 0) != 0 else 0
            payload["max_retries"] = _normalize_max_retries(payload.get("max_retries"))
            payload["review_failure_mode"] = _normalize_review_failure_mode(
                str(payload.get("review_failure_mode") or "")
            )
            return payload
    finally:
        conn.close()

    ensure_pipeline_schema()
    return get_pipeline_settings()


def update_pipeline_settings(
    *,
    active_window_start: str | None = None,
    active_window_end: str | None = None,
    heartbeat_interval_minutes: int | None = None,
    automation_enabled: bool | None = None,
    max_retries: int | None = None,
    review_failure_mode: str | None = None,
) -> dict[str, Any]:
    settings = get_pipeline_settings()
    resolved_start = (
        str(settings.get("active_window_start") or DEFAULT_ACTIVE_WINDOW_START)
        if active_window_start is None
        else str(active_window_start)
    )
    resolved_end = (
        str(settings.get("active_window_end") or DEFAULT_ACTIVE_WINDOW_END)
        if active_window_end is None
        else str(active_window_end)
    )
    resolved_interval = (
        int(settings.get("heartbeat_interval_minutes") or DEFAULT_HEARTBEAT_INTERVAL_MINUTES)
        if heartbeat_interval_minutes is None
        else int(heartbeat_interval_minutes)
    )
    resolved_automation_enabled = (
        1 if int(settings.get("automation_enabled") or 0) != 0 else 0
    ) if automation_enabled is None else (1 if bool(automation_enabled) else 0)
    resolved_max_retries = (
        _normalize_max_retries(settings.get("max_retries"), fallback=DEFAULT_MAX_RETRIES)
        if max_retries is None
        else _normalize_max_retries(max_retries)
    )
    resolved_review_failure_mode = (
        _normalize_review_failure_mode(str(settings.get("review_failure_mode") or DEFAULT_REVIEW_FAILURE_MODE))
        if review_failure_mode is None
        else _normalize_review_failure_mode(review_failure_mode)
    )
    conn = get_conn()
    try:
        now = _utc_now()
        conn.execute(
            """
            UPDATE pipeline_settings
            SET active_window_start = ?,
                active_window_end = ?,
                heartbeat_interval_minutes = ?,
                automation_enabled = ?,
                max_retries = ?,
                review_failure_mode = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                resolved_start,
                resolved_end,
                resolved_interval,
                resolved_automation_enabled,
                resolved_max_retries,
                resolved_review_failure_mode,
                now,
                PIPELINE_ID,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_pipeline_settings()


def get_shared_max_retries() -> int:
    try:
        settings = get_pipeline_settings()
    except Exception:
        return DEFAULT_MAX_RETRIES
    return _normalize_max_retries(settings.get("max_retries"), fallback=DEFAULT_MAX_RETRIES)


def update_pipeline_heartbeat(
    *,
    last_heartbeat_at: str | None = None,
    last_cycle_at: str | None = None,
    next_heartbeat_override_at: str | None = None,
) -> dict[str, Any]:
    conn = get_conn()
    try:
        settings = get_pipeline_settings()
        resolved_last_heartbeat = str(settings.get("last_heartbeat_at") or "") if last_heartbeat_at is None else last_heartbeat_at
        resolved_last_cycle = str(settings.get("last_cycle_at") or "") if last_cycle_at is None else last_cycle_at
        resolved_next_override = (
            str(settings.get("next_heartbeat_override_at") or "")
            if next_heartbeat_override_at is None
            else next_heartbeat_override_at
        )
        now = _utc_now()
        conn.execute(
            """
            UPDATE pipeline_settings
            SET last_heartbeat_at = ?,
                last_cycle_at = ?,
                next_heartbeat_override_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                resolved_last_heartbeat,
                resolved_last_cycle,
                resolved_next_override,
                now,
                PIPELINE_ID,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_pipeline_settings()


def replace_pipeline_backlog(items: list[dict[str, Any]], fetched_at: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM pipeline_backlog")
        for item in items:
            key = str(item.get("key") or "").strip().upper()
            if not key:
                continue
            task_source = _normalize_task_source(str(item.get("task_source") or ""))
            task_reference = str(item.get("task_reference") or key).strip() or key
            conn.execute(
                """
                INSERT INTO pipeline_backlog (
                    jira_key,
                    task_source,
                    task_reference,
                    title,
                    issue_type,
                    status,
                    priority,
                    assignee,
                    updated,
                    payload_json,
                    fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    task_source,
                    task_reference,
                    str(item.get("summary") or item.get("title") or "Untitled pipeline task"),
                    str(item.get("issue_type") or ""),
                    str(item.get("status") or ""),
                    str(item.get("priority") or ""),
                    str(item.get("assignee") or ""),
                    str(item.get("updated") or ""),
                    str(item.get("payload_json") or "{}"),
                    fetched_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def list_pipeline_backlog(limit: int = 400) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 1000))
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                jira_key,
                COALESCE(task_source, 'jira') AS task_source,
                COALESCE(task_reference, jira_key) AS task_reference,
                title,
                issue_type,
                status,
                priority,
                assignee,
                updated,
                payload_json,
                fetched_at
            FROM pipeline_backlog
            ORDER BY updated DESC, jira_key ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_backlog_item(jira_key: str) -> dict[str, Any] | None:
    key = str(jira_key or "").strip().upper()
    if not key:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                jira_key,
                COALESCE(task_source, 'jira') AS task_source,
                COALESCE(task_reference, jira_key) AS task_reference,
                title,
                issue_type,
                status,
                priority,
                assignee,
                updated,
                payload_json,
                fetched_at
            FROM pipeline_backlog
            WHERE jira_key = ?
            """,
            (key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_pipeline_tasks() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                jira_key,
                COALESCE(task_source, 'jira') AS task_source,
                COALESCE(task_relation, 'task') AS task_relation,
                title,
                workspace_path,
                COALESCE(jira_complete_column_name, '') AS jira_complete_column_name,
                COALESCE(starting_git_branch_override, '') AS starting_git_branch_override,
                workflow,
                status,
                order_index,
                version,
                COALESCE(failure_reason, '') AS failure_reason,
                COALESCE(is_bypassed, 0) AS is_bypassed,
                COALESCE(bypass_reason, '') AS bypass_reason,
                COALESCE(bypass_source, '') AS bypass_source,
                COALESCE(bypassed_at, '') AS bypassed_at,
                COALESCE(bypassed_by, '') AS bypassed_by,
                COALESCE(is_dependency_blocked, 0) AS is_dependency_blocked,
                COALESCE(dependency_block_reason, '') AS dependency_block_reason,
                COALESCE(execution_state, 'ready') AS execution_state,
                COALESCE(last_failure_code, '') AS last_failure_code,
                jira_payload_json,
                COALESCE(active_run_id, '') AS active_run_id,
                created_at,
                updated_at
            FROM pipeline_tasks
            ORDER BY
                CASE status
                    WHEN 'running' THEN 0
                    WHEN 'current' THEN 1
                    WHEN 'complete' THEN 2
                    WHEN 'stopped' THEN 3
                    WHEN 'failed' THEN 4
                    ELSE 5
                END,
                order_index ASC,
                updated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_pipeline_task(task_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                jira_key,
                COALESCE(task_source, 'jira') AS task_source,
                COALESCE(task_relation, 'task') AS task_relation,
                title,
                workspace_path,
                COALESCE(jira_complete_column_name, '') AS jira_complete_column_name,
                COALESCE(starting_git_branch_override, '') AS starting_git_branch_override,
                workflow,
                status,
                order_index,
                version,
                COALESCE(failure_reason, '') AS failure_reason,
                COALESCE(is_bypassed, 0) AS is_bypassed,
                COALESCE(bypass_reason, '') AS bypass_reason,
                COALESCE(bypass_source, '') AS bypass_source,
                COALESCE(bypassed_at, '') AS bypassed_at,
                COALESCE(bypassed_by, '') AS bypassed_by,
                COALESCE(is_dependency_blocked, 0) AS is_dependency_blocked,
                COALESCE(dependency_block_reason, '') AS dependency_block_reason,
                COALESCE(execution_state, 'ready') AS execution_state,
                COALESCE(last_failure_code, '') AS last_failure_code,
                jira_payload_json,
                COALESCE(active_run_id, '') AS active_run_id,
                created_at,
                updated_at
            FROM pipeline_tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _next_current_order_index(conn: Any) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) AS max_order FROM pipeline_tasks WHERE status = ?",
        (PIPELINE_STATUS_CURRENT,),
    ).fetchone()
    if not row:
        return 0
    return int(row["max_order"] or -1) + 1


def queue_pipeline_task(
    *,
    jira_key: str,
    task_source: str,
    task_relation: str | None = None,
    title: str,
    workspace_path: str,
    jira_complete_column_name: str | None,
    starting_git_branch_override: str | None,
    workflow: str,
    jira_payload_json: str,
) -> dict[str, Any]:
    key = str(jira_key or "").strip().upper()
    if not key:
        raise ValueError("jira_key is required")
    if not workspace_path.strip():
        raise ValueError("workspace_path is required")
    normalized_workflow = _normalize_workflow(workflow)
    normalized_task_source = _normalize_task_source(task_source)
    normalized_task_relation = _normalize_task_relation(task_relation)
    normalized_jira_complete_column_name = str(jira_complete_column_name or "").strip()
    normalized_starting_git_branch_override = str(starting_git_branch_override or "").strip()

    conn = get_conn()
    try:
        now = _utc_now()
        existing = conn.execute(
            "SELECT id, status, version FROM pipeline_tasks WHERE jira_key = ?",
            (key,),
        ).fetchone()
        if existing:
            next_version = int(existing["version"] or 1)
            existing_status = str(existing["status"] or "")
            if existing_status in {PIPELINE_STATUS_COMPLETE, PIPELINE_STATUS_FAILED}:
                next_version += 1
            next_order = _next_current_order_index(conn)
            conn.execute(
                """
                UPDATE pipeline_tasks
                SET title = ?,
                    workspace_path = ?,
                    jira_complete_column_name = ?,
                    starting_git_branch_override = ?,
                    task_source = ?,
                    task_relation = ?,
                    workflow = ?,
                    status = ?,
                    order_index = ?,
                    version = ?,
                    failure_reason = NULL,
                    is_bypassed = 0,
                    bypass_reason = NULL,
                    bypass_source = NULL,
                    bypassed_at = NULL,
                    bypassed_by = NULL,
                    is_dependency_blocked = 0,
                    dependency_block_reason = NULL,
                    execution_state = ?,
                    last_failure_code = NULL,
                    jira_payload_json = ?,
                    active_run_id = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    workspace_path,
                    normalized_jira_complete_column_name,
                    normalized_starting_git_branch_override,
                    normalized_task_source,
                    normalized_task_relation,
                    normalized_workflow,
                    PIPELINE_STATUS_CURRENT,
                    next_order,
                    next_version,
                    PIPELINE_TASK_EXECUTION_STATE_READY,
                    jira_payload_json,
                    now,
                    str(existing["id"]),
                ),
            )
            task_id = str(existing["id"])
        else:
            task_id = str(uuid.uuid4())
            next_order = _next_current_order_index(conn)
            conn.execute(
                """
                INSERT INTO pipeline_tasks (
                    id,
                    jira_key,
                    task_source,
                    task_relation,
                    title,
                    workspace_path,
                    jira_complete_column_name,
                    starting_git_branch_override,
                    workflow,
                    status,
                    order_index,
                    version,
                    failure_reason,
                    is_bypassed,
                    bypass_reason,
                    bypass_source,
                    bypassed_at,
                    bypassed_by,
                    is_dependency_blocked,
                    dependency_block_reason,
                    execution_state,
                    last_failure_code,
                    jira_payload_json,
                    active_run_id,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, NULL, NULL, NULL, 0, NULL, ?, NULL, ?, NULL, ?, ?)
                """,
                (
                    task_id,
                    key,
                    normalized_task_source,
                    normalized_task_relation,
                    title,
                    workspace_path,
                    normalized_jira_complete_column_name,
                    normalized_starting_git_branch_override,
                    normalized_workflow,
                    PIPELINE_STATUS_CURRENT,
                    next_order,
                    1,
                    PIPELINE_TASK_EXECUTION_STATE_READY,
                    jira_payload_json,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    task = get_pipeline_task(task_id)
    if not task:
        raise RuntimeError("Failed to queue pipeline task")
    return task


def move_pipeline_task(
    task_id: str,
    *,
    target_status: str,
    workspace_path: str | None = None,
    jira_complete_column_name: str | None = None,
    starting_git_branch_override: str | None = None,
    workflow: str | None = None,
    task_relation: str | None = None,
    increment_version: bool = False,
    failure_reason: str | None = None,
    is_bypassed: bool | None = None,
    bypass_reason: str | None = None,
    bypass_source: str | None = None,
    bypassed_by: str | None = None,
    is_dependency_blocked: bool | None = None,
    dependency_block_reason: str | None = None,
    execution_state: str | None = None,
    last_failure_code: str | None = None,
) -> dict[str, Any] | None:
    task = get_pipeline_task(task_id)
    if not task:
        return None

    normalized_status = str(target_status or "").strip().lower()
    if normalized_status not in {
        PIPELINE_STATUS_CURRENT,
        PIPELINE_STATUS_RUNNING,
        PIPELINE_STATUS_COMPLETE,
        PIPELINE_STATUS_FAILED,
        PIPELINE_STATUS_STOPPED,
        PIPELINE_STATUS_BACKLOG,
    }:
        raise ValueError("Invalid target status")

    normalized_failure_reason = str(failure_reason or "").strip()
    legacy_failure_status = normalized_status if normalized_status in {PIPELINE_STATUS_FAILED, PIPELINE_STATUS_STOPPED} else ""
    effective_status = PIPELINE_STATUS_CURRENT if legacy_failure_status else normalized_status

    conn = get_conn()
    try:
        now = _utc_now()
        next_order = task.get("order_index") or 0
        if effective_status == PIPELINE_STATUS_CURRENT:
            next_order = _next_current_order_index(conn)
        elif effective_status in {
            PIPELINE_STATUS_RUNNING,
            PIPELINE_STATUS_COMPLETE,
            PIPELINE_STATUS_FAILED,
            PIPELINE_STATUS_STOPPED,
            PIPELINE_STATUS_BACKLOG,
        }:
            next_order = -1

        version = int(task.get("version") or 1)
        if increment_version:
            version += 1
        next_workflow = _normalize_workflow(workflow, fallback=str(task.get("workflow") or PIPELINE_WORKFLOW))
        next_task_relation = (
            _normalize_task_relation(task_relation)
            if task_relation is not None
            else _normalize_task_relation(str(task.get("task_relation") or ""))
        )
        next_jira_complete_column_name = (
            str(jira_complete_column_name).strip()
            if jira_complete_column_name is not None
            else str(task.get("jira_complete_column_name") or "").strip()
        )
        next_starting_git_branch_override = (
            str(starting_git_branch_override).strip()
            if starting_git_branch_override is not None
            else str(task.get("starting_git_branch_override") or "").strip()
        )
        next_execution_state = _normalize_execution_state(execution_state)
        next_is_bypassed = _to_bool_int(is_bypassed)
        next_bypass_source = (
            _normalize_bypass_source(bypass_source)
            if str(bypass_source or "").strip()
            else ""
        )
        next_bypass_reason = str(bypass_reason or "").strip()
        next_bypassed_by = str(bypassed_by or "").strip()
        next_is_dependency_blocked = _to_bool_int(is_dependency_blocked)
        next_dependency_block_reason = str(dependency_block_reason or "").strip()
        next_last_failure_code = str(last_failure_code or "").strip()
        next_failure_reason = normalized_failure_reason

        if not legacy_failure_status:
            if effective_status == PIPELINE_STATUS_CURRENT:
                if execution_state is None:
                    next_execution_state = PIPELINE_TASK_EXECUTION_STATE_READY
                if is_bypassed is None:
                    next_is_bypassed = 0
                if bypass_reason is None:
                    next_bypass_reason = ""
                if bypass_source is None:
                    next_bypass_source = ""
                if bypassed_by is None:
                    next_bypassed_by = ""
                if is_dependency_blocked is None:
                    next_is_dependency_blocked = 0
                if dependency_block_reason is None:
                    next_dependency_block_reason = ""
                if last_failure_code is None:
                    next_last_failure_code = ""
                if failure_reason is None:
                    next_failure_reason = ""
            elif effective_status in {PIPELINE_STATUS_RUNNING, PIPELINE_STATUS_COMPLETE, PIPELINE_STATUS_BACKLOG}:
                if execution_state is None:
                    next_execution_state = PIPELINE_TASK_EXECUTION_STATE_READY
                if is_bypassed is None:
                    next_is_bypassed = 0
                if bypass_reason is None:
                    next_bypass_reason = ""
                if bypass_source is None:
                    next_bypass_source = ""
                if bypassed_by is None:
                    next_bypassed_by = ""
                if is_dependency_blocked is None:
                    next_is_dependency_blocked = 0
                if dependency_block_reason is None:
                    next_dependency_block_reason = ""
                if last_failure_code is None:
                    next_last_failure_code = ""
                if failure_reason is None:
                    next_failure_reason = ""

        if legacy_failure_status == PIPELINE_STATUS_STOPPED:
            next_execution_state = (
                _normalize_execution_state(execution_state)
                if execution_state is not None
                else PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED
            )
            next_is_bypassed = 1 if is_bypassed is None else _to_bool_int(is_bypassed)
            next_bypass_source = (
                _normalize_bypass_source(bypass_source)
                if str(bypass_source or "").strip()
                else PIPELINE_BYPASS_SOURCE_MANUAL
            )
            next_bypass_reason = (
                str(bypass_reason or "").strip()
                if bypass_reason is not None
                else str(task.get("failure_reason") or "").strip() or "Stopped by user."
            )
            next_bypassed_by = (
                str(bypassed_by or "").strip()
                if bypassed_by is not None
                else str(task.get("bypassed_by") or "").strip() or "user"
            )
            next_last_failure_code = (
                str(last_failure_code or "").strip()
                if last_failure_code is not None
                else "manual_stop_requested"
            )
            if failure_reason is None:
                next_failure_reason = str(task.get("failure_reason") or "").strip() or "Stopped by user."

        if legacy_failure_status == PIPELINE_STATUS_FAILED:
            next_execution_state = (
                _normalize_execution_state(execution_state)
                if execution_state is not None
                else PIPELINE_TASK_EXECUTION_STATE_BLOCKED
            )
            next_is_bypassed = 1 if is_bypassed is None else _to_bool_int(is_bypassed)
            next_bypass_source = (
                _normalize_bypass_source(bypass_source)
                if str(bypass_source or "").strip()
                else PIPELINE_BYPASS_SOURCE_AUTO_FAILURE
            )
            next_bypass_reason = (
                str(bypass_reason or "").strip()
                if bypass_reason is not None
                else str(task.get("failure_reason") or "").strip() or "Task failed and requires attention."
            )
            next_bypassed_by = (
                str(bypassed_by or "").strip()
                if bypassed_by is not None
                else str(task.get("bypassed_by") or "").strip() or "system"
            )
            next_last_failure_code = (
                str(last_failure_code or "").strip()
                if last_failure_code is not None
                else "task_failed"
            )
            if failure_reason is None:
                next_failure_reason = str(task.get("failure_reason") or "").strip() or "Task failed."

        conn.execute(
            """
            UPDATE pipeline_tasks
            SET workspace_path = ?,
                jira_complete_column_name = ?,
                starting_git_branch_override = ?,
                workflow = ?,
                task_relation = ?,
                status = ?,
                order_index = ?,
                version = ?,
                failure_reason = ?,
                is_bypassed = ?,
                bypass_reason = ?,
                bypass_source = ?,
                bypassed_at = CASE WHEN ? = 1 THEN COALESCE(NULLIF(TRIM(COALESCE(bypassed_at, '')), ''), ?) ELSE NULL END,
                bypassed_by = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                is_dependency_blocked = ?,
                dependency_block_reason = ?,
                execution_state = ?,
                last_failure_code = ?,
                active_run_id = CASE WHEN ? = 'running' THEN active_run_id ELSE NULL END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                workspace_path or str(task.get("workspace_path") or ""),
                next_jira_complete_column_name,
                next_starting_git_branch_override,
                next_workflow,
                next_task_relation,
                effective_status,
                int(next_order),
                version,
                next_failure_reason or None,
                next_is_bypassed,
                next_bypass_reason or None,
                next_bypass_source or None,
                next_is_bypassed,
                now,
                next_is_bypassed,
                next_bypassed_by or None,
                next_is_dependency_blocked,
                next_dependency_block_reason or None,
                next_execution_state,
                next_last_failure_code or None,
                effective_status,
                now,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_pipeline_task(task_id)


def update_pipeline_task_controls(
    task_id: str,
    *,
    failure_reason: str | None = None,
    clear_failure_reason: bool = False,
    is_bypassed: bool | None = None,
    bypass_reason: str | None = None,
    bypass_source: str | None = None,
    bypassed_by: str | None = None,
    is_dependency_blocked: bool | None = None,
    dependency_block_reason: str | None = None,
    execution_state: str | None = None,
    last_failure_code: str | None = None,
) -> dict[str, Any] | None:
    task = get_pipeline_task(task_id)
    if not task:
        return None

    next_failure_reason = (
        ""
        if clear_failure_reason
        else (
            str(failure_reason or "").strip()
            if failure_reason is not None
            else str(task.get("failure_reason") or "").strip()
        )
    )
    next_is_bypassed = (
        _to_bool_int(is_bypassed)
        if is_bypassed is not None
        else _to_bool_int(task.get("is_bypassed"))
    )
    next_bypass_reason = (
        str(bypass_reason or "").strip()
        if bypass_reason is not None
        else str(task.get("bypass_reason") or "").strip()
    )
    next_bypass_source = (
        _normalize_bypass_source(bypass_source)
        if bypass_source is not None and str(bypass_source or "").strip()
        else str(task.get("bypass_source") or "").strip()
    )
    next_bypassed_by = (
        str(bypassed_by or "").strip()
        if bypassed_by is not None
        else str(task.get("bypassed_by") or "").strip()
    )
    next_is_dependency_blocked = (
        _to_bool_int(is_dependency_blocked)
        if is_dependency_blocked is not None
        else _to_bool_int(task.get("is_dependency_blocked"))
    )
    next_dependency_block_reason = (
        str(dependency_block_reason or "").strip()
        if dependency_block_reason is not None
        else str(task.get("dependency_block_reason") or "").strip()
    )
    next_execution_state = (
        _normalize_execution_state(execution_state)
        if execution_state is not None
        else _normalize_execution_state(str(task.get("execution_state") or ""))
    )
    next_last_failure_code = (
        str(last_failure_code or "").strip()
        if last_failure_code is not None
        else str(task.get("last_failure_code") or "").strip()
    )
    now = _utc_now()

    if next_is_bypassed == 0:
        next_bypass_reason = ""
        next_bypass_source = ""
        next_bypassed_by = ""
    elif not next_bypass_source:
        next_bypass_source = PIPELINE_BYPASS_SOURCE_MANUAL

    if next_is_dependency_blocked == 0:
        next_dependency_block_reason = ""

    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET failure_reason = ?,
                is_bypassed = ?,
                bypass_reason = ?,
                bypass_source = ?,
                bypassed_at = CASE
                    WHEN ? = 1 THEN COALESCE(NULLIF(TRIM(COALESCE(bypassed_at, '')), ''), ?)
                    ELSE NULL
                END,
                bypassed_by = CASE
                    WHEN ? = 1 THEN ?
                    ELSE NULL
                END,
                is_dependency_blocked = ?,
                dependency_block_reason = ?,
                execution_state = ?,
                last_failure_code = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                next_failure_reason or None,
                next_is_bypassed,
                next_bypass_reason or None,
                next_bypass_source or None,
                next_is_bypassed,
                now,
                next_is_bypassed,
                next_bypassed_by or None,
                next_is_dependency_blocked,
                next_dependency_block_reason or None,
                next_execution_state,
                next_last_failure_code or None,
                now,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_pipeline_task(task_id)


def list_pipeline_task_dependencies(
    *,
    task_id: str | None = None,
    depends_on_task_id: str | None = None,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if task_id:
        filters.append("task_id = ?")
        params.append(str(task_id).strip())
    if depends_on_task_id:
        filters.append("depends_on_task_id = ?")
        params.append(str(depends_on_task_id).strip())

    where_sql = ""
    if filters:
        where_sql = "WHERE " + " AND ".join(filters)

    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT
                id,
                task_id,
                depends_on_task_id,
                COALESCE(dependency_type, 'hard') AS dependency_type,
                created_at,
                updated_at
            FROM pipeline_task_dependencies
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def replace_pipeline_task_dependencies(task_id: str, depends_on_task_ids: list[str]) -> list[dict[str, Any]]:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise ValueError("task_id is required")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in depends_on_task_ids:
        normalized = str(item or "").strip()
        if not normalized or normalized == normalized_task_id or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    now = _utc_now()
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM pipeline_task_dependencies WHERE task_id = ?",
            (normalized_task_id,),
        )
        for depends_on_id in deduped:
            conn.execute(
                """
                INSERT INTO pipeline_task_dependencies (
                    id,
                    task_id,
                    depends_on_task_id,
                    dependency_type,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    normalized_task_id,
                    depends_on_id,
                    "hard",
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return list_pipeline_task_dependencies(task_id=normalized_task_id)


def list_pipeline_task_dependents(depends_on_task_id: str) -> list[str]:
    normalized_depends_on_id = str(depends_on_task_id or "").strip()
    if not normalized_depends_on_id:
        return []

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT task_id
            FROM pipeline_task_dependencies
            WHERE depends_on_task_id = ?
            ORDER BY updated_at DESC
            """,
            (normalized_depends_on_id,),
        ).fetchall()
        return [str(row["task_id"]) for row in rows if str(row["task_id"] or "").strip()]
    finally:
        conn.close()


def list_dependency_blocked_current_task_ids() -> list[str]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id
            FROM pipeline_tasks
            WHERE status = ?
              AND COALESCE(is_dependency_blocked, 0) = 1
            ORDER BY order_index ASC, updated_at ASC
            """,
            (PIPELINE_STATUS_CURRENT,),
        ).fetchall()
        return [str(row["id"]) for row in rows if str(row["id"] or "").strip()]
    finally:
        conn.close()


def add_pipeline_git_handoff(
    *,
    task_id: str,
    jira_key: str,
    reason: str,
    strategy: str,
    run_id: str | None = None,
    stash_ref: str | None = None,
    commit_sha: str | None = None,
    source_branch: str | None = None,
    target_branch: str | None = None,
    file_summary: Any | None = None,
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    normalized_jira_key = str(jira_key or "").strip().upper()
    normalized_reason = str(reason or "").strip()
    normalized_strategy = str(strategy or "").strip().lower() or "manual_required"
    if not normalized_task_id:
        raise ValueError("task_id is required")
    if not normalized_jira_key:
        raise ValueError("jira_key is required")
    if not normalized_reason:
        raise ValueError("reason is required")

    serialized_file_summary = file_summary if file_summary is not None else []
    file_summary_json = json.dumps(serialized_file_summary, ensure_ascii=False)
    now = _utc_now()
    handoff_id = str(uuid.uuid4())

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO pipeline_git_handoffs (
                id,
                task_id,
                run_id,
                jira_key,
                strategy,
                stash_ref,
                commit_sha,
                source_branch,
                target_branch,
                file_summary_json,
                reason,
                resolved,
                resolved_at,
                resolved_by,
                resolution_note,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?, ?)
            """,
            (
                handoff_id,
                normalized_task_id,
                str(run_id or "").strip() or None,
                normalized_jira_key,
                normalized_strategy,
                str(stash_ref or "").strip() or None,
                str(commit_sha or "").strip() or None,
                str(source_branch or "").strip() or None,
                str(target_branch or "").strip() or None,
                file_summary_json,
                normalized_reason,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    row = get_pipeline_git_handoff(handoff_id)
    if not row:
        raise RuntimeError("Failed to create pipeline git handoff")
    return row


def get_pipeline_git_handoff(handoff_id: str) -> dict[str, Any] | None:
    normalized_handoff_id = str(handoff_id or "").strip()
    if not normalized_handoff_id:
        return None

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                task_id,
                COALESCE(run_id, '') AS run_id,
                jira_key,
                strategy,
                COALESCE(stash_ref, '') AS stash_ref,
                COALESCE(commit_sha, '') AS commit_sha,
                COALESCE(source_branch, '') AS source_branch,
                COALESCE(target_branch, '') AS target_branch,
                file_summary_json,
                reason,
                COALESCE(resolved, 0) AS resolved,
                COALESCE(resolved_at, '') AS resolved_at,
                COALESCE(resolved_by, '') AS resolved_by,
                COALESCE(resolution_note, '') AS resolution_note,
                created_at,
                updated_at
            FROM pipeline_git_handoffs
            WHERE id = ?
            """,
            (normalized_handoff_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["file_summary"] = json.loads(str(item.get("file_summary_json") or "[]"))
        except Exception:
            item["file_summary"] = []
        return item
    finally:
        conn.close()


def list_pipeline_git_handoffs(
    *,
    task_id: str | None = None,
    unresolved_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    filters: list[str] = []
    params: list[Any] = []
    if task_id:
        filters.append("task_id = ?")
        params.append(str(task_id).strip())
    if unresolved_only:
        filters.append("COALESCE(resolved, 0) = 0")

    where_sql = ""
    if filters:
        where_sql = "WHERE " + " AND ".join(filters)

    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT
                id,
                task_id,
                COALESCE(run_id, '') AS run_id,
                jira_key,
                strategy,
                COALESCE(stash_ref, '') AS stash_ref,
                COALESCE(commit_sha, '') AS commit_sha,
                COALESCE(source_branch, '') AS source_branch,
                COALESCE(target_branch, '') AS target_branch,
                file_summary_json,
                reason,
                COALESCE(resolved, 0) AS resolved,
                COALESCE(resolved_at, '') AS resolved_at,
                COALESCE(resolved_by, '') AS resolved_by,
                COALESCE(resolution_note, '') AS resolution_note,
                created_at,
                updated_at
            FROM pipeline_git_handoffs
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [*params, safe_limit],
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            try:
                item["file_summary"] = json.loads(str(item.get("file_summary_json") or "[]"))
            except Exception:
                item["file_summary"] = []
        return items
    finally:
        conn.close()


def resolve_pipeline_git_handoff(
    handoff_id: str,
    *,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> dict[str, Any] | None:
    existing = get_pipeline_git_handoff(handoff_id)
    if not existing:
        return None

    now = _utc_now()
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE pipeline_git_handoffs
            SET resolved = 1,
                resolved_at = ?,
                resolved_by = ?,
                resolution_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                str(resolved_by or "").strip() or "user",
                str(resolution_note or "").strip() or None,
                now,
                str(handoff_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_pipeline_git_handoff(handoff_id)


def has_unresolved_pipeline_git_handoff(task_id: str) -> bool:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return False

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM pipeline_git_handoffs
            WHERE task_id = ? AND COALESCE(resolved, 0) = 0
            LIMIT 1
            """,
            (normalized_task_id,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def reorder_current_pipeline_tasks(ordered_task_ids: list[str]) -> None:
    ids = [str(item).strip() for item in ordered_task_ids if str(item).strip()]
    conn = get_conn()
    try:
        current_rows = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE status = ? ORDER BY order_index ASC",
            (PIPELINE_STATUS_CURRENT,),
        ).fetchall()
        existing_ids = [str(row["id"]) for row in current_rows]
        ordered: list[str] = []
        for item in ids:
            if item in existing_ids and item not in ordered:
                ordered.append(item)
        for item in existing_ids:
            if item not in ordered:
                ordered.append(item)

        now = _utc_now()
        for index, task_id in enumerate(ordered):
            conn.execute(
                """
                UPDATE pipeline_tasks
                SET order_index = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (index, now, task_id, PIPELINE_STATUS_CURRENT),
            )
        conn.commit()
    finally:
        conn.close()


def has_running_pipeline_task() -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE status = ? LIMIT 1",
            (PIPELINE_STATUS_RUNNING,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def pop_next_current_pipeline_task() -> dict[str, Any] | None:
    conn = get_conn()
    try:
        running = conn.execute(
            "SELECT id FROM pipeline_tasks WHERE status = ? LIMIT 1",
            (PIPELINE_STATUS_RUNNING,),
        ).fetchone()
        if running:
            return None

        row = conn.execute(
            """
            SELECT id
            FROM pipeline_tasks
            WHERE status = ?
              AND COALESCE(is_bypassed, 0) = 0
              AND COALESCE(is_dependency_blocked, 0) = 0
              AND COALESCE(execution_state, 'ready') = 'ready'
              AND NOT EXISTS (
                  SELECT 1
                  FROM pipeline_git_handoffs handoff
                  WHERE handoff.task_id = pipeline_tasks.id
                    AND COALESCE(handoff.resolved, 0) = 0
              )
            ORDER BY order_index ASC, updated_at ASC
            LIMIT 1
            """,
            (PIPELINE_STATUS_CURRENT,),
        ).fetchone()
        if not row:
            return None

        task_id = str(row["id"])
        now = _utc_now()
        conn.execute(
            """
            UPDATE pipeline_tasks
            SET status = ?,
                order_index = -1,
                failure_reason = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (PIPELINE_STATUS_RUNNING, now, task_id),
        )
        conn.commit()
    finally:
        conn.close()

    return get_pipeline_task(task_id)


def set_pipeline_task_active_run(task_id: str, run_id: str | None) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE pipeline_tasks SET active_run_id = ?, updated_at = ? WHERE id = ?",
            (run_id, _utc_now(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_pipeline_task_result(task_id: str, *, status: str, failure_reason: str | None = None) -> dict[str, Any] | None:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {
        PIPELINE_STATUS_COMPLETE,
        PIPELINE_STATUS_FAILED,
        PIPELINE_STATUS_RUNNING,
        PIPELINE_STATUS_CURRENT,
        PIPELINE_STATUS_STOPPED,
        PIPELINE_STATUS_BACKLOG,
    }:
        raise ValueError("Invalid task status")

    conn = get_conn()
    try:
        task = get_pipeline_task(task_id)
        if not task:
            return None

        now = _utc_now()
        normalized_failure_reason = str(failure_reason or "").strip()
        effective_status = normalized_status
        execution_state = PIPELINE_TASK_EXECUTION_STATE_READY
        is_bypassed = 0
        bypass_reason = ""
        bypass_source = ""
        bypassed_by = ""
        is_dependency_blocked = int(task.get("is_dependency_blocked") or 0)
        dependency_block_reason = str(task.get("dependency_block_reason") or "").strip()
        last_failure_code = ""
        next_order = -1

        if normalized_status == PIPELINE_STATUS_RUNNING:
            next_order = -1
            normalized_failure_reason = ""
        elif normalized_status == PIPELINE_STATUS_COMPLETE:
            next_order = -1
            normalized_failure_reason = ""
            is_dependency_blocked = 0
            dependency_block_reason = ""
        elif normalized_status == PIPELINE_STATUS_BACKLOG:
            next_order = -1
            normalized_failure_reason = ""
            is_dependency_blocked = 0
            dependency_block_reason = ""
        elif normalized_status == PIPELINE_STATUS_CURRENT:
            next_order = _next_current_order_index(conn)
            normalized_failure_reason = ""
            is_dependency_blocked = 0
            dependency_block_reason = ""
        elif normalized_status == PIPELINE_STATUS_FAILED:
            effective_status = PIPELINE_STATUS_CURRENT
            next_order = _next_current_order_index(conn)
            execution_state = PIPELINE_TASK_EXECUTION_STATE_BLOCKED
            is_bypassed = 1
            bypass_source = PIPELINE_BYPASS_SOURCE_AUTO_FAILURE
            bypass_reason = normalized_failure_reason or "Task failed and requires attention."
            bypassed_by = "system"
            last_failure_code = "task_failed"
            if not normalized_failure_reason:
                normalized_failure_reason = "Task failed."
        elif normalized_status == PIPELINE_STATUS_STOPPED:
            effective_status = PIPELINE_STATUS_CURRENT
            next_order = _next_current_order_index(conn)
            execution_state = PIPELINE_TASK_EXECUTION_STATE_ATTENTION_REQUIRED
            is_bypassed = 1
            bypass_source = PIPELINE_BYPASS_SOURCE_MANUAL
            bypass_reason = normalized_failure_reason or "Stopped by user."
            bypassed_by = "user"
            last_failure_code = "manual_stop_requested"
            if not normalized_failure_reason:
                normalized_failure_reason = "Stopped by user."

        conn.execute(
            """
            UPDATE pipeline_tasks
            SET status = ?,
                order_index = ?,
                failure_reason = ?,
                is_bypassed = ?,
                bypass_reason = ?,
                bypass_source = ?,
                bypassed_at = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                bypassed_by = CASE WHEN ? = 1 THEN ? ELSE NULL END,
                is_dependency_blocked = ?,
                dependency_block_reason = ?,
                execution_state = ?,
                last_failure_code = ?,
                active_run_id = CASE WHEN ? = 'running' THEN active_run_id ELSE NULL END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                effective_status,
                int(next_order),
                normalized_failure_reason or None,
                is_bypassed,
                bypass_reason or None,
                bypass_source or None,
                is_bypassed,
                now,
                is_bypassed,
                bypassed_by or None,
                is_dependency_blocked,
                dependency_block_reason or None,
                execution_state,
                last_failure_code or None,
                effective_status,
                now,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_pipeline_task(task_id)


def reset_pipeline_task_runtime(
    task_id: str,
    *,
    clear_dependencies: bool = True,
    clear_task_logs: bool = False,
) -> dict[str, Any] | None:
    task = get_pipeline_task(task_id)
    if not task:
        return None

    conn = get_conn()
    try:
        now = _utc_now()
        next_order = _next_current_order_index(conn)
        normalized_task_id = str(task_id).strip()

        conn.execute(
            """
            UPDATE pipeline_tasks
            SET status = ?,
                order_index = ?,
                failure_reason = NULL,
                is_bypassed = 0,
                bypass_reason = NULL,
                bypass_source = NULL,
                bypassed_at = NULL,
                bypassed_by = NULL,
                is_dependency_blocked = 0,
                dependency_block_reason = NULL,
                execution_state = ?,
                last_failure_code = NULL,
                active_run_id = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                PIPELINE_STATUS_CURRENT,
                next_order,
                PIPELINE_TASK_EXECUTION_STATE_READY,
                now,
                normalized_task_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM pipeline_runs
            WHERE task_id = ?
            """,
            (normalized_task_id,),
        )

        conn.execute(
            """
            DELETE FROM pipeline_git_handoffs
            WHERE task_id = ?
            """,
            (normalized_task_id,),
        )

        if clear_dependencies:
            conn.execute(
                """
                DELETE FROM pipeline_task_dependencies
                WHERE task_id = ? OR depends_on_task_id = ?
                """,
                (normalized_task_id, normalized_task_id),
            )

        if clear_task_logs:
            conn.execute(
                """
                DELETE FROM pipeline_logs
                WHERE task_id = ?
                """,
                (normalized_task_id,),
            )

        conn.commit()
    finally:
        conn.close()

    return get_pipeline_task(task_id)


def create_pipeline_run(
    *,
    task_id: str,
    jira_key: str,
    task_source: str,
    version: int,
    workspace_path: str,
    workflow: str,
) -> dict[str, Any]:
    conn = get_conn()
    run_id = str(uuid.uuid4())
    now = _utc_now()
    try:
        normalized_workflow = _normalize_workflow(workflow)
        normalized_task_source = _normalize_task_source(task_source)
        conn.execute(
            """
            INSERT INTO pipeline_runs (
                id,
                task_id,
                jira_key,
                task_source,
                version,
                status,
                workspace_path,
                workflow,
                attempt_count,
                max_retries,
                attempts_failed,
                attempts_completed,
                current_activity,
                started_at,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_id,
                jira_key,
                normalized_task_source,
                int(version),
                PIPELINE_RUN_STATUS_RUNNING,
                workspace_path,
                normalized_workflow,
                0,
                0,
                0,
                0,
                "",
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    row = get_pipeline_run(run_id)
    if not row:
        raise RuntimeError("Failed to create pipeline run")
    return row


def get_pipeline_run(run_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                task_id,
                jira_key,
                COALESCE(task_source, 'jira') AS task_source,
                version,
                status,
                workspace_path,
                workflow,
                COALESCE(attempt_count, 0) AS attempt_count,
                COALESCE(max_retries, 0) AS max_retries,
                COALESCE(attempts_failed, 0) AS attempts_failed,
                COALESCE(attempts_completed, 0) AS attempts_completed,
                COALESCE(current_activity, '') AS current_activity,
                COALESCE(brief_path, '') AS brief_path,
                COALESCE(spec_path, '') AS spec_path,
                COALESCE(task_path, '') AS task_path,
                COALESCE(codex_status, '') AS codex_status,
                COALESCE(codex_summary, '') AS codex_summary,
                COALESCE(failure_reason, '') AS failure_reason,
                started_at,
                COALESCE(ended_at, '') AS ended_at,
                created_at,
                updated_at
            FROM pipeline_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_pipeline_runs(*, task_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 300))
    conn = get_conn()
    try:
        if task_id:
            rows = conn.execute(
                """
                SELECT
                    id,
                    task_id,
                    jira_key,
                    COALESCE(task_source, 'jira') AS task_source,
                    version,
                    status,
                    workspace_path,
                    workflow,
                    COALESCE(attempt_count, 0) AS attempt_count,
                    COALESCE(max_retries, 0) AS max_retries,
                    COALESCE(attempts_failed, 0) AS attempts_failed,
                    COALESCE(attempts_completed, 0) AS attempts_completed,
                    COALESCE(current_activity, '') AS current_activity,
                    COALESCE(brief_path, '') AS brief_path,
                    COALESCE(spec_path, '') AS spec_path,
                    COALESCE(task_path, '') AS task_path,
                    COALESCE(codex_status, '') AS codex_status,
                    COALESCE(codex_summary, '') AS codex_summary,
                    COALESCE(failure_reason, '') AS failure_reason,
                    started_at,
                    COALESCE(ended_at, '') AS ended_at,
                    created_at,
                    updated_at
                FROM pipeline_runs
                WHERE task_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (task_id, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    task_id,
                    jira_key,
                    COALESCE(task_source, 'jira') AS task_source,
                    version,
                    status,
                    workspace_path,
                    workflow,
                    COALESCE(attempt_count, 0) AS attempt_count,
                    COALESCE(max_retries, 0) AS max_retries,
                    COALESCE(attempts_failed, 0) AS attempts_failed,
                    COALESCE(attempts_completed, 0) AS attempts_completed,
                    COALESCE(current_activity, '') AS current_activity,
                    COALESCE(brief_path, '') AS brief_path,
                    COALESCE(spec_path, '') AS spec_path,
                    COALESCE(task_path, '') AS task_path,
                    COALESCE(codex_status, '') AS codex_status,
                    COALESCE(codex_summary, '') AS codex_summary,
                    COALESCE(failure_reason, '') AS failure_reason,
                    started_at,
                    COALESCE(ended_at, '') AS ended_at,
                    created_at,
                    updated_at
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def finalize_pipeline_run(
    run_id: str,
    *,
    status: str,
    attempt_count: int | None = None,
    max_retries: int | None = None,
    attempts_failed: int | None = None,
    attempts_completed: int | None = None,
    current_activity: str | None = None,
    brief_path: str | None = None,
    spec_path: str | None = None,
    task_path: str | None = None,
    codex_status: str | None = None,
    codex_summary: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any] | None:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {
        PIPELINE_RUN_STATUS_RUNNING,
        PIPELINE_RUN_STATUS_COMPLETE,
        PIPELINE_RUN_STATUS_FAILED,
        PIPELINE_RUN_STATUS_STOPPED,
    }:
        raise ValueError("Invalid run status")

    existing = get_pipeline_run(run_id)
    if not existing:
        return None

    ended_at = _utc_now() if normalized_status in {PIPELINE_RUN_STATUS_COMPLETE, PIPELINE_RUN_STATUS_FAILED, PIPELINE_RUN_STATUS_STOPPED} else ""
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE pipeline_runs
            SET status = ?,
                attempt_count = ?,
                max_retries = ?,
                attempts_failed = ?,
                attempts_completed = ?,
                current_activity = ?,
                brief_path = ?,
                spec_path = ?,
                task_path = ?,
                codex_status = ?,
                codex_summary = ?,
                failure_reason = ?,
                ended_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalized_status,
                (
                    max(0, int(attempt_count))
                    if attempt_count is not None
                    else int(existing.get("attempt_count") or 0)
                ),
                (
                    max(0, int(max_retries))
                    if max_retries is not None
                    else int(existing.get("max_retries") or 0)
                ),
                (
                    max(0, int(attempts_failed))
                    if attempts_failed is not None
                    else int(existing.get("attempts_failed") or 0)
                ),
                (
                    max(0, int(attempts_completed))
                    if attempts_completed is not None
                    else int(existing.get("attempts_completed") or 0)
                ),
                (
                    str(current_activity).strip()[:500]
                    if current_activity is not None
                    else str(existing.get("current_activity") or "")
                ),
                brief_path if brief_path is not None else str(existing.get("brief_path") or ""),
                spec_path if spec_path is not None else str(existing.get("spec_path") or ""),
                task_path if task_path is not None else str(existing.get("task_path") or ""),
                codex_status if codex_status is not None else str(existing.get("codex_status") or ""),
                codex_summary if codex_summary is not None else str(existing.get("codex_summary") or ""),
                failure_reason if failure_reason is not None else str(existing.get("failure_reason") or ""),
                ended_at if ended_at else str(existing.get("ended_at") or ""),
                _utc_now(),
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_pipeline_run(run_id)


def update_pipeline_run_progress(
    run_id: str,
    *,
    attempt_count: int | None = None,
    max_retries: int | None = None,
    attempts_failed: int | None = None,
    attempts_completed: int | None = None,
    current_activity: str | None = None,
) -> dict[str, Any] | None:
    existing = get_pipeline_run(run_id)
    if not existing:
        return None

    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE pipeline_runs
            SET attempt_count = ?,
                max_retries = ?,
                attempts_failed = ?,
                attempts_completed = ?,
                current_activity = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                (
                    max(0, int(attempt_count))
                    if attempt_count is not None
                    else int(existing.get("attempt_count") or 0)
                ),
                (
                    max(0, int(max_retries))
                    if max_retries is not None
                    else int(existing.get("max_retries") or 0)
                ),
                (
                    max(0, int(attempts_failed))
                    if attempts_failed is not None
                    else int(existing.get("attempts_failed") or 0)
                ),
                (
                    max(0, int(attempts_completed))
                    if attempts_completed is not None
                    else int(existing.get("attempts_completed") or 0)
                ),
                (
                    str(current_activity).strip()[:500]
                    if current_activity is not None
                    else str(existing.get("current_activity") or "")
                ),
                _utc_now(),
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_pipeline_run(run_id)


def add_pipeline_log(
    *,
    level: str,
    message: str,
    task_id: str | None = None,
    run_id: str | None = None,
    jira_key: str | None = None,
) -> dict[str, Any]:
    conn = get_conn()
    try:
        log_id = str(uuid.uuid4())
        now = _utc_now()
        conn.execute(
            """
            INSERT INTO pipeline_logs (
                id,
                task_id,
                run_id,
                jira_key,
                level,
                message,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                task_id,
                run_id,
                jira_key,
                str(level or "info").strip().lower() or "info",
                str(message or "").strip()[:12000],
                now,
            ),
        )
        conn.commit()
        return {
            "id": log_id,
            "task_id": task_id or "",
            "run_id": run_id or "",
            "jira_key": jira_key or "",
            "level": str(level or "info").strip().lower() or "info",
            "message": str(message or "").strip()[:12000],
            "created_at": now,
        }
    finally:
        conn.close()


def list_pipeline_logs(*, task_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    conn = get_conn()
    try:
        if task_id:
            rows = conn.execute(
                """
                SELECT
                    id,
                    COALESCE(task_id, '') AS task_id,
                    COALESCE(run_id, '') AS run_id,
                    COALESCE(jira_key, '') AS jira_key,
                    level,
                    message,
                    created_at
                FROM pipeline_logs
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (task_id, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    COALESCE(task_id, '') AS task_id,
                    COALESCE(run_id, '') AS run_id,
                    COALESCE(jira_key, '') AS jira_key,
                    level,
                    message,
                    created_at
                FROM pipeline_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_pipeline_logs_since(*, after_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 500))
    conn = get_conn()
    try:
        if after_id:
            anchor = conn.execute(
                "SELECT created_at FROM pipeline_logs WHERE id = ?",
                (after_id,),
            ).fetchone()
            if anchor:
                rows = conn.execute(
                    """
                    SELECT
                        id,
                        COALESCE(task_id, '') AS task_id,
                        COALESCE(run_id, '') AS run_id,
                        COALESCE(jira_key, '') AS jira_key,
                        level,
                        message,
                        created_at
                    FROM pipeline_logs
                    WHERE created_at > ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (anchor["created_at"], safe_limit),
                ).fetchall()
                return [dict(row) for row in rows]
        rows = conn.execute(
            """
            SELECT
                id,
                COALESCE(task_id, '') AS task_id,
                COALESCE(run_id, '') AS run_id,
                COALESCE(jira_key, '') AS jira_key,
                level,
                message,
                created_at
            FROM pipeline_logs
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def recover_stale_pipeline_state() -> int:
    conn = get_conn()
    try:
        stale_reason = "Pipeline execution was interrupted by an application restart."
        now = _utc_now()
        task_rows = conn.execute(
            "SELECT id, jira_key, active_run_id FROM pipeline_tasks WHERE status = ?",
            (PIPELINE_STATUS_RUNNING,),
        ).fetchall()
        run_rows = conn.execute(
            "SELECT id FROM pipeline_runs WHERE status = ?",
            (PIPELINE_RUN_STATUS_RUNNING,),
        ).fetchall()

        for row in task_rows:
            next_order = _next_current_order_index(conn)
            conn.execute(
                """
                UPDATE pipeline_tasks
                SET status = ?,
                    order_index = ?,
                    failure_reason = NULL,
                    is_bypassed = 0,
                    bypass_reason = NULL,
                    bypass_source = NULL,
                    bypassed_at = NULL,
                    bypassed_by = NULL,
                    execution_state = ?,
                    last_failure_code = ?,
                    active_run_id = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    PIPELINE_STATUS_CURRENT,
                    next_order,
                    PIPELINE_TASK_EXECUTION_STATE_READY,
                    "restart_interrupted",
                    now,
                    str(row["id"]),
                ),
            )
            conn.execute(
                """
                INSERT INTO pipeline_logs (id, task_id, run_id, jira_key, level, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    str(row["id"]),
                    str(row["active_run_id"] or "") or None,
                    str(row["jira_key"] or ""),
                    "warn",
                    stale_reason,
                    now,
                ),
            )

        for row in run_rows:
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    failure_reason = ?,
                    ended_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    PIPELINE_RUN_STATUS_FAILED,
                    stale_reason,
                    now,
                    now,
                    str(row["id"]),
                ),
            )

        recovered = len(task_rows)
        conn.commit()
        return recovered
    finally:
        conn.close()


def recover_stale_running_task(stale_threshold_seconds: int) -> int:
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)).isoformat()
    stale_reason = "Pipeline task exceeded the maximum running time and was automatically recovered."
    now = _utc_now()

    conn = get_conn()
    try:
        task_rows = conn.execute(
            """
            SELECT id, jira_key, active_run_id
            FROM pipeline_tasks
            WHERE status = ?
              AND updated_at < ?
            """,
            (PIPELINE_STATUS_RUNNING, stale_cutoff),
        ).fetchall()

        for row in task_rows:
            next_order = _next_current_order_index(conn)
            conn.execute(
                """
                UPDATE pipeline_tasks
                SET status = ?,
                    order_index = ?,
                    failure_reason = NULL,
                    is_bypassed = 0,
                    bypass_reason = NULL,
                    bypass_source = NULL,
                    bypassed_at = NULL,
                    bypassed_by = NULL,
                    execution_state = ?,
                    last_failure_code = ?,
                    active_run_id = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    PIPELINE_STATUS_CURRENT,
                    next_order,
                    PIPELINE_TASK_EXECUTION_STATE_READY,
                    "stale_running_recovered",
                    now,
                    str(row["id"]),
                ),
            )
            conn.execute(
                """
                UPDATE pipeline_runs
                SET status = ?,
                    failure_reason = ?,
                    ended_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    PIPELINE_RUN_STATUS_FAILED,
                    stale_reason,
                    now,
                    now,
                    str(row["active_run_id"] or ""),
                ),
            )
            conn.execute(
                """
                INSERT INTO pipeline_logs (id, task_id, run_id, jira_key, level, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    str(row["id"]),
                    str(row["active_run_id"] or "") or None,
                    str(row["jira_key"] or ""),
                    "warn",
                    stale_reason,
                    now,
                ),
            )

        recovered = len(task_rows)
        conn.commit()
        return recovered
    finally:
        conn.close()
