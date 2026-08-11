#!/usr/bin/env bash
# Laptop-friendly launcher for ~8GB Macs.
# OCR remains API-backed. A small local Ollama model is reserved for Unknown
# and low-OCR-confidence page classification; broader LLM tasks stay disabled.
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
export ENABLE_LLM_PAGE_CLASSIFIER=true
export ENABLE_STRUCTURED_LLM_CLASSIFIER=true
export LLM_PROVIDER=ollama

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is required but was not found. Install Ollama, then rerun this launcher." >&2
  exit 1
fi

if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  nohup ollama serve > data/logs/ollama.log 2>&1 &
  OLLAMA_PID=$!
  disown "$OLLAMA_PID" 2>/dev/null || true
  echo "Ollama pid=$OLLAMA_PID -> http://127.0.0.1:11434"
  for _attempt in {1..30}; do
    if curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
      break
    fi
    sleep 1
  done
fi

if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama did not become ready. See data/logs/ollama.log." >&2
  exit 1
fi

OLLAMA_MODELS="$(
  python -c 'from services.llm_client import llm_model; from services.structured_llm_classifier import _classifier_model; print("\n".join(dict.fromkeys((llm_model(), _classifier_model()))))'
)"
while IFS= read -r OLLAMA_MODEL; do
  [ -n "$OLLAMA_MODEL" ] || continue
  if ! ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
    echo "Pulling required Ollama model: $OLLAMA_MODEL"
    ollama pull "$OLLAMA_MODEL"
  fi
done <<< "$OLLAMA_MODELS"
echo "Ollama ready with model(s): $(echo "$OLLAMA_MODELS" | tr '\n' ' ')"

nohup env DMEF_LOW_MEMORY=true ENABLE_LLM_PAGE_CLASSIFIER=true \
  ENABLE_STRUCTURED_LLM_CLASSIFIER=true LLM_PROVIDER=ollama \
  python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 \
  >> data/logs/uvicorn.log 2>&1 &
disown $! 2>/dev/null || true
echo "API pid=$! → http://127.0.0.1:8000"

cd frontend
nohup env NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 \
  npm run dev -- -p 3000 -H 127.0.0.1 \
  >> ../data/logs/frontend.log 2>&1 &
disown $! 2>/dev/null || true
echo "Frontend pid=$! → http://127.0.0.1:3000"

sleep 4
curl -sf http://127.0.0.1:8000/health && echo
curl -sf -o /dev/null -w "frontend HTTP %{http_code}\n" http://127.0.0.1:3000/ || true
