#!/usr/bin/env bash
# DMEF release script (owned by ws-j-deploy-smoke; operator only).
#
# 1. `alembic upgrade head` against the DIRECT Neon endpoint
#    (never the -pooler host; see docs/DEPLOY_NEON.md).
# 2. Bootstrap-admin env check (creation happens on first API boot).
# 3. Deploy the API, worker, and frontend Cloud Run services.
# 4. Health check + smoke hint.
#
# Required env:
#   DATABASE_URL            direct Neon URL (?sslmode=require, no "-pooler")
#   PROJECT_ID              GCP project id
#   REGION                  GCP region, e.g. asia-south1
#   TAG                     image tag, e.g. v0.1.0 (deploy.yml uses github.ref_name)
# Optional env:
#   API_HOST                e.g. https://dmef-api-...a.run.app (else derived after deploy)
#   FRONTEND_HOST           public frontend host for CORS_ORIGINS
#   SKIP_DEPLOY=1           run migrations + checks only
#   SKIP_MIGRATE=1          deploy only (not recommended)
#
# The agent never runs this against cloud; the operator does after provisioning.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "release.sh: $*" >&2; exit 1; }

: "${DATABASE_URL:?Set DATABASE_URL to the DIRECT Neon endpoint (?sslmode=require)}"
: "${PROJECT_ID:?Set PROJECT_ID}"
: "${REGION:?Set REGION, e.g. asia-south1}"
: "${TAG:?Set TAG, e.g. v0.1.0}"

case "$DATABASE_URL" in
  *"-pooler."*)
    fail "DATABASE_URL looks like the pooled endpoint (-pooler host). Use the DIRECT endpoint for alembic."
    ;;
esac
case "$DATABASE_URL" in
  *"sslmode=require"*) ;;
  *) echo "release.sh: warning: DATABASE_URL has no ?sslmode=require (Neon needs it)" >&2 ;;
esac

command -v alembic >/dev/null 2>&1 || fail "alembic not found (source .venv/bin/activate)"
command -v python >/dev/null 2>&1 || fail "python not found"

if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  echo "==> alembic upgrade head (direct endpoint)"
  alembic upgrade head
  echo "==> alembic current"
  alembic current
else
  echo "==> SKIP_MIGRATE=1: skipping alembic upgrade head"
fi

if [ -z "${DMEF_BOOTSTRAP_ADMIN_EMAIL:-}" ] || [ -z "${DMEF_BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
  echo "release.sh: warning: DMEF_BOOTSTRAP_ADMIN_EMAIL/PASSWORD not set; first-admin bootstrap happens on API boot only when both are present" >&2
else
  echo "==> bootstrap admin env present for ${DMEF_BOOTSTRAP_ADMIN_EMAIL}"
fi

IMAGE="REGION-docker.pkg.dev/PROJECT_ID/dmef/api:TAG"
IMAGE="${IMAGE/REGION/${REGION}}"
IMAGE="${IMAGE/PROJECT_ID/${PROJECT_ID}}"
IMAGE="${IMAGE/:TAG/:${TAG}}"
echo "==> image: ${IMAGE}"

if [ "${SKIP_DEPLOY:-0}" = "1" ]; then
  echo "==> SKIP_DEPLOY=1: stopping after migrations + checks"
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || fail "gcloud not found; install Google Cloud SDK to deploy"

render_yaml() {
  # Substitute operator placeholders without editing the checked-in files.
  sed -e "s/PROJECT_ID/${PROJECT_ID}/g" \
      -e "s/REGION/${REGION}/g" \
      -e ":TAG"":${TAG}g" \
      -e "s|REGION-docker.pkg.dev/PROJECT_ID/dmef/api:TAG|${IMAGE}|g" \
      "$1"
}

TMPDIR_RELEASE="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RELEASE"' EXIT

if [ -n "${FRONTEND_HOST:-}" ]; then
  render_yaml deploy/cloudrun/api.yaml | sed -e "s|https://FRONTEND_HOST|https://${FRONTEND_HOST}|g" > "$TMPDIR_RELEASE/api.yaml"
else
  echo "release.sh: warning: FRONTEND_HOST unset; leaving https://FRONTEND_HOST placeholder in api.yaml" >&2
  render_yaml deploy/cloudrun/api.yaml > "$TMPDIR_RELEASE/api.yaml"
fi
render_yaml deploy/cloudrun/worker.yaml > "$TMPDIR_RELEASE/worker.yaml"

echo "==> deploying dmef-api"
gcloud run services replace "$TMPDIR_RELEASE/api.yaml" --region "$REGION" --project "$PROJECT_ID"
echo "==> deploying dmef-worker"
gcloud run services replace "$TMPDIR_RELEASE/worker.yaml" --region "$REGION" --project "$PROJECT_ID"

echo "==> deploying frontend (frontend/Dockerfile, standalone)"
gcloud run deploy dmef-frontend \
  --source . \
  --dockerfile frontend/Dockerfile \
  --region "$REGION" --project "$PROJECT_ID" \
  --set-env-vars "NEXT_PUBLIC_API_BASE_URL=https://${API_HOST:-API_HOST_UNSET}"

API_URL="https://${API_HOST:-}"
if [ -z "${API_HOST:-}" ]; then
  API_URL="$(gcloud run services describe dmef-api --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)')"
fi
echo "==> health: ${API_URL}/health"
curl -fsS --max-time 30 "${API_URL}/health" | python -m json.tool

echo "release OK. Next (operator):"
echo "  python scripts/smoke_batch.py --api ${API_URL} --email admin@example.com --password '...' --files <dir-with-10-pdfs> --timeout 1800"
