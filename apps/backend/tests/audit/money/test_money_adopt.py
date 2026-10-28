"""Byte-identical proof for the Money adoption helper + wired hot path.

EPIC-002 AC-audit.22.2 (reconciliation per-currency), #1167 / #1171. The helper
routes through Money for ISO currencies and falls back to the identical Decimal
arithmetic for the ``"*"`` sentinel / non-ISO codes — these tests assert the result
is the SAME as the legacy arithmetic for every branch, so the totals are byte-identical.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import Currency, CurrencyMismatchError, Money
from src.audit.money.adopt import balance_check
from src.extraction.base.validation import validate_balance_per_currency
from src.extraction.orm.statement_summary import StatementSummary
from src.reconciliation.extension.fx_transfer import TransferLeg

pytestmark = pytest.mark.no_db


@ac_proof(proof_id="test_balance_check_byte_identical", ac_ids=["AC-audit.22.2"], ci_tier="pr_ci", issue="#1171")
@pytest.mark.parametrize(
    "opening,closing,net,currency",
    [
        (Decimal("100"), Decimal("150"), Decimal("50"), "USD"),  # ISO -> Money path
        (Decimal("100"), Decimal("151"), Decimal("50"), "SGD"),  # ISO, mismatch
        (Decimal("0"), Decimal("0"), Decimal("0"), "*"),  # sentinel -> fallback
        (Decimal("10"), Decimal("20"), Decimal("9"), "BTC"),  # non-ISO -> fallback
        (Decimal("10"), Decimal("19"), Decimal("9"), None),  # no currency -> fallback
    ],
)
def test_AC2_22_2_balance_check_is_byte_identical(opening, closing, net, currency):
    """AC-audit.22.2: balance_check equals the legacy opening+net / abs(closing-expected)."""
    expected_legacy = opening + net
    diff_legacy = abs(closing - expected_legacy)
    expected, diff = balance_check(opening, closing, net, currency)
    assert (expected, diff) == (expected_legacy, diff_legacy)


@ac_proof(proof_id="test_per_currency_validation_wired", ac_ids=["AC-audit.22.2"], ci_tier="pr_ci", issue="#1171")
def test_AC2_22_2_per_currency_validation_totals_unchanged():
    """AC-audit.22.2: validate_balance_per_currency yields the same per-currency totals.

    Routed through Money for the ISO buckets; the multi-currency loops stay
    independent (no cross-sum) and the result matches the hand-computed legacy
    arithmetic, including a non-ISO bucket (fallback path).
    """
    extracted = {
        "balances": [
            {"currency": "USD", "opening": "100.00", "closing": "150.00"},
            {"currency": "SGD", "opening": "200.00", "closing": "250.00"},
            {"currency": "BTC", "opening": "1.00", "closing": "3.00"},  # non-ISO -> fallback
        ],
        "transactions": [
            {"amount": "50.00", "direction": "IN", "currency": "USD"},
            {"amount": "50.00", "direction": "IN", "currency": "SGD"},
            {"amount": "2.00", "direction": "IN", "currency": "BTC"},
        ],
    }
    result = validate_balance_per_currency(extracted)
    assert result["balance_valid"] is True
    by_ccy = {r["currency"]: r for r in result["per_currency"]}
    assert by_ccy["USD"]["expected_closing"] == "150.00"
    assert by_ccy["SGD"]["expected_closing"] == "250.00"
    assert by_ccy["BTC"]["expected_closing"] == "3.00"  # fallback path, same result


@ac_proof(
    proof_id="test_transfer_leg_money",
    ac_ids=["AC-audit.22.4"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_22_4_transfer_leg_exposes_typed_money():
    """AC-audit.22.4: TransferLeg.money is the leg value as Money (same amount/currency)."""
    leg = TransferLeg(
        user_id=uuid4(),
        account_id=uuid4(),
        direction="OUT",
        amount=Decimal("100.00"),
        currency="usd",
        occurred_at=datetime.now(UTC),
    )
    assert leg.money == Money(Decimal("100.00"), "USD")
    assert leg.money.currency == Currency("USD")
    other = TransferLeg(
        user_id=uuid4(),
        account_id=uuid4(),
        direction="IN",
        amount=Decimal("135.00"),
        currency="SGD",
        occurred_at=datetime.now(UTC),
    )
    with pytest.raises(CurrencyMismatchError):
        _ = leg.money + other.money


@ac_proof(
    proof_id="test_statement_summary_typed_balances",
    ac_ids=["AC-audit.22.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_22_1_statement_summary_typed_currency_balances():
    """AC-audit.22.1: typed_currency_balances reads the JSONB as per-currency Money."""
    stmt = StatementSummary()
    stmt.currency_balances = [
        {"currency": "USD", "opening": "100.00", "closing": "150.00"},
        {"currency": "SGD", "opening": "200.00", "closing": "250.00"},
    ]
    balances = stmt.typed_currency_balances()
    assert len(balances) == 2
    assert balances.get("USD").closing == Money(Decimal("150.00"), "USD")
    assert not hasattr(balances, "amount")
    empty = StatementSummary()
    assert len(empty.typed_currency_balances()) == 0
