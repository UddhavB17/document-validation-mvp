# DMEF Cloud Run deploy (ws-j)

Operator-run only. This agent produces configs; it never creates cloud
resources. All `PROJECT_ID`, `REGION`, `TAG`, `FRONTEND_HOST` placeholders
must be replaced by the operator before applying.

## Services

| Service | Image | Command | Scaling | Resources |
|---|---|---|---|---|
| `dmef-api` (`api.yaml`) | backend (`Dockerfile`) | `uvicorn main:app --host 0.0.0.0 --port 8080` | min 0, concurrency 20 | 2 CPU, 2 GiB |
| `dmef-worker` (`worker.yaml`) | same backend image | `python -m services.worker --serve-health 8080` | min 1, max 1, CPU always allocated | 4 CPU, 4 GiB, internal ingress only |
| `dmef-frontend` (no YAML; `scripts/release.sh` + `deploy.yml`) | `frontend/Dockerfile` (`output: 'standalone'`) | `node server.js` (port 3000) | min 0 | 1 CPU, 1 GiB |

Worker ingress is enforced in `worker.yaml` itself
(`metadata.annotations: {"run.googleapis.com/ingress": internal}`), applied
by `scripts/release.sh` via `gcloud run services replace` — no console click
needed. The API stays public (frontend + operator workstations reach it);
the worker accepts traffic only from inside the project VPC / other Cloud
Run services.

The worker's `--serve-health PORT` flag starts a minimal `GET /health`
server (worker heartbeat JSON) so Cloud Run probes pass even when no job
is running. The worker loop also updates the `worker_heartbeat` table
every 30 s when idle; `/health` reports it as
`"worker": {"last_heartbeat": ts, "status": "ok|stale"}` (stale > 2 min).

## Secrets (Secret Manager -> env, contracts §7)

Map each Secret Manager secret to the env name used in the YAMLs:

- `dmef-database-url-pooled` -> `DATABASE_URL` (pooled Neon endpoint, `?sslmode=require`)
- `dmef-gcs-bucket` -> `DMEF_GCS_BUCKET`
- `dmef-auth-secret` -> `DMEF_AUTH_SECRET` (HS256, 12 h expiry)
- `dmef-secrets-key` -> `DMEF_SECRETS_KEY` (Fernet; `DMEF_ENV=production` refuses to boot without it)
- `dmef-bootstrap-admin-email` / `dmef-bootstrap-admin-password` -> first admin on empty `users`
- `dmef-gemini-api-key` -> `GEMINI_API_KEY` (optional when ADC is available)

Service accounts:

- API/worker runtime: `roles/storage.objectAdmin` on the bucket,
  `roles/cloudvision.user` (Vision) + `roles/aiplatform.user` (Gemini),
  `roles/secretmanager.secretAccessor` on the secrets above.
- Scheduler invoker (`dmef-scheduler@...`): `roles/run.invoker` on `dmef-api`.

Frontend build arg: `NEXT_PUBLIC_API_BASE_URL=https://<api-host>`
(the brief calls this `NEXT_PUBLIC_API_URL`; the codebase name wins and the
Dockerfile honours both, with `NEXT_PUBLIC_API_URL` taking precedence).
It is baked in at **build** time (`.github/workflows/deploy.yml` passes it
as a Docker `--build-arg` when pushing
`${REGION}-docker.pkg.dev/${PROJECT_ID}/dmef/frontend:${TAG}`).
`scripts/release.sh` deploys that prebuilt, tag-matched frontend image with
`gcloud run deploy dmef-frontend --image …` — the same `:TAG` as the API —
and deliberately does **not** `--set-env-vars NEXT_PUBLIC_API_BASE_URL`,
because Next.js inlines `NEXT_PUBLIC_*` into the client bundle at build and
a runtime env var would be a silent no-op.

Validate placeholder substitution without credentials (no alembic, gcloud,
docker, or network):

```bash
PROJECT_ID=my-proj REGION=asia-south1 TAG=v1.2.3 bash scripts/release.sh --dry-run
```

## Release order (see `scripts/release.sh`)

1. `DATABASE_URL=<direct-Neon-endpoint> alembic upgrade head`
   (direct endpoint, never the `-pooler` host; see `docs/DEPLOY_NEON.md`).
2. Bootstrap-admin check (env present; creation happens on first API boot).
3. Deploy `dmef-api`, `dmef-worker`, frontend (Cloud Run).
4. `curl https://<api-host>/health` must show `database.status: ok`,
   `storage: ok`, `worker.status: ok|stale`.
5. `python scripts/smoke_batch.py --api https://<api-host> ... --files <10-pdfs>`.

## What cannot be validated here

- `gcloud run services replace api.yaml` needs project credentials; not run by the agent.
- `gcloud scheduler jobs create` needs the API URL + OIDC SA; the equivalent
  dry check is `python -c "import yaml; yaml.safe_load(open(...))"` plus the
  `dry_run=true` retention endpoint (see commit message).
- Cloud smoke against Neon + GCS needs credentials; run the same
  `smoke_batch.py` command from an operator workstation once provisioned and
  paste the table into the PR.
