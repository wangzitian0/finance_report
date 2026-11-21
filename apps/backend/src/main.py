# pyright: reportMissingImports=false
"""Finance Report Backend - FastAPI Application."""

import asyncio
import logging
import os
import shutil
import subprocess
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from infra2_sdk.fastapi import init_service
from infra2_sdk.runtime.environment import resolve_environment_tier as resolve_sdk_environment_tier
from infra2_sdk.runtime.health import (
    Dependency as SdkDependency,
    DependencyKind as SdkDependencyKind,
    DependencyManifest as SdkDependencyManifest,
    DependencyStatus,
    ProbeResult,
)
from infra2_sdk.runtime.otel import PROBE_PATHS
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import src.orm_registry  # noqa: E402, F401
from src.advisor import register_fx_pairs_read
from src.boot import Bootloader, BootMode
from src.composition import market_data_scopes, observed_fx_pairs
from src.config import settings
from src.database import async_session_maker, engine, get_db, get_test_session_maker, init_db
from src.extraction import (
    get_known_storage_paths,
    reap_stale_parsing_runs,
    run_parsing_supervisor,
)
from src.identity import auth_router
from src.observability import (
    ErrorIds,
    configure_database_pool_metrics,
    configure_otel_metrics,
    current_request_id,
    get_logger,
    get_observability_status,
    log_observability_startup,
    log_security_warning,
    mark_fastapi_instrumentation_active,
    record_market_data_sync_failure,
    record_outbox_dead_letter,
    record_rate_limit_rejected,
)
from src.platform import (
    BaseAppException,
    OutboxRelay,
    RateLimitConfig,
    RateLimiter,
    SubscriberRegistry,
    get_client_ip,
)
from src.pricing import (
    run_daily_market_data_sync,
    run_market_data_scheduler,
    subscribe_price_ingest,
)
from src.routers import (
    accounts,
    chat,
    journal,
    llm,
    portfolio,
    pricing,
    reports,
    statements,
    user_settings,
    workflow,
)
from src.routers.reconciliation import router as reconciliation_router
from src.runtime import (
    BACKGROUND_JOBS,
    BACKGROUND_JOBS_BY_CLI,
    DEPENDENCY_MANIFEST,
    resolve_env_tier,
    run_storage_sweep,
    sweep_orphaned_storage_objects,
)
from src.schemas.errors import COMMON_ERROR_RESPONSES, ErrorCode, error_code_for_status

logger = get_logger(__name__)

register_fx_pairs_read(observed_fx_pairs)

outbox_subscribers = SubscriberRegistry()
subscribe_price_ingest(outbox_subscribers, session_factory=async_session_maker)
outbox_relay = OutboxRelay(
    outbox_subscribers,
    on_dead_letter=lambda event_type, source_pkg: record_outbox_dead_letter(
        event_type=event_type,
        source_pkg=source_pkg,
    ),
)
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


async def _run_parsing_reap_once() -> dict[str, int]:
    return {"reaped": await reap_stale_parsing_runs()}


async def _run_market_data_sync_once() -> dict[str, int]:
    try:
        await run_daily_market_data_sync(market_data_scopes)
    except Exception as exc:
        record_market_data_sync_failure(reason=type(exc).__name__)
        raise
    return {"completed": 1}


async def _run_storage_sweep_once() -> dict[str, int]:
    deleted = await sweep_orphaned_storage_objects(known_paths_provider=get_known_storage_paths)
    return {"deleted": deleted}


async def _run_outbox_drain_once() -> dict[str, int]:
    async with async_session_maker() as session:
        published = await outbox_relay.run_once(session)
    return {"published": published}


BACKGROUND_JOB_LOOPS: dict[str, Callable[[asyncio.Event], Coroutine[Any, Any, None]]] = {
    "parsing_supervisor": run_parsing_supervisor,
    "market_data_scheduler": lambda stop_event: run_market_data_scheduler(stop_event, market_data_scopes),
    "storage_sweep": lambda stop_event: run_storage_sweep(stop_event, known_paths_provider=get_known_storage_paths),
    "outbox_relay": run_outbox_relay,
}

BACKGROUND_JOB_ONCE: dict[str, Callable[[], Awaitable[dict[str, int]]]] = {
    "parsing_supervisor": _run_parsing_reap_once,
    "market_data_scheduler": _run_market_data_sync_once,
    "storage_sweep": _run_storage_sweep_once,
    "outbox_relay": _run_outbox_drain_once,
}


async def run_background_job_once(cli_name: str) -> dict[str, Any]:
    """Run one manual pass of a manifest-registered background job by CLI name."""
    spec = BACKGROUND_JOBS_BY_CLI.get(cli_name)
    if spec is None:
        raise ValueError(f"Unknown background job: {cli_name}")
    result = await BACKGROUND_JOB_ONCE[spec.name]()
    return {"job": spec.name, "cli_name": spec.cli_name, **result}


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


_PROBE_PATHS = PROBE_PATHS
_RATE_LIMIT_EXEMPT_PATHS = _PROBE_PATHS | frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"})


def _is_probe_scope(scope: Mapping[str, Any]) -> bool:
    return scope.get("path") in _PROBE_PATHS


def _sync_fastapi_telemetry_status(target_app: FastAPI) -> bool:
    """Sync request_instrumentation_active from FastAPI's built-in OTel middleware."""
    native = getattr(target_app, "_native_telemetry", None)
    active = bool(settings.otel_exporter_otlp_endpoint and native is not None and native.enabled())
    mark_fastapi_instrumentation_active(active)
    if active:
        logger.info("FastAPI built-in OTel telemetry active")
    return active


def _resolve_app_version(repo_dir: Path | None = None) -> str:
    """Resolve application version from APP_VERSION env, latest git tag, or GIT_COMMIT_SHA."""
    if repo_dir is None and (env_version := os.getenv("APP_VERSION", "").strip()):
        return env_version.lstrip("v")
    git_bin = shutil.which("git")
    if git_bin:
        try:
            tag = subprocess.check_output(
                [git_bin, "describe", "--tags", "--abbrev=0"],
                cwd=repo_dir or Path(__file__).resolve().parent,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
            if tag:
                return tag.lstrip("v")
        except (OSError, subprocess.SubprocessError):
            pass
    if sha := os.getenv("GIT_COMMIT_SHA", "").strip():
        if sha != "unknown":
            return sha
    return "0.1.0"


APP_VERSION = _resolve_app_version()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - init DB and background workers on startup."""
    _ = app
    await Bootloader.validate(mode=BootMode.CRITICAL)
    Bootloader.print_config()
    await init_db()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(BACKGROUND_JOB_LOOPS[job.name](stop_event)) for job in BACKGROUND_JOBS
    ]
    log_observability_startup(logger)
    logger.info("Application started", version=APP_VERSION)
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
    version=APP_VERSION,
    lifespan=lifespan,
    telemetry={"exclude": _is_probe_scope},
)


class _BootCheck:
    def __init__(self, name: str, fn: Callable[[], Awaitable[ProbeResult]]) -> None:
        self.name = name
        self._fn = fn

    async def probe(self) -> ProbeResult:
        try:
            return await self._fn()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Health check: Unexpected error in probe",
                error=str(exc),
                error_id=ErrorIds.HEALTH_CHECK_FAILED,
                check=self.name,
                error_type=type(exc).__name__,
            )
            return ProbeResult(self.name, DependencyStatus.ABSENT, str(exc), 0.0)


async def _check_database_probe() -> ProbeResult:
    if override := app.dependency_overrides.get(get_db):
        gen = override()
        try:
            async for session in gen:
                await session.execute(text("SELECT 1"))
                return ProbeResult("database", DependencyStatus.PRESENT, "ok", 0.0)
        except Exception as exc:  # noqa: BLE001
            return ProbeResult("database", DependencyStatus.ABSENT, str(exc), 0.0)
        finally:
            await gen.aclose()
    if test_maker := get_test_session_maker():
        try:
            async with test_maker() as session:
                await session.execute(text("SELECT 1"))
            return ProbeResult("database", DependencyStatus.PRESENT, "ok", 0.0)
        except Exception as exc:  # noqa: BLE001
            return ProbeResult("database", DependencyStatus.ABSENT, str(exc), 0.0)
    res = await Bootloader._check_database()
    status = DependencyStatus.PRESENT if res.status == "ok" else DependencyStatus.ABSENT
    return ProbeResult("database", status, res.message, res.duration_ms)


def _boot_method_check(dep_name: str, method_name: str) -> _BootCheck:
    async def _run() -> ProbeResult:
        res = await getattr(Bootloader, method_name)()
        status = DependencyStatus.PRESENT if res.status == "ok" else DependencyStatus.ABSENT
        return ProbeResult(dep_name, status, res.message, res.duration_ms)

    return _BootCheck(dep_name, _run)


def _build_sdk_manifest() -> SdkDependencyManifest:
    sdk_deps: list[SdkDependency] = []
    for dep in DEPENDENCY_MANIFEST:
        tiers = frozenset(resolve_sdk_environment_tier(t.value) for t in dep.required_in)
        sdk_deps.append(
            SdkDependency(
                name=dep.name,
                kind=SdkDependencyKind(dep.kind.value),
                required_in=tiers,
                env_vars=dep.env_vars,
                summary=dep.summary,
            )
        )
    return SdkDependencyManifest(sdk_deps)


def _health_extra() -> dict[str, Any]:
    in_gha = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "version": settings.git_commit_sha,
        "git_sha": settings.git_commit_sha,
        "observability": get_observability_status(),
        "sdk_environment_tier": resolve_sdk_environment_tier(
            settings.environment, github_actions=in_gha, unknown="production"
        ).value,
    }


def _build_health_checks() -> list[_BootCheck]:
    in_gha = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
    tier = resolve_env_tier(settings.environment, github_actions=in_gha)
    probed, _ = Bootloader._required_checks(tier)
    checks: list[_BootCheck] = []
    for name in sorted(probed):
        if name == "database":
            checks.append(_BootCheck("database", _check_database_probe))
        else:
            checks.append(_boot_method_check(name, probed[name]))
    return checks


if "ENVIRONMENT" not in os.environ:
    os.environ["ENVIRONMENT"] = settings.environment
if settings.otel_exporter_otlp_endpoint:
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", settings.otel_exporter_otlp_endpoint)
if settings.otel_service_name:
    os.environ.setdefault("OTEL_SERVICE_NAME", settings.otel_service_name)
if settings.otel_resource_attributes:
    os.environ.setdefault("OTEL_RESOURCE_ATTRIBUTES", settings.otel_resource_attributes)

init_service(
    app,
    "finance-report-backend",
    checks=_build_health_checks(),
    manifest=_build_sdk_manifest(),
    strict_otel=True,
    log_level=logging.DEBUG if settings.debug else logging.INFO,
    health_extra=_health_extra,
)
_otel_disabled = os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}
if not _otel_disabled:
    configure_otel_metrics()
    configure_database_pool_metrics(engine)
    _init_otel_instrumentation()
_sync_fastapi_telemetry_status(app)


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
    return JSONResponse(status_code=status_code, content=jsonable_encoder(content), headers=headers)


api_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window,
        block_seconds=60,
    ),
    namespace="global_api",
    redis_url=settings.redis_url,
)


@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT_PATHS or path.startswith(("/docs", "/redoc")):
        return await call_next(request)
    client_ip = get_client_ip(request, trust_proxy=settings.trust_proxy)
    allowed, retry_after = await api_rate_limiter.is_allowed_async(client_ip)
    if not allowed:
        request_id = current_request_id() or request.headers.get("X-Request-ID") or str(uuid4())
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
    return _error_json(
        exc.status_code,
        exc.error_id,
        exc.detail,
        request_id=request_id,
        headers=exc.headers,
        extra=exc.extra,
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
    # `input` echoes the request body (hints, notes, amounts) and `ctx` the validator state: keep loc, msg and type.
    errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
    return _error_json(422, ErrorCode.UNPROCESSABLE_ENTITY.value, jsonable_encoder(errors))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = str(exc) if settings.debug else "An internal server error occurred. Please try again later."
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    logger.exception(
        "HTTP Request Failed", error=str(exc), error_id=ErrorIds.UNHANDLED_EXCEPTION, request_id=request_id
    )
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
    chat.router,
    journal.router,
    reports.router,
    statements.router,
    reconciliation_router,
    user_settings.router,
    llm.router,
    portfolio.router,
    pricing.router,
    workflow.router,
):
    app.include_router(_router, responses=COMMON_ERROR_RESPONSES)
