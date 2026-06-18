"""Money value-type behavioural proofs (EPIC-002 AC2.19–AC2.21, #1167 / #1170).

These exercise the ``common.money`` narrow waist: ``Money`` / ``Currency``
construction invariants, same-currency-only arithmetic, the single ``convert``
FX primitive, and the per-currency ``CurrencyBalances`` container that makes a
multi-currency statement inexpressible as a scalar.

Contract: ``docs/ssot/accounting.md#money-type``.
"""

from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from common.money import (
    Currency,
    CurrencyBalance,
    CurrencyBalances,
    CurrencyMismatchError,
    ExchangeRate,
    FloatNotAllowedError,
    InvalidCurrencyError,
    Money,
    convert,
)
from common.testing.ac_proof import ac_proof


# ── AC2.19.1: Money/Currency construction invariants ────────────────────
@ac_proof(
    proof_id="test_money_rejects_float",
    ac_ids=["AC2.19.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_1_money_rejects_float_amount():
    """AC2.19.1: Money construction rejects float (the monetary red line)."""
    with pytest.raises(FloatNotAllowedError):
        Money(10.0, "USD")
    with pytest.raises(FloatNotAllowedError):
        Money(0.1 + 0.2, "USD")
    # bool is an int subclass but is never a valid amount.
    with pytest.raises(FloatNotAllowedError):
        Money(True, "USD")


@ac_proof(
    proof_id="test_money_accepts_decimal_and_int",
    ac_ids=["AC2.19.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_1_money_is_decimal_backed():
    """AC2.19.1: Money is Decimal-backed; Decimal and int are accepted."""
    assert Money(Decimal("10.00"), "USD").amount == Decimal("10.00")
    assert isinstance(Money(5, "USD").amount, Decimal)
    assert Money(5, "USD").amount == Decimal("5")


@ac_proof(
    proof_id="test_money_is_immutable",
    ac_ids=["AC2.19.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_1_money_is_immutable():
    """AC2.19.1: Money is immutable (frozen value type)."""
    m = Money(Decimal("1.00"), "USD")
    with pytest.raises((AttributeError, TypeError)):
        m.amount = Decimal("2.00")  # type: ignore[misc]


@ac_proof(
    proof_id="test_currency_rejects_non_iso",
    ac_ids=["AC2.19.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_1_currency_rejects_non_iso():
    """AC2.19.1: Currency rejects non-ISO-4217 codes and normalises case."""
    assert Currency("usd ").code == "USD"  # normalised
    for bad in ("US", "XYZ", "EURO", "123", ""):
        with pytest.raises(InvalidCurrencyError):
            Currency(bad)
    # Money rejects a non-ISO currency at construction too.
    with pytest.raises(InvalidCurrencyError):
        Money(Decimal("1.00"), "XYZ")


# ── AC2.19.2: same-currency arithmetic; cross-currency raises ───────────
@ac_proof(
    proof_id="test_same_currency_arithmetic",
    ac_ids=["AC2.19.2"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_2_same_currency_add_and_subtract():
    """AC2.19.2: same-currency +/- works and stays in-currency."""
    a = Money(Decimal("10.00"), "SGD")
    b = Money(Decimal("2.50"), "SGD")
    assert (a + b) == Money(Decimal("12.50"), "SGD")
    assert (a - b) == Money(Decimal("7.50"), "SGD")
    assert (-a) == Money(Decimal("-10.00"), "SGD")
    assert abs(Money(Decimal("-3"), "SGD")) == Money(Decimal("3"), "SGD")


@ac_proof(
    proof_id="test_cross_currency_arithmetic_raises",
    ac_ids=["AC2.19.2"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_2_cross_currency_arithmetic_raises():
    """AC2.19.2: cross-currency +/-/compare raises (no implicit conversion)."""
    usd = Money(Decimal("10.00"), "USD")
    sgd = Money(Decimal("10.00"), "SGD")
    with pytest.raises(CurrencyMismatchError):
        _ = usd + sgd
    with pytest.raises(CurrencyMismatchError):
        _ = usd - sgd
    with pytest.raises(CurrencyMismatchError):
        _ = usd < sgd
    # Equality across currencies is False, never an implicit collapse.
    assert usd != sgd


# ── AC2.20.1: the single FX conversion primitive ────────────────────────
@ac_proof(
    proof_id="test_convert_applies_rate_and_target",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_20_1_convert_applies_rate_and_changes_currency():
    """AC2.20.1: convert applies a Decimal rate and restates into the target."""
    result = convert(Money(Decimal("100.00"), "USD"), ExchangeRate("USD", "SGD", Decimal("1.35")))
    assert result == Money(Decimal("135.00"), "SGD")
    assert result.currency == Currency("SGD")


@ac_proof(
    proof_id="test_convert_rejects_float_rate",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_20_1_convert_rejects_float_rate():
    """AC2.20.1: convert rejects a float rate (no implicit float in money math)."""
    with pytest.raises(FloatNotAllowedError):
        ExchangeRate("USD", "SGD", 1.35)  # type: ignore[arg-type]


@ac_proof(
    proof_id="test_convert_rounds_half_even_at_boundary",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_20_1_convert_rounds_half_even_at_boundary():
    """AC2.20.1: convert quantizes to 2 dp with banker's rounding at the boundary."""
    # 1.005 -> half to even -> 1.00 (HALF_UP would give 1.01).
    assert convert(Money(Decimal("1.00"), "USD"), ExchangeRate("USD", "EUR", Decimal("1.005"))) == Money(
        Decimal("1.00"), "EUR"
    )
    # 1.015 -> half to even -> 1.02.
    assert convert(Money(Decimal("1.00"), "USD"), ExchangeRate("USD", "EUR", Decimal("1.015"))) == Money(
        Decimal("1.02"), "EUR"
    )
    # An explicit non-default rounding mode is honoured.
    assert convert(
        Money(Decimal("1.00"), "USD"),
        ExchangeRate("USD", "EUR", Decimal("1.005")),
        rounding="ROUND_HALF_UP",
    ) == Money(Decimal("1.01"), "EUR")


@ac_proof(
    proof_id="test_convert_round_trip",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_20_1_convert_round_trip_within_boundary():
    """AC2.20.1: convert there-and-back returns the original at the 2-dp boundary."""
    rate = Decimal("1.25")
    original = Money(Decimal("80.00"), "USD")
    there_rate = ExchangeRate("USD", "SGD", rate)
    there = convert(original, there_rate)
    back = convert(there, there_rate.inverse())
    assert back == original
    assert ROUND_HALF_EVEN  # documents the default rounding mode used


@ac_proof(
    proof_id="test_money_typed_exchange_rate",
    ac_ids=["AC12.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_convert_accepts_typed_exchange_rate():
    """AC12.30.3: convert takes an ExchangeRate carrying source/target currency."""
    rate = ExchangeRate("usd", "sgd", Decimal("1.35"))
    assert rate.base == Currency("USD")
    assert rate.quote == Currency("SGD")
    assert convert(Money(Decimal("100.00"), "USD"), rate) == Money(Decimal("135.00"), "SGD")


@ac_proof(
    proof_id="test_money_exchange_rate_mismatch",
    ac_ids=["AC12.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_exchange_rate_source_mismatch_raises():
    """AC12.30.3: a rate whose base currency does not match the money source raises."""
    with pytest.raises(CurrencyMismatchError):
        convert(Money(Decimal("100.00"), "EUR"), ExchangeRate("USD", "SGD", Decimal("1.35")))


@ac_proof(
    proof_id="test_money_convert_rejects_naked_decimal_rate",
    ac_ids=["AC12.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_convert_rejects_naked_decimal_rate():
    """AC12.30.3: convert rejects the old naked-Decimal rate boundary."""
    with pytest.raises(TypeError):
        convert(Money(Decimal("100.00"), "USD"), Decimal("1.35"))  # type: ignore[arg-type]


# ── AC2.21.1: per-currency balance container ────────────────────────────
@ac_proof(
    proof_id="test_currency_balances_multi_currency",
    ac_ids=["AC2.21.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_21_1_multi_currency_balance_is_not_a_scalar():
    """AC2.21.1: a multi-currency balance is per-currency, never a scalar."""
    balances = CurrencyBalances(
        (
            CurrencyBalance(
                Currency("USD"),
                Money(Decimal("100"), "USD"),
                Money(Decimal("150"), "USD"),
            ),
            CurrencyBalance(
                Currency("SGD"),
                Money(Decimal("200"), "SGD"),
                Money(Decimal("250"), "SGD"),
            ),
        )
    )
    assert balances.is_multi_currency()
    assert set(balances.currencies()) == {"USD", "SGD"}
    # No scalar accessor exists that would let it masquerade as one currency.
    assert not hasattr(balances, "amount")
    assert not hasattr(balances, "currency")
    # Access is always per currency.
    assert balances.get("USD").closing == Money(Decimal("150"), "USD")


@ac_proof(
    proof_id="test_currency_balances_reject_mismatch",
    ac_ids=["AC2.21.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_21_1_balance_rejects_currency_mismatch_and_duplicates():
    """AC2.21.1: a bucket's amounts must match its currency; no duplicate currencies."""
    from common.money.errors import MoneyError

    # Wrong type for opening/closing fails with a typed MoneyError, not AttributeError.
    with pytest.raises(MoneyError):
        CurrencyBalance(Currency("USD"), "100.00", Money(Decimal("1"), "USD"))  # type: ignore[arg-type]
    with pytest.raises(MoneyError):
        CurrencyBalance(Currency("USD"), Money(Decimal("1"), "SGD"), Money(Decimal("1"), "USD"))
    with pytest.raises(MoneyError):
        CurrencyBalances(
            (
                CurrencyBalance(
                    Currency("USD"),
                    Money(Decimal("1"), "USD"),
                    Money(Decimal("1"), "USD"),
                ),
                CurrencyBalance(
                    Currency("USD"),
                    Money(Decimal("2"), "USD"),
                    Money(Decimal("2"), "USD"),
                ),
            )
        )


@ac_proof(
    proof_id="test_currency_balances_jsonb_round_trip",
    ac_ids=["AC2.21.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_21_1_currency_balances_jsonb_round_trip():
    """AC2.21.1: CurrencyBalances round-trips the StatementSummary JSONB shape."""
    rows = [
        {"currency": "USD", "opening": "100.00", "closing": "150.00"},
        {"currency": "SGD", "opening": "200.00", "closing": "250.00"},
    ]
    parsed = CurrencyBalances.from_jsonb(rows)
    assert parsed.to_jsonb() == rows
    # Amounts serialise as strings (never JSON floats).
    assert all(isinstance(r["opening"], str) for r in parsed.to_jsonb())
    # Empty / None collapses to an empty container, not a scalar.
    assert len(CurrencyBalances.from_jsonb(None)) == 0


# ── Supporting surface (full-branch coverage of the narrow waist) ────────
@ac_proof(
    proof_id="test_money_surface_helpers",
    ac_ids=["AC2.19.1", "AC2.19.2"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_19_money_surface_helpers_and_comparisons():
    """AC2.19: zero/scale/compare/str helpers behave and stay same-currency."""
    usd = Currency("USD")
    assert Money.zero(usd) == Money(Decimal("0"), "USD")
    assert Money(Decimal("2"), "USD") * 3 == Money(Decimal("6"), "USD")
    assert 3 * Money(Decimal("2"), "USD") == Money(Decimal("6"), "USD")
    a, b = Money(Decimal("1"), "USD"), Money(Decimal("2"), "USD")
    assert a < b and a <= b and b >= a and b > a
    assert str(a) == "1 USD"
    assert str(usd) == "USD"
    # Non-Money operand and non-Decimal/int amount are typed errors.
    with pytest.raises(TypeError):
        _ = a + 1  # type: ignore[operator]
    with pytest.raises(FloatNotAllowedError):
        Money("1.00", "USD")  # type: ignore[arg-type]
    with pytest.raises(InvalidCurrencyError):
        Currency(123)  # type: ignore[arg-type]
    # Explicit non-default quantize rounding mode.
    assert Money(Decimal("1.005"), "USD").quantize("ROUND_HALF_UP") == Money(Decimal("1.01"), "USD")


@ac_proof(
    proof_id="test_currency_balances_surface",
    ac_ids=["AC2.21.1"],
    ci_tier="pr_ci",
    issue="#1170",
)
def test_AC2_21_1_currency_balances_surface_and_parsing():
    """AC2.21.1: container iteration, lookup miss, and amount parsing variants."""
    bal = CurrencyBalance(Currency("USD"), Money(Decimal("1"), "USD"), Money(Decimal("2"), "USD"))
    balances = CurrencyBalances((bal,))
    assert list(iter(balances)) == [bal]
    assert not balances.is_multi_currency()
    assert balances.get("SGD") is None
    # Amount parsing accepts Decimal / int / str; rejects float and other types.
    parsed = CurrencyBalances.from_jsonb([{"currency": "USD", "opening": Decimal("1"), "closing": 2}])
    assert parsed.get("USD").closing == Money(Decimal("2"), "USD")
    with pytest.raises(FloatNotAllowedError):
        CurrencyBalances.from_jsonb([{"currency": "USD", "opening": 1.0, "closing": 2}])
    with pytest.raises(FloatNotAllowedError):
        CurrencyBalances.from_jsonb([{"currency": "USD", "opening": [], "closing": 2}])
    with pytest.raises(InvalidCurrencyError):
        CurrencyBalances.from_jsonb([{"opening": "1", "closing": "2"}])


def test_convert_rejects_non_decimal_rate_type():
    """ExchangeRate rejects a non-Decimal/int rate (e.g. str) — single FX primitive guard."""
    with pytest.raises(FloatNotAllowedError):
        ExchangeRate("USD", "EUR", "1.2")  # type: ignore[arg-type]
