"""The ``ledger`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/ledger``); every
``invariants[].test`` resolves to a real test function; ``depends_on`` must not
introduce a forbidden upward/sideways edge; and the building-block layering holds
(``base`` pure, each unit in its ``kind``'s layer, the ``JournalRepository`` split
into a base port + extension adapter, the account-balance projection a ``data``
sink).

``ledger`` is the first ``core`` domain on the package model (the double-entry
bounded context). Its ACs (the EPIC-002/012/015 double-entry + processing-account
ACs) migrate into ``roadmap`` in a later slice of the cutover (#1420 slice 3c); for
now the contract declares only the **structural invariants** of the cutover, each
pinned to a real test. ``roadmap=[]`` is standard-preserving (Decision A — deferring
the AC migration lowers no bar).
"""

from __future__ import annotations

from common.meta.package_contract import (
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="ledger",
    klass="core",
    status="active",
    # Deterministic double-entry arithmetic + persistence, no LLM: a pure-code
    # (CODE-ONLY) package.
    tier="CODE-ONLY",
    # money/config are the only registered packages the impl imports. Both are
    # lower-rank (kernel) than ledger (core), so the edges are downward.
    depends_on=["money", "config"],
    roles=["base", "extension", "data"],
    units=[
        # base — the pure double-entry core.
        Unit(name="Entry", kind=Kind.AGGREGATE_ROOT, module="base/types/entry.py"),
        Unit(name="Leg", kind=Kind.VALUE_OBJECT, module="base/types/entry.py"),
        # Entry.of / Entry.transfer — the pure factory (lives with the aggregate).
        Unit(name="EntryFactory", kind=Kind.FACTORY, module="base/types/entry.py"),
        # repository — the one split block: the abstract port lives in base/, the
        # AsyncSession adapter in extension/ (dependency inversion, mechanism B).
        Unit(
            name="JournalRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/repository.py",
        ),
        # extension — the posting domain service (an edge).
        Unit(name="post_entry", kind=Kind.DOMAIN_SERVICE, module="extension/post.py"),
        # data — the account-balance projection (read-model / leaf sink).
        Unit(name="AccountBalance", kind=Kind.PROJECTION, module="data/balance.py"),
    ],
    implementations={"be": "apps/backend/src/ledger", "fe": None},
    interface=[
        "AccountingError",
        "DegenerateEntryError",
        "Entry",
        "JournalRepository",
        "LedgerError",
        "Leg",
        "SqlJournalRepository",
        "UnbalancedEntryError",
        "ValidationError",
        "calculate_account_balance",
        "calculate_account_balances",
        "create_journal_entry",
        "post_entry",
        "post_journal_entry",
        "validate_fx_rates",
        "validate_journal_balance",
        "validate_journal_posting_invariants",
        "validate_line_account_ownership",
        "verify_accounting_equation",
        "void_journal_entry",
    ],
    events=[],
    invariants=[
        Invariant(
            id="balanced-entry-unconstructable",
            statement=(
                "An Entry is balanced per currency at construction; an unbalanced "
                "set of legs is unrepresentable (raises UnbalancedEntryError), and a "
                "<2-leg entry raises DegenerateEntryError."
            ),
            test=(
                "apps/backend/tests/ledger/test_entry.py"
                "::test_AC12_34_1_unbalanced_entry_is_unconstructable"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement=(
                "The package converges into base/ (pure core) + extension/ (edges) + "
                "data/ (the balance projection); the retired role dirs are gone."
            ),
            test=(
                "tests/tooling/test_ledger_package.py::test_ledger_converges_by_layer"
            ),
        ),
        Invariant(
            id="interface-equals-published-language",
            statement="The published language (contract.interface) equals __init__.__all__.",
            test=(
                "tests/tooling/test_ledger_package.py"
                "::test_ledger_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement=(
                "The base/ layer never imports the package's own extension/ or data/, "
                "the ORM session, or the FastAPI/transport edge."
            ),
            test="tests/tooling/test_ledger_package.py::test_ledger_base_layer_is_pure",
        ),
        Invariant(
            id="repository-splits",
            statement=(
                "The JournalRepository is a base port + an extension adapter "
                "(dependency inversion, mechanism B)."
            ),
            test="tests/tooling/test_ledger_package.py::test_ledger_repository_splits",
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates ledger with no violations.",
            test=(
                "tests/tooling/test_ledger_package.py"
                "::test_ledger_package_contract_gate_passes"
            ),
        ),
    ],
    roadmap=[],
)
