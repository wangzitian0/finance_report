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

Scope of THIS contract (the physical fold — see ``readme.md`` §Migration state):

* **The four value packages are physically folded into ``audit``.** ``money`` /
  ``ratio`` / ``quantity`` / ``unit_price`` now live as ``common/audit/<domain>``
  + ``apps/backend/src/audit/<domain>`` + ``apps/frontend/src/lib/audit/<domain>``
  (where a frontend mirror exists), each still the canonical cross-runtime
  reference (``conformance/vectors.json`` unchanged in content, only relocated).
  A prior version of this contract argued non-relocation was "the correct
  model" — that was superseded (issue #1419, 2026-07-01): the four packages'
  colliding symbol names (``FloatNotAllowedError`` etc., independently defined in
  every domain) make a flat merge unsafe, so each domain stays an internal
  **submodule** of ``audit`` (``audit.money``, ``audit.ratio``, ...) rather than
  flattening everything into one namespace. Only the 10 non-colliding
  value-object classes are re-exported flat at ``audit``'s root — exactly the
  ``units`` this contract already declared.
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
cutover, not bundled here (issue #1419 step 2/3). ``roadmap`` is therefore empty
for now — no AC may live in both an EPIC table and a package roadmap
(``check_epic_package_dual`` enforces it).

This file is the machine contract the governance gate
(``tools/check_package_contract.py``) validates: ``interface`` == the BE
implementation's ``__all__`` (the 10 value-object classes re-exported flat at
``apps/backend/src/audit/__init__.py``), and every ``invariants[].test`` resolves
to a real test function.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="audit",
    # kernel: audit now physically hosts the value-object family it governs (the
    # four folded domains), matching what each of them declared before the fold
    # (``klass="kernel"``). depends_on stays empty: the domains depend on each
    # other internally (an implementation detail within audit), not on anything
    # outside audit.
    klass="kernel",
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
    implementations={
        "be": "apps/backend/src/audit",
        "fe": "apps/frontend/src/lib/audit",
    },
    # The 10 value-object classes re-exported flat at the BE root (matches
    # ``units`` above exactly). Each domain's errors / wire codecs / helpers are
    # NOT part of this flat interface (several names collide across domains,
    # e.g. FloatNotAllowedError) — reach those via the domain submodule
    # (``src.audit.money``, ``src.audit.ratio``, ...).
    interface=[
        "Money",
        "Currency",
        "ExchangeRate",
        "MoneyTolerance",
        "CurrencyBalance",
        "CurrencyBalances",
        "Ratio",
        "Quantity",
        "Unit",
        "UnitPrice",
    ],
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
    # The two EPIC-002 money leftovers whose proof is a money-package statement
    # (not a pure value-type statement — those ACs, AC2.19/2.20/2.21, stay in
    # EPIC-002 per the invariants[].test edges above and move in step 2 of
    # #1419). These two previously lived in the now-deleted money/contract.py's
    # roadmap; money folding into audit means audit is their new single home —
    # not deferred, just following the code that already owned them.
    roadmap=[
        ACRecord(
            id="AC-money.22.3",
            statement=(
                "Reporting net-worth restatement routes through the convert primitive "
                "(restate / restate_unrounded); restated totals are byte-identical to "
                "to_money(amount*rate) / amount*rate. Was EPIC-002 AC2.22.3."
            ),
            test=(
                "apps/backend/tests/audit/money/test_money_adopt.py"
                "::test_AC2_22_3_restate_is_byte_identical"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-money.23.1",
            statement=(
                "The narrow-waist guard flags a money-shaped float violation on an "
                "injected sample and reports none on the real money modules; each stack "
                "(Python reference, shipped backend, frontend) keeps a conformance "
                "suite. Was EPIC-002 AC2.23.1."
            ),
            test=(
                "tests/tooling/test_money_narrow_waist_guard.py"
                "::test_AC2_23_1_guard_flags_injected_float_violation"
            ),
            priority="P0",
            status="done",
        ),
    ],
)
