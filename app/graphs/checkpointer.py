"""Shared AsyncPostgresSaver singleton for all LangGraph graphs."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


def _get_checkpointer_url() -> str:
    url = os.environ['DATABASE_URL']
    parsed = urlparse(url)
    host = parsed.hostname or ''
    is_local = host in ('localhost', '127.0.0.1', '') or host.startswith('/')
    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if not is_local:
        query_pairs.setdefault('sslmode', 'require')

    return urlunparse(parsed._replace(query=urlencode(query_pairs)))


async def get_checkpointer() -> AsyncPostgresSaver:
    global _pool, _checkpointer

    if _checkpointer is None:
        _pool = AsyncConnectionPool(
            conninfo=_get_checkpointer_url(),
            open=False,
            min_size=2,
            max_size=10,
            kwargs={
                'autocommit': True,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            },
        )
        await _pool.open()

        _checkpointer = AsyncPostgresSaver(_pool)
        await _checkpointer.setup()

    return _checkpointer


async def close_checkpointer() -> None:
    global _pool, _checkpointer

    _checkpointer = None

    if _pool is not None:
        await _pool.close()
        _pool = None
