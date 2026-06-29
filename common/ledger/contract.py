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
cutover (#1420). **Slice 3c-i (this change) homes the EPIC-015 processing-account
ACs** as ``AC-ledger.71.* … AC-ledger.76.*`` — the package now owns them; the
EPIC-015 backend tables are deleted and replaced with a disclaimer that lists the
new ids (mirroring how identity emptied EPIC-001). The EPIC-002 double-entry ACs
(slice 3c-ii/iii) land later under the **lower** group numbers.

**Group-number reservation (ledger-local).** The first dotted segment of an
``AC-ledger.<group>.<seq>`` id is a bare uniqueness key (no gate reads semantics
from it), so the package reserves disjoint blocks to keep the namespace
collision-free as later slices add ACs without re-reading this file:

- **groups 1–70** — the EPIC-002/012 double-entry core (slices 3c-ii/iii, not yet
  homed);
- **groups 71–76** — the EPIC-015 processing (in-transit) account, this slice
  (71=creation, 72=transfer-entry, 73=integrity, 74=detection, 75=scoring,
  76=reconciliation integration), each mirroring its source ``AC15.<g>`` group.

(The aspirational ``AC-ledger.<entity>.<seq>`` form some docs advertise is not
adopted: the live traceability regex in
``common/ssot/ac_traceability_refs.py`` accepts only the numeric
``AC-<pkg>.<n>.<n>`` grammar that every shipped package — counter/authority/
identity — already uses.) The EPIC-015 **frontend** UI-gap ACs (``AC15.7.*``)
stay in EPIC-015: ledger is a backend-only package (``fe=None``), exactly as the
identity migration left EPIC-001's frontend rows in place. ``roadmap`` carries the
23 backend ACs; the structural invariants of the cutover stay in ``invariants``
(no tier, not matrix-constrained). Decision A — standard-preserving move, no bar
lowered.
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
