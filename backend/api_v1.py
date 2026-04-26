"""User-facing API for the Next.js web app.

Sits alongside the Sheets HMAC webhook (no overlap). All routes require
a NextAuth-issued JWT (see backend/auth.py). Lead history is scoped per
authenticated user.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from . import cache, orchestrator
from .auth import CurrentUser, CurrentUserDep
from .models import BatchRequest, EnrichedLead, LeadInput


router = APIRouter(prefix="/api/v1", tags=["webapp"])


def _lead_hash(lead: LeadInput) -> str:
    canonical = "|".join([
        lead.email.strip().lower(),
        lead.company.strip().lower(),
        lead.property_address.strip().lower(),
        lead.city.strip().lower(),
        lead.state.strip().lower(),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _persist(user: CurrentUser, enriched: EnrichedLead) -> int:
    return cache.save_lead(
        user_id=user.id,
        lead_hash=_lead_hash(enriched.input),
        payload_json=enriched.model_dump_json(),
        tier=enriched.tier,
        score=enriched.score,
    )


@router.post("/enrich", response_model=EnrichedLead)
async def enrich_one(lead: LeadInput, user: CurrentUser = CurrentUserDep) -> EnrichedLead:
    result = await orchestrator.run_batch([lead], batch_mode=False)
    enriched = result.leads[0]
    _persist(user, enriched)
    return enriched


@router.post("/enrich/stream")
async def enrich_stream(req: BatchRequest, user: CurrentUser = CurrentUserDep) -> StreamingResponse:
    async def event_source():
        async for enriched in orchestrator.iter_batch(req.leads, batch_mode=True):
            _persist(user, enriched)
            payload = enriched.model_dump_json()
            yield f"event: lead\ndata: {payload}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/leads")
async def list_leads(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = CurrentUserDep,
) -> dict:
    rows, total = cache.list_leads(user.id, limit=limit, offset=offset)
    summaries = [
        {
            "id": r["id"],
            "tier": r["tier"],
            "score": r["score"],
            "created_at": r["created_at"],
            "input": json.loads(r["payload"])["input"],
        }
        for r in rows
    ]
    return {"leads": summaries, "total": total, "limit": limit, "offset": offset}


@router.get("/leads/{lead_id}", response_model=EnrichedLead)
async def get_lead(lead_id: int, user: CurrentUser = CurrentUserDep) -> EnrichedLead:
    row = cache.get_lead(user.id, lead_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")
    return EnrichedLead.model_validate_json(row["payload"])


@router.get("/me")
async def me(user: CurrentUser = CurrentUserDep) -> dict:
    return {"id": user.id, "email": user.email}
