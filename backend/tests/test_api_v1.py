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


# ---- regenerate -------------------------------------------------------------


def _seed_lead(user_id: int, *, subject: str = "OLD subj", body: str = "OLD body") -> int:
    lead = {
        "input": {
            "name": "Sarah Chen", "email": "schen@greystar.com", "company": "Greystar",
            "property_address": "1 Main", "city": "NYC", "state": "NY", "country": "USA",
        },
        "tier": "A", "score": 88.0,
        "draft_email_subject": subject,
        "draft_email_body": body,
    }
    return cache.save_lead(user_id, "h", json.dumps(lead), "A", 88.0)


def _mock_draft(monkeypatch, calls: list[dict]):
    async def fake(client, lead, batch_mode=True, tone=None, skip_cache=False):
        calls.append({"tone": tone, "skip_cache": skip_cache, "batch_mode": batch_mode})
        lead.draft_email_subject = f"NEW subj ({tone or 'default'})"
        lead.draft_email_body = f"NEW body for {lead.input.company}"

    monkeypatch.setattr("backend.lead_brief.draft_email", fake)


def test_regenerate_requires_token(client):
    r = client.post("/api/v1/leads/1/regenerate", json={})
    assert r.status_code == 401


def test_regenerate_404_for_other_users_lead(client, monkeypatch):
    other = cache.upsert_user("rival@example.com")
    lid = _seed_lead(other)
    calls: list[dict] = []
    _mock_draft(monkeypatch, calls)

    r = client.post(f"/api/v1/leads/{lid}/regenerate", json={}, headers=_bearer())
    assert r.status_code == 404
    assert calls == []  # never reached the draft step


def test_regenerate_default_tone(client, monkeypatch):
    me = cache.upsert_user("sdr@example.com")
    lid = _seed_lead(me)
    calls: list[dict] = []
    _mock_draft(monkeypatch, calls)

    r = client.post(f"/api/v1/leads/{lid}/regenerate", json={}, headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft_email_subject"] == "NEW subj (default)"
    assert body["draft_email_body"] == "NEW body for Greystar"
    # tier/score preserved
    assert body["tier"] == "A"
    assert body["score"] == 88.0
    # draft_email called once with tone=None and skip_cache=True
    assert calls == [{"tone": None, "skip_cache": True, "batch_mode": False}]

    # Persisted: GET should now return the new draft.
    r2 = client.get(f"/api/v1/leads/{lid}", headers=_bearer())
    assert r2.json()["draft_email_subject"] == "NEW subj (default)"


def test_regenerate_with_tone(client, monkeypatch):
    me = cache.upsert_user("sdr@example.com")
    lid = _seed_lead(me)
    calls: list[dict] = []
    _mock_draft(monkeypatch, calls)

    r = client.post(
        f"/api/v1/leads/{lid}/regenerate",
        json={"tone": "casual"},
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["draft_email_subject"] == "NEW subj (casual)"
    assert calls[0]["tone"] == "casual"


def test_regenerate_rejects_invalid_tone(client, monkeypatch):
    me = cache.upsert_user("sdr@example.com")
    lid = _seed_lead(me)
    _mock_draft(monkeypatch, [])

    r = client.post(
        f"/api/v1/leads/{lid}/regenerate",
        json={"tone": "snarky"},
        headers=_bearer(),
    )
    assert r.status_code == 422


def test_regenerate_falls_back_to_template_on_quota_exhausted(client, monkeypatch):
    from backend.quota import QuotaExhausted

    me = cache.upsert_user("sdr@example.com")
    seed_body = (
        "Hi Sarah,\n\nFoo.\n\n"
        "Worth a 15-min intro next week? Happy to send times."
    )
    lid = _seed_lead(me, subject="OLD subj", body=seed_body)

    async def boom(client, lead, batch_mode=True, tone=None, skip_cache=False):
        raise QuotaExhausted("gemini", used=250, ceiling=250, reason="daily_cap_reached")

    monkeypatch.setattr("backend.lead_brief.draft_email", boom)

    r = client.post(
        f"/api/v1/leads/{lid}/regenerate",
        json={"tone": "casual"},
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Tone-Source") == "template"
    body = r.json()["draft_email_body"]
    # Casual rules: "Hi " -> "Hey " and the closer is rewritten.
    assert "Hey Sarah," in body
    assert "Open to a quick 15-min chat" in body
    # Subject is left alone; existing subject persists.
    assert r.json()["draft_email_subject"] == "OLD subj"


def test_regenerate_marks_gemini_source_on_success(client, monkeypatch):
    me = cache.upsert_user("sdr@example.com")
    lid = _seed_lead(me)
    _mock_draft(monkeypatch, [])

    r = client.post(f"/api/v1/leads/{lid}/regenerate", json={}, headers=_bearer())
    assert r.status_code == 200
    assert r.headers.get("X-Tone-Source") == "gemini"
