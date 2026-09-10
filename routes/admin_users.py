"""Admin user-management routes. Implemented by ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth.dependencies import CurrentUser, get_current_user, require_role
from services.auth.service import create_user, delete_user, list_users, set_password, update_user

router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


class CreateUserPayload(BaseModel):
    email: str
    display_name: str
    role: str
    password: str


class UpdateUserPayload(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ResetPasswordPayload(BaseModel):
    new_password: str


@router.get("")
def get_users() -> dict:
    """List all users (public fields only)."""
    return {"users": list_users()}


@router.post("", status_code=201)
def post_user(
    payload: CreateUserPayload, user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Create an admin or user account."""
    try:
        created = create_user(
            email=payload.email,
            display_name=payload.display_name,
            role=payload.role,
            password=payload.password,
            created_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return created


@router.patch("/{user_id}")
def patch_user(
    user_id: int,
    payload: UpdateUserPayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Update display name, role, or active flag. Admins cannot deactivate self."""
    if user_id == user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    try:
        return update_user(
            user_id,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        status = 404 if str(exc) == "User not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/{user_id}/password")
def reset_user_password(user_id: int, payload: ResetPasswordPayload) -> dict:
    """Admin reset of any user's password (policy enforced)."""
    try:
        set_password(user_id, payload.new_password)
    except ValueError as exc:
        status = 404 if str(exc) == "User not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"status": "ok"}


@router.delete("/{user_id}")
def remove_user(user_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Permanently remove a user. Admins cannot delete themselves or the last active admin."""
    try:
        delete_user(user_id, actor_id=user.id)
    except ValueError as exc:
        status = 404 if str(exc) == "User not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"status": "ok"}
