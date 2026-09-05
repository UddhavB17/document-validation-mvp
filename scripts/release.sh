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
#   scripts/release.sh --dry-run
#     renders deploy/cloudrun/*.yaml with the placeholder substitution and
#     validates the tag, without touching alembic, gcloud, docker, or network.
#     Safe for agents and CI (see tests/test_release_script.py).
#
# The agent never runs this against cloud; the operator does after provisioning.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "release.sh: $*" >&2; exit 1; }

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: scripts/release.sh [--dry-run]"
      echo "  (no args)  migrate + deploy API, worker, frontend to Cloud Run"
      echo "  --dry-run  render deploy/cloudrun/*.yaml to stdout and validate the"
      echo "             image tag (no alembic, gcloud, docker, or network)"
      exit 0
      ;;
    *) fail "unknown argument: $arg (only --dry-run is supported)" ;;
  esac
done

build_images() {
  # Same tagged-image pattern deploy.yml pushes
  # (${REGION}-docker.pkg.dev/${PROJECT_ID}/dmef/<svc>:${TAG}).
  IMAGE="REGION-docker.pkg.dev/PROJECT_ID/dmef/api:TAG"
  IMAGE="${IMAGE/REGION/${REGION}}"
  IMAGE="${IMAGE/PROJECT_ID/${PROJECT_ID}}"
  IMAGE="${IMAGE/:TAG/:${TAG}}"
  FRONTEND_IMAGE="REGION-docker.pkg.dev/PROJECT_ID/dmef/frontend:TAG"
  FRONTEND_IMAGE="${FRONTEND_IMAGE/REGION/${REGION}}"
  FRONTEND_IMAGE="${FRONTEND_IMAGE/PROJECT_ID/${PROJECT_ID}}"
  FRONTEND_IMAGE="${FRONTEND_IMAGE/:TAG/:${TAG}}"
}

render_yaml() {
  # Substitute operator placeholders without editing the checked-in files.
  # NOTE: ':TAG' needs a real substitute (s|...|...|). A bare
  # `-e ":TAG"":${TAG}g"` is a sed *label*, not a substitution, and silently
  # leaves the literal ':TAG' in the rendered image.
  sed -e "s/PROJECT_ID/${PROJECT_ID}/g" \
      -e "s/REGION/${REGION}/g" \
      -e "s|:TAG|:${TAG}|g" \
      -e "s|REGION-docker.pkg.dev/PROJECT_ID/dmef/api:TAG|${IMAGE}|g" \
      "$1"
}

if [ "$DRY_RUN" = "1" ]; then
  # Validate placeholder substitution without credentials, docker, gcloud,
  # or network. Missing vars fall back to example values so bare
  # `bash scripts/release.sh --dry-run` works in CI.
  DATABASE_URL="${DATABASE_URL:-postgresql://operator:placeholder@localhost:5432/dmef?sslmode=require}"
  PROJECT_ID="${PROJECT_ID:-example-project}"
  REGION="${REGION:-asia-south1}"
  TAG="${TAG:-v0.0.0-dryrun}"
  build_images
  echo "==> release.sh --dry-run (no alembic, gcloud, or network)"
  echo "==> image: ${IMAGE}"
  echo "==> frontend image: ${FRONTEND_IMAGE}"
  TMPDIR_DRYRUN="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR_DRYRUN"' EXIT
  if [ -n "${FRONTEND_HOST:-}" ]; then
    render_yaml deploy/cloudrun/api.yaml | sed -e "s|https://FRONTEND_HOST|https://${FRONTEND_HOST}|g" > "$TMPDIR_DRYRUN/api.yaml"
  else
    render_yaml deploy/cloudrun/api.yaml > "$TMPDIR_DRYRUN/api.yaml"
  fi
  render_yaml deploy/cloudrun/worker.yaml > "$TMPDIR_DRYRUN/worker.yaml"
  echo "----- rendered deploy/cloudrun/api.yaml -----"
  cat "$TMPDIR_DRYRUN/api.yaml"
  echo "----- rendered deploy/cloudrun/worker.yaml -----"
  cat "$TMPDIR_DRYRUN/worker.yaml"
  leftovers="$(grep -n -e ':TAG' -e 'PROJECT_ID' "$TMPDIR_DRYRUN/api.yaml" "$TMPDIR_DRYRUN/worker.yaml" || true)"
  if [ -n "$leftovers" ]; then
    echo "release.sh --dry-run FAILED: unsubstituted placeholders remain:" >&2
    echo "$leftovers" >&2
    exit 1
  fi
  echo "dry-run OK: image tag :${TAG} rendered, all placeholders substituted"
  exit 0
fi

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

build_images
echo "==> image: ${IMAGE}"
echo "==> frontend image: ${FRONTEND_IMAGE}"

if [ "${SKIP_DEPLOY:-0}" = "1" ]; then
  echo "==> SKIP_DEPLOY=1: stopping after migrations + checks"
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || fail "gcloud not found; install Google Cloud SDK to deploy"

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

echo "==> deploying frontend (prebuilt ${FRONTEND_IMAGE})"
# NOTE: the frontend ships as the deploy.yml-built image
# (${REGION}-docker.pkg.dev/${PROJECT_ID}/dmef/frontend:${TAG}), NOT
# `gcloud run deploy --source .`. NEXT_PUBLIC_API_BASE_URL is inlined into
# the Next.js client bundle at *build* time (deploy.yml passes it as a
# --build-arg), so setting it here as a runtime --set-env-vars would be a
# silent no-op for the served UI and is intentionally not done.
gcloud run deploy dmef-frontend \
  --image "${FRONTEND_IMAGE}" \
  --region "$REGION" --project "$PROJECT_ID"

API_URL="https://${API_HOST:-}"
if [ -z "${API_HOST:-}" ]; then
  API_URL="$(gcloud run services describe dmef-api --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)')"
fi
echo "==> health: ${API_URL}/health"
curl -fsS --max-time 30 "${API_URL}/health" | python -m json.tool

echo "release OK. Next (operator):"
echo "  python scripts/smoke_batch.py --api ${API_URL} --email admin@example.com --password '...' --files <dir-with-10-pdfs> --timeout 1800"
