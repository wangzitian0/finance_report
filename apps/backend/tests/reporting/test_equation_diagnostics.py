"""TDD Test Suite for Flow 24: Accounting Equation Out-of-Balance Diagnostic Triage.

Verifies that when a Balance Sheet exhibits an equation delta (|delta| >= 0.01),
the diagnostic engine categorizes the root cause into one of the produced buckets:
1. UNPOSTED_DRAFT: Pending/unapproved statements altering cash positions
2. FX_ROUNDING_DRIFT: Multi-currency penny translation discrepancies
3. UNKNOWN_DISCREPANCY: Any other non-zero delta
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
    run_balance_sheet_diagnostics,
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


@pytest.mark.asyncio
async def test_AC_reporting_2664_1_balanced_usd_entry_without_fx_rate_row_never_reports_unclassified_discrepancy(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-reporting.2664.1: a balanced USD entry with entry fx_rate=1.35 and no stored FxRate row either balances or reports a named missing-rate cause (#2664)."""
    import src.pricing.extension.market_data.service as md_service

    bank = Account(user_id=test_user.id, name="DBS Savings", type=AccountType.ASSET, currency="SGD")
    equity = Account(user_id=test_user.id, name="Opening Balance", type=AccountType.EQUITY, currency="SGD")
    db.add_all([bank, equity])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 10, 24),
        memo="USD opening contribution",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("500.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
        ]
    )
    await db.commit()

    # Path A: lazy_load resolves a spot rate (e.g. 1.27832 != 1.35) when no FxRate row is pre-seeded.
    async def resolve_spot(_db, base: str, quote: str, _rate_date: date) -> Decimal | None:
        if (base.upper(), quote.upper()) == ("USD", "SGD"):
            return Decimal("1.27832")
        return None

    monkeypatch.setattr(md_service, "resolve_missing_fx_rate", resolve_spot)
    diag_with_lazy_spot = await run_balance_sheet_diagnostics(
        db, test_user.id, as_of_date=date(2026, 10, 24), currency="SGD"
    )
    assert "Unclassified discrepancy" not in diag_with_lazy_spot.suggested_action
    assert diag_with_lazy_spot.is_balanced is True
    assert diag_with_lazy_spot.equation_delta == Decimal("0.00")

    dq_resp = await client.get("/reports/data-quality?as_of_date=2026-10-24&currency=SGD")
    assert dq_resp.status_code == 200
    dq_body = dq_resp.json()
    assert dq_body["equation_invariant"]["is_healthy"] is True
    assert Decimal(str(dq_body["equation_invariant"]["delta"])) == Decimal("0.00")
    assert all("Unclassified discrepancy" not in item["description"] for item in dq_body["action_items"])

    # Path B: no FxRate row and lazy_load finds no rate on a mixed USD/SGD balanced entry.
    async def resolve_none(_db, _base: str, _quote: str, _rate_date: date) -> Decimal | None:
        return None

    monkeypatch.setattr(md_service, "resolve_missing_fx_rate", resolve_none)
    mixed_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 10, 24),
        memo="USD asset funded by SGD equity",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(mixed_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=mixed_entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("500.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
            JournalLine(
                journal_entry_id=mixed_entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("675.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    diag_missing = await run_balance_sheet_diagnostics(db, test_user.id, as_of_date=date(2026, 10, 24), currency="SGD")
    assert "Unclassified discrepancy" not in diag_missing.suggested_action
    assert "USD/SGD" in diag_missing.suggested_action
    assert diag_missing.primary_category == EquationDiagnosticCategory.FX_ROUNDING_DRIFT
