"""Tests for the diff-aware preflight dispatcher (common/testing/preflight.py)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml
from common.testing import preflight

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestSelectChecks:
    def test_epic_edit_selects_ac_traceability(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["docs/project/EPIC-008.testing-strategy.md"]
            )
        ]
        assert "ac-traceability" in names

    def test_epic_edit_selects_package_migration_safety(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["docs/project/EPIC-008.testing-strategy.md"]
            )
        ]
        assert "package-migration-safety" in names

    def test_manifest_edit_selects_ownership(self):
        # docs/ssot/ is retired (#1823, Package-ization 4/4); the concept
        # registry lives at common/meta/data/MANIFEST.yaml now.
        names = [
            c.name for c in preflight.select_checks(["common/meta/data/MANIFEST.yaml"])
        ]
        assert "ssot-ownership" in names

    @pytest.mark.parametrize(
        "changed_path",
        [
            "common/testing/contract.py",
            "tests/tooling/test_s4_testing_gate_infrastructure.py",
            "apps/backend/tests/ledger/test_accounting_equation.py",
            "apps/frontend/src/app/__tests__/page.test.tsx",
            "apps/frontend/src/lib/api.spec.ts",
            "common/meta/base/authority_matrix.py",
            "common/meta/extension/authority_classifier.py",
            "common/meta/extension/check_authority_reconcile.py",
            "common/meta/extension/generate_ac_registry.py",
        ],
    )
    def test_AC_testing_preflight_1_authority_input_selects_reconcile(
        self, changed_path: str
    ):
        names = [c.name for c in preflight.select_checks([changed_path])]
        assert "package-migration-safety" in names

    def test_AC_testing_preflight_1_proof_test_selects_package_migration_safety(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["tests/tooling/test_s4_testing_gate_infrastructure.py"], tier="static"
            )
        ]
        assert "package-migration-safety" in names

    def test_workflow_edit_selects_workflow_contract(self):
        names = {c.name for c in preflight.select_checks([".github/workflows/ci.yml"])}
        assert {"workflow-contract"}.issubset(names)

    def test_governance_exceptions_edit_selects_governance_exceptions(self):
        names = {
            c.name
            for c in preflight.select_checks(
                ["common/meta/data/governance-exceptions.yaml"]
            )
        }
        assert {"governance-exceptions"}.issubset(names)

    def test_fixture_edit_selects_recording_gates(self):
        c_fixture = "common/testing/fixtures/llm_" + "cas" + "settes/example.json"
        names = {c.name for c in preflight.select_checks([c_fixture])}
        expected = {"llm-" + "cas" + "settes", "cas" + "sette-graded-eval"}
        assert expected.issubset(names)

    def test_AC_testing_preflight_1_backend_proof_test_selects_ac_index(self):
        """AC-testing.preflight.1: changed backend proofs re-run AC integrity locally."""
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/tests/audit/test_money_tolerance_backend.py"],
                tier="static",
            )
        ]
        assert "ac-proof-traceability" in names

    def test_docs_edit_selects_doc_consistency(self):
        names = [c.name for c in preflight.select_checks(["docs/project/README.md"])]
        assert "doc-consistency" in names  # docs/* matches

    def test_markdown_edit_selects_taxonomy_drift(self):
        names = [c.name for c in preflight.select_checks(["common/ledger/readme.md"])]
        assert "taxonomy-drift" in names

    def test_service_edit_selects_format_and_transaction_boundary(self):
        # apps/backend/src/services/ is retired (#1610/#1666); the watched
        # commit-boundary files live under extraction/extension/ now.
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/src/extraction/extension/statement_parsing.py"]
            )
        ]
        assert "backend-format" in names
        assert "transaction-boundary" in names

    def test_backend_source_edit_selects_app_boundary(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/src/reconciliation/extension/matching.py"]
            )
        ]
        assert "app-boundary" in names

    def test_backend_source_edit_selects_public_orm_export_gate(self):
        names = [
            c.name
            for c in preflight.select_checks(["apps/backend/src/ledger/__init__.py"])
        ]
        assert "public-orm-exports" in names

    def test_backend_source_edit_selects_base_purity(self):
        selected = preflight.select_checks(
            ["apps/backend/src/reconciliation/base/repository.py"]
        )

        base_purity = next(check for check in selected if check.name == "base-purity")
        assert base_purity.commands == ((preflight.PY, "tools/check_base_purity.py"),)

    def test_migration_edit_selects_migration_risk(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/migrations/versions/0099_x.py"]
            )
        ]
        assert "migration-risk" in names

    def test_env_edit_selects_env_keys(self):
        assert [c.name for c in preflight.select_checks([".env.example"])] == [
            "env-keys"
        ]

    def test_schema_edit_selects_schema_validate(self):
        names = [
            c.name
            for c in preflight.select_checks(["apps/backend/src/schemas/account.py"])
        ]
        assert "schema-validate" in names

    def test_AC_testing_preflight_1_validator_edit_does_not_scan_schema_debt(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/src/runtime/extension/schema_validation.py"]
            )
        ]
        assert "schema-validate" not in names

    def test_router_edit_selects_api_reference_and_router_contract(self):
        # A router change shifts the OpenAPI surface AND the router-contract
        # maturity scan; both generated docs are CI-gated, so preflight must
        # flag them locally (parity with CI's api-reference + Tooling gates).
        names = [
            c.name
            for c in preflight.select_checks(["apps/backend/src/routers/income.py"])
        ]
        assert "api-reference" in names
        assert "router-contract" in names

    def test_package_extension_api_edit_selects_api_reference(self):
        """Package extension API changes select api-reference check."""
        names = [
            c.name
            for c in preflight.select_checks(
                ["apps/backend/src/identity/extension/api/users.py"]
            )
        ]
        assert "api-reference" in names

    def test_schema_edit_selects_api_reference(self):
        # Schema changes also move the OpenAPI reference (but not the
        # router-contract scan, which only reads routers/).
        names = [
            c.name
            for c in preflight.select_checks(["apps/backend/src/schemas/income.py"])
        ]
        assert "api-reference" in names
        assert "router-contract" not in names

    def test_frontend_edit_selects_frontend_gate(self):
        names = [
            c.name
            for c in preflight.select_checks(["apps/frontend/src/app/layout.tsx"])
        ]
        assert names == ["frontend-static", "frontend"]

    def test_config_edit_selects_env_reference_and_backend_format(self):
        names = [
            c.name for c in preflight.select_checks(["apps/backend/src/config.py"])
        ]
        assert "env-reference" in names
        assert "backend-format" in names

    def test_tooling_edit_selects_tooling_gate(self):
        names = [
            c.name for c in preflight.select_checks(["tools/generate_env_reference.py"])
        ]
        assert "tooling" in names

    def test_unrelated_file_selects_nothing(self):
        assert preflight.select_checks(["Makefile"]) == []

    def test_no_changes_selects_nothing(self):
        assert preflight.select_checks([]) == []


def _route_defining_backend_files() -> list[str]:
    """Return repo-relative paths of backend files that build a FastAPI app or router.

    The scan parses each file, so a comment or a string that names `APIRouter`
    does not count. FastAPI copies the docstring of each route handler into the
    OpenAPI description. A change in such a file can move `openapi.json`.
    """
    src = REPO_ROOT / "apps" / "backend" / "src"
    found: list[str] = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in {"APIRouter", "FastAPI"}:
                found.append(path.relative_to(REPO_ROOT).as_posix())
                break
    return found


def test_AC_testing_preflight_2_openapi_spec_gate_selects_every_route_file():
    """AC-testing.preflight.2: a change in any file that defines routes selects openapi-spec.

    Issue #2372: the docstring of `/health` moved in
    `apps/backend/src/runtime/extension/api/health.py` (#2365). No gate was selected,
    and `apps/frontend/openapi.json` went stale on main.
    """
    route_files = _route_defining_backend_files()
    # Positive controls: the scan must find the known route files. An empty scan
    # would let the loop below pass without any assertion.
    assert len(route_files) >= 26, route_files
    assert "apps/backend/src/runtime/extension/api/health.py" in route_files
    assert "apps/backend/src/routers/income.py" in route_files
    assert "apps/backend/src/main.py" in route_files

    unselected = [
        path
        for path in route_files
        if "openapi-spec"
        not in {c.name for c in preflight.select_checks([path], tier="static")}
    ]
    assert unselected == [], (
        f"route files that do not select openapi-spec: {unselected}"
    )


def test_AC_testing_preflight_2_api_reference_and_openapi_spec_share_input_globs():
    """AC-testing.preflight.2: both gates read the same OpenAPI document, so they share inputs."""
    by_name = {c.name: c for c in preflight.CHECKS}
    assert by_name["openapi-spec"].globs == by_name["api-reference"].globs
    assert by_name["openapi-spec"].globs == preflight.OPENAPI_INPUT_GLOBS


def test_every_check_command_references_an_existing_script():
    """Guard against a typo'd tool path in the CHECKS registry."""
    for check in preflight.CHECKS:
        for command in check.commands:
            for part in command:
                if part.endswith(".py") and part.startswith("tools/"):
                    assert (REPO_ROOT / part).exists(), f"{check.name}: missing {part}"


def test_backend_gates_run_in_the_backend_directory():
    """Backend ruff/pytest must run from apps/backend (config + src import path)."""
    by_name = {c.name: c for c in preflight.CHECKS}
    assert by_name["backend-format"].cwd == "apps/backend"
    assert by_name["transaction-boundary"].cwd == "apps/backend"


def test_AC_testing_toolchain_3_backend_format_uses_invoking_python_environment():
    """Local backend gates must use the project environment, never shell/global Python."""
    backend_format = next(c for c in preflight.CHECKS if c.name == "backend-format")
    assert backend_format.commands == (
        (preflight.PY, "-m", "ruff", "check", "src", "tests"),
        (preflight.PY, "-m", "ruff", "format", "--check", "src", "tests"),
    )
    precommit = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "cd apps/backend && uv run python ../../tools/check_env_keys.py" in precommit
    assert (
        "cd apps/backend && uv run python ../../tools/validate_schemas.py" in precommit
    )


def test_run_checks_passes_each_check_cwd_to_the_runner():
    seen: list[str] = []

    def runner(argv, cwd):
        seen.append(cwd)
        return 0

    preflight.run_checks(
        [c for c in preflight.CHECKS if c.name == "backend-format"],
        runner=runner,
        python="python3",
    )
    assert seen and all(c.endswith("apps/backend") for c in seen)


def test_schema_validation_receives_only_its_matching_changed_paths():
    """A new schema edit must not fail on unrelated historical schema debt."""
    commands: list[list[str]] = []
    schema_check = [c for c in preflight.CHECKS if c.name == "schema-validate"]

    preflight.run_checks(
        schema_check,
        changed_files=(
            "apps/backend/src/schemas/review.py",
            "apps/backend/src/extraction/extension/service.py",
        ),
        runner=lambda argv, cwd: commands.append(list(argv)) or 0,
        python="python3",
    )

    assert commands == [
        [
            "python3",
            "tools/validate_schemas.py",
            "--paths",
            "apps/backend/src/schemas/review.py",
        ]
    ]


class TestRunAndMain:
    def test_run_checks_reports_per_check_pass_fail(self):
        checks = preflight.select_checks(["apps/backend/migrations/versions/0099_x.py"])
        results = preflight.run_checks(
            checks, runner=lambda argv, cwd: 0, python="python3"
        )
        assert all(r.ok for r in results)

        results = preflight.run_checks(
            checks, runner=lambda argv, cwd: 1, python="python3"
        )
        assert all(not r.ok for r in results)

    def test_run_checks_fails_fast_on_first_nonzero_command(self):
        calls: list[list[str]] = []

        def runner(argv, cwd):
            calls.append(list(argv))
            return 1  # first command fails

        # ssot-ownership has two commands; only the first should run.
        checks = [c for c in preflight.CHECKS if c.name == "ssot-ownership"]
        preflight.run_checks(checks, runner=runner, python="python3")
        assert len(calls) == 1

    def test_main_returns_nonzero_when_a_gate_fails(self):
        rc = preflight.run(["--changed", ".env.example"], runner=lambda argv, cwd: 1)
        assert rc == 1

    def test_main_returns_zero_when_gates_pass(self):
        rc = preflight.run(["--changed", ".env.example"], runner=lambda argv, cwd: 0)
        assert rc == 0

    def test_schema_validation_is_limited_to_changed_schema_paths(self):
        calls: list[list[str]] = []

        def runner(argv, _cwd):
            calls.append(list(argv))
            return 0

        changed_path = "apps/backend/src/schemas/reconciliation.py"
        rc = preflight.run(["--changed", changed_path], runner=runner)

        assert rc == 0
        schema_command = next(
            command for command in calls if "tools/validate_schemas.py" in command
        )
        assert schema_command[-2:] == ["--paths", changed_path]

    def test_main_no_relevant_gates_is_clean(self):
        rc = preflight.run(["--changed", "Makefile"], runner=lambda argv, cwd: 1)
        assert rc == 0

    def test_main_list_does_not_run_anything(self):
        ran = []
        rc = preflight.run(
            ["--list", "--changed", "docs/project/EPIC-008.x.md"],
            runner=lambda argv, cwd: ran.append(argv) or 0,
        )
        assert rc == 0
        assert ran == []

    def test_main_uses_injected_git_when_no_explicit_changes(self):
        def fake_git(args):
            if args[0] == "merge-base":
                return "abc123\n"
            if "--cached" in args:
                return ""
            return ".env.example\n"

        rc = preflight.run([], runner=lambda argv, cwd: 0, git=fake_git)
        assert rc == 0


# ── Tier-filtered selection (#1810 G-static-parity) ──
# The static tier is the seconds-level pre-push parity command; the heavy
# suites (measured in minutes) stay in the full tier. Tier filtering must
# COMPOSE with the existing glob-based diff selection, and the default must
# preserve the exact pre-tier behavior.


def test_AC_testing_preflight_1_static_tier_composes_with_glob_selection():
    """AC-testing.preflight.1: a common/*.py diff matches both static gates and
    the heavy tooling suite; --tier=static keeps the static gates for that diff
    and drops the heavy one, while the default (full) keeps today's selection."""
    changed = ["common/testing/preflight.py"]
    full_names = {c.name for c in preflight.select_checks(changed)}
    static_selected = preflight.select_checks(changed, tier="static")
    static_names = {c.name for c in static_selected}

    # Tier filtering composes with glob selection: same diff, heavy dropped.
    assert static_names == full_names - {"tooling"}
    # The static gates relevant to the diff still run — tier never widens
    # or empties the glob-based selection, it only strips the heavy checks.
    assert static_names
    assert all(c.tier == "static" for c in static_selected)


class TestTierSelection:
    """Behavioral tier-selection contracts (AC-testing.preflight.1, #1810)."""

    def test_every_check_has_a_valid_tier(self):
        assert all(c.tier in ("static", "heavy") for c in preflight.CHECKS)

    def test_heavy_tier_membership_is_the_two_expensive_suites(self):
        # The two minutes-scale checks (the tests/tooling pytest suite and the
        # frontend lint+coverage+build chain) are the only heavy-tier members.
        heavy = {c.name for c in preflight.CHECKS if c.tier == "heavy"}
        assert heavy == {"tooling", "frontend"}

    def test_full_tier_is_the_default_and_preserves_selection(self):
        changed = [
            "common/testing/preflight.py",
            "apps/frontend/src/app/layout.tsx",
            "common/reporting/reporting.md",
        ]
        assert preflight.select_checks(changed) == preflight.select_checks(
            changed, tier="full"
        )

    def test_AC_testing_preflight_2_frontend_static_gate_parity(self):
        """AC-testing.preflight.2: frontend changes run fast static checks in tier=static."""
        # 1. Changing a frontend component selects frontend-static in tier=static
        selected = preflight.select_checks(
            ["apps/frontend/src/app/layout.tsx"], tier="static"
        )
        selected_names = {c.name for c in selected}
        assert selected_names >= {"frontend-static"}

        # 2. Check commands in frontend-static
        check = next(c for c in preflight.CHECKS if c.name == "frontend-static")
        assert check.tier == "static"
        assert check.cwd == "apps/frontend"
        cmds = check.commands
        assert ("npm", "run", "lint") in cmds
        assert ("npm", "run", "typecheck") in cmds
        assert ("npm", "run", "check:api-types") in cmds

        # 3. openapi-spec gate also verifies frontend api-types sync
        openapi_check = next(c for c in preflight.CHECKS if c.name == "openapi-spec")
        has_api_types_check = any(
            "check:api-types" in " ".join(cmd) or "check_api_types" in " ".join(cmd)
            for cmd in openapi_check.commands
        )
        assert has_api_types_check

    def test_AC_testing_preflight_3_list_all_inventory_discovery(self, capsys):
        """AC-testing.preflight.3: running --list on empty diff or with --all prints gate inventory."""
        # Empty diff with --list prints registered inventory rather than exiting empty
        rc = preflight.run(["--list", "--changed"], runner=lambda argv, cwd: 0)
        assert rc == 0
        out = capsys.readouterr().out
        assert out.find("Registered preflight gate inventory") != -1
        assert out.find("ac-traceability") != -1

        # With --tier=static and empty diff, lists all static gates
        rc = preflight.run(
            ["--list", "--tier=static", "--changed"], runner=lambda argv, cwd: 0
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert out.find("frontend-static") != -1
        assert out.find("  [heavy] frontend:") == -1  # heavy frontend excluded

        # --all runs all selected checks regardless of diff
        rc = preflight.run(
            ["--all", "--tier=static", "--list"],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert out.find("Registered preflight gate inventory") != -1
        assert out.find("frontend-static") != -1

    def test_heavy_tier_selects_only_matching_heavy_checks(self):
        selected = preflight.select_checks(
            ["common/testing/preflight.py", "apps/frontend/src/app/layout.tsx"],
            tier="heavy",
        )
        assert [c.name for c in selected] == ["tooling", "frontend"]

    def test_unknown_tier_is_rejected(self):
        with pytest.raises(ValueError):
            preflight.select_checks(["common/x.py"], tier="bogus")


class TestTierCli:
    """CLI surface of the tier switch (AC-testing.preflight.1, #1810)."""

    @staticmethod
    def _run_and_collect(args: list[str]) -> list[list[str]]:
        ran: list[list[str]] = []
        rc = preflight.run(
            [*args, "--changed", "common/testing/preflight.py"],
            runner=lambda argv, cwd: ran.append(list(argv)) or 0,
        )
        assert rc == 0
        return ran

    def test_main_default_equals_tier_full(self):
        assert self._run_and_collect([]) == self._run_and_collect(["--tier=full"])

    def test_main_tier_static_runs_strictly_fewer_commands_than_full(self):
        full_ran = self._run_and_collect([])
        static_ran = self._run_and_collect(["--tier=static"])
        # Static ran something (the diff-matched static gates) but skipped the
        # heavy suite's command(s) that full runs for the same diff.
        assert 0 < len(static_ran) < len(full_ran)
        assert all(argv in full_ran for argv in static_ran)

    def test_main_list_shows_each_selected_checks_tier(self, capsys):
        rc = preflight.run(
            ["--list", "--changed", "common/testing/preflight.py"],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        for check in preflight.select_checks(["common/testing/preflight.py"]):
            assert any(check.name in line and check.tier in line for line in lines)

    def test_main_list_respects_tier(self, capsys):
        rc = preflight.run(
            ["--list", "--tier=static", "--changed", "common/testing/preflight.py"],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        heavy = {c.name for c in preflight.CHECKS if c.tier == "heavy"}
        assert heavy and all(name not in out for name in heavy)


def test_changed_files_unions_committed_staged_unstaged_and_untracked():
    def fake_git(args):
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "ls-files":
            return "new_untracked.py\n"  # brand-new file git diff would miss
        if args[-1] == "--cached":
            return "c.py\n"
        if args[-1] == "base-sha":
            return "a.py\nb.py\n"
        return "b.py\n"  # unstaged

    assert preflight.changed_files(git=fake_git) == [
        "a.py",
        "b.py",
        "c.py",
        "new_untracked.py",
    ]


class TestCiLogging:
    """GitHub Actions ::group:: folding and ::error:: annotation formatting."""

    def test_run_checks_with_ci_formatting_on_success(self, capsys):
        test_check = preflight.Check(
            name="test-pass",
            tier="static",
            globs=("*.py",),
            commands=(("echo", "ok"),),
            why="test passing check",
        )
        results = preflight.run_checks(
            [test_check],
            changed_files=["foo.py"],
            runner=lambda argv, cwd: 0,
            ci=True,
        )
        assert len(results) == 1
        assert results[0].ok is True
        out = capsys.readouterr().out
        expected_group = "::group::Gate [static] test-pass"
        expected_endgroup = "::endgroup::"
        error_tag = "::error::"
        assert expected_group in out
        assert expected_endgroup in out
        assert error_tag not in out

    def test_run_checks_with_ci_formatting_on_failure(self, capsys):
        test_check = preflight.Check(
            name="test-fail",
            tier="static",
            globs=("*.py",),
            commands=(("echo", "fail"),),
            why="test failing check",
        )
        results = preflight.run_checks(
            [test_check],
            changed_files=["foo.py"],
            runner=lambda argv, cwd: 1,
            ci=True,
        )
        assert len(results) == 1
        assert results[0].ok is False
        out = capsys.readouterr().out
        expected_group = "::group::Gate [static] test-fail"
        expected_endgroup = "::endgroup::"
        expected_error = "::error::Gate test-fail failed: test failing check"
        assert expected_group in out
        assert expected_endgroup in out
        assert expected_error in out

    def test_run_cli_with_ci_flag(self, capsys):
        rc = preflight.run(
            ["--tier=static", "--ci", "--changed", "common/testing/preflight.py"],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        group_tag = "::group::"
        endgroup_tag = "::endgroup::"
        assert group_tag in out
        assert endgroup_tag in out

    def test_run_cli_with_quiet_flag_success(self, capsys):
        rc = preflight.run(
            ["--tier=static", "--quiet", "--changed", ".env.example"],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        summary_prefix = "preflight: all"
        summary_suffix = "gates passed"
        verbose_running = "preflight: running"
        gate_ok = "  [ok]"
        assert summary_prefix in out
        assert summary_suffix in out
        assert verbose_running not in out
        assert gate_ok not in out

    def test_run_cli_with_quiet_flag_failure(self, capsys):
        rc = preflight.run(
            ["--tier=static", "-q", "--changed", ".env.example"],
            runner=lambda argv, cwd: 1,
        )
        assert rc == 1
        out = capsys.readouterr().out
        fail_indicator = "FAIL"
        failed_summary = "failed"
        assert fail_indicator in out
        assert failed_summary in out

    def test_default_quiet_runner_suppresses_output_on_success(
        self, capsys, monkeypatch
    ):
        import subprocess

        fake_proc = subprocess.CompletedProcess(
            args=["echo", "clean"],
            returncode=0,
            stdout="some clean output\n",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: fake_proc)
        rc = preflight._default_quiet_runner(["echo", "clean"], cwd="/tmp")
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_default_quiet_runner_dumps_output_on_failure(self, capsys, monkeypatch):
        import subprocess

        fake_proc = subprocess.CompletedProcess(
            args=["flake8"],
            returncode=1,
            stdout="syntax error on line 42\n",
            stderr="warning message\n",
        )
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: fake_proc)
        rc = preflight._default_quiet_runner(["flake8"], cwd="/tmp")
        assert rc == 1
        captured = capsys.readouterr()
        error_msg = "syntax error on line 42"
        warning_msg = "warning message"
        assert error_msg in captured.out
        assert warning_msg in captured.err

    def test_default_runner_handles_timeout(self, capsys, monkeypatch):
        import subprocess

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=180)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc = preflight._default_runner(["sleep", "999"], cwd="/tmp")
        assert rc == 124
        captured = capsys.readouterr()
        assert "timed out after 180s" in captured.out

    def test_default_quiet_runner_handles_timeout(self, capsys, monkeypatch):
        import subprocess

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=180)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc = preflight._default_quiet_runner(["sleep", "999"], cwd="/tmp")
        assert rc == 124
        captured = capsys.readouterr()
        assert "timed out after 180s" in captured.out

    def test_child_env_isolates_test_namespace_and_preserves_explicit_override(
        self, monkeypatch
    ):
        monkeypatch.delenv("TEST_NAMESPACE", raising=False)
        env = preflight._child_env()
        assert env["TEST_NAMESPACE"].startswith("preflight_")

        monkeypatch.setenv("TEST_NAMESPACE", "explicit_ns")
        env_override = preflight._child_env()
        assert env_override["TEST_NAMESPACE"] == "explicit_ns"


# ── Named-gate selection and CI wiring (#2378) ──
# CI runs the `openapi-spec` gate through `--only`, so CI and the local pre-push
# run share one command list. Issue #2372: a stale openapi.json reached main
# because no CI step ran this gate.

CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class TestOnlyNamedGate:
    """`--only NAME` runs the named gate whatever the diff (AC-testing.preflight.2)."""

    @staticmethod
    def _collect(args: list[str], rc_of_runner: int = 0) -> tuple[int, list[list[str]]]:
        ran: list[list[str]] = []
        rc = preflight.run(
            args, runner=lambda argv, cwd: ran.append(list(argv)) or rc_of_runner
        )
        return rc, ran

    def test_AC_testing_preflight_2_only_runs_the_named_gate_commands(self, capsys):
        rc, ran = self._collect(["--only", "openapi-spec"])
        assert rc == 0
        assert "preflight: running 1 named gate(s)..." in capsys.readouterr().out
        gate = next(c for c in preflight.CHECKS if c.name == "openapi-spec")
        expected = [
            preflight._resolve(command, python=preflight.sys.executable)
            for command in gate.commands
        ]
        # Positive control: the gate has two commands, spec check and api-types check.
        assert len(expected) == 2
        assert ran == expected

    def test_AC_testing_preflight_2_only_ignores_the_diff(self, monkeypatch):
        def fail_if_called(args):
            raise AssertionError(f"--only must not read the git diff: {args}")

        rc = preflight.run(
            ["--only", "openapi-spec"],
            runner=lambda argv, cwd: 0,
            git=fail_if_called,
        )
        assert rc == 0

    def test_AC_testing_preflight_2_only_returns_one_when_the_gate_fails(self, capsys):
        rc, ran = self._collect(["--only", "openapi-spec"], rc_of_runner=1)
        assert rc == 1
        assert len(ran) == 1  # fail fast: the api-types command did not run
        assert "[FAIL] openapi-spec" in capsys.readouterr().out

    def test_AC_testing_preflight_2_only_rejects_an_unknown_gate(self, capsys):
        # Positive control: the same call with a real name selects and runs a gate.
        rc, ran = self._collect(["--only", "openapi-spec"])
        assert rc == 0 and ran

        ran.clear()
        with pytest.raises(SystemExit) as exc:
            preflight.run(
                ["--only", "openapi-specc"],
                runner=lambda argv, cwd: ran.append(list(argv)) or 0,
            )
        assert exc.value.code == 2
        assert ran == []
        assert "unknown gate name(s): openapi-specc" in capsys.readouterr().err

    @pytest.mark.parametrize("extra", [["--all"], ["--changed", "Makefile"]])
    def test_AC_testing_preflight_2_only_rejects_diff_selection_flags(
        self, extra, capsys
    ):
        ran: list[list[str]] = []
        with pytest.raises(SystemExit) as exc:
            preflight.run(
                ["--only", "openapi-spec", *extra],
                runner=lambda argv, cwd: ran.append(list(argv)) or 0,
            )
        assert exc.value.code == 2
        assert ran == []
        assert (
            "--only cannot combine with --all or --changed" in capsys.readouterr().err
        )

    def test_AC_testing_preflight_2_only_runs_a_gate_outside_the_requested_tier(self):
        heavy = next(c for c in preflight.CHECKS if c.tier == "heavy")
        rc, ran = self._collect(["--only", heavy.name, "--tier=static"])
        assert rc == 0
        # A tier filter must not turn a named gate into a silent no-op.
        assert len(ran) == len(heavy.commands) > 0

    def test_AC_testing_preflight_2_select_named_checks_keeps_registry_order(self):
        names = [c.name for c in preflight.CHECKS]
        picked = preflight.select_named_checks(["openapi-spec", "api-reference"])
        assert [c.name for c in picked] == [
            n for n in names if n in {"openapi-spec", "api-reference"}
        ]
        with pytest.raises(ValueError, match="unknown gate name"):
            preflight.select_named_checks(["no-such-gate"])


def _lint_steps() -> list[dict]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["lint"]["steps"]


def test_AC_testing_preflight_2_ci_lint_job_runs_the_openapi_spec_gate():
    """AC-testing.preflight.2: the CI Lint job runs the `openapi-spec` gate (#2378).

    The step must run after the backend venv and the frontend dependencies exist.
    """
    steps = _lint_steps()
    names = [step.get("name", "") for step in steps]
    matching = [
        i
        for i, step in enumerate(steps)
        if "--only openapi-spec" in step.get("run", "")
    ]
    assert len(matching) == 1, f"expected one openapi-spec step in Lint, got {matching}"
    step = steps[matching[0]]
    run_lines = [
        line.strip()
        for line in step["run"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert run_lines == [
        "cd apps/backend",
        "uv run python ../../tools/preflight.py --only openapi-spec --ci",
    ]
    assert names.index("Install dependencies") < matching[0]
    assert names.index("Install frontend dependencies") < matching[0]
    assert "if" not in step, "the openapi-spec step must run on every Lint run"
    assert not step.get("continue-on-error"), "the step must fail the Lint job"


def test_AC_testing_preflight_2_every_ci_only_gate_name_exists():
    """AC-testing.preflight.2: each `preflight.py --only NAME` in a workflow names a real gate."""
    registry = {c.name for c in preflight.CHECKS}
    referenced: set[str] = set()
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        referenced.update(
            re.findall(r"preflight\.py[^\n]*?--only[= ]([A-Za-z0-9_-]+)", text)
        )
    # Positive control: the scan must find the openapi-spec reference.
    assert "openapi-spec" in referenced
    assert referenced <= registry, sorted(referenced - registry)


class TestDiffScopedPytestTargets:
    """Fast local diff-scoped pytest execution and single-file xdist suppression (#2517)."""

    def test_transaction_boundary_check_disables_xdist_workers(self):
        gate = next(c for c in preflight.CHECKS if c.name == "transaction-boundary")
        cmd = gate.commands[0]
        assert "-n" in cmd
        n_idx = cmd.index("-n")
        assert cmd[n_idx + 1] == "0"

    def test_resolve_changed_pytest_targets_maps_source_and_test_files(self, tmp_path):
        (tmp_path / "tests" / "tooling").mkdir(parents=True)
        (tmp_path / "tests" / "tooling" / "test_preflight.py").write_text(
            "def test_ok(): pass\n", encoding="utf-8"
        )
        (tmp_path / "tests" / "tooling" / "test_direct_root.py").write_text(
            "def test_ok(): pass\n", encoding="utf-8"
        )
        (tmp_path / "apps" / "backend" / "tests" / "unit").mkdir(parents=True)
        (
            tmp_path / "apps" / "backend" / "tests" / "unit" / "test_journal_service.py"
        ).write_text("def test_ok(): pass\n", encoding="utf-8")
        (
            tmp_path / "apps" / "backend" / "tests" / "unit" / "test_direct_backend.py"
        ).write_text("def test_ok(): pass\n", encoding="utf-8")
        (tmp_path / "apps" / "backend" / "tests" / "audit" / "money").mkdir(
            parents=True
        )
        (
            tmp_path
            / "apps"
            / "backend"
            / "tests"
            / "audit"
            / "money"
            / "test_money_value_type.py"
        ).write_text("def test_ok(): pass\n", encoding="utf-8")
        root_targets, backend_targets = preflight.resolve_changed_pytest_targets(
            [
                "common/testing/__init__.py",
                "common/testing/preflight.py",
                "common/audit/money/money.py",
                "tests/tooling/test_direct_root.py",
                "apps/backend/src/services/journal_service.py",
                "apps/backend/tests/unit/test_direct_backend.py",
                "docs/README.md",
            ],
            repo_root=tmp_path,
        )
        assert root_targets == [
            "tests/tooling/test_direct_root.py",
            "tests/tooling/test_preflight.py",
        ]
        assert backend_targets == [
            "tests/audit/money/test_money_value_type.py",
            "tests/unit/test_direct_backend.py",
            "tests/unit/test_journal_service.py",
        ]

    def test_run_pytest_changed_executes_single_process_fail_fast_pytest(self, capsys):
        recorded: list[tuple[list[str], str]] = []

        def fake_runner(argv, cwd):
            recorded.append((list(argv), cwd))
            return 0

        rc = preflight.run(
            [
                "--tier=static",
                "--pytest-changed",
                "--changed",
                "common/testing/preflight.py",
                "apps/backend/tests/infra/test_transaction_boundaries.py",
            ],
            runner=fake_runner,
        )
        assert rc == 0
        out = capsys.readouterr().out
        root_calls = [
            (argv, cwd)
            for argv, cwd in recorded
            if "pytest" in argv and "tests/tooling/test_preflight.py" in argv
        ]
        backend_calls = [
            (argv, cwd)
            for argv, cwd in recorded
            if "pytest" in argv
            and "tests/infra/test_transaction_boundaries.py" in argv
            and "--no-cov" in argv
        ]
        assert len(root_calls) == 1
        assert len(backend_calls) == 1
        for argv, _ in (root_calls[0], backend_calls[0]):
            assert "-x" in argv
            assert "--no-cov" in argv
            assert "-n" in argv and argv[argv.index("-n") + 1] == "0"
        assert "[ok] pytest-changed:root" in out
        assert "[ok] pytest-changed:backend" in out

    def test_run_pytest_changed_reports_failure_in_quiet_mode(self, capsys):
        def failing_pytest_runner(argv, cwd):
            if "pytest" in argv and "--no-cov" in argv:
                return 1
            return 0

        rc = preflight.run(
            [
                "--tier=static",
                "--quiet",
                "--pytest-changed",
                "--changed",
                "common/testing/preflight.py",
            ],
            runner=failing_pytest_runner,
        )
        assert rc == 1
        out = capsys.readouterr().out
        assert "[FAIL] pytest-changed:root" in out
        assert "preflight: 1 gate(s) failed: pytest-changed:root" in out

    def test_run_pytest_changed_reports_no_relevant_gates_when_zero_targets_and_gates(
        self, capsys
    ):
        rc = preflight.run(
            [
                "--tier=static",
                "--pytest-changed",
                "--changed",
                "nonexistent_dir/unmatched.txt",
            ],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "preflight: no relevant gates for the current diff." in out

    def test_run_pytest_changed_quiet_mode_counts_executed_pytest_suite(self, capsys):
        rc = preflight.run(
            [
                "--tier=static",
                "--quiet",
                "--pytest-changed",
                "--changed",
                "tests/tooling/test_preflight.py",
            ],
            runner=lambda argv, cwd: 0,
        )
        assert rc == 0
        out = capsys.readouterr().out
        selected_count = len(
            preflight.select_checks(["tests/tooling/test_preflight.py"], tier="static")
        )
        assert f"preflight: all {selected_count + 1} gates passed." in out
