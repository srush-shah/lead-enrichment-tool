from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


Tier = Literal["A", "B", "C", "D", "Skipped"]


class LeadInput(BaseModel):
    name: str
    email: str
    company: str
    property_address: str
    city: str
    state: str
    country: str = "USA"


class BatchRequest(BaseModel):
    leads: list[LeadInput]
    force: bool = False  # bypass idempotency cache


class GeoData(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    state_fips: Optional[str] = None
    county_fips: Optional[str] = None
    tract_fips: Optional[str] = None
    zip_code: Optional[str] = None


class CensusData(BaseModel):
    total_units: Optional[int] = None
    renter_occupied_pct: Optional[float] = None
    pct_5plus_units: Optional[float] = None
    median_gross_rent: Optional[int] = None
    population: Optional[int] = None
    pop_density_per_sqmi: Optional[float] = None


class WalkData(BaseModel):
    walkscore: Optional[int] = None
    description: Optional[str] = None


class CompanyData(BaseModel):
    wiki_summary: Optional[str] = None
    wiki_url: Optional[str] = None
    has_wikipedia: bool = False


class NewsArticle(BaseModel):
    title: str
    url: str
    published_at: datetime
    source: str
    description: Optional[str] = None


class NewsData(BaseModel):
    articles: list[NewsArticle] = Field(default_factory=list)
    skipped_reason: Optional[str] = None  # e.g., "quota_reserved_for_realtime"


class SubScores(BaseModel):
    mps: float
    market_fit: float
    company_fit: float
    timing: float
    geographic: float
    pre_score: float


class LeadBrief(BaseModel):
    why_now: str
    why_now_source: Literal["news", "market", "company", "none"]
    talking_point: str
    objection_preempt: Optional[str] = None
    evidence_links: list[str] = Field(default_factory=list)


class EnrichedLead(BaseModel):
    # Echo of input
    input: LeadInput

    # Raw enrichment
    geo: GeoData = Field(default_factory=GeoData)
    census: CensusData = Field(default_factory=CensusData)
    walk: WalkData = Field(default_factory=WalkData)
    company: CompanyData = Field(default_factory=CompanyData)
    news: NewsData = Field(default_factory=NewsData)

    # Derived
    msa: Optional[str] = None
    in_top25_msa: bool = False
    corporate_domain: bool = False
    sub_scores: Optional[SubScores] = None
    score: Optional[float] = None
    tier: Tier = "D"
    skipped_reason: Optional[str] = None  # e.g., "Low Multifamily Prob (MPS: 32)"

    # SDR deliverables
    brief: Optional[LeadBrief] = None
    draft_email_subject: Optional[str] = None
    draft_email_body: Optional[str] = None

    enriched_at: datetime = Field(default_factory=_utcnow)


class BatchSummary(BaseModel):
    total: int
    tier_a: int
    tier_b: int
    tier_c: int
    tier_d: int
    skipped: int
    news_calls_used: int
    news_calls_cap: int
    gemini_calls_used: int
    wall_time_seconds: float
    fallbacks_used: int = 0


class BatchResponse(BaseModel):
    leads: list[EnrichedLead]
    summary: BatchSummary
