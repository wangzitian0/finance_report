from datetime import date
from decimal import Decimal

import pytest

from src.ledger import AccountType, Direction
from src.reporting import generate_balance_sheet
from src.reporting.base.balance_sheet_calculator import absorb_translation_rounding
from src.reporting.extension import balance_sheet as balance_sheet_module
from tests.reporting._report_fixtures import make_entry, make_pair_entry, seed_accounts, seed_fx_rates

USD_MID = "1.319330"
HKD_MID = "0.171500"


async def _seed_case_4_shape(db, user_id) -> None:
    cash_sgd, cash_usd, cash_hkd, capital, inc_sgd, inc_usd, inc_hkd = await seed_accounts(
        db,
        user_id,
        ("DBS SGD", AccountType.ASSET, "SGD"),
        ("SVB USD", AccountType.ASSET, "USD"),
        ("HSBC HKD", AccountType.ASSET, "HKD"),
        ("Opening Balance Equity", AccountType.EQUITY, "SGD"),
        ("Income SGD", AccountType.INCOME, "SGD"),
        ("Income USD", AccountType.INCOME, "USD"),
        ("Income HKD", AccountType.INCOME, "HKD"),
    )
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.343920", date(2025, 4, 1)),
        ("USD", "SGD", USD_MID, date(2025, 4, 15)),
        ("USD", "SGD", "1.305640", date(2025, 4, 30)),
        ("HKD", "SGD", "0.172706", date(2025, 4, 1)),
        ("HKD", "SGD", HKD_MID, date(2025, 4, 15)),
        ("HKD", "SGD", "0.169139", date(2025, 4, 30)),
        commit=False,
    )
    db.add_all(
        [
            make_pair_entry(user_id, date(2025, 4, 1), "Opening SGD", cash_sgd, capital, "10000.00"),
            make_entry(
                user_id,
                date(2025, 4, 1),
                "Opening USD",
                [
                    (cash_usd, Direction.DEBIT, "5000.00", "USD", Decimal("1.343920")),
                    (capital, Direction.CREDIT, "6719.60", "SGD", Decimal("1.343920")),
                ],
            ),
            make_entry(
                user_id,
                date(2025, 4, 1),
                "Opening HKD",
                [
                    (cash_hkd, Direction.DEBIT, "20000.00", "HKD", Decimal("0.172706")),
                    (capital, Direction.CREDIT, "3454.12", "SGD", Decimal("0.172706")),
                ],
            ),
            make_pair_entry(user_id, date(2025, 4, 10), "SGD income", cash_sgd, inc_sgd, "2800.00"),
            make_pair_entry(
                user_id,
                date(2025, 4, 10),
                "USD income",
                cash_usd,
                inc_usd,
                "1800.00",
                currency="USD",
                fx_rate=Decimal(USD_MID),
            ),
            make_pair_entry(
                user_id,
                date(2025, 4, 10),
                "HKD income",
                cash_hkd,
                inc_hkd,
                "4000.00",
                currency="HKD",
                fx_rate=Decimal(HKD_MID),
            ),
        ]
    )
    await db.commit()


async def test_case_4_shape_translation_rounding_absorption(db, test_user_id, monkeypatch: pytest.MonkeyPatch) -> None:
    await _seed_case_4_shape(db, test_user_id)
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    assert (bs["total_assets"], bs["equation_delta"], bs["is_balanced"]) == (Decimal("25737.69"), Decimal("0.00"), True)
    monkeypatch.setattr(balance_sheet_module, "absorb_translation_rounding", lambda **kw: kw["cta_adjustment"])
    raw = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    assert raw["equation_delta"] == Decimal("0.01")
    assert bs["cta_adjustment"] == raw["cta_adjustment"] + Decimal("0.01")


@pytest.mark.parametrize(
    ("cta", "residual", "count", "expected"),
    [
        (Decimal("9.77"), Decimal("0.01"), 7, Decimal("9.78")),
        (Decimal("9.77"), Decimal("-0.01"), 7, Decimal("9.76")),
        (Decimal("9.77"), Decimal("0.00"), 7, Decimal("9.77")),
        (Decimal("9.77"), Decimal("0.04"), 7, Decimal("9.77")),
        (Decimal("9.77"), Decimal("-0.04"), 7, Decimal("9.77")),
        (Decimal("9.77"), Decimal("0.50"), 7, Decimal("9.77")),
        (Decimal("9.77"), Decimal("100.00"), 7, Decimal("9.77")),
        (Decimal("1.00"), Decimal("0.03"), 4, Decimal("1.00")),
        (Decimal("1.00"), Decimal("0.03"), 8, Decimal("1.03")),
    ],
)
def test_absorb_translation_rounding_bounds(cta: Decimal, residual: Decimal, count: int, expected: Decimal) -> None:
    assert absorb_translation_rounding(cta_adjustment=cta, residual=residual, rounded_figure_count=count) == expected
