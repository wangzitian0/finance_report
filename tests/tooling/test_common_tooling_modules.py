"""Tests for the common shared tooling foundation."""

from __future__ import annotations

import importlib
import importlib.util
import runpy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common.coverage import policy as coverage_policy  # noqa: E402
from common.ssot import ac_registry_format, ac_traceability_refs  # noqa: E402
from common import test_isolation  # noqa: E402


def _module_is_available(module_name: str) -> bool:
    if module_name in sys.modules:
        return True
    return importlib.util.find_spec(module_name) is not None


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


def test_AC8_13_53_root_scripts_and_infra_project_are_removed():
    """AC8.13.53: Root command trees are removed after command migration."""
    assert not (ROOT / "scripts").exists()
    assert not (ROOT / "infra").exists()

    workspace = yaml.safe_load((ROOT / ".moon" / "workspace.yml").read_text())
    assert workspace["projects"] == ["apps/*", "."]

    root_project = yaml.safe_load((ROOT / "moon.yml").read_text())
    assert "infra/**/*" not in root_project["fileGroups"]["workspace"]


def test_AC8_13_53_common_coverage_component_is_a_governed_source_root():
    """AC8.13.53: Common code is measured without tool-owned implementations."""
    component = coverage_policy.get_component("common")

    assert component.component_root == ""
    assert component.source_subdir == "common"
    assert component.ci_lcov_path == "coverage/common.lcov"
    assert "common/test_isolation.py" in component.expected_sources(ROOT)
    assert "common/ssot/check_ac_traceability.py" in component.expected_sources(ROOT)
    assert "tools/_lib/dev/test_lifecycle.py" not in component.expected_sources(ROOT)
    assert not (ROOT / "common" / "dev").exists()
    assert not (ROOT / "common" / "fixtures").exists()
    assert not (ROOT / "common" / "pdf_fixtures").exists()


def test_AC8_13_56_tools_coverage_component_is_a_governed_source_root():
    """AC8.13.56: Tools entry points and private implementations are measured."""
    component = coverage_policy.get_component("tools")

    assert component.component_root == ""
    assert component.source_subdir == "tools"
    assert component.ci_lcov_path == "coverage/tools.lcov"
    assert "tools/calculate_unified_coverage.py" in component.expected_sources(ROOT)
    assert "tools/strip_lcov_branches.py" in component.expected_sources(ROOT)
    assert "tools/_lib/dev/test_lifecycle.py" in component.expected_sources(ROOT)

    # Coverage/CI library implementations now live under common (consolidated
    # from tools/_lib): they are measured by the common component.
    common = coverage_policy.get_component("common")
    assert "common/coverage/calculate_unified_coverage.py" in common.expected_sources(
        ROOT
    )
    assert "common/coverage/strip_lcov_branches.py" in common.expected_sources(ROOT)


def test_AC8_13_56_coverage_tools_delegate_to_common_implementations():
    """AC8.13.56: Coverage commands live under tools and delegate to tools._lib."""
    build_tool = importlib.import_module("tools.build_unified_lcov")
    calc_tool = importlib.import_module("tools.calculate_unified_coverage")
    analyzer_tool = importlib.import_module("tools.coverage_analyzer")
    merge_tool = importlib.import_module("tools.merge_lcov")
    strip_tool = importlib.import_module("tools.strip_lcov_branches")
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
        strip_tool.main
        is importlib.import_module("common.coverage.strip_lcov_branches").main
    )
    assert (
        policy_tool.main is importlib.import_module("common.coverage.check_policy").main
    )
    assert (
        metrics_tool.main is importlib.import_module("common.ci.metrics_contract").main
    )


@pytest.mark.parametrize(
    ("tool_module", "implementation_module"),
    [
        ("tools.analyze_pdf_fixture", "tools._lib.pdf_fixtures.analyzers.analyze_pdf"),
        (
            "tools.generate_pdf_fixtures",
            "tools._lib.pdf_fixtures.generate_pdf_fixtures",
        ),
        ("tools.generate_test_pdfs", "tools._lib.fixtures.generate_test_pdfs"),
        ("tools.seed_fx_rates", "tools._lib.market_data.seed_fx_rates"),
        ("tools.cleanup_orphaned_dbs", "tools._lib.dev.cleanup_orphaned_dbs"),
        ("tools.pr_preview_lifecycle", "tools._lib.dev.pr_preview_lifecycle"),
        ("tools.vps_host_hygiene", "tools._lib.dev.vps_host_hygiene"),
        ("tools.cli", "tools._lib.dev.cli"),
        ("tools.debug", "tools._lib.dev.debug"),
        ("tools.dev_backend", "tools._lib.dev.dev_backend"),
        ("tools.dev_frontend", "tools._lib.dev.dev_frontend"),
        ("tools.test_lifecycle", "tools._lib.dev.test_lifecycle"),
    ],
)
def test_AC8_13_53_tool_owned_commands_delegate_to_tools_lib(
    tool_module: str, implementation_module: str
):
    """AC8.13.53: Tool-owned commands delegate to tools._lib, not common."""
    assert (
        importlib.import_module(tool_module).main
        is importlib.import_module(implementation_module).main
    )


def test_AC8_13_57_ssot_tools_delegate_to_common_implementations():
    """AC8.13.57: SSOT commands live under tools and delegate to common."""
    command_modules = {
        "tools.analyze_test_ac_coverage": "common.ssot.analyze_test_ac_coverage",
        "tools.audit_ac_epic_mismatches": "common.ssot.audit_ac_epic_mismatches",
        "tools.build_ac_traceability": "common.ssot.build_ac_traceability",
        # check_ac_traceability / check_critical_proof_matrix are no longer
        # standalone tool commands: their validators are folded into the single
        # check_ac_index gate (they remain pure common-only libraries).
        "tools.check_e2e_epic_traceability": (
            "common.ssot.check_e2e_epic_traceability"
        ),
        "tools.check_manifest": "common.ssot.check_manifest",
        "tools.check_ssot_ownership": "common.ssot.check_ssot_ownership",
        "tools.generate_ac_registry": "common.ssot.generate_ac_registry",
        "tools.generate_db_schema_reference": (
            "common.ssot.generate_db_schema_reference"
        ),
        "tools.lint_doc_consistency": "common.ssot.lint_doc_consistency",
    }

    for tool_module, common_module in command_modules.items():
        assert (
            importlib.import_module(tool_module).main
            is importlib.import_module(common_module).main
        )


def test_AC8_13_58_ci_tools_delegate_to_common_implementations():
    """AC8.13.58: CI commands keep common contracts separate from tool reports."""
    command_modules = {
        "tools.check_migration_risk": "common.ci.migration_risk",
        "tools.check_toolchain_contract": "common.ci.check_toolchain_contract",
        "tools.ci_change_classifier": "common.ci.change_classifier",
        "tools.github_workflow_timing_summary": (
            "common.ci.github_workflow_timing_summary"
        ),
        "tools.production_infra_smoke": "common.ci.production_infra_smoke",
        "tools.resolve_release_coordinate": "common.ci.release_coordinate",
        "tools.verify_release_evidence": "common.ci.release_evidence",
        "tools.verify_release_images": "common.ci.release_images",
        "tools.wait_post_merge_train_turn": ("common.ci.wait_post_merge_train_turn"),
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
    """AC8.13.58: Shell command entry points stay thin and delegate to tools._lib."""
    shell_commands = [
        "bootstrap.sh",
        "check_ghcr_image_tag.sh",
        "check_repo_submodule.sh",
        "cleanup_dev_resources.sh",
        "health_check.sh",
        "infra.sh",
        "smoke_test.sh",
    ]

    for command in shell_commands:
        wrapper = (ROOT / "tools" / command).read_text(encoding="utf-8")
        implementation = (ROOT / "tools" / "_lib" / "shell" / command).read_text(
            encoding="utf-8"
        )

        assert "tools/_lib/shell/$(basename" in wrapper
        assert len(wrapper.splitlines()) <= 5
        assert implementation.startswith("#!")
        assert "tools/_lib/shell/$(basename" not in implementation


def test_AC8_13_58_infra_shell_tool_owns_legacy_docker_actions():
    """AC8.13.58: Legacy infra Moon docker actions are owned by tools/infra.sh."""
    implementation = (ROOT / "tools" / "_lib" / "shell" / "infra.sh").read_text(
        encoding="utf-8"
    )

    for command in ("docker-up", "docker-down", "docker-logs"):
        assert command in implementation
    assert "--profile infra up -d" in implementation
    assert 'down "$@"' in implementation
    assert 'logs -f "$@"' in implementation


def test_AC8_13_56_python_tool_wrappers_bootstrap_repo_root_when_run_directly():
    """AC8.13.56: Python tool wrappers are executable without preset PYTHONPATH."""
    optional_dependency_wrappers = {
        "analyze_pdf_fixture.py": "pdfplumber",
        "generate_db_schema_reference.py": "sqlalchemy",
        "generate_pdf_fixtures.py": "reportlab",
        "generate_test_pdfs.py": "reportlab",
        "seed_fx_rates.py": "sqlalchemy",
    }
    wrappers = sorted(
        path for path in (ROOT / "tools").glob("*.py") if path.name != "__init__.py"
    )

    assert wrappers
    for wrapper in wrappers:
        optional_dependency = optional_dependency_wrappers.get(wrapper.name)
        if optional_dependency and not _module_is_available(optional_dependency):
            continue

        original_sys_path = list(sys.path)
        try:
            sys.path[:] = [entry for entry in sys.path if entry != str(ROOT)]

            module_globals = runpy.run_path(
                wrapper.as_posix(),
                run_name=f"_tool_wrapper_{wrapper.stem}",
            )

            assert sys.path[0] == str(ROOT)
            assert module_globals["ROOT_DIR"] == ROOT
            assert callable(module_globals["main"])
        finally:
            sys.path[:] = original_sys_path


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


def test_AC8_13_53_common_isolation_handles_error_and_registry_edges(tmp_path):
    """AC8.13.53: Common isolation helpers cover invalid and persistent edges."""
    with pytest.raises(ValueError, match="max_length too short"):
        test_isolation.shorten_identifier("abcdefghi", 8)

    with pytest.raises(ValueError, match="Base bucket name too long"):
        test_isolation.get_s3_bucket("feature_" + "x" * 20, base_bucket="b" * 60)

    assert (
        test_isolation.get_namespace(branch_name="Feature/X", workspace_id="!!!")
        == "feature_x"
    )

    class Result:
        stdout = "Issue/Branch\n"

    assert test_isolation.get_namespace(
        run=lambda *args, **kwargs: Result(),
        cwd_getter=lambda: tmp_path,
    ).startswith("issue_branch_")

    assert test_isolation.get_namespace(
        run=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("git down")),
        cwd_getter=lambda: tmp_path,
    ).startswith("default_")

    cache_dir = tmp_path / "cache"
    active_file = cache_dir / "active.json"
    test_isolation.register_namespace("feature_x", active_file, cache_dir)
    assert test_isolation.load_active_namespaces(active_file, cache_dir) == [
        "feature_x"
    ]
    test_isolation.unregister_namespace("feature_x", active_file, cache_dir)
    assert test_isolation.load_active_namespaces(active_file, cache_dir) == []
