"""The ``runtime`` package's machine-checkable :class:`PackageContract`.

``runtime`` is the app↔external-world dependency boundary: it owns the *contract*
for the external backends the application depends on (object storage, the LLM
provider, cache, telemetry, …), how each of the six environments substitutes
them, and the invariant that a *declared* dependency must be *asserted present*
(no silent ``skipped``/``warning``/fallback).

It is a ``kernel`` leaf (``depends_on=[]``) and currently ``draft`` — still being
designed. The *construct* phase shipped the ``base`` value language + dependency
manifest + the ``DependencyCheck`` port; the *switch* phase adds the
``extension`` probe adapters (``DatabaseCheck`` / ``ObjectStorageCheck`` /
``LlmCheck``, published below) that ``boot.Bootloader`` now delegates to. The
*cleanup* phase dropped the silent ``skipped`` status: an absent declared
dependency is an ``error`` (runtime invariant 2). Remaining as a future feature
(not the migration): manifest-driven ``validate`` for *all* declared dependencies
per env tier + smoke↔declaration parity — see ``todo.md``. Roadmap ACs (each
pinned to a real test) are added when those enforcement invariants land; the
prose contract lives in ``readme.md`` + ``todo.md`` until then.
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
    implementations={"be": "apps/backend/src/runtime", "fe": None},
    interface=[
        "APP_OWNED_TIERS",
        "DEPENDENCY_MANIFEST",
        "VPS_TIERS",
        "DatabaseCheck",
        "Dependency",
        "DependencyCheck",
        "DependencyKind",
        "DependencyManifest",
        "DependencyStatus",
        "EnvTier",
        "LlmCheck",
        "ObjectStorageCheck",
        "ProbeResult",
    ],
    events=[],
    invariants=[],
    roadmap=[],
)
