"""Daily-usage counter persistence with a swappable backend.

Render's free dyno has an ephemeral filesystem, so the SQLite-backed
`daily_usage` table loses its rows on every cold start and `/health`
reports zeroed counters even when external API quotas are partially
spent. When `DATABASE_URL` is set we route the three counter functions
through Postgres instead; otherwise we fall back to the existing
SQLite implementation in `backend.cache`.

Only the three counter functions live here — the rest of the cache
(api_cache, users, leads) stays SQLite-backed.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from . import cache
from .config import settings


_pg_schema_ready = False
_pg_lock = threading.Lock()


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_usage (
    api_name    TEXT NOT NULL,
    usage_date  DATE NOT NULL,
    call_count  INTEGER NOT NULL DEFAULT 0,
    last_called TIMESTAMPTZ,
    PRIMARY KEY (api_name, usage_date)
);
"""


def _use_pg() -> bool:
    return bool(settings.database_url)


@contextmanager
def _pg_conn() -> Iterator["object"]:
    # Imported lazily so test envs without psycopg installed still work.
    import psycopg

    global _pg_schema_ready
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        if not _pg_schema_ready:
            with _pg_lock:
                if not _pg_schema_ready:
                    with conn.cursor() as cur:
                        cur.execute(_PG_SCHEMA)
                    _pg_schema_ready = True
        yield conn
    finally:
        conn.close()


def usage_today(api_name: str) -> int:
    if not _use_pg():
        return cache.usage_today(api_name)
    today = cache.reset_date(api_name)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT call_count FROM daily_usage WHERE api_name=%s AND usage_date=%s",
                (api_name, today),
            )
            row = cur.fetchone()
    return row[0] if row else 0


def increment_usage(api_name: str) -> int:
    if not _use_pg():
        return cache.increment_usage(api_name)
    today = cache.reset_date(api_name)
    now = datetime.now(timezone.utc)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO daily_usage(api_name, usage_date, call_count, last_called)
                   VALUES (%s, %s, 1, %s)
                   ON CONFLICT (api_name, usage_date)
                   DO UPDATE SET call_count = daily_usage.call_count + 1,
                                 last_called = EXCLUDED.last_called
                   RETURNING call_count""",
                (api_name, today, now),
            )
            row = cur.fetchone()
    return row[0]


def decrement_usage(api_name: str) -> None:
    if not _use_pg():
        cache.decrement_usage(api_name)
        return
    today = cache.reset_date(api_name)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE daily_usage
                   SET call_count = GREATEST(0, call_count - 1)
                   WHERE api_name=%s AND usage_date=%s""",
                (api_name, today),
            )


def clear_today(api_name: str) -> None:
    """Delete today's counter row for `api_name` so usage resets to 0.

    Used by the admin `reset` command when external quota has refreshed
    but our local row is still pinned (e.g., the 429 self-heal pinned
    the counter and we want immediate relief without waiting for the
    next reset window).
    """
    today = cache.reset_date(api_name)
    if not _use_pg():
        with cache._conn() as c:  # noqa: SLF001 — internal helper, same package.
            c.execute(
                "DELETE FROM daily_usage WHERE api_name=? AND usage_date=?",
                (api_name, today.isoformat()),
            )
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM daily_usage WHERE api_name=%s AND usage_date=%s",
                (api_name, today),
            )


def set_usage(api_name: str, count: int) -> None:
    """Pin today's counter to a specific value.

    Used by the upstream-429 self-heal path (when Gemini/NewsAPI report
    quota exhaustion, we sync the local counter to its cap so subsequent
    calls gate locally without burning more probe requests) and by the
    admin CLI's `mark-exhausted` command.
    """
    now = datetime.now(timezone.utc)
    today = cache.reset_date(api_name)
    if not _use_pg():
        with cache._conn() as c:  # noqa: SLF001 — internal helper, same package.
            c.execute(
                """INSERT INTO daily_usage(api_name, usage_date, call_count, last_called)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(api_name, usage_date)
                   DO UPDATE SET call_count = excluded.call_count,
                                 last_called = excluded.last_called""",
                (api_name, today.isoformat(), count, now.isoformat()),
            )
        return
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO daily_usage(api_name, usage_date, call_count, last_called)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (api_name, usage_date)
                   DO UPDATE SET call_count = EXCLUDED.call_count,
                                 last_called = EXCLUDED.last_called""",
                (api_name, today, count, now),
            )
