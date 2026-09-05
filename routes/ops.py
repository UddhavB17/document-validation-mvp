"""Operations routes. Endpoints implemented by ``ws-f-accuracy-ops-api``."""

from fastapi import APIRouter, Depends

from services.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/ops", tags=["ops"], dependencies=[Depends(get_current_user)]
)
