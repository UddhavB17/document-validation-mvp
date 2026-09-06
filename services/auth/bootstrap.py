"""First-admin bootstrap for ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

import logging

from services.auth.service import count_users, create_user
from services.config import get_setting

logger = logging.getLogger(__name__)


def bootstrap_admin() -> dict | None:
    """Create the first admin from bootstrap env vars when ``users`` is empty.

    No-op (one log line) when users already exist. Raises ``RuntimeError``
    with a clear message when bootstrap credentials are missing.
    """
    try:
        total = count_users()
    except Exception as exc:  # tables not initialised yet
        logger.warning("Auth bootstrap skipped: users table is unavailable (%s)", exc)
        return None
    if total > 0:
        logger.info("Auth bootstrap skipped: %s user(s) already exist", total)
        return None
    email = str(get_setting("dmef.bootstrap_admin_email", "") or "").strip()
    password = str(get_setting("dmef.bootstrap_admin_password", "") or "")
    if not email or not password:
        raise RuntimeError(
            "No users exist and DMEF_BOOTSTRAP_ADMIN_EMAIL / "
            "DMEF_BOOTSTRAP_ADMIN_PASSWORD are not set. Set both in the "
            "environment (or .env) so the first admin can be created."
        )
    admin = create_user(
        email=email, display_name="Administrator", role="admin", password=password
    )
    logger.info("Auth bootstrap created first admin %s", admin["email"])
    return admin
