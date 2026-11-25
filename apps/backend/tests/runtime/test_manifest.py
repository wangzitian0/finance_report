from __future__ import annotations

import pytest
from infra2_sdk.runtime.health import DependencyStatus

from src.config import Settings, settings
from src.runtime import APP_OWNED_TIERS, DEPENDENCY_MANIFEST, Dependency, DependencyKind, EnvTier
from src.runtime.base.env_classification import settings_env_keys

pytestmark = pytest.mark.no_db

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
    assert all(hasattr(settings, attr) for attr in _CONFIG_BACKING.values())
    all_keys = {key for field in Settings.model_fields for key in settings_env_keys(Settings, field)}
    for dep in DEPENDENCY_MANIFEST:
        assert dep.env_vars and dep.required_in, dep.name
        assert all(ev.isupper() and ev in all_keys for ev in dep.env_vars), dep.name

    with pytest.raises(ValueError):
        Dependency(name="x", kind=DependencyKind.CODE_DOMINANT, required_in=frozenset(), env_vars=frozenset({"X"}), summary="s")
    assert {d.name for d in DEPENDENCY_MANIFEST if d.kind is DependencyKind.MODEL_DOMINANT} == {"llm"}
    assert all({"database", "object_storage"} <= DEPENDENCY_MANIFEST.required_for(t) for t in EnvTier)
    assert "llm" in DEPENDENCY_MANIFEST.required_for(EnvTier.STAGING) and "llm" not in DEPENDENCY_MANIFEST.required_for(EnvTier.PREVIEW)
    assert "cache" in DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION) and "cache" not in DEPENDENCY_MANIFEST.required_for(EnvTier.PREVIEW)
    assert {"market_data"} <= DEPENDENCY_MANIFEST.required_for(EnvTier.STAGING)
    assert "market_data" in DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION) and "market_data" not in DEPENDENCY_MANIFEST.required_for(EnvTier.GITHUB_CI)
    assert APP_OWNED_TIERS == frozenset({EnvTier.LOCAL_DEV, EnvTier.LOCAL_CI, EnvTier.GITHUB_CI})
    assert {s.value for s in DependencyStatus} == {"present", "absent"}
