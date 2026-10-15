"""AC-reporting.balance-sheet.8: a translation rounding residual goes to the CTA reserve (#2473).

Account lines round to the cent one by one. Net income, unrealized FX and CTA round
from unrounded sums. The two sides can differ by a cent, so the equation delta must not
show it. A residual above the rounding bound is a real imbalance and stays visible.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.ledger import AccountType, Direction
from src.reporting import generate_balance_sheet
from src.reporting.base.balance_sheet_calculator import absorb_translation_rounding
from src.reporting.extension import balance_sheet as balance_sheet_module
from tests.reporting.test_bench_articulation_matrix import (
    _pair_entry,
    _post_entry,
    _seed_accounts,
    _seed_fx_rates,
)

USD_MID = "1.319330"
HKD_MID = "0.171500"


async def _seed_case_4_shape(db, user_id) -> None:
    """Bench V2 Case 4 shape: SGD, USD and HKD accounts with moving rates in April 2025.

    Closing assets are 12800.00 SGD, 6800 USD and 24000 HKD. Their SGD lines are
    12800.00, 8878.35 and 4059.34, so total assets are 25737.69.
    """
    cash_sgd, cash_usd, cash_hkd, capital, inc_sgd, inc_usd, inc_hkd = await _seed_accounts(
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
    await _seed_fx_rates(
        db,
        ("USD", "SGD", "1.343920", date(2025, 4, 1)),
        ("USD", "SGD", USD_MID, date(2025, 4, 15)),
        ("USD", "SGD", "1.305640", date(2025, 4, 30)),
        ("HKD", "SGD", "0.172706", date(2025, 4, 1)),
        ("HKD", "SGD", HKD_MID, date(2025, 4, 15)),
        ("HKD", "SGD", "0.169139", date(2025, 4, 30)),
    )
    db.add_all(
        [
            _pair_entry(user_id, date(2025, 4, 1), "Opening SGD", cash_sgd, capital, "10000.00"),
            _post_entry(
                user_id,
                date(2025, 4, 1),
                "Opening USD",
                [
                    (cash_usd, Direction.DEBIT, Decimal("5000.00"), "USD"),
                    (capital, Direction.CREDIT, Decimal("6719.60"), "SGD"),
                ],
                fx_rate=Decimal("1.343920"),
            ),
            _post_entry(
                user_id,
                date(2025, 4, 1),
                "Opening HKD",
                [
                    (cash_hkd, Direction.DEBIT, Decimal("20000.00"), "HKD"),
                    (capital, Direction.CREDIT, Decimal("3454.12"), "SGD"),
                ],
                fx_rate=Decimal("0.172706"),
            ),
            _pair_entry(user_id, date(2025, 4, 10), "SGD income", cash_sgd, inc_sgd, "2800.00"),
            _pair_entry(
                user_id, date(2025, 4, 10), "USD income", cash_usd, inc_usd, "1800.00", "USD", Decimal(USD_MID)
            ),
            _pair_entry(
                user_id, date(2025, 4, 10), "HKD income", cash_hkd, inc_hkd, "4000.00", "HKD", Decimal(HKD_MID)
            ),
        ]
    )
    await db.commit()


async def test_case_4_shape_balance_sheet_equation_delta_is_exactly_zero(db, test_user_id) -> None:
    await _seed_case_4_shape(db, test_user_id)

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")

    assert bs["total_assets"] == Decimal("25737.69")
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["is_balanced"] is True


async def test_case_4_shape_has_a_one_cent_residual_before_absorption(
    db, test_user_id, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard of the scenario: without the absorption the same books show a 0.01 delta."""
    await _seed_case_4_shape(db, test_user_id)
    with_absorption = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    monkeypatch.setattr(balance_sheet_module, "absorb_translation_rounding", lambda **kw: kw["cta_adjustment"])

    without_absorption = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")

    assert without_absorption["equation_delta"] == Decimal("0.01")
    assert with_absorption["cta_adjustment"] == without_absorption["cta_adjustment"] + Decimal("0.01")


@pytest.mark.parametrize(
    ("residual", "expected_cta"),
    [
        (Decimal("0.01"), Decimal("9.78")),
        (Decimal("-0.01"), Decimal("9.76")),
        (Decimal("0.00"), Decimal("9.77")),
    ],
)
def test_residual_inside_the_rounding_bound_moves_into_cta(residual: Decimal, expected_cta: Decimal) -> None:
    result = absorb_translation_rounding(cta_adjustment=Decimal("9.77"), residual=residual, rounded_figure_count=7)

    assert result == expected_cta


@pytest.mark.parametrize("residual", [Decimal("0.04"), Decimal("-0.04"), Decimal("0.50"), Decimal("100.00")])
def test_residual_above_the_rounding_bound_stays_visible(residual: Decimal) -> None:
    # Bound for 7 figures is 7 x 0.005 = 0.035.
    result = absorb_translation_rounding(cta_adjustment=Decimal("9.77"), residual=residual, rounded_figure_count=7)

    assert result == Decimal("9.77")


def test_rounding_bound_grows_with_the_number_of_rounded_figures() -> None:
    few = absorb_translation_rounding(cta_adjustment=Decimal("1.00"), residual=Decimal("0.03"), rounded_figure_count=4)
    many = absorb_translation_rounding(cta_adjustment=Decimal("1.00"), residual=Decimal("0.03"), rounded_figure_count=8)

    assert few == Decimal("1.00")
    assert many == Decimal("1.03")
