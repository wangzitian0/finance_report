"""Accounting equation out-of-balance diagnostic triage domain services (Flow 24)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select

from src.audit.money import to_money
from src.reporting.base.diagnostics import EquationDiagnosticCategory, EquationDiagnosticResult

__all__ = [
    "diagnose_equation_imbalance",
    "run_balance_sheet_diagnostics",
]

EPSILON = Decimal("0.01")
FX_DRIFT_THRESHOLD = Decimal("0.10")


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
    delta = to_money(equation_delta)
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


async def run_balance_sheet_diagnostics(
    db: Any,
    user_id: Any,
    *,
    as_of_date: date | None = None,
    currency: str | None = None,
    include_restricted: bool = False,
) -> EquationDiagnosticResult:
    """Execute end-to-end accounting equation diagnostics against ledger & statements."""
    from src.extraction import BankStatementStatus, StatementSummary
    from src.ledger import Account
    from src.reporting.extension.balance_sheet import generate_balance_sheet

    report_date = as_of_date or date.today()
    report = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=report_date,
        currency=currency,
        include_restricted=include_restricted,
    )
    pending_count = (
        await db.scalar(
            select(func.count(StatementSummary.id))
            .where(StatementSummary.user_id == user_id)
            .where(
                StatementSummary.status.in_(
                    [
                        BankStatementStatus.UPLOADED,
                        BankStatementStatus.PARSING,
                        BankStatementStatus.PARSED,
                    ]
                )
            )
        )
        or 0
    )
    unclassified_count = (
        await db.scalar(select(func.count(Account.id)).where(Account.user_id == user_id).where(Account.type.is_(None)))
        or 0
    )
    currency_count = (
        await db.scalar(select(func.count(func.distinct(Account.currency))).where(Account.user_id == user_id)) or 0
    )
    return diagnose_equation_imbalance(
        equation_delta=cast(Decimal, report.get("equation_delta", Decimal("0.00"))),
        has_pending_drafts=pending_count > 0,
        unposted_draft_count=pending_count,
        has_unclassified_accounts=unclassified_count > 0,
        unclassified_account_count=unclassified_count,
        is_multicurrency=currency_count > 1 or bool(report.get("fx_warnings")),
    )
