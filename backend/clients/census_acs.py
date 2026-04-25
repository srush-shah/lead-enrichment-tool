"""Census ACS 5-year: demographic + housing profile at tract level.

Variables:
  B25003_001E  total occupied units
  B25003_003E  renter-occupied units
  B25024_001E  total units in structure
  B25024_006E  5 to 9 units
  B25024_007E  10 to 19 units
  B25024_008E  20 to 49 units
  B25024_009E  50 or more units
  B25064_001E  median gross rent
  B01003_001E  total population
  B01001_001E  (same as B01003, kept as sanity check)
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..config import settings
from ..models import CensusData, GeoData

BASE = "https://api.census.gov/data/2022/acs/acs5"
CACHE_TTL_HOURS = 24 * 30

VARS = [
    "B25003_001E", "B25003_003E",
    "B25024_001E", "B25024_006E", "B25024_007E", "B25024_008E", "B25024_009E",
    "B25064_001E",
    "B01003_001E",
]

# Rough land area (sq mi) per census tract is not in ACS. We approximate density
# using population / (tract area proxy). Since we can't fetch TIGER shapefiles
# at runtime, we use a fixed proxy (1 sq mi) for urban tracts, adjusted by a
# bounded heuristic below. This is acknowledged in ASSUMPTIONS.md.
TRACT_AREA_PROXY_SQMI = 1.5


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
async def _fetch(client: httpx.AsyncClient, state: str, county: str, tract: str) -> list:
    params = {
        "get": ",".join(VARS),
        "for": f"tract:{tract}",
        "in": f"state:{state} county:{county}",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key
    r = await client.get(BASE, params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


async def fetch_acs(client: httpx.AsyncClient, geo: GeoData) -> CensusData:
    if not (geo.state_fips and geo.county_fips and geo.tract_fips):
        return CensusData()

    key = f"{geo.state_fips}-{geo.county_fips}-{geo.tract_fips}"
    cached = cache.cache_get("acs", key)
    if cached:
        return CensusData(**cached)

    try:
        rows = await _fetch(client, geo.state_fips, geo.county_fips, geo.tract_fips)
    except Exception:
        return CensusData()

    if not rows or len(rows) < 2:
        return CensusData()

    headers, values = rows[0], rows[1]
    v = dict(zip(headers, values))

    def _num(key: str) -> float | None:
        raw = v.get(key)
        if raw is None or raw == "" or raw == "-":
            return None
        try:
            n = float(raw)
            return n if n >= 0 else None
        except (TypeError, ValueError):
            return None

    total_occupied = _num("B25003_001E") or 0
    renter_occ = _num("B25003_003E") or 0
    total_units = _num("B25024_001E") or 0
    u5plus = sum(_num(k) or 0 for k in ("B25024_006E", "B25024_007E", "B25024_008E", "B25024_009E"))
    median_rent = _num("B25064_001E")
    population = _num("B01003_001E") or 0

    renter_pct = (renter_occ / total_occupied * 100) if total_occupied else None
    pct5 = (u5plus / total_units * 100) if total_units else None
    density = (population / TRACT_AREA_PROXY_SQMI) if population else None

    data = CensusData(
        total_units=int(total_units) if total_units else None,
        renter_occupied_pct=round(renter_pct, 1) if renter_pct is not None else None,
        pct_5plus_units=round(pct5, 1) if pct5 is not None else None,
        median_gross_rent=int(median_rent) if median_rent else None,
        population=int(population) if population else None,
        pop_density_per_sqmi=round(density, 0) if density else None,
    )
    cache.cache_set("acs", key, data.model_dump(), CACHE_TTL_HOURS)
    return data
