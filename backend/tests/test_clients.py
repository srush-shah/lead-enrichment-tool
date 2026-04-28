"""Upstream-429 self-heal behavior for the Gemini and NewsAPI clients.

Goal: when the external API returns 429, the local daily counter gets
pinned to the cap so subsequent calls gate locally without burning more
probe requests.
"""
from __future__ import annotations

import os
import tempfile

import httpx
import pytest

from backend import cache, quota_store
from backend.clients import gemini, newsapi


@pytest.fixture
def clean_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("backend.cache.settings.cache_db_path", tmp.name)
    cache.init_db()
    # Force the SQLite branch in quota_store regardless of dev env.
    monkeypatch.setattr("backend.config.settings.database_url", "")
    yield
    os.unlink(tmp.name)


# ---- quota_store.set_usage --------------------------------------------------


def test_set_usage_creates_row(clean_db):
    quota_store.set_usage("gemini", 250)
    assert quota_store.usage_today("gemini") == 250


def test_set_usage_overwrites_existing_row(clean_db):
    quota_store.increment_usage("gemini")
    assert quota_store.usage_today("gemini") == 1
    quota_store.set_usage("gemini", 250)
    assert quota_store.usage_today("gemini") == 250


# ---- gemini 429 self-heal ---------------------------------------------------


@pytest.fixture
def fast_gemini(monkeypatch):
    """Skip the 6.5s RPM gate so tests don't sleep."""
    async def _noop():
        return None
    monkeypatch.setattr(gemini, "_respect_rpm", _noop)


@pytest.mark.asyncio
async def test_gemini_429_pins_counter_to_cap(clean_db, fast_gemini, monkeypatch):
    monkeypatch.setattr("backend.config.settings.gemini_api_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await gemini.generate(
            client, "test prompt", batch_mode=False, skip_cache=True,
        )

    assert result is None
    # Local counter pinned at the hard cap so further calls gate locally.
    assert quota_store.usage_today("gemini") == gemini.SPEC.hard_cap


@pytest.mark.asyncio
async def test_gemini_500_releases_reservation(clean_db, fast_gemini, monkeypatch):
    monkeypatch.setattr("backend.config.settings.gemini_api_key", "test-key")
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "server"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await gemini.generate(
            client, "test prompt", batch_mode=False, skip_cache=True,
        )

    assert result is None
    # 5xx: the reservation is released, counter is back to 0.
    assert quota_store.usage_today("gemini") == 0
    # Tenacity retried once on 5xx (2 attempts total).
    assert len(calls) == 2


# ---- newsapi 429 self-heal --------------------------------------------------


@pytest.mark.asyncio
async def test_newsapi_429_pins_counter_to_cap(clean_db, monkeypatch):
    monkeypatch.setattr("backend.config.settings.newsapi_key", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"status": "error", "code": "rateLimited"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await newsapi.fetch_news(client, "Greystar", batch_mode=False)

    assert result.skipped_reason == "daily_cap_reached"
    assert quota_store.usage_today("newsapi") == newsapi.SPEC.hard_cap


# ---- sheets_push HMAC + body shape -----------------------------------------


def _patch_async_client(monkeypatch, module, transport):
    """Replace ``module.httpx.AsyncClient`` with a wrapper that routes
    through ``transport``. Captures the real class first to avoid the
    obvious infinite-recursion footgun (the wrapper's __init__ would
    otherwise call the patched name)."""
    real_cls = httpx.AsyncClient

    class _Ctx:
        def __init__(self, *a, **kw):
            self._client = real_cls(transport=transport)
        async def __aenter__(self):
            return self._client
        async def __aexit__(self, *a):
            await self._client.aclose()

    monkeypatch.setattr(module.httpx, "AsyncClient", _Ctx)


@pytest.mark.asyncio
async def test_sheets_push_signs_body_and_posts_payload(monkeypatch):
    """The Apps Script doPost can't read headers, so the HMAC must arrive
    via ?sig=<hex> and match what the Apps Script side computes."""
    import hashlib
    import hmac
    import json

    from backend.clients import sheets_push

    monkeypatch.setattr(
        "backend.clients.sheets_push.settings.apps_script_push_url",
        "https://script.google.com/macros/s/abc/exec",
    )
    monkeypatch.setattr(
        "backend.clients.sheets_push.settings.webhook_shared_secret",
        "shared",
    )

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["sig"] = request.url.params.get("sig")
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={"written": 2, "sheet": "Web App Output"})

    transport = httpx.MockTransport(handler)
    _patch_async_client(monkeypatch, sheets_push, transport)

    result = await sheets_push.push_rows(
        header=["a", "b"],
        rows=[[1, 2], [3, 4]],
        sheet_name="Web App Output",
    )

    assert result == {"written": 2, "sheet": "Web App Output"}
    assert captured["content_type"] == "application/json"
    # Body matches the canonical JSON we'd sign.
    payload = json.loads(captured["body"])
    assert payload == {
        "sheet_name": "Web App Output",
        "header": ["a", "b"],
        "rows": [[1, 2], [3, 4]],
    }
    expected_sig = hmac.new(b"shared", captured["body"], hashlib.sha256).hexdigest()
    assert captured["sig"] == expected_sig


@pytest.mark.asyncio
async def test_sheets_push_raises_when_url_missing(monkeypatch):
    from backend.clients import sheets_push

    monkeypatch.setattr(
        "backend.clients.sheets_push.settings.apps_script_push_url", ""
    )
    with pytest.raises(sheets_push.SheetsPushError, match="APPS_SCRIPT_PUSH_URL"):
        await sheets_push.push_rows(header=["a"], rows=[[1]])


@pytest.mark.asyncio
async def test_sheets_push_raises_on_apps_script_error_payload(monkeypatch):
    from backend.clients import sheets_push

    monkeypatch.setattr(
        "backend.clients.sheets_push.settings.apps_script_push_url",
        "https://script.google.com/macros/s/abc/exec",
    )
    monkeypatch.setattr(
        "backend.clients.sheets_push.settings.webhook_shared_secret", "shared",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "invalid signature"})

    transport = httpx.MockTransport(handler)
    _patch_async_client(monkeypatch, sheets_push, transport)

    with pytest.raises(sheets_push.SheetsPushError, match="invalid signature"):
        await sheets_push.push_rows(header=["a"], rows=[[1]])
