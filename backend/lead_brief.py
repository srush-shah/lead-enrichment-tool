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
import re
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx

from .clients import gemini
from .models import EnrichedLead, LeadBrief


Tone = Literal["casual", "formal"]


_TONE_INSTRUCTIONS: dict[str, str] = {
    "casual": (
        "TONE OVERRIDE: Casual and conversational. First-name basis, "
        "short sentences, contractions are fine. Skip corporate phrasing."
    ),
    "formal": (
        "TONE OVERRIDE: Formal and respectful. Avoid contractions and idioms. "
        "Address the contact by full name in the greeting."
    ),
}


# Tone-aware presets for the no-Gemini fallback path. Used by
# render_template_email below — runs when QuotaExhausted aborts a
# regenerate, OR when Gemini returns a malformed response. Produces a
# deterministic, fully-rebuilt draft so the user sees a clearly different
# email after every regenerate, regardless of what was there before.

_PITCH_DEFAULT = (
    "EliseAI's AI leasing agent handles 24/7 inbound inquiries and tour "
    "scheduling for multifamily operators — teams like yours typically "
    "reclaim 15+ hours per property per week."
)
_PITCH_CASUAL = (
    "Quick context — EliseAI's AI leasing agent handles 24/7 inbound "
    "inquiries and tour scheduling. Teams like yours usually claw back "
    "15+ hours per property per week."
)
_PITCH_FORMAL = (
    "EliseAI provides an AI leasing platform that addresses inbound "
    "inquiries and tour scheduling around the clock for multifamily "
    "operators. Comparable organizations typically recover in excess of "
    "15 hours per property per week."
)

_CTA_DEFAULT = "Worth a 15-min intro next week? Happy to send times."
_CTA_CASUAL = "Open to a 15-min chat next week? Happy to send a few times."
_CTA_FORMAL = (
    "Would you be available for a 15-minute introduction next week? "
    "I would be glad to share several time options."
)


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


def _email_prompt(lead: EnrichedLead, tone: Optional[Tone] = None) -> str:
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
    tone_block = f"\n\n{_TONE_INSTRUCTIONS[tone]}" if tone in _TONE_INSTRUCTIONS else ""
    return (
        SYSTEM_PREFIX
        + tone_block
        + "\n---\nLEAD BRIEF:\n"
        + json.dumps(ctx, default=str, indent=2)
        + "\n---\nReturn JSON only."
    )


async def draft_email(
    client: httpx.AsyncClient,
    lead: EnrichedLead,
    batch_mode: bool = True,
    tone: Optional[Tone] = None,
    skip_cache: bool = False,
) -> None:
    prompt = _email_prompt(lead, tone=tone)
    parsed = await gemini.generate_json(
        client, prompt, batch_mode=batch_mode, skip_cache=skip_cache,
    )
    if parsed and "subject" in parsed and "body" in parsed:
        lead.draft_email_subject = str(parsed["subject"]).strip()
        lead.draft_email_body = str(parsed["body"]).strip()
    else:
        subject, body = render_template_email(lead, tone=tone)
        lead.draft_email_subject = subject
        lead.draft_email_body = body


_LABEL_PREFIX_RE = re.compile(r"^(Trigger|Market Insight|Company Note)\s*:\s*")


def _strip_brief_label(text: str) -> str:
    return _LABEL_PREFIX_RE.sub("", text)


def _property_specs(lead: EnrichedLead) -> str:
    bits: list[str] = []
    if lead.geo.zip_code:
        bits.append(f"ZIP {lead.geo.zip_code}")
    if lead.census.pct_5plus_units:
        bits.append(f"{lead.census.pct_5plus_units:.0f}% in 5+ unit buildings")
    if lead.walk.walkscore:
        bits.append(f"WalkScore {lead.walk.walkscore}")
    if lead.census.median_gross_rent:
        bits.append(f"median rent ${lead.census.median_gross_rent:,}")
    return " · ".join(bits)


def _fallback_subject(lead: EnrichedLead) -> str:
    return f"Quick idea for {lead.input.company} in {lead.input.city}"


def render_template_email(
    lead: EnrichedLead, tone: Optional[Tone] = None,
) -> tuple[str, str]:
    """Build a fresh subject + body from the deterministic brief, biased
    by tone. Used whenever Gemini is unavailable (quota exhausted or
    malformed response) so the user always sees a tone-correct draft."""
    brief = lead.brief
    first = lead.input.name.split()[0] if lead.input.name else "there"
    full = lead.input.name or "there"
    raw_anchor = (
        brief.why_now if brief
        else f"Saw {lead.input.company} is active in {lead.input.city}."
    )
    anchor = _strip_brief_label(raw_anchor)
    specs = _property_specs(lead)
    footer = f"\n\n---\nProperty specs: {specs}" if specs else ""

    if tone == "casual":
        greeting, pitch, cta = f"Hey {first},", _PITCH_CASUAL, _CTA_CASUAL
        subject = f"Quick idea for {lead.input.company}"
    elif tone == "formal":
        greeting, pitch, cta = f"Dear {full},", _PITCH_FORMAL, _CTA_FORMAL
        subject = f"Introduction — EliseAI for {lead.input.company}"
    else:
        greeting, pitch, cta = f"Hi {first},", _PITCH_DEFAULT, _CTA_DEFAULT
        subject = _fallback_subject(lead)

    body = f"{greeting}\n\n{anchor}\n\n{pitch}\n\n{cta}{footer}"
    return subject, body


def _fallback_body(lead: EnrichedLead) -> str:
    _, body = render_template_email(lead, tone=None)
    return body
