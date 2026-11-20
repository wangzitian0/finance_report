"""``runtime`` — the app↔external-world dependency boundary (BE implementation).

`PackageContract.implementations["be"]` for the `runtime` package; the spec
(ubiquitous language, invariants, roadmap) lives in `common/runtime/`. This
ships the `base` value language + manifest and the `extension` probe adapters
(`boot.Bootloader` delegates its checks to them). The `DependencyCheck` port,
`DependencyStatus` and `ProbeResult` are the infra2-sdk types in
`infra2_sdk.runtime.health`. Import them from there. This package does not re-export
them, because its published interface lists only names that the repo defines.
The declared-required enforcement and the compose/lifecycle integration.
"""

from __future__ import annotations

from src.runtime.base.env_classification import (
    NON_DEPENDENCY_ENV_FIELDS,
    check_env_classification,
)
from src.runtime.base.jobs import (
    BACKGROUND_JOBS,
    BACKGROUND_JOBS_BY_CLI,
    BACKGROUND_JOBS_BY_NAME,
    BackgroundJobSpec,
)
from src.runtime.base.kind import DependencyKind
from src.runtime.base.manifest import (
    DEPENDENCY_MANIFEST,
    Dependency,
    DependencyManifest,
)
from src.runtime.base.tiers import APP_OWNED_TIERS, VPS_TIERS, EnvTier, resolve_env_tier
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
    "APP_OWNED_TIERS",
    "AnalyticsCheck",
    "BACKGROUND_JOBS",
    "BACKGROUND_JOBS_BY_CLI",
    "BACKGROUND_JOBS_BY_NAME",
    "BackgroundJobSpec",
    "DEPENDENCY_MANIFEST",
    "DatabaseCheck",
    "Dependency",
    "DependencyKind",
    "DependencyManifest",
    "EnvTier",
    "LlmCheck",
    "MarketDataCheck",
    "NON_DEPENDENCY_ENV_FIELDS",
    "ObjectStorageCheck",
    "RedisCheck",
    "StorageError",
    "StorageService",
    "TelemetryCheck",
    "VPS_TIERS",
    "WorkflowEngineCheck",
    "check_env_classification",
    "redact_presigned_url",
    "resolve_env_tier",
    "run_storage_sweep",
    "sweep_orphaned_storage_objects",
]
