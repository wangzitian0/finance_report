"""Backend money module + materiality adoption (EPIC-002 AC2.22, #1167 / #1171).

Proves the backend's own ``src.audit.money`` "end" conforms to the shared standard, and
that the first materiality call-sites are routed through the value types in a
behaviour-preserving way:

- AC-audit.22.1 — ``StatementSummary.typed_currency_balances()`` reads the per-currency
  JSONB as a typed ``CurrencyBalances`` (no scalar collapse).
- AC-audit.22.4 — ``TransferLeg.money`` exposes a leg's value as a typed ``Money``.

(AC-audit.22.2 reconciliation + AC-money.22.3 reporting hot-path arithmetic adoption
are proven separately in ``test_money_adopt.py``; AC-money.22.3 has migrated into
the money package roadmap. Routing them through Money's ISO-4217 validation needs
non-ISO-currency-tolerant handling, hence the dedicated byte-identical adoption
helpers there.)
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import Currency, CurrencyMismatchError, ExchangeRate, Money, convert
from src.extraction.orm.statement_summary import StatementSummary
from src.reconciliation.extension.fx_transfer import TransferLeg

pytestmark = pytest.mark.no_db

_VECTORS = json.loads((Path(__file__).resolve().parents[5] / "common/audit/money/conformance/vectors.json").read_text())


# ── backend module conforms to the shared standard ──────────────────────
@ac_proof(
    proof_id="test_backend_money_module_rounding_conformance",
    ac_ids=["AC-audit.20.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
@pytest.mark.parametrize("case", _VECTORS["rounding"], ids=lambda c: f"{c['amount']}/{c['rounding']}")
def test_AC2_20_1_backend_money_module_matches_rounding(case):
    """AC-audit.20.1: src.audit.money reproduces the shared rounding standard."""
    assert Money(Decimal(case["amount"]), "USD").quantize(case["rounding"]).amount == Decimal(case["expected"])


@ac_proof(
    proof_id="test_backend_money_module_convert_conformance",
    ac_ids=["AC-audit.20.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
@pytest.mark.parametrize("case", _VECTORS["convert"], ids=lambda c: f"{c['amount']}*{c['rate']}")
def test_AC2_20_1_backend_money_module_matches_convert(case):
    """AC-audit.20.1: src.audit.money.convert reproduces the shared FX standard."""
    result = convert(
        Money(Decimal(case["amount"]), case["from"]),
        ExchangeRate(case["from"], case["to"], Decimal(case["rate"])),
        rounding=case["rounding"],
    )
    assert result.amount == Decimal(case["expected"])
    assert result.currency.code == case["to"]


@ac_proof(
    proof_id="test_backend_money_typed_exchange_rate",
    ac_ids=["AC-audit.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_backend_convert_accepts_typed_exchange_rate():
    """AC-audit.30.3: src.audit.money.convert takes ExchangeRate, not a naked Decimal rate."""
    result = convert(Money(Decimal("100.00"), "USD"), ExchangeRate("USD", "SGD", Decimal("1.35")))
    assert result == Money(Decimal("135.00"), "SGD")


@ac_proof(
    proof_id="test_backend_money_exchange_rate_mismatch",
    ac_ids=["AC-audit.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_backend_exchange_rate_source_mismatch_raises():
    """AC-audit.30.3: src.audit.money.convert rejects a rate whose base does not match money.currency."""
    with pytest.raises(CurrencyMismatchError):
        convert(Money(Decimal("100.00"), "EUR"), ExchangeRate("USD", "SGD", Decimal("1.35")))


@ac_proof(
    proof_id="test_backend_money_convert_rejects_naked_decimal_rate",
    ac_ids=["AC-audit.30.3"],
    ci_tier="pr_ci",
)
def test_AC12_30_3_backend_convert_rejects_naked_decimal_rate():
    """AC-audit.30.3: src.audit.money.convert rejects the old naked-Decimal rate boundary."""
    with pytest.raises(TypeError):
        convert(Money(Decimal("100.00"), "USD"), Decimal("1.35"))  # type: ignore[arg-type]


@ac_proof(
    proof_id="test_backend_money_module_iso_parity",
    ac_ids=["AC-audit.19.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_19_1_backend_money_module_iso_parity():
    """AC-audit.19.1: the backend ISO set equals the shared canonical set."""
    from src.audit.money.currency import ISO_4217_CODES

    assert ISO_4217_CODES == set(_VECTORS["iso4217"])


# ── AC-audit.22.4: fx_transfer leg routed through Money ──────────────────────
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
    # Two legs in different currencies cannot be summed implicitly.
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


# ── AC-audit.22.1: StatementSummary per-currency balances are typed ──────────
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
    assert balances.is_multi_currency()
    assert balances.get("USD").closing == Money(Decimal("150.00"), "USD")
    # No scalar accessor that could collapse the multi-currency balance.
    assert not hasattr(balances, "amount")
    # NULL/empty -> empty typed container (scalar degenerate case lives elsewhere).
    empty = StatementSummary()
    assert len(empty.typed_currency_balances()) == 0


def test_exchange_rate_coercion_routes_through_shared_codec_and_keeps_fx_invariants():
    """AC-audit.36.2 (#1864 backfill): backend ``_coerce_rate`` delegates to the shared
    codec (float/bool rejection) while the finite-and-positive rule stays FX-specific."""
    from src.audit.money.errors import FloatNotAllowedError, InvalidExchangeRateError

    with pytest.raises(FloatNotAllowedError):
        ExchangeRate(Currency.of("USD"), Currency.of("SGD"), 1.35)
    with pytest.raises(FloatNotAllowedError):
        ExchangeRate(Currency.of("USD"), Currency.of("SGD"), True)
    with pytest.raises(FloatNotAllowedError):
        ExchangeRate(Currency.of("USD"), Currency.of("SGD"), "1.35")
    for bad_rate in (Decimal("0"), Decimal("-1.35"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(InvalidExchangeRateError):
            ExchangeRate(Currency.of("USD"), Currency.of("SGD"), bad_rate)
    assert ExchangeRate(Currency.of("USD"), Currency.of("SGD"), Decimal("1.35")).rate == Decimal("1.35")
