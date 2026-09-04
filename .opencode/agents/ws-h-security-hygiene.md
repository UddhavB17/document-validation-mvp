---
description: Wave 1 stream H. Small, merges first - remove /shutdown, CORS from env, encrypt secret settings at rest, no auto-generated keys in production, fix stale docs, remove Stop DMEF button.
mode: primary
---

You are the security-hygiene agent. This is a short stream: a handful of
changes that must land before the app is reachable from outside a laptop. Keep
the diff small; merge order puts you first in Wave 1.

# Read first

1. `docs/agents/00-CONTRACTS.md` §7, §9, §10
2. `main.py` (all), especially lines 40–60 (CORS) and 72–110 (`/shutdown`)
3. `routes/settings.py`, `services/config.py:150-290` (settings read/write, `secret` flag), `database/db.py:180-260` (settings seed rows, which are marked secret)
4. `services/job_control.py` (Fernet key auto-generation under `data/`)
5. `services/local_health.py`, `services/python_runtime.py` (laptop-only helpers referenced by `/health` or settings)
6. `docs/MAINTAINING.md:30-60`
7. `frontend/components/AppShell.tsx` (only the "Stop DMEF" button and its handler), `frontend/lib/api.ts` `shutdown` call

# Files you own

```text
main.py                         (CORS block, /shutdown removal, startup hooks section)
routes/settings.py
services/config.py
services/job_control.py         (key handling only; ws-c owns the job-state functions - keep your edit to the key/encryption helpers)
services/local_health.py
docs/MAINTAINING.md
tests/test_security_hygiene.py
frontend/components/AppShell.tsx (remove the Stop DMEF button and its handler only; ws-e restructures the shell later)
```

# Steps

1. **Delete `POST /shutdown`** in `main.py` and the `shutdown` client function in
   `frontend/lib/api.ts` (one deletion in a shared file; note it) and the button
   in `AppShell.tsx`. Remove tests that exercised it.
2. **CORS from env**: `CORS_ORIGINS` (comma-separated). Default
   `http://localhost:3000`. No regex, no wildcard when `allow_credentials=True`.
   Startup log line listing the origins.
3. **Secrets at rest**: settings marked `secret` in `system_settings` are stored
   Fernet-encrypted with `DMEF_JOB_INPUT_KEY` (rename the env to
   `DMEF_SECRETS_KEY` and keep the old name as a fallback with a deprecation
   warning). `services/config.py` decrypts on read; `routes/settings.py` never
   returns secret values (return `"***"` + `is_set: true`). In
   `services/job_control.py`, remove the auto-generation of the key under
   `data/`: if the key is missing and `DMEF_ENV=production`, fail startup with a
   clear message; otherwise generate an in-memory key and log a warning.
4. **Health**: `/health` must not call laptop-specific helpers (Ollama probe,
   local Python runtime checks) unless `LLM_PROVIDER=ollama`. Keep the response
   shape; add `"database": "ok"` computed with `SELECT 1` through
   `get_connection()` and `"storage": "ok"` via `get_store().exists("healthcheck")`
   (`exists` returning False is still "ok"; exceptions are "error").
5. **Settings precedence**: document the precedence in one docstring at the top
   of `services/config.py` (env overrides DB for `LLM_*`? Determine what the code
   does today at `:192-275`, make env win consistently, and write the test). Do
   not consolidate the 53 env vars; that is deferred.
6. **Docs**: `docs/MAINTAINING.md` — remove the "facade" claim about
   `field_extractor.py`, `consistency_checks.py`, `mapped_verification.py`; add
   the new runtime paths (`DMEF_JOB_WORK_DIR`, object store, worker process);
   link to `docs/agents/00-CONTRACTS.md`.
7. **Test** (`tests/test_security_hygiene.py`): `/shutdown` is 404; CORS reflects
   `CORS_ORIGINS`; secret settings round-trip encrypted (raw DB value is not the
   plaintext); `GET /settings` never contains the plaintext; production without
   key fails startup (call the check function directly).

# Done when

- [ ] `rg "shutdown" main.py routes frontend/lib frontend/components` returns nothing
- [ ] `rg "allow_origin_regex|localhost:\\d" main.py` returns nothing
- [ ] `sqlite3 data/dmef.db "select value from system_settings where key like '%API_KEY%'"` shows ciphertext after saving a key via the settings UI
- [ ] Full suite green; ruff clean; frontend typecheck/lint/test clean

# Verify

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test
```

# PR description

Contracts §10 template, workstream `ws-h security hygiene`.

# Stop conditions

Contracts §10.
