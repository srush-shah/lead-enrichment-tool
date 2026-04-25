from __future__ import annotations

from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..config import settings
from ..models import GeoData, WalkData

BASE = "https://api.walkscore.com/score"
CACHE_TTL_HOURS = 24 * 30


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
async def _fetch(client: httpx.AsyncClient, address: str, lat: float, lng: float) -> dict:
    params = {
        "format": "json",
        "address": address,
        "lat": lat,
        "lon": lng,
        "wsapikey": settings.walkscore_api_key,
    }
    r = await client.get(BASE, params=params, timeout=10.0)
    r.raise_for_status()
    return r.json()


async def fetch_walkscore(client: httpx.AsyncClient, address: str, geo: GeoData) -> WalkData:
    if not settings.walkscore_api_key or geo.lat is None or geo.lng is None:
        return WalkData()

    key = f"{geo.lat:.5f},{geo.lng:.5f}"
    cached = cache.cache_get("walkscore", key)
    if cached:
        return WalkData(**cached)

    try:
        data = await _fetch(client, address, geo.lat, geo.lng)
    except Exception:
        return WalkData()

    score = data.get("walkscore") if data.get("status") == 1 else None
    result = WalkData(walkscore=score, description=data.get("description"))
    cache.cache_set("walkscore", key, result.model_dump(), CACHE_TTL_HOURS)
    return result
