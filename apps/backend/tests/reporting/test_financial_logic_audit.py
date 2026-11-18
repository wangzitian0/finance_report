from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import TraceDecisionRef, VersionedTraceRef
from src.extraction.base.result import StatementSourceType
from src.ledger import AccountType
from src.reporting import generate_cash_flow
from src.reporting.base.package_contribution import PackageSectionContribution
from src.reporting.extension.package_document import _cash_inputs_from_contributions
from tests.reporting._report_fixtures import post_pair, seed_accounts


async def test_AC5_10_and_package_doc_8_cash_flow_balances_signs_and_cash_inputs(db: AsyncSession, test_user) -> None:
    cash, equity, rent = await seed_accounts(
        db,
        test_user.id,
        ("Cash", AccountType.ASSET),
        ("Owner Equity", AccountType.EQUITY),
        ("Rent Expense", AccountType.EXPENSE),
    )
    await post_pair(db, test_user.id, date(2025, 12, 31), "Opening capital", cash, equity, "1000.00")
    await post_pair(db, test_user.id, date(2026, 1, 15), "January rent", rent, cash, "100.00", commit=True)

    rep = await generate_cash_flow(
        db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )
    assert (
        rep["summary"]["beginning_cash"],
        rep["summary"]["ending_cash"],
        rep["summary"]["net_cash_flow"],
        rep["summary"]["operating_activities"],
        rep["operating"][0]["amount"],
    ) == (Decimal("1000.00"), Decimal("900.00"), Decimal("-100.00"), Decimal("-100.00"), Decimal("-100.00"))

    cash.name = "DBS"
    await db.commit()

    contrib = PackageSectionContribution(
        contribution_type="statement_source",
        section_ids=("balance_sheet", "cash_flow", "traceability_appendix"),
        payload=SimpleNamespace(
            statement_id=uuid4(),
            source_result=SimpleNamespace(source_type=StatementSourceType.BANK),
            account_id=cash.id,
        ),
        state="authoritative",
        decision=TraceDecisionRef(
            decision_id=uuid4(),
            target=VersionedTraceRef("statement_extraction_result", "fixture", "v1"),
            assertion=VersionedTraceRef("extraction_authority", "fixture", "v1"),
        ),
        input_refs=(f"account:{cash.id}",),
        reason_code=None,
    )
    cash_inputs = _cash_inputs_from_contributions((contrib,))
    assert cash_inputs.is_complete and cash_inputs.account_ids == frozenset({cash.id})
    scoped = await generate_cash_flow(
        db,
        test_user.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        cash_account_ids=cash_inputs.account_ids,
        currency="SGD",
    )
    assert (scoped["summary"]["beginning_cash"], scoped["summary"]["ending_cash"]) == (
        Decimal("1000.00"),
        Decimal("900.00"),
    )
    assert all(item["account_id"] != cash.id for item in scoped["investing"])
