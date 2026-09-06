---
description: Wave 1 stream C. Durable database-backed worker, retries with backoff and failure reasons, batch upload endpoints, multi-file upload UI.
mode: primary
---

You are the queue-and-batch agent. Today a job runs inside the API process in a
`ThreadPoolExecutor` (`services/job_runner.py`); if the process dies the job is
lost, and the UI accepts one file at a time. You make jobs durable rows that a
separate worker process claims one at a time, with three attempts and a
human-readable failure reason, and let users upload ten files at once.

# Read first

1. `docs/agents/00-CONTRACTS.md` §1, §4, §9, §10
2. `services/job_runner.py` (27 lines), `services/job_control.py`, `services/reprocessing.py`
3. `routes/upload.py:408-560` (`_queue_mapped_verification`), `:1065-1200` (`_run_pipeline_task`, `_run_mapped_pipeline_task`, `upload_progress`)
4. `services/pipeline/orchestrator.py:51-120` (`run_pipeline` signature, how status is written)
5. `services/progress_tracker.py` (job rows, `pipeline_jobs` writes)
6. `database/models.py` — `pipeline_jobs`, `pipeline_job_inputs`, `intake_packages` (columns `max_attempts`, `next_run_at`, `failure_reason`, `batch_id` are added by ws-a; until ws-a merges, add them in your worktree in `database/models.py` **identically** to contracts §4 so rebases are trivial)
7. `frontend/app/upload/page.tsx`, `frontend/components/upload/*`, `frontend/lib/api.ts` upload section, `frontend/lib/queries.ts` upload hooks
8. `tests/test_job_control.py`, `tests/test_upload_routes.py`

# Files you own

```text
services/job_runner.py
services/worker.py
services/pipeline/tasks.py
services/reprocessing.py
services/job_control.py
routes/upload.py           (the _run_*_task functions, _queue_mapped_verification, new batch endpoints; ws-b owns the file-saving lines)
routes/batches.py          (new; or put batch endpoints in routes/upload.py under a "# --- batch ---" section)
frontend/app/upload/**
frontend/components/upload/**
tests/test_worker.py, tests/test_batch_upload.py
```

Shared appends: `main.py` (router line if you create `routes/batches.py`), `frontend/lib/api.ts` (bottom section `// --- ws-c batch ---`).

# Steps

## 1. Move task bodies out of routes

Cut `_run_pipeline_task` and `_run_mapped_pipeline_task` from `routes/upload.py`
into `services/pipeline/tasks.py` as `run_pipeline_job(job_id)` and
`run_mapped_job(job_id)`. They load everything they need from the job row and
`pipeline_job_inputs` (this already exists for restarts — reuse it). Fix the bug
at `routes/upload.py:1136-1149` where the intake package is marked `completed`
even when the pipeline failed: package status must mirror the job outcome.

## 2. Enqueue only (`services/job_runner.py`)

Replace the executor with `enqueue(kind, application_id, payload, batch_id=None) -> job_id`
that inserts a `pipeline_jobs` row with `status='queued'`, `attempt=0`,
`max_attempts=3`, `next_run_at=NULL`, stores inputs in `pipeline_job_inputs`, and
returns the id via `RETURNING id`. Keep a `DMEF_INLINE_WORKER=1` env switch
(default `0`; tests set `1`) that runs the job synchronously in the request for
the existing tests that expect immediate results. Under `DMEF_INLINE_WORKER=0`
the API never runs pipeline code.

## 3. Worker (`services/worker.py`)

```python
def run_worker(poll_seconds: float = 2.0, once: bool = False) -> None
```

Loop: claim → run → finalize → sleep. Claim in one transaction:

- Postgres: `SELECT id ... FOR UPDATE SKIP LOCKED` then `UPDATE ... SET status='running', started_at=?, attempt=attempt+1, worker_id=? WHERE id=?`.
- SQLite: `BEGIN IMMEDIATE` (use `connection.execute("BEGIN IMMEDIATE")` via the wrapper; if ws-b's wrapper is not merged yet, branch on `database.db.dialect()` if present, else assume SQLite).

Run the job via `tasks.run_*`. On exception: if `attempt < max_attempts` set
`status='retrying'`, `next_run_at = now + backoff(attempt)` (30 s, 120 s), store
the exception summary in `last_error`; else `status='failed'`,
`failure_reason=<one sentence for operators>` (map known exceptions: OCR quota,
corrupt PDF, password-protected PDF, empty ZIP, unsupported file; default
"Processing failed after 3 attempts. Contact an administrator."). Also set
`applications.status='failed'` and the intake package status.

Heartbeat: update `pipeline_jobs.heartbeat_at` every 30 s from a thread while a
job runs (add the column in your worktree if ws-a has not; identical name).
Stale recovery at startup: jobs `running` with `heartbeat_at` older than 10 min
→ `retrying` with `attempt` unchanged.

`python -m services.worker` runs forever; `--once` processes one job and exits
(used by tests and by the smoke script). Handle `SIGTERM` by finishing the current
job then exiting.

## 4. Batch endpoints

- `POST /upload/batch` (multipart, N files, optional manifest per file by
  filename convention `<name>.pdf` + `<name>.manifest.json`, or a single mapped
  ZIP each) → creates one application per file, enqueues one job per file with
  the same `batch_id`, returns `{batch_id, items:[{filename, application_id, job_id, status}]}`.
  Validate each file with the existing `file_validator`; invalid files are
  reported in `items` with `status='rejected'` and a reason, without failing the batch.
- `GET /upload/batch/{batch_id}` → per-item `{application_id, filename, status, attempt, failure_reason, progress_percentage, review_ready: bool}`.
- Existing single-file endpoints keep working (they enqueue with `batch_id=None`).
- Job control routes (pause/cancel/resume/restart in `routes/review.py`) keep
  their behaviour through `services/job_control.py`; make `restart` reset
  `attempt=0`, `status='queued'`, `failure_reason=NULL`.

## 5. Frontend multi-file upload

- `frontend/components/upload/PdfUploadForm.tsx`: `<input type="file" multiple>`;
  submit calls `api.uploadBatch(files)`.
- New `frontend/components/upload/BatchStatusTable.tsx`: polls
  `GET /upload/batch/{id}` every 3 s while any item is not terminal; columns
  file, status pill (Queued / Processing / Retrying / Completed / Failed),
  attempt `n/3`, reason (on failure), "Open review" link when `review_ready`.
- Remove demo defaults in `frontend/components/upload/ZipPackageForm.tsx:16-26`
  (fake PAN/Aadhaar manifest) — the form starts empty.
- Copy: no "pipeline", "job", "worker" words in the UI. Use "Processing",
  "Waiting", "Retrying (2 of 3)", "Failed: <reason>".
- Add schemas to `frontend/lib/api.ts` bottom section with zod, as the file already does.

## 6. Tests

- `tests/test_worker.py`: enqueue 3 jobs → `run_worker(once=True)` ×3 processes
  them in id order; a job whose task raises every time ends `failed` after 3
  attempts with a `failure_reason`; `next_run_at` respected (monkeypatch time);
  stale `running` job is recovered at startup; SIGTERM flag finishes current job.
  Use a fake task registered via monkeypatch instead of the real pipeline.
- `tests/test_batch_upload.py`: 3 small PDFs → 3 applications, 3 jobs, one
  `batch_id`; one invalid file → `rejected` item, others still queued; status
  endpoint shape.

# Done when

- [ ] `DMEF_INLINE_WORKER=0`: uploading does not run any pipeline code in the API process (assert via monkeypatch in test)
- [ ] `python -m services.worker --once` processes exactly one job
- [ ] A task that raises three times leaves `status='failed'`, readable `failure_reason`, `applications.status='failed'`
- [ ] Killing the worker mid-job (simulate by setting `heartbeat_at` old) leads to recovery
- [ ] 10-file batch from the UI shows ten rows updating independently; the review link appears per file as it completes
- [ ] Existing `tests/test_job_control.py`, `tests/test_upload_routes.py` pass (with `DMEF_INLINE_WORKER=1` in `tests/conftest.py` if needed — add a fixture, do not edit other tests' logic)
- [ ] `npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test` clean
- [ ] `rg "ThreadPoolExecutor" services routes` returns nothing

# Verify

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test
# manual: terminal 1 `uvicorn main:app --port 8000`, terminal 2 `python -m services.worker`, upload 3 files at /upload
```

# PR description

Contracts §10 template, workstream `ws-c queue + batch`. List the `pipeline_jobs`
columns you added in your worktree so the merge with ws-a is checked.

# Stop conditions

Contracts §10. Additionally: if `pipeline_job_inputs` does not hold enough to
re-run a mapped job, extend what is stored there (JSON) rather than reading from
request objects.
