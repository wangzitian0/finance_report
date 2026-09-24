"""Tests for tools/worktree_doctor.py (AC-testing.preflight.4)."""

from __future__ import annotations

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
