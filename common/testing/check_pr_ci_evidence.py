"""Reconcile declared proof execution tiers against actual PR junit evidence.

A behavioral ``@ac_proof`` declaring ``ci_tier="pr_ci"`` promises its test runs
on every PR. Until issue #1557 that field was shape-validated but never checked
against real execution — a proof could claim pr_ci and silently never run.

This gate runs in the ``ac-behavioral-ratchet`` job after junit aggregation:
every behavioral pr_ci proof whose file classifies (via the execution matrix)
into a PR-evidence stage must appear as an executed testcase in the aggregated
junit. Absent → hard fail. Present but skipped-only → hard fail too (#1558):
a proof that only ever skips pre-merge is not executing its promise — either
make it run or declare post_merge_environment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

from common.testing.matrix import PR_EVIDENCE_STAGES, classify_stage


def _module_for(file: str) -> str:
    """Map a repo-relative test file to its pytest junit classname module."""
    path = file[:-3] if file.endswith(".py") else file
    # Backend suites run with cwd=apps/backend, so junit classnames are
    # rooted at tests.*
    prefix = "apps/backend/"
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return path.replace("/", ".")


def collect_executed(junit_paths: list[Path]) -> dict[tuple[str, str], bool]:
    """Return {(classname_module, base_test_name): ran_non_skipped}."""
    executed: dict[tuple[str, str], bool] = {}
    for path in junit_paths:
        if not path.exists():
            continue
        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError:
            continue
        for case in tree.iter("testcase"):
            classname = case.get("classname") or ""
            name = (case.get("name") or "").split("[", 1)[0]
            skipped = case.find("skipped") is not None
            key = (classname, name)
            executed[key] = executed.get(key, False) or not skipped
    return executed


def run_check(junit_paths: list[Path]) -> int:
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    proofs = build_matrix_from_graph(build_proofs_only()).get("proofs", [])
    scoped = [
        p
        for p in proofs
        if p.get("scope") == "behavioral"
        and p.get("ci_tier") == "pr_ci"
        and classify_stage(p.get("file", "")) in PR_EVIDENCE_STAGES
    ]

    executed = collect_executed(junit_paths)
    by_class: dict[str, dict[str, bool]] = {}
    for (classname, name), ran in executed.items():
        by_class.setdefault(classname, {})
        by_class[classname][name] = by_class[classname].get(name, False) or ran

    missing: list[str] = []
    skipped_only: list[str] = []
    for proof in scoped:
        module = _module_for(proof["file"])
        test = proof["test"]
        hit = None
        for classname, names in by_class.items():
            if classname == module or classname.startswith(module + "."):
                if test in names:
                    hit = names[test]
                    break
        label = f"{proof['id']}: {proof['file']}::{test}"
        if hit is None:
            missing.append(label)
        elif hit is False:
            skipped_only.append(label)

    if missing or skipped_only:
        print(
            f"ERROR: {len(missing)} behavioral pr_ci proof(s) never executed and "
            f"{len(skipped_only)} only ever skipped in PR junit evidence. Either "
            "the test does not run pre-merge (fix the marker/stage/skip condition "
            "so it does) or the proof's ci_tier is wrong (declare "
            "post_merge_environment).",
            file=sys.stderr,
        )
        for label in missing:
            print(f"  - missing: {label}", file=sys.stderr)
        for label in skipped_only:
            print(f"  - skipped-only: {label}", file=sys.stderr)
        return 1
    print(f"pr_ci evidence reconciliation: {len(scoped)} proofs executed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: check_pr_ci_evidence.py <junit-xml> [...]", file=sys.stderr)
        return 2
    return run_check([Path(a) for a in args])


if __name__ == "__main__":
    sys.exit(main())
