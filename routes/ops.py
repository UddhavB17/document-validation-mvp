"""Operations routes for non-technical users. Owned by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.auth.dependencies import CurrentUser, get_current_user, require_role
from services.ops_workflow import (
    check_items,
    claim,
    create_document_request,
    reassign,
    release,
    review_next,
    save_check,
    tat_metrics,
    update_request_item,
    workflow_detail,
)
from services.ops_workflow import (
    worklist as build_worklist,
)

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(get_current_user)])


@router.get("/applications/{application_id}")
def get_ops_application(application_id: int) -> dict[str, Any]:
    """Return the operator-facing payload for one application (§5)."""
    from services.ops_presentation import build_ops_payload

    try:
        return build_ops_payload(application_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")


class ReviewCheckRequest(BaseModel):
    check_key: str = Field(min_length=1, max_length=64)
    evidence_revision: str = Field(min_length=1, max_length=64)
    status: str
    note: str | None = Field(default=None, max_length=2000)


class DocumentRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    items: list[str] = Field(min_length=1, max_length=30)
    follow_up_at: datetime | None = None


class DocumentItemUpdate(BaseModel):
    status: str
    uploaded_file_id: int | None = None


class ReassignBody(BaseModel):
    user_id: int
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/workflow/{application_id}")
def get_ops_workflow(
    application_id: int, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    from services.ops_presentation import build_ops_payload

    try:
        detail = workflow_detail(application_id, user.id)
        current_checks = check_items(build_ops_payload(application_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")
    saved = {item["check_key"]: item for item in detail["checks"]}
    current_revisions = {item["check_key"]: item["evidence_revision"] for item in current_checks}
    detail["changed_review_items"] = sum(
        1 for key, item in saved.items() if current_revisions.get(key) != item["evidence_revision"]
    )
    for item in current_checks:
        prior = saved.get(item["check_key"])
        if prior and prior["evidence_revision"] == item["evidence_revision"]:
            item["status"] = prior["status"]
            item["note"] = prior["note"]
            item["updated_at"] = prior["updated_at"]
        else:
            item["status"] = None
            item["note"] = None
    detail["review_items"] = current_checks
    detail.pop("checks", None)
    return detail


@router.post("/applications/{application_id}/claim")
def claim_ops_case(
    application_id: int, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        return {"case": claim(application_id, user.id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Case is not ready for Ops review")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/release")
def release_ops_case(
    application_id: int, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        return {"case": release(application_id, user.id, admin=user.role == "admin")}
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/reassign")
def reassign_ops_case(
    application_id: int, payload: ReassignBody, user: CurrentUser = Depends(require_role("admin"))
) -> dict[str, Any]:
    try:
        return {"case": reassign(application_id, payload.user_id, user.id, payload.reason)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Active user or Ops case not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/checks")
def save_ops_check(
    application_id: int, payload: ReviewCheckRequest, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    from services.ops_presentation import build_ops_payload

    try:
        result = save_check(
            application_id,
            user.id,
            payload.check_key,
            payload.evidence_revision,
            payload.status,
            payload.note,
            build_ops_payload(application_id),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.post("/applications/{application_id}/document-requests")
def request_ops_documents(
    application_id: int, payload: DocumentRequestBody, user: CurrentUser = Depends(get_current_user)
) -> dict[str, Any]:
    from services.ops_workflow import ensure_case

    try:
        ensure_case(application_id, user.id)
        follow_up_at = payload.follow_up_at.isoformat() if payload.follow_up_at else None
        return create_document_request(
            application_id, user.id, payload.message, payload.items, follow_up_at
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/applications/{application_id}/document-requests/{request_id}/items/{item_id}")
def update_ops_document_item(
    application_id: int,
    request_id: int,
    item_id: int,
    payload: DocumentItemUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return update_request_item(
            application_id, request_id, item_id, payload.status, payload.uploaded_file_id, user.id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Requested document item not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/metrics/tat")
def get_ops_tat_metrics(_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return tat_metrics()


@router.get("/worklist/next")
def get_next_ops_case(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    application_id = review_next(user.id)
    return {"application_id": application_id}


@router.get("/worklist")
def get_ops_worklist(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    view: str = Query("all", pattern="^(all|ready|mine|waiting|completed|processing)$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return operations worklist rows (no technical fields)."""
    return build_worklist(None, user.id, view, limit, offset)
