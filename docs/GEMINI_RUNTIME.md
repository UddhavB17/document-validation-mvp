# Gemini review runtime

The selected model is `gemini-3.8-flash`, using the Google global endpoint and
`thinking_level=low`. The existing regional endpoint rejected this model with 404;
the global endpoint accepted a live synthetic JSON request. Credentials, database
and object storage continue to load through the normal application configuration.

Use the checked-in non-secret wrapper to override older environment model pins:

```bash
bash scripts/with_gemini38.sh .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
bash scripts/with_gemini38.sh .venv/bin/python -m services.worker
```

Each command starts one service; do not launch a second worker over an active run.
An already running worker retains its process environment and imported code until
its normal restart. Updating the Settings model alone cannot override an existing
`GEMINI_MODEL` environment value. The wrapper explicitly selects the global endpoint;
deployments requiring regional processing should validate an allowed endpoint first.

The shared prompt lives in `services/review_prompts.py`. New review reports include
its version, fingerprint and model. Existing completed reports are not regenerated
when the configured model changes.
