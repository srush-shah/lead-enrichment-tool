"""CLI runner for local demo: CSV in -> enriched CSV out.

Usage:
    python -m backend.cli sample_data/leads_input.csv out.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from . import orchestrator
from .models import EnrichedLead, LeadInput


COLUMNS = [
    "name", "email", "company", "property_address", "city", "state", "country",
    "tier", "score", "mps", "pre_score", "market_fit", "company_fit", "timing", "geographic",
    "msa", "in_top25_msa", "corporate_domain",
    "skipped_reason",
    "why_now", "why_now_source", "talking_point", "objection_preempt",
    "draft_email_subject", "draft_email_body",
    "renter_pct", "pct_5plus_units", "median_gross_rent", "walkscore",
    "population", "zip_code",
    "has_wikipedia", "news_article_count", "news_skipped_reason",
    "evidence_links",
]


def read_leads(path: Path) -> list[LeadInput]:
    fields = ("name", "email", "company", "property_address", "city", "state", "country")
    out: list[LeadInput] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = {k: (row.get(k) or "").strip() for k in fields}
            if not vals["country"]:
                vals["country"] = "USA"
            out.append(LeadInput(**vals))
    return out


def _row_for(lead: EnrichedLead) -> dict:
    sub = lead.sub_scores
    brief = lead.brief
    return {
        "name": lead.input.name,
        "email": lead.input.email,
        "company": lead.input.company,
        "property_address": lead.input.property_address,
        "city": lead.input.city,
        "state": lead.input.state,
        "country": lead.input.country,
        "tier": lead.tier,
        "score": lead.score,
        "mps": sub.mps if sub else None,
        "pre_score": sub.pre_score if sub else None,
        "market_fit": sub.market_fit if sub else None,
        "company_fit": sub.company_fit if sub else None,
        "timing": sub.timing if sub else None,
        "geographic": sub.geographic if sub else None,
        "msa": lead.msa,
        "in_top25_msa": lead.in_top25_msa,
        "corporate_domain": lead.corporate_domain,
        "skipped_reason": lead.skipped_reason,
        "why_now": brief.why_now if brief else None,
        "why_now_source": brief.why_now_source if brief else None,
        "talking_point": brief.talking_point if brief else None,
        "objection_preempt": brief.objection_preempt if brief else None,
        "draft_email_subject": lead.draft_email_subject,
        "draft_email_body": lead.draft_email_body,
        "renter_pct": lead.census.renter_occupied_pct,
        "pct_5plus_units": lead.census.pct_5plus_units,
        "median_gross_rent": lead.census.median_gross_rent,
        "walkscore": lead.walk.walkscore,
        "population": lead.census.population,
        "zip_code": lead.geo.zip_code,
        "has_wikipedia": lead.company.has_wikipedia,
        "news_article_count": len(lead.news.articles),
        "news_skipped_reason": lead.news.skipped_reason,
        "evidence_links": " | ".join(brief.evidence_links) if brief else "",
    }


def write_output(path: Path, leads: list[EnrichedLead]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for lead in leads:
            w.writerow(_row_for(lead))


async def _main(input_csv: Path, output_csv: Path) -> None:
    leads = read_leads(input_csv)
    if not leads:
        print("No leads found in input.", file=sys.stderr)
        sys.exit(1)
    print(f"Processing {len(leads)} lead(s)...", file=sys.stderr)
    result = await orchestrator.run_batch(leads, batch_mode=True)
    write_output(output_csv, result.leads)

    s = result.summary
    print(
        f"\nDone in {s.wall_time_seconds}s | "
        f"A={s.tier_a} B={s.tier_b} C={s.tier_c} D={s.tier_d} Skipped={s.skipped} | "
        f"News {s.news_calls_used}/{s.news_calls_cap} | "
        f"Gemini {s.gemini_calls_used} | "
        f"Fallbacks {s.fallbacks_used}",
        file=sys.stderr,
    )
    print(f"Output written to {output_csv}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="EliseAI GTM lead enrichment CLI")
    ap.add_argument("input_csv", type=Path)
    ap.add_argument("output_csv", type=Path)
    args = ap.parse_args()
    asyncio.run(_main(args.input_csv, args.output_csv))


if __name__ == "__main__":
    main()
