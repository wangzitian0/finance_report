"""The ``audit`` package's machine-checkable :class:`PackageContract`.

``audit`` is the **number governor** — the parallel peer to ``meta`` (the *form*
governor) in the package migration standard
([`common/meta/migration-standard.md`](../meta/migration-standard.md), the
"meta / audit symmetry"). Where ``meta.base`` is the package model that everyone's
structure conforms to, ``audit.base`` is the **value language** that everyone's
numbers are expressed in: the cross-runtime Shared-Kernel value types
(``Money`` / ``Currency`` / ``ExchangeRate`` / ``MoneyTolerance`` /
``CurrencyBalances`` / ``Ratio`` / ``Quantity`` / ``Unit`` / ``UnitPrice``), plus
— in a later fold — audit's own base value objects (financial invariants,
confidence / provenance, trace records). ``audit.extension`` will then reach the
financial flow (``ledger`` / ``extraction`` / ``portfolio`` / ``reporting``) to
assert global numeric correctness (issue #1419, umbrella #1416; closeout #1429).

Scope of THIS contract (the low-risk first fold — see ``readme.md`` §Migration
state):

* **Declares the Shared Kernel as audit's value-object ``units``.** The four value
  packages (``money`` / ``ratio`` / ``quantity`` / ``unit_price``) remain the
  canonical cross-runtime reference (``common/<pkg>`` + BE/FE mirrors +
  ``conformance/vectors.json``) — their code is **not** physically relocated, which
  is the correct model: they ARE the Shared-Kernel reference (see
  ``common/meta/migration-standard.md`` "project-level contract"). ``audit``
  declares them as the value language it governs.
* **Pins the number-governor invariants to the existing conformance tests.** Each
  ``invariants[].test`` resolves to a real, already-green conformance/guard test,
  so the gate proves audit's numeric guarantees against the SAME vectors that keep
  the BE/FE mirrors honest — without duplicating or weakening any proof.

Deliberately deferred (a separate atomic transaction — see ``readme.md`` and
``todo.md``): transferring AC *ownership* (``AC2.19/2.20`` in EPIC-002,
``AC12.9/12.30/12.32/12.33/12.36`` in EPIC-012) into audit's ``roadmap``. Those
ACs are registry-tracked and wired into ``@ac_proof`` edges, the per-type
PROTECTION count floor (``docs/ssot/protection-floor.json``), the tier baseline,
and the BE/FE traceability references; re-homing them must rename every such
reference atomically to avoid lowering the protection floor — so it is its own
cutover, not bundled here. ``roadmap`` is therefore empty for now, exactly as the
``money`` contract documents for the same reason (no AC may live in both an EPIC
table and a package roadmap; ``check_epic_package_dual`` enforces it).

This file is the machine contract the governance gate
(``tools/check_package_contract.py``) validates: ``interface`` == the BE
implementation's ``__all__`` (audit has no BE implementation yet, so its interface
is empty), and every ``invariants[].test`` resolves to a real test function.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="audit",
    # platform: the number governor, a governing peer to ``meta`` (also platform).
    # It declares the value language as its units but imports none of it (its base
    # depends on nothing, per the migration-standard package table), so depends_on
    # is empty and no dependency edge or cycle is introduced.
    klass="platform",
    status="active",
    # The number governor is deterministic value-language + invariant checking, no
    # LLM: a pure-code (CODE-ONLY) package, like ``meta`` and the value packages.
    tier="CODE-ONLY",
    depends_on=[],
    # The Shared Kernel value language audit governs, declared as value-object
    # units (the taxonomy; no module path — audit has no physical base/extension
    # split of its own yet, and the canonical code lives in the value packages'
    # cross-runtime reference, so the gate skips placement). audit's OWN base value
    # objects (financial invariants, confidence/provenance, trace records) arrive
    # in a later fold and are tracked in readme.md/todo.md, not declared as vapor
    # units here.
    units=[
        Unit(name="Money", kind=Kind.VALUE_OBJECT),
        Unit(name="Currency", kind=Kind.VALUE_OBJECT),
        Unit(name="ExchangeRate", kind=Kind.VALUE_OBJECT),
        Unit(name="MoneyTolerance", kind=Kind.VALUE_OBJECT),
        Unit(name="CurrencyBalance", kind=Kind.VALUE_OBJECT),
        Unit(name="CurrencyBalances", kind=Kind.VALUE_OBJECT),
        Unit(name="Ratio", kind=Kind.VALUE_OBJECT),
        Unit(name="Quantity", kind=Kind.VALUE_OBJECT),
        Unit(name="Unit", kind=Kind.VALUE_OBJECT),
        Unit(name="UnitPrice", kind=Kind.VALUE_OBJECT),
    ],
    # No BE/FE implementation of its own yet: audit is governance-only at this
    # stage (the value language runs in the value packages' mirrors). An empty
    # interface against a missing BE implementation is accepted by the gate.
    implementations={"be": None, "fe": None},
    interface=[],
    events=[],
    # The number-governor guarantees, each pinned to an existing, already-green
    # conformance/guard test (the SAME vectors that keep the BE/FE value mirrors in
    # lockstep). No new test, no duplicated proof: audit asserts numeric
    # correctness over the canonical Shared-Kernel suites.
    invariants=[
        Invariant(
            id="money-rounds-half-even",
            statement=(
                "Money quantizes to its currency's minor unit with banker's "
                "HALF_EVEN rounding, matching the money conformance vectors."
            ),
            test=(
                "tests/tooling/test_money_conformance.py"
                "::test_AC2_20_1_conformance_rounding"
            ),
        ),
        Invariant(
            id="fx-convert-is-deterministic",
            statement=(
                "convert() applies a typed ExchangeRate and rounds the result "
                "deterministically, matching the money conformance vectors."
            ),
            test=(
                "tests/tooling/test_money_conformance.py"
                "::test_AC2_20_1_conformance_convert"
            ),
        ),
        Invariant(
            id="ratio-percent-policy",
            statement=(
                "Ratio percent rendering/application matches its conformance "
                "vectors (canonical 2 dp / ROUND_HALF_UP)."
            ),
            test=(
                "tests/tooling/test_ratio_conformance.py"
                "::test_AC12_9_2_to_percent_matches_standard"
            ),
        ),
        Invariant(
            id="quantity-quantizes",
            statement=(
                "Quantity quantizes to 6 dp / ROUND_HALF_UP, matching its "
                "conformance vectors."
            ),
            test=(
                "tests/tooling/test_quantity_conformance.py"
                "::test_AC12_30_2_quantity_quantize_matches_standard"
            ),
        ),
        Invariant(
            id="unit-price-times-quantity-is-money",
            statement=(
                "UnitPrice applied to a same-unit Quantity yields Money, matching "
                "the unit_price conformance vectors (currency/unit checked)."
            ),
            test=(
                "tests/tooling/test_unit_price_conformance.py"
                "::test_AC12_32_2_unit_price_product_matches_standard"
            ),
        ),
        Invariant(
            id="no-float-in-money-narrow-waist",
            statement=(
                "Monetary values never use float in the money narrow waist; the "
                "no-float guard reports any injected float violation."
            ),
            test=(
                "tests/tooling/test_money_narrow_waist_guard.py"
                "::test_AC2_23_1_money_modules_are_float_free"
            ),
        ),
    ],
    roadmap=[],
)
