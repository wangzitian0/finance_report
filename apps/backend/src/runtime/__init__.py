"""``runtime`` — the app↔external-world dependency boundary (BE implementation).

`PackageContract.implementations["be"]` for the `runtime` package; the spec
(ubiquitous language, invariants, roadmap) lives in `common/runtime/`. This
ships the `base` manifest/jobs/env-classification definitions and the `extension`
probe adapters (`boot.Bootloader` delegates its checks to them). The SDK types
(`Dependency`, `DependencyCheck`, `DependencyKind`, `DependencyManifest`,
`DependencyStatus`, `EnvironmentTier`, `ProbeResult`, `resolve_tier`)
live in `infra2_sdk.{config,service}` and must be imported directly from there.
"""

from __future__ import annotations

from src.runtime.base.env_classification import (
    NON_DEPENDENCY_ENV_FIELDS,
    check_env_classification,
    resolve_tier_or_production,
)
from src.runtime.base.jobs import (
    BACKGROUND_JOBS,
    BACKGROUND_JOBS_BY_CLI,
    BACKGROUND_JOBS_BY_NAME,
    BackgroundJobSpec,
)
from src.runtime.base.manifest import DEPENDENCY_MANIFEST
from src.runtime.extension.adapters import (
    AnalyticsCheck,
    DatabaseCheck,
    LlmCheck,
    MarketDataCheck,
    ObjectStorageCheck,
    RedisCheck,
    TelemetryCheck,
    WorkflowEngineCheck,
)
from src.runtime.extension.storage import StorageError, StorageService, redact_presigned_url
from src.runtime.extension.storage_sweep import run_storage_sweep, sweep_orphaned_storage_objects

__all__ = [
    "AnalyticsCheck",
    "BACKGROUND_JOBS",
    "BACKGROUND_JOBS_BY_CLI",
    "BACKGROUND_JOBS_BY_NAME",
    "BackgroundJobSpec",
    "DEPENDENCY_MANIFEST",
    "DatabaseCheck",
    "LlmCheck",
    "MarketDataCheck",
    "NON_DEPENDENCY_ENV_FIELDS",
    "ObjectStorageCheck",
    "RedisCheck",
    "StorageError",
    "StorageService",
    "TelemetryCheck",
    "WorkflowEngineCheck",
    "check_env_classification",
    "redact_presigned_url",
    "resolve_tier_or_production",
    "run_storage_sweep",
    "sweep_orphaned_storage_objects",
]
