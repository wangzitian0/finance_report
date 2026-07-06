"""Base-package boundary codec guards (EPIC-012 AC-audit.31.4)."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _ensure_backend_src_importable() -> None:
    backend_path = str(REPO / "apps/backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    loaded_src = sys.modules.get("src")
    if loaded_src is not None and not hasattr(loaded_src, "__path__"):
        del sys.modules["src"]


@ac_proof(
    proof_id="test_base_package_common_boundary_codecs",
    ac_ids=["AC-audit.31.4"],
    ci_tier="pr_ci",
)
def test_AC12_31_4_common_boundary_codecs_round_trip_strings_and_db_fields():
    """AC-audit.31.4: common base packages own JSON-string and DB Decimal codecs."""
    from common.audit.money import (
        ExchangeRate,
        InvalidMoneyPayloadError,
        Money,
        exchange_rate_from_db_fields,
        exchange_rate_from_wire,
        exchange_rate_to_db_fields,
        exchange_rate_to_wire,
        money_from_db_fields,
        money_from_wire,
        money_to_db_fields,
        money_to_wire,
    )
    from common.audit.money import (
        FloatNotAllowedError as MoneyFloatNotAllowedError,
    )
    from common.audit.quantity import (
        FloatNotAllowedError as QuantityFloatNotAllowedError,
    )
    from common.audit.quantity import (
        InvalidQuantityPayloadError,
        Quantity,
        quantity_from_db_fields,
        quantity_from_wire,
        quantity_to_db_fields,
        quantity_to_wire,
    )
    from common.audit.ratio import (
        FloatNotAllowedError as RatioFloatNotAllowedError,
    )
    from common.audit.ratio import (
        InvalidRatioPayloadError,
        Ratio,
        ratio_from_db_value,
        ratio_from_wire,
        ratio_to_db_value,
        ratio_to_wire,
    )

    money = Money(Decimal("10.50"), "usd")
    assert money_to_wire(money) == {"amount": "10.5", "currency": "USD"}
    assert json.loads(json.dumps(money_to_wire(money)))["amount"] == "10.5"
    assert money_from_wire({"amount": "10.50", "currency": "USD"}) == money
    assert money_to_wire(
        Money(Decimal("123456789012345678901234567890.00"), "USD")
    ) == {
        "amount": "123456789012345678901234567890",
        "currency": "USD",
    }
    assert money_to_db_fields(money) == {"amount": Decimal("10.50"), "currency": "USD"}
    assert money_from_db_fields(Decimal("10.50"), "USD") == money
    with pytest.raises(MoneyFloatNotAllowedError):
        money_from_wire({"amount": 10.50, "currency": "USD"})
    with pytest.raises(InvalidMoneyPayloadError):
        money_from_wire({"amount": "10.50"})

    rate = ExchangeRate("usd", "sgd", Decimal("1.35"))
    assert exchange_rate_to_wire(rate) == {
        "base": "USD",
        "quote": "SGD",
        "rate": "1.35",
    }
    assert (
        exchange_rate_from_wire({"base": "USD", "quote": "SGD", "rate": "1.35"}) == rate
    )
    assert exchange_rate_to_db_fields(rate) == {
        "base": "USD",
        "quote": "SGD",
        "rate": Decimal("1.35"),
    }
    assert exchange_rate_from_db_fields("USD", "SGD", Decimal("1.35")) == rate
    with pytest.raises(MoneyFloatNotAllowedError):
        exchange_rate_from_wire({"base": "USD", "quote": "SGD", "rate": 1.35})
    with pytest.raises(InvalidMoneyPayloadError):
        exchange_rate_from_wire({"base": "USD", "quote": "SGD", "rate": "not-decimal"})

    ratio = Ratio(Decimal("0.125"))
    assert ratio_to_wire(ratio) == "0.125"
    assert ratio_from_wire("0.125") == ratio
    assert ratio_to_db_value(ratio) == Decimal("0.125")
    assert ratio_from_db_value(Decimal("0.125")) == ratio
    with pytest.raises(RatioFloatNotAllowedError):
        ratio_from_wire(0.125)
    with pytest.raises(InvalidRatioPayloadError):
        ratio_from_wire("not-decimal")

    quantity = Quantity(Decimal("2.500000"), "shares")
    assert quantity_to_wire(quantity) == {"value": "2.5", "unit": "shares"}
    assert quantity_from_wire({"value": "2.500000", "unit": "shares"}) == quantity
    assert quantity_to_db_fields(quantity) == {
        "value": Decimal("2.500000"),
        "unit": "shares",
    }
    assert quantity_from_db_fields(Decimal("2.500000"), "shares") == quantity
    with pytest.raises(QuantityFloatNotAllowedError):
        quantity_from_wire({"value": 2.5, "unit": "shares"})
    with pytest.raises(InvalidQuantityPayloadError):
        quantity_from_wire({"value": "2.5"})


@ac_proof(
    proof_id="test_base_package_backend_boundary_codecs",
    ac_ids=["AC-audit.31.4"],
    ci_tier="pr_ci",
)
def test_AC12_31_4_backend_boundary_codecs_match_common_surface():
    """AC-audit.31.4: backend runtime copies expose the same boundary codec surface."""
    _ensure_backend_src_importable()
    from src.audit.money import (
        ExchangeRate,
        Money,
        exchange_rate_from_db_fields,
        exchange_rate_from_wire,
        exchange_rate_to_db_fields,
        exchange_rate_to_wire,
        money_from_db_fields,
        money_from_wire,
        money_to_db_fields,
        money_to_wire,
    )
    from src.audit.quantity import (
        Quantity,
        quantity_from_db_fields,
        quantity_from_wire,
        quantity_to_db_fields,
        quantity_to_wire,
    )
    from src.audit.ratio import (
        Ratio,
        ratio_from_db_value,
        ratio_from_wire,
        ratio_to_db_value,
        ratio_to_wire,
    )

    assert money_from_wire(money_to_wire(Money(Decimal("1.23"), "USD"))) == Money(
        Decimal("1.23"), "USD"
    )
    assert money_from_db_fields(
        **money_to_db_fields(Money(Decimal("1.23"), "USD"))
    ) == Money(Decimal("1.23"), "USD")
    assert exchange_rate_from_wire(
        exchange_rate_to_wire(ExchangeRate("USD", "SGD", Decimal("1.35")))
    ) == ExchangeRate("USD", "SGD", Decimal("1.35"))
    assert exchange_rate_from_db_fields(
        **exchange_rate_to_db_fields(ExchangeRate("USD", "SGD", Decimal("1.35")))
    ) == ExchangeRate("USD", "SGD", Decimal("1.35"))
    assert ratio_from_wire(ratio_to_wire(Ratio(Decimal("0.5")))) == Ratio(
        Decimal("0.5")
    )
    assert ratio_from_db_value(ratio_to_db_value(Ratio(Decimal("0.5")))) == Ratio(
        Decimal("0.5")
    )
    assert quantity_from_wire(
        quantity_to_wire(Quantity(Decimal("3"), "shares"))
    ) == Quantity(Decimal("3"), "shares")
    assert quantity_from_db_fields(
        **quantity_to_db_fields(Quantity(Decimal("3"), "shares"))
    ) == Quantity(Decimal("3"), "shares")


@ac_proof(
    proof_id="test_base_package_wire_codec_shared_api",
    ac_ids=["AC-audit.31.4"],
    ci_tier="pr_ci",
)
def test_AC12_31_4_wire_codecs_are_declared_in_shared_api():
    """AC-audit.31.4: language-neutral vectors declare the cross-end wire codec surface."""
    money_api = set(
        json.loads((REPO / "common/audit/money/conformance/vectors.json").read_text())[
            "shared_api"
        ]
    )
    ratio_api = set(
        json.loads((REPO / "common/audit/ratio/conformance/vectors.json").read_text())[
            "shared_api"
        ]
    )
    quantity_api = set(
        json.loads(
            (REPO / "common/audit/quantity/conformance/vectors.json").read_text()
        )["shared_api"]
    )

    assert {
        "money_to_wire",
        "money_from_wire",
        "exchange_rate_to_wire",
        "exchange_rate_from_wire",
    } <= money_api
    assert {"ratio_to_wire", "ratio_from_wire"} <= ratio_api
    assert {"quantity_to_wire", "quantity_from_wire"} <= quantity_api
