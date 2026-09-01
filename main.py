"""FastAPI application entry point for DMEF.

Run with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from services.python_runtime import require_python_311

require_python_311()

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.models import initialize_schema
from routes import decisions, review, settings, upload, verification
from services.config import log_effective_config


APP_VERSION = "0.1.0"
FRONTEND_PORT = 3000
SHUTDOWN_DELAY_SECONDS = 0.5

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize application dependencies before serving requests."""
    initialize_schema()
    log_effective_config()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title="Document Matching Early Finder",
        description=(
            "Validates loan-file PDFs against a product checklist "
            "and surfaces exceptions for human review."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    application.include_router(upload.router)
    application.include_router(decisions.router)
    application.include_router(verification.router)
    application.include_router(review.router)
    application.include_router(settings.router)
    return application


app = create_app()


@app.get("/health", tags=["meta"])
def health_check() -> dict[str, str]:
    """Return a lightweight liveness response."""
    return {"status": "ok", "version": app.version}


@app.post("/shutdown", tags=["meta"])
def shutdown() -> dict[str, str]:
    """Request a local development shutdown of the UI and API processes."""
    threading.Thread(target=_perform_shutdown, daemon=True).start()
    return {"message": "DMEF services shutting down..."}


def _perform_shutdown() -> None:
    """Stop the local frontend and then terminate the current API process."""
    time.sleep(SHUTDOWN_DELAY_SECONDS)
    _stop_frontend_processes()
    os.kill(os.getpid(), signal.SIGTERM)


def _stop_frontend_processes() -> None:
    """Ask processes listening on the local frontend port to stop."""
    try:
        process_ids = _frontend_process_ids()
        if sys.platform == "win32":
            for process_id in process_ids:
                subprocess.run(
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            return

        for process_id in process_ids:
            try:
                os.kill(process_id, signal.SIGTERM)
            except ProcessLookupError:
                continue
    except (OSError, subprocess.SubprocessError):
        # Shutdown is best-effort; the API process must still terminate.
        return


def _frontend_process_ids() -> set[int]:
    """Return process IDs listening on ``FRONTEND_PORT``."""
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            check=False,
            capture_output=True,
            text=True,
        )
        process_ids = set()
        for line in result.stdout.splitlines():
            if f":{FRONTEND_PORT}" not in line or "LISTENING" not in line:
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                process_ids.add(int(parts[-1]))
        return process_ids

    result = subprocess.run(
        ["lsof", f"-tiTCP:{FRONTEND_PORT}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {int(value) for value in result.stdout.split() if value.isdigit()}
