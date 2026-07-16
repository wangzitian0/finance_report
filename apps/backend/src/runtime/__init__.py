"""``runtime`` — the app↔external-world dependency boundary (BE implementation).

`PackageContract.implementations["be"]` for the `runtime` package; the spec
(ubiquitous language, invariants, roadmap) lives in `common/runtime/`. This
ships the `base` value language + manifest + `DependencyCheck` port and the
`extension` probe adapters (`boot.Bootloader` delegates its checks to them). The
declared-required enforcement and the compose/lifecycle integration.
"""

from __future__ import annotations

from importlib import import_module

from src.runtime.base.check import (
    DependencyCheck,
    DependencyStatus,
    ProbeResult,
)
from src.runtime.base.env_classification import (
    NON_DEPENDENCY_ENV_FIELDS,
    check_env_classification,
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
from src.runtime.extension.storage_sweep import (
    register_known_storage_paths_provider,
    run_storage_sweep,
)

__all__ = [
    "APP_OWNED_TIERS",
    "AnalyticsCheck",
    "DEPENDENCY_MANIFEST",
    "DatabaseCheck",
    "Dependency",
    "DependencyCheck",
    "DependencyKind",
    "DependencyManifest",
    "DependencyStatus",
    "EnvTier",
    "LlmCheck",
    "MarketDataCheck",
    "NON_DEPENDENCY_ENV_FIELDS",
    "ObjectStorageCheck",
    "ProbeResult",
    "RedisCheck",
    "StorageError",
    "StorageService",
    "TelemetryCheck",
    "VPS_TIERS",
    "WorkflowEngineCheck",
    "check_env_classification",
    "redact_presigned_url",
    "register_known_storage_paths_provider",
    "resolve_env_tier",
    "run_storage_sweep",
    "runtime_system_router",
]


def __getattr__(name: str) -> object:
    """Resolve the HTTP router lazily to avoid boot/runtime import cycles."""
    if name != "runtime_system_router":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("src.runtime.extension.api"), "router")
    globals()[name] = value
    return value
