ARG PYTHON_IMAGE=python:3.12.12-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.18

FROM ${UV_IMAGE} AS uv-source

# Build stage
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /app
COPY --from=uv-source /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime stage
FROM ${PYTHON_IMAGE}
WORKDIR /app

# Build arguments
# NOTE: Build args must be declared before they are referenced in ENV,
# so keep this ARG above any ENV instructions that use GIT_COMMIT_SHA.
ARG GIT_COMMIT_SHA=unknown

# Install runtime libraries: curl for health checks and libpq5 for PostgreSQL drivers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Inject Git SHA for runtime verification
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# Copy application code and migration configuration.
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

# Ensure shell scripts are executable and normalize Windows line endings.
RUN chmod +x scripts/*.sh && \
    sed -i 's/\r$//' scripts/entrypoint.sh scripts/prefect_worker_entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use the entrypoint so bootstrapping logic runs before the app starts.
ENTRYPOINT ["/bin/bash", "scripts/entrypoint.sh"]
