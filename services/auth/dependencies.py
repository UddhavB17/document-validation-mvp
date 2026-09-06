"""Auth FastAPI dependencies. Implemented by ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth.service import get_user_by_id
from services.auth.tokens import decode

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """Authenticated principal resolved from the bearer JWT."""

    id: int
    email: str
    display_name: str
    role: str
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
        }


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Return the authenticated user from the bearer JWT.

    Raises 401 when the token is missing, invalid, expired, or belongs to an
    unknown/inactive user.
    """
    if (
        not isinstance(credentials, HTTPAuthorizationCredentials)
        or not credentials.credentials
    ):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid token")
    return CurrentUser(
        id=int(user["id"]),
        email=str(user["email"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        is_active=bool(user["is_active"]),
    )


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    """Return a dependency enforcing one of ``roles`` (401 without token, 403).

    ``admin`` satisfies any role check.
    """

    def _require_role(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != "admin" and user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _require_role
