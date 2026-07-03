"""``runtime`` — the app↔external-world dependency boundary (BE implementation).

`PackageContract.implementations["be"]` for the `runtime` package; the spec
(ubiquitous language, invariants, roadmap) lives in `common/runtime/`. Draft:
this ships the `base` value language + manifest + `DependencyCheck` port and the
`extension` probe adapters (`boot.Bootloader` delegates its checks to them). The
declared-required enforcement and the compose/lifecycle relocation land in the
cleanup phase (see `common/runtime/todo.md`).
"""

from __future__ import annotations

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
    DatabaseCheck,
    LlmCheck,
    ObjectStorageCheck,
)

__all__ = [
    "APP_OWNED_TIERS",
    "DEPENDENCY_MANIFEST",
    "NON_DEPENDENCY_ENV_FIELDS",
    "VPS_TIERS",
    "DatabaseCheck",
    "Dependency",
    "DependencyCheck",
    "DependencyKind",
    "DependencyManifest",
    "DependencyStatus",
    "EnvTier",
    "LlmCheck",
    "ObjectStorageCheck",
    "ProbeResult",
    "check_env_classification",
    "resolve_env_tier",
]
