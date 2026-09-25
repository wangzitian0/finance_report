"""Application health HTTP endpoint."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from infra2_sdk.runtime.environment import resolve_environment_tier
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.boot import Bootloader
from src.config import settings
from src.database import _test_session_maker, async_session_maker, get_db
from src.observability import ErrorIds, get_logger, get_observability_status
from src.runtime.base.tiers import resolve_env_tier

router = APIRouter()
logger = get_logger(__name__)


async def _get_health_db(
    request: Request,
    full: bool = False,
) -> AsyncGenerator[AsyncSession | None, None]:
    """Provide a database session only when full readiness health check is requested."""
    if not full:
        yield None
        return

    if get_db in request.app.dependency_overrides:
        override = request.app.dependency_overrides[get_db]
        async for session in override():
            yield session
            return

    maker = _test_session_maker or async_session_maker
    async with maker() as session:
        yield session


@router.get("/health")
async def health_check(
    full: bool = False,
    db: AsyncSession | None = Depends(_get_health_db),
) -> Response:
    """Return fast liveness (default) or manifest-complete dependency health (?full=1)."""
    try:
        checks: dict[str, bool] = {}
        tier = None
        if not full:
            # Cheap liveness path: zero external I/O, fast return (<10ms)
            checks["liveness"] = True
        else:
            # Full readiness path: probe database, s3, and tier-manifest dependencies
            try:
                assert db is not None
                await db.execute(text("SELECT 1"))
                checks["database"] = True
            except Exception:
                checks["database"] = False

            s3_result = await Bootloader._check_s3()
            checks["s3"] = s3_result.status == "ok"

            tier = resolve_env_tier(
                settings.environment,
                github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true",
            )
            probed, unprobed = Bootloader._required_checks(tier)
            names = sorted(probed.keys() - {"database", "object_storage"})
            results = await asyncio.gather(*(getattr(Bootloader, probed[name])() for name in names))
            for name, result in zip(names, results, strict=True):
                checks[name] = result.status == "ok"
            for name in unprobed:
                checks[name] = False

        # infra2_sdk.runtime.environment's tier vocabulary as a second, independent
        # opinion alongside `tier` below (src.runtime.base.tiers.EnvTier) — not a
        # replacement. The two enums' values diverge on one name (this repo's
        # "local_ci" vs the SDK's "local_test", kept as an *input* alias for this
        # repo specifically — see the SDK's own resolve_environment_tier docstring)
        # and on unknown-value handling (EnvTier defaults unknown to PRODUCTION;
        # the SDK raises unless told unknown="production", which is passed here to
        # match this repo's existing fail-closed-to-strictest behavior). Swapping
        # `tier` itself to the SDK type is a separate, larger change — every
        # `content["tier"]` consumer would see "local_ci" become "local_test".
        sdk_tier = resolve_environment_tier(
            settings.environment,
            github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true",
            unknown="production",
        )

        all_healthy = all(checks.values())
        content = {
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": settings.git_commit_sha,
            "git_sha": settings.git_commit_sha,
            "checks": checks,
            "observability": get_observability_status(),
            "sdk_environment_tier": sdk_tier.value,
        }
        if tier is not None:
            content["tier"] = tier.value
            content["vault_secrets"] = Bootloader.vault_secrets_snapshot()
        return JSONResponse(status_code=200 if all_healthy else 503, content=content)
    except Exception as exc:  # noqa: BLE001 - health must always return a verdict
        logger.error(
            "Health check: Unexpected error in endpoint",
            error=str(exc),
            error_id=ErrorIds.HEALTH_CHECK_FAILED,
            error_type=type(exc).__name__,
            error_module=type(exc).__module__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "timestamp": datetime.now(UTC).isoformat(),
                "error": "Health check failed with unexpected error",
                "error_type": type(exc).__name__,
            },
        )
