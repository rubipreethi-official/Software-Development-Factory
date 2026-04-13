# ──────────────────────────────────────────────────────────
# AI Control Plane — Multi-stage Docker Build
# Task: DEP-01
# ──────────────────────────────────────────────────────────

# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system deps for building
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy and install dependencies into a virtual env
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source
COPY config.py config.yaml database.py models.py \
     spec_system.py agents.py orchestrator.py \
     validation.py observability.py api.py main.py \
     ./

# Copy Alembic for migrations (optional in container)
COPY alembic/ alembic/
COPY alembic.ini .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Copy env template (override at runtime via env vars or mounted .env)
COPY .env.example /app/.env.example

# Switch to non-root
USER appuser

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://127.0.0.1:8000/api/v1/health'); exit(0 if r.status_code == 200 else 1)" || exit 1

# Start the application
CMD ["python", "main.py"]
