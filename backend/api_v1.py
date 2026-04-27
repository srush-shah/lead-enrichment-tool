"""User-facing API for the Next.js web app.

Sits alongside the Sheets HMAC webhook (no overlap). All routes require
a NextAuth-issued JWT (see backend/auth.py). Lead history is scoped per
authenticated user.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import cache, lead_brief, orchestrator
from .auth import CurrentUser, CurrentUserDep
from .models import BatchRequest, EnrichedLead, LeadInput
from .quota import QuotaExhausted


class RegenerateRequest(BaseModel):
    tone: Optional[Literal["casual", "formal"]] = None


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


@router.post("/leads/{lead_id}/regenerate", response_model=EnrichedLead)
async def regenerate_email(
    lead_id: int,
    response: Response,
    req: RegenerateRequest = RegenerateRequest(),
    user: CurrentUser = CurrentUserDep,
) -> EnrichedLead:
    """Re-run the Gemini email draft only — keeps every other field on the
    stored lead intact. Optional tone hint biases the prompt.

    If Gemini quota is exhausted, fall back to local string-replacement
    tone shifts on the existing draft. Sets `X-Tone-Source: template`
    so the caller can tell apart Gemini-fresh vs template-shifted output.
    """
    row = cache.get_lead(user.id, lead_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")

    enriched = EnrichedLead.model_validate_json(row["payload"])
    response.headers["X-Tone-Source"] = "gemini"
    async with httpx.AsyncClient(headers={"User-Agent": "EliseAI-GTM-Tool/1.0"}) as client:
        try:
            await lead_brief.draft_email(
                client, enriched, batch_mode=False, tone=req.tone, skip_cache=True,
            )
        except QuotaExhausted:
            subject, body = lead_brief.apply_tone_template(
                enriched.draft_email_subject or "",
                enriched.draft_email_body or "",
                req.tone,
            )
            enriched.draft_email_subject = subject
            enriched.draft_email_body = body
            response.headers["X-Tone-Source"] = "template"

    cache.update_lead(
        lead_id=lead_id,
        user_id=user.id,
        payload_json=enriched.model_dump_json(),
        tier=enriched.tier,
        score=enriched.score,
    )
    return enriched


@router.get("/me")
async def me(user: CurrentUser = CurrentUserDep) -> dict:
    return {"id": user.id, "email": user.email}
