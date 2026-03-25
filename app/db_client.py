from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
except ModuleNotFoundError:
    psycopg2 = None

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()
_sqlite_default_path = Path(__file__).resolve().parent.parent / 'assistant.db'
_MAX_QUERY_ATTEMPTS = 2

_PRAGMA_TABLE_INFO_PATTERN = re.compile(r"^\s*PRAGMA\s+table_info\((?P<table>[^)]+)\)\s*$", re.IGNORECASE)


class _InMemoryCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def fetchone(self) -> dict[str, Any] | None:
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class PooledConnection:
    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn
        self._total_changes = 0

    @property
    def total_changes(self) -> int:
        return self._total_changes

    def _translate_query(self, query: str) -> str:
        translated: list[str] = []
        in_single_quote = False
        in_double_quote = False

        for char in query:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                translated.append(char)
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                translated.append(char)
                continue

            if char == '?' and not in_single_quote and not in_double_quote:
                translated.append('%s')
                continue

            translated.append(char)

        return ''.join(translated)

    def _handle_pragma_table_info(self, query: str) -> _InMemoryCursor | None:
        match = _PRAGMA_TABLE_INFO_PATTERN.match(query)
        if not match:
            return None

        table_name = match.group('table').strip().strip('"').strip("'")
        sql = (
            'SELECT column_name AS name '
            'FROM information_schema.columns '
            'WHERE table_schema = current_schema() AND table_name = %s '
            'ORDER BY ordinal_position'
        )
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (table_name,))
            rows = [dict(row) for row in cur.fetchall()]
        return _InMemoryCursor(rows)

    def _reconnect(self) -> None:
        _require_psycopg2()

        old_conn = self._conn
        try:
            _get_pool().putconn(old_conn, close=True)
        except Exception:
            try:
                old_conn.close()
            except Exception:
                pass

        reset_pool()
        self._conn = _get_pool().getconn()

    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any:
        pragma_result = self._handle_pragma_table_info(query)
        if pragma_result is not None:
            return pragma_result

        translated_query = self._translate_query(query)
        for attempt in range(_MAX_QUERY_ATTEMPTS):
            try:
                cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                if params is None:
                    cur.execute(translated_query)
                else:
                    cur.execute(translated_query, tuple(params))

                self._total_changes += max(int(cur.rowcount or 0), 0)
                return cur
            except Exception as exc:
                if attempt < (_MAX_QUERY_ATTEMPTS - 1) and _is_retryable_connection_error(exc):
                    self._reconnect()
                    continue
                raise

    def executescript(self, script: str) -> None:
        statements = [statement.strip() for statement in script.split(';') if statement.strip()]
        for statement in statements:
            cursor = self.execute(statement)
            close = getattr(cursor, 'close', None)
            if callable(close):
                close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        release_conn(self)


def _require_psycopg2() -> None:
    if psycopg2 is not None:
        return
    raise RuntimeError(
        'psycopg2 is required for DB_BACKEND=postgres. '
        'Install dependencies with: pip install -r requirements.txt'
    )


def _get_database_backend() -> str:
    raw = str(os.environ.get('DB_BACKEND', 'postgres') or '').strip().lower()
    if raw in {'postgres', 'postgresql', 'supabase'}:
        return 'postgres'
    if raw in {'sqlite', 'sqlite3'}:
        return 'sqlite'
    raise RuntimeError("DB_BACKEND must be one of: 'postgres', 'sqlite'")


def _get_sqlite_path() -> Path:
    raw_path = str(os.environ.get('SQLITE_PATH', '') or '').strip()
    if not raw_path:
        return _sqlite_default_path
    return Path(raw_path).expanduser().resolve()


def _get_database_url() -> str:
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        raise RuntimeError(
            'DATABASE_URL is not set. '
            'Get it from Supabase -> Settings -> Database -> Connection string -> URI '
            'and append ?sslmode=require'
        )
    parsed = urlparse(url)
    if parsed.port == 6543:
        raise RuntimeError(
            'DATABASE_URL points at Supabase pooler port 6543. '
            'Use the direct Postgres connection on port 5432.'
        )

    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    host = parsed.hostname or ''
    is_local = host in ('localhost', '127.0.0.1', '') or host.startswith('/')
    if not is_local:
        query_pairs.setdefault('sslmode', 'require')
    updated_query = urlencode(query_pairs)
    return urlunparse(parsed._replace(query=updated_query))



def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    _require_psycopg2()
    global _pool

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, dsn=_get_database_url())

    return _pool


def _is_retryable_connection_error(exc: Exception) -> bool:
    if _get_database_backend() == 'sqlite' or psycopg2 is None:
        return False

    if not isinstance(exc, (psycopg2.InterfaceError, psycopg2.OperationalError, psycopg2.DatabaseError)):
        return False

    message = str(exc).strip().lower()
    retryable_substrings = (
        'cursor already closed',
        'server closed the connection unexpectedly',
        'connection already closed',
        'terminating connection',
        'could not receive data from server',
        'connection not open',
        'ssl connection has been closed unexpectedly',
    )
    return any(fragment in message for fragment in retryable_substrings)


def _is_conn_pre_ping_enabled() -> bool:
    raw = str(os.environ.get('DB_CONN_PRE_PING', 'true') or '').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def _is_postgres_connection_healthy(conn: psycopg2.extensions.connection) -> bool:
    if not _is_conn_pre_ping_enabled():
        return True
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
            cur.fetchone()
        return True
    except Exception:
        return False



def validate_database_config() -> None:
    backend = _get_database_backend()
    if backend == 'sqlite':
        sqlite_path = _get_sqlite_path()
        parent = sqlite_path.parent
        if not parent.exists():
            raise RuntimeError(f'SQLITE_PATH parent directory does not exist: {parent}')
        return
    _get_database_url()



def init_pool() -> None:
    if _get_database_backend() == 'sqlite':
        return
    _get_pool()


def reset_pool() -> None:
    global _pool

    if _get_database_backend() == 'sqlite':
        return

    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
        _pool = None



def get_conn() -> PooledConnection | sqlite3.Connection:
    if _get_database_backend() == 'sqlite':
        conn = sqlite3.connect(_get_sqlite_path())
        conn.row_factory = sqlite3.Row
        return conn

    _require_psycopg2()

    for attempt in range(3):
        try:
            pool = _get_pool()
            raw_conn = pool.getconn()

            if getattr(raw_conn, "closed", 0):
                pool.putconn(raw_conn, close=True)
                if attempt < 2:
                    continue
                raise RuntimeError('Failed to obtain an open database connection')

            if not _is_postgres_connection_healthy(raw_conn):
                pool.putconn(raw_conn, close=True)
                if attempt < 2:
                    reset_pool()
                    continue
                raise RuntimeError('Failed to obtain a healthy database connection')

            return PooledConnection(raw_conn)
        except psycopg2.pool.PoolError:
            if attempt < 2:
                reset_pool()
            else:
                raise

    raise RuntimeError("Failed to obtain a database connection")



def release_conn(
    conn: PooledConnection | psycopg2.extensions.connection | sqlite3.Connection | None,
) -> None:
    if conn is None:
        return

    if _get_database_backend() == 'sqlite':
        conn.close()
        return

    raw = conn._conn if isinstance(conn, PooledConnection) else conn

    try:
        pool = _get_pool()

        if getattr(raw, "closed", 0):
            pool.putconn(raw, close=True)
            return

        try:
            pool.putconn(raw)
        except (psycopg2.OperationalError, psycopg2.DatabaseError, psycopg2.InterfaceError):
            pool.putconn(raw, close=True)
    except psycopg2.pool.PoolError:
        try:
            raw.close()
        except Exception:
            pass
