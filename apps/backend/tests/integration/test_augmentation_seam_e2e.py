from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration
from src.audit import JournalEntrySourceType
from src.identity import User
from src.ledger import AccountType, post_journal_entry
from src.pricing import ManualValuationComponentType, ValuationService
from src.reporting import generate_balance_sheet
from tests.factories import AccountFactory
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry


async def test_augmentation_seam_excludes_superseded_without_source_assurance(
    db: AsyncSession, test_user: User
) -> None:
    uid, as_of, service = test_user.id, date(2026, 5, 31), ValuationService()
    cash = await AccountFactory.create_async(db, user_id=uid, name="Cash", type=AccountType.ASSET)
    equity = await AccountFactory.create_async(db, user_id=uid, name="Opening Equity", type=AccountType.EQUITY)
    salary = await AccountFactory.create_async(db, user_id=uid, name="Salary", type=AccountType.INCOME)
    for edate, memo, credit, amt, src_type in (
        (date(2026, 5, 1), "Opening capital", equity, Decimal("1000.00"), JournalEntrySourceType.MANUAL),
        (date(2026, 5, 10), "Auto-parsed deposit", salary, Decimal("500.00"), JournalEntrySourceType.AUTO_PARSED),
    ):
        entry = await create_journal_entry(
            db=db,
            user_id=uid,
            entry_date=edate,
            memo=memo,
            lines_data=[
                {"account_id": cash.id, "direction": "DEBIT", "amount": amt, "currency": "SGD"},
                {"account_id": credit.id, "direction": "CREDIT", "amount": amt, "currency": "SGD"},
            ],
            source_type=src_type,
        )
        await post_journal_entry(db, entry.id, uid)

    vkey = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=as_of,
        currency="SGD",
        source="manual appraisal",
    )
    await service.create_valuation_snapshot(db, user_id=uid, value=Decimal("1000000.00"), **vkey)
    await service.create_valuation_snapshot(db, user_id=uid, value=Decimal("1100000.00"), **vkey)
    await db.commit()

    bs = await generate_balance_sheet(db, uid, as_of_date=as_of, currency="SGD")
    asset_lines = {line["name"]: line for line in bs["assets"]}
    components = await service.get_latest_valuation_components(db, uid, as_of_date=as_of)
    assert (
        bs["total_assets"],
        bs["equation_delta"],
        bs["is_balanced"],
        Decimal(str(asset_lines["Cash"]["amount"])),
        components.total_assets,
    ) == (Decimal("1101500.00"), Decimal("0.00"), True, Decimal("1500.00"), Decimal("1100000.00"))
    assert "confidence_tier" not in asset_lines["Cash"]
