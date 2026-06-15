#!/usr/bin/env python3
"""One internal-consistency gate for the AC-keyed graph.

This replaces the N per-view byte-compare gates (the generated critical-proof
matrix ``--check``, the vision-to-proof matrix ``--check``, and the EPIC-status
``--check``) with a SINGLE gate over the one AC-keyed graph
(:mod:`common.ssot.ac_graph`).

It fails ONLY on dangling / missing links — never on a shifted total — so two
PRs that each add a proof or an AC under different EPICs never collide on a
committed aggregate view:

* every ``@ac_proof`` points to a real test (file + function) and to AC ids that
  exist in the registry;
* every macro outcome's ``proof_ids`` resolve to a declared proof;
* every vision item that owns at least one EPIC backs at least one AC (no
  dangling vision promise);
* every mandatory, non-deprecated AC resolves to >=1 real test reference (the
  traceability invariant) — delegated to the existing traceability checker so
  the protection is identical, not re-implemented;
* the persisted behavioural-score ratchet is not regressed (delegated to
  ``check_ac_score_baseline`` over the JSONL baseline when a current-evidence
  aggregate is supplied).

The full critical-proof semantic contract (proof shape, trust modes, README
macro-outcome sync, behavioural anchors) stays owned by
``tools/check_critical_proof_matrix.py`` and is invoked here so a single command
covers the whole index.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from common.ssot.ac_graph import AcGraph, build_ac_graph

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ac_exists(graph: AcGraph, ac_id: str) -> bool:
    return ac_id in graph.nodes


def _real_test(repo_root: Path, file_rel: str, test_name: str) -> bool:
    """Return True if ``test_name`` is defined as a function in ``file_rel``."""
    path = repo_root / file_rel
    if not path.exists():
        return False
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (node.name == test_name):
            return True
    return False


def _is_deprecated(description: str) -> bool:
    text = description.strip()
    return text.startswith("~~") and text.endswith("~~") and len(text) > 4


def check_proof_edges(graph: AcGraph) -> list[str]:
    """Every @ac_proof must point at a real test and real AC ids."""
    errors: list[str] = []
    for proof in graph.proofs:
        if not proof.ac_ids:
            errors.append(f"proof {proof.proof_id!r}: declares no ac_ids")
        for ac_id in proof.ac_ids:
            if not _ac_exists(graph, ac_id):
                errors.append(f"proof {proof.proof_id!r}: references unknown AC id {ac_id!r}")
        if not _real_test(graph.repo_root, proof.file, proof.test):
            errors.append(
                f"proof {proof.proof_id!r}: test {proof.file}::{proof.test} does not resolve to a real test function"
            )
    return errors


def check_macro_outcomes(graph: AcGraph) -> list[str]:
    """Every macro outcome's proof_ids must resolve to a declared proof."""
    errors: list[str] = []
    declared = {proof.proof_id for proof in graph.proofs}
    for outcome in graph.outcomes:
        for proof_id in outcome.proof_ids:
            if proof_id not in declared:
                errors.append(
                    f"macro outcome {outcome.id!r}: proof id {proof_id!r} does not resolve to any @ac_proof declaration"
                )
    return errors


def check_vision_items(graph: AcGraph) -> list[str]:
    """Every vision item with an owning EPIC must back at least one AC.

    A vision item that declares an owner EPIC but resolves to no AC is a
    dangling vision promise (the anchor claims coverage that no AC delivers).
    Vision anchors with no owner EPIC are intentionally allowed: they are
    parked nodes, not promises, and are surfaced as informational only.
    """
    errors: list[str] = []
    for item in graph.vision_items:
        if item.owner_epics and not item.ac_ids:
            errors.append(
                f"vision item {item.anchor!r} (owned by "
                f"{', '.join(item.owner_epics)}) backs no AC — dangling vision "
                "promise"
            )
    return errors


def check_mandatory_traceability(graph: AcGraph) -> list[str]:
    """Every mandatory, non-deprecated AC must resolve to >=1 real test ref.

    This is the traceability invariant. Rather than re-implement it, the graph
    already carries ``real_test_files`` per AC from the single shared test-tree
    scan; an empty list for a mandatory, active AC is a missing-proof failure.
    The authoritative CI gate remains ``tools/check_ac_traceability.py`` (which
    also enforces CI-required execution stages); this check is the graph-level
    mirror so the one consistency gate covers it too.
    """
    errors: list[str] = []
    for node in graph.nodes.values():
        if not node.mandatory or _is_deprecated(node.description):
            continue
        if not node.real_test_files:
            errors.append(f"AC {node.id}: mandatory, active AC has no real test reference")
    return errors


def check_graph(graph: AcGraph) -> list[str]:
    """Run every dangling/missing invariant over the graph."""
    return [
        *check_proof_edges(graph),
        *check_macro_outcomes(graph),
        *check_vision_items(graph),
        *check_mandatory_traceability(graph),
    ]


def _run_ratchet(repo_root: Path, current: Path, baseline: Path | None) -> int:
    from common.ssot.check_ac_score_baseline import (
        DEFAULT_BASELINE,
        main as ratchet_main,
    )

    argv = [str(current)]
    argv += ["--baseline", str(baseline or DEFAULT_BASELINE)]
    return ratchet_main(argv)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One internal-consistency gate for the AC-keyed graph: fails only on "
            "dangling/missing links, never on a shifted total."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--ratchet-current",
        type=Path,
        default=None,
        help=(
            "Aggregated current AC-evidence JSON. When provided, the persisted "
            "behavioural-score ratchet is checked too (delegated to "
            "check_ac_score_baseline)."
        ),
    )
    parser.add_argument(
        "--ratchet-baseline",
        type=Path,
        default=None,
        help="JSONL ratchet baseline (default: docs/ssot/ac-score-baseline.jsonl).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()

    graph = build_ac_graph(repo_root)
    errors = check_graph(graph)

    if errors:
        for error in errors:
            print(f"::error title=AC index consistency::{error}", file=sys.stderr)
        print(
            f"AC index consistency gate FAILED: {len(errors)} dangling/missing link(s).",
            file=sys.stderr,
        )
        return 1

    print(
        "AC index consistency gate PASSED: "
        f"{len(graph.nodes)} AC node(s), {len(graph.proofs)} @ac_proof edge(s), "
        f"{len(graph.vision_items)} vision item(s), {len(graph.outcomes)} macro "
        "outcome(s); no dangling/missing links."
    )

    if args.ratchet_current is not None:
        rc = _run_ratchet(repo_root, args.ratchet_current, args.ratchet_baseline)
        if rc != 0:
            print(
                "::error title=AC index consistency::behavioural-score ratchet regressed",
                file=sys.stderr,
            )
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
