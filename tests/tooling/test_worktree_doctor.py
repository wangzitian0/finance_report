"""Tests for tools/worktree_doctor.py (AC-testing.preflight.4)."""

from __future__ import annotations

import pytest

from common.testing.extension import worktree_doctor


def test_AC_testing_preflight_4_worktree_doctor_audit_and_prune():
    """AC-testing.preflight.4: worktree doctor audits worktrees, flags index leakage, and safely prunes orphans."""
    porcelain_output = (
        "worktree /repo/main\n"
        "HEAD 11111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/wt_merged\n"
        "HEAD 22222222\n"
        "branch refs/heads/feature_merged\n"
        "\n"
        "worktree /repo/wt_active\n"
        "HEAD 33333333\n"
        "branch refs/heads/feature_active\n"
    )

    def fake_runner(cmd, cwd=None):
        cmd_str = " ".join(cmd)
        if "worktree list --porcelain" in cmd_str:
            return 0, porcelain_output
        if "status --porcelain" in cmd_str:
            if "/repo/main" in str(cwd):
                # Staged file leakage in main (M, MM, A, R, C) and unstaged ( M, ??)
                return 0, (
                    "M  apps/frontend/src/lib/api-types.ts\n"
                    "MM apps/backend/src/service.py\n"
                    "A  apps/frontend/src/new.ts\n"
                    " M docs/readme.md\n"
                    "?? untracked.txt\n"
                )
            return 0, ""
        if "lsof" in cmd_str:
            return 0, ""
        if "merge-base" in cmd_str:
            if "22222222" in cmd_str:
                return 0, ""
            return 1, ""
        if "worktree remove" in cmd_str:
            return 0, ""
        return 0, ""

    def fake_pr_resolver(branch: str):
        if branch == "feature_merged":
            return {"number": 101, "state": "MERGED"}
        if branch == "feature_active":
            return {"number": 102, "state": "OPEN"}
        return None

    report = worktree_doctor.audit_worktrees(
        runner=fake_runner,
        pr_resolver=fake_pr_resolver,
        path_exists=lambda p: True,
        main_root="/repo/main",
    )

    # 1. Main worktree detects all staged index leakages (M, MM, A) but ignores unstaged ( M, ??)
    expected_staged = [
        "M  apps/frontend/src/lib/api-types.ts",
        "MM apps/backend/src/service.py",
        "A  apps/frontend/src/new.ts",
    ]
    assert report.staged_leakage == expected_staged

    # 2. wt_merged is classified as safe to prune (merged PR, clean tree, no locks)
    merged_wt = next(w for w in report.worktrees if w.path == "/repo/wt_merged")
    assert merged_wt.is_orphan is True
    assert merged_wt.safe_to_prune is True
    assert merged_wt.locks_unknown is False

    # 3. wt_active is classified as ACTIVE (open PR)
    active_wt = next(w for w in report.worktrees if w.path == "/repo/wt_active")
    assert active_wt.is_orphan is False
    assert active_wt.safe_to_prune is False

    # 4. Prune execution only targets safe-to-prune worktrees
    removed = worktree_doctor.prune_worktrees(report, runner=fake_runner, dry_run=False)
    assert removed == ["/repo/wt_merged"]


def test_AC_testing_preflight_4_lsof_error_blocks_prune():
    """AC-testing.preflight.4: if lsof returns error or is missing, locks_unknown is True and worktree is not pruned."""
    porcelain_output = (
        "worktree /repo/main\n"
        "HEAD 11111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/wt_merged\n"
        "HEAD 22222222\n"
        "branch refs/heads/feature_merged\n"
    )

    def fake_runner_lsof_fail(cmd, cwd=None):
        cmd_str = " ".join(cmd)
        if "worktree list --porcelain" in cmd_str:
            return 0, porcelain_output
        if "status --porcelain" in cmd_str:
            return 0, ""
        if "lsof" in cmd_str:
            # lsof command failed with error code 127
            return 127, "lsof: command not found"
        if "merge-base" in cmd_str:
            return 0, ""
        return 0, ""

    report = worktree_doctor.audit_worktrees(
        runner=fake_runner_lsof_fail,
        pr_resolver=lambda b: {"number": 101, "state": "MERGED"},
        path_exists=lambda p: True,
        main_root="/repo/main",
    )

    merged_wt = next(w for w in report.worktrees if w.path == "/repo/wt_merged")
    assert merged_wt.locks_unknown is True
    assert merged_wt.is_orphan is False
    assert merged_wt.safe_to_prune is False


def test_AC_testing_preflight_4_doctor_report_properties_and_porcelain_parsing():
    """AC-testing.preflight.4: tests DoctorReport helper properties and diverse git worktree porcelain outputs."""
    raw = (
        "worktree /repo/bare\nbare\n\n"
        "worktree /repo/detached\nHEAD dddddddd\ndetached\n\n"
    )
    parsed = worktree_doctor.parse_worktree_porcelain(raw)
    assert len(parsed) == 2
    assert parsed[0].get("bare") == "true"
    assert parsed[1].get("branch") == "detached"

    report = worktree_doctor.DoctorReport(
        worktrees=[
            worktree_doctor.WorktreeInfo(
                path="/p1", head="h1", branch="b1", is_orphan=True
            ),
            worktree_doctor.WorktreeInfo(
                path="/p2", head="h2", branch="b2", is_orphan=False
            ),
        ]
    )
    assert len(report.orphans) == 1
    assert len(report.active) == 1


def test_AC_testing_preflight_4_cli_flags_and_formatting(capsys):
    """AC-testing.preflight.4: tests CLI execution with --json, --dry-run, --prune, and --check."""
    import tools.worktree_doctor as tools_shim

    porcelain_output = (
        "worktree /repo/main\n"
        "HEAD 11111111\n"
        "branch refs/heads/main\n\n"
        "worktree /repo/wt_merged\n"
        "HEAD 22222222\n"
        "branch refs/heads/feature_merged\n"
    )

    def fake_runner(cmd, cwd=None):
        cmd_str = " ".join(cmd)
        if "worktree list --porcelain" in cmd_str:
            return 0, porcelain_output
        if "status --porcelain" in cmd_str:
            return 0, ""
        if "lsof" in cmd_str:
            return 1, ""
        if "merge-base" in cmd_str:
            return 0, ""
        if "worktree remove" in cmd_str:
            return 0, ""
        return 0, ""

    def fake_pr(b):
        return {"number": 101, "state": "MERGED"}

    # 1. Test --json
    rc = worktree_doctor.run_doctor(
        ["--json"],
        runner=fake_runner,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 0
    out_json = capsys.readouterr().out
    assert out_json.find('"safe_to_prune": true') != -1

    # 2. Test plain output
    rc = worktree_doctor.run_doctor(
        [],
        runner=fake_runner,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 0
    out_text = capsys.readouterr().out
    assert out_text.find("=== Worktree Doctor Audit ===") != -1
    assert out_text.find("[ORPHAN]") != -1

    # 3. Test --dry-run and --prune
    rc = worktree_doctor.run_doctor(
        ["--dry-run"],
        runner=fake_runner,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 0
    out_dry = capsys.readouterr().out
    assert out_dry.find("Would prune 1 orphan worktree(s)") != -1

    rc = worktree_doctor.run_doctor(
        ["--prune"],
        runner=fake_runner,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 0
    out_prune = capsys.readouterr().out
    assert out_prune.find("Pruned 1 orphan worktree(s)") != -1

    # 4. Test --check fails when unpruned orphan exists
    rc = worktree_doctor.run_doctor(
        ["--check"],
        runner=fake_runner,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 1

    # 5. Test plain output with staged leakage
    def fake_runner_with_leak(cmd, cwd=None):
        cmd_str = " ".join(cmd)
        if "status --porcelain" in cmd_str and "/repo/main" in str(cwd):
            return 0, "M  apps/frontend/src/lib/api-types.ts\n"
        return fake_runner(cmd, cwd)

    rc = worktree_doctor.run_doctor(
        [],
        runner=fake_runner_with_leak,
        pr_resolver=fake_pr,
        path_exists=lambda p: True,
    )
    assert rc == 0
    out_leak = capsys.readouterr().out
    assert out_leak.find("STAGED INDEX LEAKAGE DETECTED IN MAIN") != -1

    # 6. Test standard main wrapper
    with pytest.raises(SystemExit) as exc:
        worktree_doctor.main(["--help"])
    assert exc.value.code == 0
    assert tools_shim.main is worktree_doctor.main
    assert tools_shim.run_doctor is worktree_doctor.run_doctor


def test_AC_testing_preflight_4_runner_and_pr_resolver_edge_cases(monkeypatch):
    """AC-testing.preflight.4: tests default runner error handling and pr resolver filter."""
    import runpy

    # Test tools/worktree_doctor.py __main__ entrypoint
    monkeypatch.setattr(worktree_doctor, "main", lambda argv=None: 0)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("tools/worktree_doctor.py", run_name="__main__")
    assert exc.value.code == 0

    # Test _default_runner catches FileNotFoundError
    rc, out = worktree_doctor._default_runner(["nonexistent-command-xyz-987"])
    assert rc == 127

    # Test _default_pr_resolver ignores main and detached branches without spawning gh
    assert worktree_doctor._default_pr_resolver("main") is None
    assert worktree_doctor._default_pr_resolver("refs/heads/main") is None
    assert worktree_doctor._default_pr_resolver("detached") is None
    assert worktree_doctor._default_pr_resolver("HEAD") is None


def test_AC_testing_preflight_5_worktree_doctor_recognizes_squash_merged_prs():
    """AC-testing.preflight.5: a clean worktree for a MERGED PR is recognized as safe to prune even when git merge-base --is-ancestor fails (squash merge isolation)."""
    porcelain_output = (
        "worktree /repo/main\n"
        "HEAD 11111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/wt_squash_merged\n"
        "HEAD 33333333\n"
        "branch refs/heads/feature_squash_merged\n"
    )

    def fake_runner_squash(cmd, cwd=None):
        cmd_str = " ".join(cmd)
        if "worktree list --porcelain" in cmd_str:
            return 0, porcelain_output
        if "status --porcelain" in cmd_str:
            return 0, ""
        if "lsof" in cmd_str:
            return 1, ""  # 0 open files
        if "merge-base" in cmd_str:
            # git merge-base --is-ancestor returns 1 because the commit was squashed into main
            return 1, ""
        if "worktree remove" in cmd_str:
            return 0, ""
        if "branch -D" in cmd_str:
            return 0, ""
        return 0, ""

    report = worktree_doctor.audit_worktrees(
        runner=fake_runner_squash,
        pr_resolver=lambda b: {"number": 105, "state": "MERGED"},
        path_exists=lambda p: True,
        main_root="/repo/main",
    )

    squash_wt = next(w for w in report.worktrees if w.path == "/repo/wt_squash_merged")
    assert squash_wt.is_orphan is True
    assert squash_wt.safe_to_prune is True

    removed = worktree_doctor.prune_worktrees(
        report, runner=fake_runner_squash, dry_run=False
    )
    assert removed == ["/repo/wt_squash_merged"]
