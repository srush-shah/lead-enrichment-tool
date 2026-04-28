from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .. import cache, quota_store
from ..config import NEWSAPI_BATCH_CEILING, NEWSAPI_DAILY_CAP, settings
from ..models import NewsArticle, NewsData
from ..quota import QuotaExhausted, QuotaSpec, release, reserve


def _retry_unless_429(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return False
    return True

BASE = "https://newsapi.org/v2/everything"
CACHE_TTL_HOURS = 6  # refresh news a few times per day
# NewsAPI's free Developer plan only serves articles from the last ~30 days.
# Asking for 90 returns HTTP 426 "parameterInvalid".
LOOKBACK_DAYS = 29

SPEC = QuotaSpec(
    api="newsapi",
    hard_cap=NEWSAPI_DAILY_CAP,
    batch_ceiling=NEWSAPI_BATCH_CEILING,
    reserved_for_realtime=NEWSAPI_DAILY_CAP - NEWSAPI_BATCH_CEILING,
)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=3),
    retry=retry_if_exception(_retry_unless_429),
    reraise=True,
)
async def _fetch(client: httpx.AsyncClient, query: str) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    params = {
        "q": f'"{query}"',
        "from": since,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "apiKey": settings.newsapi_key,
    }
    r = await client.get(BASE, params=params, timeout=10.0)
    r.raise_for_status()
    return r.json()


async def fetch_news(
    client: httpx.AsyncClient,
    company: str,
    batch_mode: bool = True,
) -> NewsData:
    key = company.lower().strip()
    cached = cache.cache_get("news", key)
    if cached:
        return NewsData(**cached)

    if not settings.newsapi_key:
        return NewsData(skipped_reason="no_api_key")

    try:
        reserve(SPEC, batch_mode=batch_mode)
    except QuotaExhausted as e:
        return NewsData(skipped_reason=e.reason)

    try:
        data = await _fetch(client, company)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            quota_store.set_usage(SPEC.api, SPEC.hard_cap)
            return NewsData(skipped_reason="daily_cap_reached")
        release(SPEC)
        return NewsData(skipped_reason="api_error")
    except Exception:
        release(SPEC)  # don't burn budget on transport errors
        return NewsData(skipped_reason="api_error")

    arts: list[NewsArticle] = []
    for a in (data.get("articles") or [])[:5]:
        try:
            arts.append(NewsArticle(
                title=a.get("title") or "",
                url=a.get("url") or "",
                published_at=datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00")),
                source=(a.get("source") or {}).get("name") or "",
                description=a.get("description"),
            ))
        except Exception:
            continue

    result = NewsData(articles=arts)
    cache.cache_set("news", key, result.model_dump(), CACHE_TTL_HOURS)
    return result
