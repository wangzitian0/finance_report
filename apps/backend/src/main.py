"""Finance Report Backend - FastAPI Application."""

import asyncio
import os
import time
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
    and external API calls without manual code instrumentation.
    """
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        # Global instrumentation
        FastAPIInstrumentor.instrument()
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        HTTPXClientInstrumentor().instrument()

        logger.info("OpenTelemetry auto-instrumentation initialized")
    except Exception:
        logger.warning("OTEL instrumentation not available", exc_info=True)


# Initialize instrumentation BEFORE app creation
_init_otel_instrumentation()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan (startup/shutdown)."""
    # Environment variable check
    if not await Bootloader.validate(mode=BootMode.CRITICAL):
        logger.critical("Bootloader failed, exiting")
        import sys

        sys.exit(1)

    # Run DB migrations
    await init_db()

    # Start background workers
    stop_event = asyncio.Event()
    supervisor_task = asyncio.create_task(run_parsing_supervisor(stop_event))

    logger.info("Application startup complete")
    yield

    # Clean up
    stop_event.set()
    supervisor_task.cancel()
    with suppress(asyncio.CancelledError):
        await supervisor_task

    # Close rate limiters
    auth_rate_limiter.close()
    register_rate_limiter.close()

    await engine.dispose()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Finance Report API",
    description="Backend API for Finance Report application",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next: Any) -> Response:
    """Middleware to track request processing time and request IDs."""
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
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
    """Catch-all for unhandled exceptions to prevent internal details leak."""
    logger.exception("Unhandled exception", url=str(request.url), error=str(exc))

    detail = str(exc) if settings.debug else "An internal server error occurred."

    return JSONResponse(
        status_code=500,
        content={
            "detail": detail,
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
app.include_router(statements.router)
app.include_router(reconciliation.router)
app.include_router(users.router)


# --- Health & Demo Endpoints ---


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> Response:
    """Check application health status with dependency checks."""
    try:
        checks = {}

        # DB
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        # Use a fresh bootloader for detailed checks
        boot = Bootloader(mode=BootMode.DRY_RUN)

        # Redis
        redis_res = await boot._check_redis()
        checks["redis"] = redis_res.status == "ok" or redis_res.status == "skipped"

        # S3
        s3_res = await boot._check_s3()
        checks["s3"] = s3_res.status == "ok" or s3_res.status == "skipped"

        all_healthy = all(checks.values())
        # Only DB is critical for readiness in some environments
        is_ready = checks["database"]
        status_code = 200 if is_ready else 503

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
        logger.exception("Health check failed")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "timestamp": datetime.now(UTC).isoformat(),
                "error": str(e),
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
