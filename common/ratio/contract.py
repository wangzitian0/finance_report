"""The ``ratio`` package's machine-checkable :class:`PackageContract`.

Migrates the ratio value-type package onto the package model (EPIC-025). Prose +
conformance spec stay in [`contract/ratio.contract.md`](./contract/ratio.contract.md)
+ [`conformance/vectors.json`](./conformance/vectors.json); this is the machine
contract the governance gate validates (``interface`` == the BE ``__all__``, every
``invariants[].test`` resolves).

``roadmap`` is empty: the ratio ACs (AC12.9.x) are still owned by the EPIC-012
table; moving that ownership into the roadmap is a tracked follow-up (no AC may be
mirrored into both a roadmap and an EPIC).
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="ratio",
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles=["types", "ops"],
    implementations={"be": "apps/backend/src/ratio", "fe": "apps/frontend/src/lib/ratio"},
    interface=["PERCENT_DP", "PERCENT_ROUNDING", "FloatNotAllowedError", "InvalidRatioPayloadError", "Ratio", "RatioError", "UndefinedRatioError", "ratio_from_db_value", "ratio_from_wire", "ratio_to_db_value", "ratio_to_wire"],
    events=[],
    invariants=[
        Invariant(
            id="to-percent-matches-standard",
            statement="Ratio.to_percent() renders the percentage at the standard decimal places/rounding, matching the conformance vectors.",
            test="tests/tooling/test_ratio_conformance.py::test_AC12_9_2_to_percent_matches_standard",
        ),
        Invariant(
            id="percent-of-matches-standard",
            statement="percent_of() applies a ratio to a base deterministically, matching the conformance vectors.",
            test="tests/tooling/test_ratio_conformance.py::test_AC12_9_2_percent_of_matches_standard",
        ),
        Invariant(
            id="from-percent-round-trip",
            statement="from_percent() round-trips with to_percent() within the standard precision, matching the conformance vectors.",
            test="tests/tooling/test_ratio_conformance.py::test_AC12_9_2_from_percent_round_trip",
        ),
    ],
    roadmap=[],
)
