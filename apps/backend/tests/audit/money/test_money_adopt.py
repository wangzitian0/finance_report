from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit.money import Currency, CurrencyMismatchError, Money
from src.audit.money.adopt import balance_check
from src.extraction.base.validation import validate_balance_per_currency
from src.extraction.orm.statement_summary import StatementSummary
from src.reconciliation.extension.fx_transfer import TransferLeg

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(("opening", "closing", "net", "currency"), [(Decimal("100"), Decimal("150"), Decimal("50"), "USD"), (Decimal("100"), Decimal("151"), Decimal("50"), "SGD"), (Decimal("0"), Decimal("0"), Decimal("0"), "*"), (Decimal("10"), Decimal("20"), Decimal("9"), "BTC"), (Decimal("10"), Decimal("19"), Decimal("9"), None)])
def test_AC2_22_2_balance_check_is_byte_identical(opening, closing, net, currency) -> None:
    expected_legacy = opening + net
    assert balance_check(opening, closing, net, currency) == (expected_legacy, abs(closing - expected_legacy))


def test_AC2_22_money_adoption_boundaries() -> None:
    result = validate_balance_per_currency(
        {
            "balances": [{"currency": "USD", "opening": "100.00", "closing": "150.00"}, {"currency": "SGD", "opening": "200.00", "closing": "250.00"}, {"currency": "BTC", "opening": "1.00", "closing": "3.00"}],
            "transactions": [{"amount": "50.00", "direction": "IN", "currency": "USD"}, {"amount": "50.00", "direction": "IN", "currency": "SGD"}, {"amount": "2.00", "direction": "IN", "currency": "BTC"}],
        }
    )
    by_ccy, now = {r["currency"]: r for r in result["per_currency"]}, datetime.now(UTC)
    leg = TransferLeg(user_id=uuid4(), account_id=uuid4(), direction="OUT", amount=Decimal("100.00"), currency="usd", occurred_at=now)
    other = TransferLeg(user_id=uuid4(), account_id=uuid4(), direction="IN", amount=Decimal("135.00"), currency="SGD", occurred_at=now)
    stmt = StatementSummary()
    stmt.currency_balances = [{"currency": "USD", "opening": "100.00", "closing": "150.00"}, {"currency": "SGD", "opening": "200.00", "closing": "250.00"}]
    balances = stmt.typed_currency_balances()
    assert (result["balance_valid"], by_ccy["USD"]["expected_closing"], by_ccy["SGD"]["expected_closing"], by_ccy["BTC"]["expected_closing"], leg.money, leg.money.currency, len(balances), balances.get("USD").closing, hasattr(balances, "amount"), len(StatementSummary().typed_currency_balances())) == (
        True, "150.00", "250.00", "3.00", Money(Decimal("100.00"), "USD"), Currency("USD"), 2, Money(Decimal("150.00"), "USD"), False, 0,
    )
    with pytest.raises(CurrencyMismatchError):
        _ = leg.money + other.money
