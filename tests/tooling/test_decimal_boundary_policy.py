"""Decimal boundary-policy guards (EPIC-012 AC12.31)."""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    target = REPO / path
    if target.is_dir():
        return "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(target.rglob("*.py"))
        )
    return target.read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_decimal_boundary_policy", ac_ids=["AC-audit.31.1"], ci_tier="pr_ci"
)
def test_AC12_31_1_decimal_boundary_policy_is_mece_and_enforced():
    """AC-audit.31.1: raw Decimal is an explicit boundary, not domain semantics."""
    ssot = _read(Path("common/audit/readme.md"))
    for phrase in [
        "Raw Decimal boundary policy",
        "Allowed raw Decimal boundaries",
        "Forbidden raw Decimal zones",
        "DB models and migrations",
        "Schemas and API contracts",
        "Parser and provider adapters",
        "Tests, fixtures, and generated code",
        "Boundary codec surface",
        "DB adapters",
        "package wire codecs",
        "Invalid*PayloadError",
        "service/domain calculations",
    ]:
        assert phrase in ssot

    fx = _read(Path("apps/backend/src/services/fx.py"))
    # convert_amount routes through the money primitive (imported privately as
    # _money_convert; the public fx.convert_money is now the Money-native helper).
    assert (
        "from src.audit.money import ExchangeRate, Money, MoneyError, convert as _money_convert"
        in fx
    )
    assert "ExchangeRate(source, target, rate)" in fx
    assert "Money(amount, source)" in fx
    assert "except MoneyError as exc:" in fx
    assert "raise FxRateError(" in fx
    assert "return amount * rate" not in fx


@ac_proof(
    proof_id="test_decimal_boundary_migrated_hotspots",
    ac_ids=["AC-audit.31.3"],
    ci_tier="pr_ci",
)
def test_AC12_31_3_migrated_hotspots_use_base_packages():
    """AC-audit.31.3: migrated money/quantity/frontend hotspots stay behind base packages."""
    quantity_service_files = [
            Path("apps/backend/src/portfolio/extension/positions.py"),
        Path("apps/backend/src/portfolio/extension/accounting.py"),
        Path("apps/backend/src/services/market_data_discovery.py"),
        Path("apps/backend/src/services/reporting"),
    ]
    naked_quantity_zero = re.compile(
        r"(?:quantity|remaining_quantity)\s*(?:==|!=|>|<|>=|<=)\s*Decimal\(\"0(?:\.0+)?\"\)"
    )
    for path in quantity_service_files:
        src = _read(path)
        # value type via direct import OR a model .quantity_qty accessor (#3 push)
        assert (
            "from src.audit.quantity import Quantity" in src or ".quantity_qty" in src
        ), f"{path} must use Quantity (import or .quantity_qty accessor)"
        assert "quantized_quantity_value" not in src
        assert "quantity_is_zero" not in src
        assert "quantity_zero_value" not in src
        assert not naked_quantity_zero.search(src), (
            f"{path} has a naked Decimal quantity-zero comparison"
        )

    reporting = _read(Path("apps/backend/src/services/reporting"))
    assert "position.quantity * latest_price" not in reporting
    # Quantity flows via the ManagedPosition.quantity_qty accessor (#3 boundary push);
    # market value is UnitPrice(price) * quantity, no raw quantity*price.
    assert "position_quantity = position.quantity_qty.quantize()" in reporting

    investment = _read(Path("apps/backend/src/portfolio/extension/accounting.py"))
    assert (
        "trade_quantity = Quantity(quantity, INVESTMENT_QUANTITY_UNIT).quantize()"
        in investment
    )
    assert "trade_quantity.is_zero()" in investment
    assert "amount = _money(quantity * unit_price" not in investment
    assert "proceeds = _money(quantity * unit_price" not in investment
    assert "lot.remaining_quantity * lot.unit_cost" not in investment
    assert "consumed_quantity" in investment

    frontend_app_leaks: list[str] = []
    for path in (REPO / "apps/frontend/src/app").rglob("*.[tj]sx"):
        src = path.read_text(encoding="utf-8")
        if 'import("decimal.js").Decimal' in src:
            frontend_app_leaks.append(str(path.relative_to(REPO)))
    assert frontend_app_leaks == []
