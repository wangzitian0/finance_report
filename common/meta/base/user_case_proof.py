"""Pure derivation of objective proof tiers for the 47 canonical user cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any


class ProofTier(StrEnum):
    """Derived proof maturity tier for one user case."""

    L0_GAP = "L0_GAP"
    L1_PARTIAL = "L1_PARTIAL"
    L2_SURFACE_CONTRACT = "L2_SURFACE"
    L3_BENCH_PROVEN = "L3_BENCH"
    L3_E2E_PROVEN = "L3_E2E"
    L4_FULL_PROOF = "L4_FULL"


PROOF_TIER_ORDER: tuple[ProofTier, ...] = (
    ProofTier.L4_FULL_PROOF,
    ProofTier.L3_E2E_PROVEN,
    ProofTier.L3_BENCH_PROVEN,
    ProofTier.L2_SURFACE_CONTRACT,
    ProofTier.L1_PARTIAL,
    ProofTier.L0_GAP,
)

# Current baseline floors (ratchet: only block proof deletions, never unrelated PRs).
PROOF_FLOOR_L4_FULL = 14
PROOF_FLOOR_E2E_TOTAL = 21
PROOF_FLOOR_BENCH_TOTAL = 30


def derive_proof_tier(uc: Mapping[str, Any]) -> ProofTier:
    """Compute the objective proof tier strictly from physical proof references."""
    if uc.get("gap_issue"):
        return ProofTier.L0_GAP if uc.get("gap_kind") == "gap" else ProofTier.L1_PARTIAL
    has_e2e = bool(str(uc.get("e2e_test_ref") or "").strip())
    has_bench = bool(uc.get("benchmark_cases"))
    if has_e2e and has_bench:
        return ProofTier.L4_FULL_PROOF
    if has_e2e:
        return ProofTier.L3_E2E_PROVEN
    if has_bench:
        return ProofTier.L3_BENCH_PROVEN
    return ProofTier.L2_SURFACE_CONTRACT


def format_proof_tier_cell(uc: Mapping[str, Any]) -> str:
    """Render the Markdown cell value for one user case's derived proof tier."""
    tier = derive_proof_tier(uc)
    gap_issue = uc.get("gap_issue")
    return f"{tier.value} ({gap_issue})" if gap_issue else tier.value


def summarize_domain_tiers(domains: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate derived proof-tier counts per domain."""
    rows: list[dict[str, Any]] = []
    for domain in domains:
        counts = {tier: 0 for tier in PROOF_TIER_ORDER}
        cases = domain.get("user_cases", ())
        for uc in cases:
            counts[derive_proof_tier(uc)] += 1
        rows.append(
            {
                "id": int(domain["id"]),
                "name": str(domain["name"]),
                "total": len(cases),
                **{tier.value: counts[tier] for tier in PROOF_TIER_ORDER},
            }
        )
    return rows


def summarize_registry_totals(domains: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Aggregate derived proof-tier counts across all domains."""
    domain_rows = summarize_domain_tiers(domains)
    totals: dict[str, int] = {"total": sum(row["total"] for row in domain_rows)}
    for tier in PROOF_TIER_ORDER:
        totals[tier.value] = sum(row[tier.value] for row in domain_rows)
    return totals
