from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType, Direction
from src.reporting import EquationDiagnosticCategory, diagnose_equation_imbalance, run_balance_sheet_diagnostics
from tests.reporting._report_fixtures import make_entry, seed_accounts


@pytest.mark.parametrize(
    ("delta", "drafts", "multi", "expected_bal", "expected_cat", "action_contains", "action_excludes"),
    [
        (Decimal("0.00"), 0, False, True, EquationDiagnosticCategory.BALANCED, None, None),
        (Decimal("-150.00"), 2, False, False, EquationDiagnosticCategory.UNPOSTED_DRAFT, "pending statement", None),
        (
            Decimal("0.04"),
            0,
            True,
            False,
            EquationDiagnosticCategory.FX_ROUNDING_DRIFT,
            "POST /reconciliation/adjustments",
            "revaluation",
        ),
        (Decimal("12.50"), 0, True, False, EquationDiagnosticCategory.UNKNOWN_DISCREPANCY, None, None),
    ],
)
def test_flow_24_diagnostics_categories(
    delta: Decimal,
    drafts: int,
    multi: bool,
    expected_bal: bool,
    expected_cat: EquationDiagnosticCategory,
    action_contains: str | None,
    action_excludes: str | None,
) -> None:
    res = diagnose_equation_imbalance(equation_delta=delta, unposted_draft_count=drafts, is_multicurrency=multi)
    assert (res.is_balanced, res.primary_category, res.equation_delta) == (expected_bal, expected_cat, delta)
    if action_contains:
        assert action_contains.lower() in res.suggested_action.lower()
    if action_excludes:
        assert action_excludes not in res.suggested_action.lower()
    if expected_cat is EquationDiagnosticCategory.UNKNOWN_DISCREPANCY:
        assert res.details == {"delta": str(delta)}


async def test_AC_reporting_2664_1_balanced_usd_entry_without_fx_rate_row_never_reports_unclassified_discrepancy(
    client: AsyncClient, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.pricing.extension.market_data.service as md_service

    bank, equity = await seed_accounts(
        db, test_user.id, ("DBS Savings", AccountType.ASSET), ("Opening Balance", AccountType.EQUITY)
    )
    db.add(
        make_entry(
            test_user.id,
            date(2026, 10, 24),
            "USD opening",
            [
                (bank, Direction.DEBIT, "500.00", "USD", Decimal("1.35")),
                (equity, Direction.CREDIT, "500.00", "USD", Decimal("1.35")),
            ],
        )
    )
    await db.commit()

    monkeypatch.setattr(
        md_service,
        "resolve_missing_fx_rate",
        lambda _db, base, quote, _d: _async_val(
            Decimal("1.27832") if (base.upper(), quote.upper()) == ("USD", "SGD") else None
        ),
    )
    diag = await run_balance_sheet_diagnostics(db, test_user.id, as_of_date=date(2026, 10, 24), currency="SGD")
    assert (
        diag.is_balanced is True
        and diag.equation_delta == Decimal("0.00")
        and "Unclassified discrepancy" not in diag.suggested_action
    )

    dq_resp = await client.get("/reports/data-quality?as_of_date=2026-10-24&currency=SGD")
    assert dq_resp.status_code == 200
    dq_body = dq_resp.json()
    assert dq_body["equation_invariant"]["is_healthy"] is True and Decimal(
        str(dq_body["equation_invariant"]["delta"])
    ) == Decimal("0.00")
    assert all("Unclassified discrepancy" not in item["description"] for item in dq_body["action_items"])

    monkeypatch.setattr(md_service, "resolve_missing_fx_rate", lambda *_a: _async_val(None))
    db.add(
        make_entry(
            test_user.id,
            date(2026, 10, 24),
            "Mixed",
            [(bank, Direction.DEBIT, "500.00", "USD", Decimal("1.35")), (equity, Direction.CREDIT, "675.00", "SGD")],
        )
    )
    await db.commit()
    diag_missing = await run_balance_sheet_diagnostics(db, test_user.id, as_of_date=date(2026, 10, 24), currency="SGD")
    assert diag_missing.primary_category == EquationDiagnosticCategory.FX_ROUNDING_DRIFT
    assert (
        "USD/SGD" in diag_missing.suggested_action and "Unclassified discrepancy" not in diag_missing.suggested_action
    )


async def _async_val(val):
    return val
