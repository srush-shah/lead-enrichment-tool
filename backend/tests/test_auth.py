from __future__ import annotations

import os
import tempfile
import time

import jwt
import pytest
from fastapi import HTTPException

from backend import auth, cache


SECRET = "a" * 64  # >= 32 bytes per RFC 7518 §3.2


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("backend.cache.settings.cache_db_path", tmp.name)
    monkeypatch.setattr("backend.config.settings.nextauth_secret", SECRET)
    monkeypatch.setattr("backend.config.settings.allowed_emails", "allowed@example.com,vip@example.com")
    cache.init_db()
    yield
    os.unlink(tmp.name)


def _token(email: str, exp_offset: int = 3600, secret: str = SECRET) -> str:
    return jwt.encode(
        {"email": email, "exp": int(time.time()) + exp_offset},
        secret,
        algorithm="HS256",
    )


def test_valid_token_returns_user_and_upserts():
    u = auth.current_user(authorization=f"Bearer {_token('allowed@example.com')}")
    assert u.email == "allowed@example.com"
    assert u.id > 0
    # Idempotent upsert -- same id on second call.
    u2 = auth.current_user(authorization=f"Bearer {_token('allowed@example.com')}")
    assert u2.id == u.id


def test_missing_bearer_header_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.current_user(authorization="")
    assert exc.value.status_code == 401


def test_malformed_authorization_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.current_user(authorization="Token abc")
    assert exc.value.status_code == 401


def test_expired_token_rejected():
    tok = _token("allowed@example.com", exp_offset=-10)
    with pytest.raises(HTTPException) as exc:
        auth.current_user(authorization=f"Bearer {tok}")
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


def test_bad_signature_rejected():
    tok = _token("allowed@example.com", secret="b" * 64)
    with pytest.raises(HTTPException) as exc:
        auth.current_user(authorization=f"Bearer {tok}")
    assert exc.value.status_code == 401


def test_disallowed_email_rejected():
    tok = _token("denied@example.com")
    with pytest.raises(HTTPException) as exc:
        auth.current_user(authorization=f"Bearer {tok}")
    assert exc.value.status_code == 403


def test_empty_allowlist_is_open(monkeypatch):
    monkeypatch.setattr("backend.config.settings.allowed_emails", "")
    u = auth.current_user(authorization=f"Bearer {_token('anyone@example.com')}")
    assert u.email == "anyone@example.com"
