"""The ``money`` package's machine-checkable :class:`PackageContract`.

Migrates the money value-type package onto the package model (EPIC-025). The
authoritative prose + conformance spec stay in
[`contract/money.contract.md`](./contract/money.contract.md) +
[`conformance/vectors.json`](./conformance/vectors.json); this file is the machine
contract the governance gate (``tools/check_package_contract.py``) validates:
``interface`` == the BE implementation's ``__all__`` and every ``invariants[].test``
resolves to a real test function.

``roadmap`` homes the EPIC-002 money *leftovers* whose anchor test proves a money
statement: AC2.23.1 (the narrow-waist float-ban guard over the money modules) and
AC2.22.3 (net-worth restatement routed through the ``convert`` primitive), renamed
``AC-money.23.1`` / ``AC-money.22.3`` (leading "2" dropped, group+seq preserved, each
inheriting the package CODE-ONLY tier). The package model forbids mirroring an AC into
both a roadmap and an EPIC, so their EPIC-002 table rows are deleted in the same change.

The pure value-type ACs ``AC2.19.x`` / ``AC2.20.x`` / ``AC2.21.x`` deliberately STAY in
the EPIC-002 table: they are already the anchors of this contract's ``invariants[].test``
proof edges (the conformance tests below carry ``@ac_proof(ac_ids=["AC2.19.1"/"AC2.20.1"])``),
so re-homing them is a separate cutover, not bundled here. No EPIC-012 group migrates:
each money-touching EPIC-012 group is mixed (a Money sub-AC beside Quantity/Ratio ones)
or an adoption/ORM/feature AC proven by a non-money-value-type test — not squarely money.
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
    name="money",
    # kernel: a member of the value-type family. money imports ratio (MoneyTolerance
    # is a Ratio) — a declared, acyclic same-class edge, allowed by the package model
    # ("never up, never sideways-cyclic").
    klass="kernel",
    status="active",
    # Pure-Decimal value type, no LLM in the package: CODE-ONLY (0% LLM).
    tier="CODE-ONLY",
    depends_on=["ratio"],
    # The package's domain value objects (kind for the taxonomy; no module path —
    # the BE implementation has not yet split into base/extension/data, so the gate
    # skips placement here). `units` is the layer-converging taxonomy; the legacy
    # `roles` kwarg is dropped (it defaults to empty and the gate accepts its absence).
    units=[
        Unit(name="Money", kind=Kind.VALUE_OBJECT),
        Unit(name="Currency", kind=Kind.VALUE_OBJECT),
        Unit(name="ExchangeRate", kind=Kind.VALUE_OBJECT),
        Unit(name="MoneyTolerance", kind=Kind.VALUE_OBJECT),
        Unit(name="CurrencyBalance", kind=Kind.VALUE_OBJECT),
        Unit(name="CurrencyBalances", kind=Kind.VALUE_OBJECT),
    ],
    implementations={
        "be": "apps/backend/src/money",
        "fe": "apps/frontend/src/lib/money",
    },
    interface=[
        "ISO_4217_CODES",
        "MONEY_QUANTUM",
        "Currency",
        "CurrencyBalance",
        "CurrencyBalances",
        "CurrencyMismatchError",
        "ExchangeRate",
        "FloatNotAllowedError",
        "InvalidExchangeRateError",
        "InvalidCurrencyError",
        "InvalidMoneyPayloadError",
        "Money",
        "MoneyError",
        "MoneyTolerance",
        "convert",
        "exchange_rate_from_db_fields",
        "exchange_rate_from_wire",
        "exchange_rate_to_db_fields",
        "exchange_rate_to_wire",
        "money_from_db_fields",
        "money_from_wire",
        "money_to_db_fields",
        "money_to_wire",
        "to_money",
    ],
    events=[],
    invariants=[
        Invariant(
            id="money-rounds-half-even",
            statement="Money quantizes to its currency's minor unit with banker's HALF_EVEN rounding, matching the conformance vectors.",
            test="tests/tooling/test_money_conformance.py::test_AC2_20_1_conformance_rounding",
        ),
        Invariant(
            id="convert-applies-rate-deterministically",
            statement="convert() applies an ExchangeRate and rounds the result deterministically, matching the conformance vectors.",
            test="tests/tooling/test_money_conformance.py::test_AC2_20_1_conformance_convert",
        ),
        Invariant(
            id="currency-validated",
            statement="A Currency must be a valid ISO-4217 code; an invalid code is unrepresentable (InvalidCurrencyError).",
            test="tests/tooling/test_money_conformance.py::test_AC2_19_1_conformance_currency_validation",
        ),
    ],
    roadmap=[
        # ── EPIC-002 money leftovers (was AC2.22.* / AC2.23.*) ──
        # The pure value-type ACs AC2.19/2.20/2.21 stay in EPIC-002 (they anchor the
        # invariants[].test proof edges above); only the two leftovers whose proof is a
        # money-package statement migrate here.
        ACRecord(
            id="AC-money.22.3",
            statement=(
                "Reporting net-worth restatement routes through the convert primitive "
                "(restate / restate_unrounded); restated totals are byte-identical to "
                "to_money(amount*rate) / amount*rate. Was EPIC-002 AC2.22.3."
            ),
            test=(
                "apps/backend/tests/money/test_money_adopt.py"
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
