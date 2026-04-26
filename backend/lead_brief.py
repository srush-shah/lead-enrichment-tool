"""Lead Brief composer.

The 'Why Now' anchor has a documented fallback chain:
   1. Fresh news trigger (last 30 days)
   2. Recent news (last 90 days) with lower confidence
   3. Market-fit anchor (ZIP demographics)
   4. Company-fit fallback (Wikipedia mention)

Everything here is deterministic string composition. Gemini is only used for
email drafting and for optional prose polish on the talking point.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import httpx

from .clients import gemini
from .models import EnrichedLead, LeadBrief


def compose_brief(lead: EnrichedLead) -> LeadBrief:
    evidence: list[str] = []
    why_now, source = _why_now(lead, evidence)
    talking = _talking_point(lead)
    objection = _objection_preempt(lead)

    if lead.company.wiki_url:
        evidence.append(lead.company.wiki_url)

    return LeadBrief(
        why_now=why_now,
        why_now_source=source,
        talking_point=talking,
        objection_preempt=objection,
        evidence_links=evidence,
    )


def _why_now(lead: EnrichedLead, evidence: list[str]) -> tuple[str, str]:
    # 1. Fresh news
    fresh = _freshest_article(lead)
    if fresh:
        age_days, art = fresh
        freshness = f"{age_days} day{'s' if age_days != 1 else ''} ago"
        zip_bit = f" (ZIP {lead.geo.zip_code})" if lead.geo.zip_code else ""
        evidence.append(art.url)
        return (
            f"Trigger: {lead.input.company} — \"{art.title}\" ({freshness}, {art.source}){zip_bit}.",
            "news",
        )

    # 2. Market-fit anchor
    c = lead.census
    if c.renter_occupied_pct and c.median_gross_rent:
        zip_bit = f"{lead.geo.zip_code} " if lead.geo.zip_code else ""
        return (
            f"Market Insight: {zip_bit}has {c.renter_occupied_pct:.0f}% renter density "
            f"and ${c.median_gross_rent:,} median rent — "
            f"top-decile automation ROI territory for EliseAI.",
            "market",
        )
    if c.renter_occupied_pct:
        zip_bit = f"{lead.geo.zip_code} " if lead.geo.zip_code else ""
        return (
            f"Market Insight: {zip_bit}has {c.renter_occupied_pct:.0f}% renter density, "
            f"signaling high inquiry volume per property.",
            "market",
        )

    # 3. Company fallback
    if lead.company.has_wikipedia and lead.company.wiki_summary:
        snippet = lead.company.wiki_summary.split(".")[0]
        return (f"Company Note: {snippet}.", "company")

    return ("No fresh trigger found — treat as cold outreach.", "none")


def _freshest_article(lead: EnrichedLead):
    if not lead.news.articles:
        return None
    now = datetime.now(timezone.utc)
    scored = []
    for a in lead.news.articles:
        pub = a.published_at if a.published_at.tzinfo else a.published_at.replace(tzinfo=timezone.utc)
        age = (now - pub).days
        if age <= 90:
            scored.append((age, a))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    return scored[0]


def _talking_point(lead: EnrichedLead) -> str:
    c = lead.census
    w = lead.walk
    bits = []
    if c.pct_5plus_units:
        bits.append(f"{c.pct_5plus_units:.0f}% of housing units in this tract sit in 5+ unit buildings")
    if c.median_gross_rent:
        bits.append(f"median rent ${c.median_gross_rent:,}")
    if w.walkscore:
        bits.append(f"Walkability {w.walkscore}/100")
    if not bits:
        return f"Reference: {lead.input.company} manages property in {lead.input.city}, {lead.input.state}."
    return (
        f"{lead.input.city}, {lead.input.state}: "
        + "; ".join(bits)
        + ". Lead with leasing-volume ROI."
    )


def _objection_preempt(lead: EnrichedLead) -> Optional[str]:
    c = lead.census
    if c.renter_occupied_pct and c.renter_occupied_pct >= 70:
        return "High-churn tract (>=70% renter). Lead with leasing speed, not tenant retention."
    if c.renter_occupied_pct and c.renter_occupied_pct < 40:
        return "Owner-occupied skew. Be ready to confirm unit count before pitching volume ROI."
    if not lead.corporate_domain:
        return "Free-mail domain — confirm org size early; may be an independent owner."
    return None


# ---- Gemini-powered email draft --------------------------------------------


SYSTEM_PREFIX = """You are a senior SDR at EliseAI, which sells an AI leasing and resident
communications platform to multifamily property management companies and
owner-operators. Our product automates inbound leasing inquiries 24/7,
qualifies prospects, schedules tours, and handles maintenance triage --
saving operations staff hours per property per week.

You write concise, specific outreach emails. No generic openers ("I hope this
email finds you well"), no jargon, no corporate cliches. Always anchor on a
specific data point or trigger event from the lead brief provided.

Return STRICT JSON with keys "subject" and "body". The body is plain text,
3-4 short sentences max, ending with a single calendar CTA.
"""


def _email_prompt(lead: EnrichedLead) -> str:
    brief = lead.brief
    ctx = {
        "contact_name": lead.input.name,
        "contact_first_name": lead.input.name.split()[0] if lead.input.name else "there",
        "company": lead.input.company,
        "city": lead.input.city,
        "state": lead.input.state,
        "property_address": lead.input.property_address,
        "tier": lead.tier,
        "score": lead.score,
        "why_now": brief.why_now if brief else None,
        "why_now_source": brief.why_now_source if brief else None,
        "talking_point": brief.talking_point if brief else None,
        "objection_preempt": brief.objection_preempt if brief else None,
        "msa": lead.msa,
        "median_rent": lead.census.median_gross_rent,
        "renter_pct": lead.census.renter_occupied_pct,
        "pct_5plus": lead.census.pct_5plus_units,
        "walkscore": lead.walk.walkscore,
        "wiki_summary": lead.company.wiki_summary,
    }
    return (
        SYSTEM_PREFIX
        + "\n---\nLEAD BRIEF:\n"
        + json.dumps(ctx, default=str, indent=2)
        + "\n---\nReturn JSON only."
    )


async def draft_email(
    client: httpx.AsyncClient,
    lead: EnrichedLead,
    batch_mode: bool = True,
) -> None:
    prompt = _email_prompt(lead)
    parsed = await gemini.generate_json(client, prompt, batch_mode=batch_mode)
    if parsed and "subject" in parsed and "body" in parsed:
        lead.draft_email_subject = str(parsed["subject"]).strip()
        lead.draft_email_body = str(parsed["body"]).strip()
    else:
        lead.draft_email_subject = _fallback_subject(lead)
        lead.draft_email_body = _fallback_body(lead)


def _fallback_subject(lead: EnrichedLead) -> str:
    return f"Quick idea for {lead.input.company} in {lead.input.city}"


def _fallback_body(lead: EnrichedLead) -> str:
    brief = lead.brief
    first = lead.input.name.split()[0] if lead.input.name else "there"
    anchor = brief.why_now if brief else f"Saw {lead.input.company} is active in {lead.input.city}."
    talking = brief.talking_point if brief else ""
    return (
        f"Hi {first},\n\n"
        f"{anchor} {talking}\n\n"
        f"EliseAI's AI leasing agent handles 24/7 inbound inquiries and tour "
        f"scheduling for multifamily operators — teams like yours typically "
        f"reclaim 15+ hours per property per week.\n\n"
        f"Worth a 15-min intro next week? Happy to send times."
    )
