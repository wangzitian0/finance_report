#!/usr/bin/env python3
"""Per-type protection counts + the monotonic count floor (Gate B part 2).

This is the COUNT side of the protection ratchet. The per-AC behavioural-score
floor (``ac-score-baseline.jsonl``) is owned by
:mod:`common.testing.check_ac_score_baseline`; this module owns the complementary
per-TYPE count floor: for each protection *type* it derives how many mandatory,
active ACs currently have that type from the graph, and enforces
``current_count[type] >= committed_floor[type]`` so protection never regresses
in aggregate.

Protection types (each derived purely from the AC graph):

* ``has_real_ref`` — L1: a real (non-stub) test file references the AC id.
* ``has_proof`` — L2: a resolved ``@ac_proof`` binds the AC.
* ``has_score`` — L3: the AC has a persisted ratchet floor in the JSONL baseline.
* ``has_mirror`` — a proof binding the AC carries a ``mirror_proof_id``.

Conflict-safety convention (this is the whole point of the split file):
adding protection only RAISES the current count, which passes
``current >= floor`` without touching ``protection-floor.json``. The floor file
is bumped ONLY by an explicit ``--update-floor`` ("lock in gains") action, so a
normal protection-adding PR never edits it and it never becomes a merge-conflict
hotspot. The default empty floor (all zeros / missing file) is VALID, so a
brand-new repo passes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from common.testing.ac_graph import AcGraph

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FLOOR = REPO_ROOT / "common" / "testing" / "data" / "protection-floor.json"

# The protection types enforced by the count floor, in a stable display order.
PROTECTION_TYPES = ("has_real_ref", "has_proof", "has_score", "has_mirror")


def _is_deprecated(description: str) -> bool:
    text = description.strip()
    return text.startswith("~~") and text.endswith("~~") and len(text) > 4


def _ac_has_mirror(graph: AcGraph, proof_ids: tuple[str, ...]) -> bool:
    for proof_id in proof_ids:
        proof = graph.proof_by_id(proof_id)
        if proof is not None and str(proof.fields.get("mirror_proof_id", "")).strip():
            return True
    return False


def count_protection_types(graph: AcGraph) -> dict[str, int]:
    """Count mandatory, active ACs that currently have each protection type.

    Pure projection over the graph — no I/O beyond what the graph already holds.
    Only mandatory, non-deprecated ACs are counted (the population the gate
    protects); a deprecated or non-mandatory AC never contributes to a floor.
    """
    counts = dict.fromkeys(PROTECTION_TYPES, 0)
    for node in graph.nodes.values():
        if not node.mandatory or _is_deprecated(node.description):
            continue
        if node.real_test_files:
            counts["has_real_ref"] += 1
        if node.proof_ids:
            counts["has_proof"] += 1
        if node.score is not None:
            counts["has_score"] += 1
        if _ac_has_mirror(graph, node.proof_ids):
            counts["has_mirror"] += 1
    return counts


def load_floor(path: Path = DEFAULT_FLOOR) -> dict[str, int]:
    """Load the committed per-type floor; a missing file is an all-zero floor.

    A missing TYPE defaults to 0 (so a brand-new repo / newly-added type passes),
    but a PRESENT value that is not a non-negative integer is a hard error rather
    than a silent coercion to 0: silently swallowing a malformed floor would
    weaken the ratchet (a bad edit would let regressions pass unnoticed).
    """
    if not path.exists():
        return dict.fromkeys(PROTECTION_TYPES, 0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: protection floor must be a JSON object")
    floor = payload.get("floor", payload)
    if not isinstance(floor, dict):
        raise ValueError(f"{path}: 'floor' must be a JSON object of type->int")
    result = dict.fromkeys(PROTECTION_TYPES, 0)
    for ptype in PROTECTION_TYPES:
        if ptype not in floor:
            continue
        value = floor[ptype]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"{path}: floor[{ptype!r}] must be a non-negative integer, got {value!r}"
            )
        result[ptype] = value
    return result


@dataclass(frozen=True)
class FloorResult:
    """Outcome of comparing current per-type counts against the committed floor."""

    counts: dict[str, int]
    floor: dict[str, int]
    errors: list[str]


def check_count_floor(graph: AcGraph, floor_path: Path = DEFAULT_FLOOR) -> FloorResult:
    """Enforce ``current_count[type] >= committed_floor[type]`` for each type.

    A regression (current below floor) is a hard failure. Adding protection only
    raises the current count and passes without editing the floor file.
    """
    counts = count_protection_types(graph)
    floor = load_floor(floor_path)
    errors: list[str] = []
    for ptype in PROTECTION_TYPES:
        if counts[ptype] < floor[ptype]:
            errors.append(
                f"protection type {ptype!r}: current count {counts[ptype]} < "
                f"committed floor {floor[ptype]} — protection regressed"
            )
    return FloorResult(counts=counts, floor=floor, errors=errors)


def write_floor(path: Path, floor: dict[str, int]) -> None:
    """Write the per-type floor as deterministic JSON with a convention header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            "Per-type PROTECTION COUNT floor (monotonic, raise-only). Normal PRs "
            "that ADD protection must NOT edit this file: adding protection only "
            "raises the CURRENT count, which passes current>=floor untouched. "
            "Bump it ONLY via `tools/check_ac_index.py --update-floor` (a separate "
            "lock-in-gains action), so it is almost never in a PR diff and does "
            "not become a conflict hotspot. Default all-zero is valid."
        ),
        "version": 1,
        "floor": {ptype: int(floor.get(ptype, 0)) for ptype in PROTECTION_TYPES},
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def update_floor(graph: AcGraph, floor_path: Path = DEFAULT_FLOOR) -> dict[str, int]:
    """Raise each floor to the current count (never lowers). Returns the new floor."""
    counts = count_protection_types(graph)
    current_floor = load_floor(floor_path)
    raised = {
        ptype: max(current_floor[ptype], counts[ptype]) for ptype in PROTECTION_TYPES
    }
    write_floor(floor_path, raised)
    return raised
