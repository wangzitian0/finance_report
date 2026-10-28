"""TDD Test Suite for Flow 24: Accounting Equation Out-of-Balance Diagnostic Triage.

Verifies that when a Balance Sheet exhibits an equation delta (|delta| >= 0.01),
the diagnostic engine categorizes the root cause into one of the produced buckets:
1. UNPOSTED_DRAFT: Pending/unapproved statements altering cash positions
2. FX_ROUNDING_DRIFT: Multi-currency penny translation discrepancies
3. UNKNOWN_DISCREPANCY: Any other non-zero delta
"""

from decimal import Decimal

from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
)


def test_flow_24_diagnostics_balanced():
    """Flow 24: Balanced sheet returns BALANCED category with no corrective actions."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("0.00"),
        is_multicurrency=False,
    )
    assert result.is_balanced is True
    assert result.primary_category == EquationDiagnosticCategory.BALANCED
    assert result.equation_delta == Decimal("0.00")


def test_flow_24_diagnostics_unposted_draft():
    """Flow 24: Pending drafts identified as highest-priority diagnostic culprit."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("-150.00"),
        unposted_draft_count=2,
        is_multicurrency=False,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT
    assert "pending statement" in result.suggested_action.lower()


def test_flow_24_diagnostics_fx_rounding_drift():
    """Flow 24: Immaterial delta on multicurrency book classified as FX rounding drift."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("0.04"),
        is_multicurrency=True,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.FX_ROUNDING_DRIFT
    # The advice names only an action a user can run: the penny adjustment endpoint (Flow 18).
    # No job or route books a revaluation entry (#2774), so the text must not tell the user to trigger one.
    assert "revaluation" not in result.suggested_action.lower()
    assert "POST /reconciliation/adjustment" in result.suggested_action


def test_flow_24_diagnostics_unknown_discrepancy():
    """Flow 24: A delta above the FX drift threshold with no pending drafts stays unexplained."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("12.50"),
        is_multicurrency=True,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.UNKNOWN_DISCREPANCY
    assert result.details == {"delta": "12.50"}


def test_flow_24_every_category_is_produced_by_the_diagnosis():
    """Flow 24: the enum holds only categories that diagnose_equation_imbalance can return."""
    produced = {
        diagnose_equation_imbalance(Decimal("0.00")).primary_category,
        diagnose_equation_imbalance(Decimal("-150.00"), unposted_draft_count=2).primary_category,
        diagnose_equation_imbalance(Decimal("0.04"), is_multicurrency=True).primary_category,
        diagnose_equation_imbalance(Decimal("12.50"), is_multicurrency=True).primary_category,
    }
    assert produced == set(EquationDiagnosticCategory)
