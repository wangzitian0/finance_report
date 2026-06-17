"""Backend money module + materiality adoption (EPIC-002 AC2.22, #1167 / #1171).

Proves the backend's own ``src.money`` "end" conforms to the shared standard, and
that the first materiality call-sites are routed through the value types in a
behaviour-preserving way:

- AC2.22.1 — ``StatementSummary.typed_currency_balances()`` reads the per-currency
  JSONB as a typed ``CurrencyBalances`` (no scalar collapse).
- AC2.22.4 — ``TransferLeg.money`` exposes a leg's value as a typed ``Money``.

(AC2.22.2 reconciliation + AC2.22.3 reporting hot-path arithmetic adoption are a
tracked follow-up — see EPIC-002 — because routing them through Money's ISO-4217
validation needs non-ISO-currency-tolerant handling first.)
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.models.statement_summary import StatementSummary
from src.money import Currency, CurrencyMismatchError, Money, convert
from src.services.fx_transfer import TransferLeg

pytestmark = pytest.mark.no_db

_VECTORS = json.loads((Path(__file__).resolve().parents[4] / "common/money/conformance/vectors.json").read_text())


# ── backend module conforms to the shared standard ──────────────────────
@ac_proof(
    proof_id="test_backend_money_module_rounding_conformance",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
@pytest.mark.parametrize("case", _VECTORS["rounding"], ids=lambda c: f"{c['amount']}/{c['rounding']}")
def test_AC2_20_1_backend_money_module_matches_rounding(case):
    """AC2.20.1: src.money reproduces the shared rounding standard."""
    assert Money(Decimal(case["amount"]), "USD").quantize(case["rounding"]).amount == Decimal(case["expected"])


@ac_proof(
    proof_id="test_backend_money_module_convert_conformance",
    ac_ids=["AC2.20.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
@pytest.mark.parametrize("case", _VECTORS["convert"], ids=lambda c: f"{c['amount']}*{c['rate']}")
def test_AC2_20_1_backend_money_module_matches_convert(case):
    """AC2.20.1: src.money.convert reproduces the shared FX standard."""
    result = convert(
        Money(Decimal(case["amount"]), case["from"]),
        Decimal(case["rate"]),
        to=case["to"],
        rounding=case["rounding"],
    )
    assert result.amount == Decimal(case["expected"])
    assert result.currency.code == case["to"]


@ac_proof(
    proof_id="test_backend_money_module_iso_parity",
    ac_ids=["AC2.19.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_19_1_backend_money_module_iso_parity():
    """AC2.19.1: the backend ISO set equals the shared canonical set."""
    from src.money.currency import ISO_4217_CODES

    assert ISO_4217_CODES == set(_VECTORS["iso4217"])


# ── AC2.22.4: fx_transfer leg routed through Money ──────────────────────
@ac_proof(
    proof_id="test_transfer_leg_money",
    ac_ids=["AC2.22.4"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_22_4_transfer_leg_exposes_typed_money():
    """AC2.22.4: TransferLeg.money is the leg value as Money (same amount/currency)."""
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


# ── AC2.22.1: StatementSummary per-currency balances are typed ──────────
@ac_proof(
    proof_id="test_statement_summary_typed_balances",
    ac_ids=["AC2.22.1"],
    ci_tier="pr_ci",
    issue="#1171",
)
def test_AC2_22_1_statement_summary_typed_currency_balances():
    """AC2.22.1: typed_currency_balances reads the JSONB as per-currency Money."""
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
