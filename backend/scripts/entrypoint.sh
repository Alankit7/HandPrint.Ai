#!/usr/bin/env bash
# entrypoint.sh — runs Alembic migrations then execs the CMD (uvicorn).
set -euo pipefail

echo "=== Handprint AI — Starting ==="

# ── 1. Verify data directories exist ──────────────────────────────────────────
for dir in "${UPLOAD_DIR:-/mnt/data/uploads}" \
           "${SAMPLE_DIR:-/mnt/data/samples}" \
           "${OUTPUT_DIR:-/mnt/data/outputs}" \
           "$(dirname "${DATABASE_URL:-sqlite:////mnt/data/db/handprint.db}" | sed 's|sqlite:///||')"; do
  mkdir -p "$dir" 2>/dev/null || true
done
echo "Data directories verified."

# ── 2. Run database migrations ────────────────────────────────────────────────
echo "Running Alembic migrations..."
alembic upgrade head
echo "Migrations complete."

# ── 3. Print GPU info if available ───────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
  echo "GPU detected:"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
else
  echo "No GPU detected — running in CPU mode (ML stubs will use synthetic fallback)."
fi

echo "=== Starting server ==="

# ── 4. Exec the main process ──────────────────────────────────────────────────
exec "$@"
