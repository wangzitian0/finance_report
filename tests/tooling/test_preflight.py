"""Tests for the diff-aware preflight dispatcher (common/ssot/preflight.py)."""

from __future__ import annotations

from pathlib import Path

from common.ssot import preflight

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

    def test_ssot_edit_selects_ownership_and_doc_consistency(self):
        names = [c.name for c in preflight.select_checks(["docs/ssot/reporting.md"])]
        assert "ssot-ownership" in names
        assert "doc-consistency" in names  # docs/* also matches

    def test_service_edit_selects_format_and_transaction_boundary(self):
        names = [
            c.name
            for c in preflight.select_checks(["apps/backend/src/services/foo.py"])
        ]
        assert "backend-format" in names
        assert "transaction-boundary" in names

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
        rc = preflight.main(["--changed", ".env.example"], runner=lambda argv, cwd: 1)
        assert rc == 1

    def test_main_returns_zero_when_gates_pass(self):
        rc = preflight.main(["--changed", ".env.example"], runner=lambda argv, cwd: 0)
        assert rc == 0

    def test_main_no_relevant_gates_is_clean(self):
        rc = preflight.main(["--changed", "Makefile"], runner=lambda argv, cwd: 1)
        assert rc == 0

    def test_main_list_does_not_run_anything(self):
        ran = []
        rc = preflight.main(
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

        rc = preflight.main([], runner=lambda argv, cwd: 0, git=fake_git)
        assert rc == 0


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
