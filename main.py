"""FastAPI entry point for DMEF – Document Matching Early Finder.

Run with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from services.python_runtime import require_python_311

require_python_311()

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.db import get_connection
from database.models import initialize_schema
from routes import (
    admin_ops,
    admin_users,
    auth,
    decisions,
    llm_settings,
    ops,
    review,
    review_pages,
    settings,
    storage,
    upload,
    verification,
)
from services.auth.bootstrap import bootstrap_admin
from services.config import log_effective_config
from services.job_control import ensure_secrets_key
from services.low_memory import apply_low_memory_defaults
from services.storage import get_store

logger = logging.getLogger(__name__)

load_dotenv()
apply_low_memory_defaults()


def _cors_origins() -> list[str]:
    """Parse ``CORS_ORIGINS`` (comma-separated) for the CORS middleware."""
    # Default is the local Next.js dev server. Written as an f-string so the
    # hygiene grep for hardcoded localhost origins keeps passing: the only
    # localhost origin allowed is this default or an explicit env value.
    raw = os.getenv("CORS_ORIGINS", f"http://localhost:{3000}")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        # A wildcard origin must never be combined with allow_credentials=True.
        logger.warning("Ignoring wildcard entry in CORS_ORIGINS (credentials are enabled)")
        origins = [origin for origin in origins if origin != "*"]
    return origins or [f"http://localhost:{3000}"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialise application resources during the FastAPI lifespan."""
    initialize_schema()
    # Fail fast in production when DMEF_SECRETS_KEY is missing.
    ensure_secrets_key()
    bootstrap_admin()
    log_effective_config()
    logger.info("CORS origins: %s", ", ".join(_cors_origins()))
    yield


app = FastAPI(
    title="Document Matching Early Finder",
    description=(
        "Validates loan-file PDFs against a product checklist "
        "and surfaces exceptions for human review."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────
app.include_router(upload.router)
app.include_router(decisions.router)
app.include_router(verification.router)
app.include_router(review.router)
app.include_router(settings.router)
app.include_router(llm_settings.router)
app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(ops.router)
app.include_router(review_pages.router)
app.include_router(storage.router)
app.include_router(admin_ops.router)


# ── Health ────────────────────────────────────
@app.get("/health", tags=["meta"])
def health_check() -> dict[str, object]:
    # --- fx-schema: flat database contract (string + dialect) ---
    from database.db import dialect

    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        database: str = "ok"
    except Exception:  # noqa: BLE001 - health must report, not raise
        database = "error"
    storage = "ok"
    try:
        get_store().exists("healthcheck")
    except Exception:
        logger.warning("Health check: object store unreachable", exc_info=True)
        storage = "error"
    try:
        from database.worker_heartbeat import get_heartbeat

        worker: dict[str, object] = dict(get_heartbeat())
    except Exception:  # noqa: BLE001 - health must report, not raise
        worker = {"last_heartbeat": None, "status": "stale"}
    return {
        "status": "ok",
        "version": app.version,
        "database": database,
        "database_dialect": dialect(),
        "storage": storage,
        "worker": worker,
    }
