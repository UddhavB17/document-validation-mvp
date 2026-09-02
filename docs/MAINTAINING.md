# Backend maintenance note

This note is the short map for contributors working on the Python backend.

## Module map

```text
main.py
  └── routes/                 HTTP validation, orchestration, and response serialization
        └── services/review/  review domain assembly and read-only repository boundary
services/pipeline/            extraction pipeline orchestration and persistence
services/{checklist_engine,consistency_checks,field_extractor,person_ownership}.py
                              compatibility facades for the existing validation imports
database/                     SQLite schema, migrations, connection lifecycle, and queries
services/paths.py             environment-driven database and filesystem locations
```

Routes should stay thin: validate request parameters, call a service, translate
expected domain errors to HTTP responses, and preserve the existing payload
keys. Review SQL belongs in `services/review/repository.py`; comparison,
document-summary, and worklist assembly belong in their matching service
modules. Keep the compatibility facades when moving implementation code so
older imports and monkeypatch targets continue to work.

The generated domain split from Cursor PR #21 is intentionally not part of the
maintained tree. Its generated extraction helper redeclared functions and the
large package move changed too much algorithm code for a safe consolidation.
The current pipeline and validation facades remain the behavior-preserving
source of truth.

## Runtime paths

All defaults are relative to the repository root and are resolved by
`services.paths`:

| Purpose | Environment variable | Default |
|---|---|---|
| SQLite database | `DATABASE_PATH` | `data/dmef.db` |
| Uploaded PDFs/packages | `UPLOAD_DIR` | `data/uploads` |
| Rendered pages and OCR JSON | `PAGE_OUTPUT_DIR` | `data/processed` |
| Reports | `REPORT_OUTPUT_DIR` | `data/reports` |
| Checklist definition | `CHECKLIST_JSON_PATH` | `data/checklist.json` |

The historical `DATABASE_URL=sqlite:///...` setting is still accepted for
older local `.env` files. Never commit real databases, credentials, uploaded
documents, or generated output. Existing sample and database files are kept
unless their disposal is explicitly proven safe.

## Setup and quality checks

Use the project-supported Python 3.11 environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m services.local_health --no-ollama
```

Before committing backend work, run:

```bash
python -m pytest -q
python -m compileall -q main.py database routes services tests
ruff check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
ruff format --check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
mypy services/paths.py services/review
git diff --check
```

The quality tools are listed in `requirements.txt`, so the documented install
and `setup.ps1` install the same tools used by these checks.
