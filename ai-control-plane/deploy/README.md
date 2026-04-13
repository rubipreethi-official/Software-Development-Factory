# AI Control Plane — Deployment Guide

## Quick Reference

| Method | Command | URL |
|--------|---------|-----|
| **Local (dev)** | `python main.py` | http://localhost:8000 |
| **Docker** | `docker compose up -d` | http://localhost:8000 |
| **Kubernetes** | `kubectl apply -f deploy/scaling.yaml` | Via Service/Ingress |

---

## 1. Local Development

### Prerequisites
- Python 3.11+
- pip

### Setup
```bash
cd ai-control-plane

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/Mac

# Start the server
python main.py
```

### Verify
- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/api/v1/health
- **Metrics**: http://localhost:8000/metrics

### Run Tests
```bash
python -m pytest tests/ -v --tb=short
```

### Run End-to-End Pipeline Test
```bash
# In a separate terminal (server must be running):
python test_pipeline.py
```

---

## 2. Docker Deployment

### Prerequisites
- Docker Desktop (Windows/Mac) or Docker Engine (Linux)

### Start Full Stack
```bash
cd ai-control-plane

# Start control plane + Prometheus + Grafana
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f control-plane
```

### Access Points
| Service | URL | Credentials |
|---------|-----|-------------|
| **API** | http://localhost:8000 | — |
| **API Docs** | http://localhost:8000/docs | — |
| **Prometheus** | http://localhost:9090 | — |
| **Grafana** | http://localhost:3000 | admin / admin |

### Stop
```bash
docker compose down        # Stop services
docker compose down -v     # Stop + remove data volumes
```

---

## 3. Kubernetes Deployment

### Prerequisites
- Kubernetes cluster (local: minikube, kind, or Docker Desktop K8s)
- `kubectl` configured
- Docker image built and pushed to a registry

### Build & Push Image
```bash
docker build -t ai-control-plane:latest .
# For remote cluster:
docker tag ai-control-plane:latest your-registry/ai-control-plane:latest
docker push your-registry/ai-control-plane:latest
```

### Create Secrets
```bash
kubectl create secret generic ai-control-plane-secrets \
  --from-literal=database-url='postgresql+asyncpg://user:pass@host:5432/db' \
  --from-literal=claude-api-key='your-api-key' \
  --from-literal=jwt-secret-key='your-jwt-secret'
```

### Deploy
```bash
kubectl apply -f deploy/scaling.yaml
```

### Verify
```bash
kubectl get pods -l app=ai-control-plane
kubectl get hpa ai-control-plane-hpa
kubectl logs -l app=ai-control-plane --tail=50
```

---

## 4. Database Operations

### Backup
```bash
python scripts/backup.py                    # Create backup
python scripts/backup.py --list             # List backups
python scripts/backup.py --retain-days 14   # Custom retention
```

### Restore
```bash
python scripts/restore.py --list            # List available backups
python scripts/restore.py --latest          # Restore most recent
python scripts/restore.py --file backups/backup_20260410.db  # Specific file
```

---

## 5. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | `development`, `staging`, `production` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/control_plane.db` | Database connection string |
| `CLAUDE_API_KEY` | `mock` | Anthropic API key (`mock` = mock responses) |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |
| `API_HOST` | `0.0.0.0` | API bind host |
| `API_PORT` | `8000` | API bind port |
| `JWT_SECRET_KEY` | — | JWT signing secret (change in production!) |
| `LOG_LEVEL` | `DEBUG` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `RATE_LIMIT_PER_MINUTE` | `60` | API rate limit per client |

---

## 6. Scaling Guidelines

### Horizontal Scaling (HPA)
The included `deploy/scaling.yaml` configures:
- **Min replicas**: 2
- **Max replicas**: 8
- **Scale up trigger**: CPU > 70% average
- **Scale down**: Conservative (5-minute stabilization)

### When to Scale
| Metric | Threshold | Action |
|--------|-----------|--------|
| Active workflows > 10 | Medium load | Scale to 4 replicas |
| Agent execution p95 > 5s | High load | Scale to 6 replicas |
| API response time > 500ms | Very high | Scale to 8 replicas |

### Database Scaling
For production, switch from SQLite to PostgreSQL:
```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ai_control_plane
```
Add `asyncpg` to requirements.txt:
```
asyncpg==0.30.0
```
