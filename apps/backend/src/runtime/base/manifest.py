"""`DependencyManifest` — the declared external dependencies of the app."""

from __future__ import annotations

from infra2_sdk.runtime.environment import EnvironmentTier
from infra2_sdk.runtime.health import Dependency, DependencyKind, DependencyManifest

__all__ = ["DEPENDENCY_MANIFEST"]

_ALL = frozenset(EnvironmentTier)
_VPS = frozenset({EnvironmentTier.PREVIEW, EnvironmentTier.STAGING, EnvironmentTier.PRODUCTION})
_SP = frozenset({EnvironmentTier.STAGING, EnvironmentTier.PRODUCTION})


def _dep(
    name: str,
    kind: DependencyKind,
    required_in: frozenset[EnvironmentTier],
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
            env_vars=("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL"),
            summary="AI provider for statement extraction and advisor (LLM_*); required on staging and production.",
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
            _SP,
            env_vars=("MARKET_DATA_YAHOO_TIMEOUT_SECONDS",),
            summary="Yahoo Finance market-data fetch for report-side FX.",
        ),
    )
)
