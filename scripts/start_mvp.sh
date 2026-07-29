#!/usr/bin/env bash
# Opt-in low-memory launcher for ~8GB laptops.
# Default local run is full power: copy .env.example → .env and use uvicorn + npm.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/logs

lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill -9 2>/dev/null || true
lsof -tiTCP:3000 -sTCP:LISTEN | xargs kill -9 2>/dev/null || true
sleep 1

# shellcheck disable=SC1091
source .venv/bin/activate
export DMEF_LOW_MEMORY=true
export ENABLE_LLM_PAGE_CLASSIFIER=false
export OCR_FORCE_FAST_PATH=true

nohup env DMEF_LOW_MEMORY=true OCR_FORCE_FAST_PATH=true ENABLE_LLM_PAGE_CLASSIFIER=false \
  python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 \
  > data/logs/uvicorn.log 2>&1 &
disown $! 2>/dev/null || true
echo "API pid=$! → http://127.0.0.1:8000"

cd frontend
nohup env NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
  npm run dev -- -p 3000 -H 127.0.0.1 \
  > ../data/logs/frontend.log 2>&1 &
disown $! 2>/dev/null || true
echo "Frontend pid=$! → http://127.0.0.1:3000"

sleep 4
curl -sf http://127.0.0.1:8000/health && echo
curl -sf -o /dev/null -w "frontend HTTP %{http_code}\n" http://127.0.0.1:3000/ || true
