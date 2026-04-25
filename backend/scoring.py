"""Pure scoring logic. No I/O; fully testable.

The pipeline computes scores in three passes that mirror the enrichment stages:

  S1 (Foundation) -> MPS, MarketFit, DomainSignal, PreScore
  S2 (Context)    -> CompanyFit, Timing (needs Wikipedia + News)
  S3 (Synthesis)  -> FinalScore, Tier (uses everything)
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import (
    CITY_TO_MSA,
    FREE_MAIL_DOMAINS,
    FULL_SCORE_WEIGHTS,
    MPS_SKIP_THRESHOLD,
    MPS_WEIGHTS,
    PRE_SCORE_WEIGHTS,
    TIER_A_MIN,
    TIER_B_MIN,
    TIER_C_MIN,
    TOP_25_MSAS,
)
from .models import CensusData, CompanyData, EnrichedLead, NewsData, SubScores, Tier, WalkData


# ---- Derived input signals -------------------------------------------------


def classify_msa(city: str) -> tuple[str | None, bool]:
    msa = CITY_TO_MSA.get(city.lower().strip())
    return msa, (msa in TOP_25_MSAS if msa else False)


def is_corporate_email(email: str) -> bool:
    domain = email.split("@")[-1].lower().strip() if "@" in email else ""
    if not domain:
        return False
    return domain not in FREE_MAIL_DOMAINS


# ---- Sub-scores ------------------------------------------------------------


def mps(census: CensusData, walk: WalkData) -> float:
    """Multifamily Probability Score (0-100). See ASSUMPTIONS.md A7."""
    p5 = census.pct_5plus_units or 0.0
    ws = walk.walkscore if walk.walkscore is not None else 50.0  # neutral default
    dens = min((census.pop_density_per_sqmi or 0) / 15000.0, 1.0) * 100.0
    renter = census.renter_occupied_pct or 0.0
    w = MPS_WEIGHTS
    score = w["p5plus"] * p5 + w["walkscore"] * ws + w["density"] * dens + w["renter"] * renter
    return round(min(score, 100.0), 1)


def market_fit(census: CensusData, in_top25: bool) -> float:
    """Market Fit 0-100 = rent pricing headroom (A3) + MSA bonus (A6)."""
    rent = census.median_gross_rent
    if rent is None:
        rent_score = 30.0  # neutral when missing
    elif rent >= 2500:
        rent_score = 100.0
    elif rent >= 1500:
        rent_score = 50.0 + (rent - 1500) * 50.0 / 1000.0
    elif rent >= 1000:
        rent_score = (rent - 1000) * 50.0 / 500.0
    else:
        rent_score = 0.0
    msa_bonus = 25.0 if in_top25 else 0.0
    return round(min(rent_score * 0.75 + msa_bonus, 100.0), 1)


def domain_signal(email: str) -> float:
    return 100.0 if is_corporate_email(email) else 0.0


def pre_score(mps_val: float, mf: float, ds: float) -> float:
    w = PRE_SCORE_WEIGHTS
    return round(w["mps"] * mps_val + w["market_fit"] * mf + w["domain"] * ds, 1)


def company_fit(company: CompanyData, corp_email: bool) -> float:
    """Company Fit 0-100 = Wikipedia scale proxy (A5) + corporate domain (A2)."""
    wiki = 50.0 if company.has_wikipedia else 0.0
    dom = 50.0 if corp_email else 0.0
    return round(wiki + dom, 1)


def timing(news: NewsData) -> float:
    """Timing 0-100 based on news velocity (A4).

    Fresh (<=30d):   up to 100
    Recent (31-90d): up to 60
    None/skipped:    0 (and surface fallback reason elsewhere)
    """
    if not news.articles:
        return 0.0
    now = datetime.now(timezone.utc)
    scored = 0.0
    for a in news.articles[:3]:
        age_days = (now - a.published_at).days if a.published_at.tzinfo else (now - a.published_at.replace(tzinfo=timezone.utc)).days
        if age_days <= 30:
            scored = max(scored, 100.0 - age_days * 1.0)
        elif age_days <= 90:
            scored = max(scored, 60.0 - (age_days - 30) * 0.5)
    return round(min(scored, 100.0), 1)


def geographic(in_top25: bool) -> float:
    return 100.0 if in_top25 else 30.0  # non-top-25 still counts, just less


def full_score(mf: float, cf: float, tm: float, geo: float) -> float:
    w = FULL_SCORE_WEIGHTS
    return round(w["market_fit"] * mf + w["company_fit"] * cf + w["timing"] * tm + w["geographic"] * geo, 1)


def tier_for(score: float, skipped: bool) -> Tier:
    if skipped:
        return "Skipped"
    if score >= TIER_A_MIN:
        return "A"
    if score >= TIER_B_MIN:
        return "B"
    if score >= TIER_C_MIN:
        return "C"
    return "D"


# ---- Orchestrator entry points --------------------------------------------


def compute_stage1(lead: EnrichedLead) -> SubScores:
    """Compute MPS, MarketFit, DomainSignal, PreScore. Called after S1 enrichment."""
    msa, in_top25 = classify_msa(lead.input.city)
    lead.msa = msa
    lead.in_top25_msa = in_top25
    lead.corporate_domain = is_corporate_email(lead.input.email)

    mps_val = mps(lead.census, lead.walk)
    mf = market_fit(lead.census, in_top25)
    ds = domain_signal(lead.input.email)
    ps = pre_score(mps_val, mf, ds)

    # Stage 1 populates what it can; timing/company_fit filled in later.
    return SubScores(
        mps=mps_val,
        market_fit=mf,
        company_fit=0.0,
        timing=0.0,
        geographic=geographic(in_top25),
        pre_score=ps,
    )


def finalize(lead: EnrichedLead, sub: SubScores) -> None:
    """Fill in company_fit, timing, full score, tier. Called after S2."""
    sub.company_fit = company_fit(lead.company, lead.corporate_domain)
    sub.timing = timing(lead.news)

    if sub.mps < MPS_SKIP_THRESHOLD:
        lead.skipped_reason = f"Low Multifamily Prob (MPS: {sub.mps:.0f})"
        lead.score = sub.mps  # surface the MPS itself as the visible number
        lead.tier = "Skipped"
    else:
        score = full_score(sub.market_fit, sub.company_fit, sub.timing, sub.geographic)
        lead.score = score
        lead.tier = tier_for(score, skipped=False)

    lead.sub_scores = sub
