"""The ``quantity`` package's machine-checkable :class:`PackageContract`.

Migrates the quantity value-type package onto the package model (EPIC-025). Prose
+ conformance spec stay in
[`contract/quantity.contract.md`](./contract/quantity.contract.md) +
[`conformance/vectors.json`](./conformance/vectors.json); this is the machine
contract the governance gate validates.

``roadmap`` is empty: the quantity ACs (AC12.30.x) are still owned by the EPIC-012
table; moving that ownership into the roadmap is a tracked follow-up.
"""

from __future__ import annotations

from common.governance.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="quantity",
    # platform, not kernel: quantity imports the ratio kernel package (a Ratio can
    # scale a Quantity), so it sits one layer above ratio in the dependency DAG.
    klass="platform",
    status="active",
    tier="PC",
    depends_on=["ratio"],
    roles=["types", "ops"],
    implementations={"be": "apps/backend/src/quantity", "fe": "apps/frontend/src/lib/quantity"},
    interface=["QUANTITY_DP", "QUANTITY_QUANTUM", "QUANTITY_ROUNDING", "FloatNotAllowedError", "InvalidQuantityPayloadError", "InvalidUnitError", "Quantity", "QuantityError", "Unit", "UnitMismatchError", "quantity_from_db_fields", "quantity_from_wire", "quantity_to_db_fields", "quantity_to_wire"],
    events=[],
    invariants=[
        Invariant(
            id="quantize-matches-standard",
            statement="Quantity quantizes to its standard decimal places/rounding, matching the conformance vectors.",
            test="tests/tooling/test_quantity_conformance.py::test_AC12_30_2_quantity_quantize_matches_standard",
        ),
        Invariant(
            id="unit-validated",
            statement="A Quantity carries a valid Unit and rejects unit mismatches; an invalid unit is unrepresentable.",
            test="tests/tooling/test_quantity_conformance.py::test_AC12_30_2_quantity_unit_validation_matches_standard",
        ),
        Invariant(
            id="ratio-application-matches-standard",
            statement="Applying a Ratio to a Quantity rounds deterministically, matching the conformance vectors.",
            test="tests/tooling/test_quantity_conformance.py::test_AC12_30_2_quantity_ratio_matches_standard",
        ),
    ],
    roadmap=[],
)
