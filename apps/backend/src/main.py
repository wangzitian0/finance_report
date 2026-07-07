# pyright: reportMissingImports=false
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
from starlette.exceptions import HTTPException as StarletteHTTPException

# Eagerly register every ORM model on Base.metadata at app startup so SQLAlchemy
# can resolve cross-module string relationships (replaces the former
# ``from src.models import ...`` hub side effect; issue #1461).
import src.models._registry  # noqa: E402, F401
from src.boot import Bootloader, BootMode
from src.config import settings
from src.database import engine, get_db, init_db
from src.extraction.extension.statement_parsing_supervisor import run_parsing_supervisor
from src.identity import auth_router, users_router
from src.models.ping_state import PingState
from src.observability import (
    configure_database_pool_metrics,
    configure_logging,
    configure_otel_metrics,
    get_logger,
    get_observability_status,
    http_route_label_from_scope,
    log_observability_startup,
    log_security_warning,
    mark_fastapi_instrumentation_active,
    record_http_request,
    record_rate_limit_rejected,
)
from src.platform import BaseAppException, RateLimitConfig, RateLimiter
from src.routers import (
    accounts,
    ai_feedback,
    app_config,
    assets,
    audit,
    chat,
    classifications,
    corrections,
    evidence,
    income,
    journal,
    llm,
    market_data,
    metrics,
    portfolio,
    reports,
    review,
    statements,
    user_settings,
    workflow,
)
from src.routers.reconciliation import router as reconciliation_router
from src.runtime import resolve_env_tier
from src.runtime.extension.storage_sweep import run_storage_sweep
from src.schemas import PingStateResponse
from src.schemas.errors import (
    COMMON_ERROR_RESPONSES,
    ErrorCode,
    ErrorResponse,
    error_code_for_status,
)
from src.services.market_data_scheduler import run_market_data_scheduler

# Initialize logging early
configure_logging()
configure_otel_metrics()
configure_database_pool_metrics(engine)
logger = get_logger(__name__)


def _init_otel_instrumentation() -> None:
    """Initialize OpenTelemetry auto-instrumentation for SQLAlchemy and HTTPX.

    These are global instrumentors that do not require the FastAPI app instance,
    so they are wired here. FastAPI request instrumentation is bound to the app
    instance in `_instrument_fastapi_app` after the app is created.
    Must be called after the TracerProvider is configured.
    """
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # pyright: ignore[reportMissingImports]
        from opentelemetry.instrumentation.sqlalchemy import (
            SQLAlchemyInstrumentor,  # pyright: ignore[reportMissingImports]
        )

        # Instrument SQLAlchemy with the async engine
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

        # Instrument HTTPX for outbound HTTP calls
        HTTPXClientInstrumentor().instrument()

        logger.info("OTEL instrumentation initialized", components=["sqlalchemy", "httpx"])
    except Exception:  # pragma: no cover - defensive import guard
        logger.warning("OTEL instrumentation not available", exc_info=True)


def _instrument_fastapi_app(app: FastAPI) -> None:
    """Apply OpenTelemetry request instrumentation to the FastAPI app instance.

    Uses ``FastAPIInstrumentor.instrument_app(app)`` (the supported per-app API).
    The previous code used the base instrumentor's no-arg classmethod with no
    instance and before the app existed, which raised and silently disabled
    request tracing in production (see issue #768/#576).
    """
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # pyright: ignore[reportMissingImports]

        FastAPIInstrumentor.instrument_app(app)
        mark_fastapi_instrumentation_active(True)
        logger.info("OTEL FastAPI request instrumentation applied")
    except Exception:  # pragma: no cover - defensive import guard
        mark_fastapi_instrumentation_active(False)
        logger.warning("OTEL FastAPI instrumentation not available", exc_info=True)


# Initialize global (app-independent) instrumentation after logging is configured
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
    market_data_task = asyncio.create_task(run_market_data_scheduler(stop_event))
    sweep_task = asyncio.create_task(run_storage_sweep(stop_event))
    log_observability_startup(logger)
    logger.info("Application started", version="0.1.0")
    yield
    stop_event.set()
    supervisor_task.cancel()
    market_data_task.cancel()
    sweep_task.cancel()

    with suppress(asyncio.CancelledError):
        await supervisor_task
    with suppress(asyncio.CancelledError):
        await market_data_task
    with suppress(asyncio.CancelledError):
        await sweep_task
    logger.info("Application shutting down")


app = FastAPI(
    title="Finance Report API",
    description="Personal financial management system with double-entry bookkeeping",
    version="0.1.0",
    lifespan=lifespan,
)

# Apply OTEL request instrumentation to the app instance (issue #768/#576).
_instrument_fastapi_app(app)


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
        record_http_request(
            method=request.method,
            route=http_route_label_from_scope(request.scope),
            status_code=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )

        # Inject Request-ID into response headers
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration = time.perf_counter() - start_time
        record_http_request(
            method=request.method,
            route=http_route_label_from_scope(request.scope),
            status_code=500,
            duration_ms=round(duration * 1000, 2),
        )
        logger.exception(
            "HTTP Request Failed",
            duration_ms=round(duration * 1000, 2),
            error=str(exc),
        )
        raise


# Paths exempt from global API rate limiting
_RATE_LIMIT_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/ping",
        "/ping/toggle",
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
        "/redoc",
    }
)


# Composition root owns the config-bound app-wide rate limiter; the platform
# package stays config-free (only the RateLimiter class lives there).
api_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window,
        block_seconds=60,
    )
)


@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next: Any) -> Response:
    """Global API rate limiting middleware. Runs before logging middleware (LIFO order)."""
    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
        return await call_next(request)

    # Use the actual remote address only; honoring X-Forwarded-For requires a
    # trusted-proxy setup and is intentionally deferred to a future config option.
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = api_rate_limiter.is_allowed(client_ip)
    if not allowed:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=path,
        )
        record_rate_limit_rejected(scope="global_api")
        log_security_warning(
            logger,
            "rate_limit.rejected",
            reason="global_api_rate_limit",
            client_ip=client_ip,
            path=path,
            retry_after=retry_after,
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please try again later."},
            headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
        )
    return await call_next(request)


def _current_request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """Handle BaseAppException: return structured JSON with error_id and correct HTTP status."""
    request_id = _current_request_id()
    logger.warning(
        "Application exception",
        error_id=exc.error_id,
        status_code=exc.status_code,
        message=exc.message,
        request_id=request_id,
    )
    body = ErrorResponse(error_id=exc.error_id, detail=exc.message, request_id=request_id)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Emit the structured ``ErrorResponse`` shape for plain ``HTTPException``\\ s (#1005).

    Routers that still raise ``HTTPException(detail="...")`` get a stable,
    machine-readable ``error_id`` derived from the status code, so the frontend can
    branch on a code instead of parsing ``detail`` text. ``detail`` is preserved as
    a human-readable string for display and back-compat with existing callers.
    """
    request_id = _current_request_id()
    # Preserve the original ``detail`` verbatim: most call sites pass a string, but a
    # few raise ``HTTPException(detail={...})`` with a structured body. We add
    # ``error_id``/``request_id`` around it rather than coercing it to a string, so
    # those structured-detail endpoints keep working.
    content = {
        "error_id": error_code_for_status(exc.status_code).value,
        "detail": exc.detail,
        "request_id": request_id,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler to ensure a consistent structured JSON response."""
    # Log is already handled by middleware or logger.exception

    # Only show exception details in DEBUG mode
    if settings.debug:
        detail = str(exc)
        trace = traceback.format_exc()
    else:
        detail = "An internal server error occurred. Please try again later."
        trace = None

    request_id = _current_request_id()
    content: dict[str, Any] = ErrorResponse(
        error_id=ErrorCode.INTERNAL_ERROR.value,
        detail=detail,
        request_id=request_id,
    ).model_dump()
    if settings.debug:
        content["trace"] = trace
    return JSONResponse(status_code=500, content=content)


# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

# Include routers. Every router declares the shared 4xx/5xx ErrorResponse contract
# (#1005) so the structured-error shape is visible in the OpenAPI schema and the
# generated frontend client.
_router_kwargs = {"responses": COMMON_ERROR_RESPONSES}
app.include_router(auth_router, **_router_kwargs)
app.include_router(accounts.router, **_router_kwargs)
app.include_router(app_config.router, **_router_kwargs)
app.include_router(ai_feedback.router, **_router_kwargs)
app.include_router(audit.router, **_router_kwargs)
app.include_router(assets.router, **_router_kwargs)
app.include_router(chat.router, **_router_kwargs)
app.include_router(classifications.router, **_router_kwargs)
app.include_router(corrections.router, **_router_kwargs)
app.include_router(evidence.router, **_router_kwargs)
app.include_router(journal.router, **_router_kwargs)
app.include_router(market_data.router, **_router_kwargs)
app.include_router(metrics.router, **_router_kwargs)
app.include_router(income.router, **_router_kwargs)
app.include_router(reports.router, **_router_kwargs)
app.include_router(statements.router, **_router_kwargs)
app.include_router(review.router, **_router_kwargs)
app.include_router(review.conflicts_router, **_router_kwargs)
app.include_router(reconciliation_router, **_router_kwargs)
app.include_router(users_router, **_router_kwargs)
app.include_router(user_settings.router, **_router_kwargs)
app.include_router(llm.router, **_router_kwargs)
app.include_router(portfolio.router, **_router_kwargs)
app.include_router(workflow.router, **_router_kwargs)


# --- Health & Demo Endpoints ---


@app.get("/health")
async def health_check(full: bool = False, db: AsyncSession = Depends(get_db)) -> Response:
    """Check application health status with dependency checks.

    Returns 200 if all critical services are healthy, 503 otherwise.
    This endpoint is used by Docker healthcheck and deployment verification.

    The default (frequent Docker healthcheck) stays light: database + S3.
    ``?full=1`` asserts the FULL manifest-declared dependency set for this
    environment's tier (smoke ↔ declaration parity, invariant 6 / #1578): every
    dependency in ``DEPENDENCY_MANIFEST.required_for(tier)`` must be present or
    the endpoint returns 503. The smoke test calls this form.
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

        # S3
        s3_res = await Bootloader._check_s3()
        checks["s3"] = s3_res.status == "ok"

        tier = None
        if full:
            tier = resolve_env_tier(
                settings.environment, github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true"
            )
            probed, unprobed = Bootloader._required_checks(tier)
            names = sorted(probed.keys() - {"database", "object_storage"})
            # Probe concurrently — latency is the slowest single probe, not the sum
            # (each probe has its own ~5s timeout and never raises for an outage).
            results = await asyncio.gather(*(getattr(Bootloader, probed[name])() for name in names))
            for name, result in zip(names, results, strict=True):
                checks[name] = result.status == "ok"
            for name in unprobed:  # declared before its probe lands: visible, failing
                checks[name] = False

        all_healthy = all(checks.values())
        status_code = 200 if all_healthy else 503

        content = {
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": settings.git_commit_sha,
            "git_sha": settings.git_commit_sha,
            "checks": checks,
            "observability": get_observability_status(),
        }
        if tier is not None:
            content["tier"] = tier.value
        return JSONResponse(status_code=status_code, content=content)
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
