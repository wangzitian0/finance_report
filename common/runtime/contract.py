"""The ``runtime`` package's machine-checkable :class:`PackageContract`.

``runtime`` is the app↔external-world dependency boundary: it owns the *contract*
for the external backends the application depends on (object storage, the LLM
provider, cache, telemetry, …), how each of the six environments substitutes
them, and the invariant that a *declared* dependency must be *asserted present*
(no silent ``skipped``/``warning``/fallback).

It is a ``kernel`` leaf (``depends_on=[]``) and currently ``draft`` — still being
designed. It ships no implementation units and no curated published language yet
(``interface=[]``), so the prose contract (ubiquitous language, invariants, the
roadmap of ACs) lives in ``readme.md`` + ``todo.md`` until each AC lands with a
real test. Roadmap entries move here (each pinned to its test) as they are built.
"""

from __future__ import annotations

from common.meta.package_contract import PackageContract

CONTRACT = PackageContract(
    name="runtime",
    klass="kernel",
    status="draft",
    tier="CODE-ONLY",
    depends_on=[],
    roles=[],
    implementations={"be": "common/runtime", "fe": None},
    interface=[],
    events=[],
    invariants=[],
    roadmap=[],
)
