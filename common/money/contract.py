"""The ``money`` package's machine-checkable :class:`PackageContract`.

Migrates the money value-type package onto the package model (EPIC-025). The
authoritative prose + conformance spec stay in
[`contract/money.contract.md`](./contract/money.contract.md) +
[`conformance/vectors.json`](./conformance/vectors.json); this file is the machine
contract the governance gate (``tools/check_package_contract.py``) validates:
``interface`` == the BE implementation's ``__all__`` and every ``invariants[].test``
resolves to a real test function.

``roadmap`` is empty: the money ACs (AC2.19.x / AC2.20.x) are still owned by the
EPIC-002 table, and the package model forbids mirroring an AC into both a roadmap
and an EPIC. Moving that AC ownership into the roadmap is a tracked follow-up.
"""

from __future__ import annotations

from common.governance.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="money",
    # kernel: a member of the value-type family. money imports ratio (MoneyTolerance
    # is a Ratio) — a declared, acyclic same-class edge, allowed by the package model
    # ("never up, never sideways-cyclic").
    klass="kernel",
    status="active",
    # Pure-Decimal value type, no LLM in the package: CODE-ONLY (0% LLM).
    tier="CODE-ONLY",
    depends_on=["ratio"],
    roles=["types", "ops"],
    implementations={"be": "apps/backend/src/money", "fe": "apps/frontend/src/lib/money"},
    interface=["ISO_4217_CODES", "MONEY_QUANTUM", "Currency", "CurrencyBalance", "CurrencyBalances", "CurrencyMismatchError", "ExchangeRate", "FloatNotAllowedError", "InvalidExchangeRateError", "InvalidCurrencyError", "InvalidMoneyPayloadError", "Money", "MoneyError", "MoneyTolerance", "convert", "exchange_rate_from_db_fields", "exchange_rate_from_wire", "exchange_rate_to_db_fields", "exchange_rate_to_wire", "money_from_db_fields", "money_from_wire", "money_to_db_fields", "money_to_wire", "to_money"],
    events=[],
    invariants=[
        Invariant(
            id="money-rounds-half-even",
            statement="Money quantizes to its currency's minor unit with banker's HALF_EVEN rounding, matching the conformance vectors.",
            test="tests/tooling/test_money_conformance.py::test_AC2_20_1_conformance_rounding",
        ),
        Invariant(
            id="convert-applies-rate-deterministically",
            statement="convert() applies an ExchangeRate and rounds the result deterministically, matching the conformance vectors.",
            test="tests/tooling/test_money_conformance.py::test_AC2_20_1_conformance_convert",
        ),
        Invariant(
            id="currency-validated",
            statement="A Currency must be a valid ISO-4217 code; an invalid code is unrepresentable (InvalidCurrencyError).",
            test="tests/tooling/test_money_conformance.py::test_AC2_19_1_conformance_currency_validation",
        ),
    ],
    roadmap=[],
)
