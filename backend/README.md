# Handprint AI — Backend API

A FastAPI service that:
1. Accepts **handwriting sample images** to build a writer _profile_.
2. **Fine-tunes** a diffusion model on those samples (ML call behind a stub today).
3. **Converts** any printed PDF into the writer's handwriting style.
4. Serves the finished PDF for download.

---

## Project layout

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── health.py        # GET /health
│   │   ├── profiles.py      # POST /profiles, POST /profiles/{id}/train, GET /profiles/{id}
│   │   └── jobs.py          # POST /convert, GET /jobs/{id}, GET /download/{id}
│   ├── core/
│   │   ├── config.py        # Pydantic-Settings singleton — all env vars here
│   │   ├── security.py      # X-API-Key dependency
│   │   ├── exceptions.py    # Domain exceptions + FastAPI handlers
│   │   └── logging.py       # Structured stdout logging
│   ├── db/
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   ├── models.py        # Profile + Job ORM models
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   └── session.py       # Engine, SessionLocal, get_db dependency
│   ├── ml/
│   │   └── stubs.py         # train_profile() + render_pdf() — raise NotImplementedError
│   ├── workers/
│   │   ├── pool.py          # Thread-pool executor
│   │   ├── train_worker.py  # Background training task
│   │   ├── convert_worker.py# Background conversion task
│   │   └── cleanup.py       # Scheduled file cleanup
│   └── main.py              # App factory, lifespan, scheduler
├── alembic/                 # DB migrations
├── tests/                   # pytest suite
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Quick start

```bash
# 1. Clone / enter the backend directory
cd backend

# 2. Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit .env — set API_KEY to a strong random value:
#   python3 -c "import secrets; print(secrets.token_hex(32))"

# 5. Run migrations
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --reload
```

The interactive docs are at <http://localhost:8000/docs>.

---

## Docker

```bash
# Build
docker build -t handprint-backend .

# Run (mount a volume for persistent data)
docker run -p 8000:8000 \
  -e API_KEY=your-secret-key \
  -v "$(pwd)/data:/app/data" \
  handprint-backend
```

---

## Authentication

Every endpoint (except `GET /health`) requires the header:

```
X-API-Key: <your-api-key>
```

Missing key → **401**.  Wrong key → **403**.

---

## API reference & curl examples

Replace `$KEY` with your actual API key and `$BASE` with `http://localhost:8000`.

### Health check

```bash
curl $BASE/health
# {"status":"ok"}
```

---

### 1. Create a writer profile

Upload 15–30 handwriting sample images (JPEG or PNG, ≤ 10 MB each).

```bash
curl -X POST "$BASE/profiles" \
  -H "X-API-Key: $KEY" \
  -F "name=Alice" \
  -F "images=@sample_01.png;type=image/png" \
  -F "images=@sample_02.png;type=image/png" \
  # ... repeat up to 30 images
```

**Response (201)**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Alice",
  "status": "pending",
  "sample_count": 2,
  "train_progress": 0.0,
  "error": null,
  "created_at": "2026-11-11T10:00:00Z",
  "updated_at": "2026-11-11T10:00:00Z"
}
```

Save the `id` as `$PROFILE_ID`.

---

### 2. Start training

```bash
curl -X POST "$BASE/profiles/$PROFILE_ID/train" \
  -H "X-API-Key: $KEY"
```

**Response (202)**

```json
{"message": "Training started for profile '3fa85f64-…'."}
```

> **Note:** Training calls `ml.stubs.train_profile()`, which raises
> `NotImplementedError` until real ML code is plugged in.  The job will
> transition to `failed` immediately.  Replace the stub to enable training.

---

### 3. Poll profile status

```bash
curl "$BASE/profiles/$PROFILE_ID" \
  -H "X-API-Key: $KEY"
```

**Response (200)**

```json
{
  "id": "3fa85f64-…",
  "status": "training",   // pending | training | ready | failed
  "train_progress": 0.42,
  "error": null,
  ...
}
```

Poll until `status == "ready"` before submitting a conversion job.

---

### 4. Convert a PDF

```bash
curl -X POST "$BASE/convert" \
  -H "X-API-Key: $KEY" \
  -F "profile_id=$PROFILE_ID" \
  -F "pdf=@document.pdf;type=application/pdf"
```

**Response (202)**

```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "profile_id": "3fa85f64-…",
  "status": "queued",
  "progress": 0.0,
  "message": "Queued",
  ...
}
```

Save the `id` as `$JOB_ID`.

---

### 5. Poll job status

```bash
curl "$BASE/jobs/$JOB_ID" \
  -H "X-API-Key: $KEY"
```

**Response (200)**

```json
{
  "id": "7c9e6679-…",
  "status": "processing",  // queued | processing | done | failed
  "progress": 0.65,
  "message": "Rendering… 65%",
  ...
}
```

---

### 6. Download the finished PDF

```bash
curl "$BASE/download/$JOB_ID" \
  -H "X-API-Key: $KEY" \
  -o handwritten_output.pdf
```

Returns the binary PDF with `Content-Type: application/pdf`.
Returns **409** if the job is not yet `done`.

---

## Running tests

```bash
pytest -v
```

The test suite uses an **in-memory SQLite** database and temp directories —
no `.env` needed, no files left on disk.

---

## Plugging in real ML

Open `app/ml/stubs.py` and replace the two function bodies:

```python
def train_profile(profile_id, sample_dir, checkpoint_out_dir, progress_cb):
    # YOUR fine-tuning code here
    # Call progress_cb(0.0 … 1.0) periodically
    # Write checkpoint to checkpoint_out_dir
    pass

def render_pdf(input_pdf_path, checkpoint_path, output_pdf_path, progress_cb):
    # YOUR inference code here
    # Call progress_cb(0.0 … 1.0) periodically
    # Write finished PDF to output_pdf_path
    pass
```

No other files need to change.

---

## Configuration reference

All settings are in `.env` (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | *(required)* | Secret key for `X-API-Key` header |
| `DATABASE_URL` | `sqlite:///./data/db/handprint.db` | SQLAlchemy DB URL |
| `UPLOAD_DIR` | `data/uploads` | Uploaded PDFs |
| `SAMPLE_DIR` | `data/samples` | Profile sample images |
| `OUTPUT_DIR` | `data/outputs` | Generated PDFs |
| `MAX_SAMPLE_IMAGE_MB` | `10` | Per-image size limit |
| `MAX_PDF_MB` | `50` | Input PDF size limit |
| `MIN_SAMPLE_IMAGES` | `15` | Minimum images per profile |
| `MAX_SAMPLE_IMAGES` | `30` | Maximum images per profile |
| `WORKER_THREADS` | `2` | Background thread pool size |
| `CLEANUP_AGE_HOURS` | `24` | Files older than this are deleted |
| `CLEANUP_INTERVAL_MINUTES` | `60` | How often the cleanup task runs |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
