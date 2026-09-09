"""User management domain logic for ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from database.db import get_connection
from services.auth.passwords import (
    dummy_verify,
    hash_password,
    validate_password,
    verify_password,
)

logger = logging.getLogger(__name__)

VALID_ROLES = ("admin", "user")

_PUBLIC_USER_COLUMNS = "id, email, display_name, role, is_active, created_at, created_by"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _audit(action: str, details: dict[str, Any]) -> None:
    """Write an auth audit row (no application context; application_id is NULL)."""
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (None, action, json.dumps(details)),
        )


def _public_user(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "email": str(row["email"]),
        "display_name": str(row["display_name"]),
        "role": str(row["role"]),
        "is_active": bool(row["is_active"]),
        "created_at": str(row["created_at"]),
    }


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise ValueError("Email address is not valid")
    return normalized


def _check_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"Role must be one of {VALID_ROLES}")
    return role


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Return the public user dict for ``email``, or None when unknown."""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {_PUBLIC_USER_COLUMNS} FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    return _public_user(row) if row is not None else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Return the public user dict for ``user_id``, or None when unknown."""
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {_PUBLIC_USER_COLUMNS} FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _public_user(row) if row is not None else None


def list_users() -> list[dict[str, Any]]:
    """Return every user (public fields only, never password hashes)."""
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT {_PUBLIC_USER_COLUMNS} FROM users ORDER BY id",
        ).fetchall()
    return [_public_user(row) for row in rows]


def count_users() -> int:
    """Return the number of user rows (used by bootstrap)."""
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"])


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Return the public user on valid credentials, else None.

    Always runs one bcrypt verification (real or dummy) so unknown emails do
    not fail faster than wrong passwords.
    """
    normalized = email.strip().lower()
    stored_hash: str | None = None
    user: dict[str, Any] | None = None
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {_PUBLIC_USER_COLUMNS} FROM users WHERE email = ?",
            (normalized,),
        ).fetchone()
        if row is not None:
            user = _public_user(row)
            secret = connection.execute(
                "SELECT password_hash FROM user_passwords WHERE user_id = ?",
                (user["id"],),
            ).fetchone()
            stored_hash = str(secret["password_hash"]) if secret is not None else None
    if stored_hash is None:
        dummy_verify(password)
        return None
    if not verify_password(password, stored_hash):
        return None
    if user is not None and not user["is_active"]:
        return None
    return user


def create_user(
    *,
    email: str,
    display_name: str,
    role: str,
    password: str,
    created_by: int | None = None,
) -> dict[str, Any]:
    """Create a user with a bcrypt password; raises ``ValueError`` on bad input."""
    normalized = _normalize_email(email)
    _check_role(role)
    validate_password(password)
    name = display_name.strip()
    if not name:
        raise ValueError("Display name is required")
    password_hash = hash_password(password)
    now = _now_iso()
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ?", (normalized,)
        ).fetchone()
        if existing is not None:
            raise ValueError("A user with this email already exists")
        user_id = int(
            connection.execute(
                """
                INSERT INTO users (email, display_name, role, is_active, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (normalized, name, role, True, now, created_by),
            ).fetchone()["id"]
        )
        connection.execute(
            """
            INSERT INTO user_passwords (user_id, password_hash, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                password_hash = excluded.password_hash,
                updated_at = excluded.updated_at
            """,
            (user_id, password_hash, now),
        )
    created = get_user_by_id(user_id)
    assert created is not None
    _audit(
        "user_created",
        {"user_id": user_id, "email": normalized, "role": role, "created_by": created_by},
    )
    logger.info("Created user %s with role %s", normalized, role)
    return created


def set_password(user_id: int, new_password: str) -> None:
    """Replace ``user_id``'s password after enforcing policy."""
    validate_password(new_password)
    password_hash = hash_password(new_password)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise ValueError("User not found")
        connection.execute(
            """
            INSERT INTO user_passwords (user_id, password_hash, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                password_hash = excluded.password_hash,
                updated_at = excluded.updated_at
            """,
            (user_id, password_hash, _now_iso()),
        )
        email = str(row["email"])
    _audit("password_changed", {"user_id": user_id, "email": email})
    logger.info("Password changed for user %s", email)


def update_user(
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """Patch a user's profile fields; raises ``ValueError`` when unknown/invalid."""
    updates: list[str] = []
    params: list[Any] = []
    if display_name is not None:
        name = display_name.strip()
        if not name:
            raise ValueError("Display name is required")
        updates.append("display_name = ?")
        params.append(name)
    if role is not None:
        updates.append("role = ?")
        params.append(_check_role(role))
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(bool(is_active))
    if not updates:
        raise ValueError("No fields to update")
    params.append(user_id)
    with get_connection() as connection:
        updated = connection.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        if updated.rowcount != 1:
            raise ValueError("User not found")
    user = get_user_by_id(user_id)
    assert user is not None
    if is_active is False:
        _audit(
            "user_deactivated",
            {"user_id": user_id, "email": user["email"]},
        )
    return user


def deactivate(user_id: int) -> dict[str, Any]:
    """Deactivate ``user_id`` (sets ``is_active`` to False)."""
    return update_user(user_id, is_active=False)


def delete_user(user_id: int, *, actor_id: int) -> None:
    """Permanently remove ``user_id`` and their stored password hash.

    Raises ``ValueError`` when the user is unknown, when an admin tries to
    delete their own account, or when the target is the last active admin
    (removing them would leave no admin path back, since bootstrap only
    runs on an empty ``users`` table).
    """
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, email, role, is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise ValueError("User not found")
        email = str(row["email"])
        if int(row["id"]) == int(actor_id):
            raise ValueError("You cannot delete your own account")
        if str(row["role"]) == "admin" and bool(row["is_active"]):
            remaining = connection.execute(
                "SELECT COUNT(*) AS total FROM users "
                "WHERE role = 'admin' AND is_active = ? AND id != ?",
                (True, user_id),
            ).fetchone()
            if int(remaining["total"]) == 0:
                raise ValueError("Cannot delete the last active admin")
        connection.execute("DELETE FROM user_passwords WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _audit("user_deleted", {"user_id": user_id, "email": email, "deleted_by": actor_id})
    logger.info("Deleted user %s", email)
