"""Bearer JWT issue/decode for ``ws-d-auth`` (contracts §6).

HS256 with ``DMEF_AUTH_SECRET`` and a 12 h expiry. Env is read through
``services/config.py`` helpers only (contracts §7); a missing secret raises
``RuntimeError`` with a clear message at startup/test time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from services.config import get_setting

TOKEN_TTL = timedelta(hours=12)
ALGORITHM = "HS256"


def auth_secret() -> str:
    """Return the configured JWT secret or raise with a clear message."""
    secret = get_setting("dmef.auth_secret", "")
    if not secret or not str(secret).strip():
        raise RuntimeError(
            "DMEF_AUTH_SECRET is not set. Set it in the environment (or .env) "
            "before starting the backend or running auth tests."
        )
    return str(secret)


def issue(user: dict[str, Any]) -> str:
    """Issue a signed JWT for an authenticated user row/dict."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, auth_secret(), algorithm=ALGORITHM)


def decode(token: str) -> dict[str, Any]:
    """Decode and verify ``token``; raises ``jwt.PyJWTError`` when invalid.

    ``sub`` and ``exp`` are required claims: tokens missing either (or that
    are expired, malformed, or wrongly signed) raise a ``PyJWTError``
    subclass so callers map them to 401 instead of 500.
    """
    payload = jwt.decode(
        token, auth_secret(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
    )
    try:
        sub = payload["sub"]
        exp = payload["exp"]
    except KeyError as exc:
        raise jwt.InvalidTokenError(f"Missing required claim: {exc}") from exc
    return {
        "sub": sub,
        "email": payload.get("email", ""),
        "role": payload.get("role", ""),
        "exp": exp,
    }
