from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend import scoring
from backend.config import MPS_SKIP_THRESHOLD
from backend.models import (
    CensusData, CompanyData, EnrichedLead, LeadInput, NewsArticle, NewsData, WalkData,
)


def _lead(**kw) -> EnrichedLead:
    base = LeadInput(
        name="Jane Doe",
        email="jane@bigreit.com",
        company="BigREIT",
        property_address="100 Main St",
        city="Austin",
        state="TX",
    )
    return EnrichedLead(input=base, **kw)


def test_mps_high_for_dense_urban():
    # Manhattan-like tract: 90% units in 5+, walkscore 95, 30k/sqmi, 80% renter.
    c = CensusData(pct_5plus_units=90.0, renter_occupied_pct=80.0, pop_density_per_sqmi=30000)
    w = WalkData(walkscore=95)
    assert scoring.mps(c, w) >= 85


def test_mps_low_for_suburban_sfh():
    # Typical SFH suburb: 5% units in 5+, walkscore 30, 2k/sqmi, 35% renter.
    c = CensusData(pct_5plus_units=5.0, renter_occupied_pct=35.0, pop_density_per_sqmi=2000)
    w = WalkData(walkscore=30)
    assert scoring.mps(c, w) < MPS_SKIP_THRESHOLD


def test_mps_weights_favor_5plus_over_renter():
    # Two tracts with same renter % but very different building stock should
    # produce very different MPS -- confirms renter% demotion worked.
    c_mf = CensusData(pct_5plus_units=80.0, renter_occupied_pct=50.0, pop_density_per_sqmi=10000)
    c_sfh = CensusData(pct_5plus_units=10.0, renter_occupied_pct=50.0, pop_density_per_sqmi=10000)
    w = WalkData(walkscore=60)
    assert scoring.mps(c_mf, w) - scoring.mps(c_sfh, w) >= 30


def test_market_fit_rent_tiers():
    # <$1000 floor -> 0 from rent, but MSA bonus still allowed.
    assert scoring.market_fit(CensusData(median_gross_rent=800), in_top25=False) == 0.0
    assert scoring.market_fit(CensusData(median_gross_rent=800), in_top25=True) == 25.0
    # $2500+ saturates rent component at 100.
    assert scoring.market_fit(CensusData(median_gross_rent=3000), in_top25=False) == 75.0
    assert scoring.market_fit(CensusData(median_gross_rent=3000), in_top25=True) == 100.0


def test_domain_signal():
    assert scoring.domain_signal("a@gmail.com") == 0.0
    assert scoring.domain_signal("a@bigreit.com") == 100.0
    assert scoring.domain_signal("no-at-sign") == 0.0


def test_timing_fresh_vs_stale():
    fresh = NewsArticle(
        title="X", url="u", published_at=datetime.now(timezone.utc) - timedelta(days=5),
        source="S",
    )
    stale = NewsArticle(
        title="Y", url="u", published_at=datetime.now(timezone.utc) - timedelta(days=60),
        source="S",
    )
    assert scoring.timing(NewsData(articles=[fresh])) > 90
    assert 30 < scoring.timing(NewsData(articles=[stale])) < 60
    assert scoring.timing(NewsData(articles=[])) == 0


def test_finalize_skipped_when_low_mps():
    lead = _lead()
    lead.census = CensusData(pct_5plus_units=3.0, renter_occupied_pct=25.0, median_gross_rent=1200)
    lead.walk = WalkData(walkscore=20)
    sub = scoring.compute_stage1(lead)
    scoring.finalize(lead, sub)
    assert lead.tier == "Skipped"
    assert lead.skipped_reason is not None
    assert "Low Multifamily Prob" in lead.skipped_reason


def test_finalize_tier_a_for_hot_lead():
    lead = _lead()
    lead.census = CensusData(
        pct_5plus_units=85.0, renter_occupied_pct=78.0,
        median_gross_rent=2800, pop_density_per_sqmi=25000,
    )
    lead.walk = WalkData(walkscore=90)
    lead.company = CompanyData(has_wikipedia=True)
    lead.news = NewsData(articles=[
        NewsArticle(
            title="BigREIT closes $200M fund",
            url="https://news.example/article",
            published_at=datetime.now(timezone.utc) - timedelta(days=7),
            source="Bloomberg",
        )
    ])
    sub = scoring.compute_stage1(lead)
    scoring.finalize(lead, sub)
    assert lead.tier == "A"
    assert lead.score is not None and lead.score >= 80


def test_classify_msa_maps_austin():
    msa, top = scoring.classify_msa("Austin")
    assert msa is not None and "Austin" in msa
    assert top is True


def test_classify_msa_unknown_city():
    msa, top = scoring.classify_msa("Boise")
    assert msa is None
    assert top is False
