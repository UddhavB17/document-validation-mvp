# Maintaining DMEF

This note is the backend contributor map. Start with the
[`README.md`](../README.md) quickstart, then use this file for ownership,
runtime paths, and quality checks. Keep the MVP behavior-preserving: prefer a
small focused change over a broad package move.

## Backend architecture

```mermaid
flowchart TD
    Main[main.py\nFastAPI app and lifespan] --> Routes[routes/\nHTTP boundaries]
    Routes --> Upload[routes/upload.py\nintake and job queue]
    Routes --> ReviewRoutes[routes/review.py\nworklist and evidence]
    Routes --> Verify[routes/verification.py\nreports and checklist]
    Routes --> Decisions[routes/decisions.py]
    Routes --> Settings[routes/settings.py]
    Upload --> Pipeline[services/pipeline/\npage pipeline and persistence]
    ReviewRoutes --> ReviewServices[services/review/\nrepository, worklist, summaries, comparison]
    Pipeline --> Domain[services/\nOCR, extraction, classification, checklist, reports]
    Pipeline --> Database[(database/\nSQLite schema and connections)]
    ReviewServices --> Database
    Pipeline --> Runtime[(data/\nuploads, processed pages, reports)]
```

### Ownership rules

- `main.py` owns application wiring, lifespan initialization, CORS, and the
  small `/health` endpoint. It should not own document-processing logic.
- `routes/` validates request parameters, calls a service, and translates
  expected domain errors to HTTP responses. Preserve existing response keys
  when changing a route.
- `services/pipeline/` is the current source of truth for processing order,
  checkpoints, persistence, and pipeline outcomes.
- `services/review/repository.py` owns review SQL. Worklist, comparison, and
  document-summary assembly belongs in the matching `services/review/` module.
- Field extraction (`services/field_extractor.py`), cross-document consistency
  checks (`services/consistency_checks.py`), and trusted-manifest verification
  (`services/mapped_verification.py`) are active implementation modules with
  their own unit tests — not facades. Keep their public function names stable:
  other modules and tests import them directly.
- `database/` owns schema statements, connections, and shared data models.
  `services/paths.py` is the single source for environment-driven filesystem
  locations.
- `frontend/` is a separate Next.js application. Backend changes that alter a
  payload must be checked against `frontend/lib/api.ts` and its consumers.

The generated domain split described in older planning notes is not the
maintained source of truth. Do not reintroduce a large generated package move
without a separate, tested migration plan.

## Runtime paths

Paths default relative to the repository root and are resolved by
`services.paths`:

| Purpose | Environment variable | Default |
|---|---|---|
| SQLite database | `DATABASE_PATH` | `data/dmef.db` |
| Uploaded PDFs and ZIP packages | `UPLOAD_DIR` | `data/uploads` |
| Rendered pages and OCR JSON | `PAGE_OUTPUT_DIR` | `data/processed` |
| Reports | `REPORT_OUTPUT_DIR` | `data/reports` |
| Checklist definition | `CHECKLIST_JSON_PATH` | `data/checklist.json` |
| Object store (durable files) | `DMEF_LOCAL_STORE_DIR` | `data/store` |
| Per-job working directory (deleted in a `finally` after each run) | `DMEF_JOB_WORK_DIR` | `/tmp/dmef-jobs` |
| Secrets key for encrypted settings and recovery payloads | `DMEF_SECRETS_KEY` | none (ephemeral in-memory key outside production; startup fails when `DMEF_ENV=production`) |

Durable file layout follows the object-store key scheme and the worker
process (`services/worker.py`, which polls `pipeline_jobs`) in
[`docs/agents/00-CONTRACTS.md`](agents/00-CONTRACTS.md) §§2–4. That contracts
file is the cross-workstream source of truth for the DB wrapper, storage
backends, schema registry, job table, ops payload, auth/roles, env vars, and
budgets; this note only maps the backend code.

The legacy `DATABASE_URL=sqlite:///...` value is still accepted for older local
`.env` files. Runtime databases, uploads, rendered pages, OCR output, reports,
logs, credential files, and `.env` are ignored by Git, but they still need
careful handling. Existing sample/data artifacts are not disposable merely
because they are local; confirm ownership before removing anything.

## Configuration boundaries

- Google Vision is the normal OCR provider for scanned pages. Digital PDF text
  is extracted without an OCR API call.
- Local PaddleOCR is intentionally isolated behind
  `DMEF_LOCAL_OCR_TEST_MODE=true` and is not installed by `requirements.txt`.
- LLM providers are optional. `LLM_PROVIDER=none` is the explicit no-LLM mode;
  `auto` chooses an API-compatible provider when a key exists and otherwise
  chooses Ollama. Do not put keys in source, tests, fixtures, or documentation.
- The Settings UI writes selected settings to the configured database. Secret
  values are masked in API responses; do not infer that masking makes the local
  database safe to share.
- When changing a setting, check both `.env.example` and the database-backed
  setting path. Non-empty environment values take precedence over UI-managed
  database settings.

## Setup and health check

Use the root README quickstart. For a backend-only check with an active Python
3.11 environment:

```bash
python -m services.local_health --no-ollama --fail-on-error
```

This checks the Python minor version, importable PyMuPDF and Google Vision
modules, configured paths, and the checklist file. It does not authenticate to
Google Vision, run OCR, or validate an Ollama model. A fresh checkout may show
warnings until FastAPI creates the SQLite schema and processed-page directory.

## Quality checks before a backend commit

Run from the repository root with `.venv` active:

```bash
python -m pytest -q
python -m compileall -q main.py database routes services tests
ruff check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
ruff format --check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
mypy services/paths.py services/review
git diff --check
```

For frontend-facing changes, also run from the repository root:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

On Windows PowerShell, use `npm.cmd --prefix frontend ...` and
`python -m ...` after activating `.venv`. These checks use the tools listed in
`requirements.txt` and the scripts listed in `frontend/package.json`.

## Safe change workflow

1. Read the relevant route/service and its tests before editing.
2. Keep observed document values, resolved metadata, and trusted input separate.
   Do not make trusted JSON overwrite observed OCR evidence.
3. Add or update focused tests for runtime behavior; do not use live Google,
   Ollama, or other external services in tests.
4. Run the smallest relevant check while iterating, then run the full checks
   above before committing.
5. Inspect `git status --short --ignored`, `git diff --check`, and staged diff
   content for documents, identifiers, secrets, and generated output.

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the contributor checklist.
