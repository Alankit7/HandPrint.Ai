#!/usr/bin/env bash
# healthcheck.sh — curl the /health endpoint, exit 0 if healthy, 1 otherwise.
set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
TIMEOUT="${HEALTH_TIMEOUT:-5}"

response=$(curl -sf --max-time "$TIMEOUT" "$HEALTH_URL" 2>/dev/null || echo "")

if echo "$response" | grep -q '"status":"ok"'; then
  exit 0
else
  echo "Health check failed: $response" >&2
  exit 1
fi
