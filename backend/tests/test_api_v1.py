"""Auth gating + history routes for the user-facing /api/v1/* router.

The /enrich endpoints are not exercised here -- they would call external
APIs. Auth + persistence + history are sufficient to prove the wiring;
the orchestrator itself is covered by the existing test files.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from backend import cache


SECRET = "x" * 64


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("backend.cache.settings.cache_db_path", tmp.name)
    monkeypatch.setattr("backend.config.settings.nextauth_secret", SECRET)
    monkeypatch.setattr("backend.config.settings.allowed_emails", "sdr@example.com")
    cache.init_db()
    from backend.app import app
    yield TestClient(app)
    os.unlink(tmp.name)


def _bearer(email: str = "sdr@example.com") -> dict:
    tok = jwt.encode(
        {"email": email, "exp": int(time.time()) + 3600},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {tok}"}


def test_me_requires_token(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401


def test_me_returns_user_with_valid_token(client):
    r = client.get("/api/v1/me", headers=_bearer())
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "sdr@example.com"
    assert body["id"] > 0


def test_leads_list_requires_token(client):
    r = client.get("/api/v1/leads")
    assert r.status_code == 401


def test_leads_list_empty_for_new_user(client):
    r = client.get("/api/v1/leads", headers=_bearer())
    assert r.status_code == 200
    assert r.json() == {"leads": [], "total": 0, "limit": 50, "offset": 0}


def test_leads_list_is_user_scoped(client):
    # Seed two users' leads directly.
    me = cache.upsert_user("sdr@example.com")
    other = cache.upsert_user("rival@example.com")
    payload = json.dumps({"input": {"name": "Test", "email": "t@x.com", "company": "Acme",
                                      "property_address": "1 Main", "city": "NYC", "state": "NY",
                                      "country": "USA"}})
    cache.save_lead(me, "h1", payload, "A", 90.0)
    cache.save_lead(other, "h2", payload, "A", 90.0)

    r = client.get("/api/v1/leads", headers=_bearer())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # only sees own
    assert body["leads"][0]["tier"] == "A"


def test_get_lead_404_for_other_users_lead(client):
    other = cache.upsert_user("rival@example.com")
    payload = json.dumps({
        "input": {"name": "X", "email": "x@x.com", "company": "C",
                   "property_address": "1", "city": "NYC", "state": "NY", "country": "USA"},
        "tier": "A", "score": 90.0,
    })
    lid = cache.save_lead(other, "h", payload, "A", 90.0)

    r = client.get(f"/api/v1/leads/{lid}", headers=_bearer())
    assert r.status_code == 404


def test_disallowed_email_blocked(client):
    bad = jwt.encode({"email": "denied@x.com", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 403
