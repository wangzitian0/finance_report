"""Tests for the diff-aware preflight dispatcher (common/testing/preflight.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

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
            "tests/tooling/test_s4_gate_contracts.py",
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
        assert "authority-reconcile" in names

    def test_AC_testing_preflight_1_proof_test_selects_baseline_contract(self):
        names = [
            c.name
            for c in preflight.select_checks(
                ["tests/tooling/test_s4_gate_contracts.py"], tier="static"
            )
        ]
        assert "gate-contracts" in names

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
        assert names == ["frontend"]

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

        # ac-traceability has two commands; only the first should run.
        checks = [c for c in preflight.CHECKS if c.name == "ac-traceability"]
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

    def test_frontend_diff_has_no_static_gates(self):
        # The frontend gate is heavy-only, so a frontend-only diff selects
        # nothing under --tier=static (nothing static maps to that path).
        selected = preflight.select_checks(
            ["apps/frontend/src/app/layout.tsx"], tier="static"
        )
        assert selected == []

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
