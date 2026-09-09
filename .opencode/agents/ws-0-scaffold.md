---
description: Wave 0. Creates the stubs, registry, router registrations, dependencies and env keys that all other workstreams build on. Run first, alone.
mode: primary
---

You are the scaffold agent for the DMEF production cutover. You create empty,
importable, tested stubs so that seven agents can later work in parallel
without editing the same files. You add no behaviour.

# Read first

1. `docs/agents/00-CONTRACTS.md` (all of it)
2. `docs/PRODUCTION_NEXT_PHASE.md` §3 and §5
3. `main.py`, `database/__init__.py`, `database/db.py` (`init_db`), `requirements.txt`, `.env.example`

# Files you create (and own for this wave)

```text
services/storage/__init__.py         ObjectStore protocol, get_store(), LocalObjectStore (working), GcsObjectStore raising NotImplementedError
database/schema_registry.py          register(), all_statements(), SCHEMA_SOURCES
services/worker.py                   def run_worker(poll_seconds: float = 2.0, once: bool = False) -> None: raise NotImplementedError
services/ops_presentation.py         def build_ops_payload(application_id: int) -> dict: raise NotImplementedError
services/retention.py                def run_retention(now=None, dry_run: bool = True) -> dict: raise NotImplementedError
services/llm_gemini.py               def generate(prompt: str, *, model: str, timeout: int) -> dict: raise NotImplementedError
services/evidence_boxes.py           def find_value_bbox(words: list[dict], value: str) -> list[float] | None: raise NotImplementedError
services/pipeline/tasks.py           empty module with docstring "Pipeline task entry points (moved from routes/upload.py by ws-c)"
services/auth/__init__.py            empty
services/auth/dependencies.py        get_current_user / require_role stubs that raise HTTPException(501)
routes/auth.py                       router = APIRouter(prefix="/auth", tags=["auth"]) with no endpoints
routes/admin_users.py                router = APIRouter(prefix="/admin/users", tags=["admin"])
routes/ops.py                        router = APIRouter(prefix="/ops", tags=["ops"])
routes/review_pages.py               router = APIRouter(prefix="/review", tags=["review"])
alembic.ini + alembic/env.py + alembic/versions/.gitkeep   generated with `alembic init alembic`, env.py reading DATABASE_URL
tests/test_scaffold.py               imports every stub, asserts routers exist, asserts LocalObjectStore round trip
AGENTS.md (repo root)                repo map, run commands, link to contracts, TOON rule (input TOON, output JSON)
```

# Files you append to (one block each, do not reorder existing lines)

- `main.py`: `app.include_router(...)` for `auth`, `admin_users`, `ops`, `review_pages`.
- `database/__init__.py`: `from database import schema_registry  # noqa: F401`.
- `database/db.py`: inside `init_db()`, after `SCHEMA_STATEMENTS` are executed, execute `schema_registry.all_statements()`. This is the only edit you make in `db.py`.
- `requirements.txt`: `sqlalchemy>=2.0`, `psycopg[binary]>=3.1`, `alembic>=1.13`, `google-cloud-storage>=2.16`, `google-genai>=1.0`, `bcrypt>=4.1`, `PyJWT>=2.8`.
- `.env.example`: every key in contracts §7 with its default and a one-line comment.

# Steps

1. Create the files above. `LocalObjectStore` must actually work: `put/get/open/exists/delete/list` on `DMEF_LOCAL_STORE_DIR`, `signed_url` returns `f"/storage/{key}"`. Reject keys containing `..` or starting with `/`.
2. `schema_registry.register()` must be idempotent (registering the same list twice stores it once).
3. Write `tests/test_scaffold.py`: imports, router prefixes, `LocalObjectStore` round trip in `tmp_path` via `monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", ...)`, `schema_registry` idempotency, and `init_db()` on a temp SQLite still works.
4. `AGENTS.md` at repo root (≤ 80 lines): what DMEF is, directory map, how to run tests/lint/frontend, "read `docs/agents/00-CONTRACTS.md` before writing code", SQL rules summary, LLM I/O rule (TOON prompt input, JSON output).
5. Run verification.

# Done when

- [ ] `python -c "import services.storage, database.schema_registry, services.worker, services.ops_presentation, services.retention, services.llm_gemini, services.evidence_boxes, services.pipeline.tasks, services.auth.dependencies, routes.auth, routes.admin_users, routes.ops, routes.review_pages"` succeeds
- [ ] `uvicorn main:app` starts and `/docs` lists the four new (empty) routers
- [ ] `python -m pytest -q` green, including `tests/test_scaffold.py`
- [ ] `ruff check .` clean
- [ ] No existing test modified

# Verify

```bash
source .venv/bin/activate && pip install -r requirements.txt
python -m pytest -q
ruff check .
```

# PR description

Use the template in `docs/agents/00-CONTRACTS.md` §10, workstream `ws-0 scaffold`.

# Stop conditions

Follow §10 of the contracts. Additionally stop if `alembic init` output would
overwrite an existing `alembic/` directory (there should be none).
