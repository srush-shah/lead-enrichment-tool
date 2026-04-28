"""JWT session auth for the user-facing web app (Next.js -> FastAPI).

The Sheets webhook uses HMAC over the body and is unaffected. This module
provides a parallel auth scheme for browser-driven requests:

  Next.js issues an HS256 JWT signed with `NEXTAUTH_SECRET` containing
  the user's email. The frontend attaches it as `Authorization: Bearer
  <token>` on every /api/v1/* call. This dependency verifies the token,
  enforces the email allowlist, upserts the user row, and returns the
  internal user_id for handlers to scope queries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from . import lead_store
from .config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str


def _allowlist() -> Optional[frozenset[str]]:
    raw = settings.allowed_emails.strip()
    if not raw:
        return None  # open for local dev
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.nextauth_secret,
            algorithms=["HS256"],
            options={"require": ["email", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {e}")


def current_user(authorization: str = Header(default="")) -> CurrentUser:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_token(token)
    email = str(claims["email"]).strip().lower()

    allowed = _allowlist()
    if allowed is not None and email not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="email not allowed")

    user_id = lead_store.upsert_user(email)
    return CurrentUser(id=user_id, email=email)


CurrentUserDep = Depends(current_user)
