"""AC-runtime.2.1 — the config↔manifest env-var guardrail (#1579).

`runtime` is the SSOT for *which* env vars configure each external dependency
(`Dependency.env_vars`); everything else in `config.py` is a non-dependency env
var that stays with `config` and its domain package. This gate closes the gap
between the two: every `Settings` field must be classified — either one of a
declared dependency's env vars, or a reasoned entry in
`NON_DEPENDENCY_ENV_FIELDS`. A brand-new field with neither fails here, so a new
external backend can never slip into `config.py` without a manifest entry
(fail-closed, same pattern as `check_package_directory_coverage`).
"""

from __future__ import annotations

import pytest

from src.config import Settings
from src.runtime import (
    DEPENDENCY_MANIFEST,
    NON_DEPENDENCY_ENV_FIELDS,
    check_env_classification,
)
from src.runtime.base.env_classification import (
    NON_DEPENDENCY_CATEGORIES,
    settings_env_keys,
)

pytestmark = pytest.mark.no_db


def test_every_config_env_var_is_classified() -> None:
    """AC-runtime.2.1: no unclassified, double-classified, or orphaned env var."""
    assert check_env_classification(Settings) == []


def test_guardrail_rejects_an_unclassified_new_field() -> None:
    """A new Settings field that is neither declared nor classified is caught."""

    class WithStray(Settings):
        shiny_new_backend_url: str = "http://nowhere"

    errors = check_env_classification(WithStray)
    assert any("shiny_new_backend_url" in e for e in errors)


def test_guardrail_rejects_double_classification() -> None:
    """A field cannot be both a dependency env var and a non-dependency entry."""
    errors = check_env_classification(
        Settings,
        non_dependency_fields={**NON_DEPENDENCY_ENV_FIELDS, "database_url": "tuning"},
    )
    assert any("database_url" in e for e in errors)


def test_every_declared_env_var_binds_to_a_settings_field() -> None:
    """Manifest side of the reconciliation: no orphaned/typo'd declaration."""
    all_keys = {key for field in Settings.model_fields for key in settings_env_keys(Settings, field)}
    for dep in DEPENDENCY_MANIFEST:
        for env_var in dep.env_vars:
            assert env_var in all_keys, f"{dep.name}: declared {env_var} has no Settings field"


def test_classification_categories_are_the_documented_set() -> None:
    """Categories mirror the charter's 'feature/security/domain stay with config'."""
    assert set(NON_DEPENDENCY_ENV_FIELDS.values()) <= NON_DEPENDENCY_CATEGORIES


def test_public_bucket_env_vars_are_owned_by_object_storage() -> None:
    """The optional public-bucket S3 client is the same external backend —
    its env vars belong to the object_storage declaration, not a side channel."""
    declared = DEPENDENCY_MANIFEST.get("object_storage").env_vars
    assert {
        "S3_PUBLIC_ENDPOINT",
        "S3_PUBLIC_ACCESS_KEY",
        "S3_PUBLIC_SECRET_KEY",
        "S3_PUBLIC_BUCKET",
    } <= declared
