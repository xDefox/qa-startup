# ============================================================
# WebScope — Dockerfile (multi-stage)
# Stage 1: builder — install deps, compile wheels
# Stage 2: runtime — minimal image with Playwright/Chromium
# ============================================================

# ---- Stage 1: Builder ----
FROM python:3.12-slim AS builder

# System deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps via pip (cached layer)
COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only=main --no-interaction --no-ansi

# Copy source code
COPY src/ ./src/
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only=main --no-interaction --no-ansi

# ---- Stage 2: Runtime ----
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy AS runtime

# Install system deps for runtime (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r webscope && useradd -r -g webscope -d /app -s /bin/bash webscope

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app/src ./src

# Create directories for data, uploads, logs
RUN mkdir -p /data /uploads /var/log/webscope && \
    chown -R webscope:webscope /app /data /uploads /var/log/webscope

# Switch to non-root user
USER webscope

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WEBSCOPE_HOST=0.0.0.0 \
    WEBSCOPE_PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Entry point
CMD ["python", "-m", "uvicorn", "webscope.webapp.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]