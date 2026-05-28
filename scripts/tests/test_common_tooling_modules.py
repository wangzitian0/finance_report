"""Tests for the common shared tooling foundation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from common.coverage import policy as coverage_policy  # noqa: E402
from common.ssot import ac_registry_format, ac_traceability_refs  # noqa: E402
from common import test_isolation  # noqa: E402


def test_AC8_13_53_common_ssot_helpers_are_the_authoritative_imports():
    """AC8.13.53: SSOT helper logic is owned under common."""
    payload = {
        "groups": {
            "AC8": {
                "AC8.13": [
                    {
                        "id": "AC8.13.53",
                        "description": "Common shared tooling",
                    }
                ]
            }
        }
    }

    entries = list(ac_registry_format.iter_registry_entries(payload))
    assert entries == [
        {
            "id": "AC8.13.53",
            "description": "Common shared tooling",
        }
    ]
    assert ac_registry_format.epic_group_key("AC8.13.53") == "AC8"
    assert ac_registry_format.scenario_group_key("AC8.13.53") == "AC8.13"
    assert (
        ac_traceability_refs.classify_reference_file(
            Path("tests/test_common.py"),
            'def test_contract():\n    """AC8.13.53: real reference"""\n    assert True\n',
        )
        == "real"
    )


def test_AC8_13_53_legacy_script_shared_modules_delegate_to_common():
    """AC8.13.53: Existing scripts imports stay compatible during migration."""
    legacy_registry = importlib.import_module("ac_registry_format")
    legacy_refs = importlib.import_module("ac_traceability_refs")
    legacy_coverage = importlib.import_module("coverage_policy")

    assert (
        legacy_registry.load_registry_entries
        is ac_registry_format.load_registry_entries
    )
    assert (
        legacy_refs.classify_reference_file
        is ac_traceability_refs.classify_reference_file
    )
    assert legacy_coverage.CoverageComponent is coverage_policy.CoverageComponent


def test_AC8_13_53_common_coverage_component_is_a_governed_source_root():
    """AC8.13.53: Common code is measured as its own coverage component."""
    component = coverage_policy.get_component("common")

    assert component.component_root == ""
    assert component.source_subdir == "common"
    assert component.ci_lcov_path == "coverage/common.lcov"
    assert "common/test_isolation.py" in component.expected_sources(ROOT)


def test_AC8_13_53_common_isolation_names_are_stable_and_bounded():
    """AC8.13.53: Test isolation naming is reusable outside scripts."""
    namespace = test_isolation.sanitize_namespace("Feature/Auth-v2")

    assert namespace == "feature_auth_v2"
    assert test_isolation.get_env_suffix(namespace) == "-feature_auth_v2"
    assert test_isolation.get_s3_bucket(namespace) == "statements-feature-auth-v2"

    long_namespace = "feature_" + "x" * 120
    db_name = test_isolation.get_test_db_name(long_namespace)
    bucket = test_isolation.get_s3_bucket(long_namespace)

    assert db_name.startswith("finance_report_test_feature_")
    assert len(db_name) <= test_isolation.MAX_POSTGRES_IDENTIFIER_LENGTH
    assert bucket.startswith("statements-feature-")
    assert len(bucket) <= test_isolation.MAX_S3_BUCKET_LENGTH
