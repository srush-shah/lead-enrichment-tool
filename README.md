# EliseAI GTM Engineer — Inbound Lead Enrichment Tool

Automates the top-of-funnel SDR workflow for EliseAI: takes basic inbound
lead info, enriches via five public APIs, scores for multifamily-AI fit,
and drafts a personalized outreach email — all within free-tier limits.

## What it does

```
Google Sheet (SDR pastes lead)   ┌───────────────────────────────┐
  │                              │ FastAPI backend               │
  │  onEdit  -OR-  9 AM cron  ───▶│   ┌────────────────────────┐ │
  │                              │   │ 3-stage enrichment     │ │
  │                              │   │  S1: Census + WalkScore│ │
  │                              │   │  S2: Wiki + News       │ │
  │                              │   │  S3: Gemini email      │ │
  │                              │   └────────────────────────┘ │
  │  <-- Tier, Score, Why-Now,   │                              │
  │      Talking Point, Email    │                              │
  └──────────────────────────────┴───────────────────────────────┘
```

## Deliverables

| Artifact | Path |
|---|---|
| Assumptions registry | [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) |
| Rollout plan | [`docs/ROLLOUT_PLAN.md`](docs/ROLLOUT_PLAN.md) |
| Backend engine | `backend/` (FastAPI + async enrichment + SQLite cache) |
| Sheets integration | `apps_script/Code.gs` |
| Sample input | `sample_data/leads_input.csv` (20 leads mixing ICP + non-ICP) |
| Tests | `backend/tests/` (pytest, no network) |

## Public APIs used and why

| API | Role | Free-tier constraint |
|---|---|---|
| **Census Geocoder** | Address → lat/lng + FIPS codes (state/county/tract) in one call | None — replaces Nominatim + downstream tract lookup |
| **Census ACS 5-year** | Housing-stock, renter %, median rent, population per tract | Generous; 30-day cache |
| **WalkScore** | Urban-context proxy for apartment density | 5,000/day |
| **Wikipedia** | Company scale proxy (notability ≈ enterprise size) | None |
| **NewsAPI** | Last-90-day trigger events (funding, M&A, launches) | **100/day — the binding constraint** |
| **Gemini 1.5 Flash** | Email subject + body synthesis | **15 RPM / 1,500 RPD** |

The assignment requires ≥ 2 APIs; this uses 6. The stack is deliberately
lightweight — no infra beyond a single FastAPI service + SQLite.

## Quickstart (CLI — no Sheets required for demo)

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

The server signs incoming requests with HMAC-SHA256 over the body using
`WEBHOOK_SHARED_SECRET`. Apps Script attaches `X-Signature` with the same
secret.

## Quickstart (Google Sheet trigger)

1. Create a sheet with the header row described in `apps_script/Code.gs`.
2. Paste `Code.gs` + `appsscript.json` into the sheet's Apps Script editor.
3. Set `BACKEND_URL` to your deployed FastAPI URL.
4. Set `WEBHOOK_SECRET` via Project Settings → Script Properties (same value
   as `.env`'s `WEBHOOK_SHARED_SECRET`).
5. Run `installDailyTrigger()` once to register the 9 AM cron.
6. The `onEdit` trigger auto-fires when an SDR sets `Status=Ready` on a row.

### Optional: web-app push-to-sheet (Step 8)

The web app can push enriched rows back into the same spreadsheet via
the `doPost` handler in `Code.gs`. To enable it:

1. In Apps Script editor: Deploy → New deployment → type **Web app**.
   Execute as: **Me**. Who has access: **Anyone with the link**.
2. Copy the resulting `https://script.google.com/macros/s/.../exec` URL.
3. Set `APPS_SCRIPT_PUSH_URL` on the FastAPI backend env (Render or
   `.env`).
4. (Optional) Set `NEXT_PUBLIC_PILOT_SHEET_URL` on Vercel to the sheet's
   public URL — the post-push toast offers a one-click "Open sheet"
   link.
5. The handler verifies HMAC-SHA256 over the raw body using the same
   `WEBHOOK_SHARED_SECRET`; signature is passed as `?sig=...` because
   Apps Script `doPost` can't read custom headers.
6. Rows land on a `Web App Output` tab (auto-created on first push) so
   the SDR's primary `Leads` tab stays clean.

## Running tests

```bash
pytest backend/tests/ -v
```

Tests are fully offline (no network calls) and cover:
- MPS weight behavior (dense multifamily vs. SFH suburban)
- Market-Fit rent tiers and MSA bonus
- News age decay (fresh vs. stale)
- Full-score tier assignment for known hot/cold lead profiles
- Quota budget guard: batch ceiling, realtime reserved pool, hard cap

## Implementation notes

- **Async throughout** — `httpx.AsyncClient` + `asyncio.gather` for
  parallel per-lead enrichment; `asyncio.Semaphore(10)` caps cross-lead
  concurrency.
- **Deterministic scoring** — all sub-scores are pure functions in
  `backend/scoring.py`. Gemini is only invoked for email drafting, never
  for scoring. This makes the logic auditable and testable without a
  mocked LLM.
- **Token-bucket RPM gate** — `backend/clients/gemini.py` enforces a
  global 4.5s minimum gap across concurrent tasks via `asyncio.Lock`.
- **SQLite cache + daily_usage table** — cache reuses stable data (ZIP-level
  Census results last 30 days; news last 6 hours). The `daily_usage` table
  implements the 85/15 batch/realtime split with lazy midnight reset
  (rows keyed by `(api, today())`).
- **Review Queue visibility** — when `MPS < 50` the row is still written
  back with `Tier=Skipped` and a human-readable reason; Apps Script shades
  the row grey. This is intentional — silent drops are a demo smell.
- **Census Geocoder over Nominatim** — single upstream call returns
  coordinates *and* FIPS codes needed for ACS. Saves an API hop and avoids
  Nominatim's 1 req/sec fair-use policy.

