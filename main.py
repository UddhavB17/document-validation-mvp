"""FastAPI entry point for DMEF – Document Matching Early Finder.

Run with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from services.python_runtime import require_python_311

require_python_311()

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.models import initialize_schema
from routes import decisions, review, upload, verification, settings
from services.config import log_effective_config
from services.low_memory import apply_low_memory_defaults

load_dotenv()
apply_low_memory_defaults()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialise application resources during the FastAPI lifespan."""
    initialize_schema()
    log_effective_config()
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
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
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


# ── Health ────────────────────────────────────
@app.get("/health", tags=["meta"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


# ── Shutdown ──────────────────────────────────
@app.post("/shutdown", tags=["meta"])
def shutdown() -> dict[str, str]:
    """Gracefully shutdown Next.js UI and FastAPI backend."""
    import threading
    import time
    import subprocess
    import os
    import signal
    import sys

    def perform_shutdown():
        time.sleep(0.5)  # Wait for the API response to be sent
        # Attempt to kill UI on port 3000
        try:
            if sys.platform == "win32":
                output = subprocess.check_output("netstat -ano", shell=True).decode()
                for line in output.splitlines():
                    if ":3000" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            subprocess.run(
                                f"taskkill /F /PID {pid}", shell=True, capture_output=True
                            )
            else:
                output = subprocess.check_output("lsof -i :3000 -t", shell=True).decode().strip()
                if output:
                    for pid in output.split():
                        subprocess.run(f"kill -9 {pid}", shell=True, capture_output=True)
        except Exception:
            pass
        # Kill the FastAPI backend process
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=perform_shutdown, daemon=True).start()
    return {"message": "DMEF services shutting down..."}
