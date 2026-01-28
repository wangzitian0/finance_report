# Build stage
FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime stage
FROM python:3.12-slim
WORKDIR /app

# Build arguments
ARG GIT_COMMIT_SHA=unknown

# 安装必要的运行时库：curl (健康检查) 和 libpq5 (psycopg2 依赖)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Inject Git SHA for runtime verification
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# 复制业务代码和数据库迁移配置
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

# 确保脚本具有执行权限并修复换行符 (Windows 兼容性)
RUN chmod +x scripts/*.sh && \
    sed -i 's/\r$//' scripts/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 使用 Entrypoint 模式启动，确保引导逻辑执行
ENTRYPOINT ["/bin/bash", "scripts/entrypoint.sh"]