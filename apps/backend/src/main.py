"""Finance Report Backend - FastAPI Application."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from src.boot import Bootloader, BootMode
from src.config import settings
from src.database import engine, init_db
from src.deps import DbSession
from src.logger import configure_logging, get_logger
from src.models import PingState
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
    if not settings.enable_otel:
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    # Initialize auto-instrumentation
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    HTTPXClientInstrumentor().instrument()

    logger.info("OpenTelemetry auto-instrumentation initialized")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan (startup/shutdown)."""
    # Initialize environment
    bootloader = Bootloader(mode=BootMode.CRITICAL)
    if not await bootloader.run():
        logger.critical("Bootloader failed, exiting")
        import sys

        sys.exit(1)

    # Run DB migrations
    await init_db()

    # Start background workers
    supervisor_task = asyncio.create_task(run_parsing_supervisor())

    _init_otel_instrumentation()

    logger.info("Application startup complete")
    yield

    # Clean up
    supervisor_task.cancel()
    with suppress(asyncio.CancelledError):
        await supervisor_task
    await engine.dispose()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Finance Report API",
    description="Backend API for Finance Report application",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next: Any) -> Response:
    """Middleware to track request processing time and request IDs."""
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)

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
    logger.exception("Unhandled exception", url=str(request.url))
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
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
async def health_check(db: DbSession):
    """Health check endpoint for monitoring."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "timestamp": time.time()}
    except Exception:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Database unreachable")


@app.get("/ping", response_model=PingStateResponse)
async def ping(db: DbSession):
    """Ping endpoint to test DB connectivity and session management."""
    result = await db.execute(select(PingState).limit(1))
    state = result.scalar_one_or_none()

    if not state:
        new_state = PingState(state="ping", toggle_count=0)
        db.add(new_state)
        await db.commit()
        await db.refresh(new_state)
        return PingStateResponse.model_validate(new_state)

    state.state = "pong" if state.state == "ping" else "ping"
    state.toggle_count += 1
    await db.commit()
    await db.refresh(state)

    return PingStateResponse.model_validate(state)
