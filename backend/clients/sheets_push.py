"""Push enriched leads from the web app into a Google Sheet via the
Apps Script `doPost` web-app endpoint (Path B).

Apps Script doPost can't read custom HTTP headers, so we sign the raw
body with HMAC-SHA256 and pass the hex digest as `?sig=...` — Apps
Script verifies the same way (see apps_script/Code.gs).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from ..config import settings


class SheetsPushError(RuntimeError):
    """Raised when the Apps Script web app rejects or fails the push."""


def _sign(body: bytes) -> str:
    return hmac.new(
        settings.webhook_shared_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


async def push_rows(
    header: list[str],
    rows: list[list[Any]],
    *,
    sheet_name: str = "Web App Output",
    timeout: float = 30.0,
) -> dict:
    """POST {header, rows, sheet_name} to the configured Apps Script URL.

    Returns the parsed JSON response on success: ``{"written": N, "sheet": "..."}``.
    Raises :class:`SheetsPushError` on any non-2xx, missing config, or
    JSON parse failure.
    """
    url = settings.apps_script_push_url
    if not url:
        raise SheetsPushError("APPS_SCRIPT_PUSH_URL is not configured")

    body = json.dumps(
        {"sheet_name": sheet_name, "header": header, "rows": rows},
        default=str,
    ).encode("utf-8")
    sig = _sign(body)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            params={"sig": sig},
            content=body,
            headers={"Content-Type": "application/json"},
            follow_redirects=True,  # Apps Script web apps redirect once
        )
    if resp.status_code >= 400:
        raise SheetsPushError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise SheetsPushError(f"non-JSON response: {resp.text[:200]}") from e
    if "error" in data:
        raise SheetsPushError(str(data["error"]))
    return data
