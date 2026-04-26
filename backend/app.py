"""FastAPI entrypoint. Exposes a single batch endpoint + health.

Auth: HMAC-SHA256 over the raw request body, using WEBHOOK_SHARED_SECRET.
Apps Script signs the request; this app verifies before doing any work.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import api_v1, cache, orchestrator
from .config import settings
from .models import BatchRequest, BatchResponse


app = FastAPI(title="EliseAI GTM Enrichment", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Vercel prod URL added once deployed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1.router)


@app.on_event("startup")
def _startup() -> None:
    cache.init_db()
    cache.prune_old()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "newsapi_used_today": cache.usage_today("newsapi"),
        "gemini_used_today": cache.usage_today("gemini"),
    }


def _verify(raw: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        settings.webhook_shared_secret.encode("utf-8"),
        raw,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/enrich/batch", response_model=BatchResponse)
async def enrich_batch(request: Request) -> BatchResponse:
    raw = await request.body()
    sig = request.headers.get("X-Signature")
    if not _verify(raw, sig):
        raise HTTPException(status_code=401, detail="invalid signature")
    req = BatchRequest.model_validate_json(raw)
    return await orchestrator.run_batch(req.leads, batch_mode=True)


@app.post("/enrich/realtime", response_model=BatchResponse)
async def enrich_realtime(request: Request) -> BatchResponse:
    """Same engine, different budget: uses the 15-call onEdit reserve."""
    raw = await request.body()
    sig = request.headers.get("X-Signature")
    if not _verify(raw, sig):
        raise HTTPException(status_code=401, detail="invalid signature")
    req = BatchRequest.model_validate_json(raw)
    return await orchestrator.run_batch(req.leads, batch_mode=False)
