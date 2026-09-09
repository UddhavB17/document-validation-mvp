---
description: Wave 1 stream D. Users, roles (admin/operations), JWT auth, login page, Next middleware, admin user management, route protection.
mode: primary
---

You are the authentication agent. The application has no login. You add
email/password users with two roles, protect every backend route except
`/health` and `/auth/login`, and give the frontend a login page and middleware.
You do not build the role-aware navigation (ws-e does); you make it possible.

# Read first

1. `docs/agents/00-CONTRACTS.md` §1, §3, §6, §7, §9, §10
2. `services/auth/dependencies.py`, `routes/auth.py`, `routes/admin_users.py` (stubs from ws-0)
3. `main.py`, `routes/settings.py`, `routes/review.py:219-320` (job control + ocr-json), `routes/upload.py` router definition, `routes/decisions.py`, `routes/verification.py`
4. `frontend/app/layout.tsx`, `frontend/app/providers.tsx`, `frontend/lib/api.ts:1-80` (the `request` helper — you must attach the token here; append-only edits at the top are allowed for the fetch wrapper, coordinate by keeping the change to the single `headers` construction)
5. `frontend/components/AppShell.tsx` (read only; ws-e edits it)

# Files you own

```text
services/auth/**                      (dependencies.py, passwords.py, tokens.py, service.py, bootstrap.py)
database/auth_schema.py               (registered via schema_registry)
routes/auth.py
routes/admin_users.py
tests/test_auth.py
frontend/app/login/page.tsx
frontend/app/api/session/route.ts     (sets/clears the httpOnly cookie)
frontend/middleware.ts
frontend/lib/auth.ts                  (decode role from JWT payload client-side, logout helper)
```

Shared appends: `frontend/lib/api.ts` (token header in the request helper + `login` schema at the bottom), `.env.example` (already has the keys; fill defaults if missing), `main.py` (startup hook calling `bootstrap_admin()`).

You also add `Depends(require_role("admin"))` or `Depends(get_current_user)` to
routers owned by others. Do it at the **router level** (`APIRouter(dependencies=[...])`)
so the edit is a single line per file: `routes/settings.py`, `routes/review.py`,
`routes/upload.py`, `routes/decisions.py`, `routes/verification.py`,
`routes/ops.py`, `routes/review_pages.py`, `routes/storage.py` (if present). List
each line under NEEDS-COORDINATION so the owners see it at rebase.

# Steps

## 1. Schema (`database/auth_schema.py`)

```sql
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','user')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL,
  created_by INTEGER
);
CREATE TABLE IF NOT EXISTS user_passwords (
  user_id INTEGER PRIMARY KEY,
  password_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Register at import in `database/__init__.py` (one line). Booleans are Python
`True/False` in parameters (contracts §1).

## 2. Services

- `passwords.py`: bcrypt hash/verify; minimum length 10; reject the top-100
  common passwords list embedded as a constant.
- `tokens.py`: `issue(user) -> str`, `decode(token) -> {sub, email, role, exp}`;
  HS256 with `DMEF_AUTH_SECRET`; 12 h expiry; if the secret is missing raise at
  startup with a clear message (tests set it via `conftest` fixture).
- `service.py`: `authenticate(email, password)`, `create_user(...)`,
  `set_password(...)`, `deactivate(...)`, `list_users()`. Constant-time failure
  path (always run bcrypt even if the user does not exist).
- `dependencies.py`: `get_current_user` reads `Authorization: Bearer`, returns a
  `CurrentUser` dataclass; 401 on missing/invalid/expired/inactive.
  `require_role(*roles)` → 403. Admin satisfies any role check.
- `bootstrap.py`: `bootstrap_admin()` creates the first admin from
  `DMEF_BOOTSTRAP_ADMIN_EMAIL/PASSWORD` when `users` is empty; no-op otherwise;
  logs one line.
- Write an `audit_log` row for login success/failure, user create, password
  change, deactivate (use the existing `services/audit_service.py` API; do not edit it).

## 3. Routes

- `POST /auth/login {email, password}` → `{token, user:{id, email, display_name, role}}`; rate-limit 10/min per IP in memory.
- `GET /auth/me`, `POST /auth/logout` (no-op server side; the frontend clears the cookie), `POST /auth/change-password`.
- `GET/POST /admin/users`, `PATCH /admin/users/{id}` (display_name, role, is_active), `POST /admin/users/{id}/password` (admin reset). Admin only. An admin cannot deactivate themselves.
- Router-level dependencies per contracts §6 table. `/health` stays open.
  `/upload/*` is admin-only in this phase (operations users review, they do not upload).

## 4. Frontend

- `frontend/app/login/page.tsx`: email + password, error message, redirect to
  `/` on success. Plain form; styles consistent with existing components
  (Tailwind utility classes, no new hex colours).
- `frontend/app/api/session/route.ts`: `POST {token}` sets cookie `dmef_session`
  (httpOnly, sameSite=lax, secure in production, 12 h). `DELETE` clears it.
- `frontend/middleware.ts`: redirects to `/login` when the cookie is missing on
  every route except `/login`, `/_next`, `/api/session`. Does not check role
  (ws-e adds role-based redirects between `/ops` and `/admin`).
- Token flow (the cookie is httpOnly, so page code cannot read it directly):
  `GET /api/session` (same route handler) returns `{token, role}` from the cookie
  or 401. `frontend/lib/auth.ts` exposes `useSession()` (React context provided
  in `providers.tsx`) that loads the token once on mount and keeps it in memory.
  The `request` helper in `frontend/lib/api.ts` reads the in-memory token via a
  module-level getter `setAuthTokenProvider(fn)` and adds
  `Authorization: Bearer …`. That getter registration is your only edit to the
  helper.
- On 401 from the backend anywhere: `DELETE /api/session`, then redirect to `/login`.

## 5. Tests (`tests/test_auth.py`)

Bootstrap creates admin once; login success/failure; expired token; inactive
user; operations user gets 403 on `/settings`, 200 on `/review/worklist`;
admin can create operations user; user cannot deactivate self; every route in
`app.routes` except `/health`, `/auth/login`, `/docs`, `/openapi.json` returns
401 without a token (iterate `app.routes`, this test protects future routes).

# Done when

- [ ] The "every route requires auth" test passes
- [ ] Existing route tests pass with an `auth_headers` fixture added to `tests/conftest.py` that logs in as bootstrap admin (add the fixture; make it autouse **only if** fewer than ~10 tests need changes, otherwise add the header explicitly and list the files)
- [ ] Frontend: unauthenticated visit to `/` lands on `/login`; after login the worklist loads; refresh keeps the session
- [ ] `npm --prefix frontend run typecheck && ... lint && ... test` clean; ruff clean

# Verify

```bash
source .venv/bin/activate
DMEF_AUTH_SECRET=test DMEF_BOOTSTRAP_ADMIN_EMAIL=admin@example.com DMEF_BOOTSTRAP_ADMIN_PASSWORD='Str0ngPassw0rd!' python -m pytest -q
ruff check .
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test
```

# PR description

Contracts §10 template, workstream `ws-d auth`. Under NEEDS-COORDINATION list
every router-level dependency line you added to files you do not own.

# Stop conditions

Contracts §10. Additionally: if adding router-level auth breaks more than ~10
existing tests in ways an `auth_headers` fixture cannot fix, stop and describe.
