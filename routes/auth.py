"""Auth routes. Implemented by ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from database.db import get_connection
from services.auth.dependencies import CurrentUser, get_current_user
from services.auth.passwords import validate_password
from services.auth.service import authenticate, set_password
from services.auth.tokens import issue

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory per-IP rate limiting for login: at most 10 attempts per 60 s.
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW_SECONDS = 60.0


class LoginPayload(BaseModel):
    email: str
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str


def _check_login_rate_limit(client_host: str) -> None:
    now = time.monotonic()
    attempts = [at for at in _LOGIN_ATTEMPTS[client_host] if now - at < LOGIN_RATE_WINDOW_SECONDS]
    if len(attempts) >= LOGIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    attempts.append(now)
    _LOGIN_ATTEMPTS[client_host] = attempts


def _audit_login(email: str, *, success: bool) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (
                None,
                "login_success" if success else "login_failure",
                json.dumps({"email": email.strip().lower()}),
            ),
        )


def _public_user_payload(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


@router.post("/login")
def login(payload: LoginPayload, request: Request) -> dict:
    """Authenticate with email/password and return a bearer JWT."""
    host = request.client.host if request.client else "unknown"
    _check_login_rate_limit(host)
    user = authenticate(payload.email, payload.password)
    if user is None:
        _audit_login(payload.email, success=False)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _audit_login(payload.email, success=True)
    return {"token": issue(user), "user": _public_user_payload(user)}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Return the current authenticated user."""
    return user.to_dict()


@router.post("/logout")
def logout(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Server-side no-op; the frontend clears the ``dmef_session`` cookie."""
    return {"status": "ok"}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordPayload, user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Change the current user's password after verifying the current one."""
    current = authenticate(user.email, payload.current_password)
    if current is None:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_password(user.id, payload.new_password)
    return {"status": "ok"}
