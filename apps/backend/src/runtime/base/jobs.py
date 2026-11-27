"""Pure background and batch job manifest (SSOT for lifespan and CLI replay)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConcurrencyStrategy = Literal[
    "skip_locked",
    "advisory_lock",
    "idempotent_upsert",
    "stateless_scan",
]


@dataclass(frozen=True)
class BackgroundJobSpec:
    """Contract binding one scheduled loop, manual CLI trigger, locking mode, and failure metric."""

    name: str
    cli_name: str
    concurrency: ConcurrencyStrategy
    failure_metric: str
    summary: str
    scheduler: Literal["prefect", "in_process"] = "prefect"


BACKGROUND_JOBS: tuple[BackgroundJobSpec, ...] = (
    BackgroundJobSpec(
        name="parsing_supervisor",
        cli_name="parsing-reap",
        concurrency="skip_locked",
        failure_metric="finance.async_parse.failure",
        summary="Reap stale statement parsing runs after heartbeat or claim timeout.",
        scheduler="prefect",
    ),
    BackgroundJobSpec(
        name="market_data_scheduler",
        cli_name="market-data-sync",
        concurrency="idempotent_upsert",
        failure_metric="finance.market_data.sync_failure",
        summary="Synchronize daily FX rates and equity prices across tracked scopes.",
        scheduler="prefect",
    ),
    BackgroundJobSpec(
        name="storage_sweep",
        cli_name="storage-sweep",
        concurrency="stateless_scan",
        failure_metric="finance.storage_sweep.failure",
        summary="Delete orphaned S3 objects older than the configured grace period.",
        scheduler="prefect",
    ),
    BackgroundJobSpec(
        name="outbox_relay",
        cli_name="outbox-drain",
        concurrency="skip_locked",
        failure_metric="finance.outbox.dead_letter",
        summary="Drain committed transactional outbox rows and quarantine poison pills.",
        scheduler="in_process",
    ),
)

BACKGROUND_JOBS_BY_NAME: dict[str, BackgroundJobSpec] = {job.name: job for job in BACKGROUND_JOBS}
BACKGROUND_JOBS_BY_CLI: dict[str, BackgroundJobSpec] = {job.cli_name: job for job in BACKGROUND_JOBS}
