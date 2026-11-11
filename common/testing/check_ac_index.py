#!/usr/bin/env python3
"""Integrity (Gate A) and protection-ratchet (Gate B) gates over the AC-keyed graph."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from common.meta.base.gate_cli import run_cli_command
from common.meta.base.gate_util import parse_ast_cached
from common.testing.ac_graph import AcGraph, build_ac_graph
from common.testing.protection import (
    PROTECTION_TYPES,
    check_count_floor,
    update_floor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_UPDATE_MODE = "raise-only"
RepoIntegrityCheck = Callable[[Path, AcGraph], list[str]]


def _escape_workflow_command(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _ac_exists(graph: AcGraph, ac_id: str) -> bool:
    return ac_id in graph.nodes


def _real_test(repo_root: Path, file_rel: str, test_name: str) -> bool:
    path = repo_root / file_rel
    if not path.exists():
        return False
    try:
        module = parse_ast_cached(path)
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == test_name
        for node in ast.walk(module)
    )


@dataclass(frozen=True)
class Obligation:
    ok: bool
    message: str


def _proof_obligations(graph: AcGraph) -> list[Obligation]:
    out: list[Obligation] = []
    for proof in graph.proofs:
        if not proof.ac_ids:
            out.append(
                Obligation(False, f"proof {proof.proof_id!r}: declares no ac_ids")
            )
        for ac_id in proof.ac_ids:
            out.append(
                Obligation(
                    _ac_exists(graph, ac_id),
                    f"proof {proof.proof_id!r}: references unknown AC id {ac_id!r}",
                )
            )
        out.append(
            Obligation(
                _real_test(graph.repo_root, proof.file, proof.test),
                f"proof {proof.proof_id!r}: test {proof.file}::{proof.test} "
                "does not resolve to a real test function",
            )
        )
    return out


def _macro_outcome_obligations(graph: AcGraph) -> list[Obligation]:
    declared = {proof.proof_id for proof in graph.proofs}
    return [
        Obligation(
            proof_id in declared,
            f"macro outcome {outcome.id!r}: proof id {proof_id!r} "
            "does not resolve to any @ac_proof declaration",
        )
        for outcome in graph.outcomes
        for proof_id in outcome.proof_ids
    ]


def _vision_obligations(graph: AcGraph) -> list[Obligation]:
    return [
        Obligation(
            bool(item.ac_ids),
            f"vision item {item.anchor!r} (owned by "
            f"{', '.join(item.owner_epics)}) backs no AC — dangling vision promise",
        )
        for item in graph.vision_items
        if item.owner_epics
    ]


def _managed_obligations(graph: AcGraph) -> list[Obligation]:
    if not graph.nodes:
        return [Obligation(False, "AC graph is empty: zero AC nodes discovered")]
    return [
        Obligation(
            bool(node.id) and node.id == ac_id,
            f"AC {ac_id!r}: not managed — missing from the protection structure",
        )
        for ac_id, node in graph.nodes.items()
    ]


def _integrity_obligations(graph: AcGraph) -> list[Obligation]:
    return [
        *_managed_obligations(graph),
        *_proof_obligations(graph),
        *_macro_outcome_obligations(graph),
        *_vision_obligations(graph),
    ]


def check_integrity(graph: AcGraph) -> list[str]:
    return [ob.message for ob in _integrity_obligations(graph) if not ob.ok]


def check_repo_contracts(repo_root: Path, graph: AcGraph | None = None) -> list[str]:
    from common.testing.check_ac_traceability import (
        run_traceability,
        traceability_failure_messages,
    )
    from common.testing.check_critical_proof_matrix import validate_matrix_contract
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    matrix_result = (
        validate_matrix_contract(repo_root, build_matrix_from_graph(graph))
        if graph is not None
        else validate_matrix_contract(repo_root)
    )
    return [
        *traceability_failure_messages(run_traceability(repo_root)),
        *matrix_result.errors,
    ]


def _render_protection_dashboard(counts: dict[str, int], floor: dict[str, int]) -> str:
    return "\n".join(
        [
            "PROTECTION dashboard (mandatory, active ACs per type):",
            *(
                f"  {ptype}: current {counts[ptype]} (floor {floor[ptype]})"
                for ptype in PROTECTION_TYPES
            ),
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run INTEGRITY and PROTECTION RATCHET gates over the AC-keyed graph."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--floor-file", type=Path, default=None)
    parser.add_argument("--update-floor", action="store_true")
    return parser.parse_args(argv)


def _run_ac_index(
    argv: Sequence[str] | None = None,
    *,
    repo_integrity_checks: Sequence[RepoIntegrityCheck] = (),
) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    floor_file = args.floor_file or (
        repo_root / "common" / "testing" / "data" / "protection-floor.json"
    )
    graph = build_ac_graph(repo_root)

    if args.update_floor:
        raised = update_floor(graph, floor_file)
        print("Updated per-type protection floor:")
        for ptype in PROTECTION_TYPES:
            print(f"  {ptype}: {raised[ptype]}")
        return 0

    integrity_errors = check_integrity(graph) + check_repo_contracts(repo_root, graph)
    for check in repo_integrity_checks:
        integrity_errors.extend(check(repo_root, graph))
    if integrity_errors:
        for error in integrity_errors:
            print(
                f"::error title=AC index INTEGRITY::{_escape_workflow_command(error)}",
                file=sys.stderr,
            )
        print(
            f"[INTEGRITY] FAILED: {len(integrity_errors)} dangling/missing link(s) "
            "or folded traceability/critical-proof contract violation(s).",
            file=sys.stderr,
        )
        return 1

    print(
        "[INTEGRITY] PASSED: "
        f"{len(graph.nodes)} AC node(s) managed, {len(graph.proofs)} @ac_proof "
        f"edge(s), {len(graph.vision_items)} vision item(s), {len(graph.outcomes)} "
        "macro outcome(s); no dangling/missing links; CI-stage traceability + "
        "critical-proof contract intact."
    )

    floor_result = check_count_floor(graph, floor_file)
    print(_render_protection_dashboard(floor_result.counts, floor_result.floor))
    if floor_result.errors:
        for error in floor_result.errors:
            print(
                f"::error title=AC index PROTECTION::{_escape_workflow_command(error)}",
                file=sys.stderr,
            )
        print(
            f"[PROTECTION] FAILED: {len(floor_result.errors)} per-type count "
            "regression(s). Restore the protection that was removed (adding it back "
            "raises the current count), or — only if the floor was set too high — "
            "lower it by hand-editing protection-floor.json (--update-floor only "
            "RAISES floors and cannot fix current < floor).",
            file=sys.stderr,
        )
        return 1

    print("[PROTECTION] PASSED: no per-type count regression.")
    return 0


def run_ac_index(
    argv: Sequence[str] | None = None,
    *,
    repo_integrity_checks: Sequence[RepoIntegrityCheck] = (),
) -> int:
    return run_cli_command(
        lambda cli_argv: _run_ac_index(
            cli_argv, repo_integrity_checks=repo_integrity_checks
        ),
        argv,
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run_ac_index(argv)


if __name__ == "__main__":
    raise SystemExit(main())
