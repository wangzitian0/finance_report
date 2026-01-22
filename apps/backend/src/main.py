"""Finance Report Backend - FastAPI Application."""

import asyncio
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aioboto3
import structlog
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db, init_db
from src.env_check import check_env_on_startup, print_loaded_config
from src.logger import configure_logging, get_logger
from src.models import PingState
from src.rate_limit import auth_rate_limiter, register_rate_limiter
from src.routers import accounts, ai_models, auth, chat, journal, reports, statements, users
from src.routers.reconciliation import router as reconciliation_router
from src.schemas import PingStateResponse
from src.services.statement_parsing_supervisor import run_parsing_supervisor

# Conditional import for Redis (optional dependency in production)
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Initialize logging early
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - init DB on startup."""
    # Environment variable check
    check_env_on_startup()
    print_loaded_config(settings)

    await init_db()
    stop_event = asyncio.Event()
    supervisor_task = asyncio.create_task(run_parsing_supervisor(stop_event))
    logger.info("Application started", version="0.1.0")
    yield
    stop_event.set()
    supervisor_task.cancel()

    # Close rate limiters (Redis connections)
    auth_rate_limiter.close()
    register_rate_limiter.close()

    with suppress(asyncio.CancelledError):
        await supervisor_task
    logger.info("Application shutting down")


app = FastAPI(
    title="Finance Report API",
    description="Personal financial management system with double-entry bookkeeping",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next: Any) -> Response:
    """Middleware to inject Request-ID and log request details."""
    request_id = request.headers.get("X-Request-ID", str(uuid4()))

    # Clear and set contextvars for this request
    # Note: structlog.contextvars are isolated per async context/task.
    # We clear to ensure a clean slate for the top-level request task.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        logger.info(
            "HTTP Request",
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )

        # Inject Request-ID into response headers
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration = time.perf_counter() - start_time
        logger.exception(
            "HTTP Request Failed",
            duration_ms=round(duration * 1000, 2),
            error=str(exc),
        )
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler to ensure JSON response."""
    # Log is already handled by middleware or logger.exception

    # Only show exception details in DEBUG mode
    if settings.debug:
        detail = str(exc)
        trace = traceback.format_exc()
    else:
        detail = "An internal server error occurred. Please try again later."
        trace = None

    return JSONResponse(
        status_code=500,
        content={
            "detail": detail,
            "trace": trace if settings.debug else None,
            "request_id": structlog.contextvars.get_contextvars().get("request_id"),
        },
    )


# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-User-Id"],
)

# Include routers
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(ai_models.router)
app.include_router(chat.router)
app.include_router(journal.router)
app.include_router(reports.router)
app.include_router(statements.router)
app.include_router(reconciliation_router)
app.include_router(users.router)


# --- Health & Demo Endpoints ---


async def check_database(db: AsyncSession) -> bool:
    """Check database connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return True
    except (OSError, TimeoutError) as e:
        # Expected: Network errors, connection refused, query timeout
        logger.error(
            "Health check: Database connection failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def check_redis() -> bool:
    """Check Redis connectivity if configured."""
    if not settings.redis_url or not REDIS_AVAILABLE:
        return True

    redis_client = None
    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        return True
    except (OSError, TimeoutError) as e:
        # Expected: Network errors, connection refused, Redis command failures
        logger.error(
            "Health check: Redis connection failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    finally:
        if redis_client:
            await redis_client.aclose()


async def check_s3() -> bool:
    """Check S3/MinIO connectivity with short timeout."""
    try:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=BotoConfig(connect_timeout=2, read_timeout=2),
        ) as s3_client:
            await s3_client.head_bucket(Bucket=settings.s3_bucket)
            return True
    except ClientError as e:
        # Expected: 404 Not Found, 403 Forbidden, bucket access errors
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            "Health check: S3 client error",
            error=str(e),
            error_code=error_code,
            bucket=settings.s3_bucket,
        )
        return False
    except (BotoCoreError, OSError, TimeoutError) as e:
        # Expected: Connection errors, timeouts, network issues
        logger.error(
            "Health check: S3 connection failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> Response:
    """Check application health status with dependency checks.

    Returns 200 if all critical services are healthy, 503 otherwise.
    This endpoint is used by Docker healthcheck and deployment verification.
    """
    checks = {
        "database": await check_database(db),
        "redis": await check_redis(),
        "s3": await check_s3(),
    }

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": checks,
        },
    )


@app.get("/ping", response_model=PingStateResponse)
async def get_ping_state(db: AsyncSession = Depends(get_db)) -> PingStateResponse:
    """Get current ping-pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        return PingStateResponse(state="ping", toggle_count=0, updated_at=None)

    return PingStateResponse.model_validate(state)


@app.post("/ping/toggle", response_model=PingStateResponse)
async def toggle_ping_state(db: AsyncSession = Depends(get_db)) -> PingStateResponse:
    """Toggle between ping and pong state."""
    result = await db.execute(select(PingState).order_by(PingState.id.desc()).limit(1))
    state = result.scalar_one_or_none()

    if state is None:
        new_state = PingState(state="pong", toggle_count=1)
        db.add(new_state)
        await db.commit()
        await db.refresh(new_state)
        return PingStateResponse.model_validate(new_state)

    state.state = "pong" if state.state == "ping" else "ping"
    state.toggle_count += 1
    await db.commit()
    await db.refresh(state)

    return PingStateResponse.model_validate(state)
