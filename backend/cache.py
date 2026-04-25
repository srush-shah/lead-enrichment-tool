from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from .config import settings


_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    namespace TEXT NOT NULL,
    key       TEXT NOT NULL,
    payload   TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    PRIMARY KEY (namespace, key)
);

CREATE TABLE IF NOT EXISTS daily_usage (
    api_name    TEXT NOT NULL,
    usage_date  DATE NOT NULL,
    call_count  INTEGER NOT NULL DEFAULT 0,
    last_called TIMESTAMP,
    PRIMARY KEY (api_name, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_usage_date ON daily_usage(usage_date);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = sqlite3.connect(settings.cache_db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL;")
        try:
            yield c
        finally:
            c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def cache_get(namespace: str, key: str) -> Optional[Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT payload, expires_at FROM api_cache WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return json.loads(row["payload"])


def cache_set(namespace: str, key: str, payload: Any, ttl_hours: int) -> None:
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO api_cache(namespace,key,payload,expires_at) VALUES(?,?,?,?)",
            (namespace, key, json.dumps(payload, default=str), expires.isoformat()),
        )


def usage_today(api_name: str) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT call_count FROM daily_usage WHERE api_name=? AND usage_date=?",
            (api_name, _today().isoformat()),
        ).fetchone()
    return row["call_count"] if row else 0


def increment_usage(api_name: str) -> int:
    today = _today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO daily_usage(api_name, usage_date, call_count, last_called)
               VALUES(?, ?, 1, ?)
               ON CONFLICT(api_name, usage_date)
               DO UPDATE SET call_count = call_count + 1, last_called = excluded.last_called""",
            (api_name, today, now),
        )
        row = c.execute(
            "SELECT call_count FROM daily_usage WHERE api_name=? AND usage_date=?",
            (api_name, today),
        ).fetchone()
    return row["call_count"]


def decrement_usage(api_name: str) -> None:
    today = _today().isoformat()
    with _conn() as c:
        c.execute(
            """UPDATE daily_usage SET call_count = MAX(0, call_count - 1)
               WHERE api_name=? AND usage_date=?""",
            (api_name, today),
        )


def prune_old() -> None:
    cutoff = (_today() - timedelta(days=7)).isoformat()
    with _conn() as c:
        c.execute("DELETE FROM daily_usage WHERE usage_date < ?", (cutoff,))
        c.execute("DELETE FROM api_cache WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))
