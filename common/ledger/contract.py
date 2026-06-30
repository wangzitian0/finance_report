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
bounded context). Slice 3b (#1420) folds the **processing (in-transit) account**
into the package: its pure identity + transfer detection/scoring policy live in
``base/processing.py`` (the :class:`ProcessingAccount` aggregate + ``TransferPair``
value object + ``detect_transfer_pattern``) and its impure verbs (acquire / post /
project / ``find_transfer_pairs``) in ``extension/processing.py`` — the original
``services/processing_account.py`` is deleted (zero residue). Reconciliation/
reporting consume it only through the published ``src.ledger`` interface, by id/
event (Decision B — one transaction per domain).

The package's ACs migrate into ``roadmap`` across the slice-3c sub-slices of the
cutover (#1420). **Slice 3c-i homed the EPIC-015 processing-account ACs** as
``AC-ledger.71.* … AC-ledger.76.*``. **Slice 3c-ii (this change) homes the first
half of the EPIC-002 double-entry core** — groups ``AC2.1``…``AC2.12`` → groups
``AC-ledger.1.*``…``AC-ledger.12.*`` (the leading "2" is dropped; seq preserved).
In each case the package now owns the ACs; the source EPIC backend tables are
deleted and replaced with a disclaimer that lists the new ids (mirroring how
identity emptied EPIC-001). The remaining EPIC-002 groups ``AC2.13``…``AC2.23``
land in slice 3c-iii under groups ``AC-ledger.13.*``…``AC-ledger.23.*``.

**Group-number reservation (ledger-local).** The first dotted segment of an
``AC-ledger.<group>.<seq>`` id is a bare uniqueness key (no gate reads semantics
from it), so the package reserves disjoint blocks to keep the namespace
collision-free as later slices add ACs without re-reading this file:

- **groups 1–12** — the EPIC-002 double-entry core, first half, this slice
  (1=account-mgmt, 2=entry-creation, 3=posting/voiding, 4=balance, 5=equation,
  6=boundary, 7=router/errors, 8=decimal-safety, 9=data-model, 10=endpoints,
  11=must-have-traceability, 12=multi-currency), each mirroring its source
  ``AC2.<g>`` group;
- **groups 13–70** — the rest of the EPIC-002/012 double-entry core (slice
  3c-iii, not yet homed);
- **groups 71–76** — the EPIC-015 processing (in-transit) account, slice 3c-i
  (71=creation, 72=transfer-entry, 73=integrity, 74=detection, 75=scoring,
  76=reconciliation integration), each mirroring its source ``AC15.<g>`` group.

(The aspirational ``AC-ledger.<entity>.<seq>`` form some docs advertise is not
adopted: the live traceability regex in
``common/ssot/ac_traceability_refs.py`` accepts only the numeric
``AC-<pkg>.<n>.<n>`` grammar that every shipped package — counter/authority/
identity — already uses.) The EPIC-015 **frontend** UI-gap ACs (``AC15.7.*``)
stay in EPIC-015: ledger is a backend-only package (``fe=None``), exactly as the
identity migration left EPIC-001's frontend rows in place. ``roadmap`` carries the
homed backend ACs (the 23 EPIC-015 processing ACs + the 61 EPIC-002 first-half
ACs of this slice); the structural invariants of the cutover stay in
``invariants`` (no tier, not matrix-constrained). Decision A — standard-preserving
move, no bar lowered.
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
        # processing — the in-transit (Processing) virtual account (#1420 slice 3b).
        # base: the account-identity value object + the transfer detection/scoring
        # policy + the TransferPair value object (all pure).
        Unit(
            name="ProcessingAccount",
            kind=Kind.AGGREGATE_ROOT,
            module="base/processing.py",
        ),
        Unit(name="TransferPair", kind=Kind.VALUE_OBJECT, module="base/processing.py"),
        # extension: the pairing domain service over persisted Processing entries
        # (the acquire/post/project verbs are its repository + read edges).
        Unit(
            name="find_transfer_pairs",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/processing.py",
        ),
    ],
    implementations={"be": "apps/backend/src/ledger", "fe": None},
    interface=[
        "AccountingError",
        "DegenerateEntryError",
        "Entry",
        "JournalRepository",
        "LedgerError",
        "Leg",
        "ProcessingAccount",
        "SqlJournalRepository",
        "TransferPair",
        "UnbalancedEntryError",
        "ValidationError",
        "calculate_account_balance",
        "calculate_account_balances",
        "create_journal_entry",
        "create_transfer_in_entry",
        "create_transfer_out_entry",
        "detect_transfer_pattern",
        "find_transfer_pairs",
        "get_or_create_processing_account",
        "get_processing_balance",
        "get_unpaired_transfers",
        "list_processing_transfer_legs",
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
            id="processing-converges-by-layer",
            statement=(
                "The processing (in-transit) account folded into the package "
                "(#1420 slice 3b): pure identity/policy in base/processing.py, impure "
                "verbs in extension/processing.py, and services/processing_account.py "
                "deleted (zero residue, no re-export shim)."
            ),
            test=(
                "tests/tooling/test_ledger_package.py"
                "::test_ledger_processing_converges_by_layer"
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
    roadmap=[
        # ── EPIC-002 double-entry core (slice 3c-ii of #1420): groups 1–12 ──
        # (was AC2.1.* … AC2.12.*; AC2.13.* … AC2.23.* land in slice 3c-iii.)
        # ── group 1: Account management (was EPIC-002 AC2.1.*) ──
        ACRecord(
            id="AC-ledger.1.1",
            statement=(
                "Creating an account with valid data persists it with the correct "
                "type, code, and ownership. Was EPIC-002 AC2.1.1."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_create_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.1.2",
            statement=(
                "An account is retrievable by id for its owner. Was EPIC-002 AC2.1.2."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_get_account_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.1.3",
            statement=(
                "Fetching a non-existent account raises a not-found error. Was "
                "EPIC-002 AC2.1.3."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_get_account_not_found"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.1.4",
            statement=(
                "Updating an existing account applies the new fields. Was EPIC-002 "
                "AC2.1.4."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_update_account_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.1.5",
            statement=(
                "Updating a non-existent account raises a not-found error. Was "
                "EPIC-002 AC2.1.5."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_update_account_not_found"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.1.6",
            statement=(
                "Listing accounts honours type/active filters. Was EPIC-002 AC2.1.6."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_list_accounts_with_filters"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 2: Journal entry creation & validation (was EPIC-002 AC2.2.*) ──
        ACRecord(
            id="AC-ledger.2.1",
            statement=(
                "A balanced double-entry (SUM(DEBIT) == SUM(CREDIT)) passes "
                "validation. Was EPIC-002 AC2.2.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_balanced_entry_passes"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.2",
            statement=(
                "An unbalanced entry is rejected by validation. Was EPIC-002 AC2.2.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_unbalanced_entry_fails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.3",
            statement=(
                "A single-line entry is rejected (a journal entry needs at least "
                "two lines). Was EPIC-002 AC2.2.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_single_line_entry_fails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.4",
            statement=(
                "Decimal amounts retain full precision through validation (no float "
                "drift). Was EPIC-002 AC2.2.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py::test_decimal_precision"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.5",
            statement=(
                "A non-base-currency line requires an fx_rate. Was EPIC-002 AC2.2.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_fx_rate_required_for_non_base_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.6",
            statement="Posting an unbalanced entry is rejected. Was EPIC-002 AC2.2.6.",
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_post_unbalanced_entry_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.2.7",
            statement=(
                "Balance validation treats an omitted line currency as the base "
                "currency. Was EPIC-002 AC2.2.7."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_missing_currency_balances_as_base_currency"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 3: Journal entry posting & voiding (was EPIC-002 AC2.3.*) ──
        ACRecord(
            id="AC-ledger.3.1",
            statement=(
                "A draft entry posts successfully (draft -> posted). Was EPIC-002 "
                "AC2.3.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_post_journal_entry_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.2",
            statement="Posting an already-posted entry is rejected. Was EPIC-002 AC2.3.2.",
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_post_journal_entry_already_posted_fails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.3",
            statement="A posted entry cannot be reposted. Was EPIC-002 AC2.3.3.",
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_posted_entry_cannot_be_reposted"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.4",
            statement=(
                "A posted entry's status is immutable against direct update. Was "
                "EPIC-002 AC2.3.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_posted_entry_status_immutable_via_direct_update"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.5",
            statement=(
                "Voiding a posted entry creates a balanced reversal entry. Was "
                "EPIC-002 AC2.3.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_void_journal_entry_creates_reversal"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.6",
            statement=(
                "Journal service operations handle non-existent entries cleanly. "
                "Was EPIC-002 AC2.3.6."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_service.py"
                "::test_journal_router_direct"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.7",
            statement=(
                "create_entry surfaces a ValidationError for unbalanced/single-line "
                "input. Was EPIC-002 AC2.3.7."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_delete_and_validation.py"
                "::test_create_unbalanced_entry_returns_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.8",
            statement=(
                "post_journal_entry error handling: not-found, wrong-user, and "
                "inactive-account paths. Was EPIC-002 AC2.3.8."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_service_errors.py"
                "::test_post_journal_entry_errors"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.9",
            statement=(
                "void_journal_entry error handling: not-found, wrong-user, and "
                "non-posted paths. Was EPIC-002 AC2.3.9."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_service_errors.py"
                "::test_void_journal_entry_errors"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.10",
            statement="post_journal_entry success path. Was EPIC-002 AC2.3.10.",
            test=(
                "apps/backend/tests/ledger/test_accounting_service_errors.py"
                "::test_post_journal_entry_success"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.11",
            statement=(
                "void_journal_entry success path produces a reversal. Was EPIC-002 "
                "AC2.3.11."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_service_errors.py"
                "::test_void_journal_entry_success"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 4: Balance calculation (was EPIC-002 AC2.4.*) ──
        ACRecord(
            id="AC-ledger.4.1",
            statement=(
                "Balance calculation for an asset account sums posted lines "
                "correctly. Was EPIC-002 AC2.4.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_calculate_balance_for_asset_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.4.2",
            statement=(
                "Balance calculation for an income account sums posted lines "
                "correctly. Was EPIC-002 AC2.4.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_calculate_balance_for_income_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.4.3",
            statement=(
                "Draft entries are excluded from balance calculation. Was EPIC-002 "
                "AC2.4.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_draft_entries_not_included_in_balance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.4.4",
            statement=(
                "Balances aggregate correctly by account type. Was EPIC-002 AC2.4.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_balances.py"
                "::test_calculate_account_balances_by_type"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.4.5",
            statement=(
                "An empty account list returns empty balances. Was EPIC-002 AC2.4.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_balances.py"
                "::test_calculate_account_balances_empty_list"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.4.6",
            statement=(
                "Account-balance calculation across types is covered end to end. "
                "Was EPIC-002 AC2.4.6."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_balances.py"
                "::test_calculate_account_balances_by_type"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 5: Accounting equation validation (was EPIC-002 AC2.5.*) ──
        ACRecord(
            id="AC-ledger.5.1",
            statement=(
                "The accounting equation holds across all five account types. Was "
                "EPIC-002 AC2.5.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_accounting_equation_holds_with_all_account_types"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.5.2",
            statement=(
                "An accounting-equation violation is detected. Was EPIC-002 AC2.5.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_accounting_equation_violation_detected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.5.3",
            statement=(
                "The accounting equation holds after a sequence of posted "
                "transactions. Was EPIC-002 AC2.5.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_accounting_equation_holds"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 6: Boundary & edge cases (was EPIC-002 AC2.6.*) ──
        ACRecord(
            id="AC-ledger.6.1",
            statement=(
                "Maximum amount boundary (999,999,999.99) is handled correctly. Was "
                "EPIC-002 AC2.6.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_max_amount_boundary"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.6.2",
            statement=(
                "Minimum amount boundary (0.01) is handled correctly. Was EPIC-002 "
                "AC2.6.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_min_amount_boundary"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.6.3",
            statement="Decimal precision loss is detected. Was EPIC-002 AC2.6.3.",
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_amount_precision_loss_detection"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.6.4",
            statement=(
                "A many-line complex entry (salary breakdown) posts balanced "
                "through the real posting path. Was EPIC-002 AC2.6.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_many_lines_complex_salary_correct"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 7: API router & error handling (was EPIC-002 AC2.7.*) ──
        ACRecord(
            id="AC-ledger.7.1",
            statement=(
                "The journal router uses flush, not commit, so the request owns the "
                "transaction. Was EPIC-002 AC2.7.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_create_journal_entry_uses_flush_not_commit"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.2",
            statement=(
                "Journal router error paths return clean errors (validation error "
                "path). Was EPIC-002 AC2.7.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_router_errors.py"
                "::test_create_entry_validation_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.3",
            statement=(
                "Journal router additional scenarios: a missing entry returns "
                "not-found. Was EPIC-002 AC2.7.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_router_additional.py"
                "::test_get_entry_not_found"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.4",
            statement=(
                "A malformed request yields a validation error (422), not a 500. "
                "Was EPIC-002 AC2.7.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_router_additional.py"
                "::test_create_entry_validation_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.5",
            statement=(
                "DELETE /{entry_id} deletes a draft entry successfully. Was "
                "EPIC-002 AC2.7.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_delete_and_validation.py"
                "::test_delete_draft_entry_success"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.6",
            statement=(
                "Voiding a journal entry via the API behaves correctly. Was "
                "EPIC-002 AC2.7.6."
            ),
            test=(
                "apps/backend/tests/api/test_journal_router.py::test_void_journal_entry"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.7.7",
            statement=(
                "Deleting a journal entry via the API is allowed only for drafts. "
                "Was EPIC-002 AC2.7.7."
            ),
            test=(
                "apps/backend/tests/api/test_journal_router.py"
                "::test_delete_journal_entry"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 8: Decimal safety (was EPIC-002 AC2.8.*) ──
        ACRecord(
            id="AC-ledger.8.1",
            statement=(
                "Monetary amounts never use float (float injection is rejected). "
                "Was EPIC-002 AC2.8.1."
            ),
            test=(
                "apps/backend/tests/accounting/test_decimal_safety.py"
                "::test_float_injection_safety"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.8.2",
            statement=(
                "Decimal precision is maintained through arithmetic. Was EPIC-002 "
                "AC2.8.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py::test_decimal_precision"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.8.3",
            statement=(
                "Scientific-notation monetary input is handled/rejected safely. Was "
                "EPIC-002 AC2.8.3."
            ),
            test=(
                "apps/backend/tests/accounting/test_decimal_safety.py"
                "::test_scientific_notation_rejection"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 9: Data model checklist coverage (was EPIC-002 AC2.9.*) ──
        ACRecord(
            id="AC-ledger.9.1",
            statement=(
                "The Account model supports the required fields and types. Was "
                "EPIC-002 AC2.9.1."
            ),
            test=(
                "apps/backend/tests/accounting/test_account_service_unit.py"
                "::test_create_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.9.2",
            statement=(
                "The JournalEntry model supports the required fields and status "
                "flow. Was EPIC-002 AC2.9.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_equation.py"
                "::test_posted_entry_cannot_be_reposted"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.9.3",
            statement=(
                "JournalLine enforces debit/credit direction and positive-amount "
                "rules. Was EPIC-002 AC2.9.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_single_line_entry_fails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.9.4",
            statement=(
                "Pydantic account/journal schemas validate their inputs. Was "
                "EPIC-002 AC2.9.4."
            ),
            test=(
                "apps/backend/tests/accounting/test_schemas.py"
                "::test_account_create_valid"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 10: API endpoint checklist coverage (was EPIC-002 AC2.10.*) ──
        ACRecord(
            id="AC-ledger.10.1",
            statement=(
                "The account endpoints (POST/GET/GET-by-id/PUT /accounts) behave "
                "correctly. Was EPIC-002 AC2.10.1."
            ),
            test=(
                "apps/backend/tests/accounting/test_accounts_endpoints.py"
                "::test_accounts_endpoints"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.10.2",
            statement=(
                "The journal-entry endpoints (POST/GET/GET-by-id) behave correctly. "
                "Was EPIC-002 AC2.10.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_endpoints.py"
                "::test_journal_entry_endpoints"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.10.3",
            statement=(
                "The posting/voiding endpoints behave correctly. Was EPIC-002 AC2.10.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_endpoints.py"
                "::test_journal_entry_endpoints"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.10.4",
            statement=(
                "API error behaviour for missing/invalid resources is correct. Was "
                "EPIC-002 AC2.10.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_journal_router_errors.py"
                "::test_create_entry_validation_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.10.5",
            statement=(
                "DELETE /statements/{id} succeeds for a valid owner. Was EPIC-002 "
                "AC2.10.5."
            ),
            test=(
                "apps/backend/tests/accounting/test_delete_endpoints.py"
                "::test_delete_statement"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 11: Must-have traceability (was EPIC-002 AC2.11.*) ──
        ACRecord(
            id="AC-ledger.11.4",
            statement=(
                "Multi-currency entries require an fx_rate on non-base lines. Was "
                "EPIC-002 AC2.11.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting.py"
                "::test_fx_rate_required_for_non_base_currency"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 12: Multi-currency ledger integrity (was EPIC-002 AC2.12.*) ──
        ACRecord(
            id="AC-ledger.12.1",
            statement=(
                "Journal-entry balance validation uses base-currency converted "
                "amounts when line currencies differ. Was EPIC-002 AC2.12.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_multicurrency_integrity.py"
                "::test_AC2_12_1_multicurrency_entry_balances_in_base_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.12.2",
            statement=(
                "Accounting-equation verification uses base-currency converted "
                "account balances. Was EPIC-002 AC2.12.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_multicurrency_integrity.py"
                "::test_AC2_12_2_accounting_equation_uses_base_currency_balances"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.12.6",
            statement=(
                "Statement validation rejects invalid statement balance and "
                "transaction states. Was EPIC-002 AC2.12.6."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_validate_balance_mismatch"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 71: Processing account creation (was EPIC-015 AC15.1.*) ──
        ACRecord(
            id="AC-ledger.71.1",
            statement=(
                "The Processing (in-transit) account is auto-created on the first "
                "get_or_create call for a user. Was EPIC-015 AC15.1.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_processing_account_created_on_first_call"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.71.2",
            statement=(
                "Processing-account creation is idempotent: repeated get_or_create "
                "calls return the same account. Was EPIC-015 AC15.1.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_processing_account_idempotent"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.71.3",
            statement=(
                "The Processing account is a system account hidden from "
                "list_accounts (is_system=true). Was EPIC-015 AC15.1.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_processing_account_hidden_from_list"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.71.4",
            statement=(
                "Each user gets their own isolated Processing account. Was "
                "EPIC-015 AC15.1.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_processing_account_per_user"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 72: Transfer entry creation (was EPIC-015 AC15.2.*) ──
        ACRecord(
            id="AC-ledger.72.1",
            statement=(
                "A transfer-OUT entry debits Processing and credits the source "
                "account (balanced double-entry); non-positive amounts and "
                "empty/whitespace descriptions are rejected. Was EPIC-015 AC15.2.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_transfer_out_to_processing"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.72.2",
            statement=(
                "A transfer-IN entry debits the destination account and credits "
                "Processing (balanced double-entry); non-positive amounts and empty "
                "descriptions are rejected. Was EPIC-015 AC15.2.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_transfer_in_from_processing"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.72.3",
            statement=(
                "A paired transfer OUT + IN nets the Processing balance to zero. "
                "Was EPIC-015 AC15.2.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_paired_transfers_zero_balance"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 73: Accounting integrity (was EPIC-015 AC15.3.*) ──
        ACRecord(
            id="AC-ledger.73.1",
            statement=(
                "An unpaired transfer leaves a non-zero Processing balance, keeping "
                "in-transit funds visible (get_unpaired_transfers + balance query). "
                "Was EPIC-015 AC15.3.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_unpaired_transfer_visible_in_processing_balance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.73.2",
            statement=(
                "The accounting equation holds after transfers through Processing "
                "(sum(accounts) + Processing is conserved). Was EPIC-015 AC15.3.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_accounting_equation_holds_with_processing"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 74: Transfer detection (was EPIC-015 AC15.4.*) ──
        ACRecord(
            id="AC-ledger.74.1",
            statement=(
                "detect_transfer_pattern identifies transfer keywords in a "
                "description (SOP-001). Was EPIC-015 AC15.4.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_detect_transfer_keywords"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.74.2",
            statement=(
                "detect_transfer_pattern returns False for a None/empty "
                "description (no false positive). Was EPIC-015 AC15.4.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_detect_transfer_no_description"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.74.3",
            statement=(
                "find_transfer_pairs auto-pairs transfers whose confidence is at or "
                "above the threshold (>= 85). Was EPIC-015 AC15.4.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_auto_pair_transfers_above_threshold"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 75: Pairing scoring functions (was EPIC-015 AC15.5.*) ──
        ACRecord(
            id="AC-ledger.75.1",
            statement=(
                "Amount scoring returns 100 for an exact match within one cent. "
                "Was EPIC-015 AC15.5.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_amount_exact_match"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.75.2",
            statement=(
                "Amount scoring degrades by tier as the gap widens (exact/close/"
                "moderate bands), e.g. within 1 SGD scores 85. Was EPIC-015 AC15.5.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_amount_close_match"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.75.3",
            statement=(
                "Description scoring returns a proportional score for a partial "
                "match (SequenceMatcher + token overlap). Was EPIC-015 AC15.5.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_description_partial_match"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.75.4",
            statement=(
                "Date-proximity scoring degrades over a 7-day window (same day 100, "
                "3 days 85, >7 days 0). Was EPIC-015 AC15.5.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_processing_account.py"
                "::test_date_three_day_diff"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 76: Reconciliation integration (was EPIC-015 AC15.6.*) ──
        ACRecord(
            id="AC-ledger.76.1",
            statement=(
                "During reconciliation, a detected transfer creates a Processing "
                "entry for the linked account (Phase 1). Was EPIC-015 AC15.6.1."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_transfer_detected_creates_processing_entry"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.2",
            statement=(
                "Transfer detection logs a warning and skips when the statement has "
                "no linked account. Was EPIC-015 AC15.6.2."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_transfer_detection_skips_when_no_account_linked"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.3",
            statement=(
                "A detected transfer-IN creates the correct Processing entry "
                "(debit destination, credit Processing). Was EPIC-015 AC15.6.3."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_transfer_in_creates_correct_processing_entry"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.4",
            statement=(
                "The auto-pairing phase pairs transfers with the same amount and "
                "date, netting the Processing balance to zero (Phase 3). Was "
                "EPIC-015 AC15.6.4."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_auto_pair_transfers_same_amount_same_date"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.5",
            statement=(
                "An unpaired transfer leaves a non-zero Processing balance after "
                "reconciliation. Was EPIC-015 AC15.6.5."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_unpaired_transfer_leaves_processing_nonzero"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.6",
            statement=(
                "Non-transfer transactions skip Phase 1 and proceed to normal "
                "matching (Phase 2), preserving existing reconciliation. Was "
                "EPIC-015 AC15.6.6."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_non_transfer_transaction_proceeds_to_normal_matching"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.76.7",
            statement=(
                "Transfer detection is idempotent: re-running matching does not "
                "create a duplicate Processing entry/match. Was EPIC-015 AC15.6.7."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_transfer_idempotency.py"
                "::test_transfer_out_duplicate_detection_skipped"
            ),
            priority="P0",
            status="done",
        ),
    ],
)
