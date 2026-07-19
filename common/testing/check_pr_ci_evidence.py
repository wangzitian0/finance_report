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

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from common.audit.base import TraceRecord, TraceRecordValidationError
from common.audit.extension import TraceJUnitAdapter, TraceRecordCodec
from common.meta.base.gate_cli import run_gate
from common.testing.executed_proof import (
    executed_proof_assertion_version,
    executed_proof_matches,
    github_execution_id,
)
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


def collect_executed_proofs(
    junit_paths: list[Path],
) -> tuple[dict[tuple[str, str], tuple[TraceRecord, ...]], set[tuple[str, str]]]:
    """Collect canonical trace properties and retain malformed testcase keys."""
    records: dict[tuple[str, str], list[TraceRecord]] = {}
    malformed: set[tuple[str, str]] = set()
    for path in junit_paths:
        if not path.exists():
            continue
        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError:
            continue
        for case in tree.iter("testcase"):
            key = (
                case.get("classname") or "",
                (case.get("name") or "").split("[", 1)[0],
            )
            for prop in case.findall("./properties/property"):
                if prop.get("name") != TraceJUnitAdapter.PROPERTY_KEY:
                    continue
                raw = prop.get("value")
                if raw is None:
                    malformed.add(key)
                    continue
                try:
                    records.setdefault(key, []).append(TraceRecordCodec.decode(raw))
                except TraceRecordValidationError:
                    malformed.add(key)
    return ({key: tuple(value) for key, value in records.items()}, malformed)


def _matching_testcase_keys(
    proof: dict[str, object],
    keys: set[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    module = _module_for(str(proof["file"]))
    test = str(proof["test"])
    return tuple(
        key
        for key in keys
        if (key[0] == module or key[0].startswith(module + ".")) and key[1] == test
    )


def _has_exact_executed_proof(
    proof: dict[str, object],
    *,
    records: dict[tuple[str, str], tuple[TraceRecord, ...]],
    malformed: set[tuple[str, str]],
    repository_id: str,
    commit_sha: str,
    execution_id: str,
) -> bool:
    keys = _matching_testcase_keys(proof, set(records) | malformed)
    if not keys or any(key in malformed for key in keys):
        return False
    assertion_version = executed_proof_assertion_version(
        proof_id=str(proof["id"]),
        scenario_id=str(proof["scenario_id"]),
        oracle_kind=str(proof["oracle_kind"]),
        ac_ids=[str(item) for item in proof.get("ac_ids", [])],
        stage=str(proof["stage"]),
        task_category=str(proof["task_category"]),
    )
    return any(
        executed_proof_matches(
            record,
            proof_id=str(proof["id"]),
            scenario_id=str(proof["scenario_id"]),
            repository_id=repository_id,
            commit_sha=commit_sha,
            execution_id=execution_id,
            assertion_version=assertion_version,
        )
        for key in keys
        for record in records.get(key, ())
    )


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

    invalid_executed_proof: list[str] = []
    if os.environ.get("GITHUB_ACTIONS") == "true":
        repository_id = os.environ.get("GITHUB_REPOSITORY", "")
        commit_sha = os.environ.get("GITHUB_SHA", "")
        execution_id = github_execution_id(os.environ)
        records, malformed = collect_executed_proofs(junit_paths)
        not_executed = set(missing) | set(skipped_only)
        for proof in scoped:
            if not proof.get("scenario_id"):
                continue
            label = f"{proof['id']}: {proof['file']}::{proof['test']}"
            if label in not_executed:
                continue
            if not _has_exact_executed_proof(
                proof,
                records=records,
                malformed=malformed,
                repository_id=repository_id,
                commit_sha=commit_sha,
                execution_id=execution_id,
            ):
                invalid_executed_proof.append(label)

    if missing or skipped_only or invalid_executed_proof:
        print(
            f"ERROR: {len(missing)} behavioral pr_ci proof(s) never executed and "
            f"{len(skipped_only)} only ever skipped; {len(invalid_executed_proof)} "
            "executed scenario proof(s) lack one exact canonical TraceRecord. Fix "
            "the marker/stage/skip condition for absent executions, correct an "
            "overstated ci_tier, or ensure the executed-proof pytest plugin emits "
            "a well-formed trace property with the exact CI coordinates.",
            file=sys.stderr,
        )
        for label in missing:
            print(f"  - missing: {label}", file=sys.stderr)
        for label in skipped_only:
            print(f"  - skipped-only: {label}", file=sys.stderr)
        for label in invalid_executed_proof:
            print(f"  - invalid-executed-proof: {label}", file=sys.stderr)
        return 1
    print(f"pr_ci evidence reconciliation: {len(scoped)} proofs executed.")
    return 0


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: check_pr_ci_evidence.py <junit-xml> [...]", file=sys.stderr)
        return 2
    return run_check([Path(a) for a in args])


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "PR-CI-EVIDENCE", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
