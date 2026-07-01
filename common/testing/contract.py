"""The ``testing`` package's machine-checkable :class:`PackageContract`.

``testing`` is a ``kernel`` leaf: test/fixture-scoped capability code reused
across backend, tooling, and E2E tests (mirrors ``base_values.py``'s own
docstring: "these helpers are intentionally test/fixture scoped"). It has no
production runtime edge — nothing under ``apps/*/src`` imports it — so unlike
``money``/``counter`` its BE implementation is itself: ``implementations["be"]
= "common/testing"`` (the same self-hosting shape as ``common/meta`` and the
draft ``common/runtime``).

This formalizes what was already a de facto package (50+ test files import
``common.testing.*``) with a machine-checked contract, per the package-model
cutover. It is the landing package for cassette/PDF-fixture test assets: the
32-case LLM cassette corpus (``fixtures/llm_cassettes/`` +
``fixtures/cassette-eval-baseline.jsonl``, ``Cassette`` value object) and the
PDF fixture generator + committed synthetic PDFs (``fixtures/pdf/``,
``FixtureDocument`` value object), both relocated here from
``apps/backend/tests/fixtures/`` / ``tools/_lib/pdf_fixtures/`` and
``docs/ssot/pdf-fixtures.md`` (see ``README.md#pdf-fixtures``).

The package's ACs live here in ``roadmap`` (the package-model AC registry);
``common/ssot/generate_ac_registry.py`` sources them directly from this
contract, same as ``counter``.
"""

from __future__ import annotations

from common.meta.package_contract import ACRecord, Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="testing",
    klass="kernel",
    status="active",
    # Deterministic test/fixture helpers, no LLM in the package: CODE-ONLY.
    tier="CODE-ONLY",
    depends_on=["money"],
    roles=[],
    # No base/extension split yet, so these are taxonomy-only (no module path;
    # the gate skips placement for units with no module, same as money's VOs).
    units=[
        Unit(name="Cassette", kind=Kind.VALUE_OBJECT),
        Unit(name="FixtureDocument", kind=Kind.VALUE_OBJECT),
    ],
    implementations={"be": "common/testing", "fe": None},
    interface=["money_amount"],
    events=[],
    invariants=[
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates testing with no violations.",
            test=(
                "tests/tooling/test_testing_package.py"
                "::test_AC_testing_1_1_package_contract_gate_passes_for_testing"
            ),
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC-testing.1.1",
            statement=(
                "`common/testing` ships a machine-checkable PackageContract "
                "that the package governance gate discovers and validates "
                "clean, formalizing it as the governed home for test/fixture "
                "capability code, including the relocated LLM cassette corpus "
                "and PDF fixture generator/data."
            ),
            test=(
                "tests/tooling/test_testing_package.py"
                "::test_AC_testing_1_1_package_contract_gate_passes_for_testing"
            ),
            priority="P2",
            status="done",
        ),
    ],
)
