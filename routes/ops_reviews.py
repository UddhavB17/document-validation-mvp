"""Operations API for persisted human review of individual findings."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.auth.dependencies import CurrentUser, get_current_user
from services.ops_reviews import StaleReviewItemError, get_review_items, update_review_item

router = APIRouter(
    prefix="/ops", tags=["ops"], dependencies=[Depends(get_current_user)]
)


class ReviewItemUpdate(BaseModel):
    expected_revision: str = Field(min_length=8, max_length=128)
    disposition: Literal["correct", "reopen"]
    note: str | None = Field(default=None, max_length=2000)


@router.get("/applications/{application_id}/review-items")
def list_review_items(application_id: int) -> dict:
    try:
        return get_review_items(application_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.put("/applications/{application_id}/review-items/{item_id}")
def save_review_item(
    application_id: int,
    item_id: str,
    payload: ReviewItemUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        return update_review_item(
            application_id,
            item_id,
            payload.expected_revision,
            payload.disposition,
            user.id,
            payload.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Review item not found")
    except StaleReviewItemError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
