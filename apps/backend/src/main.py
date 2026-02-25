"""Finance Report Backend - FastAPI Application."""

import asyncio
import os
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.boot import Bootloader, BootMode
from src.config import settings
from src.database import engine, get_db, init_db
from src.logger import configure_logging, get_logger
from src.models import PingState
from src.rate_limit import auth_rate_limiter, register_rate_limiter
from src.routers import (
    accounts,
    ai_models,
    assets,
    auth,
    chat,
    journal,
    reconciliation,
    reports,
    review,
    statements,
    users,
)
from src.schemas import PingStateResponse
from src.services.statement_parsing_supervisor import run_parsing_supervisor

# Initialize logging early
configure_logging()
logger = get_logger(__name__)


def _init_otel_instrumentation() -> None:
    """Initialize OpenTelemetry auto-instrumentation for FastAPI, SQLAlchemy, and HTTPX.

    This enables distributed tracing across HTTP requests, database queries,
    and outbound HTTP calls. Must be called after TracerProvider is configured.
    """
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        # Instrument FastAPI - will be applied to app after creation
        FastAPIInstrumentor.instrument()

        # Instrument SQLAlchemy with the async engine
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

        # Instrument HTTPX for outbound HTTP calls
        HTTPXClientInstrumentor().instrument()

        logger.info("OTEL instrumentation initialized", components=["fastapi", "sqlalchemy", "httpx"])
    except Exception:  # pragma: no cover - defensive import guard
        logger.warning("OTEL instrumentation not available", exc_info=True)


# Initialize instrumentation after logging is configured
_init_otel_instrumentation()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - init DB on startup."""
    # Environment variable check
    # Bootloader check (Critical Only)
    # This ensures we have DB connectivity before accepting traffic
    # Will sys.exit(1) if critical checks fail
    await Bootloader.validate(mode=BootMode.CRITICAL)
    Bootloader.print_config()

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
app.include_router(assets.router)
app.include_router(chat.router)
app.include_router(journal.router)
app.include_router(reports.router)
app.include_router(review.router)
app.include_router(statements.router)
app.include_router(reconciliation.router)
app.include_router(users.router)


# --- Health & Demo Endpoints ---


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> Response:
    """Check application health status with dependency checks.

    Returns 200 if all critical services are healthy, 503 otherwise.
    This endpoint is used by Docker healthcheck and deployment verification.
    """
    try:
        # Use Bootloader's internal check methods to ensure consistency
        # We don't use validate() here because we want granular report
        checks = {}

        # DB (Use session from dependency for consistency with request scope)
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        # Redis
        redis_res = await Bootloader._check_redis()
        checks["redis"] = redis_res.status == "ok" or redis_res.status == "skipped"

        # S3
        s3_res = await Bootloader._check_s3()
        checks["s3"] = s3_res.status == "ok" or s3_res.status == "skipped"

        all_healthy = all(checks.values())
        status_code = 200 if all_healthy else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if all_healthy else "unhealthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "git_sha": os.getenv("GIT_COMMIT_SHA", "unknown"),
                "checks": checks,
                "version": settings.git_commit_sha,
            },
        )
    except Exception as e:
        logger.error(
            "Health check: Unexpected error in endpoint",
            error=str(e),
            error_type=type(e).__name__,
            error_module=type(e).__module__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "timestamp": datetime.now(UTC).isoformat(),
                "error": "Health check failed with unexpected error",
                "error_type": type(e).__name__,
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
