"""Background service for sweeping orphaned storage objects.

Process crashes or timeouts during statement upload can leave S3 objects
without a corresponding database record. This service runs periodically
to detect and remove such orphaned objects.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from botocore.exceptions import BotoCoreError, ClientError
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.database import async_session_maker
from src.logger import get_logger
from src.models import UploadedDocument
from src.services import StorageError, StorageService

logger = get_logger(__name__)

STATEMENT_PREFIX = "statements/"

# Sweep cadence and grace period are config-driven (issue #356): the live values
# are read from ``settings.storage_sweep_*`` at call time (see
# ``sweep_orphaned_storage_objects`` and ``run_storage_sweep`` below) so that
# environment changes and test-time patching of ``settings`` take effect.


def _list_storage_keys(storage: StorageService) -> list[tuple[str, datetime]]:
    """List all statement keys with their last-modified timestamps from S3."""
    keys: list[tuple[str, datetime]] = []
    paginator = storage.client.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=storage.bucket, Prefix=STATEMENT_PREFIX):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                last_modified: datetime = obj["LastModified"]
                # Ensure timezone-aware
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=UTC)
                keys.append((key, last_modified))
    except (BotoCoreError, ClientError) as exc:
        raise StorageError(f"Failed to list storage objects: {exc}") from exc
    return keys


async def sweep_orphaned_storage_objects(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Identify and delete S3 objects that have no corresponding DB record.

    Only objects older than the configured grace period
    (``settings.storage_sweep_grace_period_hours``) are considered, to avoid deleting
    objects that are still being uploaded or whose DB record is being committed.

    Returns:
        Number of orphaned objects deleted.
    """
    if not settings.s3_bucket:
        logger.debug("Storage sweep skipped - no S3 bucket configured")
        return 0

    storage = StorageService()
    try:
        storage_keys = await run_in_threadpool(_list_storage_keys, storage)
    except StorageError as exc:
        logger.warning("Storage sweep: failed to list objects", error=str(exc))
        return 0

    if not storage_keys:
        return 0

    grace_period = timedelta(hours=settings.storage_sweep_grace_period_hours)
    cutoff = datetime.now(UTC) - grace_period
    candidate_keys = [key for key, modified in storage_keys if modified < cutoff]

    if not candidate_keys:
        return 0

    # Fetch all known file paths from the database
    session_factory = sessionmaker or async_session_maker
    async with session_factory() as session:
        result = await session.execute(
            select(UploadedDocument.file_path).where(UploadedDocument.file_path.in_(candidate_keys))
        )
        known_paths: set[str] = {row[0] for row in result.all()}

    orphaned = [key for key in candidate_keys if key not in known_paths]
    if not orphaned:
        logger.debug("Storage sweep: no orphaned objects found", scanned=len(candidate_keys))
        return 0

    deleted = 0
    for key in orphaned:
        try:
            await run_in_threadpool(storage.delete_object, key)
            deleted += 1
            logger.info("Storage sweep: deleted orphaned object", key=key)
        except StorageError as exc:
            logger.warning("Storage sweep: failed to delete orphaned object", key=key, error=str(exc))

    logger.info(
        "Storage sweep completed",
        scanned=len(candidate_keys),
        orphaned=len(orphaned),
        deleted=deleted,
    )
    return deleted


async def run_storage_sweep(stop_event: asyncio.Event) -> None:
    """Run periodic storage sweeps until stop_event is set.

    Exits immediately (no-op) when ``settings.enable_storage_sweep`` is False,
    which is recommended for CI/test environments where an S3 service is not
    running to avoid spurious network errors and noisy log output.
    """
    if not settings.enable_storage_sweep:
        logger.debug("Storage sweep disabled via ENABLE_STORAGE_SWEEP setting")
        return
    while not stop_event.is_set():
        try:
            deleted = await sweep_orphaned_storage_objects()
            if deleted:
                logger.info("Storage sweep removed orphaned objects", count=deleted)
        except Exception:
            logger.exception("Storage sweep encountered an unexpected error")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.storage_sweep_interval_seconds)
        except TimeoutError:
            continue
