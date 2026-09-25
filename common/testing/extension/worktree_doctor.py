"""Multi-worker worktree lifecycle doctor (AC-testing.preflight.4).

Audits local git worktrees against active process locks (lsof), GitHub PR status
(gh pr view), and uncommitted working-tree dirt. Prevents index leakages into the
main working tree and safely identifies or prunes completed orphan worktrees.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

Runner = Callable[[list[str], str | None], tuple[int, str]]
PrResolver = Callable[[str], dict | None]


@dataclass
class WorktreeInfo:
    path: str
    head: str
    branch: str
    is_main: bool = False
    is_dirty: bool = False
    uncommitted_lines: list[str] = field(default_factory=list)
    open_files_count: int = 0
    locks_unknown: bool = False
    pr_info: dict | None = None
    is_orphan: bool = False
    safe_to_prune: bool = False


@dataclass
class DoctorReport:
    worktrees: list[WorktreeInfo]
    staged_leakage: list[str] = field(default_factory=list)

    @property
    def orphans(self) -> list[WorktreeInfo]:
        return [w for w in self.worktrees if w.is_orphan]

    @property
    def active(self) -> list[WorktreeInfo]:
        return [w for w in self.worktrees if not w.is_orphan]


def _default_runner(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        return res.returncode, res.stdout
    except FileNotFoundError:
        return 127, ""
    except Exception as e:
        return 1, str(e)


def _default_pr_resolver(branch: str) -> dict | None:
    clean_branch = branch.replace("refs/heads/", "")
    if clean_branch in ("main", "detached", "HEAD"):
        return None
    res = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            clean_branch,
            "--state",
            "all",
            "--json",
            "number,state,title,mergedAt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            prs = json.loads(res.stdout)
            if prs and isinstance(prs, list):
                return prs[0]
        except Exception:
            return None
    return None


def parse_worktree_porcelain(output: str) -> list[dict[str, str]]:
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line.startswith("detached"):
            current["branch"] = "detached"
        elif line.startswith("bare"):
            current["bare"] = "true"
    if current:
        worktrees.append(current)
    return worktrees


def audit_worktrees(
    *,
    runner: Runner = _default_runner,
    pr_resolver: PrResolver = _default_pr_resolver,
    path_exists: Callable[[str], bool] = os.path.exists,
    main_root: str | None = None,
) -> DoctorReport:
    rc, wt_out = runner(["git", "worktree", "list", "--porcelain"], main_root)
    raw_wts = parse_worktree_porcelain(wt_out)

    detected_main_root = main_root or (raw_wts[0]["path"] if raw_wts else ".")
    staged_leakage: list[str] = []

    # Check main worktree status specifically for staged leakage
    rc, status_main = runner(["git", "status", "--porcelain"], detected_main_root)
    for line in status_main.splitlines():
        # In git status --porcelain, the first column represents index (staged) state.
        # Characters 'M', 'A', 'D', 'R', 'C' indicate index modifications.
        if len(line) >= 2 and line[0] in ("M", "A", "D", "R", "C"):
            staged_leakage.append(line.strip())

    results: list[WorktreeInfo] = []

    for raw in raw_wts:
        path = raw.get("path", "")
        head = raw.get("head", "")
        branch_ref = raw.get("branch", "detached")
        branch_name = branch_ref.replace("refs/heads/", "")
        is_main = (path == detected_main_root) or (branch_name == "main")

        rc, status_out = runner(["git", "status", "--porcelain"], path)
        status_lines = [
            line_str.strip() for line_str in status_out.splitlines() if line_str.strip()
        ]
        is_dirty = len(status_lines) > 0

        # Check file locks via lsof if path exists
        open_files = 0
        locks_unknown = False
        if path_exists(path):
            rc_lsof, lsof_out = runner(["lsof", "+D", path], None)
            if rc_lsof in (0, 1):
                open_lines = [
                    line_str
                    for line_str in lsof_out.splitlines()
                    if line_str.strip() and not line_str.startswith("COMMAND")
                ]
                open_files = len(open_lines)
            else:
                # lsof failed (missing binary or error) -> locks are unknown
                locks_unknown = True

        pr_info = pr_resolver(branch_name) if not is_main else None

        # Check if head commit is an ancestor of main
        rc_anc, _ = runner(
            ["git", "merge-base", "--is-ancestor", head, "main"], detected_main_root
        )
        is_merged_to_main = rc_anc == 0

        # Orphan criteria:
        # Non-main, (PR is MERGED or head is ancestor of main), not dirty, and locks known to be 0
        is_merged_pr = bool(pr_info and pr_info.get("state") == "MERGED")
        is_merged = is_merged_pr or is_merged_to_main
        is_orphan = (
            (not is_main)
            and is_merged
            and (not is_dirty)
            and (not locks_unknown)
            and (open_files == 0)
        )
        safe_to_prune = is_orphan

        info = WorktreeInfo(
            path=path,
            head=head,
            branch=branch_name,
            is_main=is_main,
            is_dirty=is_dirty,
            uncommitted_lines=status_lines,
            open_files_count=open_files,
            locks_unknown=locks_unknown,
            pr_info=pr_info,
            is_orphan=is_orphan,
            safe_to_prune=safe_to_prune,
        )
        results.append(info)

    return DoctorReport(worktrees=results, staged_leakage=staged_leakage)


def prune_worktrees(
    report: DoctorReport,
    *,
    runner: Runner = _default_runner,
    dry_run: bool = False,
) -> list[str]:
    pruned: list[str] = []
    for wt in report.worktrees:
        if wt.safe_to_prune:
            if not dry_run:
                rc, out = runner(["git", "worktree", "remove", wt.path], None)
                if rc == 0:
                    pruned.append(wt.path)
            else:
                pruned.append(wt.path)
    return pruned


def run_doctor(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _default_runner,
    pr_resolver: PrResolver = _default_pr_resolver,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> int:
    parser = argparse.ArgumentParser(
        description="Audit git worktrees for orphan states, open file locks, and staged index leakages."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail non-zero if index leakage or unpruned orphans exist.",
    )
    parser.add_argument(
        "--prune", action="store_true", help="Safely remove verified orphan worktrees."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without executing.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print report in JSON format."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = audit_worktrees(
        runner=runner,
        pr_resolver=pr_resolver,
        path_exists=path_exists,
    )

    if args.json:
        data = {
            "staged_leakage": report.staged_leakage,
            "worktrees": [
                {
                    "path": w.path,
                    "branch": w.branch,
                    "head": w.head[:8],
                    "is_main": w.is_main,
                    "is_dirty": w.is_dirty,
                    "open_files_count": w.open_files_count,
                    "locks_unknown": w.locks_unknown,
                    "is_orphan": w.is_orphan,
                    "safe_to_prune": w.safe_to_prune,
                    "pr_number": w.pr_info.get("number") if w.pr_info else None,
                    "pr_state": w.pr_info.get("state") if w.pr_info else None,
                }
                for w in report.worktrees
            ],
        }
        print(json.dumps(data, indent=2))
        return 0

    print("=== Worktree Doctor Audit ===")
    if report.staged_leakage:
        print(
            f"⚠️  STAGED INDEX LEAKAGE DETECTED IN MAIN ({len(report.staged_leakage)} files):"
        )
        for line in report.staged_leakage:
            print(f"    {line}")
    else:
        print("✓ Main worktree index clean (no staged leakages).")

    print(f"\nWorktrees ({len(report.worktrees)} total):")
    for w in report.worktrees:
        role = "MAIN" if w.is_main else ("ORPHAN" if w.is_orphan else "ACTIVE")
        pr_str = (
            f"PR #{w.pr_info['number']} ({w.pr_info['state']})"
            if w.pr_info
            else "No PR"
        )
        locks_disp = (
            "unknown (lsof error)" if w.locks_unknown else str(w.open_files_count)
        )
        print(f"  [{role}] {w.path}")
        print(
            f"         Branch: {w.branch} ({w.head[:8]}) | {pr_str} | Locks: {locks_disp} | Dirty: {w.is_dirty}"
        )

    if args.prune or args.dry_run:
        pruned = prune_worktrees(report, runner=runner, dry_run=args.dry_run)
        action = "Would prune" if args.dry_run else "Pruned"
        print(f"\n{action} {len(pruned)} orphan worktree(s):")
        for p in pruned:
            print(f"  - {p}")

    if args.check:
        if report.staged_leakage or (report.orphans and not args.prune):
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_doctor(argv)


if __name__ == "__main__":
    raise SystemExit(main())
