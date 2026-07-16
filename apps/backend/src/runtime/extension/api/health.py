"""Application health HTTP endpoint."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.boot import Bootloader
from src.config import settings
from src.database import get_db
from src.observability import get_logger, get_observability_status
from src.runtime.base.tiers import resolve_env_tier

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health")
async def health_check(full: bool = False, db: AsyncSession = Depends(get_db)) -> Response:
    """Return light or manifest-complete dependency health."""
    try:
        checks: dict[str, bool] = {}
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        s3_result = await Bootloader._check_s3()
        checks["s3"] = s3_result.status == "ok"

        tier = None
        if full:
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

        all_healthy = all(checks.values())
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
            content["vault_secrets"] = Bootloader.vault_secrets_snapshot()
        return JSONResponse(status_code=200 if all_healthy else 503, content=content)
    except Exception as exc:  # noqa: BLE001 - health must always return a verdict
        logger.error(
            "Health check: Unexpected error in endpoint",
            error=str(exc),
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
