"""``runtime`` — the app↔external-world dependency boundary (BE implementation).

`PackageContract.implementations["be"]` for the `runtime` package; the spec
(ubiquitous language, invariants, roadmap) lives in `common/runtime/`. Draft:
this ships the `base` value language + manifest + the `DependencyCheck` port. The
adapters, the assert-present enforcement, and the compose/lifecycle relocation
land in the switch/cleanup phases (see `common/runtime/todo.md`).
"""

from __future__ import annotations

from src.runtime.base.check import DependencyCheck, DependencyStatus
from src.runtime.base.kind import DependencyKind
from src.runtime.base.manifest import (
    DEPENDENCY_MANIFEST,
    Dependency,
    DependencyManifest,
)
from src.runtime.base.tiers import APP_OWNED_TIERS, VPS_TIERS, EnvTier

__all__ = [
    "APP_OWNED_TIERS",
    "DEPENDENCY_MANIFEST",
    "VPS_TIERS",
    "Dependency",
    "DependencyCheck",
    "DependencyKind",
    "DependencyManifest",
    "DependencyStatus",
    "EnvTier",
]
