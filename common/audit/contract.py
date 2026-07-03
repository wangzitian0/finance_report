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

The value-language ACs (``AC2.19/2.20`` in EPIC-002, ``AC12.9/12.30/12.32/12.33/
12.36`` in EPIC-012) are homed in ``roadmap`` below as ``AC-audit.<n>.<n>``
(issue #1419 step 2/3, following the physical fold of step 1). Every
``@ac_proof`` edge, docstring/comment cross-reference, and the tier baseline
(``docs/ssot/ac-tier-baseline.json``) were renamed in the same change — no AC
may live in both an EPIC table and a package roadmap (``check_epic_package_dual``
enforces it).

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
    # AC-money.* — the two EPIC-002 money leftovers whose proof is a
    # money-package statement (not a pure value-type statement). These two
    # previously lived in the now-deleted money/contract.py's roadmap; money
    # folding into audit means audit is their new single home.
    #
    # AC-audit.* — the value-language ACs migrated from EPIC-002 (AC2.19/2.20)
    # and EPIC-012 (AC12.9/12.30/12.32/12.33/12.36) in step 2 of #1419. Numeric
    # AC-audit.<group>.<seq> grammar (leading epic number dropped, group+seq
    # preserved). Test FUNCTION names keep their old AC2_x_y/AC12_x_y form (the
    # `test=` below references them verbatim); only the dotted docstring/
    # comment ids and @ac_proof(ac_ids=[...]) lists were repointed. Each `test=`
    # anchor is the EPIC table's primary test function — sibling test functions
    # (the table's "(+ siblings)" note) keep proving the same AC via their own
    # renamed @ac_proof decorator, they just aren't the roadmap's resolvable
    # anchor. No package tier lower than "P0"/"P1" was assigned per-AC; the
    # package-level tier="CODE-ONLY" above applies to every roadmap AC.
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
        # ── group 19: Money/Currency value types (was EPIC-002 AC2.19.*) ──
        ACRecord(
            id="AC-audit.19.1",
            statement=(
                "Money(amount, currency) rejects float/bool, is Decimal-backed "
                "and immutable; Currency rejects non-ISO-4217 codes and "
                "normalises case. Was EPIC-002 AC2.19.1."
            ),
            test=(
                "tests/tooling/test_money_value_type.py"
                "::test_AC2_19_1_money_rejects_float_amount"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-audit.19.2",
            statement=(
                "Same-currency +/-/compare works; cross-currency arithmetic or "
                "comparison raises a typed CurrencyMismatchError (no implicit "
                "float, no implicit conversion). Was EPIC-002 AC2.19.2."
            ),
            test=(
                "tests/tooling/test_money_value_type.py"
                "::test_AC2_19_2_cross_currency_arithmetic_raises"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 20: Single FX conversion primitive (was EPIC-002 AC2.20.*) ──
        ACRecord(
            id="AC-audit.20.1",
            statement=(
                "convert(money, rate, *, to, rounding) applies a Decimal rate "
                "into an explicit target currency, rejects float rates, "
                "quantizes with banker's rounding at the boundary, and "
                "round-trips at 2 dp. Was EPIC-002 AC2.20.1."
            ),
            test=(
                "tests/tooling/test_money_value_type.py"
                "::test_AC2_20_1_convert_rounds_half_even_at_boundary"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 9: Ratio / percent value type (was EPIC-012 AC12.9.*) ──
        ACRecord(
            id="AC-audit.9.1",
            statement=(
                "Ratio rejects float, is Decimal-backed/immutable; "
                "fraction(part, whole) builds it (zero whole undefined → "
                "raises); percent display is the canonical 2 dp / "
                "ROUND_HALF_UP; dimensionless arithmetic. Was EPIC-012 AC12.9.1."
            ),
            test=(
                "tests/tooling/test_ratio_value_type.py"
                "::test_AC12_9_1_ratio_rejects_float_and_is_decimal_backed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.9.2",
            statement=(
                "Cross-language conformance: the Python reference, shipped "
                "backend src.audit.ratio, and frontend lib/ratio reproduce the "
                "same vectors.json (to_percent / percent_of / from_percent) and "
                "export the same shared_api (identifier-parity guard). Was "
                "EPIC-012 AC12.9.2."
            ),
            test=(
                "tests/tooling/test_ratio_conformance.py"
                "::test_AC12_9_2_to_percent_matches_standard"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.9.3",
            statement=(
                "Ratio adoption: portfolio performance/P&L percentages, "
                "allocation shares, reconciliation match rate, and frontend "
                "confidence/portfolio percent formatting route through the "
                "Ratio narrow waist without changing API shapes. Was EPIC-012 "
                "AC12.9.3."
            ),
            test=(
                "tests/tooling/test_ratio_adoption.py"
                "::test_AC12_9_3_backend_percentage_call_sites_route_through_ratio"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 30: Quantity + ExchangeRate (was EPIC-012 AC12.30.*) ──
        ACRecord(
            id="AC-audit.30.1",
            statement=(
                "Quantity(value, unit) rejects float/bool, is "
                "Decimal-backed/immutable, quantizes to 6 dp / ROUND_HALF_UP, "
                "supports same-unit arithmetic/comparison, and derives Ratio "
                "from same-unit quantities. Was EPIC-012 AC12.30.1."
            ),
            test=(
                "tests/tooling/test_quantity_value_type.py"
                "::test_AC12_30_1_quantity_rejects_float_and_is_decimal_backed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.30.2",
            statement=(
                "Cross-language conformance: Python reference, shipped backend "
                "src.audit.quantity, and frontend lib/quantity reproduce the "
                "same vectors.json and export the same shared_api. Was "
                "EPIC-012 AC12.30.2."
            ),
            test=(
                "tests/tooling/test_quantity_conformance.py"
                "::test_AC12_30_2_quantity_quantize_matches_standard"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.30.3",
            statement=(
                "Money conversion uses typed ExchangeRate(base, quote, rate) "
                "instead of a naked rate; source/target mismatch raises and the "
                "Python/backend/frontend conformance vectors route through "
                "ExchangeRate. Was EPIC-012 AC12.30.3."
            ),
            test=(
                "tests/tooling/test_money_value_type.py"
                "::test_AC12_30_3_convert_accepts_typed_exchange_rate"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.30.4",
            statement=(
                "Quantity adoption: frontend quantity formatting is public only "
                "from lib/quantity, and targeted backend quantity hot paths use "
                "Quantity for 6-dp quantization/zero checks instead of local "
                "naked-Decimal quantity helpers. Was EPIC-012 AC12.30.4."
            ),
            test=(
                "tests/tooling/test_quantity_adoption.py"
                "::test_AC12_30_4_frontend_quantity_formatting_is_not_exported_from_money"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 32: UnitPrice (was EPIC-012 AC12.32.*) ──
        ACRecord(
            id="AC-audit.32.1",
            statement=(
                "UnitPrice(rate, currency, unit) rejects float/bool, is "
                "Decimal-backed/immutable, quantizes to 6 dp / ROUND_HALF_UP, "
                "applies to a same-unit Quantity to yield Money (unit/currency "
                "mismatch raises), and derives from Money / Quantity via "
                "from_total (zero quantity undefined → raises). Was EPIC-012 "
                "AC12.32.1."
            ),
            test=(
                "tests/tooling/test_unit_price_value_type.py"
                "::test_AC12_32_1_unit_price_rejects_float_and_is_decimal_backed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.32.2",
            statement=(
                "Cross-language conformance: the Python reference "
                "(common/audit/unit_price) and shipped backend "
                "(src.audit.unit_price) reproduce the same vectors.json "
                "(quantize / product / from_total) and export the same "
                "shared_api (identifier-parity guard). Frontend is a P2 "
                "follow-up. Was EPIC-012 AC12.32.2."
            ),
            test=(
                "tests/tooling/test_unit_price_conformance.py"
                "::test_AC12_32_2_unit_price_quantize_matches_standard"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.32.3",
            statement=(
                "UnitPrice adoption: investment accounting prices buys/sells "
                "and lot/avg-cost through UnitPrice (removing the local "
                "_quantized_unit_rate helper and UNIT_RATE_QUANTUM literal), "
                "and market-data single-sources the price quantum from "
                "UNIT_PRICE_QUANTUM. Was EPIC-012 AC12.32.3."
            ),
            test=(
                "tests/tooling/test_unit_price_adoption.py"
                "::test_AC12_32_3_investment_accounting_uses_unit_price"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 33: composite value operations (was EPIC-012 AC12.33.*) ──
        ACRecord(
            id="AC-audit.33.1",
            statement=(
                "Money exposes is_zero/is_positive/is_negative and a typed "
                "Money.sum (cross-currency raises; empty needs a currency); "
                "Ratio.fraction_or_zero/fraction_or_none give the "
                "zero-denominator fallback; MoneyTolerance(absolute, relative) "
                "matches on max(absolute, relative*|expected|), scales, and "
                "rejects cross-currency comparison. Was EPIC-012 AC12.33.1."
            ),
            test=(
                "tests/tooling/test_composite_ops.py"
                "::test_AC12_33_1_money_predicates_and_sum"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.33.2",
            statement=(
                "Cross-language conformance: the Python reference and shipped "
                "backend reproduce the shared vectors.json groups "
                "(predicates/sum/tolerance for money, fraction_or_zero for "
                "ratio). Was EPIC-012 AC12.33.2."
            ),
            test=(
                "tests/tooling/test_composite_ops.py"
                "::test_AC12_33_2_money_composite_matches_standard"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.33.3",
            statement=(
                "Adoption: zero-denominator ratio branching routes through "
                "Ratio.fraction_or_zero (retiring the local _ratio_or_zero "
                "helper in portfolio, plus performance-report and "
                "reconciliation-stats call sites), and investment accounting "
                'uses Money predicates + Money.sum instead of naked Decimal("0") '
                "comparisons. Was EPIC-012 AC12.33.3."
            ),
            test=(
                "tests/tooling/test_composite_ops_adoption.py"
                "::test_AC12_33_3_zero_denominator_branching_routes_through_ratio"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 36: shared Decimal-scalar codec (was EPIC-012 AC12.36.*) ──
        ACRecord(
            id="AC-audit.36.1",
            statement=(
                "The four common/ base-package codecs route raw-Decimal "
                "conversion through one shared common.audit.decimal_scalar module "
                "(decimal_to_wire / coerce_decimal / WireCodec); no base "
                "package re-defines the _decimal_to_wire / _decimal_from_wire / "
                "_payload_mapping / _field bodies or the construction-time "
                "_coerce body locally, and the canonical codec logic (rstrip, "
                "IEEE-754 rejection, decimal-string parse) lives only in "
                "decimal_scalar. Was EPIC-012 AC12.36.1."
            ),
            test=(
                "tests/tooling/test_decimal_scalar_ssot.py"
                "::test_AC12_36_1_common_base_packages_share_one_scalar_codec"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-audit.36.2",
            statement=(
                "The backend self-contained mirror likewise routes every "
                "base-package Decimal boundary through one shared "
                "src.audit.decimal_scalar module, keeping the backend end conformant "
                "without re-duplicating the codec per package. Was EPIC-012 "
                "AC12.36.2."
            ),
            test=(
                "tests/tooling/test_decimal_scalar_ssot.py"
                "::test_AC12_36_2_backend_base_packages_share_one_scalar_codec"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
