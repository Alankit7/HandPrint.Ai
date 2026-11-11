# Handprint AI

Convert any printed PDF into the same content rendered in a specific person's handwriting,
using a few-shot diffusion model (One-DM or DiffusionPen) running on a GPU host.

## Monorepo layout

```
.
├── backend/        Python 3.11 FastAPI service (PDF pipeline + model inference)
├── app/            Flutter mobile/web app (Riverpod, Dio, go_router)
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick start (Docker)

```bash
cp .env.example .env          # configure secrets and paths
# Download model checkpoint into backend/checkpoints/onedm/model.pth
docker compose up --build
```

The API is available at `http://localhost:8000` and the Flutter web build at `http://localhost`.

## Quick start (local dev)

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env       # or symlink
uvicorn app.main:app --reload
```

**Flutter**
```bash
cd app
flutter pub get
# edit lib/core/config.dart → set apiBaseUrl
flutter run
```

## Model checkpoints

| Model | Download |
|-------|----------|
| One-DM | https://github.com/dailenson/One-DM (follow their release page) |
| DiffusionPen | https://github.com/koninik/DiffusionPen |

Place the `.pth` file at the path set in `ONEDM_CHECKPOINT` / `DIFFUSIONPEN_CHECKPOINT` in `.env`.

## API summary

| Method | Path | Description |
|--------|------|-------------|
| POST | `/jobs` | Upload PDF + style samples; returns `job_id` |
| GET  | `/jobs/{job_id}` | Poll job status & progress |
| GET  | `/jobs/{job_id}/download` | Stream the finished PDF |
| GET  | `/health` | Liveness check |

## Running tests

```bash
cd backend && pytest -v
```
