"""Finance Report Backend - FastAPI Application."""

import asyncio
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.config import settings
from src.database import get_db, init_db
from src.env_check import check_env_on_startup, print_loaded_config
from src.logger import configure_logging, get_logger
from src.models import PingState
from src.routers import accounts, ai_models, auth, chat, journal, reports, statements, users
from src.routers.reconciliation import router as reconciliation_router
from src.schemas import PingStateResponse
from src.services.statement_parsing_supervisor import run_parsing_supervisor

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


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Check application health status."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


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