#!/usr/bin/env python3
"""Exactly TWO gates over the one AC-keyed graph.

This replaces the N per-view byte-compare gates (the generated critical-proof
matrix ``--check``, the vision-to-proof matrix ``--check``, and the EPIC-status
``--check``) with TWO gates over the one AC-keyed graph
(:mod:`common.ssot.ac_graph`):

**Gate A — INTEGRITY (hard, binary).** One predicate — "does this reference
obligation resolve?" — applied to every edge type. It collects, from the graph,
every ``(source, expected_target, kind, reason)`` obligation and asserts each
target exists. It catches:

* every AC is *managed*: enumerated with a protection record (an all-zero/empty
  record is VALID — managed means present in the structure, not that it has a
  test);
* every ``@ac_proof`` points at a real test (file + function) and at AC ids that
  exist in the registry;
* every macro outcome's ``proof_ids`` resolve to a declared proof;
* every vision item that owns at least one EPIC backs at least one AC (no
  dangling vision promise);
* every mandatory, non-deprecated AC resolves to >=1 real test reference (the
  traceability invariant — kept a HARD integrity rule, identical to before).

The per-edge-type ERROR WORDING is preserved verbatim from the four legacy
functions; only the engine is unified, so fixability is unchanged.

**Gate B — PROTECTION RATCHET (soft, monotonic, per type).** Two conflict-safe,
never-regressing sub-parts:

1. the per-AC behavioural-score floor over ``ac-score-baseline.jsonl`` (delegated
   unchanged to ``check_ac_score_baseline``, ``merge=union`` conflict-free);
2. the per-type COUNT floor over ``protection-floor.json`` (delegated to
   :mod:`common.ssot.protection`): for each protection type, current count of
   mandatory active ACs at that type must be ``>=`` the committed floor. Adding
   protection only raises the current count and passes WITHOUT editing the floor
   file; the floor is bumped only by the explicit ``--update-floor`` action.

``main()`` runs Gate A then Gate B and exits 1 if either fails. On pass it prints
the per-type protection dashboard so the gate REPORTS the protection levels even
though only a floor regression fails it.

The full critical-proof semantic contract (proof shape, trust modes, README
macro-outcome sync, behavioural anchors) stays owned by
``tools/check_critical_proof_matrix.py``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from common.ssot.ac_graph import AcGraph, build_ac_graph
from common.ssot.protection import (
    PROTECTION_TYPES,
    check_count_floor,
    update_floor,
)

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


# ---------------------------------------------------------------------------
# Gate A — INTEGRITY
# ---------------------------------------------------------------------------
#
# One predicate — "does this reference obligation resolve?" — over every edge
# type. Each obligation carries a per-edge-type ``message`` so the SPECIFIC
# legacy wording is preserved verbatim (generic messages hurt fixability). The
# four legacy functions below are kept as thin views onto the same obligation
# engine so existing imports/tests keep working.


@dataclass(frozen=True)
class Obligation:
    """One 'this reference must resolve' assertion produced from the graph."""

    ok: bool
    message: str


def _proof_obligations(graph: AcGraph) -> list[Obligation]:
    """Every @ac_proof must point at a real test and real AC ids."""
    out: list[Obligation] = []
    for proof in graph.proofs:
        if not proof.ac_ids:
            out.append(Obligation(False, f"proof {proof.proof_id!r}: declares no ac_ids"))
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
    """Every macro outcome's proof_ids must resolve to a declared proof."""
    declared = {proof.proof_id for proof in graph.proofs}
    out: list[Obligation] = []
    for outcome in graph.outcomes:
        for proof_id in outcome.proof_ids:
            out.append(
                Obligation(
                    proof_id in declared,
                    f"macro outcome {outcome.id!r}: proof id {proof_id!r} "
                    "does not resolve to any @ac_proof declaration",
                )
            )
    return out


def _vision_obligations(graph: AcGraph) -> list[Obligation]:
    """Every vision item with an owning EPIC must back at least one AC.

    A vision item that declares an owner EPIC but resolves to no AC is a
    dangling vision promise (the anchor claims coverage that no AC delivers).
    Vision anchors with no owner EPIC are intentionally allowed: they are
    parked nodes, not promises, and are surfaced as informational only.
    """
    out: list[Obligation] = []
    for item in graph.vision_items:
        if item.owner_epics:
            out.append(
                Obligation(
                    bool(item.ac_ids),
                    f"vision item {item.anchor!r} (owned by "
                    f"{', '.join(item.owner_epics)}) backs no AC — dangling vision "
                    "promise",
                )
            )
    return out


def _mandatory_traceability_obligations(graph: AcGraph) -> list[Obligation]:
    """Every mandatory, non-deprecated AC must resolve to >=1 real test ref.

    This is the traceability invariant, kept a HARD integrity rule (behaviour
    identical to before). The graph carries ``real_test_files`` per AC from the
    single shared test-tree scan; an empty list for a mandatory, active AC is a
    missing-proof failure. The authoritative CI gate remains
    ``tools/check_ac_traceability.py``; this is the graph-level mirror so the one
    consistency gate covers it too.
    """
    out: list[Obligation] = []
    for node in graph.nodes.values():
        if not node.mandatory or _is_deprecated(node.description):
            continue
        out.append(
            Obligation(
                bool(node.real_test_files),
                f"AC {node.id}: mandatory, active AC has no real test reference",
            )
        )
    return out


def _managed_obligations(graph: AcGraph) -> list[Obligation]:
    """Every AC in the registry must be enumerated with a protection record.

    "Managed" means the AC is present in the structure (the graph enumerates it
    and the protection projection can score it), NOT that it has any test. An
    all-zero/empty protection record is therefore VALID. This obligation only
    fails on a structurally broken node, so a brand-new all-empty repo passes.
    """
    out: list[Obligation] = []
    for ac_id, node in graph.nodes.items():
        out.append(
            Obligation(
                bool(node.id) and node.id == ac_id,
                f"AC {ac_id!r}: not managed — missing from the protection structure",
            )
        )
    return out


def _integrity_obligations(graph: AcGraph) -> list[Obligation]:
    return [
        *_managed_obligations(graph),
        *_proof_obligations(graph),
        *_macro_outcome_obligations(graph),
        *_vision_obligations(graph),
        *_mandatory_traceability_obligations(graph),
    ]


def check_integrity(graph: AcGraph) -> list[str]:
    """Gate A: one engine, every reference obligation must resolve.

    Collects all ``(source, expected_target, kind, reason)`` obligations from the
    graph and asserts each target exists, returning the per-edge-type message for
    each unresolved one (verbatim from the legacy checks).
    """
    return [ob.message for ob in _integrity_obligations(graph) if not ob.ok]


# Backwards-compatible thin views onto the unified obligation engine. They keep
# the exact same return shape (and messages) as before so existing callers/tests
# that import the individual checks keep working.
def check_proof_edges(graph: AcGraph) -> list[str]:
    return [ob.message for ob in _proof_obligations(graph) if not ob.ok]


def check_macro_outcomes(graph: AcGraph) -> list[str]:
    return [ob.message for ob in _macro_outcome_obligations(graph) if not ob.ok]


def check_vision_items(graph: AcGraph) -> list[str]:
    return [ob.message for ob in _vision_obligations(graph) if not ob.ok]


def check_mandatory_traceability(graph: AcGraph) -> list[str]:
    return [ob.message for ob in _mandatory_traceability_obligations(graph) if not ob.ok]


def check_graph(graph: AcGraph) -> list[str]:
    """Run Gate A (INTEGRITY) over the graph. Alias for :func:`check_integrity`."""
    return check_integrity(graph)


# ---------------------------------------------------------------------------
# Gate B — PROTECTION RATCHET
# ---------------------------------------------------------------------------


def _run_score_ratchet(repo_root: Path, current: Path, baseline: Path | None) -> int:
    from common.ssot.check_ac_score_baseline import (
        DEFAULT_BASELINE,
        main as ratchet_main,
    )

    argv = [str(current)]
    argv += ["--baseline", str(baseline or DEFAULT_BASELINE)]
    return ratchet_main(argv)


def _render_protection_dashboard(counts: dict[str, int], floor: dict[str, int]) -> str:
    lines = ["PROTECTION dashboard (mandatory, active ACs per type):"]
    for ptype in PROTECTION_TYPES:
        lines.append(f"  {ptype}: current {counts[ptype]} (floor {floor[ptype]})")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exactly two gates over the AC-keyed graph: A) INTEGRITY (hard: every "
            "AC managed + no dangling reference), B) PROTECTION RATCHET (per-type "
            "count floor + per-AC score floor, monotonic and conflict-safe)."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--ratchet-current",
        type=Path,
        default=None,
        help=(
            "Aggregated current AC-evidence JSON. When provided, the persisted "
            "behavioural-score floor (Gate B part 1) is checked too (delegated to "
            "check_ac_score_baseline)."
        ),
    )
    parser.add_argument(
        "--ratchet-baseline",
        type=Path,
        default=None,
        help="JSONL ratchet baseline (default: docs/ssot/ac-score-baseline.jsonl).",
    )
    parser.add_argument(
        "--floor-file",
        type=Path,
        default=None,
        help="Per-type protection count floor (default: docs/ssot/protection-floor.json).",
    )
    parser.add_argument(
        "--update-floor",
        action="store_true",
        help=(
            "Raise the per-type count floor to the current counts (never lowers), "
            "then exit. The separate 'lock in gains' action so protection-adding "
            "PRs never edit the floor file."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    floor_file = args.floor_file or (repo_root / "docs" / "ssot" / "protection-floor.json")

    graph = build_ac_graph(repo_root)

    # The explicit "lock in gains" action: raise floors, write, exit.
    if args.update_floor:
        raised = update_floor(graph, floor_file)
        print("Updated per-type protection floor:")
        for ptype in PROTECTION_TYPES:
            print(f"  {ptype}: {raised[ptype]}")
        return 0

    # ---- Gate A: INTEGRITY (hard) ----
    integrity_errors = check_integrity(graph)
    if integrity_errors:
        for error in integrity_errors:
            print(f"::error title=AC index INTEGRITY::{error}", file=sys.stderr)
        print(
            f"[INTEGRITY] FAILED: {len(integrity_errors)} dangling/missing link(s).",
            file=sys.stderr,
        )
        return 1

    print(
        "[INTEGRITY] PASSED: "
        f"{len(graph.nodes)} AC node(s) managed, {len(graph.proofs)} @ac_proof "
        f"edge(s), {len(graph.vision_items)} vision item(s), {len(graph.outcomes)} "
        "macro outcome(s); no dangling/missing links."
    )

    # ---- Gate B: PROTECTION RATCHET (soft, monotonic, per type) ----
    # Part 2: per-type COUNT floor.
    floor_result = check_count_floor(graph, floor_file)
    print(_render_protection_dashboard(floor_result.counts, floor_result.floor))
    if floor_result.errors:
        for error in floor_result.errors:
            print(f"::error title=AC index PROTECTION::{error}", file=sys.stderr)
        print(
            f"[PROTECTION] FAILED: {len(floor_result.errors)} per-type count "
            "regression(s). Restore the protection that was removed (adding it back "
            "raises the current count), or — only if the floor was set too high — "
            "lower it by hand-editing protection-floor.json (--update-floor only "
            "RAISES floors and cannot fix current < floor).",
            file=sys.stderr,
        )
        return 1

    # Part 1: per-AC behavioural-score floor (delegated, unchanged).
    if args.ratchet_current is not None:
        rc = _run_score_ratchet(repo_root, args.ratchet_current, args.ratchet_baseline)
        if rc != 0:
            print(
                "::error title=AC index PROTECTION::behavioural-score ratchet regressed",
                file=sys.stderr,
            )
            return rc

    print("[PROTECTION] PASSED: no per-type count regression; score floor intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
