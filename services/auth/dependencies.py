"""Auth FastAPI dependencies. Implemented by ``ws-d-auth``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException


def get_current_user() -> dict[str, Any]:
    """Return the authenticated user from the bearer JWT. Stub owned by ws-d."""
    raise HTTPException(status_code=501, detail="Not implemented (ws-d-auth)")


def require_role(*roles: str) -> Callable[..., dict[str, Any]]:
    """Return a dependency enforcing one of ``roles``. Stub owned by ws-d."""

    def _require_role(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        _ = (roles, user)
        raise HTTPException(status_code=501, detail="Not implemented (ws-d-auth)")

    return _require_role
