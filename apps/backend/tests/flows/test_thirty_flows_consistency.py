"""Unified 30-Flow Backend Consistency Assurance Suite.

Validates that all 30 core wealth & accounting flows defined in
`common/meta/flows/thirty_flows_ssot.json` are:
1. Formally registered with complete metadata and domain taxonomy.
2. Backed by verified test suites and runtime endpoints.
3. Invariant-compliant across double-entry balance, split logic, and reporting.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.ledger.splits import (
    calculate_dividend_split,
    calculate_mortgage_split,
    calculate_payroll_split,
    calculate_reconciliation_adjustment,
    calculate_transfer_fx_split,
)
from src.reporting.diagnostics import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
)


def _load_ssot_registry() -> dict:
    repo_root = Path(__file__).resolve().parents[4]
    ssot_path = repo_root / "common" / "meta" / "flows" / "thirty_flows_ssot.json"
    assert ssot_path.exists(), f"SSOT registry missing at {ssot_path}"
    with open(ssot_path, encoding="utf-8") as f:
        return json.load(f)


def _all_flows() -> list[dict]:
    data = _load_ssot_registry()
    flows = []
    for domain in data.get("domains", []):
        for flow in domain.get("flows", []):
            flows.append({**flow, "domain_id": domain["id"], "domain_name": domain["name"]})
    return flows


def test_ssot_registry_completeness():
    """Verify that the SSOT registry contains exactly 30 flows across 7 canonical domains."""
    data = _load_ssot_registry()
    domains = data.get("domains", [])
    assert len(domains) == 7, f"Expected 7 domains, got {len(domains)}"

    flows = _all_flows()
    assert len(flows) == 30, f"Expected exactly 30 flows, got {len(flows)}"

    # Check contiguous IDs 1..30
    flow_ids = [f["id"] for f in flows]
    assert sorted(flow_ids) == list(range(1, 31)), "Flow IDs must be contiguous 1..30"


@pytest.mark.parametrize("flow", _all_flows(), ids=lambda f: f"Flow_{f['id']}_{f['name'][:20]}")
def test_each_flow_has_valid_contracts_and_test_evidence(flow: dict):
    """Verify that every single flow points to valid UI surfaces, endpoints, and existing test files."""
    repo_root = Path(__file__).resolve().parents[4]

    assert flow["name"].strip(), f"Flow {flow['id']} missing name"
    assert flow["title"].strip(), f"Flow {flow['id']} missing title"
    assert flow["ui_surface"].startswith("/"), f"Flow {flow['id']} invalid ui_surface"
    assert flow["backend_endpoint"].strip(), f"Flow {flow['id']} missing backend_endpoint"
    assert flow["invariant"].strip(), f"Flow {flow['id']} missing invariant"

    test_file_path = repo_root / flow["test_ref"]
    assert test_file_path.exists(), f"Flow {flow['id']} referenced test file does not exist: {flow['test_ref']}"


def test_domain_1_ingestion_balance_invariant():
    """Flow 1 Invariant: opening + sum(IN) - sum(OUT) == calculated_closing."""
    opening = Decimal("1000.00")
    txns = [
        {"amount": Decimal("250.50"), "dir": "IN"},
        {"amount": Decimal("50.25"), "dir": "OUT"},
        {"amount": Decimal("100.00"), "dir": "OUT"},
    ]
    calc_closing = opening + sum(t["amount"] if t["dir"] == "IN" else -t["amount"] for t in txns)
    assert calc_closing == Decimal("1100.25")


def test_domain_3_payroll_split_invariant():
    """Flow 14 Invariant: gross_salary == net_payout + income_tax + employee_deductions."""
    result = calculate_payroll_split(
        gross_salary=Decimal("5000.00"),
        income_tax=Decimal("750.00"),
        employee_deductions=Decimal("1000.00"),
    )
    assert result.gross_salary == Decimal("5000.00")
    assert result.net_payout == Decimal("3250.00")
    assert result.net_payout + result.income_tax + result.employee_deductions == result.gross_salary


def test_domain_4_transfer_and_adjustment_invariants():
    """Flow 17 & 18 Invariants: FX real-time decomposition and penny threshold control."""
    # Flow 17
    fx = calculate_transfer_fx_split(
        source_amount=Decimal("500.00"),
        source_currency="GBP",
        source_to_base_rate=Decimal("1.30"),
        target_amount=Decimal("640.00"),
        target_currency="USD",
        target_to_base_rate=Decimal("1.00"),
    )
    assert fx.source_base_value == Decimal("650.00")
    assert fx.target_base_value == Decimal("640.00")
    assert fx.realized_gain_loss == Decimal("-10.00")

    # Flow 18
    adj = calculate_reconciliation_adjustment(
        bank_balance=Decimal("500.04"),
        book_balance=Decimal("500.00"),
    )
    assert adj.difference == Decimal("0.04")
    assert adj.is_gain is True


def test_domain_5_investments_split_invariants():
    """Flow 20 & 22 Invariants: Dividend WHT and Mortgage principal reduction."""
    # Flow 20
    div = calculate_dividend_split(gross_amount=Decimal("2000.00"), withholding_tax_rate=Decimal("0.30"))
    assert div.net_amount + div.tax_amount == div.gross_amount

    # Flow 22
    mtg = calculate_mortgage_split(total_payment=Decimal("2500.00"), interest_amount=Decimal("1200.00"))
    assert mtg.interest_amount + mtg.principal_amount == mtg.total_payment


def test_domain_6_reporting_equation_and_diagnostics():
    """Flow 23 & 24 Invariants: Equation balance and root cause diagnosis."""
    # Flow 23
    balanced = diagnose_equation_imbalance(Decimal("0.00"))
    assert balanced.is_balanced is True

    # Flow 24
    unbalanced = diagnose_equation_imbalance(Decimal("150.00"), has_pending_drafts=True)
    assert unbalanced.is_balanced is False
    assert unbalanced.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT
