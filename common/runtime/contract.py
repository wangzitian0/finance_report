"""The ``runtime`` package's machine-checkable :class:`PackageContract`.

``runtime`` is the app↔external-world dependency boundary: it owns the *contract*
for the external backends the application depends on (object storage, the LLM
provider, cache, telemetry, …), how each of the six environments substitutes
them, and the invariant that a *declared* dependency must be *asserted present*
(no silent ``skipped``/``warning``/fallback).

An ``infra`` leaf (L1, ``depends_on=[]``), now ``active``. The *construct* phase
shipped the ``base`` value language + dependency manifest + the
``DependencyCheck`` port; the *switch* phase added the ``extension`` probe
adapters (``DatabaseCheck`` / ``ObjectStorageCheck`` / ``LlmCheck``, published
below) that ``boot.Bootloader`` delegates to; the *cleanup* phase dropped the
silent ``skipped`` status. The *migrate* phase homes the smoke-test / health
ACs here: EPIC-008 AC8.1.1–.4 → ``AC-runtime.1.*`` (smoke / service reachability /
DB connectivity) and EPIC-007 AC7.7.1–.2 → ``AC-runtime.7.*`` (``/health``
dependency-presence), each ``test=`` resolving to its existing proof; the package
tier (CODE-ONLY) gives ``proof_kind=exact``. (Step 3 / cleanup absorbs the
env-smoke-test SSOT prose into ``readme.md`` and retires the doc.) Remaining as a
future feature (not this migration): manifest-driven
``validate`` for *all* declared dependencies per env tier + smoke↔declaration
parity — see ``todo.md``.
"""

from __future__ import annotations

from common.meta.package_contract import ACRecord, PackageContract

CONTRACT = PackageContract(
    name="runtime",
    status="active",
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
    roadmap=[
        # ── Smoke tests / service reachability (was EPIC-008 AC8.1.1–.4) ──
        ACRecord(
            id="AC-runtime.1.1",
            statement="The API health endpoint is reachable and returns 200. Was EPIC-008 AC8.1.1.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_api_health_check",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.2",
            statement="The backend service is reachable and returns a structured health JSON. Was EPIC-008 AC8.1.2.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_backend_service_reachable",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.3",
            statement="The frontend API proxy is reachable, validating API availability through the proxy. Was EPIC-008 AC8.1.3.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_frontend_api_proxy_reachable",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.4",
            statement="Database connectivity is proven through a create+read cycle. Was EPIC-008 AC8.1.4.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_database_connectivity",
            priority="P0",
            status="done",
        ),
        # ── /health dependency-presence (was EPIC-007 AC7.7.1–.2) ──
        ACRecord(
            id="AC-runtime.7.1",
            statement="/health returns 200 when all declared dependencies are present. Was EPIC-007 AC7.7.1.",
            test="apps/backend/tests/infra/test_main.py::test_health_when_all_services_healthy",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.7.2",
            statement="/health returns 503 when a declared dependency is absent (invariant 2). Was EPIC-007 AC7.7.2.",
            test="apps/backend/tests/infra/test_main.py::test_health_returns_503_on_database_failure",
            priority="P0",
            status="done",
        ),
    ],
)
