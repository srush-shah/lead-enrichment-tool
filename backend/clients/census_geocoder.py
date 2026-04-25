"""Census Geocoder: address -> (lat, lng) + FIPS codes (state/county/tract).

Chosen over Nominatim because it returns FIPS geographies in one call,
removing a downstream lookup. Free, no API key, no hard rate limit.
"""
from __future__ import annotations

from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..models import GeoData

BASE = "https://geocoding.geo.census.gov/geocoder/geographies/address"
CACHE_TTL_HOURS = 24 * 30  # addresses rarely change


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
async def _fetch(client: httpx.AsyncClient, params: dict) -> dict:
    r = await client.get(BASE, params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


async def geocode(
    client: httpx.AsyncClient,
    street: str,
    city: str,
    state: str,
) -> GeoData:
    key = f"{street}|{city}|{state}".lower().strip()
    cached = cache.cache_get("geocode", key)
    if cached:
        return GeoData(**cached)

    params = {
        "street": street,
        "city": city,
        "state": state,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    try:
        data = await _fetch(client, params)
    except Exception:
        return GeoData()

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return GeoData()

    m = matches[0]
    coords = m.get("coordinates", {})
    geos = m.get("geographies", {})
    tracts = geos.get("Census Tracts", [])
    tract = tracts[0] if tracts else {}

    geo = GeoData(
        lat=coords.get("y"),
        lng=coords.get("x"),
        state_fips=tract.get("STATE"),
        county_fips=tract.get("COUNTY"),
        tract_fips=tract.get("TRACT"),
        zip_code=_extract_zip(m.get("matchedAddress", "")),
    )
    cache.cache_set("geocode", key, geo.model_dump(), CACHE_TTL_HOURS)
    return geo


def _extract_zip(addr: str) -> Optional[str]:
    # e.g. "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500"
    parts = [p.strip() for p in addr.split(",")]
    if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
        return parts[-1]
    return None
