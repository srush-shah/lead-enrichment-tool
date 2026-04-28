# Commercial Assumptions Registry

Every line of scoring logic in this tool rests on one or more of the seven
assumptions below. Each is testable post-pilot against closed-won data.

| # | Assumption | Signal Source | Directional Impact | Confidence | Risk if Wrong |
|---|---|---|---|---|---|
| **A1** | Dense rental markets = AI leasing ROI. High renter % + population density → high inquiry volume per property → EliseAI's automation value scales linearly. | Census B25003 (renter-occupied %), B01003 (density) | +Market Fit sub-score | High | SFH/low-density leads over-rated → mitigated by MPS gate (see A7) |
| **A2** | Corporate email domain = institutional owner with SaaS budget. `@company.com` implies a professional org; free-mail (`@gmail.com`, `@yahoo.com`, etc.) correlates with mom-and-pop landlords outside ICP. | Email regex match against free-mail allowlist | +Domain Signal; auto-downgrade for free-mail | High | Penalizes small-but-professional operators → domain penalty is additive (−), never disqualifying |
| **A3** | Median rent > $1,500 = pricing headroom for SaaS ACV. EliseAI's per-unit pricing only pencils above a rent floor; sub-$1,000 MSAs have thin op margins. | Census B25064 (median gross rent) | Market Fit rent sub-score (0-100) | Medium | Underweights cost-efficient Midwest markets → floor is 0 (not negative); MSA bonus can offset |
| **A4** | News velocity in last 90 days = active buying window. Funding, M&A, new-property launches, senior hires signal organizational motion and budget availability. | NewsAPI (90-day window, dedupe by URL) | +Timing sub-score, decays with article age | Medium-High | Irrelevant news boosts score → demo Gemini sentiment filter is planned for v1.1 |
| **A5** | Wikipedia presence ≈ scale threshold (~$50M rev / 5k+ units). The bar for a company Wikipedia page correlates with enterprise scale — EliseAI's sweet spot. | Wikipedia/Wikidata query | +Company Fit (+50 pts flat) | Medium | Private mid-market operators lack pages → signal is additive only, never penalizing |
| **A6** | Top-25 multifamily MSA = shorter sales cycle. NMHC-defined top metros have the highest density of EliseAI reference customers, reducing perceived risk for new buyers. | Static NMHC 50 apartment markets list (top 25) | +Geographic sub-score | Medium | Biases against emerging markets → Geographic weight capped at 15% of full score |
| **A7** | Walkable + dense tract = apartment-scale inventory, not SFH rentals. ACS B25024 "Units in Structure" directly identifies 5+ unit buildings; WalkScore adds urban-context confirmation. | Census B25024 + WalkScore API | Drives Multifamily Probability Score (MPS) — the hard gate | High | Pre-war brownstone SFH gets over-scored → B25024 dominates MPS (50% weight), which mitigates |

---

## Multifamily Probability Score (MPS)

**Formula:**

```
MPS = (0.50 × P5plus) + (0.25 × WalkScoreNorm) + (0.15 × DensityNorm) + (0.10 × RenterPct)

  P5plus        = % housing units in 5+ unit buildings   [Census B25024, summed 006-009]
  WalkScoreNorm = WalkScore value (0-100)                [WalkScore API; neutral 50 if missing]
  DensityNorm   = min(pop_per_sqmi / 15000, 1.0) × 100   [capped so NYC and dense Dallas both saturate]
  RenterPct     = % renter-occupied households           [Census B25003]
```

**Weight rationale:**
- 50% on P5+ — the *direct* signal; everything else is a proxy.
- 25% on WalkScore — independent confirmation; catches new-build corridors Census lags on.
- 15% on Density — sanity check; capped to avoid NYC-only bias.
- 10% on Renter% — deliberately demoted; polluted by renter-occupied SFH. Tiebreaker only.

**MPS gate:**
| MPS | Interpretation | Action |
|---|---|---|
| **≥ 50** | Multifamily territory | Proceed to S2/S3 enrichment |
| **< 50** | Likely SFH / suburban duplex | Visible "Review Queue" — row tagged `Tier=Skipped`, `Reason=Low Multifamily Prob (MPS: X)` |

Low-MPS rows are still written back to the sheet with their S1 data so reps can
audit the filter; nothing is silently dropped.

---

## 3-Stage Enrichment Funnel

| Stage | Applies to | APIs called per lead | Gating rule |
|---|---|---|---|
| **S1 — Foundation** | All 50 | Census Geocoder · Census ACS · WalkScore · email-domain parse | Always run |
| **S2 — Context** | Pre-Score ≥ 50 **AND** corporate domain | Wikipedia · NewsAPI | After S1 |
| **S3 — Synthesis** | Full Score ≥ 70 | Gemini 1.5 Flash (JSON subject + body) | After S2 |

**Pre-Score = 0.60 × MPS + 0.25 × MarketFit + 0.15 × DomainSignal**
(Used as the S2 gate only — not the final customer-facing score.)

**Full Score = 0.35 × MarketFit + 0.30 × CompanyFit + 0.20 × Timing + 0.15 × Geographic**
(0–100 number shown to reps.)

**Tier mapping:**
| Tier | Score | Action |
|---|---|---|
| A | ≥ 80 | Gemini email generated; priority queue |
| B | 60–79 | Gemini email generated; standard queue |
| C | 40–59 | Brief only, no email |
| D | < 40 | Brief only, no email |
| Skipped | MPS < 50 | Review queue (visible, greyed row) |

---

## Free-Tier Budget Compliance (50-lead batch)

| Resource | Free cap | Worst-case batch use | Reserved for onEdit | Headroom |
|---|---|---|---|---|
| NewsAPI | 100/day | 30 (S2 only, ~30 leads clear gate) | 15 | 55% buffer |
| Gemini 1.5 Flash RPM | 15/min | Paced at 4.5s gap → ~13 RPM | — | 13% buffer |
| Gemini 1.5 Flash RPD | 1,500/day | ~18 (S3 leads × 1 call for email) | 200 | 98% buffer |
| WalkScore | 5,000/day | 50 | — | negligible |
| Census ACS | generous + 30d cache | ~20 uncached | — | negligible |
| Census Geocoder | no official cap | 50 | — | negligible |

**Fail-soft behavior:** when a quota is exhausted mid-batch, the offending
enrichment is skipped (with a `skipped_reason` surfaced to the sheet), the
"Why Now" automatically falls back to a Market-Fit anchor, and the batch
continues. No hard failures.

---

## The "Why Now" Fallback Chain

Every Tier A/B lead is guaranteed a non-empty "Why Now". Priority order:

1. **News trigger** (fresh, ≤ 90 days): `Trigger: {Company} — "{headline}" ({N days ago}, {source}) (ZIP {zip}).`
2. **Market-Fit anchor**: `Market Insight: {ZIP} has {renter%}% renter density and ${median_rent} median rent — top-decile automation ROI territory for EliseAI.`
3. **Company fallback**: `Company Note: {first sentence of Wikipedia summary}.`
4. **None** (rare): `No fresh trigger found — treat as cold outreach.`

---

## Deployment / Access Assumptions (assessment scope)

The seven scoring assumptions above are the commercial bets. The five
below are scope decisions for the take-home itself — demo-scoped, not
production-grade, but each is structured so the path to a real
multi-tenant deploy is config + a sign-up flow, not a rewrite.

| # | Assumption | Why this is OK for v1 | What changes in production |
|---|---|---|---|
| **D1** | **Single demo user** during the assessment. | Reviewers need a frictionless login, not a tenancy story. | `users` and `leads` tables are already `user_id`-keyed (`idx_leads_user_created`, `idx_leads_user_hash`); a real deploy adds sign-up + invite flows on top. |
| **D2** | **Google OAuth + email allowlist** (`ALLOWED_EMAILS`) gates both the Auth.js `signIn` callback and the backend JWT verifier — belt and suspenders. | Prevents random Google accounts from burning the demo's free-tier quota. Reviewers see an "unverified app" interstitial because the OAuth consent screen stays in Testing mode. | Publish the OAuth consent screen; replace the allowlist with an org-domain check or SSO. |
| **D3** | **Per-user private history** in the web app — no team views, no sharing. | One demo user means there's nothing to share. | Add a `team_id` column or row-level visibility rules; UI gets a "shared by" filter. |
| **D4** | **CSV / TSV export is the v1 writeback path** from the web app; Sheets writeback is queued as Step 8 (Path B: HMAC-signed Apps Script `doPost` → dedicated `Web App Output` tab). | Lets the web app ship even if the Apps Script side isn't redeployed. The pilot SDRs already on Sheets keep using `onEdit` — no collision with web-app users. | Step 8 lands; "Push to Sheet" button writes to a separate tab so the pilot's `Leads` tab stays clean. |
| **D5** | **Frontend has no automated tests.** Backend has 36 covering the engine, scoring, quota, and auth. | A manual smoke pass before recording covers the demo path; doubling the frontend budget for marginal demo value didn't pencil. | Vitest + Playwright before the first real customer — smoke tests for the BFF route handlers (auth, JWT minting, SSE proxy) take priority. |
