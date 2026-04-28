"""User + lead persistence with a swappable backend.

Mirrors `backend.quota_store`: when `DATABASE_URL` is set we route the
five user/lead functions through Postgres so they survive Render's
ephemeral free-dyno disk; otherwise we fall back to the SQLite-backed
implementations in `backend.cache`.

Only the user/lead persistence lives here — the api_cache table stays
SQLite-only because its TTL semantics make loss-on-redeploy harmless.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from . import cache
from .config import settings


_pg_schema_ready = False
_pg_lock = threading.Lock()


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leads (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    lead_hash   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    tier        TEXT NOT NULL,
    score       REAL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_user_created ON leads(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_user_hash ON leads(user_id, lead_hash);
"""


def _use_pg() -> bool:
    return bool(settings.database_url)


@contextmanager
def _pg_conn() -> Iterator["object"]:
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


def upsert_user(email: str) -> int:
    if not _use_pg():
        return cache.upsert_user(email)
    email = email.strip().lower()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            # ON CONFLICT DO NOTHING + a follow-up SELECT keeps the id stable
            # across concurrent inserts (DO UPDATE bumps the sequence).
            cur.execute(
                "INSERT INTO users(email) VALUES (%s) ON CONFLICT (email) DO NOTHING",
                (email,),
            )
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
    return row[0]


def save_lead(
    user_id: int,
    lead_hash: str,
    payload_json: str,
    tier: str,
    score: Optional[float],
) -> int:
    if not _use_pg():
        return cache.save_lead(user_id, lead_hash, payload_json, tier, score)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO leads(user_id, lead_hash, payload, tier, score)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (user_id, lead_hash, payload_json, tier, score),
            )
            row = cur.fetchone()
    return row[0]


def list_leads(user_id: int, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    if not _use_pg():
        return cache.list_leads(user_id, limit=limit, offset=offset)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, lead_hash, tier, score, created_at, payload
                   FROM leads WHERE user_id=%s
                   ORDER BY created_at DESC, id DESC
                   LIMIT %s OFFSET %s""",
                (user_id, limit, offset),
            )
            rows = [
                {
                    "id": r[0], "lead_hash": r[1], "tier": r[2],
                    "score": r[3], "created_at": r[4].isoformat() if r[4] else None,
                    "payload": r[5],
                }
                for r in cur.fetchall()
            ]
            cur.execute("SELECT COUNT(*) FROM leads WHERE user_id=%s", (user_id,))
            total = cur.fetchone()[0]
    return rows, total


def get_lead(user_id: int, lead_id: int) -> Optional[dict]:
    if not _use_pg():
        return cache.get_lead(user_id, lead_id)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, lead_hash, tier, score, created_at, payload
                   FROM leads WHERE id=%s AND user_id=%s""",
                (lead_id, user_id),
            )
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "lead_hash": r[1], "tier": r[2],
        "score": r[3], "created_at": r[4].isoformat() if r[4] else None,
        "payload": r[5],
    }


def update_lead(
    lead_id: int, user_id: int, payload_json: str, tier: str, score: Optional[float]
) -> bool:
    if not _use_pg():
        return cache.update_lead(lead_id, user_id, payload_json, tier, score)
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE leads SET payload=%s, tier=%s, score=%s
                   WHERE id=%s AND user_id=%s""",
                (payload_json, tier, score, lead_id, user_id),
            )
            return cur.rowcount > 0
