"""FastAPI entry point for DMEF – Document Matching Early Finder.

Run with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8000
"""

import os

from services.python_runtime import require_python_311

require_python_311()

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.models import initialize_schema
from routes import decisions, review, upload, verification
from services.config import log_effective_config

load_dotenv()

app = FastAPI(
    title="Document Matching Early Finder",
    description=(
        "Validates loan-file PDFs against a product checklist "
        "and surfaces exceptions for human review."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────
@app.on_event("startup")
def on_startup() -> None:
    """Initialise the SQLite schema on first run."""
    initialize_schema()
    log_effective_config()


# ── Routers ───────────────────────────────────
app.include_router(upload.router)
app.include_router(decisions.router)
app.include_router(verification.router)
app.include_router(review.router)


# ── Health ────────────────────────────────────
@app.get("/health", tags=["meta"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
