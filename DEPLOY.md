# Handprint AI — GPU Deployment Guide

This guide covers deploying the backend to three GPU hosting platforms:
[RunPod](https://runpod.io), [GCP T4 VM](https://cloud.google.com/compute/docs/gpus),
and [Modal](https://modal.com). The same Docker image works on all three.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Build the image](#2-build-the-image)
3. [Quick start (docker-compose)](#3-quick-start-docker-compose)
4. [Deploy to RunPod](#4-deploy-to-runpod)
5. [Deploy to GCP T4](#5-deploy-to-gcp-t4)
6. [Deploy to Modal](#6-deploy-to-modal)
7. [Configuration reference](#7-configuration-reference)
8. [Verification](#8-verification)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### On your local machine (for building)

- Docker 24+ with BuildKit
- Docker Compose v2.20+
- `git` to clone the repo

### On the GPU host

- **NVIDIA driver** 525+ (check with `nvidia-smi`)
- **NVIDIA Container Toolkit** (so Docker can access the GPU)
  ```bash
  # Ubuntu / Debian
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```

### Model weights

Place your trained checkpoint files in a directory that will be mounted into the
container at `/mnt/checkpoints`:

```
checkpoints/
├── onedm/
│   └── model.pth
└── diffusionpen/
    └── model.pth
```

If no checkpoint exists, the backend starts in "synthetic" mode — it produces
output using a fallback renderer so you can verify the pipeline end-to-end
without a trained model.

---

## 2. Build the image

```bash
cd /path/to/HandPrint-AI/backend
docker build -f Dockerfile.prod -t handprint-ai:latest .
```

This produces a ~6 GB image based on `pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime`
with all Python dependencies pre-installed.

Verify the build:

```bash
docker run --rm --gpus all handprint-ai:latest nvidia-smi
```

You should see your GPU listed.

---

## 3. Quick start (docker-compose)

Use this for a single-server deployment with nginx TLS termination and rate
limiting. Works on any GPU host with Docker Compose installed.

### 3.1 Configure environment

```bash
cd /path/to/HandPrint-AI
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
API_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
```

### 3.2 Generate TLS certificates

For development / testing:

```bash
chmod +x backend/nginx/generate-cert.sh
./backend/nginx/generate-cert.sh ./certs
```

For production, use Let's Encrypt:

```bash
sudo apt-get install -y certbot
sudo certbot certonly --standalone -d your-domain.com
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./certs/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem  ./certs/key.pem
```

### 3.3 Add model weights

```bash
# Copy your trained checkpoint into the volume mount point
mkdir -p checkpoints/onedm
cp /path/to/your/model.pth checkpoints/onedm/
```

### 3.4 Launch

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

### 3.5 Verify

```bash
# Health check (via nginx → backend)
curl -k https://localhost/health

# Should return: {"status":"ok"}

# Create a profile (requires API key)
curl -k -X POST https://localhost/profiles \
  -H "X-API-Key: $API_KEY" \
  -F "name=Test" \
  -F "images=@sample.png;type=image/png"
```

### 3.6 View logs

```bash
# Backend logs (JSON structured)
docker compose -f docker-compose.prod.yml logs -f backend

# nginx logs
docker compose -f docker-compose.prod.yml logs -f nginx
```

### 3.7 Stop

```bash
docker compose -f docker-compose.prod.yml down
# To keep data volumes: omit the -v flag
# To wipe data volumes: add -v
```

---

## 4. Deploy to RunPod

RunPod provides on-demand GPU pods billed by the hour. Ideal for development
and small-scale production.

### 4.1 Create a pod

1. Sign in at [runpod.io](https://runpod.io)
2. Click **Deploy** → **GPU Pods**
3. Select a template:
   - **Custom template**: use `pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime`
   - **GPU**: RTX 3090, RTX 4090, or A100 (T4 works for testing but is slower)
   - **Pod name**: `handprint-ai`
4. Configure **Network Volume** (persistent storage):
   - Click **Add Network Volume**
   - Name: `handprint-data`
   - Size: 100 GB
   - Data center: same as your pod
5. Set **Container Disk** to 50 GB (for the image layers)
6. Set **Volume Mount Path** to `/mnt/data`
7. Click **Deploy On-Demand** (or **Spot** for cheaper rates)

### 4.2 Connect to the pod

```bash
# RunPod gives you SSH access — find the command in the pod details
ssh root@<pod-ip> -p <port>
```

### 4.3 Install Docker + Compose inside the pod

```bash
# RunPod pods come with Python + CUDA but not always Docker
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
```

### 4.4 Deploy the app

```bash
# Clone the repo
git clone <your-repo-url> /opt/handprint-ai
cd /opt/handprint-ai

# Configure
cp .env.example .env
# Edit .env — set API_KEY
nano .env

# Generate self-signed certs
chmod +x backend/nginx/generate-cert.sh
./backend/nginx/generate-cert.sh ./certs

# Mount the network volume for data
# Edit docker-compose.prod.yml — change the data volume to bind mount:
#   volumes:
#     - /mnt/data:/mnt/data
#     - /root/checkpoints:/mnt/checkpoints

# Copy model weights to /root/checkpoints/
# (or use the RunPod network volume)

# Launch
docker compose -f docker-compose.prod.yml up --build -d
```

### 4.5 Expose the port

RunPod pods have a public IP. Map the HTTPS port:

1. Go to pod settings → **Public Ports**
2. Add port **443** (HTTPS) and **80** (HTTP redirect)
3. RunPod gives you a public URL like `https://xyz-443.proxy.runpod.net`

```bash
# Test the public endpoint
curl -k https://<runpod-proxy-url>/health
```

### 4.6 Set up persistent deployment

To keep the pod running and auto-restart:

1. In pod settings, enable **Always On**
2. Set up a health-check script in RunPod's pod settings
3. Consider using RunPod's **Serverless** endpoint for auto-scaling

---

## 5. Deploy to GCP T4

Google Cloud T4 GPUs are cost-effective ($0.35/hour for n1-standard-4 + T4)
and available in most regions.

### 5.1 Create a GPU-enabled VM

```bash
# Set variables
export PROJECT_ID="your-project"
export ZONE="us-central1-a"
export INSTANCE_NAME="handprint-ai"

# Create the VM with a T4 GPU
gcloud compute instances create $INSTANCE_NAME \
  --project=$PROJECT_ID \
  --zone=$ZONE \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --maintenance-policy=TERMINATE \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=100GB \
  --boot-disk-type=pd-ssd
```

### 5.2 Install NVIDIA drivers + Container Toolkit

```bash
# SSH into the VM
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE

# Install CUDA driver
sudo apt-get update
sudo apt-get install -y nvidia-driver-535

# Reboot to load the driver
sudo reboot

# Wait ~2 minutes, then reconnect
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE

# Verify GPU is visible
nvidia-smi

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 5.3 Attach a persistent disk for data

```bash
# Create a 200 GB persistent disk
gcloud compute disks create handprint-data \
  --size=200GB --type=pd-ssd --zone=$ZONE

# Attach it to the VM
gcloud compute instances attach-disk $INSTANCE_NAME \
  --disk=handprint-data --zone=$ZONE

# Format and mount (first time only)
sudo mkfs.ext4 /dev/sdb
sudo mkdir -p /mnt/data
sudo mount /dev/sdb /mnt/data
echo "/dev/sdb /mnt/data ext4 defaults 0 2" | sudo tee -a /etc/fstab
```

### 5.4 Deploy

```bash
# Clone and configure
git clone <your-repo-url> /opt/handprint-ai
cd /opt/handprint-ai
cp .env.example .env
nano .env  # set API_KEY

# Generate certs
chmod +x backend/nginx/generate-cert.sh
./backend/nginx/generate-cert.sh ./certs

# Edit docker-compose.prod.yml to use the persistent disk:
# volumes:
#   - /mnt/data:/mnt/data
#   - /mnt/data/checkpoints:/mnt/checkpoints

# Copy model weights
scp model.pth $INSTANCE_NAME:/mnt/data/checkpoints/onedm/

# Launch
docker compose -f docker-compose.prod.yml up --build -d

# Verify
curl -k https://localhost/health
```

### 5.5 Set up a static IP + firewall

```bash
# Reserve a static external IP
gcloud compute addresses create handprint-ip --region=$ZONE

# Assign it to the VM
gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --format='value(networkInterfaces[0].accessConfigs[0].natIP)'

# Open firewall ports
gcloud compute firewall-rules create allow-https \
  --allow tcp:443 --network=default

gcloud compute firewall-rules create allow-http \
  --allow tcp:80 --network=default
```

### 5.6 Set up a domain + Let's Encrypt

```bash
# Point your domain's A record to the static IP
# Then get real TLS certs:
sudo certbot certonly --standalone -d your-domain.com
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./certs/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem  ./certs/key.pem

# Restart nginx
docker compose -f docker-compose.prod.yml restart nginx
```

---

## 6. Deploy to Modal

Modal is a serverless GPU platform — no VM management, pay-per-second billing.
Best for intermittent workloads.

### 6.1 Install Modal

```bash
pip install modal
modal setup  # authenticate
```

### 6.2 Create the deployment script

Create a file `backend/deploy/modal_app.py`:

```python
"""Modal deployment for Handprint AI."""
import modal

app = modal.App("handprint-ai")

# Build the image from our Dockerfile.prod
image = modal.Image.from_dockerfile(
    "backend/Dockerfile.prod",
    context_dir=".",
)

# Persistent volume for data and checkpoints
vol = modal.Volume.from_name("handprint-data", create_if_missing=True)

@app.function(
    image=image,
    gpu="T4",
    volumes={"/mnt/data": vol},
    min_containers=0,
    scaledown_window=300,
    timeout=600,
)
@modal.asgi_app()
def web():
    from app.main import app
    return app
```

### 6.3 Deploy

```bash
# From the project root
modal deploy backend/deploy/modal_app.py
```

Modal gives you a public URL like `https://your-workspace--handprint-ai-web.modal.run`.

### 6.4 Upload model weights

```bash
# Upload checkpoint to the Modal volume
modal volume put handprint-data /path/to/model.pth checkpoints/onedm/model.pth
```

### 6.5 Configure secrets

```bash
# Set environment variables as Modal secrets
modal secret create handprint-config \
  API_KEY=your-secret-key \
  LOG_FORMAT=json
```

Reference the secret in your modal_app.py:

```python
@app.function(
    image=image,
    gpu="T4",
    volumes={"/mnt/data": vol},
    secrets=["handprint-config"],
)
```

### 6.6 Notes on Modal

- **Rate limiting**: Modal doesn't provide nginx, so rate limiting must be
  added at the application level (e.g., SlowAPI) or via a CDN/Cloudflare in front.
- **TLS**: Modal handles TLS automatically — no nginx needed.
- **Health check**: Modal probes `/health` automatically.
- **Cold starts**: First request after scale-down takes ~30s to spin up the container.
  Use `min_containers=1` to keep a warm instance.

---

## 7. Configuration reference

All settings come from environment variables (or `.env` file).

### Required

| Variable | Example | Description |
|---|---|---|
| `API_KEY` | `a3f8b2c1...` | Secret key for X-API-Key header (min 8 chars) |

### Server

| Variable | Default | Description |
|---|---|---|
| `BACKEND_HOST` | `0.0.0.0` | Bind address |
| `BACKEND_PORT` | `8000` | Bind port |

### Storage (set to volume mount paths in production)

| Variable | Prod default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:////mnt/data/db/handprint.db` | SQLAlchemy URL |
| `UPLOAD_DIR` | `/mnt/data/uploads` | Uploaded PDFs |
| `SAMPLE_DIR` | `/mnt/data/samples` | Handwriting samples |
| `OUTPUT_DIR` | `/mnt/data/outputs` | Generated PDFs |

### Limits

| Variable | Default | Description |
|---|---|---|
| `MAX_SAMPLE_IMAGE_MB` | `10` | Per-image upload limit |
| `MAX_PDF_MB` | `50` | PDF upload limit |
| `MIN_SAMPLE_IMAGES` | `15` | Minimum samples per profile |
| `MAX_SAMPLE_IMAGES` | `30` | Maximum samples per profile |

### Workers & cleanup

| Variable | Default | Description |
|---|---|---|
| `WORKER_THREADS` | `2` | Background thread pool size |
| `CLEANUP_AGE_HOURS` | `24` | Files older than this are deleted |
| `CLEANUP_INTERVAL_MINUTES` | `60` | Cleanup task frequency |

### Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_FORMAT` | `json` | `text` or `json` (one JSON object per line) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### CORS

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

### nginx rate limits

Configured in `backend/nginx/prod.conf`:

| Zone | Rate | Burst | Applied to |
|---|---|---|---|
| `api_limit` | 10 req/s | 20 | All general endpoints |
| `upload_limit` | 2 req/s | 5 | `POST /profiles`, `POST /convert` |
| `download_limit` | 5 req/s | 10 | `GET /download/` |

Adjust the `limit_req_zone` directives in `prod.conf` to change these.

---

## 8. Verification

After deployment, verify each layer:

### 8.1 Health check

```bash
curl -k https://your-host/health
# Expected: {"status":"ok"}
```

### 8.2 GPU available

```bash
docker exec -it $(docker compose -f docker-compose.prod.yml ps -q backend) nvidia-smi
# Should show GPU name, memory, driver version
```

### 8.3 Rate limiting

```bash
# Send 30 rapid requests — some should get 429
for i in $(seq 1 30); do
  curl -sk -o /dev/null -w "%{http_code}\n" https://your-host/health
done
```

### 8.4 Structured logging

```bash
docker compose -f docker-compose.prod.yml logs backend | head -5
# Should show JSON objects with timestamp, level, logger, message
```

### 8.5 Full API flow

```bash
# 1. Create a profile
PROFILE=$(curl -sk -X POST https://your-host/profiles \
  -H "X-API-Key: $API_KEY" \
  -F "name=Test" \
  -F "images=@sample.png;type=image/png")
PROFILE_ID=$(echo $PROFILE | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Start training
curl -sk -X POST https://your-host/profiles/$PROFILE_ID/train \
  -H "X-API-Key: $API_KEY"

# 3. Poll status
curl -sk https://your-host/profiles/$PROFILE_ID \
  -H "X-API-Key: $API_KEY"
```

---

## 9. Troubleshooting

### GPU not detected inside container

```bash
# Verify NVIDIA Container Toolkit is installed
nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Test
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

If `nvidia-smi` fails inside the container, the host driver may be too old.
Update to driver 525+ and reinstall nvidia-container-toolkit.

### `docker compose` GPU section not working

Ensure Docker Compose v2.20+ is installed (not the legacy `docker-compose` v1):

```bash
docker compose version
# Should show v2.20+
```

If stuck on v1, install the plugin:

```bash
sudo apt-get install docker-compose-plugin
```

### TLS certificate errors

```bash
# Regenerate self-signed certs
rm -rf certs/
./backend/nginx/generate-cert.sh ./certs

# Or skip TLS verification in curl
curl -k https://your-host/health
```

### Rate limiting too aggressive

Edit `backend/nginx/prod.conf` and adjust the `limit_req_zone` rates:

```nginx
# Example: increase upload rate to 5 req/s
limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=5r/s;
```

Rebuild nginx:

```bash
docker compose -f docker-compose.prod.yml up --build -d nginx
```

### Database migration failures

```bash
# Run migrations manually
docker exec -it $(docker compose -f docker-compose.prod.yml ps -q backend) \
  alembic upgrade head

# If the DB is corrupted, reset it
docker exec -it $(docker compose -f docker-compose.prod.yml ps -q backend) \
  rm /mnt/data/db/handprint.db
docker compose -f docker-compose.prod.yml restart backend
```

### Out of memory on GPU

```bash
# Check GPU memory usage
docker exec -it $(docker compose -f docker-compose.prod.yml ps -q backend) nvidia-smi

# If another process is using the GPU, stop it
sudo fuser -v /dev/nvidia*

# Reduce model batch size or use a larger GPU
```

### Logs not showing JSON format

Ensure `LOG_FORMAT=json` is set in the environment:

```bash
docker exec -it $(docker compose -f docker-compose.prod.yml ps -q backend) \
  printenv LOG_FORMAT
# Should print: json
```

If not, check your `.env` file and restart:

```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

### Pod / VM restarted and lost data

On RunPod, use **Network Volumes** (not container disk) for persistent storage.
On GCP, use **Persistent Disk** with `pd-ssd` type.
On Modal, use `modal.Volume`.

Never store data in the container's writable layer — it is lost on restart.
