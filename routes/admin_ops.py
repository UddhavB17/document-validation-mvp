"""Admin operations for deploy + smoke (owned by ``ws-j-deploy-smoke``).

- ``POST /admin/retention/run?dry_run=true|false`` (admin, or Cloud
  Scheduler with its dedicated header) runs ``services.retention.run_retention``
  and returns its counts dict.
- ``GET /admin/worker/heartbeat`` (admin) returns the worker heartbeat
  (``{"last_heartbeat": iso|None, "status": "ok|stale"}``).

Auth is enforced with ``services.auth.dependencies.require_role("admin")``
(contracts §6). Cloud Scheduler cannot mint a DMEF admin JWT, so the
retention endpoint additionally accepts ``X-DMEF-Scheduler-Token``. Keeping
the scheduler credential out of ``Authorization`` avoids its replacement by
Cloud Scheduler OIDC. The token is read via ``services.config.get_setting``;
when unset, the endpoint is admin-only and schedulers get 401.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)


def _admin_dependency():
    from services.auth.dependencies import require_role

    return require_role("admin")


def _admin_or_scheduler(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Admin JWT, or the Cloud Scheduler token (retention only).

    Scheduler wiring lives in ``deploy/scheduler/retention.yaml``. The job
    targets the public API and sends a dedicated secret header; normal users
    continue to authenticate with a DMEF bearer JWT.
    """
    from services.auth.dependencies import get_current_user
    from services.config import get_setting

    expected = str(get_setting("DMEF_SCHEDULER_TOKEN", "") or "").strip()
    presented = str(request.headers.get("x-dmef-scheduler-token") or "").strip()
    if expected and presented and secrets.compare_digest(presented, expected):
        return None
    # Fall through to the normal admin check (401 without token, 403).
    user = get_current_user(credentials)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


@router.post("/retention/run", summary="Run the retention job")
def run_retention_endpoint(
    request: Request,
    dry_run: bool = True,
    _auth=Depends(_admin_or_scheduler),  # noqa: B008
) -> dict:
    from services.retention import run_retention

    return dict(run_retention(dry_run=bool(dry_run)))


@router.get("/worker/heartbeat", summary="Get worker heartbeat")
def worker_heartbeat_endpoint(
    _admin=Depends(_admin_dependency()),  # noqa: B008
) -> dict:
    from database.worker_heartbeat import get_heartbeat

    return dict(get_heartbeat())
