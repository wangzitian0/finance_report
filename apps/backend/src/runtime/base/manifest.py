"""`DependencyManifest` — the declared external dependencies of the app.

This is the single source of truth for *what the runtime depends on*: each
external backend, its `DependencyKind`, and the `EnvTier`s that require it to be
present. It is pure data (no imports of `config`/`boot`); the parity test binds
it to `config.py`, and later phases (switch/cleanup) route `boot.validate` and
the smoke test through it so a *declared* dependency that is *absent* fails
(invariant 2). Kept deliberately declarative here — no I/O, no probing.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.runtime.base.kind import DependencyKind
from src.runtime.base.tiers import EnvTier


@dataclass(frozen=True)
class Dependency:
    """One external backend the app depends on.

    `required_in` is the set of tiers where the dependency MUST be present; it is
    never empty (a dependency the app never requires anywhere does not belong in
    the manifest). The *backend* behind it may differ per tier (in-memory vs real)
    — the manifest declares the requirement, not the implementation.
    """

    name: str
    kind: DependencyKind
    required_in: frozenset[EnvTier]
    summary: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Dependency.name must be non-empty")
        if not self.required_in:
            raise ValueError(
                f"dependency {self.name!r} is required in no tier; a dependency "
                "must be required somewhere (no silent-optional dependencies)"
            )


class DependencyManifest:
    """The frozen set of declared dependencies, with tier/name lookups."""

    def __init__(self, dependencies: tuple[Dependency, ...]) -> None:
        names = [d.name for d in dependencies]
        if len(names) != len(set(names)):
            raise ValueError("duplicate dependency name in manifest")
        self._by_name: dict[str, Dependency] = {d.name: d for d in dependencies}

    def __iter__(self):
        return iter(self._by_name.values())

    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def get(self, name: str) -> Dependency:
        return self._by_name[name]

    def required_for(self, tier: EnvTier) -> frozenset[str]:
        """Names of the dependencies that must be present in `tier`."""
        return frozenset(d.name for d in self._by_name.values() if tier in d.required_in)


_ALL = frozenset(EnvTier)
_VPS = frozenset({EnvTier.PREVIEW, EnvTier.STAGING, EnvTier.PRODUCTION})

#: The app's declared external dependencies. `required_in` values are a starting
#: declaration refined as the switch phase wires enforcement; the *kind* is the
#: stable contract (it decides the substitute strategy).
DEPENDENCY_MANIFEST = DependencyManifest(
    (
        Dependency(
            name="database",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=_ALL,
            summary="Postgres — the system of record (DATABASE_URL).",
        ),
        Dependency(
            name="object_storage",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=_ALL,
            summary="S3-compatible object storage for uploaded statements (S3_*).",
        ),
        Dependency(
            name="llm",
            kind=DependencyKind.MODEL_DOMINANT,
            required_in=_ALL,
            summary="The AI provider used for statement extraction (AI_*); "
            "recorded in CI/preview, real on staging/prod.",
        ),
        Dependency(
            name="cache",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=_VPS,
            summary="Redis (REDIS_URL) — optional in the app-owned tiers.",
        ),
        Dependency(
            name="workflow_engine",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=frozenset({EnvTier.STAGING, EnvTier.PRODUCTION}),
            summary="Prefect (PREFECT_API_URL) — durable flows; in-process fallback in the app-owned tiers.",
        ),
        Dependency(
            name="telemetry",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=_VPS,
            summary="OTel exporter (OTEL_EXPORTER_OTLP_ENDPOINT).",
        ),
        Dependency(
            name="analytics",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=frozenset({EnvTier.STAGING, EnvTier.PRODUCTION}),
            summary="OpenPanel product analytics (OPENPANEL_API_URL).",
        ),
        Dependency(
            name="market_data",
            kind=DependencyKind.CODE_DOMINANT,
            required_in=frozenset({EnvTier.PRODUCTION}),
            summary="Yahoo Finance market-data fetch for report-side FX.",
        ),
    )
)
