"""FastAPI entry point for DMEF."""

from fastapi import FastAPI

from routes import decisions, upload

app = FastAPI(title="Document Matching Early Finder")
app.include_router(upload.router)
app.include_router(decisions.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
