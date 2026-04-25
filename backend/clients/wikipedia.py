from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import cache
from ..models import CompanyData

BASE = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
CACHE_TTL_HOURS = 24 * 7


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=3), reraise=True)
async def _search(client: httpx.AsyncClient, company: str) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": company,
        "srlimit": 1,
    }
    r = await client.get(BASE, params=params, timeout=10.0)
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=3), reraise=True)
async def _summary(client: httpx.AsyncClient, title: str) -> dict:
    url = SUMMARY.format(title=title.replace(" ", "_"))
    r = await client.get(url, timeout=10.0)
    r.raise_for_status()
    return r.json()


async def fetch_company(client: httpx.AsyncClient, company: str) -> CompanyData:
    key = company.lower().strip()
    cached = cache.cache_get("wikipedia", key)
    if cached:
        return CompanyData(**cached)

    try:
        title = await _search(client, company)
        if not title:
            result = CompanyData(has_wikipedia=False)
            cache.cache_set("wikipedia", key, result.model_dump(), CACHE_TTL_HOURS)
            return result
        data = await _summary(client, title)
    except Exception:
        return CompanyData(has_wikipedia=False)

    # Wikipedia "search" matches loosely; require the title to actually contain
    # a token from the company name to avoid false positives (e.g. searching
    # "Camden" returning the city).
    if not _looks_related(company, data.get("title", "")):
        result = CompanyData(has_wikipedia=False)
        cache.cache_set("wikipedia", key, result.model_dump(), CACHE_TTL_HOURS)
        return result

    extract = data.get("extract") or ""
    result = CompanyData(
        has_wikipedia=bool(extract),
        wiki_summary=extract[:500] if extract else None,
        wiki_url=data.get("content_urls", {}).get("desktop", {}).get("page"),
    )
    cache.cache_set("wikipedia", key, result.model_dump(), CACHE_TTL_HOURS)
    return result


def _looks_related(company: str, title: str) -> bool:
    c_tokens = {t.lower() for t in company.split() if len(t) > 2}
    t_tokens = {t.lower() for t in title.split() if len(t) > 2}
    return bool(c_tokens & t_tokens)
