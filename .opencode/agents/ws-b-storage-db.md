---
description: Wave 1 stream B. Object storage (local + GCS), dialect-aware database wrapper, alembic skeleton, uploads and evidence pages through the store, Dockerfile, CI Postgres job.
mode: primary
---

You are the storage-and-database agent. Files currently land in the project
folder and the database is SQLite. You make every file go through an
`ObjectStore`, and make `get_connection()` speak both SQLite and PostgreSQL
without changing how callers use it.

# Read first

1. `docs/agents/00-CONTRACTS.md` §1, §2, §7, §9, §10
2. `services/storage/__init__.py` (stub from ws-0; `LocalObjectStore` already works)
3. `database/db.py` (all), `database/models.py:1-60`
4. `services/paths.py`, `.env.example`
5. `routes/upload.py:60-95` (`_save_upload_stream`), `:229-330` (zip package upload), `:554-740` (`_save_mapped_zip_package`, `_persist_intake_package`), `:924-1065` (`upload_file`)
6. `services/zip_package.py`, `services/pdf_processor.py` (where pages are rendered and where to)
7. `routes/review.py:121-213` (`source-pdf`, `source-page` — serve from the store)
8. `services/pipeline/input_preparation.py` (how the pipeline receives file paths)

# Files you own

```text
services/storage/**
database/db.py
alembic/**, alembic.ini
services/paths.py
routes/upload.py            (only the file-saving code paths; ws-c owns batch endpoints and _run_*_task functions — coordinate by keeping your edits to _save_upload_stream, _save_mapped_zip_package, _persist_intake_package, upload_zip_package, upload_mapped_file, upload_file file-handling lines)
services/zip_package.py
services/pdf_processor.py
services/pipeline/input_preparation.py
routes/review.py            (source-pdf, source-page, ocr-json routes only)
routes/storage.py           (new: GET /storage/{key} for the local backend, admin-only later)
Dockerfile, .dockerignore
docker-compose.dev.yml
.github/workflows/ci.yml    (add a postgres job; allowed to fail until ws-i)
tests/test_storage.py, tests/test_db_wrapper.py
```

# Steps

## 1. Database wrapper (`database/db.py`)

- Build a SQLAlchemy `Engine` from `DATABASE_URL`; when empty, `sqlite:///{DATABASE_PATH}`.
  Keep `check_same_thread=False` and WAL for SQLite. Use `pool_pre_ping=True` for Postgres.
- `get_connection()` yields a `Connection` wrapper with `.execute(sql, params=())`
  translating `?` → `%s`-style bound parameters (use `sqlalchemy.text` with
  positional → named conversion: replace the n-th `?` with `:p{n}`; skip `?`
  inside string literals). Return a cursor-like object exposing `.fetchone()`,
  `.fetchall()`, `.rowcount`, with rows supporting `row["col"]`, `dict(row)`,
  `row.keys()` (`sqlalchemy.engine.Row._mapping` does this; wrap it).
- Commit on exit, rollback on exception. `executemany` support via a list of tuples.
- `init_db()`: run `SCHEMA_STATEMENTS` + `schema_registry.all_statements()` only
  when `DATABASE_URL` is empty (SQLite dev/test). On Postgres, `init_db()` does
  nothing except verify connectivity; schema comes from alembic (ws-i writes the
  baseline). Keep the seed of `system_settings` defaults behind a
  `seed_defaults()` function that is dialect neutral (`ON CONFLICT DO NOTHING`).
- Delete the `PRAGMA`/`sqlite_master`-based `MIGRATION_STATEMENTS` mechanism.
  Databases are created fresh; there is no migration of the archive.
- Add `dialect() -> "sqlite" | "postgresql"` for the rare caller that must branch (ws-c's worker).

## 2. GCS store (`services/storage/gcs.py`)

Implement `GcsObjectStore` for the protocol in contracts §2 using
`google-cloud-storage` and ADC. `signed_url` uses V4 signing with
`expires_seconds`. `open()` returns `blob.open("rb")`. `get_store()` picks by
`DMEF_STORAGE_BACKEND`. Integration test `tests/test_storage.py::test_gcs_roundtrip`
is `skipif` when `DMEF_GCS_BUCKET` is unset.

## 3. Uploads through the store

In `routes/upload.py` replace disk writes with:

```python
store = get_store()
key = f"applications/{application_id}/source/{_safe_name(file.filename)}"
store.put(key, await file.read() or stream, file.content_type or "application/octet-stream")
```

Do not add columns to `database/models.py` (ws-a owns it). Instead create
`database/storage_schema.py`, registered through `schema_registry`, with one table:

```sql
CREATE TABLE IF NOT EXISTS object_refs (
  id INTEGER PRIMARY KEY,
  owner_table TEXT NOT NULL,      -- 'applications' | 'intake_packages'
  owner_id TEXT NOT NULL,
  purpose TEXT NOT NULL,          -- 'source' | 'manifest' | 'normalized_pdf' | 'ocr_export' | 'report'
  storage_key TEXT NOT NULL UNIQUE,
  content_type TEXT,
  size_bytes INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_object_refs_owner ON object_refs(owner_table, owner_id);
```

Provide `services/storage/refs.py` with `record_ref(...)`, `get_ref(owner_table, owner_id, purpose)`,
`list_refs(owner_table, owner_id)`. Retention (ws-a) and the pipeline read keys
from here. Legacy `file_path` columns are no longer written.

For ZIP intake: upload the ZIP to `applications/{id}/source/...` (or
`intake/{package_id}/...` before an application exists), extract in
`DMEF_JOB_WORK_DIR/{package_id}` only, upload the selected PDF as
`normalized_pdf`, delete the work dir in `finally`.

## 4. Pipeline input

`services/pipeline/input_preparation.py`: given an application id, fetch the
`source` (or `normalized_pdf`) key from `object_refs`, download to
`DMEF_JOB_WORK_DIR/{job_id}/source.pdf`, hand that path to the existing pipeline
code, delete the directory when the pipeline returns (success or failure).
`services/pdf_processor.py`: render pages under the job work dir, never under
`PAGE_OUTPUT_DIR`; delete `PAGE_OUTPUT_DIR` usage from `services/paths.py` once
nothing reads it (grep).

## 5. Evidence serving

`routes/review.py`:

- `source-pdf`: stream from `store.open(key)` with `StreamingResponse`; no `FileResponse` of DB paths.
- `source-page/{n}`: download the PDF to a temp file (or open from store), render page `n` with the existing renderer at the requested DPI, return PNG bytes, cache in memory with an LRU of 64 pages keyed by `(application_id, page, dpi)`.
- `ocr-json`: build on demand via `services.ocr_json_export`, upload to `applications/{id}/ocr-export.json` with purpose `ocr_export`, return the JSON.

`routes/storage.py`: `GET /storage/{key:path}` serving `LocalObjectStore` objects
(reject `..`). Add `# TODO(ws-d): require_role("admin")`.

## 6. Dev and CI

- `docker-compose.dev.yml`: `postgres:16` with `dmef/dmef` and a volume.
- `Dockerfile`: python 3.11-slim, system deps needed by the existing OCR/PDF
  stack (check `requirements.txt` for `pdf2image`/poppler, `opencv`), two entry
  commands documented in a comment: `uvicorn main:app --host 0.0.0.0 --port 8080`
  and `python -m services.worker`.
- `.github/workflows/ci.yml`: existing job unchanged; add `tests-postgres` with a
  `postgres:16` service and `DATABASE_URL=postgresql://...`; `continue-on-error: true`
  with a comment `# ws-i makes this required`.

## 7. Tests

- `tests/test_db_wrapper.py`: `?` translation with literals containing `?`,
  `RETURNING id`, rollback on exception, `dict(row)`, `executemany`.
- `tests/test_storage.py`: local round trip, key validation, `object_refs` helper,
  upload route stores a key and no file appears under `data/uploads`.

# Done when

- [ ] `python -m pytest -q` green with default env (SQLite + local store)
- [ ] `DATABASE_URL=postgresql://dmef:dmef@localhost:5432/dmef python -m pytest -q tests/test_db_wrapper.py tests/test_storage.py tests/test_database.py` green against docker-compose Postgres (other tests may still fail on Postgres; that is ws-i)
- [ ] Uploading a PDF and a ZIP through the API writes nothing under `data/uploads` or `data/pages`
- [ ] `rg "FileResponse" routes/` returns nothing
- [ ] `rg "PAGE_OUTPUT_DIR|UPLOAD_DIR" --type py` returns only `services/paths.py` compatibility shims or nothing
- [ ] ruff clean

# Verify

```bash
source .venv/bin/activate
docker compose -f docker-compose.dev.yml up -d
python -m pytest -q
DATABASE_URL=postgresql://dmef:dmef@localhost:5432/dmef python -m pytest -q tests/test_db_wrapper.py tests/test_storage.py tests/test_database.py
ruff check .
```

# PR description

Contracts §10 template, workstream `ws-b storage + db`. List every `routes/upload.py`
line range you touched so ws-c can rebase cleanly.

# Stop conditions

Contracts §10. Additionally: if a `?` in existing SQL cannot be translated
safely (e.g. inside a JSON literal), rewrite that statement to use a bound
parameter and note it.
