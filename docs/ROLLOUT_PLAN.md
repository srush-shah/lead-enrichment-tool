# Rollout Plan — Sales Org Deployment

## Two-Surface Architecture

Same scoring engine, two SDR-facing surfaces — chosen so the rollout
doesn't disrupt anyone already living in Google Sheets:

| Surface | Who uses it | Phase |
|---|---|---|
| **Sheets bridge** — Apps Script `onEdit` → `/enrich/realtime` + nightly `/enrich/batch` | Pilot SDRs already running their pipeline in a shared sheet | Phase 1 (pilot, weeks 5–8) |
| **Web app** — Next.js + Google OAuth, single-lead form + bulk CSV + history + per-lead regenerate | New SDRs, managers, anyone outside the pilot sheet | Phase 2 (org rollout, week 9+) |

Both surfaces hit the same FastAPI backend (`/enrich/*` HMAC routes for
Apps Script, `/api/v1/*` JWT routes for the web app). Same scoring
weights, same "Why Now" fallback chain, same `daily_usage` quota
counters — adding the web app didn't fork any business logic, and
SDRs on the Sheets bridge keep their workflow untouched. The web app
exports CSV/TSV today, which is enough overlap with Sheets for managers
to roll up data; if the org later wants direct Sheets writeback from
the web app, that's a small additive step on top of the existing
Apps Script bridge.

---

## Stakeholders & Roles

| Role | Why involved |
|---|---|
| **VP Sales** | Executive sponsor; sets success metrics (reply-rate lift, time-to-first-touch) |
| **SDR Manager** | Day-to-day product owner; nominates pilot reps; owns SDR feedback loop |
| **Design-partner SDRs (2)** | Real users during pilot; surface friction and false positives |
| **RevOps** | Lead data hygiene (input quality); CRM integration in phase 3 |
| **Marketing** | ICP alignment; ensure scoring mirrors MQL definition |
| **IT / Security** | API-key vaulting; data-handling review (Census/Wikipedia/News all public; Gemini is outbound) |
| **Eng** | Long-term infra ownership (Render → internal hosting migration) |

---

## Success Metrics (defined upfront)

| Metric | Baseline | Target |
|---|---|---|
| Time per lead (research + draft) | ~15 min | ≤ 2 min |
| Reply rate — AI-drafted vs. SDR-drafted | existing reply rate | +20% (or non-inferior with time savings) |
| SQL conversion on Tier-A leads | unscored baseline | +15% |
| SDR satisfaction (post-pilot survey) | n/a | NPS ≥ 40 |
| Score-outcome agreement (Cohen's κ vs. SDR judgment, 50-lead manual review) | n/a | ≥ 0.6 |

---

## Testing the MVP

1. **Unit tests** — `backend/tests/test_scoring.py` + `test_quota.py` cover pure logic, no network. Run in CI on every commit.
2. **Backtest** — run scorer over last 90 days of inbound leads; correlate score vs. actual SQL/closed-won. Tune weights if κ < 0.5.
3. **Side-by-side blind review** — 1 senior SDR scores 50 recent leads cold; tool scores the same 50; measure agreement.
4. **Email quality pass** — sales leader reviews 30 generated emails for tone/accuracy before pilot.
5. **Load test** — 500 leads in one batch; confirm <10 min wall time and zero free-tier breaches (watch `cache.daily_usage` table).
6. **Degradation drill** — deliberately set NewsAPI key to invalid value; confirm batch completes with market-fit fallback on every lead.

---

## Phased Rollout (10-week plan)

| Week | Phase | Deliverable |
|---|---|---|
| **1** | Discovery | Stakeholder interviews, ICP doc, metric baseline |
| **2–3** | Build | Backend + Sheet integration; dogfood CSV with 20 sample leads |
| **4** | Internal QA | Backtest + side-by-side; tune weights |
| **5** | Dogfood | SDR Manager runs daily on real inbound for 1 week |
| **6–7** | **Pilot (Phase 1: Sheets)** | 2 SDRs use the Sheets bridge live; 2 control SDRs continue manual; measure reply-rate delta |
| **8** | Iterate | Scoring/email refinements from pilot feedback; web app QA on staging |
| **9** | **Org rollout (Phase 2: web app)** | New SDRs + managers onboard via the web app; pilot SDRs stay on the Sheets bridge they already trust. 30-min training + Loom walkthrough; office hours |
| **10+** | Optimize & extend | Weekly metrics review; Salesforce/HubSpot trigger integration; multi-touch follow-up sequences |

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Score wrong → reps chase bad leads | Brief shows *why* score was assigned; SDR can override; weekly weight tuning |
| Generic-feeling emails | Assist ≠ autopilot — all emails require SDR review before send; track edit distance as quality proxy |
| NewsAPI outage mid-batch | `quota_reserved_for_realtime` / `api_error` handling → fall back to Market-Fit anchor; batch continues |
| Free-tier rate limit surprises | SQLite `daily_usage` counter with 85/15 batch/realtime split; Gemini 4.5s token bucket |
| Address-parse failures | Census Geocoder returns empty → MPS defaults cause soft-Skip with clear reason; row enters review queue |
| Prompt injection via news content | Articles feed Gemini via structured JSON context; system prompt explicitly sets role and output format |

---

## Post-Rollout Roadmap

1. **CRM trigger** — replace Sheets with Salesforce/HubSpot webhook; same engine.
2. **Multi-touch sequences** — Gemini drafts 3-touch cadence, not just intro.
3. **Account rollup** — one company → multiple buildings → account-level score.
4. **Slack alerts** — Tier-A leads post to `#sales-hot-inbound` channel.
5. **Closed-loop learning** — feed SQL/closed-won outcomes back as weight tuning signal.
