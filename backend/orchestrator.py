"""Three-stage enrichment funnel.

  S1 (all leads): geocode + ACS + walkscore + derived signals -> Pre-Score
  S2 (Pre-Score >= 50 AND corporate domain): Wikipedia + News
  S3 (Full Score >= 70): Gemini email draft

Concurrency strategy:
  - Leads run in parallel under a semaphore (default 10).
  - Within one lead, independent calls (e.g. ACS + WalkScore) run via asyncio.gather.
  - Gemini pacing is enforced globally by the client (token-bucket lock).
"""
from __future__ import annotations

import asyncio
import time

import httpx

from . import cache, lead_brief, scoring
from .clients import census_acs, census_geocoder, gemini, newsapi, walkscore, wikipedia
from .config import FULL_SCORE_S3_GATE, PRE_SCORE_S2_GATE
from .models import BatchResponse, BatchSummary, EnrichedLead, LeadInput


CONCURRENCY = 10


async def _stage1(client: httpx.AsyncClient, lead: EnrichedLead) -> None:
    geo = await census_geocoder.geocode(
        client,
        lead.input.property_address,
        lead.input.city,
        lead.input.state,
    )
    lead.geo = geo

    address_full = f"{lead.input.property_address}, {lead.input.city}, {lead.input.state}"
    census_task = census_acs.fetch_acs(client, geo)
    walk_task = walkscore.fetch_walkscore(client, address_full, geo)
    census_data, walk_data = await asyncio.gather(census_task, walk_task)

    lead.census = census_data
    lead.walk = walk_data
    lead.sub_scores = scoring.compute_stage1(lead)


async def _stage2(client: httpx.AsyncClient, lead: EnrichedLead, batch_mode: bool) -> None:
    wiki_task = wikipedia.fetch_company(client, lead.input.company)
    news_task = newsapi.fetch_news(client, lead.input.company, batch_mode=batch_mode)
    company, news = await asyncio.gather(wiki_task, news_task)
    lead.company = company
    lead.news = news


async def _stage3(client: httpx.AsyncClient, lead: EnrichedLead, batch_mode: bool) -> None:
    await lead_brief.draft_email(client, lead, batch_mode=batch_mode)


async def _process_lead(
    client: httpx.AsyncClient,
    raw: LeadInput,
    batch_mode: bool,
    sem: asyncio.Semaphore,
) -> EnrichedLead:
    async with sem:
        lead = EnrichedLead(input=raw)

        await _stage1(client, lead)

        sub = lead.sub_scores
        if sub is None:
            return lead  # should not happen; defensive

        gate_s2 = sub.pre_score >= PRE_SCORE_S2_GATE and lead.corporate_domain
        # If MPS is below the skip threshold, do not burn S2 quota -- compose
        # brief from S1 data only and mark Skipped.
        if sub.mps < scoring.MPS_SKIP_THRESHOLD:
            scoring.finalize(lead, sub)
            lead.brief = lead_brief.compose_brief(lead)
            return lead

        if gate_s2:
            await _stage2(client, lead, batch_mode=batch_mode)

        scoring.finalize(lead, sub)
        lead.brief = lead_brief.compose_brief(lead)

        if lead.score is not None and lead.score >= FULL_SCORE_S3_GATE and lead.tier != "Skipped":
            await _stage3(client, lead, batch_mode=batch_mode)

        return lead


async def run_batch(leads: list[LeadInput], batch_mode: bool = True) -> BatchResponse:
    cache.init_db()
    started = time.monotonic()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(headers={"User-Agent": "EliseAI-GTM-Tool/1.0"}) as client:
        tasks = [_process_lead(client, lead, batch_mode, sem) for lead in leads]
        enriched = await asyncio.gather(*tasks)

    summary = _summarize(enriched, time.monotonic() - started)
    return BatchResponse(leads=enriched, summary=summary)


def _summarize(leads: list[EnrichedLead], wall_time: float) -> BatchSummary:
    tiers = {"A": 0, "B": 0, "C": 0, "D": 0, "Skipped": 0}
    fallbacks = 0
    for l in leads:
        tiers[l.tier] = tiers.get(l.tier, 0) + 1
        if l.brief and l.brief.why_now_source in ("market", "company", "none"):
            fallbacks += 1

    from .config import GEMINI_DAILY_CAP, NEWSAPI_DAILY_CAP
    return BatchSummary(
        total=len(leads),
        tier_a=tiers["A"],
        tier_b=tiers["B"],
        tier_c=tiers["C"],
        tier_d=tiers["D"],
        skipped=tiers["Skipped"],
        news_calls_used=cache.usage_today("newsapi"),
        news_calls_cap=NEWSAPI_DAILY_CAP,
        gemini_calls_used=cache.usage_today("gemini"),
        wall_time_seconds=round(wall_time, 2),
        fallbacks_used=fallbacks,
    )
