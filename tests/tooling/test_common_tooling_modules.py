"""Tests for the common shared tooling foundation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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


def test_AC8_13_53_root_scripts_tree_is_removed():
    """AC8.13.53: Root scripts are removed after command migration."""
    assert not (ROOT / "scripts").exists()


def test_AC8_13_53_common_coverage_component_is_a_governed_source_root():
    """AC8.13.53: Common code is measured as its own coverage component."""
    component = coverage_policy.get_component("common")

    assert component.component_root == ""
    assert component.source_subdir == "common"
    assert component.ci_lcov_path == "coverage/common.lcov"
    assert "common/test_isolation.py" in component.expected_sources(ROOT)
    assert "common/dev/test_lifecycle.py" in component.expected_sources(ROOT)


def test_AC8_13_56_tools_coverage_component_is_a_governed_source_root():
    """AC8.13.56: Tools entry points are measured separately from shared code."""
    component = coverage_policy.get_component("tools")

    assert component.component_root == ""
    assert component.source_subdir == "tools"
    assert component.ci_lcov_path == "coverage/tools.lcov"
    assert "tools/calculate_unified_coverage.py" in component.expected_sources(ROOT)


def test_AC8_13_56_coverage_tools_delegate_to_common_implementations():
    """AC8.13.56: Coverage commands live under tools and delegate to common."""
    build_tool = importlib.import_module("tools.build_unified_lcov")
    calc_tool = importlib.import_module("tools.calculate_unified_coverage")
    analyzer_tool = importlib.import_module("tools.coverage_analyzer")
    merge_tool = importlib.import_module("tools.merge_lcov")
    policy_tool = importlib.import_module("tools.check_coverage_policy")
    metrics_tool = importlib.import_module("tools.check_ci_metrics_contract")

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


def test_AC8_13_57_ssot_tools_delegate_to_common_implementations():
    """AC8.13.57: SSOT commands live under tools and delegate to common."""
    command_modules = {
        "tools.analyze_test_ac_coverage": "common.ssot.analyze_test_ac_coverage",
        "tools.audit_ac_epic_mismatches": "common.ssot.audit_ac_epic_mismatches",
        "tools.build_ac_traceability": "common.ssot.build_ac_traceability",
        "tools.check_ac_traceability": "common.ssot.check_ac_traceability",
        "tools.check_critical_proof_matrix": (
            "common.ssot.check_critical_proof_matrix"
        ),
        "tools.check_manifest": "common.ssot.check_manifest",
        "tools.check_ssot_ownership": "common.ssot.check_ssot_ownership",
        "tools.generate_ac_registry": "common.ssot.generate_ac_registry",
        "tools.lint_doc_consistency": "common.ssot.lint_doc_consistency",
    }

    for tool_module, common_module in command_modules.items():
        assert (
            importlib.import_module(tool_module).main
            is importlib.import_module(common_module).main
        )


def test_AC8_13_58_ci_tools_delegate_to_common_implementations():
    """AC8.13.58: CI commands live under tools and delegate to common."""
    command_modules = {
        "tools.check_toolchain_contract": "common.ci.check_toolchain_contract",
        "tools.ci_change_classifier": "common.ci.change_classifier",
        "tools.github_workflow_timing_summary": (
            "common.ci.github_workflow_timing_summary"
        ),
    }

    for tool_module, common_module in command_modules.items():
        assert (
            importlib.import_module(tool_module).main
            is importlib.import_module(common_module).main
        )


def test_AC8_13_59_config_validation_tools_delegate_to_common_implementations():
    """AC8.13.59: Config validation commands live under tools and delegate to common."""
    command_modules = {
        "tools.check_env_keys": "common.config.env_keys",
        "tools.validate_schemas": "common.config.schema_validation",
    }

    for tool_module, common_module in command_modules.items():
        assert (
            importlib.import_module(tool_module).main
            is importlib.import_module(common_module).main
        )


def test_AC8_13_58_shell_tools_delegate_to_common_shell_implementations():
    """AC8.13.58: Shell command entry points stay thin and delegate to common."""
    shell_commands = [
        "bootstrap.sh",
        "check_ghcr_image_tag.sh",
        "check_repo_submodule.sh",
        "cleanup_dev_resources.sh",
        "dokploy_deploy.sh",
        "health_check.sh",
        "infra.sh",
        "smoke_test.sh",
    ]

    for command in shell_commands:
        wrapper = (ROOT / "tools" / command).read_text(encoding="utf-8")
        implementation = (ROOT / "common" / "shell" / command).read_text(
            encoding="utf-8"
        )

        assert "common/shell/$(basename" in wrapper
        assert len(wrapper.splitlines()) <= 5
        assert implementation.startswith("#!")
        assert "common/shell/$(basename" not in implementation


def test_AC8_13_53_common_isolation_names_are_stable_and_bounded():
    """AC8.13.53: Test isolation naming is reusable outside command entry points."""
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
