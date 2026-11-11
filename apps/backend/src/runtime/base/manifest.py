"""`DependencyManifest` — the declared external dependencies of the app."""

from __future__ import annotations

from dataclasses import dataclass

from src.runtime.base.kind import DependencyKind
from src.runtime.base.tiers import EnvTier

__all__ = ["DEPENDENCY_MANIFEST", "Dependency", "DependencyManifest"]


@dataclass(frozen=True)
class Dependency:
    """One external backend the app depends on."""

    name: str
    kind: DependencyKind
    required_in: frozenset[EnvTier]
    env_vars: frozenset[str]
    summary: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Dependency.name must be non-empty")
        if not self.required_in:
            raise ValueError(
                f"dependency {self.name!r} is required in no tier; a dependency "
                "must be required somewhere (no silent-optional dependencies)"
            )
        if not self.env_vars:
            raise ValueError(
                f"dependency {self.name!r} declares no env vars; runtime is the "
                "SSOT for which env vars configure each external dependency"
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
        return frozenset(d.name for d in self._by_name.values() if tier in d.required_in)


_ALL = frozenset(EnvTier)
_VPS = frozenset({EnvTier.PREVIEW, EnvTier.STAGING, EnvTier.PRODUCTION})
_SP = frozenset({EnvTier.STAGING, EnvTier.PRODUCTION})


def _dep(
    name: str,
    kind: DependencyKind,
    required_in: frozenset[EnvTier],
    *,
    env_vars: tuple[str, ...],
    summary: str,
) -> Dependency:
    return Dependency(
        name=name,
        kind=kind,
        required_in=required_in,
        env_vars=frozenset(env_vars),
        summary=summary,
    )


DEPENDENCY_MANIFEST = DependencyManifest(
    (
        _dep(
            "database",
            DependencyKind.CODE_DOMINANT,
            _ALL,
            env_vars=("DATABASE_URL",),
            summary="Postgres — the system of record (DATABASE_URL).",
        ),
        _dep(
            "object_storage",
            DependencyKind.CODE_DOMINANT,
            _ALL,
            env_vars=(
                "S3_ENDPOINT",
                "S3_ACCESS_KEY",
                "S3_SECRET_KEY",
                "S3_BUCKET",
                "S3_REGION",
                "S3_PUBLIC_ENDPOINT",
                "S3_PUBLIC_ACCESS_KEY",
                "S3_PUBLIC_SECRET_KEY",
                "S3_PUBLIC_BUCKET",
            ),
            summary="S3-compatible object storage for uploaded statements (S3_*).",
        ),
        _dep(
            "llm",
            DependencyKind.MODEL_DOMINANT,
            _SP,
            env_vars=("AI_PROVIDER", "AI_API_KEY", "ZAI_API_KEY", "AI_BASE_URL"),
            summary="The AI provider used for statement extraction (AI_*); recorded (cassette substitute) in CI/preview, real on staging/prod.",
        ),
        _dep(
            "cache",
            DependencyKind.CODE_DOMINANT,
            _SP,
            env_vars=("REDIS_URL",),
            summary="Redis (REDIS_URL) — optional in the app-owned tiers and preview.",
        ),
        _dep(
            "workflow_engine",
            DependencyKind.CODE_DOMINANT,
            _SP,
            env_vars=("PREFECT_API_URL",),
            summary="Prefect (PREFECT_API_URL) — durable flows; in-process fallback in the app-owned tiers.",
        ),
        _dep(
            "telemetry",
            DependencyKind.CODE_DOMINANT,
            _VPS,
            env_vars=("OTEL_EXPORTER_OTLP_ENDPOINT",),
            summary="OTel exporter (OTEL_EXPORTER_OTLP_ENDPOINT).",
        ),
        _dep(
            "analytics",
            DependencyKind.CODE_DOMINANT,
            _SP,
            env_vars=("OPENPANEL_API_URL", "OPENPANEL_CLIENT_ID"),
            summary="OpenPanel product analytics (OPENPANEL_API_URL).",
        ),
        _dep(
            "market_data",
            DependencyKind.CODE_DOMINANT,
            frozenset({EnvTier.PRODUCTION}),
            env_vars=("MARKET_DATA_YAHOO_TIMEOUT_SECONDS",),
            summary="Yahoo Finance market-data fetch for report-side FX.",
        ),
    )
)
