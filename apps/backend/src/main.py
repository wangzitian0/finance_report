# pyright: reportMissingImports=false
"""Finance Report Backend - FastAPI Application."""

import asyncio
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import src.orm_registry  # noqa: E402, F401
from src.advisor import register_fx_pairs_read
from src.boot import Bootloader, BootMode
from src.composition import market_data_scopes, observed_fx_pairs
from src.config import settings
from src.database import async_session_maker, engine, init_db
from src.extraction import (
    ActiveRunExists,
    StatementClassificationBusy,
    find_in_flight_parse_id,
    get_known_storage_paths,
    get_statement_coverage_rows,
    register_position_reconciler,
    run_parsing_supervisor,
)
from src.identity import auth_router, register_in_flight_parse_checker, users_router
from src.ledger import register_statement_coverage_reader
from src.observability import (
    ErrorIds,
    configure_database_pool_metrics,
    configure_logging,
    configure_otel_metrics,
    current_request_id,
    get_logger,
    http_route_label_from_scope,
    log_observability_startup,
    log_security_warning,
    mark_fastapi_instrumentation_active,
    record_http_request,
    record_rate_limit_rejected,
)
from src.platform import (
    BaseAppException,
    OutboxRelay,
    RateLimitConfig,
    RateLimiter,
    SubscriberRegistry,
    get_client_ip,
    platform_system_router,
)
from src.portfolio import PositionService
from src.pricing import (
    build_manual_valuation_lines,
    build_manual_valuation_lines_series,
    run_market_data_scheduler,
    subscribe_price_ingest,
)
from src.reporting import register_manual_valuation_lines_provider
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
from src.runtime import register_known_storage_paths_provider, run_storage_sweep, runtime_system_router
from src.schemas.errors import COMMON_ERROR_RESPONSES, ErrorCode, error_code_for_status

configure_logging()
configure_otel_metrics()
configure_database_pool_metrics(engine)
logger = get_logger(__name__)

register_fx_pairs_read(observed_fx_pairs)
register_manual_valuation_lines_provider(
    build_manual_valuation_lines, series_provider=build_manual_valuation_lines_series
)
register_known_storage_paths_provider(get_known_storage_paths)
register_statement_coverage_reader(get_statement_coverage_rows)
register_in_flight_parse_checker(find_in_flight_parse_id)
register_position_reconciler(PositionService().reconcile_positions)

outbox_subscribers = SubscriberRegistry()
subscribe_price_ingest(outbox_subscribers, session_factory=async_session_maker)
outbox_relay = OutboxRelay(outbox_subscribers)
OUTBOX_RELAY_POLL_SECONDS = 1.0


async def run_outbox_relay(stop_event: asyncio.Event) -> None:
    """Drain committed outbox rows periodically until shutdown."""
    while not stop_event.is_set():
        try:
            async with async_session_maker() as session:
                await outbox_relay.run_once(session)
        except Exception:
            logger.exception("Outbox relay pass failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=OUTBOX_RELAY_POLL_SECONDS)


def _init_otel_instrumentation() -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # pyright: ignore[reportMissingImports]
        from opentelemetry.instrumentation.sqlalchemy import (
            SQLAlchemyInstrumentor,  # pyright: ignore[reportMissingImports]
        )

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        HTTPXClientInstrumentor().instrument()
        logger.info("OTEL instrumentation initialized", components=["sqlalchemy", "httpx"])
    except Exception:  # pragma: no cover
        logger.warning("OTEL instrumentation not available", exc_info=True)


def _instrument_fastapi_app(app: FastAPI) -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry.instrumentation.fastapi import (
            FastAPIInstrumentor,  # pyright: ignore[reportMissingImports]
        )

        FastAPIInstrumentor.instrument_app(app)
        mark_fastapi_instrumentation_active(True)
        logger.info("OTEL FastAPI request instrumentation applied")
    except Exception:  # pragma: no cover
        mark_fastapi_instrumentation_active(False)
        logger.warning("OTEL FastAPI instrumentation not available", exc_info=True)


_init_otel_instrumentation()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - init DB and background workers on startup."""
    _ = app
    await Bootloader.validate(mode=BootMode.CRITICAL)
    Bootloader.print_config()
    await init_db()
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(run_parsing_supervisor(stop_event)),
        asyncio.create_task(run_market_data_scheduler(stop_event, market_data_scopes)),
        asyncio.create_task(run_storage_sweep(stop_event)),
        asyncio.create_task(run_outbox_relay(stop_event)),
    ]
    log_observability_startup(logger)
    logger.info("Application started", version="0.1.0")
    yield
    stop_event.set()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    logger.info("Application shutting down")


app = FastAPI(
    title="Finance Report API",
    description="Personal financial management system with double-entry bookkeeping",
    version="0.1.0",
    lifespan=lifespan,
)
_instrument_fastapi_app(app)

_PROBE_PATHS = frozenset({"/health"})
_RATE_LIMIT_EXEMPT_PATHS = _PROBE_PATHS | frozenset(
    {"/ping", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
)


def _is_successful_probe(path: str, status_code: int) -> bool:
    return path in _PROBE_PATHS and 200 <= status_code < 300


def _bind_request_ctx(request_id: str, method: str, path: str) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, method=method, path=path)


def _error_json(
    status_code: int,
    error_id: str,
    detail: Any,
    *,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    rid = request_id if request_id is not None else current_request_id()
    content: dict[str, Any] = {"error_id": error_id, "detail": detail, "request_id": rid}
    if extra:
        content.update(extra)
    return JSONResponse(status_code=status_code, content=content, headers=headers)


@app.middleware("http")
async def logging_middleware(request: Request, call_next: Any) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    _bind_request_ctx(request_id, request.method, request.url.path)
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if not _is_successful_probe(request.url.path, response.status_code):
            logger.info("HTTP Request", status_code=response.status_code, duration_ms=duration_ms)
        record_http_request(
            method=request.method,
            route=http_route_label_from_scope(request.scope),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        record_http_request(
            method=request.method,
            route=http_route_label_from_scope(request.scope),
            status_code=500,
            duration_ms=duration_ms,
        )
        logger.exception(
            "HTTP Request Failed", duration_ms=duration_ms, error=str(exc), error_id=ErrorIds.UNHANDLED_EXCEPTION
        )
        raise


api_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window,
        block_seconds=60,
    )
)


@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT_PATHS or path.startswith(("/docs", "/redoc")):
        return await call_next(request)
    client_ip = get_client_ip(request, trust_proxy=settings.trust_proxy)
    allowed, retry_after = api_rate_limiter.is_allowed(client_ip)
    if not allowed:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        _bind_request_ctx(request_id, request.method, path)
        record_rate_limit_rejected(scope="global_api")
        log_security_warning(
            logger,
            "rate_limit.rejected",
            reason="global_api_rate_limit",
            client_ip=client_ip,
            path=path,
            retry_after=retry_after,
        )
        return _error_json(
            429,
            ErrorCode.TOO_MANY_REQUESTS.value,
            "Rate limit exceeded. Please try again later.",
            request_id=request_id,
            headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
        )
    return await call_next(request)


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    _ = request
    request_id = current_request_id()
    logger.warning(
        "Application exception",
        error_id=exc.error_id,
        status_code=exc.status_code,
        message=exc.message,
        request_id=request_id,
    )
    return _error_json(exc.status_code, exc.error_id, exc.message, request_id=request_id)


@app.exception_handler(StatementClassificationBusy)
async def statement_classification_busy_handler(request: Request, exc: StatementClassificationBusy) -> JSONResponse:
    _ = request
    return _error_json(409, error_code_for_status(409).value, str(exc))


@app.exception_handler(ActiveRunExists)
async def active_run_exists_handler(request: Request, exc: ActiveRunExists) -> JSONResponse:
    _ = request
    return _error_json(
        409,
        error_code_for_status(409).value,
        "The statement has an active run. Wait for it to end.",
        extra={"active_run_id": str(exc.active_run_id)},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    _ = request
    return _error_json(
        exc.status_code,
        error_code_for_status(exc.status_code).value,
        exc.detail,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    _ = request
    return _error_json(422, ErrorCode.UNPROCESSABLE_ENTITY.value, jsonable_encoder(exc.errors()))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = str(exc) if settings.debug else "An internal server error occurred. Please try again later."
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    return _error_json(
        500,
        ErrorCode.INTERNAL_ERROR.value,
        detail,
        request_id=request_id,
        headers={"X-Request-ID": request_id} if request_id else None,
        extra={"trace": traceback.format_exc()} if settings.debug else None,
    )


_cors_regex = settings.cors_origin_regex.strip() if settings.cors_origin_regex else ""
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=_cors_regex if _cors_regex and _cors_regex != "^$" else None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

for _router in (
    auth_router,
    accounts.router,
    app_config.router,
    ai_feedback.router,
    audit.router,
    assets.router,
    chat.router,
    classifications.router,
    corrections.router,
    evidence.router,
    journal.router,
    market_data.router,
    metrics.router,
    income.router,
    reports.router,
    statements.router,
    review.router,
    review.conflicts_router,
    reconciliation_router,
    users_router,
    user_settings.router,
    llm.router,
    portfolio.router,
    workflow.router,
    workflow.notifications_router,
    runtime_system_router,
    platform_system_router,
):
    app.include_router(_router, responses=COMMON_ERROR_RESPONSES)
