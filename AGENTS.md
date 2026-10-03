# AGENTS.md — DMEF production cutover

DMEF (Document Matching Early Finder) validates loan-file PDFs against a
product checklist and surfaces exceptions for human review. FastAPI backend
at the repo root (`main.py`, `routes/`, `services/`, `database/`), Next.js 14
frontend in `frontend/`. Python 3.11 only (use `.venv`).

**Read `docs/agents/00-CONTRACTS.md` before writing code.** It defines the DB
wrapper, object store, schema registry, job table, ops payload, auth/roles,
env vars, size budgets, and file ownership. Plan: `docs/PRODUCTION_NEXT_PHASE.md`.

## Directory map

- `main.py` — FastAPI app, router registration (append one line per stream)
- `routes/` — HTTP layer (thin; no SQL for new code)
- `services/` — domain logic; `services/storage/`, `services/auth/`, `services/worker.py`
- `services/pipeline/` — pipeline stages; task entry points in `tasks.py`
- `database/` — `db.py` wrapper, `models.py` (SQLite DDL), `schema_registry.py`
- `alembic/` — Postgres migrations (`DATABASE_URL`; empty = SQLite)
- `frontend/` — Next.js 14 app (`frontend/lib/api.ts`, `frontend/lib/queries.ts`)
- `tests/` — pytest suite (`python -m pytest -q`)

## Git delivery

When the user requests a push, deliver tested changes to `origin/main` unless
they explicitly choose another branch. Integrate the latest `origin/main`
and verify the combined changes first. Preserve divergent local work on a
backup branch; never force-push or publish fixes only to a `cursor/*` branch.

## Run commands

```bash
source .venv/bin/activate && pip install -r requirements.txt
python -m pytest -q
ruff check .
uvicorn main:app --reload --host 127.0.0.1 --port 8000
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test
```

## SQL rules (contracts §1, dialect-neutral)

- `?` placeholders only (wrapper translates to `%s` on Postgres); write literal `%` as `%%`
- `ON CONFLICT (...) DO NOTHING / DO UPDATE` — never `INSERT OR IGNORE/REPLACE`
- `INSERT ... RETURNING id` + `.fetchone()["id"]` — never `cursor.lastrowid`
- No `PRAGMA` / `sqlite_master`; pass ISO timestamps from Python (`datetime.now(UTC)`)
- JSON columns are `TEXT` (`json.dumps`); never query inside JSON in SQL
- Python `True`/`False` for booleans; rows support `row["col"]`, `dict(row)`

## LLM I/O rule

TOON for prompt input, JSON for model output. Env only via
`services/config.py` helpers or `services/paths.py` — no new `os.getenv` in
domain modules. Each brief owns its files; shared-append files (`main.py`,
`requirements.txt`, `.env.example`, `database/__init__.py`) take added lines
only, never reorders. On contract mismatch, add `NEEDS-COORDINATION` and stop.
