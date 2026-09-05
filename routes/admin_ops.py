"""Admin operations for deploy + smoke (owned by ``ws-j-deploy-smoke``).

- ``POST /admin/retention/run?dry_run=true|false`` (admin) runs
  ``services.retention.run_retention`` and returns its counts dict.
- ``GET /admin/worker/heartbeat`` (admin) returns the worker heartbeat
  (``{"last_heartbeat": iso|None, "status": "ok|stale"}``).

Auth is enforced with ``services.auth.dependencies.require_role("admin")``
(contracts §6). Until ``ws-d-auth`` lands, that dependency raises 501 and
these endpoints fail closed; see NEEDS-COORDINATION in the ws-j commit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

router = APIRouter(prefix="/admin", tags=["admin"])


def _admin_dependency():
    from services.auth.dependencies import require_role

    return require_role("admin")


@router.post("/retention/run", summary="Run the retention job")
def run_retention_endpoint(
    dry_run: bool = True,
    _admin=Depends(_admin_dependency()),  # noqa: B008
) -> dict:
    from services.retention import run_retention

    return dict(run_retention(dry_run=bool(dry_run)))


@router.get("/worker/heartbeat", summary="Get worker heartbeat")
def worker_heartbeat_endpoint(
    _admin=Depends(_admin_dependency()),  # noqa: B008
) -> dict:
    from database.worker_heartbeat import get_heartbeat

    return dict(get_heartbeat())
