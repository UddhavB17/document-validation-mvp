"""LLM provider settings endpoint owned by ``ws-g-gemini-llm``.

``GET /settings/llm/providers`` returns the real provider list, the Gemini
model list for the dropdown, and the current token/cost summary. (The generic
settings CRUD in ``routes/settings.py`` is owned by ws-h and untouched.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from services.auth.dependencies import require_role
from services.llm_client import ALLOWED_PROVIDERS, llm_model, llm_provider

# Provider and model configuration is restricted to admins.
router = APIRouter(
    prefix="/settings/llm",
    tags=["settings"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("/providers")
def get_llm_providers() -> dict:
    from services import llm_accounting
    from services.llm_gemini import list_models

    try:
        current_provider = llm_provider()
    except Exception:  # noqa: BLE001 - misconfigured provider still returns the list
        current_provider = "ollama"
    try:
        current_model = llm_model()
    except Exception:  # noqa: BLE001
        current_model = ""
    return {
        "providers": list(ALLOWED_PROVIDERS),
        "current_provider": current_provider,
        "current_model": current_model,
        "gemini_models": list_models(),
        "costs": llm_accounting.summarise_costs(),
    }
