"""Admin user-management routes. Endpoints implemented by ``ws-d-auth``."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin/users", tags=["admin"])
