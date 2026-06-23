#!/usr/bin/env python3
"""Enforcement gate for the tier -> valid-proof-kind matrix (EPIC-026 phase 2).

EPIC-026 phase 1 gave every acceptance criterion (AC) an authority *tier*
(PC/CP/HU/LP/PL) and an SSOT matrix (``docs/ssot/authority-tiers.md``) saying
which KIND of proof is valid for an AC at each tier. That matrix was descriptive
only. This gate makes it ENFORCED — but ONLY for ACs that carry a tier, so it is
non-breaking for the ~1655 untagged legacy ACs (they have no ``proof_kind`` key
and are ignored).

The proof KIND is declared next to the AC text with a ``{proof:KIND}`` marker
(parsed by :mod:`common.ssot.generate_ac_registry` alongside ``{tier:XX}``). When
an AC declares a tier but no explicit proof marker, the kind defaults to the
tier's canonical valid kind, so the registry value is always a matrix-valid kind
unless someone declares an explicit, *contradictory* marker.

The matrix this gate enforces (mirroring ``authority-tiers.md`` "tier -> valid
proof type"):

- **PC**: ``exact`` or ``property`` — a deterministic exact/property assertion.
- **CP**: ``exact`` or ``property`` — the test asserts the CODE's final decision.
- **HU**: ``evidence`` — the test asserts the evidence chain is present.
- **LP**: ``property`` | ``invariant`` | ``eval`` and **MUST NOT** be ``exact`` —
  an LLM-emitted output cannot be proven by an exact golden assertion; it is
  caught by a deterministic invariant or graded eval instead.
- **PL**: ``eval`` | ``smoke`` and **MUST NOT** be ``exact`` — pure-LLM narrative
  has no hard oracle and must not assert numbers.

This gate asserts the AC's *declared* (or tier-defaulted) proof kind matches its
tier. It does not yet inspect the referenced test's shape — verifying that an LP
AC's test is genuinely invariant-style (not an exact assertion mislabeled
``property``) is a documented follow-up; until then the first-batch LP ACs are
repointed at real property/invariant tests so the declared kind is honest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.ssot.ac_registry_format import sort_key
from common.ssot.authority_matrix import TIER_VALID_PROOF_KINDS
from common.ssot.generate_ac_registry import AC_PROOF_KINDS, build_registry_entries

REPO_ROOT = Path(__file__).resolve().parents[2]

# tier -> the set of proof kinds the SSOT matrix accepts for that tier. The prose
# source of truth is docs/ssot/authority-tiers.md; its single MACHINE mirror is
# common/ssot/authority_matrix.TIER_VALID_PROOF_KINDS (which package_contract also
# re-exports for the PackageContract model). Aliased here so this gate and the
# contract model enforce one identical matrix — they cannot drift apart.
VALID_PROOF_KINDS: dict[str, frozenset[str]] = TIER_VALID_PROOF_KINDS


def proof_kind_violations(repo_root: Path) -> list[str]:
    """Return one message per tier-tagged AC whose proof_kind violates the matrix.

    Untagged ACs (no ``tier``) are ignored entirely, so the gate is non-breaking.
    A tier-tagged AC always has a ``proof_kind`` (explicit marker or tier default);
    a missing key is treated as a structural error and reported.
    """
    entries = build_registry_entries(epic_source=repo_root / "docs" / "project")
    errors: list[str] = []
    for ac_id in sorted(entries, key=sort_key):
        entry = entries[ac_id]
        tier = entry.get("tier")
        if not tier:
            continue
        tier = str(tier).upper()
        valid = VALID_PROOF_KINDS.get(tier)
        if valid is None:
            errors.append(
                f"{ac_id}: unknown tier {tier!r} (expected one of {sorted(VALID_PROOF_KINDS)})"
            )
            continue
        proof_kind = entry.get("proof_kind")
        if not proof_kind:
            errors.append(
                f"{ac_id} (tier {tier}): carries a tier but no proof_kind — "
                "declare a {proof:KIND} marker at its definition site."
            )
            continue
        proof_kind = str(proof_kind).lower()
        if proof_kind not in AC_PROOF_KINDS:
            errors.append(
                f"{ac_id} (tier {tier}): unknown proof kind {proof_kind!r} "
                f"(valid kinds: {', '.join(AC_PROOF_KINDS)})."
            )
            continue
        if proof_kind not in valid:
            forbidden_exact = tier in {"LP", "PL"} and proof_kind == "exact"
            hint = (
                " — LP/PL behavior is LLM-emitted and MUST NOT be proven by an "
                "exact golden assertion; use property/invariant/eval (LP) or "
                "eval/smoke (PL)."
                if forbidden_exact
                else ""
            )
            errors.append(
                f"{ac_id} (tier {tier}): proof kind {proof_kind!r} is not valid "
                f"for this tier (valid: {', '.join(sorted(valid))}){hint}"
            )
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce the tier -> valid-proof-kind matrix for tier-tagged ACs "
            "(non-breaking: untagged ACs are ignored)."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()

    violations = proof_kind_violations(repo_root)
    if violations:
        for message in violations:
            print(
                f"::error title=AC proof-kind::{message} "
                "(see docs/ssot/authority-tiers.md).",
                file=sys.stderr,
            )
        print(
            f"[PROOF-KIND] FAILED: {len(violations)} tier-tagged AC(s) whose "
            "declared proof kind violates the tier->proof matrix.",
            file=sys.stderr,
        )
        return 1

    print(
        "[PROOF-KIND] PASSED: every tier-tagged AC declares a proof kind valid "
        "for its tier (LP/PL never exact; HU is evidence)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
