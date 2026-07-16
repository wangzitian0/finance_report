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

``ledger`` is the first ``domain``-layer (L3) bounded context on the package
model (the double-entry bounded context). Slice 3b (#1420) folds the **processing (in-transit) account**
into the package: its pure identity + transfer detection/scoring policy live in
``base/processing.py`` (the :class:`ProcessingAccount` aggregate + ``TransferPair``
value object + ``detect_transfer_pattern``) and its impure verbs (acquire / post /
project / ``find_transfer_pairs``) in ``extension/processing.py`` — the original
``services/processing_account.py`` is deleted (zero residue). Reconciliation/
reporting consume it only through the published ``src.ledger`` interface, by id/
event (Decision B — one transaction per domain).

The package's ACs migrate into ``roadmap`` across the slice-3c sub-slices of the
cutover (#1420). **Slice 3c-i homed the EPIC-015 processing-account ACs** as
``AC-ledger.71.* … AC-ledger.76.*``. **Slice 3c-ii homed the first half of the
EPIC-002 double-entry core** — groups ``AC2.1``…``AC2.12`` → groups
``AC-ledger.1.*``…``AC-ledger.12.*`` (the leading "2" is dropped; seq preserved).
**Slice 3c-iii (this change, the final AC batch) homes the genuine double-entry
ACs of the second half** — ``AC2.13``…``AC2.16`` → groups
``AC-ledger.13.*``…``AC-ledger.16.*`` (same drop-the-"2", seq-preserved rule). It
deliberately does **not** drag the non-double-entry rows of that range into the
ledger roadmap (the #1517 mis-file lesson — validate each AC, never blanket
rename): the frontend UI ACs ``AC2.15.8``/``AC2.16.3``/``AC2.17.1`` stay in
EPIC-002 (ledger is ``fe=None``), the reporting tier-degrade ``AC2.16.4`` is a
report-layer property not a posting one, the framework-boundary contract
``AC2.18.1`` is a cross-EPIC doc-assertion test (not double-entry behaviour), and
the entire Money value-type extension ``AC2.19.*``–``AC2.23.*`` belongs to the
``audit`` package (``infra``-layer; folded from ``money`` — issue #1419), not ledger. Those rows
remain defined in EPIC-002.
In each case the package now owns the migrated ACs; the source EPIC backend
tables are deleted and replaced with a disclaimer that lists the new ids
(mirroring how identity emptied EPIC-001).

**Group-number reservation (ledger-local).** The first dotted segment of an
``AC-ledger.<group>.<seq>`` id is a bare uniqueness key (no gate reads semantics
from it), so the package reserves disjoint blocks to keep the namespace
collision-free as later slices add ACs without re-reading this file:

- **groups 1–12** — the EPIC-002 double-entry core, first half (slice 3c-ii)
  (1=account-mgmt, 2=entry-creation, 3=posting/voiding, 4=balance, 5=equation,
  6=boundary, 7=router/errors, 8=decimal-safety, 9=data-model, 10=endpoints,
  11=must-have-traceability, 12=multi-currency), each mirroring its source
  ``AC2.<g>`` group;
- **groups 13–16** — the genuine double-entry ACs of the EPIC-002 second half
  (slice 3c-iii, this change): 13=user-scoped ledger integrity,
  14=database invariant floor, 15=guided opening balances,
  16=opening-balance readiness, each mirroring its source ``AC2.<g>`` group (only
  the backend double-entry rows; the frontend/reporting/framework/money rows of
  ``AC2.15``–``AC2.23`` stay in EPIC-002 as noted above);
- **groups 17–70** — reserved for any later EPIC-002/012 double-entry ACs (not
  yet homed);
- **groups 71–76** — the EPIC-015 processing (in-transit) account, slice 3c-i
  (71=creation, 72=transfer-entry, 73=integrity, 74=detection, 75=scoring,
  76=reconciliation integration), each mirroring its source ``AC15.<g>`` group.
- **group 77** — #1866 processing front-door, explicit-currency, and balance-space
  signature surgery; **group 78** is reserved for the parallel confidence-tier
  single-owner slice.

(The aspirational ``AC-ledger.<entity>.<seq>`` form some docs advertise is not
adopted: the live traceability regex in
``common/testing/ac_traceability_refs.py`` accepts only the numeric
``AC-<pkg>.<n>.<n>`` grammar that every shipped package — counter/authority/
identity — already uses.) The EPIC-015 **frontend** UI-gap ACs (``AC15.7.*``)
stay in EPIC-015: ledger is a backend-only package (``fe=None``), exactly as the
identity migration left EPIC-001's frontend rows in place. ``roadmap`` carries the
homed backend ACs (the 23 EPIC-015 processing ACs + the 61 EPIC-002 first-half
ACs + the 18 EPIC-002 second-half double-entry ACs of slice 3c-iii); the
structural invariants of the cutover stay in ``invariants`` (no tier, not
matrix-constrained). Decision A — standard-preserving move, no bar lowered.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    ConceptRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="ledger",
    status="active",
    # Deterministic double-entry arithmetic + persistence, no LLM: a pure-code
    # (CODE-ONLY) package.
    tier="CODE-ONLY",
    # audit/observability are lower-layer (infra, L1) than ledger (domain,
    # L3), so those edges are downward. (money folded into audit — issue
    # #1419.) ``pricing`` was dropped (#1675 D5c): the former direct FX
    # revaluation import (#1610 P2's pricing.get_exchange_rate) is now
    # ``register_fx_revaluation_provider``, an inverted port wired by
    # main.py — pricing depends on extraction (ManualValuationSnapshot et
    # al.), and a direct ledger -> pricing edge would cycle
    # (ledger -> pricing -> extraction -> ledger). ``platform`` was added
    # (#1675 D6): the base ORM mixins (UUIDMixin/UserOwnedMixin/TimestampMixin)
    # moved from src/models/base.py to platform.orm.base, also a downward edge
    # (platform is infra, L1). ``extraction`` is deliberately NOT declared:
    # account_coverage.py's statement-envelope read goes through the inverted
    # ``register_statement_coverage_reader`` port (extraction is domain, L3,
    # same rank as ledger, and extraction already depends_on ledger — a direct
    # edge would cycle).
    depends_on=["audit", "observability", "platform"],
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
        # extension: the ledger's contribution to FX-scope discovery (#1641) —
        # the distinct currencies used by the user's accounts + journal lines,
        # composed by the delivery layer into pricing's crawl scopes.
        Unit(
            name="used_currencies",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/currencies.py",
        ),
        # ── ORM entities: taxonomy-only (module unset — the gate skips
        # placement checks, the llm/pricing/platform precedent from #1675 D2).
        # The mapped classes live in orm/journal.py + orm/account.py (#1675
        # D5): intra-ledger relationships (entry↔line↔account) stay; the
        # ``FK(users.id)`` tenancy anchor is a bare column, not a
        # ``relationship()``. ``JournalEntrySourceType`` is owned by ``audit``
        # (with the trust hierarchy that ranks it) and consumed downward. ──
        Unit(name="JournalEntry", kind=Kind.AGGREGATE_ROOT),
        Unit(name="JournalLine", kind=Kind.ENTITY),
        Unit(name="JournalAuditLog", kind=Kind.ENTITY),
        Unit(name="Account", kind=Kind.AGGREGATE_ROOT),
        Unit(name="AccountType", kind=Kind.VALUE_OBJECT),
        Unit(name="JournalEntryStatus", kind=Kind.VALUE_OBJECT),
        Unit(name="Direction", kind=Kind.VALUE_OBJECT),
    ],
    implementations={"be": "apps/backend/src/ledger", "fe": None},
    interface=[
        "Account",
        "AccountNotFoundError",
        "AccountType",
        "AccountingError",
        "ConfidenceTier",
        "DEFAULT_STALE_AFTER_DAYS",
        "DegenerateEntryError",
        "Direction",
        "Entry",
        "JournalAuditLog",
        "JournalEntry",
        "JournalEntryStatus",
        "JournalLine",
        "JournalRepository",
        "LedgerError",
        "Leg",
        "ProcessingAccount",
        "ProcessingCurrencyConflictError",
        "RevaluationError",
        "SqlJournalRepository",
        "StatementCoverageRow",
        "TransferAccountCurrencyMismatchError",
        "TransferPair",
        "UnbalancedEntryError",
        "ValidationError",
        "account_service",
        "calculate_account_balance",
        "calculate_account_balances",
        "calculate_account_balances_in_base_currency",
        "calculate_unrealized_fx_gains",
        "create_journal_entry",
        "create_transfer_in_entry",
        "create_transfer_out_entry",
        "derive_confidence_tier",
        "detect_transfer_pattern",
        "find_transfer_pairs",
        "get_account_statement_coverage",
        "get_opening_balance_readiness",
        "get_or_create_processing_account",
        "get_processing_balance",
        "get_unpaired_transfers",
        "list_processing_transfer_legs",
        "post_entry",
        "post_journal_entry",
        "post_opening_balance_entry",
        "register_fx_revaluation_provider",
        "register_statement_coverage_reader",
        "used_currencies",
        "worst_confidence_tier",
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
        ACRecord(
            id="AC-ledger.fx-port.1",
            statement=(
                "Ledger's FX revaluation registration exposes the exact pricing "
                "lookup shape without Callable[..., Any] erasure."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.78.1",
            statement=(
                "ConfidenceTier owns the one worst_confidence_tier rank function; reporting and "
                "advisor consume it with explicit empty-input defaults, and unknown tiers fail "
                "closed as less trusted than every known tier."
            ),
            test=(
                "apps/backend/tests/ledger/test_confidence_tier_owner.py"
                "::test_AC_ledger_78_1_worst_confidence_tier_is_single_homed"
            ),
            priority="P1",
            status="done",
        ),
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
        ACRecord(
            id="AC-ledger.3.12",
            statement=(
                "Voiding a posted entry preserves the historical base-currency "
                "basis encoded by its line currencies and FX rates, even after "
                "the effective base currency changes."
            ),
            test=(
                "apps/backend/tests/ledger/test_multicurrency_integrity.py"
                "::test_void_preserves_historical_base_after_effective_currency_change"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.3.13",
            statement=(
                "Voiding fails closed when every historical line carries an FX rate "
                "and the original base-currency basis cannot be recovered."
            ),
            test=(
                "apps/backend/tests/ledger/test_multicurrency_integrity.py"
                "::test_void_rejects_all_fx_entry_without_historical_basis"
            ),
            priority="P0",
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
        # ── EPIC-002 double-entry core (slice 3c-iii of #1420): groups 13–16 ──
        # (the second half of EPIC-002; was AC2.13.* … AC2.16.*, leading "2"
        # dropped, sequence preserved. The non-double-entry AC2.* rows — the
        # frontend UI ACs AC2.15.8/2.16.3/2.17.1, the reporting tier-degrade
        # AC2.16.4, the framework-boundary doc-contract AC2.18.1, and the whole
        # Money-extension block AC2.19.*–AC2.23.* — are NOT double-entry and stay
        # defined in EPIC-002.)
        # ── group 13: User-scoped ledger integrity (was EPIC-002 AC2.13.*) ──
        ACRecord(
            id="AC-ledger.13.1",
            statement=(
                "Manual journal creation rejects lines using another user's "
                "account. Was EPIC-002 AC2.13.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_AC2_13_1_create_journal_entry_rejects_cross_user_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.13.2",
            statement=(
                "Posting validates that every line account belongs to the entry "
                "owner. Was EPIC-002 AC2.13.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_AC2_13_2_journal_lines_reject_cross_user_account_at_db_boundary"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.13.3",
            statement=(
                "Balance aggregation requires account and entry ownership to "
                "match. Was EPIC-002 AC2.13.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_accounting_integration.py"
                "::test_AC2_13_3_balance_queries_ignore_cross_user_entry_headers"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 14: Database ledger invariant floor (was EPIC-002 AC2.14.*) ──
        ACRecord(
            id="AC-ledger.14.1",
            statement=(
                "PostgreSQL rejects posted/reconciled entries with fewer than two "
                "lines even when service validation is bypassed. Was EPIC-002 "
                "AC2.14.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_ledger_schema_invariants.py"
                "::test_AC2_14_1_posted_entry_requires_two_lines_at_database_boundary"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.14.2",
            statement=(
                "PostgreSQL rejects posted/reconciled entries whose debits and "
                "credits do not balance after base-currency conversion. Was "
                "EPIC-002 AC2.14.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_ledger_schema_invariants.py"
                "::test_AC2_14_2_posted_entry_must_balance_in_base_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.14.3",
            statement=(
                "PostgreSQL rejects posted/reconciled non-base-currency lines "
                "without a positive FX rate. Was EPIC-002 AC2.14.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_ledger_schema_invariants.py"
                "::test_AC2_14_3_non_base_posted_lines_require_positive_fx_rate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.14.4",
            statement=(
                "PostgreSQL blocks direct update/delete of posted/reconciled "
                "entries and lines while draft entries remain editable. Was "
                "EPIC-002 AC2.14.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_ledger_schema_invariants.py"
                "::test_AC2_14_4_posted_entries_and_lines_are_immutable_but_drafts_are_editable"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.14.5",
            statement=(
                "Voiding a posted entry preserves a non-null immutable reversal "
                "relationship instead of deleting or editing posted lines. Was "
                "EPIC-002 AC2.14.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_ledger_schema_invariants.py"
                "::test_AC2_14_5_void_transition_requires_reversal_relationship"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.14.6",
            statement=(
                "Account deletion blocked by the immutability invariant "
                "(posted/reconciled entries) returns a clean HTTP 409, not a "
                "leaked 500. Was EPIC-002 AC2.14.6."
            ),
            test=(
                "apps/backend/tests/api/test_users_router.py"
                "::test_delete_user_with_immutable_entries_returns_409"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 15: Guided opening balances (was EPIC-002 AC2.15.*) ──
        # (AC2.15.8 is the frontend OpeningBalanceModal test — fe=None, so it
        # stays defined in EPIC-002, like the EPIC-015 AC15.7.* frontend block.)
        ACRecord(
            id="AC-ledger.15.1",
            statement=(
                "POST /api/accounts/opening-balances posts one balanced entry that "
                "increases each account to its opening balance on its normal side "
                "and offsets the net into a system Opening Balance Equity account; "
                "the as-of balance sheet reflects the starting position with the "
                "accounting equation intact. Was EPIC-002 AC2.15.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.2",
            statement=(
                "A single asset opening balance offsets entirely into Opening "
                "Balance Equity, keeping the entry balanced. Was EPIC-002 AC2.15.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_2_single_asset_opening_balance_offsets_into_equity"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.3",
            statement=(
                "An opening balance for a non-owned or unknown account is "
                "rejected. Was EPIC-002 AC2.15.3."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_3_unknown_account_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.4",
            statement=(
                "An opening balance establishes a starting position, not a delta: "
                "it is rejected when an affected account already has posted "
                "activity before the opening date. Was EPIC-002 AC2.15.4."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.5",
            statement=(
                "Opening balances are accepted only in the base currency, with a "
                "clear error rather than a confusing FX-rate failure. Was EPIC-002 "
                "AC2.15.5."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_5_non_base_currency_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.6",
            statement=(
                "An opening balance into an account whose currency differs from "
                "the request currency is rejected, so journal lines cannot be "
                "mis-stamped. Was EPIC-002 AC2.15.6."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_6_account_currency_mismatch_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.15.7",
            statement=(
                "Opening balances may only target user-managed accounts; a system "
                "account (e.g. Processing) cannot be set via this endpoint even "
                "though the entry is SYSTEM-typed. Was EPIC-002 AC2.15.7."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance.py"
                "::test_AC2_15_7_system_account_target_is_rejected"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 16: Opening-balance readiness nudge (was EPIC-002 AC2.16.*) ──
        # (Only the backend ledger-activity detection ACs migrate. AC2.16.3 is the
        # frontend nudge test — fe=None — and AC2.16.4 is a reporting-layer
        # tier-degrade test, not double-entry posting; both stay in EPIC-002.)
        ACRecord(
            id="AC-ledger.16.1",
            statement=(
                "get_opening_balance_readiness reports needs_opening_balance=True "
                "only when the user has posted activity and no opening-balance "
                "entry on or before its earliest date (no activity, an opening "
                "entry before activity, or a mis-dated opening entry after "
                "activity are all distinguished). Was EPIC-002 AC2.16.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance_readiness.py"
                "::test_AC2_16_1_activity_without_opening_entry_needs_opening_balance"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.16.2",
            statement=(
                "GET /api/accounts/opening-balance-readiness exposes the readiness "
                "signal to the UI. Was EPIC-002 AC2.16.2."
            ),
            test=(
                "apps/backend/tests/ledger/test_opening_balance_readiness.py"
                "::test_AC2_16_2_readiness_endpoint_returns_status"
            ),
            priority="P1",
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
                "Transfer detection skips (creates no Processing entry and yields no "
                "match) when the statement has no linked account. Was EPIC-015 "
                "AC15.6.2."
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
        # AC-ledger.* migrated from EPIC-012 groups 12.34 (#1419-pattern AC move).
        ACRecord(
            id="AC-ledger.34.1",
            statement=(
                "Entry/Leg make double-entry a value object: a balanced "
                "transfer/multi-leg entry constructs; an unbalanced one raises "
                "UnbalancedEntryError; balance is checked **per currency**; legs "
                "must be positive Money; empty entries raise. Was EPIC-012 "
                "AC12.34.1."
            ),
            test=(
                "apps/backend/tests/ledger/test_entry.py"
                "::test_AC12_34_1_balanced_entry_constructs"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.34.2",
            statement=(
                "The ledger module converges by layer — base/ (the Entry/Leg "
                "nouns) + extension/ (the post_entry verb + the journal "
                "Repository adapter) + data/ (the balance projection) — and "
                "exports Entry/Leg/post_entry/UnbalancedEntryError (the retired "
                "types/ops/store  dirs are gone; cutover #1420 slice 3a). Was "
                "EPIC-012 AC12.34.2."
            ),
            test=(
                "tests/tooling/test_ledger_module.py"
                "::test_AC12_34_2_ledger_module_converges_by_role"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.34.3",
            statement=(
                "Layer-DAG rule: the model layer imports no service (no upward "
                "edge / import cycle); derive_confidence_tier lives in the model "
                "and the service re-exports it (the old models.journal → "
                "services.confidence_tier cycle is removed). Was EPIC-012 "
                "AC12.34.3."
            ),
            test=(
                "tests/tooling/test_ledger_module.py"
                "::test_AC12_34_3_model_layer_never_imports_a_service"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.34.4",
            statement=(
                "Adoption: investment buy/sell/dividend build typed Entry and "
                "post via ledger.post_entry instead of hand-rolling balanced "
                "lines_data dicts (the legacy create_journal_entry/_post_and_load "
                "path is gone from the service). Was EPIC-012 AC12.34.4."
            ),
            test=(
                "tests/tooling/test_ledger_module.py"
                "::test_AC12_34_4_investment_postings_use_ledger_post"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.34.5",
            statement=(
                "Every computed/transfer posting path gates balance through "
                "Entry: opening-balance, fx-revaluation, and processing-account "
                "transfers construct an Entry before persisting (fx-revaluation "
                "and processing-account previously wrote raw JournalLines with no "
                "balance validation at all). The remaining raw site review_queue "
                "validates via validate_journal_balance/_posting_invariants; "
                "reconciliation_audit is a deterministic audit fixture. Was "
                "EPIC-012 AC12.34.5."
            ),
            test=(
                "tests/tooling/test_ledger_module.py"
                "::test_AC12_34_5_remaining_posting_paths_guard_balance_with_entry"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.34.6",
            statement=(
                "The journal write pipeline "
                "(create_journal_entry/post_journal_entry/void_journal_entry + "
                "validators) lives in the ledger package "
                "(ledger/extension/repository.py, behind the JournalRepository "
                "port); ledger.extension.post depends down on it instead of up on "
                "services.accounting. After the package cutover (#1420 slice 3a) "
                "NO services.accounting re-export shim survives — callers import "
                "the pipeline + ValidationError from the published ledger "
                "interface (from src.ledger import ...), zero residue. Was "
                "EPIC-012 AC12.34.6."
            ),
            test=(
                "tests/tooling/test_ledger_module.py"
                "::test_AC12_34_6_ledger_owns_posting_pipeline_no_upward_edge"
            ),
            priority="P1",
            status="done",
        ),
        # ── group journeys: account CRUD + core financial journeys, E2E
        # (migrated from EPIC-008 AC8.2.2-5/.3/.11, migration closeout
        # continuation, #1663 / #1707) ──
        ACRecord(
            id="AC-ledger.journeys.1",
            statement="Creating a cash asset account via the API returns the correct type/currency/active state.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_create_cash_account",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.2",
            statement="Creating a bank asset account via the API succeeds with the correct type.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_create_bank_account",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.3",
            statement="Updating an account's name via the API reflects the new name.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_update_account",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.4",
            statement="Deleting an account with no transactions removes it (204), and a subsequent GET returns 404.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_delete_account",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.5",
            statement="A simple two-account expense entry is created in draft status with correct amounts.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_simple_expense_entry",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.6",
            statement="Voiding a posted journal entry transitions it to void state.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_void_journal_entry",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.7",
            statement="Posting a draft journal entry transitions it to posted state.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_post_draft_entry",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.8",
            statement="An unbalanced journal entry (debits != credits) is rejected.",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_unbalanced_journal_entry_rejection"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.9",
            statement="Journal entry create/read/update/delete via the API round-trips correctly end to end.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_journal_entry_crud",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.10",
            statement="Recording income posts a balanced entry crediting the income account.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_income_recording",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.11",
            statement="A credit card spend posts a balanced entry against the liability account.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_credit_card_spend",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.12",
            statement="A credit card repayment posts a balanced entry reducing the liability.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_credit_card_repayment",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.13",
            statement="An internal transfer between two of the user's own accounts posts a balanced entry.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_internal_transfer",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.journeys.14",
            statement="A split transaction across multiple expense categories posts one balanced multi-line entry.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_split_transaction",
            priority="P0",
            status="done",
        ),
        # ── group fxrevaluation: FX revaluation provider error-path unit gates
        # (migrated from EPIC-008 AC8.12.1-3, migration closeout continuation,
        # #1663 / #1707) ──
        ACRecord(
            id="AC-ledger.fxrevaluation.1",
            statement="A liability account's unrealized FX gain/loss returns the negated net balance.",
            test=(
                "apps/backend/tests/reporting/test_fx_revaluation.py"
                "::test_returns_negated_balance_for_liability_account"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fxrevaluation.2",
            statement="A SQLAlchemyError raised during the revaluation flush is wrapped in RevaluationError.",
            test=(
                "apps/backend/tests/reporting/test_fx_revaluation.py"
                "::test_flush_error_raises_revaluation_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fxrevaluation.3",
            statement="An account whose unrealized-FX calculation returns None is skipped, not errored.",
            test="apps/backend/tests/reporting/test_fx_revaluation.py::test_none_revaluation_skipped",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.77.1",
            statement=(
                "A brand-new user can register, log in, create their first "
                "ledger accounts, post a first manual journal entry, and the "
                "accounting equation stays balanced end to end. Was EPIC-001 "
                "AC1.9.1 (migration closeout wave 3, #1663)."
            ),
            test=(
                "apps/backend/tests/integration/test_onboarding_e2e.py"
                "::test_AC1_9_1_first_run_registration_account_entry_journey"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        # ── group processing: Processing/in-transit account summary (was
        # EPIC-015 AC15.7.1, #1821 Wave A pending-package move) ──
        ACRecord(
            id="AC-ledger.processing.1",
            statement=(
                "GET /api/accounts/processing/summary returns "
                "{pending_count, pending_total, current_balance, currency, "
                "oldest_pending_date}."
            ),
            # was AC15.7.1
            test=(
                "apps/backend/tests/ledger/test_processing_account_endpoints.py"
                "::test_processing_summary_aggregates_unpaired"
            ),
            priority="P1",
            status="done",
        ),
        # ── group api-vectors: backend-owned API response conformance
        # vectors (#1827 G-contract-reddens, pattern from #1167). The wire
        # shape of GET /api/accounts is committed as
        # common/ledger/conformance/vectors.json; the backend drift test
        # recomputes it and the frontend loads the same file as mock data. ──
        ACRecord(
            id="AC-ledger.api-vectors.1",
            statement=(
                "The serialized GET /api/accounts response "
                "(ListResponse[AccountResponse] wire shape, decimal-string "
                "balances) recomputed from fixed deterministic inputs equals "
                "the committed common/ledger/conformance/vectors.json, so a "
                "serializer change without vector regeneration reds CI "
                "(#1827)."
            ),
            test=(
                "apps/backend/tests/schemas/test_api_response_vectors.py"
                "::test_AC_ledger_api_vectors_1_accounts_list_matches_committed_vector"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.api-vectors.2",
            statement=(
                "The frontend accounts page test consumes the committed "
                "ledger conformance vector verbatim as its mock data (via "
                "the shared fixture helper), so a regenerated breaking wire "
                "shape reds the frontend suite (#1827)."
            ),
            test=(
                "apps/frontend/src/__tests__/accountsPage.test.tsx"
                "::AC16.15.2 renders grouped accounts and supports type filters"
            ),
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ACRecord(
            id="AC-ledger.fe-accounts-journal.1",
            statement="Accounts page renders loading and error retry states",
            # was AC16.15.1
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.1 renders loading and error retry states",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.2",
            statement="Accounts page renders grouped account cards and type filters on successful fetch",
            # was AC16.15.2
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.2 renders grouped accounts and supports type filters",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.3",
            statement="Accounts page delete action confirms and calls delete API with success toast",
            # was AC16.15.3
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.3 delete action confirms and calls delete API with success toast",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.4",
            statement="Edit button opens modal with account data",
            # was AC16.15.7
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.7 edit button opens modal with account data",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.5",
            statement="Add Account button opens create modal",
            # was AC16.15.8
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.8 Add Account button opens create modal",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.6",
            statement="Modal onSuccess triggers account list refresh",
            # was AC16.15.9
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.9 modal onSuccess triggers account list refresh",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.7",
            statement="Modal onClose closes modal and clears editing state",
            # was AC16.15.10
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC16.15.10 modal onClose closes modal and clears editing state",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.8",
            statement="Journal page renders error state and retries loading entries",
            # was AC16.16.5
            test="apps/frontend/src/__tests__/journalPage.test.tsx::AC16.16.5 renders error state and retries loading entries",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.9",
            statement="Journal page filters entries by status and renders totals",
            # was AC16.16.6
            test="apps/frontend/src/__tests__/journalPage.test.tsx::AC16.16.6 filters entries by status and renders totals",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.10",
            statement="Journal page draft actions post and delete entries with API calls",
            # was AC16.16.7
            test="apps/frontend/src/__tests__/journalPage.test.tsx::AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.11",
            statement="Journal page void flow submits reason and refreshes entries",
            # was AC16.16.8
            test="apps/frontend/src/__tests__/journalPage.test.tsx::AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.12",
            statement="Account form modal create mode submits normalized payload and closes on success",
            # was AC16.21.1
            test="apps/frontend/src/__tests__/accountFormModalComponent.test.tsx::AC16.21.1 create mode submits normalized payload and closes on success",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.13",
            statement="Account form modal edit mode pre-fills values and submits update payload",
            # was AC16.21.2
            test="apps/frontend/src/__tests__/accountFormModalComponent.test.tsx::AC16.21.2 edit mode pre-fills values and submits update payload",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.14",
            statement="Account form modal surfaces API errors and field validation feedback",
            # was AC16.21.3
            test="apps/frontend/src/__tests__/accountFormModalComponent.test.tsx::AC16.21.3 shows validation and API errors in create flow",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.15",
            statement="Journal entry form loads account options and enforces balanced double-entry totals",
            # was AC16.21.4
            test="apps/frontend/src/__tests__/journalEntryFormComponent.test.tsx::AC16.21.4 loads account options and shows balanced/unbalanced state",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.16",
            statement="Journal entry form creates draft entries with normalized line amounts and optional posting",
            # was AC16.21.5
            test="apps/frontend/src/__tests__/journalEntryFormComponent.test.tsx::AC16.21.5 submits create-draft payload with normalized amounts",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.17",
            statement="Journal entry form supports dynamic line add/remove and submit-time error handling",
            # was AC16.21.6
            test="apps/frontend/src/__tests__/journalEntryFormComponent.test.tsx::AC16.21.6 supports add and remove line interactions",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts-journal.18",
            statement="Journal entry details expose line account, direction, amount, and currency as mobile line cards",
            # was AC16.25.3
            test="apps/frontend/src/__tests__/detailViewComponents.test.tsx::AC16.25.3 journal entry details mobile line cards expose all line fields",
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ACRecord(
            id="AC-ledger.fe-accounts2.1",
            statement="Accounts page mobile filters and account rows avoid document-level horizontal scroll and content overlap",
            # was AC2.17.1
            test="apps/frontend/playwright/mobile-ux.spec.ts::AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.1",
            statement=(
                'Dashboard "Processing / In-Transit" card renders the four fields '
                "with currency code, the signed current balance, and a warning "
                "when that balance is non-zero."
            ),
            # was AC15.7.2 + AC15.7.8
            test="apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx::AC15.7.2 / AC15.7.8 — ProcessingSummaryCard renders fields and current balance warning",
            priority="P2",
            status="done",
            vision_anchor="decision-5-processing-account",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts2.2",
            statement="The Accounts page offers a guided opening-balance flow: a non-accountant enters an as-of date and a starting balance per eligible (active, non-income/expense) account, and the UI posts the balances map to `POST /api/accounts/opening-balances` — never hand-written journal lines — validating positive two-decimal amounts and surfacing backend errors instead of silently closing",
            # was AC2.15.8
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC2.15.8 opens the guided opening-balance modal and refreshes on success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.2",
            statement="Card click-through navigates to `/processing` listing pending transfers (existing or new page) with line items `{from_account, to_account, amount, initiated_date, days_outstanding}`",
            # was AC15.7.3
            test="apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx::AC15.7.3 — /processing listing renders pending transfers",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts2.3",
            statement="The Accounts page shows a warning nudge (with a CTA that opens the guided flow) when opening balances are missing, and hides it once they are recorded",
            # was AC2.16.3
            test="apps/frontend/src/__tests__/accountsPage.test.tsx::AC2.16.3 shows a readiness nudge and opens the modal when opening balances are missing",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.3",
            statement="Pending entries older than 7 days render a warning badge on the listing row",
            # was AC15.7.4
            test="apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx::AC15.7.4 — warning badge for >7 day pending",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.4",
            statement="Frontend test mounts ProcessingSummaryCard and asserts `pending_count` + `pending_total` labels render",
            # was AC15.7.5
            test="apps/frontend/src/__tests__/uiGapAudit.processingVisibility.test.tsx::AC15.7.5 — ProcessingSummaryCard mount test",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-accounts2.4",
            statement="ConfidenceBadge mounted on every transaction row in Stage 1 review, Stage 2 listing, and processing-account listing; reads `confidence_tier` from API response",
            # was AC18.5.2
            test="apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.2 — Journal page surfaces ConfidenceBadge tier",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.5",
            statement="Processing is discoverable as a card in the Audit hub (`/audit`), superseding the old sidebar entry",
            # was AC15.7.6
            test="apps/frontend/src/__tests__/auditHub.test.tsx::AC15.7.6 aggregates the verify-on-demand machinery (incl. Processing) as deep-linking cards",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.fe-processing.6",
            statement="The sidebar Processing badge was removed with the Advanced drawer; the non-zero-balance warning is carried by the Home Processing card and attention inbox",
            # was AC15.7.7
            test="apps/frontend/src/__tests__/sidebarAndTabs.test.tsx::AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)",
            priority="P1",
            status="done",
        ),
        # #1866 PR-A: package-local signature surgery guarantees.
        ACRecord(
            id="AC-ledger.signature.1",
            statement=(
                "Processing transfer legs are built once and persisted through post_entry, so "
                "the standard balanced-entry, account-ownership, and posting invariants apply."
            ),
            test=(
                "apps/backend/tests/ledger/test_signature_surgery.py"
                "::test_processing_transfers_use_the_post_entry_front_door"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.signature.2",
            statement=(
                "System-account and processing APIs require callers to supply the owning "
                "currency explicitly; the processing path has no hidden SGD or configuration default."
            ),
            test=(
                "apps/backend/tests/ledger/test_signature_surgery.py"
                "::test_processing_apis_require_explicit_currency"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.signature.3",
            statement=(
                "Nominal account balances and base-currency account balances use separate "
                "typed functions with caller-supplied explicit base currency, so a boolean or "
                "process default cannot silently change result semantics."
            ),
            test=(
                "apps/backend/tests/ledger/test_signature_surgery.py"
                "::test_account_balance_currency_spaces_are_explicit"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ledger.signature.4",
            statement=(
                "Caller-supplied operation currency reaches both Python journal "
                "validation and the PostgreSQL deferred ledger invariant."
            ),
            test=(
                "apps/backend/tests/ledger/test_multicurrency_integrity.py"
                "::test_effective_usd_base_drives_posting_trigger_and_equation"
            ),
            priority="P0",
            status="done",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="accounting_equation",
            owner="common/ledger/readme.md#accounting-equation",
            description="Assets = Liabilities + Equity + (Income - Expenses) invariant.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "apps/backend/tests/ledger/test_accounting_equation.py",
            ],
            family="accounting",
        ),
        ConceptRecord(
            key="decimal_monetary_rule",
            owner="common/ledger/readme.md#decimal-rule",
            description=(
                "All monetary amounts MUST use Python Decimal, never float; money rounds via "
                "banker's HALF_EVEN."
            ),
            cross_refs=[
                "AGENTS.md",
                "docs/agents/red-lines.md",
                "apps/backend/tests/accounting/test_decimal_safety.py",
            ],
            proofs=[
                "apps/backend/tests/accounting/test_decimal_safety.py",
                "apps/backend/tests/audit/money/test_money.py",
            ],
            family="accounting",
        ),
        ConceptRecord(
            key="double_entry_bookkeeping",
            owner="common/ledger/readme.md#entry-balance",
            description="Every JournalEntry must have balanced debits and credits.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "apps/backend/tests/ledger/test_accounting.py",
            ],
            family="accounting",
        ),
        ConceptRecord(
            key="processing_account",
            owner="common/ledger/readme.md",
            description="Unconfirmed in-transit funds; balance 0 means transfer paired.",
            cross_refs=[
                "common/extraction/confirmation-workflow.md",
                "common/reconciliation/reconciliation.md",
            ],
            family="accounting",
        ),
        ConceptRecord(
            key="transaction_boundary",
            owner="common/ledger/readme.md#async-tx-boundary",
            description="Routers commit(); Services flush() only.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "apps/backend/tests/ledger/test_accounting_integration.py",
            ],
            family="accounting",
        ),
    ],
)

# Test roots this package owns (aggregated into the execution matrix's
# generated ownership view; see common/testing/matrix.py, issue #1558).
TEST_ROOTS: tuple[str, ...] = (
    "apps/backend/tests/ledger/",
    "tests/tooling/test_ledger_module.py",
    "tests/tooling/test_ledger_package.py",
)
