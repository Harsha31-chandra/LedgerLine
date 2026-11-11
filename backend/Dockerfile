# LedgerLine — Production Backend Dockerfile
# Python 3.12 slim base image
FROM python:3.12-slim AS runtime

# Set environment variables for Python runtime safety and performance
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=10000

# Install curl for container health check probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group
RUN groupadd --gid 10001 ledgerline \
    && useradd --uid 10001 --gid ledgerline --shell /bin/false --no-create-home ledgerline

WORKDIR /app

# Install Python dependencies reproducibly
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy backend application source code, Alembic migrations, and configuration
COPY app /app/backend/app
COPY migrations /app/backend/migrations
COPY alembic.ini /app/backend/alembic.ini

# Ensure non-root ownership
RUN chown -R ledgerline:ledgerline /app

# Switch to unprivileged runtime user
USER 10001:10001

EXPOSE 10000

# Health check probe against existing GET /health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD sh -c "curl -f http://127.0.0.1:${PORT:-10000}/health || exit 1"

# Trusted proxy address for Nginx reverse proxy (guaranteed IP in proxy-net)
ENV FORWARDED_ALLOW_IPS="127.0.0.1,172.28.1.10"

# Production ASGI server execution (migrations are never executed on startup)
# Restricts trusted proxy headers strictly to loopback and the designated Nginx reverse proxy IP (172.28.1.10)
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,172.28.1.10}\""]
