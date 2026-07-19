"""Structural proofs for the TrustedYearScenario v0 contract (#696)."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from common.testing.ac_proof import PROOF_ATTR, ac_proof
from common.testing.generate_critical_proof_matrix import collect_proofs
from common.testing.trusted_year import (
    TRUSTED_YEAR_SCENARIO,
    TrustedYearError,
    TrustedYearProofBinding,
)


def test_AC_testing_trusted_year_1_scenario_is_small_exact_and_closed() -> None:
    """AC-testing.trusted-year.1: v0 truth is compact, exact, and closed."""
    scenario = TRUSTED_YEAR_SCENARIO

    assert scenario.scenario_id == "trusted-year-v0"
    assert len(scenario.movements) == 3
    assert len(scenario.expected_manifest) == 6
    assert all(isinstance(movement.amount, Decimal) for movement in scenario.movements)
    assert scenario.expected.ending_cash == Decimal("13000.00")

    with pytest.raises(TrustedYearError, match="must be Decimal"):
        replace(scenario, opening_cash=10000)  # type: ignore[arg-type]
    with pytest.raises(TrustedYearError, match="balance-sheet equation"):
        replace(scenario.expected, total_liabilities=Decimal("1.00"))


def test_AC_testing_capability_proof_2_binding_rejects_stitching() -> None:
    """AC-testing.capability-proof.2: one proof cannot stitch scenarios."""
    binding = TrustedYearProofBinding(
        proof_id="trusted-year-v0-terminal",
        scenario_ids=(TRUSTED_YEAR_SCENARIO.scenario_id,),
        oracle_kind="independent_decimal",
    )
    assert binding.scenario_ids == ("trusted-year-v0",)

    with pytest.raises(TrustedYearError, match="exactly one scenario"):
        replace(binding, scenario_ids=("trusted-year-v0", "another-scenario"))
    with pytest.raises(TrustedYearError, match="oracle_kind is required"):
        replace(binding, oracle_kind="")


def test_AC_testing_capability_proof_1_collector_preserves_scenario_binding() -> None:
    """AC-testing.capability-proof.1: collection retains execution coordinates."""
    repo_root = Path(__file__).resolve().parents[2]
    proof = next(
        item
        for item in collect_proofs(repo_root)
        if item.proof_id == "trusted-year-v0-terminal"
    )

    assert proof.fields["scenario_id"] == "trusted-year-v0"
    assert proof.fields["oracle_kind"] == "independent_decimal"
    assert proof.fields["ci_tier"] == "pr_ci"

    @ac_proof(
        "runtime-binding",
        ac_ids=["AC-testing.capability-proof.1"],
        scenario_id="trusted-year-v0",
        oracle_kind="independent_decimal",
    )
    def runtime_proof() -> None:
        pass

    metadata = getattr(runtime_proof, PROOF_ATTR)
    assert metadata.scenario_id == "trusted-year-v0"
    assert metadata.oracle_kind == "independent_decimal"
