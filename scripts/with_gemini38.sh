#!/usr/bin/env bash
# Non-secret runtime selection. Existing credentials load through normal config.
set -euo pipefail
if [ "$#" -eq 0 ]; then
  echo "Usage: bash scripts/with_gemini38.sh <command> [arguments...]" >&2
  exit 2
fi
export LLM_PROVIDER=gemini
export GEMINI_MODEL=gemini-3.8-flash
export GOOGLE_CLOUD_LOCATION=global
exec "$@"
