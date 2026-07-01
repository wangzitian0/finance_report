"""`runtime` dependency-manifest tests (draft: value language + config parity).

These anchor the construct phase: the manifest is well-formed, binds to real
`config.py` settings, and encodes the substitute-kind contract. Enforcement of
"declared ⇒ asserted present" (routing `boot.validate`/smoke through the manifest)
lands in the switch phase and gets its own roadmap AC then.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.runtime import (
    APP_OWNED_TIERS,
    DEPENDENCY_MANIFEST,
    Dependency,
    DependencyKind,
    DependencyStatus,
    EnvTier,
)

pytestmark = pytest.mark.no_db

# Each declared dependency is backed by a real Settings field (the manifest is
# grounded in config.py, not free-floating).
_CONFIG_BACKING = {
    "database": "database_url",
    "object_storage": "s3_endpoint",
    "llm": "ai_base_url",
    "cache": "redis_url",
    "workflow_engine": "prefect_api_url",
    "telemetry": "otel_exporter_otlp_endpoint",
    "analytics": "openpanel_api_url",
    "market_data": "market_data_yahoo_timeout_seconds",
}


def test_manifest_declares_the_known_external_dependencies() -> None:
    assert DEPENDENCY_MANIFEST.names() == frozenset(_CONFIG_BACKING)


def test_every_dependency_is_backed_by_a_real_config_setting() -> None:
    for name, attr in _CONFIG_BACKING.items():
        assert name in DEPENDENCY_MANIFEST.names()
        assert hasattr(settings, attr), f"{name}: settings.{attr} missing"


def test_every_dependency_is_required_somewhere_no_silent_optional() -> None:
    # A dependency required in no tier is meaningless; `Dependency` forbids it.
    for dep in DEPENDENCY_MANIFEST:
        assert dep.required_in, dep.name
    with pytest.raises(ValueError):
        Dependency(name="x", kind=DependencyKind.CODE_DOMINANT, required_in=frozenset(), summary="s")


def test_llm_is_the_only_model_dominant_dependency() -> None:
    model = {d.name for d in DEPENDENCY_MANIFEST if d.kind is DependencyKind.MODEL_DOMINANT}
    assert model == {"llm"}


def test_required_for_tier_returns_the_declared_subset() -> None:
    # database + object_storage + llm are required in every tier.
    for tier in EnvTier:
        required = DEPENDENCY_MANIFEST.required_for(tier)
        assert {"database", "object_storage", "llm"} <= required
    # market_data is production-only.
    assert "market_data" in DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION)
    assert "market_data" not in DEPENDENCY_MANIFEST.required_for(EnvTier.GITHUB_CI)


def test_app_owned_tiers_are_the_compose_hostable_three() -> None:
    assert APP_OWNED_TIERS == frozenset({EnvTier.LOCAL_DEV, EnvTier.LOCAL_CI, EnvTier.GITHUB_CI})


def test_status_is_binary_no_skipped() -> None:
    assert {s.value for s in DependencyStatus} == {"present", "absent"}
