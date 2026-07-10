# =============================================================================
# Multi-stage Dockerfile for Demand Planner Backend
# =============================================================================
# Optimized for FastAPI + Celery + PostgreSQL + Redis

# =============================================================================
# Stage 1: Builder (compiles packages, then discarded)
# =============================================================================
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy requirements and install Python packages
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# =============================================================================
# Stage 2: Runtime (small, production-ready image)
# =============================================================================
FROM python:3.11-slim

# Metadata labels
LABEL org.opencontainers.image.title="Demand Planner Backend"
LABEL org.opencontainers.image.description="FastAPI backend with Celery task queue"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.authors="demand-planning-team"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create directories with correct permissions
RUN mkdir -p /app/logs /app/tmp && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
