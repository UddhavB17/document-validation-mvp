# Deploy DMEF on Neon PostgreSQL (ws-i postgres cutover)

This is the production database path. SQLite remains the local dev/test
default (empty `DATABASE_URL`); Neon is a managed PostgreSQL used for
staging and production.

## 1. Create the Neon project

1. Create a new Neon project (region closest to the API host).
2. Create the `dmef` database (or keep the default `neondb` and use it).
3. In the Neon dashboard, copy the connection strings. Neon exposes two
   endpoints per branch:
   - **Pooled** (PgBouncer, `...-pooler.` host): for the API runtime.
   - **Direct** (no pooler): for migrations.

## 2. Configure the API

```bash
# Pooled endpoint for the running API (reduces connection churn).
DATABASE_URL=postgresql://<user>:<password>@<pooled-host>/<db>?sslmode=require
```

`database/db.py` uses `pool_pre_ping=True`, so stale pooled connections
are recycled transparently. Keep `?sslmode=require` on Neon.

```bash
DMEF_BOOTSTRAP_ADMIN_EMAIL=admin@example.com
DMEF_BOOTSTRAP_ADMIN_PASSWORD=<long-random-password>
```

On first boot with an empty `users` table these create the first admin
(contracts §6). Rotate the password after login.

## 3. Create the schema (release step)

Migrations must use the **direct** endpoint: PgBouncer in transaction mode
does not support the advisory locks DDL relies on.

```bash
# Direct endpoint for alembic (note: no -pooler host).
DATABASE_URL=postgresql://<user>:<password>@<direct-host>/<db>?sslmode=require \
  alembic upgrade head
```

`alembic/versions/0001_baseline.py` is the baseline translated from the
final SQLite schema plus the `llm_calls` / `object_refs` registry modules.
`init_db()` on Postgres is a connectivity check only; the schema always
comes from `alembic upgrade head` (run as a release step, see ws-j).

Verify the baseline (`alembic check` is unsupported here — it needs
autogenerate metadata and `alembic/env.py` sets `target_metadata = None`):
compare the applied revision against the known head instead.

```bash
DATABASE_URL=...?sslmode=require alembic heads     # latest known head(s)
DATABASE_URL=...?sslmode=require alembic history   # changelog for review
DATABASE_URL=...?sslmode=require alembic current   # applied revision(s)
# `current` must list the same revision as `heads` after `upgrade head`.
```

## 4. Verify with /health

```bash
curl -s https://<api-host>/health | python3 -m json.tool
```

Expected (Postgres):

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "ok",
  "database_dialect": "postgresql",
  "storage": "ok",
  "worker": {"last_heartbeat": "2026-09-05T00:00:00+00:00", "status": "ok"}
}
```

The frontend `healthSchema` (`frontend/lib/api.ts`) only requires
`status`/`version`, so the extra keys are ignored by the UI. `database` is
always a string (`"ok"`/`"error"`); the dialect lives in the top-level
`"database_dialect"` key. `worker.status` is `"stale"` when the heartbeat
is older than 2 minutes.

## 5. Neon notes

- **Pooled vs direct**: API traffic → pooled; `alembic upgrade/downgrade`,
  one-off backfills, and `psql` → direct.
- **`pool_pre_ping`**: already enabled in `database/db.py` and the test
  fixture; leave it on for pooled endpoints.
- **Autosuspend + worker poll**: Neon suspends idle compute; the first
  query after suspend pays a cold-start (typically a few seconds). The
  durable worker polls with `run_worker(poll_seconds=2.0)` by default;
  in production set `poll_seconds=5` to reduce wake-ups and expect the
  first poll after idle to take longer. The 2 s default is for local dev
  responsiveness, not for suspended Neon branches.
- **Local parity**: the same baseline runs against
  `docker-compose.dev.yml` Postgres
  (`DATABASE_URL=postgresql://dmef:dmef@localhost:5432/dmef alembic upgrade
  head`, then `python -m pytest -q`). CI runs the full suite on both
  SQLite and Postgres; both jobs are required.
