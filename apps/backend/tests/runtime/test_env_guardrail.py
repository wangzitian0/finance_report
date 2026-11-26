from __future__ import annotations

import pytest
from infra2_sdk.config import EnvironmentTier
from infra2_sdk.service import Dependency, DependencyKind, DependencyManifest

from src.config import Settings
from src.runtime import DEPENDENCY_MANIFEST, NON_DEPENDENCY_ENV_FIELDS, check_env_classification
from src.runtime.base.env_classification import NON_DEPENDENCY_CATEGORIES, settings_env_keys

pytestmark = pytest.mark.no_db


def test_every_config_env_var_is_classified() -> None:
    assert check_env_classification(Settings) == []
    assert any(
        "database_url" in e
        for e in check_env_classification(
            Settings, non_dependency_fields={**NON_DEPENDENCY_ENV_FIELDS, "database_url": "tuning"}
        )
    )
    all_keys = {key for field in Settings.model_fields for key in settings_env_keys(Settings, field)}
    assert all(ev in all_keys for dep in DEPENDENCY_MANIFEST for ev in dep.env_vars)

    stray = DependencyManifest(
        dependencies=(
            Dependency(
                name="ghost",
                kind=DependencyKind.CODE_DOMINANT,
                required_in=frozenset({EnvironmentTier.PRODUCTION}),
                env_vars=frozenset({"GHOST_BACKEND_URL"}),
                summary="stray",
            ),
        )
    )
    assert any("GHOST_BACKEND_URL" in e for e in check_env_classification(Settings, manifest=stray))

    declared = {ev for dep in DEPENDENCY_MANIFEST for ev in dep.env_vars}
    matched_count = 0
    for field_name in Settings.model_fields:
        keys = settings_env_keys(Settings, field_name)
        if keys & declared:
            assert keys <= declared, f"{field_name}: undeclared aliases {sorted(keys - declared)}"
            matched_count += 1
    assert matched_count > 0
    assert set(NON_DEPENDENCY_ENV_FIELDS.values()) <= NON_DEPENDENCY_CATEGORIES
    assert {
        "S3_PUBLIC_ENDPOINT",
        "S3_PUBLIC_ACCESS_KEY",
        "S3_PUBLIC_SECRET_KEY",
        "S3_PUBLIC_BUCKET",
    } <= DEPENDENCY_MANIFEST.get("object_storage").env_vars


def test_guardrail_rejects_an_unclassified_new_field() -> None:
    class WithStray(Settings):
        shiny_new_backend_url: str = "http://nowhere"

    assert any("shiny_new_backend_url" in e for e in check_env_classification(WithStray))
