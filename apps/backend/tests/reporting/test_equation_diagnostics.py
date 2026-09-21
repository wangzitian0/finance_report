"""TDD Test Suite for Flow 24: Accounting Equation Out-of-Balance Diagnostic Triage.

Verifies that when a Balance Sheet exhibits an equation delta (|delta| >= 0.01),
the diagnostic engine categorizes the root cause into one of the canonical buckets:
1. UNPOSTED_DRAFT: Pending/unapproved statements altering cash positions
2. ONE_SIDED_ENTRY: Malformed journal entries with unequal debits and credits
3. UNCLASSIFIED_ACCOUNT: Accounts missing standard accounting categorization
4. FX_ROUNDING_DRIFT: Multi-currency penny translation discrepancies
"""

from decimal import Decimal

from src.reporting.diagnostics import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
)


def test_flow_24_diagnostics_balanced():
    """Flow 24: Balanced sheet returns BALANCED category with no corrective actions."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("0.00"),
        has_pending_drafts=False,
        has_one_sided_entries=False,
        has_unclassified_accounts=False,
        is_multicurrency=False,
    )
    assert result.is_balanced is True
    assert result.primary_category == EquationDiagnosticCategory.BALANCED
    assert result.equation_delta == Decimal("0.00")


def test_flow_24_diagnostics_unposted_draft():
    """Flow 24: Pending drafts identified as highest-priority diagnostic culprit."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("-150.00"),
        has_pending_drafts=True,
        has_one_sided_entries=False,
        has_unclassified_accounts=False,
        is_multicurrency=False,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT
    assert "pending statement" in result.suggested_action.lower()


def test_flow_24_diagnostics_one_sided_entry():
    """Flow 24: Unbalanced journal entry detected as root cause."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("50.00"),
        has_pending_drafts=False,
        has_one_sided_entries=True,
        has_unclassified_accounts=False,
        is_multicurrency=False,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.ONE_SIDED_ENTRY
    assert "journal entry" in result.suggested_action.lower()


def test_flow_24_diagnostics_unclassified_account():
    """Flow 24: Unclassified accounts identified when accounts lack accounting types."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("200.00"),
        has_pending_drafts=False,
        has_one_sided_entries=False,
        has_unclassified_accounts=True,
        is_multicurrency=False,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.UNCLASSIFIED_ACCOUNT
    assert "chart of accounts" in result.suggested_action.lower()


def test_flow_24_diagnostics_fx_rounding_drift():
    """Flow 24: Immaterial delta on multicurrency book classified as FX rounding drift."""
    result = diagnose_equation_imbalance(
        equation_delta=Decimal("0.04"),
        has_pending_drafts=False,
        has_one_sided_entries=False,
        has_unclassified_accounts=False,
        is_multicurrency=True,
    )
    assert result.is_balanced is False
    assert result.primary_category == EquationDiagnosticCategory.FX_ROUNDING_DRIFT
    assert "fx revaluation" in result.suggested_action.lower()
