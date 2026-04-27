from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..config import (
    GEMINI_BATCH_CEILING,
    GEMINI_DAILY_CAP,
    GEMINI_MIN_GAP_SECONDS,
    settings,
)
from ..quota import QuotaExhausted, QuotaSpec, release, reserve

# Cache prompt -> response by sha256(prompt). When the lead brief changes
# (different news, different scoring) the prompt changes and the cache
# auto-invalidates. 24h TTL keeps drafts fresh enough for outreach.
GEMINI_CACHE_TTL_HOURS = 24

ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
)

SPEC = QuotaSpec(
    api="gemini",
    hard_cap=GEMINI_DAILY_CAP,
    batch_ceiling=GEMINI_BATCH_CEILING,
    reserved_for_realtime=GEMINI_DAILY_CAP - GEMINI_BATCH_CEILING,
)

# Token bucket: a module-level timestamp of the last call pins the 15 RPM ceiling
# across concurrent tasks within a single process.
_last_call_ts: float = 0.0
_gap_lock = asyncio.Lock()


async def _respect_rpm() -> None:
    global _last_call_ts
    async with _gap_lock:
        now = time.monotonic()
        wait = GEMINI_MIN_GAP_SECONDS - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_ts = time.monotonic()


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
async def _call(client: httpx.AsyncClient, prompt: str) -> str:
    r = await client.post(
        ENDPOINT,
        params={"key": settings.gemini_api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.6,
                "maxOutputTokens": 512,
                # 2.5 Flash enables "thinking" by default, which silently
                # consumes the output budget and returns an empty body.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    batch_mode: bool = True,
    skip_cache: bool = False,
) -> Optional[str]:
    if not settings.gemini_api_key:
        return None

    cache_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if not skip_cache:
        cached = cache.cache_get("gemini", cache_key)
        if cached is not None:
            return cached if isinstance(cached, str) else cached.get("text")

    try:
        reserve(SPEC, batch_mode=batch_mode)
    except QuotaExhausted:
        return None

    await _respect_rpm()
    try:
        text = await _call(client, prompt)
    except Exception:
        release(SPEC)
        return None

    if text:
        cache.cache_set("gemini", cache_key, {"text": text}, GEMINI_CACHE_TTL_HOURS)
    return text


async def generate_json(
    client: httpx.AsyncClient,
    prompt: str,
    batch_mode: bool = True,
    skip_cache: bool = False,
) -> Optional[dict]:
    """Gemini doesn't support strict JSON mode on free tier; we parse defensively."""
    text = await generate(client, prompt, batch_mode=batch_mode, skip_cache=skip_cache)
    if not text:
        return None
    # Strip common markdown fences.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Salvage the first {...} block.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None
