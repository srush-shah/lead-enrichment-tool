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

from . import cache, cli, lead_brief, orchestrator
from .auth import CurrentUser, CurrentUserDep
from .clients import sheets_push
from .models import BatchRequest, EnrichedLead, LeadInput
from .quota import QuotaExhausted


class RegenerateRequest(BaseModel):
    tone: Optional[Literal["casual", "formal"]] = None


class PushToSheetRequest(BaseModel):
    lead_ids: list[int]
    sheet_name: Optional[str] = None  # default "Web App Output" lives in sheets_push


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


def _enriched_with_id(enriched: EnrichedLead, lead_id: int) -> dict:
    """Serialize an EnrichedLead to JSON-safe dict with the cache id attached.
    Used by the streaming + single endpoints so the frontend can push the
    lead to Sheets without a second round-trip to look up the id."""
    data = enriched.model_dump(mode="json")
    data["id"] = lead_id
    return data


@router.post("/enrich")
async def enrich_one(lead: LeadInput, user: CurrentUser = CurrentUserDep) -> dict:
    result = await orchestrator.run_batch([lead], batch_mode=False)
    enriched = result.leads[0]
    lead_id = _persist(user, enriched)
    return _enriched_with_id(enriched, lead_id)


@router.post("/enrich/stream")
async def enrich_stream(req: BatchRequest, user: CurrentUser = CurrentUserDep) -> StreamingResponse:
    async def event_source():
        async for enriched in orchestrator.iter_batch(req.leads, batch_mode=True):
            lead_id = _persist(user, enriched)
            payload = json.dumps(_enriched_with_id(enriched, lead_id))
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


@router.post("/leads/push-to-sheet")
async def push_to_sheet(
    req: PushToSheetRequest,
    user: CurrentUser = CurrentUserDep,
) -> dict:
    """Append the user's selected enriched leads to the configured Apps
    Script-fronted Google Sheet.

    Lead IDs that don't belong to the current user are silently skipped
    (mirrors the 404 behavior of GET /leads/{id}). Column order matches
    the CLI's CSV output so a Sheets row reads the same as a CSV row.
    """
    if not req.lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids is empty")

    rows: list[list] = []
    skipped: list[int] = []
    for lead_id in req.lead_ids:
        row = cache.get_lead(user.id, lead_id)
        if row is None:
            skipped.append(lead_id)
            continue
        enriched = EnrichedLead.model_validate_json(row["payload"])
        flat = cli._row_for(enriched)
        rows.append([flat.get(col) for col in cli.COLUMNS])

    if not rows:
        raise HTTPException(status_code=404, detail="no leads found for current user")

    try:
        result = await sheets_push.push_rows(
            header=list(cli.COLUMNS),
            rows=rows,
            sheet_name=req.sheet_name or "Web App Output",
        )
    except sheets_push.SheetsPushError as e:
        raise HTTPException(status_code=502, detail=f"sheets push failed: {e}") from e

    return {
        "written": result.get("written", len(rows)),
        "sheet": result.get("sheet"),
        "skipped": skipped,
    }


@router.get("/me")
async def me(user: CurrentUser = CurrentUserDep) -> dict:
    return {"id": user.id, "email": user.email}
