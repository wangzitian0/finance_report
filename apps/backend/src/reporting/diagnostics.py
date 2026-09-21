"""Accounting equation out-of-balance diagnostic triage (Flow 24).

When an equation delta (|Assets - (Liabilities + Equity + PnL)| >= 0.01) is observed,
this module diagnoses the discrepancy into 4 actionable root cause categories:
1. UNPOSTED_DRAFT: Unapproved/pending statements altering physical cash balances.
2. ONE_SIDED_ENTRY: Unbalanced journal entry (debit != credit).
3. UNCLASSIFIED_ACCOUNT: Accounts missing standard accounting categorization.
4. FX_ROUNDING_DRIFT: Multi-currency fractional cent translation rounding.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EquationDiagnosticCategory",
    "EquationDiagnosticResult",
    "diagnose_equation_imbalance",
]

ZERO = Decimal("0.00")
EPSILON = Decimal("0.01")
FX_DRIFT_THRESHOLD = Decimal("0.10")


class EquationDiagnosticCategory(str, Enum):
    """Categorized root causes for accounting equation imbalance."""

    BALANCED = "balanced"
    UNPOSTED_DRAFT = "unposted_draft"
    ONE_SIDED_ENTRY = "one_sided_entry"
    UNCLASSIFIED_ACCOUNT = "unclassified_account"
    FX_ROUNDING_DRIFT = "fx_rounding_drift"
    UNKNOWN_DISCREPANCY = "unknown_discrepancy"


class EquationDiagnosticResult(BaseModel):
    """Structured diagnostic evaluation of accounting equation state."""

    model_config = ConfigDict(frozen=True)

    is_balanced: bool
    equation_delta: Decimal
    primary_category: EquationDiagnosticCategory
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: str
    details: dict[str, Any] = Field(default_factory=dict)


def diagnose_equation_imbalance(
    equation_delta: Decimal,
    has_pending_drafts: bool = False,
    has_one_sided_entries: bool = False,
    has_unclassified_accounts: bool = False,
    is_multicurrency: bool = False,
    unposted_draft_count: int = 0,
    unclassified_account_count: int = 0,
) -> EquationDiagnosticResult:
    """Diagnose an accounting equation delta into an actionable cause."""
    delta = equation_delta.quantize(Decimal("0.01"))
    abs_delta = abs(delta)

    if abs_delta < EPSILON:
        return EquationDiagnosticResult(
            is_balanced=True,
            equation_delta=delta,
            primary_category=EquationDiagnosticCategory.BALANCED,
            confidence=1.0,
            suggested_action="Accounting equation is strictly balanced. No action required.",
            details={"status": "balanced"},
        )

    # 1. Unposted drafts
    if has_pending_drafts or unposted_draft_count > 0:
        return EquationDiagnosticResult(
            is_balanced=False,
            equation_delta=delta,
            primary_category=EquationDiagnosticCategory.UNPOSTED_DRAFT,
            confidence=0.95,
            suggested_action=(
                f"Review and approve or reject pending statement(s) ({unposted_draft_count} pending) "
                "before generating final balance sheet."
            ),
            details={"pending_count": unposted_draft_count},
        )

    # 2. One-sided or unbalanced manual journal entries
    if has_one_sided_entries:
        return EquationDiagnosticResult(
            is_balanced=False,
            equation_delta=delta,
            primary_category=EquationDiagnosticCategory.ONE_SIDED_ENTRY,
            confidence=0.98,
            suggested_action=(
                f"An unbalanced journal entry exists (delta: {delta}). "
                "Review manual journal vouchers to ensure total debits equal total credits."
            ),
            details={"imbalance": str(delta)},
        )

    # 3. Unclassified accounts lacking accounting classification
    if has_unclassified_accounts or unclassified_account_count > 0:
        return EquationDiagnosticResult(
            is_balanced=False,
            equation_delta=delta,
            primary_category=EquationDiagnosticCategory.UNCLASSIFIED_ACCOUNT,
            confidence=0.90,
            suggested_action=(
                "Update Chart of Accounts to ensure all active accounts have a defined "
                "Asset, Liability, or Equity classification."
            ),
            details={"unclassified_count": unclassified_account_count},
        )

    # 4. Multi-currency rounding drift
    if is_multicurrency and abs_delta <= FX_DRIFT_THRESHOLD:
        return EquationDiagnosticResult(
            is_balanced=False,
            equation_delta=delta,
            primary_category=EquationDiagnosticCategory.FX_ROUNDING_DRIFT,
            confidence=0.85,
            suggested_action=(
                f"Multi-currency conversion created a penny drift of {delta}. "
                "Trigger FX revaluation or record an immaterial rounding adjustment."
            ),
            details={"is_multicurrency": True, "threshold": str(FX_DRIFT_THRESHOLD)},
        )

    # 5. Default/Unknown discrepancy
    return EquationDiagnosticResult(
        is_balanced=False,
        equation_delta=delta,
        primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
        confidence=0.50,
        suggested_action=(f"Unclassified discrepancy of {delta} detected. Run audit ledger verification."),
        details={"delta": str(delta)},
    )
