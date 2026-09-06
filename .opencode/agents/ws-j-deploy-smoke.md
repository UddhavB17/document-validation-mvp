---
description: Wave 3. Deployment (Cloud Run API + worker), secrets wiring, health with worker heartbeat, end-to-end smoke script on 10 files, retention schedule, pilot metrics.
mode: primary
---

You are the deploy-and-smoke agent. Everything is merged; you make it run
outside a laptop and prove it with a ten-file batch.

# Read first

1. `docs/agents/00-CONTRACTS.md` §7 (env), §8 (budgets), §10
2. `docs/DEPLOY_NEON.md` (ws-i), `Dockerfile`, `docker-compose.dev.yml`, `.github/workflows/ci.yml`
3. `services/worker.py`, `services/retention.py`, `main.py` (`/health`, startup hooks), `routes/auth.py` bootstrap
4. `scripts/eval_gemini_models.py` (reuse its runner helpers), `routes/upload.py` batch endpoints, `routes/ops.py`

# Files you own

```text
Dockerfile                                (entrypoints only)
deploy/cloudrun/api.yaml, deploy/cloudrun/worker.yaml, deploy/cloudrun/README.md
deploy/scheduler/retention.yaml
routes/admin_ops.py                       (new: POST /admin/retention/run, GET /admin/worker/heartbeat)
scripts/smoke_batch.py
scripts/release.sh                        (alembic upgrade head, bootstrap admin check)
docs/agents/PILOT_METRICS.md
tests/test_smoke_script.py                (dry-run mode)
.github/workflows/deploy.yml
```

Shared appends: `main.py` (router line), `.env.example` (`DMEF_ENV`, `DMEF_WORKER_POLL_SECONDS` if missing).

# Steps

1. **Containers**: two images. Backend (`Dockerfile`): python 3.11-slim,
   non-root user, `PYTHONUNBUFFERED=1`; the API runs
   `uvicorn main:app --host 0.0.0.0 --port 8080`, the worker runs
   `python -m services.worker --serve-health 8080` (same image, different
   command). Frontend (`frontend/Dockerfile`, `next build` with
   `output: 'standalone'`) as a separate Cloud Run service with
   `NEXT_PUBLIC_API_URL`.
2. **Cloud Run**: API service min instances 0, concurrency 20, 2 GiB. Worker as
   a Cloud Run service with `min-instances=1`, `max-instances=1`, CPU always
   allocated, 4 GiB (OCR + PDF rendering), internal ingress only. Implement the
   `--serve-health PORT` flag in `services/worker.py` (you may edit this one
   function): start a minimal HTTP server thread that answers `GET /health` with
   the worker heartbeat so Cloud Run's health probe works. Secrets from Secret
   Manager mapped to the env names in contracts §7. Service account with
   `roles/storage.objectAdmin` on the bucket and Vision + Gemini access.
3. **Release**: `scripts/release.sh` runs `alembic upgrade head` against the
   direct Neon endpoint, then deploys API, worker, frontend. `deploy.yml`
   workflow triggers on a tag, builds the image, runs the script; requires the
   CI workflow to be green.
4. **Health**: `/health` adds `"worker": {"last_heartbeat": ts, "status": "ok|stale"}`
   from `pipeline_jobs.heartbeat_at` max or a dedicated `worker_heartbeat`
   registered table (one row updated every 30 s by the worker loop even when idle
   — add it via `schema_registry`, alembic migration `0002_worker_heartbeat.py`).
   Stale = older than 2 minutes.
5. **Retention**: `POST /admin/retention/run?dry_run=true|false` (admin) calling
   `services.retention.run_retention`; Cloud Scheduler job (`deploy/scheduler/retention.yaml`)
   daily 02:00 IST with an OIDC token to that endpoint. Response is the counts dict.
6. **Smoke** (`scripts/smoke_batch.py --api URL --email --password --files dir --timeout 1800`):
   login, `POST /upload/batch` with all files in `dir` (use `tests/fixtures`
   PDFs ×10 by copying with different names if fewer than 10), poll
   `GET /upload/batch/{id}` until all terminal, then for each completed
   application call `GET /ops/applications/{id}` and assert: valid payload, ≤ 5
   findings, Hindi present; for each failed, print `failure_reason`. Print a
   table: file, status, seconds, findings, size of ops payload. Exit non-zero if
   any item is not terminal within the timeout or any payload is invalid.
   `--dry-run` validates arguments and prints the plan (used by the test).
7. **Pilot metrics** (`docs/agents/PILOT_METRICS.md`): SQL (Postgres) for the
   five pilot KPIs — processing time per application (job `started_at`→`finished_at`),
   failure rate, retries, findings per application by code, manual-review effort
   proxy (`reviewer_decisions` per application and time to decision), LLM cost
   per application (`llm_calls`), storage per application (`object_refs.size_bytes`).
   One query each, tested against docker Postgres with a seeded fixture if
   practical; otherwise verified by running once and pasting sample output.

# Done when

- [ ] `docker build` succeeds; `docker run` of API answers `/health` with `database`, `storage`, `worker` keys
- [ ] `scripts/smoke_batch.py` against a local stack (API + worker + docker Postgres + local store) processes 10 files; all terminal within budget; report printed
- [ ] With cloud credentials provided: the same smoke run against Cloud Run + Neon + GCS; paste the table in the PR. Without: describe exactly what is left for the operator
- [ ] Retention endpoint dry run returns counts; scheduler config validated with `gcloud scheduler jobs create --dry-run` equivalent or documented
- [ ] `docs/agents/PILOT_METRICS.md` queries run without error on Postgres
- [ ] Full suite green; ruff clean

# Verify

```bash
source .venv/bin/activate
docker compose -f docker-compose.dev.yml up -d
DATABASE_URL=postgresql://dmef:dmef@localhost:5432/dmef alembic upgrade head
# terminal 1: DATABASE_URL=... uvicorn main:app --port 8000
# terminal 2: DATABASE_URL=... python -m services.worker
python scripts/smoke_batch.py --api http://localhost:8000 --email admin@example.com --password '...' --files tests/fixtures --timeout 1800
python -m pytest -q && ruff check .
```

# PR description

Contracts §10 template, workstream `ws-j deploy + smoke`. Include the smoke table.

# Stop conditions

Contracts §10. Cloud resources must not be created by you; you produce the
configs and the operator applies them. If a config cannot be validated without
creating resources, say which.
