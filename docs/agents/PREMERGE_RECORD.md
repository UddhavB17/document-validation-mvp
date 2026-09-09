# PREMERGE_RECORD — pm-preflight (no-credential pre-merge checks)

- branch: `pm-preflight` at `d0e7c779` (`fx-cutover-repair` tip per brief)
- date (UTC): 2026-09-06T06:19:56Z
- credentials: skipped (no gcloud apply, no docker build, no alembic against Neon, no network outside pytest's existing skipifs)
- env for suite: `DMEF_LOCAL_STORE_DIR=/tmp/pm-preflight/store`, `DMEF_JOB_WORK_DIR=/tmp/pm-preflight/work`, `REPORT_OUTPUT_DIR=/tmp/pm-preflight/reports`

## 1. pytest

- command: `python -m pytest -q` (note: repo `pyproject.toml` already sets `addopts = "-q"`, so this runs at `-qq` and prints dots only)
- result: exit 0
- summary (`-q -q` prints no count line; same suite via `python -m pytest --tb=short`): **953 passed, 2 skipped** (~42–46 s, 30 warnings, all pre-existing deprecation/insecure-test-key warnings)
- skips (credential-gated, expected):
  - `tests/test_schema_parity.py:95`: `DATABASE_URL not set; Postgres parity checked in CI Postgres job`
  - `tests/test_storage.py:412`: `GCS integration needs DMEF_GCS_BUCKET`
- excerpt: dots to `[100%]`, then `warnings summary`, no failures/errors.

## 2. ruff

- command: `ruff check .`
- result: exit 0 — `All checks passed!`

## 3. npm (frontend)

- `npm --prefix frontend run typecheck` — exit 0 (`tsc --noEmit`, no errors)
- `npm --prefix frontend run lint` — exit 0 (`next lint`, `✔ No ESLint warnings or errors`)
- `npm --prefix frontend test` — exit 0 (`# pass 45, # fail 0`, `1..45`)

## 4. git diff --check

- command: `git diff --check`
- result: exit 0, no output (no whitespace errors)

## 5. alembic heads

- command: `alembic heads`
- result: exit 0, single head as expected:
  - `0005_batch_rejections (head)`

## 6. release dry-run

- command: `PROJECT_ID=my-proj REGION=asia-south1 TAG=v1.2.3 FRONTEND_HOST=unused bash scripts/release.sh --dry-run`
- result: exit 0
- tag check: `:v1.2.3` rendered (5 occurrences across api + frontend image lines and rendered manifests); literal `:TAG` occurrences: 0
- images:
  - `asia-south1-docker.pkg.dev/my-proj/dmef/api:v1.2.3`
  - `asia-south1-docker.pkg.dev/my-proj/dmef/frontend:v1.2.3`
- trailer line: `dry-run OK: image tag :v1.2.3 rendered, all placeholders substituted`

## 7. smoke dry-run

- command: `python scripts/smoke_batch.py --dry-run --api http://localhost:8000 --email a@b.c --password x --files tests/fixtures/smoke`
- result: exit 0, no network I/O:
  - `api: http://localhost:8000`, login as `a@b.c`, upload 2 file(s): `loan-a.pdf, loan-b.pdf`, poll `GET .../upload/batch/{id}`, ops check per completed item, timeout 1800 s

## 8. rg guards (all expect no match)

- `rg -n "CREATE TABLE IF NOT EXISTS batch_rejections" routes/` — no match (exit 1); schema lives in migrations/models, not HTTP layer
- `rg -n "export declare" frontend/lib/api.ts` — no match (exit 1)
- `rg -n "or True" tests/test_worker.py` — no match (exit 1)

## Verdict

PASS (no-credential scope). No product code changed. Only file added by this agent: `docs/agents/PREMERGE_RECORD.md`.
