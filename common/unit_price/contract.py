"""The ``unit_price`` package's machine-checkable :class:`PackageContract`.

Migrates the unit_price value-type package onto the package model (EPIC-025).
Prose + conformance spec stay in
[`contract/unit_price.contract.md`](./contract/unit_price.contract.md) +
[`conformance/vectors.json`](./conformance/vectors.json); this is the machine
contract the governance gate validates.

``roadmap`` is empty: the unit_price ACs (AC12.32.x) are still owned by the
EPIC-012 table; moving that ownership into the roadmap is a tracked follow-up.
"""

from __future__ import annotations

from common.governance.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="unit_price",
    # kernel: a member of the value-type family. Imports money + quantity (a
    # UnitPrice is money-per-unit) — declared, acyclic same-class edges.
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=["money", "quantity"],
    roles=["types", "ops"],
    implementations={"be": "apps/backend/src/unit_price", "fe": None},
    interface=["UNIT_PRICE_DP", "UNIT_PRICE_QUANTUM", "UNIT_PRICE_ROUNDING", "CurrencyMismatchError", "FloatNotAllowedError", "InvalidUnitPricePayloadError", "UndefinedUnitPriceError", "UnitMismatchError", "UnitPrice", "UnitPriceError", "unit_price_from_db_fields", "unit_price_from_wire", "unit_price_to_db_fields", "unit_price_to_wire"],
    events=[],
    invariants=[
        Invariant(
            id="unit-price-policy-matches-standard",
            statement="UnitPrice enforces its currency+unit policy (no float, currency/unit consistency), matching the conformance vectors.",
            test="tests/tooling/test_unit_price_conformance.py::test_AC12_32_2_unit_price_policy_matches_standard",
        ),
        Invariant(
            id="quantize-matches-standard",
            statement="UnitPrice quantizes to its standard decimal places/rounding, matching the conformance vectors.",
            test="tests/tooling/test_unit_price_conformance.py::test_AC12_32_2_unit_price_quantize_matches_standard",
        ),
        Invariant(
            id="product-matches-standard",
            statement="UnitPrice × Quantity yields Money rounded deterministically (currency/unit checked), matching the conformance vectors.",
            test="tests/tooling/test_unit_price_conformance.py::test_AC12_32_2_unit_price_product_matches_standard",
        ),
    ],
    roadmap=[],
)
