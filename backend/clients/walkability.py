"""Walkability proxy via OpenStreetMap Overpass API.

Replaces the original WalkScore integration. WalkScore restricted free keys
to a single registered domain, which made the public API unusable for this
project. Overpass is open data, no key, no domain lock.

The 0-100 score we produce is a log-scaled count of walkable POIs and transit
near the address (shops, restaurants, schools, banks, transit stops). It is
not WalkScore-equivalent in absolute terms, but it is monotonic with urban
density -- which is what the MPS weight in scoring.py:46-54 actually needs.

Calibration on the sample addresses (count -> score):
    Manhattan        2313 -> 100
    Chicago Loop     1770 ->  97
    SF Mission       1175 ->  92
    Bismarck downtown  60 ->  53
    Bellaire suburb    39 ->  48
    Highlands Ranch     2 ->  14
"""
from __future__ import annotations

import asyncio
import math

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..models import GeoData, WalkData

ENDPOINT = "https://overpass-api.de/api/interpreter"
CACHE_TTL_HOURS = 24 * 30  # OSM amenity density changes slowly

# Public Overpass servers rate-limit aggressively on bursts. We tested 3
# concurrent and got 429s + retry-chain stalls (sum 270s vs 112s at sem=2).
# 2 is the sustainable sweet spot; results cache 30 days so re-runs are free.
_OVERPASS_SEM = asyncio.Semaphore(2)

QUERY = """
[out:json][timeout:25];
(
  node(around:1500,{lat},{lng})[shop];
  node(around:1500,{lat},{lng})[amenity~"^(restaurant|cafe|bar|pub|fast_food|school|bank|pharmacy|marketplace|library|cinema|theatre|hospital|clinic|college|university)$"];
  node(around:800,{lat},{lng})[public_transport];
  node(around:500,{lat},{lng})[highway=bus_stop];
);
out count;
"""


def _score_from_count(count: int) -> int:
    if count <= 0:
        return 0
    return int(min(100, round(30.0 * math.log10(count + 1))))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8), reraise=True)
async def _fetch(client: httpx.AsyncClient, lat: float, lng: float) -> int:
    async with _OVERPASS_SEM:
        r = await client.post(
            ENDPOINT,
            data=QUERY.format(lat=lat, lng=lng),
            timeout=45.0,
        )
    r.raise_for_status()
    data = r.json()
    total = 0
    for el in data.get("elements", []):
        if el.get("type") == "count":
            total += int(el.get("tags", {}).get("total", 0))
    return total


async def fetch_walkability(client: httpx.AsyncClient, address: str, geo: GeoData) -> WalkData:
    if geo.lat is None or geo.lng is None:
        return WalkData()

    key = f"{geo.lat:.5f},{geo.lng:.5f}"
    cached = cache.cache_get("walkability", key)
    if cached:
        return WalkData(**cached)

    try:
        count = await _fetch(client, geo.lat, geo.lng)
    except Exception:
        return WalkData()

    score = _score_from_count(count)
    result = WalkData(
        walkscore=score,
        description=f"Walkability proxy ({count} POIs/transit nodes within 1.5km, OpenStreetMap)",
    )
    cache.cache_set("walkability", key, result.model_dump(), CACHE_TTL_HOURS)
    return result
