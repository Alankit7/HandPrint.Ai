# ── Handprint AI — development Dockerfile (CPU, single-stage) ─────────────────
# For GPU production use Dockerfile.prod instead.
FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF, OpenCV, Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libsm6 libxrender1 libxext6 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime directories — same paths as Dockerfile.prod so .env works for both
RUN mkdir -p /mnt/data/uploads /mnt/data/samples /mnt/data/outputs /mnt/data/db \
             /mnt/checkpoints

EXPOSE 8000

ENV DATABASE_URL=sqlite:////mnt/data/db/handprint.db \
    UPLOAD_DIR=/mnt/data/uploads \
    SAMPLE_DIR=/mnt/data/samples \
    OUTPUT_DIR=/mnt/data/outputs \
    LOG_FORMAT=text \
    LOG_LEVEL=INFO

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:8000/health | grep -q '"status":"ok"' || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
