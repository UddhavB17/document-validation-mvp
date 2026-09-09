---
description: Wave 1 stream A. Data diet - stop persisting raw Vision JSON and private blobs, explicit columns, status endpoint, retention, indexes, size-budget tests.
mode: primary
---

You are the data-diet agent. Today one page row can be 100 MB because the full
Google Vision response is stored as `structured_content.native`, and the review
endpoint ships every page's OCR text to the browser every 2 seconds. You make
the pipeline write only what is read, and you prove it with a budget test.

# Read first

1. `docs/agents/00-CONTRACTS.md` §1, §3, §4, §8, §9, §10
2. `docs/PRODUCTION_NEXT_PHASE.md` §2, §3
3. Code, in this order:
   - `services/ocr_router.py:440-500` (`native` is built here from `structure_json`)
   - `services/google_vision_ocr.py` (where `structure_json` comes from)
   - `services/pipeline/page_processing.py:600-700` and `:952-990` (`extracted_fields` private keys, `_public_ocr_structure`)
   - `services/pipeline/persistence.py` (all of it; `_insert_page` at :62)
   - `services/pipeline/orchestrator.py:80-120` and `:230-270` (two `ground_truth` saves; export at run end)
   - `services/progress_tracker.py:180-250` (`pipeline_page_events` payload)
   - `services/ocr_json_export.py:340-420`
   - `services/review/repository.py:40-120` (`SELECT *` on pages)
   - `routes/review.py:68-120` (review payload assembly)
   - `database/models.py` (schema) and `database/db.py:1-120` (`init_db`, `MIGRATION_STATEMENTS`)
   - `frontend/lib/queries.ts:30-60` (what the frontend polls; you do not edit it, but the `/status` endpoint you add must satisfy it)

# Files you own

```text
services/google_vision_ocr.py
services/ocr_router.py
services/pipeline/persistence.py
services/pipeline/page_processing.py
services/pipeline/orchestrator.py
services/progress_tracker.py
services/ocr_json_export.py
services/report_generator.py
services/audit_service.py
services/retention.py
services/review/repository.py
routes/review_pages.py
database/models.py
tests/test_storage_budget.py
tests/test_retention.py
tests/fixtures/** (add only)
```

Do not edit: `database/db.py` (ws-b), `routes/review.py` (ws-b), `routes/upload.py` (ws-b/ws-c), `services/consistency_checks.py` and other ws-f files, anything under `frontend/`.

# Steps

## 1. Stop building `native`

In `services/ocr_router.py` remove `"native": ...` from both coercion sites
(`:465`, `:496`). Replace with a compact word layout:

```python
"words": [{"t": text, "b": [x0, y0, x1, y1], "c": conf}, ...]   # normalized 0-1, conf rounded to 2 dp
```

Build it in `services/google_vision_ocr.py` from the Vision `fullTextAnnotation`
words (page → blocks → paragraphs → words → symbols). Cap at 3,000 words per
page. Keep `text`, `confidence`, `language`, `structure_json` only if something
downstream reads them; grep for each key before deleting and delete dead ones.
`words` stays **in memory only** for this run (ws-f uses it to compute
evidence bboxes); it is not persisted.

## 2. Split `extracted_fields`

In `services/pipeline/page_processing.py` where `_classification`, `_triage`,
`_language`, `_structured_llm_classification`, and any other `_`-prefixed key is
put into `extracted_fields`, move them into `page["meta"]` instead.
`extracted_fields` ends up with business keys only. Search the repo for readers
of these private keys (`rg "_classification\"|_triage\"|_language\""`) and point
them at `page["meta"]` (or `pages_meta` when reading from the DB). If a reader is
in a file you do not own, list it under NEEDS-COORDINATION with the one-line
change needed; ws-f owns most of them and will have the same grep.

## 3. Schema (`database/models.py`)

- `pages`: drop `structured_content` and `image_path` from `CREATE TABLE`.
  (Fresh databases only; the archive SQLite is not migrated. Remove any
  `MIGRATION_STATEMENTS` in `database/db.py` that reference them — this is the
  one exception to the "do not edit db.py" rule, and only deletions of
  migration lines are allowed.)
- New `pages_meta(application_id, page_number, meta_json TEXT, PRIMARY KEY(application_id, page_number))`.
- `pipeline_page_events`: drop `extracted_fields`.
- `validation_results`: add `evidence_json TEXT`.
- `applications`: add `ops_summary_en TEXT`, `ops_summary_hi TEXT`, `ops_findings_json TEXT`.
- `pipeline_jobs`: add `max_attempts INTEGER NOT NULL DEFAULT 3`, `next_run_at TEXT`, `failure_reason TEXT`, `batch_id TEXT`.
- New `llm_calls(id INTEGER PRIMARY KEY, application_id INTEGER, provider TEXT, model TEXT, purpose TEXT, tokens_in INTEGER, tokens_out INTEGER, duration_ms INTEGER, est_cost_usd REAL, created_at TEXT)`.
- Drop table `exceptions` and its Pydantic model if unused (grep first).
- Indexes: `pages(application_id, page_number)`, `applications(created_at)`, `reviewer_decisions(decided_at)`, `pipeline_jobs(status, next_run_at)`, `llm_calls(application_id)`.

## 4. Persistence

- `_insert_page`: write the explicit column list, no `structured_content`. Write
  `pages_meta` in the same transaction from `page["meta"]`.
- `_load_page_checkpoints`: stop synthesising `ocr_structure` from
  `structured_content`; return `meta` from `pages_meta`.
- `orchestrator.py`: save `ground_truth` once (keep the later, complete one); do
  not write any PNG or OCR export at run end; do not call `init_db()`.
- `progress_tracker.py`: `pipeline_page_events` payload without `extracted_fields`.
- `ocr_json_export.py`: produce a single copy of each page (drop `raw_ocr_pages`
  and `page_details` duplicates or make them references by page number). It is
  now generated on demand only (route stays in `routes/review.py:306`, owned by
  ws-b; you only change the builder).
- `report_generator.py`, `audit_service.py`: remove any read of
  `structured_content`, `image_path`, `native`.

## 5. Read path

- `services/review/repository.py`: explicit column list; two functions:
  `load_pages_summary(application_id)` (no `ocr_text`, no meta) and
  `load_page_text(application_id, page_number)`.
- `routes/review_pages.py` (yours):
  - `GET /review/applications/{id}/status` → `{application_id, status, progress:{stage, percentage, completed_pages, total_pages}, updated_at, job:{id, status, attempt, failure_reason}}`. ≤ 5 KB. This will be what the frontend polls.
  - `GET /review/applications/{id}/pages/{n}/text` → `{page_number, ocr_text, ocr_confidence, document_type}`. Admin-only later (ws-d adds the dependency; leave a `# TODO(ws-d): require_role("admin")` comment).
- Make `routes/review.py`'s review payload stop including `ocr_text` by changing
  what `repository.py` returns (you own the repository, not the route). If the
  route spreads `**page` you may need a one-line change in `routes/review.py`;
  do it and note it under NEEDS-COORDINATION.

## 6. `init_db()` out of request handlers

`rg "init_db\(" routes services` — remove every call outside `main.py` startup
and tests. Do not edit files you do not own; list those call sites under
NEEDS-COORDINATION with the exact line to delete (ws-b/ws-c/ws-h will delete
them in their files). Delete the ones in your files.

## 7. Retention (`services/retention.py`)

`run_retention(now=None, dry_run=True) -> dict` with counts per action:

- delete `pipeline_job_inputs` for jobs with status `completed`;
- keep the newest `DMEF_RETENTION_JOB_ATTEMPTS` `pipeline_jobs` per application;
- delete `ocr_route_events`, `classification_review_log` older than `DMEF_RETENTION_TELEMETRY_DAYS`;
- delete `audit_log` rows older than the same period **unless** `action` is a user action or job lifecycle (define the allow-list as a module constant);
- mark applications older than `DMEF_RETENTION_SOURCE_DAYS` as `archived_at` set (add the column) — deleting source files from the object store is ws-b's `ObjectStore.delete`; call `get_store().delete(key)` for each `uploaded_files.storage_key` and `intake_packages.*_key` you find when `dry_run=False`.

Dialect-neutral SQL only (contracts §1): compute cut-off timestamps in Python.

## 8. Budget test (`tests/test_storage_budget.py`)

Use the existing fixture pipeline test pattern (see `tests/test_pipeline.py`)
with a small fixture set. Assert:

- no row in `pages` has a `structured_content` column; no serialized page
  contains the substring `"native"`;
- average serialized `pages` row ≤ 4 KB; `extracted_fields` has no `_` keys;
- `pipeline_page_events` has no `extracted_fields` column;
- `GET /review/applications/{id}` response text does not contain `"ocr_text"` or `"structured_content"`;
- `GET /review/applications/{id}/status` ≤ 5 KB;
- no `.png` written outside `DMEF_JOB_WORK_DIR` during the run (monkeypatch `DMEF_JOB_WORK_DIR` to `tmp_path`, then walk the repo `data/` dir and `PAGE_OUTPUT_DIR`).

# Done when

- [ ] All items in the budget test pass on the fixture run
- [ ] `rg "native" services/ database/` shows no persisted key
- [ ] `rg "init_db\(" routes services` returns only what you listed under NEEDS-COORDINATION
- [ ] `tests/test_retention.py` covers each retention action with `dry_run` True and False on a temp SQLite
- [ ] Full suite green; ruff clean; no frontend files touched

# Verify

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
python - <<'EOF'
import sqlite3, os
c = sqlite3.connect(os.environ.get("DATABASE_PATH", "data/dmef.db"))
print(c.execute("select avg(length(coalesce(ocr_text,'')) + length(coalesce(extracted_fields,''))) from pages").fetchone())
EOF
```

# PR description

Contracts §10 template, workstream `ws-a data diet`. Include the before/after
average page-row size from the fixture run.

# Stop conditions

Contracts §10. Additionally: if removing `structured_content` breaks a test in
`tests/test_review_*.py` or `tests/test_pipeline.py` because the test asserts on
the blob, update the test expectation (the blob is gone by design) and say so in
the PR.
