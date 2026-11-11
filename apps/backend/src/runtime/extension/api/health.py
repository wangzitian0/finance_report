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
from src.database import async_session_maker, get_db, get_test_session_maker
from src.observability import ErrorIds, get_logger, get_observability_status
from src.runtime.base.tiers import resolve_env_tier

router = APIRouter()
logger = get_logger(__name__)
_test_session_maker = None


async def _get_health_db(request: Request, full: bool = False) -> AsyncGenerator[AsyncSession | None, None]:
    if not full:
        yield None
        return
    if override := request.app.dependency_overrides.get(get_db):
        async for session in override():
            yield session
            return
    maker = _test_session_maker or get_test_session_maker() or async_session_maker
    async with maker() as session:
        yield session


@router.get("/health")
async def health_check(full: bool = False, db: AsyncSession | None = Depends(_get_health_db)) -> Response:
    """Return fast liveness (default) or manifest-complete dependency health (?full=1)."""
    try:
        in_gha = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
        checks: dict[str, bool] = {}
        tier = None
        if not full:
            checks["liveness"] = True
        else:
            try:
                assert db is not None
                await db.execute(text("SELECT 1"))
                checks["database"] = True
            except Exception:
                checks["database"] = False
            checks["s3"] = (await Bootloader._check_s3()).status == "ok"
            tier = resolve_env_tier(settings.environment, github_actions=in_gha)
            probed, unprobed = Bootloader._required_checks(tier)
            names = sorted(probed.keys() - {"database", "object_storage"})
            results = await asyncio.gather(*(getattr(Bootloader, probed[name])() for name in names))
            checks.update({name: r.status == "ok" for name, r in zip(names, results, strict=True)})
            checks.update(dict.fromkeys(unprobed, False))

        sdk_tier = resolve_environment_tier(settings.environment, github_actions=in_gha, unknown="production")
        all_healthy = all(checks.values())
        content = {
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": settings.git_commit_sha,
            "git_sha": settings.git_commit_sha,
            "checks": checks,
            "observability": get_observability_status(),
            "sdk_environment_tier": sdk_tier.value,
            **({"tier": tier.value} if tier is not None else {}),
        }
        return JSONResponse(status_code=200 if all_healthy else 503, content=content)
    except Exception as exc:  # noqa: BLE001
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
