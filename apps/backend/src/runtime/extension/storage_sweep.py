"""Background service for sweeping orphaned storage objects."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.config
from src.database import async_session_maker
from src.observability import get_logger
from src.runtime.base.tiers import EnvTier, resolve_env_tier
from src.runtime.extension.storage import StorageError, StorageService

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    KnownStoragePathsProvider = Callable[[AsyncSession, "list[str]"], Awaitable["set[str]"]]

_known_paths_provider: KnownStoragePathsProvider | None = None
logger = get_logger(__name__)
settings = src.config.settings
STATEMENT_PREFIX = "statements/"


def register_known_storage_paths_provider(provider: KnownStoragePathsProvider) -> None:
    global _known_paths_provider
    _known_paths_provider = provider


def _get_known_paths_provider() -> KnownStoragePathsProvider:
    if _known_paths_provider is None:
        raise RuntimeError(
            "storage_sweep.register_known_storage_paths_provider() was never called — "
            "main.py wires it at startup (#1675 D3); a test exercising this path must call it too."
        )
    return _known_paths_provider


def _list_storage_keys(storage: StorageService) -> list[tuple[str, datetime]]:
    keys: list[tuple[str, datetime]] = []
    try:
        for page in storage.client.get_paginator("list_objects_v2").paginate(
            Bucket=storage.bucket, Prefix=STATEMENT_PREFIX
        ):
            for obj in page.get("Contents", []):
                modified: datetime = obj["LastModified"]
                keys.append((obj["Key"], modified if modified.tzinfo else modified.replace(tzinfo=UTC)))
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Failed to list storage objects: {exc}") from exc
    return keys


def _is_preview() -> bool:
    return resolve_env_tier(str(getattr(settings, "environment", ""))) is EnvTier.PREVIEW


async def sweep_orphaned_storage_objects(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Identify and delete S3 objects older than grace period without a DB record."""
    if _is_preview() or not settings.s3_bucket:
        return 0
    storage = StorageService()
    try:
        storage_keys = await run_in_threadpool(_list_storage_keys, storage)
    except StorageError as exc:
        logger.warning("Storage sweep: failed to list objects", error=str(exc))
        return 0
    if not storage_keys:
        return 0
    cutoff = datetime.now(UTC) - timedelta(hours=settings.storage_sweep_grace_period_hours)
    candidate_keys = [key for key, modified in storage_keys if modified < cutoff]
    if not candidate_keys:
        return 0
    async with (sessionmaker or async_session_maker)() as session:
        known_paths = await _get_known_paths_provider()(session, candidate_keys)
    orphaned = [key for key in candidate_keys if key not in known_paths]
    if not orphaned:
        return 0
    deleted = 0
    for key in orphaned:
        try:
            await run_in_threadpool(storage.delete_object, key)
            deleted += 1
            logger.info("Storage sweep: deleted orphaned object", key=key)
        except StorageError as exc:
            logger.warning("Storage sweep: failed to delete orphaned object", key=key, error=str(exc))
    logger.info("Storage sweep completed", scanned=len(candidate_keys), orphaned=len(orphaned), deleted=deleted)
    return deleted


async def run_storage_sweep(stop_event: asyncio.Event) -> None:
    """Run periodic storage sweeps until stop_event is set."""
    if not settings.enable_storage_sweep or _is_preview():
        return
    while not stop_event.is_set():
        try:
            if deleted := await sweep_orphaned_storage_objects():
                logger.info("Storage sweep removed orphaned objects", count=deleted)
        except Exception:
            logger.exception("Storage sweep encountered an unexpected error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.storage_sweep_interval_seconds)
        except TimeoutError:
            continue
