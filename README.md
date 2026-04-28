# EliseAI GTM Engineer — Inbound Lead Enrichment Tool

Automates the top-of-funnel SDR workflow for EliseAI: takes basic
inbound lead info, enriches via six public APIs, scores it for
multifamily-AI fit, and drafts a personalized outreach email — all
within free-tier limits.

Two SDR-facing surfaces share the same engine: a **Google Sheet
bridge** for SDRs already living in Sheets, and a **Next.js web app**
for everyone else.

## What it does

```
Sheets bridge                                   Web app
(SDR pastes a row)                              (login + form / CSV)
        │                                              │
        │ HMAC-signed                                  │ JWT-auth'd
        ▼                                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI backend                                                 │
│    3-stage funnel:                                               │
│      S1 — Census + WalkScore   (every lead)                      │
│      S2 — Wikipedia + NewsAPI  (only if S1 looks promising)      │
│      S3 — Gemini email draft   (only if score ≥ 70)              │
│    Postgres on Render: users · leads · daily quota counters      │
│    SQLite:   short-lived API response cache                      │
└──────────────────────────────────────────────────────────────────┘
        │                                              │
        ▼                                              ▼
Sheet rows updated:                              Web app shows:
Tier · Score · Why Now · Talking Point · Draft Email
```

## Deliverables

| Artifact | Path |
|---|---|
| Assumptions registry | [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) |
| Rollout plan | [`docs/ROLLOUT_PLAN.md`](docs/ROLLOUT_PLAN.md) |
| Backend engine | `backend/` (FastAPI + async enrichment) |
| Sheets integration | `apps_script/Code.gs` |
| Web app | `web/` (Next.js 16 + Auth.js v5 + shadcn/ui) |
| Sample input | `sample_data/leads_input.csv` (20 leads mixing ICP + non-ICP) |
| Tests | `backend/tests/` (58 pytests, no network calls) |

## Public APIs used and why

| API | Role | Free-tier constraint |
|---|---|---|
| **Census Geocoder** | Address → lat/lng + FIPS codes (state/county/tract) in one call | None — replaces Nominatim + downstream tract lookup |
| **Census ACS 5-year** | Housing-stock, renter %, median rent, population per tract | Generous; 30-day cache |
| **WalkScore** | Urban-context proxy for apartment density | 5,000/day |
| **Wikipedia** | Company scale proxy (notability ≈ enterprise size) | None |
| **NewsAPI** | Last-90-day trigger events (funding, M&A, launches) | **100/day — the binding constraint** |
| **Gemini 3.1 Flash Lite** | Email subject + body synthesis | **500 RPD / 15 RPM / 250k TPM** (free-tier) |

The assignment requires ≥ 2 APIs; this uses 6. The stack is deliberately
lightweight — one FastAPI service + Postgres on Render + Vercel for the
web app, all on free tiers.

## Quickstart (CLI — fastest demo, no Sheet or login required)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in API keys (all optional — tool degrades gracefully)

python -m backend.cli sample_data/leads_input.csv out.csv
```

The tool runs with any subset of keys. Missing keys produce a `skipped_reason`
on the relevant enrichment; the pipeline completes regardless.

## Quickstart (FastAPI server)

```bash
uvicorn backend.app:app --reload --port 8000

# health check
curl localhost:8000/health
```

Two auth schemes share the server:
- `/enrich/*` — HMAC-SHA256 over the raw body using `WEBHOOK_SHARED_SECRET` (Apps Script signs requests with `X-Signature`).
- `/api/v1/*` — short-lived HS256 JWT signed with `NEXTAUTH_SECRET` (the web app's BFF mints these per request).

## Quickstart (Google Sheet trigger)

1. Create a sheet with the header row described in `apps_script/Code.gs`.
2. Paste `Code.gs` + `appsscript.json` into the sheet's Apps Script editor.
3. Set `BACKEND_URL` to your deployed FastAPI URL.
4. Set `WEBHOOK_SECRET` via Project Settings → Script Properties (same value
   as `.env`'s `WEBHOOK_SHARED_SECRET`).
5. Run `installDailyTrigger()` once to register the 9 AM cron.
6. The `onEdit` trigger auto-fires when an SDR sets `Status=Ready` on a row.

## Quickstart (Web app)

```bash
cd web
cp .env.example .env.local   # fill in NEXTAUTH_SECRET, GOOGLE_*, ALLOWED_EMAILS, BACKEND_URL
npm install
npm run dev
```

Visit http://localhost:3000 → sign in with a Google account that's
listed in `ALLOWED_EMAILS`. The dashboard has three tabs:

- **New Lead** — form for one lead, result card with tier badge, sub-score bars, "Why Now", talking point, and a draft email with copy / edit / regenerate (with tone).
- **Bulk Upload** — drop a CSV, watch leads stream in via SSE, sort the results, export CSV or copy as TSV for paste-into-Sheets.
- **History** — paginated list of past enrichments scoped to your account; click any row to re-open the result card and regenerate.

## Running tests

```bash
pytest backend/tests/ -v
```

58 tests, fully offline (no network calls). Coverage:
- MPS weight behavior (dense multifamily vs. SFH suburban)
- Market-Fit rent tiers and MSA bonus
- News age decay (fresh vs. stale)
- Full-score tier assignment for known hot/cold lead profiles
- Quota budget guard: batch ceiling, realtime reserved pool, hard cap, upstream-429 self-heal
- Web-app JWT auth + email allowlist + per-user lead isolation
- Regenerate route: tone hint, Gemini-fail template fallback

## Implementation notes

- **Async throughout** — `httpx.AsyncClient` + `asyncio.gather` for
  parallel per-lead enrichment; `asyncio.Semaphore(10)` caps cross-lead
  concurrency.
- **Deterministic scoring** — all sub-scores are pure functions in
  `backend/scoring.py`. Gemini is only invoked for email drafting,
  never for scoring. This makes the logic auditable and testable
  without a mocked LLM.
- **Tone-aware regenerate fallback** — when Gemini quota is exhausted,
  `lead_brief.render_template_email(lead, tone)` rebuilds a casual /
  formal / default draft from a deterministic template so the user
  always sees a tone-correct draft, not a no-op.
- **Token-bucket RPM gate** — `backend/clients/gemini.py` enforces a
  6.5s minimum gap across concurrent tasks via `asyncio.Lock` (~9 RPM,
  giving headroom under Gemini's 10 RPM free-tier limit).
- **Upstream-429 self-heal** — if Gemini or NewsAPI returns 429 mid-batch,
  the local `daily_usage` counter is pinned to its hard cap so subsequent
  calls gate locally instead of burning more probe requests.
- **Postgres persistence on Render** — `users`, `leads`, and
  `daily_usage` route through Postgres when `DATABASE_URL` is set
  (mirrored by `backend/lead_store.py` + `backend/quota_store.py`)
  so user history and quota counters survive Render's free-dyno
  redeploys. Local dev falls back to SQLite automatically.
- **Short-lived API cache (SQLite)** — Census results cached 30 days,
  news cached 6 hours. SQLite is fine here because cache loss on
  redeploy is harmless (next call refetches).
- **Review Queue visibility** — when `MPS < 50` the row is still written
  back with `Tier=Skipped` and a human-readable reason; Apps Script
  shades the row grey. Silent drops would be a demo smell.
- **Census Geocoder over Nominatim** — single upstream call returns
  coordinates *and* FIPS codes needed for ACS. Saves an API hop and avoids
  Nominatim's 1 req/sec fair-use policy.
- **BFF pattern for the web app** — the browser never holds the backend
  JWT or `NEXTAUTH_SECRET`; Next.js route handlers under `/api/proxy/*`
  mint a 1-hour JWT per request and forward to FastAPI. SSE works
  through the proxy by piping the response stream straight through.
