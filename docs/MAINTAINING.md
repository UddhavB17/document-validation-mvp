# Maintaining DMEF

This guide is for contributors and interns working in the repository. It describes how the project is laid out, how to run it locally, and what belongs in version control.

The browser UI is the Next.js app in `frontend/`. The legacy Streamlit UI has been removed.

## Project map

| Area | Location | Role |
|---|---|---|
| API entry point | `main.py` | FastAPI app, CORS, router registration, schema init |
| HTTP routes | `routes/` | Upload, review, verification, decisions, settings APIs |
| Business logic | `services/` | PDF/OCR pipeline, checklist, reports, LLM helpers |
| Database | `database/` | SQLite schema, migrations, connection helpers |
| Frontend | `frontend/` | Next.js 14 App Router UI (TypeScript, TanStack Query) |
| Shared config | `services/config.py` | Runtime tuning (profiles, thresholds, settings DB lookup) |
| Filesystem paths | `services/paths.py` | Upload, database, pipeline output, and checklist paths |
| Product data | `data/` | Checklist JSON, document-type registry, stamp-duty rules (tracked) |
| Tests | `tests/` | Backend pytest suite |
| Docs | `docs/` | Policies, examples, and maintainer notes |

## Running locally

### Prerequisites

- Python 3.11.x
- Node.js 20+

### Quick start

**Windows (PowerShell):**

```powershell
.\setup.ps1
.\run_local.ps1
```

**macOS / Linux:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env
```

Backend (terminal 1):

```bash
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Frontend (terminal 2):

```bash
cd frontend
npm run dev -- -p 3000
```

- UI: http://localhost:3000
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

`scripts/start_mvp.sh` is a macOS helper that also manages Ollama when local LLMs are enabled.

## Configuration precedence

1. **Shell / `.env` variables** — loaded by `python-dotenv` at process start.
2. **`system_settings` table** — for a small set of UI-managed keys (OCR provider, LLM toggles, classification profile). These win over a copied `.env` for the same key. See `services/config.py`.
3. **Code defaults** — used when neither env nor DB provides a value.

### Common path variables

Resolved in `services/paths.py`:

| Variable | Default | Used for |
|---|---|---|
| `DATABASE_PATH` | `data/dmef.db` | SQLite database file |
| `UPLOAD_DIR` | `data/uploads` | Uploaded PDFs and ZIP packages |
| `PAGE_OUTPUT_DIR` | `data/processed` | Per-application pipeline artifacts (page PNGs, OCR JSON) |
| `REPORT_OUTPUT_DIR` | `data/reports` | Generated Excel/JSON reports |
| `CHECKLIST_JSON_PATH` | `data/checklist.json` | Product checklist definition |

`DATABASE_URL=sqlite:///...` is still accepted when `DATABASE_PATH` is unset (legacy `.env` files).

Run `python -m services.local_health` after setup to verify Python, core packages, and configured paths.

## Where to add things

### New API route

1. Add or extend a module under `routes/` (for example `routes/review.py`).
2. Register the router in `main.py` with `app.include_router(...)`.
3. Add pytest coverage under `tests/` using `TestClient` or direct function calls with a temporary database (`monkeypatch.setattr(db, "DATABASE_PATH", ...)`).

### New service / pipeline step

1. Add logic under `services/` or `services/pipeline/`.
2. Call it from the relevant route or from `services/pipeline/orchestrator.py`.
3. Keep deterministic validation separate from optional LLM helpers.

### New frontend screen or component

1. Add pages under `frontend/app/`.
2. Add shared UI under `frontend/components/`.
3. Add API helpers in `frontend/lib/api.ts` and query hooks in `frontend/lib/queries.ts` as needed.
4. Point the UI at the backend with `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://127.0.0.1:8000`).

## Running checks

Backend (from repo root with `.venv` active):

```bash
pytest
python -m compileall -q main.py database routes services tests
git diff --check
```

Frontend (from `frontend/`):

```bash
npm run typecheck
npm run lint
npm run build
```

## What not to commit

- Real loan files, customer data, or production credentials
- `.env` (only `.env.example` is tracked)
- Local SQLite databases and WAL/SHM sidecars (`data/*.db`, `data/dmef.db-*`)
- Uploaded PDFs, rendered page images, generated reports (`data/uploads/`, `data/processed/`, `data/reports/`)
- API keys, service-account JSON, or encryption keys
- `node_modules/`, `.venv/`, `.next/`, and pytest cache directories

Tracked files under `data/` are product configuration (checklist, document registry, stamp-duty rules), not runtime output.

### Backing up a local database

If you have useful rows in `data/dmef.db` before resetting or switching branches:

```bash
cp data/dmef.db data/dmef.db.backup-$(date +%Y%m%d)
```

Keep backups outside Git. The repository previously tracked disposable backup files; new clones should create a fresh database via `setup.ps1` or the first backend start (`database/models.py` initializes schema).

## Related docs

- `README.md` — product overview and OCR setup
- `run.md` — local run commands and troubleshooting
- `docs/multilingual_document_policy.md` — language/script handling policy
