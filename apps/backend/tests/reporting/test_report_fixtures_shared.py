from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.reporting import generate_balance_sheet
from tests.reporting._report_fixtures import STANDARD_CHART_SPEC, build_standard_chart_of_accounts, post_pair


async def test_report_fixtures_shared(db: AsyncSession, test_user_id) -> None:
    accounts = await build_standard_chart_of_accounts(db, test_user_id)
    assert [(a.name, a.type) for a in accounts] == list(STANDARD_CHART_SPEC)
    assert all(a.id is not None and a.currency == "SGD" for a in accounts)
    assert [a.type for a in accounts] == [
        AccountType.ASSET,
        AccountType.LIABILITY,
        AccountType.EQUITY,
        AccountType.INCOME,
        AccountType.EXPENSE,
    ]
    cash, _liability, equity, *_rest = accounts
    await post_pair(db, test_user_id, date.today(), "Owner contribution", cash, equity, "1000.00", commit=True)
    report = await generate_balance_sheet(db, test_user_id, as_of_date=date.today(), currency="SGD")
    assert (report["total_assets"], report["total_equity"], report["is_balanced"]) == (
        Decimal("1000.00"),
        Decimal("1000.00"),
        True,
    )
