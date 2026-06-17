"""Backend-runtime conformance to the shared money standard (#1167 / #1170).

The cross-language standard lives in ``common/money/conformance/vectors.json`` and
the Python reference impl (``common/money``) is proven against it in the tooling
lane. This test proves the **actually-shipped backend rounding path**
(``src.utils.money.to_money`` — imported by ~16 routers/services) also conforms to
the standard's HALF_EVEN rounding, so the deployed service cannot drift from the
frontend even though it keeps its own self-contained implementation.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.utils.money import MONEY_QUANTUM, to_money

pytestmark = pytest.mark.no_db

_VECTORS = json.loads(
    (Path(__file__).resolve().parents[4] / "common/money/conformance/vectors.json").read_text()
)


def test_backend_to_money_matches_standard_quantum():
    assert str(MONEY_QUANTUM) == _VECTORS["money_quantum"]
    assert _VECTORS["default_rounding"] == "ROUND_HALF_EVEN"


@pytest.mark.parametrize(
    "case",
    [c for c in _VECTORS["rounding"] if c["rounding"] == "ROUND_HALF_EVEN"],
    ids=lambda c: c["amount"],
)
def test_backend_to_money_matches_rounding_vectors(case):
    """The shipped to_money() reproduces every default-rounding standard vector."""
    assert to_money(Decimal(case["amount"])) == Decimal(case["expected"]), case
