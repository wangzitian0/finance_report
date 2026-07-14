"""Value-asserting ratchet for critical macro-outcome proofs (issue #1623).

A `covered` critical outcome today only has to point at a behavioral E2E proof —
"the flow ran". It is not required to assert a business VALUE (compare an actual
computed number against an expected). That is exactly how "green but wrong" ships
(e.g. a brokerage statement rendering "Parsing"/$0.00 while every gate is green).

A proof is *value-asserting* when at least one AC it backs declares a
value-asserting ``proof_kind`` (exact / property / invariant / eval — see
``common/meta/base/authority_matrix.py``). smoke / evidence / unset are not.

Enforced as a RATCHET, not an absolute gate: the critical proofs today are
mostly un-tagged (proof_kind unset), so an absolute gate would fail everything.
Instead we freeze the current set of non-value-asserting (outcome, proof) pairs
as a baseline; the set may only SHRINK. A NEW critical outcome, or a newly
non-value-asserting proof, fails CI — and once an AC gains a value-asserting
proof_kind (which the proof_kind ratchet then prevents downgrading), the
baseline shrinks and can never regrow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTCOMES_PATH = (
    REPO_ROOT / "common" / "testing" / "data" / "critical-proof-outcomes.yaml"
)
BASELINE_PATH = Path(__file__).parent / "critical-value-proof-baseline.json"

VALUE_ASSERTING_KINDS = {"exact", "property", "invariant", "eval"}


def _registry_proof_kinds(repo_root: Path = REPO_ROOT) -> dict[str, str | None]:
    """EXPLICIT ``proof_kind`` declarations per AC id, from the LIVE source.

    ``docs/ac_registry.yaml`` is a checked-in pointer stub (no per-AC entries),
    so reading it here silently degraded this ratchet to "no AC is
    value-asserting" — exactly the silent-safety-net failure #1826 targets.
    Read the authoritative source instead: every package contract roadmap's
    ``ACRecord(proof_kind=...)`` literal (AST scan via the registry
    generator's own reader, no contract import).

    Deliberately EXPLICIT-only: a tier's canonical default kind (e.g.
    CODE-ONLY -> exact) is a vocabulary fallback, not evidence that the
    backing test asserts a business value — counting defaults would clear the
    whole critical-value baseline for free the moment a package declares a
    tier. Legacy EPIC-owned ACs (no package home yet) are likewise counted as
    non-value-asserting until they migrate — over-strict fails safe.
    """
    from common.meta.extension.generate_ac_registry import _roadmap_acs_from_contract

    kinds: dict[str, str | None] = {}
    for contract_path in sorted((repo_root / "common").glob("*/contract.py")):
        for record in _roadmap_acs_from_contract(contract_path):
            kinds[record["id"]] = record["proof_kind"]
    return kinds


def current_non_value_proofs() -> set[str]:
    """Return ``"{outcome}::{proof}"`` for every covered-outcome proof that
    references no value-asserting AC."""
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    proofs = {
        p["id"]: p
        for p in build_matrix_from_graph(build_proofs_only()).get("proofs", [])
    }
    kinds = _registry_proof_kinds()
    outcomes = yaml.safe_load(OUTCOMES_PATH.read_text(encoding="utf-8")).get(
        "outcomes", []
    )

    offenders: set[str] = set()
    for outcome in outcomes:
        if outcome.get("status") != "covered":
            continue
        for pid in outcome.get("proof_ids", []):
            proof = proofs.get(pid)
            if proof is None:
                continue  # unknown-proof is caught by the existing matrix gate
            has_value = any(
                kinds.get(ac_id) in VALUE_ASSERTING_KINDS
                for ac_id in proof.get("ac_ids", [])
            )
            if not has_value:
                offenders.add(f"{outcome['id']}::{pid}")
    return offenders


def _load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    return set(
        json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get(
            "non_value_proofs", []
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    current = current_non_value_proofs()
    baseline = _load_baseline()

    if "--update" in args:
        # Seeding (no baseline yet) is allowed; once a baseline exists it may
        # only shrink — new violations must be fixed, not baselined.
        added = (current - baseline) if BASELINE_PATH.exists() else set()
        if added:
            print(
                "REFUSED: the ratchet only shrinks; these NEW non-value-asserting "
                "critical proofs must gain a value-asserting proof_kind, not be "
                "baselined:\n  " + "\n  ".join(sorted(added)),
                file=sys.stderr,
            )
            return 1
        BASELINE_PATH.write_text(
            json.dumps({"non_value_proofs": sorted(current)}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"baseline updated: {len(baseline)} -> {len(current)} non-value-asserting critical proofs"
        )
        return 0

    added = current - baseline
    if added:
        print(
            f"ERROR: {len(added)} critical macro-outcome proof(s) assert no business "
            "value (no backing AC has proof_kind in {exact, property, invariant, "
            "eval}). A covered critical outcome must prove a NUMBER is right, not "
            "just that the flow ran:\n  " + "\n  ".join(sorted(added)),
            file=sys.stderr,
        )
        return 1
    print(
        f"critical value-proof ratchet: {len(current)} non-value-asserting "
        f"(baseline {len(baseline)}); no new violations."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
