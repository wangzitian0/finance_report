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


def test_AC8_13_55_tools_coverage_component_is_a_governed_source_root():
    """AC8.13.55: Tools entry points are measured separately from shared code."""
    component = coverage_policy.get_component("tools")

    assert component.component_root == ""
    assert component.source_subdir == "tools"
    assert component.ci_lcov_path == "coverage/tools.lcov"
    assert "tools/coverage/calculate_unified_coverage.py" in component.expected_sources(
        ROOT
    )


def test_AC8_13_55_coverage_tools_delegate_to_common_implementations():
    """AC8.13.55: Coverage commands live under tools and delegate to common."""
    build_tool = importlib.import_module("tools.coverage.build_unified_lcov")
    calc_tool = importlib.import_module("tools.coverage.calculate_unified_coverage")
    analyzer_tool = importlib.import_module("tools.coverage.coverage_analyzer")
    merge_tool = importlib.import_module("tools.coverage.merge_lcov")
    policy_tool = importlib.import_module("tools.coverage.check_coverage_policy")
    metrics_tool = importlib.import_module("tools.ci.check_ci_metrics_contract")
    coveralls_tool = importlib.import_module("tools.ci.mark_coveralls_reporting_status")

    assert (
        build_tool.main
        is importlib.import_module("common.coverage.build_unified_lcov").main
    )
    assert (
        calc_tool.main
        is importlib.import_module("common.coverage.calculate_unified_coverage").main
    )
    assert (
        analyzer_tool.main is importlib.import_module("common.coverage.analyzer").main
    )
    assert merge_tool.main is importlib.import_module("common.coverage.merge_lcov").main
    assert (
        policy_tool.main is importlib.import_module("common.coverage.check_policy").main
    )
    assert (
        metrics_tool.main is importlib.import_module("common.ci.metrics_contract").main
    )
    assert (
        coveralls_tool.main
        is importlib.import_module("common.ci.coveralls_status").main
    )


def test_AC8_13_55_legacy_coverage_scripts_delegate_to_common():
    """AC8.13.55: Legacy coverage scripts are wrappers during migration."""
    legacy_build = importlib.import_module("build_unified_lcov")
    legacy_calc = importlib.import_module("calculate_unified_coverage")
    legacy_analyzer = importlib.import_module("coverage_analyzer")
    legacy_policy = importlib.import_module("check_coverage_policy")
    legacy_merge = importlib.import_module("merge_lcov")
    legacy_metrics = importlib.import_module("check_ci_metrics_contract")
    legacy_coveralls = importlib.import_module("mark_coveralls_reporting_status")

    assert (
        legacy_build.main
        is importlib.import_module("common.coverage.build_unified_lcov").main
    )
    assert (
        legacy_calc.main
        is importlib.import_module("common.coverage.calculate_unified_coverage").main
    )
    assert (
        legacy_policy.main
        is importlib.import_module("common.coverage.check_policy").main
    )
    assert (
        legacy_analyzer.main is importlib.import_module("common.coverage.analyzer").main
    )
    assert (
        legacy_merge.main is importlib.import_module("common.coverage.merge_lcov").main
    )
    assert (
        legacy_metrics.main
        is importlib.import_module("common.ci.metrics_contract").main
    )
    assert (
        legacy_coveralls.main
        is importlib.import_module("common.ci.coveralls_status").main
    )


def test_AC8_13_56_ssot_tools_delegate_to_common_implementations():
    """AC8.13.56: SSOT commands live under tools and delegate to common."""
    command_modules = {
        "tools.ssot.analyze_test_ac_coverage": "common.ssot.analyze_test_ac_coverage",
        "tools.ssot.audit_ac_epic_mismatches": "common.ssot.audit_ac_epic_mismatches",
        "tools.ssot.build_ac_traceability": "common.ssot.build_ac_traceability",
        "tools.ssot.check_ac_traceability": "common.ssot.check_ac_traceability",
        "tools.ssot.check_critical_proof_matrix": (
            "common.ssot.check_critical_proof_matrix"
        ),
        "tools.ssot.check_manifest": "common.ssot.check_manifest",
        "tools.ssot.check_ssot_ownership": "common.ssot.check_ssot_ownership",
        "tools.ssot.generate_ac_registry": "common.ssot.generate_ac_registry",
        "tools.ssot.lint_doc_consistency": "common.ssot.lint_doc_consistency",
    }

    for tool_module, common_module in command_modules.items():
        assert (
            importlib.import_module(tool_module).main
            is importlib.import_module(common_module).main
        )


def test_AC8_13_56_legacy_ssot_scripts_delegate_to_common():
    """AC8.13.56: Legacy SSOT scripts are wrappers during migration."""
    legacy_modules = {
        "analyze_test_ac_coverage": "common.ssot.analyze_test_ac_coverage",
        "audit_ac_epic_mismatches": "common.ssot.audit_ac_epic_mismatches",
        "build_ac_traceability": "common.ssot.build_ac_traceability",
        "check_ac_traceability": "common.ssot.check_ac_traceability",
        "check_critical_proof_matrix": "common.ssot.check_critical_proof_matrix",
        "check_manifest": "common.ssot.check_manifest",
        "check_ssot_ownership": "common.ssot.check_ssot_ownership",
        "generate_ac_registry": "common.ssot.generate_ac_registry",
        "lint_doc_consistency": "common.ssot.lint_doc_consistency",
    }

    for legacy_module, common_module in legacy_modules.items():
        assert importlib.import_module(legacy_module) is importlib.import_module(
            common_module
        )


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
