# ============================================================
# WebScope — Dockerfile (multi-stage)
# Stage 1: builder — install deps, compile wheels
# Stage 2: runtime — minimal image with Playwright/Chromium
# ============================================================

# ---- Stage 1: Builder ----
FROM python:3.13-slim AS builder

# System deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps via pip (cached layer)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# Copy source code
COPY src/ ./src/
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# ---- Stage 2: Runtime ----
FROM python:3.13-slim AS runtime

# Playwright browsers location (shared, world-readable)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system deps first (Chromium + node runtime libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libatomic1 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright + Chromium
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir playwright && \
    playwright install chromium

# Create non-root user
RUN groupadd -r webscope && useradd -r -g webscope -d /app -s /bin/bash webscope

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
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
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

# Entry point (honors $PORT for Railway/Render; defaults to 8000)
CMD ["sh", "-c", "python -m uvicorn webscope.webapp.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]