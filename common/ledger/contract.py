"""Machine-checkable PackageContract for ``ledger``."""

from __future__ import annotations

from common.meta.package_contract import (
    CommandBoundary,
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="ledger",
    status="active",
    tier="CODE-ONLY",
    depends_on="audit observability platform pricing".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/ledger", "fe": None},
    context=ContextScope(
        purpose="Own double-entry financial facts.",
        in_scope=[
            "Ledger account, journal-entry, journal-line.",
            "Double-entry, currency-balance, posting, voiding, and immutability rules.",
            "Ledger-owned decision-anchored financial-write boundary and balance projections.",
        ],
        out_of_scope=[
            "Shared money, provenance, or assurance-language ownership.",
            "Generic persistence, telemetry, event delivery, or external FX-provider ownership.",
            "Reconciliation matching, report presentation.",
        ],
    ),
    relationships=rels(
        "ledger",
        """
audit|published-language|Uses audit-owned Money, Currency, source-type.
audit|consumer-port|Consumes audit TraceRecord repository/emitter ports for decision evidence.
observability|published-language|Uses published safe logging language for ledger operational diagnostics.
platform|composition|Uses platform persistence mixins for ledger ORM rows.
pricing|published-language|Uses pricing FX-rate lookup for read-only unrealized FX gain/loss calculation.
""",
    ),
    units=units(
        """
Entry|agg|base/types/entry.py
Leg|vo|base/types/entry.py
EntryFactory|fac|base/types/entry.py
post_entry|svc|extension/post.py
DecisionAnchor|vo|base/decision_anchor.py
@svc|extension/anchored_posting.py|submit_anchored_journal_entry current_anchored_journal_entries ledger_trace_policy_registry
@vo|base/contribution.py|JournalLineContribution ResolvedJournalContribution
list_journal_contributions|svc|extension/contribution.py
AccountBalance|proj|data/balance.py
ProcessingAccount|agg|base/processing.py
TransferPair|vo|base/processing.py
find_transfer_pairs|svc|extension/processing.py
used_currencies|svc|extension/currencies.py
@agg|-|JournalEntry Account
@ent|-|JournalLine JournalAuditLog
@vo|-|AccountType JournalEntryStatus Direction
"""
    ),
    interface="""
OpeningPosition list_opening_positions Account AccountNotFoundError AccountType
AccountingError AnchoredJournalCommand ConfidenceTier DEFAULT_STALE_AFTER_DAYS
DegenerateEntryError DecisionAnchor DecisionAnchorError Direction Entry
JournalAuditLog JournalEntry JournalEntryAuthorityState JournalEntryStatus
JournalLine JournalLineContribution LedgerError Leg MAX_JOURNAL_LINE_AMOUNT
MAX_JOURNAL_LINE_FX_RATE PROCESSING_ACCOUNT_CODE ProcessingAccount
ProcessingCurrencyConflictError ResolvedJournalContribution RevaluationError
StatementCoverageRow TransferAccountCurrencyMismatchError TransferPair
UnbalancedEntryError ValidationError account_service active_journal_entry_filter
calculate_account_balance calculate_account_balances
calculate_account_balances_in_base_currency calculate_reconciliation_adjustment
calculate_unrealized_fx_gains current_anchored_journal_entries
find_processing_account create_transfer_in_entry create_transfer_out_entry
derive_confidence_tier detect_transfer_pattern find_transfer_pairs fit_journal_memo
get_account_statement_coverage get_opening_balance_readiness
get_or_create_processing_account get_processing_balance get_unpaired_transfers
initialize_opening_positions journal_command_target ledger_trace_policy_registry
list_journal_contributions list_processing_transfer_legs post_entry
submit_anchored_journal_entries submit_anchored_journal_entry
submit_manual_journal_entry submit_system_journal_entry
validate_manual_journal_entry_for_post post_journal_entry post_opening_balance_entry
register_statement_coverage_reader used_currencies worst_confidence_tier
validate_fx_rates validate_journal_balance validate_journal_line_amount
validate_journal_line_fx_rate validate_journal_line_tags
validate_journal_posting_invariants validate_line_account_ownership
verify_accounting_equation void_journal_entry
""".split(),
    events=[],
    command_boundaries=[
        CommandBoundary(
            symbol="AnchoredJournalCommand",
            version="2",
            proof="apps/backend/tests/ledger/test_decision_anchor.py::test_submit_anchored_journal_entry_is_idempotent_and_conflicts_on_new_authority",
        )
    ],
    invariants=invs(
        """
balanced-entry-unconstructable|An Entry is balanced per currency at construction.|$be/ledger/test_entry.py::test_AC12_34_1_unbalanced_entry_is_unconstructable
@$t/test_ledger_package.py
converges-by-layer|The package converges into base/ + extension/ + data/.|test_ledger_converges_by_layer
processing-converges-by-layer|The processing account folded into the package.|test_ledger_processing_converges_by_layer
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_ledger_only_all_is_the_published_language
base-layer-pure|The base/ layer never imports the package's own extension/ or data/, the ORM session, or the FastAPI/transport edge.|test_ledger_base_layer_is_pure
anchored-persistence-boundary|Only the extension's decision-anchored command service may call the private journal persistence sink.|test_ledger_anchored_persistence_boundary
passes-own-governance-gate|Check_package_contract validates ledger with no violations.|test_ledger_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "ledger",
        """
@$be/ledger/test_opening_position.py|P0
opening-position.8|Source-backed starting stock.|test_source_opening_retains_pdf_ancestor
opening-position.1|Manual and automatic source approval establish the same account starting stock.|test_manual_approval_posts_opening
opening-position.2|Concurrent repeated initialization creates one opening position and one journal entry per account.|test_concurrent_opening_initialization
opening-position.3|Readiness checks each account and accepts explicit zero initialization.|test_zero_and_per_account_readiness
opening-position.4|Foreign-currency opening positions preserve original money and historical FX.|test_foreign_opening_and_missing_rate
opening-position.5|Opening positions retain immutable evidence and do not reinterpret voided or unproven history as initialized.|test_opening_projection_and_immutability
opening-position.6|A trusted opening position is a dated stock with a public evidence-bearing projection, never a fabricated prior-day flow.|test_opening_projection_preserves_date
statement-category.1|The accepted economic category is pinned on the counter-account journal command.|test_statement_category_is_pinned
@$be/ledger/test_opening_position_query_budget.py|P1
opening-position.10|The opening-position projection issues a fixed number of SQL statements that does not grow with the count of opening records.|test_AC_ledger_opening_position_10_projection_reads_fixed_statements_and_only_opening_entries
opening-position.11|The opening-position projection runs the current-authority projection once, for the decisions of the opening records, of their journal entries and of the historical system opening entries only.|test_AC_ledger_opening_position_11_projection_reads_only_the_decisions_it_needs
@$be/accounting/test_accounts_service.py|P0
1.1|Creating an account with valid data persists it with the correct type, code.|test_create_account
1.2|An account is retrievable by id for its owner.|test_get_account_success
1.3|Fetching a non-existent account raises a not-found error.|test_get_account_not_found
1.4|Updating an existing account applies the new fields.|test_update_account_success
1.5|Updating a non-existent account raises a not-found error.|test_update_account_not_found
1.6|Listing accounts honours type/active filters.|test_list_accounts|P1
9.1|The Account model supports the required fields and types.|test_create_account
@$be/ledger/test_accounting.py|P0
2.1|A balanced double-entry (SUM == SUM) passes validation.|test_balanced_entry_passes
2.2|An unbalanced entry is rejected by validation.|test_unbalanced_entry_fails
2.3|A single-line entry is rejected.|test_single_line_entry_fails
2.4|Decimal amounts retain full precision through validation.|test_decimal_precision
2.5|A non-base-currency line requires an fx_rate.|test_fx_rate_required_for_non_base_currency
2.7|Balance validation treats an omitted line currency as the base currency.|test_missing_currency_balances_as_base_currency
8.2|Decimal precision is maintained through arithmetic.|test_decimal_precision
9.3|JournalLine enforces debit/credit direction and positive-amount rules.|test_single_line_entry_fails
11.4|Multi-currency entries require an fx_rate on non-base lines.|test_fx_rate_required_for_non_base_currency
@$be/ledger/test_accounting_integration.py|P0
2.6|Posting an unbalanced entry is rejected.|test_post_unbalanced_entry_rejected
3.1|A draft entry posts successfully.|test_post_journal_entry_success
3.2|Posting an already-posted entry is rejected.|test_post_journal_entry_already_posted_fails
3.5|Voiding a posted entry creates a balanced reversal entry.|test_void_journal_entry_creates_reversal
4.1|Balance calculation for an asset account sums posted lines correctly.|test_calculate_balance_for_asset_account
4.2|Balance calculation for an income account sums posted lines correctly.|test_calculate_balance_for_income_account
4.3|Draft entries are excluded from balance calculation.|test_draft_entries_not_included_in_balance
5.3|The accounting equation holds.|test_accounting_equation_holds
7.1|The journal router uses flush, not commit.|test_create_journal_entry_uses_flush_not_commit
13.1|Manual journal creation rejects lines using another user's account.|test_AC2_13_1_create_journal_entry_rejects_cross_user_account
13.2|Posting validates that every line account belongs to the entry owner.|test_AC2_13_2_journal_lines_reject_cross_user_account_at_db_boundary
13.3|Balance aggregation requires account and entry ownership to match.|test_AC2_13_3_balance_queries_ignore_cross_user_entry_headers
@$be/ledger/test_accounting_equation.py|P0
3.3|A posted entry cannot be reposted.|test_posted_entry_cannot_be_reposted
3.4|A posted entry's status is immutable against direct update.|test_posted_entry_status_immutable_via_direct_update
5.1|The accounting equation holds across all five account types.|test_accounting_equation_holds_with_all_account_types
5.2|An accounting-equation violation is detected.|test_accounting_equation_violation_detected
6.1|Maximum amount boundary is handled correctly.|test_max_amount_boundary|P1
6.2|Minimum amount boundary is handled correctly.|test_min_amount_boundary|P1
6.3|Decimal precision loss is detected.|test_amount_precision_loss_detection|P1
6.4|A many-line complex entry posts balanced.|test_many_lines_complex_salary_correct|P1
9.2|The JournalEntry model supports the required fields and status flow.|test_posted_entry_cannot_be_reposted
@$be/ledger/test_journal_delete_and_validation.py|P1
3.7|Create_entry surfaces a ValidationError for unbalanced/single-line input.|test_create_unbalanced_entry_returns_error
7.5|DELETE /{entry_id} deletes a draft entry successfully.|test_delete_draft_entry_success
@$be/ledger/test_accounting_service_errors.py|P1
3.8|Post_journal_entry error handling.|test_post_journal_entry_errors
3.9|Void_journal_entry error handling.|test_void_journal_entry_errors
3.10|Post_journal_entry success path.|test_post_journal_entry_success
3.11|Void_journal_entry success path produces a reversal.|test_void_journal_entry_success
@$be/ledger/test_multicurrency_integrity.py|P0
3.12|Voiding a posted entry preserves the historical base-currency basis encoded by its line currencies and FX rates, even.|test_void_preserves_historical_base_after_effective_currency_change
3.13|Voiding fails closed when every historical line carries an FX rate and the original base-currency basis cannot be recovered.|test_void_rejects_all_fx_entry_without_historical_basis
12.1|Journal-entry balance validation uses base-currency converted amounts.|test_AC2_12_1_multicurrency_entry_balances_in_base_currency
12.2|Accounting-equation verification uses base-currency converted account balances.|test_AC2_12_2_accounting_equation_uses_base_currency_balances
signature.4|Caller-supplied operation currency reaches both Python journal validation and the PostgreSQL deferred ledger invariant.|test_effective_usd_base_drives_posting_trigger_and_equation
@$be/ledger/test_accounting_balances.py|P1
4.4|Balances aggregate correctly by account type.|test_calculate_account_balances_by_type
4.5|An empty account list returns empty balances.|test_calculate_account_balances_empty_list
4.6|Account-balance calculation across types is covered end to end.|test_calculate_account_balances_by_type
@$be/ledger/test_journal_router_errors.py|P1
7.2|Journal router error paths return clean errors.|test_create_entry_validation_error
10.4|API error behaviour for missing/invalid resources is correct.|test_create_entry_validation_error
2576.1|Manual journal line schemas bound amount and fx_rate.|test_AC_ledger_2576_1_journal_wire_bounds_and_tags_validation
@$be/ledger/test_journal_router_additional.py|P1
7.3|Journal router additional scenarios.|test_get_entry_not_found
7.4|A malformed request yields a validation error, not a 500.|test_create_entry_validation_error
@$be/api/test_journal_router.py|P1
7.6|Voiding a journal entry via the API behaves correctly.|test_void_journal_entry
7.7|Deleting a journal entry via the API is allowed only for drafts.|test_delete_journal_entry
@$be/accounting/test_decimal_safety.py|P0
8.1|Monetary amounts never use float.|test_float_injection_safety
8.3|Scientific-notation monetary input is handled/rejected safely.|test_scientific_notation_rejection|P1
@$be/accounting/test_accounts_endpoints.py|P0
10.1|The account endpoints behave correctly.|test_accounts_endpoints
2674.1|System accounts reject update and delete mutations in account_service and /accounts endpoints.|test_AC_ledger_2674_1_system_accounts_cannot_be_updated_or_deleted|P1
@$be/ledger/test_journal_endpoints.py|P0
10.2|The journal-entry endpoints behave correctly.|test_journal_entry_endpoints
10.3|The posting/voiding endpoints behave correctly.|test_journal_entry_endpoints
@$be/ledger/test_ledger_schema_invariants.py|P0
14.1|PostgreSQL rejects posted/reconciled entries with fewer than two lines even.|test_AC2_14_1_posted_entry_requires_two_lines_at_database_boundary
14.2|PostgreSQL rejects posted/reconciled entries whose debits and credits do not balance.|test_AC2_14_2_posted_entry_must_balance_in_base_currency
14.3|PostgreSQL rejects posted/reconciled non-base-currency lines.|test_AC2_14_3_non_base_posted_lines_require_positive_fx_rate
14.4|PostgreSQL blocks direct update/delete of posted/reconciled entries and lines.|test_AC2_14_4_posted_entries_and_lines_are_immutable_but_drafts_are_editable
14.5|Voiding a posted entry preserves a non-null immutable reversal relationship.|test_AC2_14_5_void_transition_requires_reversal_relationship
14.8|Fr_validate_journal_entry_invariants validates a posted or reconciled entry against journal_entries.base_currency (falling back to fr_ledger_base_currency only.|test_AC_ledger_14_8_reconcile_posted_usd_entry_uses_row_base_currency|P1
14.9|Fr_guard_journal_entry_immutability rejects base_currency mutations during posted -> reconciled and posted/reconciled -> void transitions.|test_AC_ledger_14_9_immutability_guard_rejects_base_currency_mutation|P1
@$be/ledger/test_opening_balance.py|P0
15.1|POST /api/accounts/opening-balances posts one balanced entry that increases each account to its opening balance on its normal side and offsets the net into a system Opening Balance Equity account.|test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet
15.2|A single asset opening balance offsets entirely into Opening Balance Equity, keeping the entry balanced.|test_AC2_15_2_single_asset_opening_balance_offsets_into_equity
15.3|An opening balance for a non-owned or unknown account is rejected.|test_AC2_15_3_unknown_account_is_rejected
15.4|An opening balance establishes a starting position, not a delta.|test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists
15.5|Opening balances require an explicit positive historical FX rate for non-base currency.|test_AC2_15_5_non_base_currency_is_rejected
15.6|An opening balance into an account whose currency differs from the request currency is rejected.|test_AC2_15_6_account_currency_mismatch_is_rejected
15.7|Opening balances may only target user-managed accounts.|test_AC2_15_7_system_account_target_is_rejected
@$be/ledger/test_opening_balance_readiness.py|P1
16.1|Get_opening_balance_readiness reports needs_opening_balance=True.|test_AC2_16_1_activity_without_opening_entry_needs_opening_balance
16.2|GET /api/accounts/opening-balance-readiness exposes the readiness signal to the UI.|test_AC2_16_2_readiness_endpoint_returns_status
@$be/ledger/test_processing_account.py|P0
71.1|The Processing account is auto-created on the first get_or_create call for a user.|test_processing_account_created_on_first_call
71.2|Processing-account creation is idempotent.|test_processing_account_idempotent
71.3|The Processing account is a system account hidden from list_accounts.|test_processing_account_hidden_from_list
71.4|Each user gets their own isolated Processing account.|test_processing_account_per_user
72.1|A transfer-OUT entry debits Processing and credits the source account.|test_transfer_out_to_processing
72.2|A transfer-IN entry debits the destination account and credits Processing.|test_transfer_in_from_processing
72.3|A paired transfer OUT + IN nets the Processing balance to zero.|test_paired_transfers_zero_balance
73.1|An unpaired transfer leaves a non-zero Processing balance, keeping in-transit funds visible.|test_unpaired_transfer_visible_in_processing_balance
73.2|The accounting equation holds.|test_accounting_equation_holds_with_processing
74.1|Detect_transfer_pattern identifies transfer keywords in a description.|test_detect_transfer_keywords
74.2|Detect_transfer_pattern returns False for a None/empty description.|test_detect_transfer_no_description
74.3|Find_transfer_pairs auto-pairs transfers whose confidence is at or above the threshold.|test_auto_pair_transfers_above_threshold
74.4|Find_transfer_pairs orders candidates by and excludes paired entry IDs.|test_AC_ledger_74_4_find_transfer_pairs_orders_and_excludes_paired_before_limit
75.1|Amount scoring returns 100 for an exact match within one cent.|test_amount_exact_match
75.2|Amount scoring degrades by tier as the gap widens, e.g. within 1 SGD scores 85.|test_amount_close_match
75.3|Description scoring returns a proportional score for a partial match.|test_description_partial_match|P1
75.4|Date-proximity scoring degrades over a 7-day window.|test_date_three_day_diff|P1
@$be/reconciliation/test_transfer_integration.py|P0
76.1|During reconciliation, a detected transfer creates a Processing entry for the linked account.|test_transfer_detected_creates_processing_entry
76.2|Transfer detection skips when the statement has no linked account.|test_transfer_detection_skips_when_no_account_linked
76.3|A detected transfer-IN creates the correct Processing entry.|test_transfer_in_creates_correct_processing_entry
76.4|The auto-pairing phase pairs transfers with the same amount and date, netting the Processing balance to zero.|test_auto_pair_transfers_same_amount_same_date
76.5|An unpaired transfer leaves a non-zero Processing balance.|test_unpaired_transfer_leaves_processing_nonzero
76.6|Non-transfer transactions skip Phase 1 and proceed to normal matching.|test_non_transfer_transaction_proceeds_to_normal_matching
@$t/test_ledger_module.py|P1
34.2|The ledger module converges by layer.|test_AC12_34_2_ledger_module_converges_by_role
34.3|Layer-DAG rule: the model layer imports no service.|test_AC12_34_3_model_layer_never_imports_a_service
34.4|Adoption: investment buy/sell/dividend build typed Entry and post.|test_AC12_34_4_investment_postings_use_ledger_post
34.5|Every computed/transfer posting path gates balance.|test_AC12_34_5_remaining_posting_paths_guard_balance_with_entry
34.6|The journal write pipeline lives in the ledger package.|test_AC12_34_6_ledger_owns_posting_pipeline_no_upward_edge
@$be/ledger/test_ledger_shift_left.py|P0
journeys.1|Creating a cash asset account.|test_account_creation_cash_and_bank
journeys.2|Creating a bank asset account.|test_account_creation_cash_and_bank
journeys.3|Updating an account's name via the API reflects the new name.|test_account_update_and_delete|P1
journeys.4|Deleting an account with no transactions removes it.|test_account_update_and_delete|P1
journeys.5|A simple two-account expense entry is created in draft status with correct amounts.|test_journal_entry_balancing_and_validation
journeys.6|Voiding a posted journal entry transitions it to void state.|test_journal_entry_post_and_void_reversal
journeys.7|Posting a draft journal entry transitions it to posted state.|test_journal_entry_post_and_void_reversal
journeys.8|An unbalanced journal entry (debits != credits) is rejected.|test_journal_entry_balancing_and_validation
journeys.9|Journal entry create/read/update/delete.|test_journal_entry_post_and_void_reversal|P1
journeys.10|Recording income posts a balanced entry crediting the income account.|test_income_recording_balance_update
journeys.11|A credit card spend posts a balanced entry against the liability account.|test_credit_card_spend_and_repayment_invariants
journeys.12|A credit card repayment posts a balanced entry reducing the liability.|test_credit_card_spend_and_repayment_invariants
journeys.13|An internal transfer between two of the user's own accounts posts a balanced entry.|test_credit_card_spend_and_repayment_invariants
journeys.14|A split transaction across multiple expense categories posts one balanced multi-line entry.|test_credit_card_spend_and_repayment_invariants
@$be/reporting/test_fx_revaluation.py|P1
fxrevaluation.1|A liability account's unrealized FX gain/loss returns the negated net balance.|test_returns_negated_balance_for_liability_account
fxrevaluation.3|An account whose unrealized-FX calculation returns None is skipped, not errored.|test_none_revaluation_skipped
@$fe/__tests__/accountsPage.test.tsx|P2
api-vectors.2|The frontend accounts page test consumes the committed ledger conformance vector verbatim as its mock data.|AC16.15.2 renders grouped accounts and supports type filters|P1
fe-accounts-journal.1|Accounts page renders loading and error retry states.|AC16.15.1 renders loading and error retry states
fe-accounts-journal.2|Accounts page renders grouped account cards and type filters on successful fetch.|AC16.15.2 renders grouped accounts and supports type filters
fe-accounts-journal.3|Accounts page delete action confirms and calls delete API with success toast.|AC16.15.3 delete action confirms and calls delete API with success toast
fe-accounts-journal.4|Edit button opens modal with account data.|AC16.15.7 edit button opens modal with account data
fe-accounts-journal.5|Add Account button opens create modal.|AC16.15.8 Add Account button opens create modal
fe-accounts-journal.6|Modal onSuccess triggers account list refresh.|AC16.15.9 modal onSuccess triggers account list refresh
fe-accounts-journal.7|Modal onClose closes modal and clears editing state.|AC16.15.10 modal onClose closes modal and clears editing state
fe-accounts2.2|The Accounts page offers a guided opening-balance flow.|AC2.15.8 opens the guided opening-balance modal and refreshes on success|P1
fe-accounts2.3|The Accounts page shows a warning nudge.|AC2.16.3 shows a readiness nudge and opens the modal when opening balances are missing|P1
@$fe/__tests__/journalPage.test.tsx|P2
fe-accounts-journal.8|Journal page renders error state and retries loading entries.|AC16.16.5 renders error state and retries loading entries
fe-accounts-journal.9|Journal page filters entries by status and renders totals.|AC16.16.6 filters entries by status and renders totals
fe-accounts-journal.10|Journal page draft actions post and delete entries with API calls.|AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows
fe-accounts-journal.11|Journal page void flow submits reason and refreshes entries.|AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows
@$fe/__tests__/accountFormModalComponent.test.tsx|P2
fe-accounts-journal.12|Account form modal initializes.|AC16.21.1 create mode submits normalized payload and closes on success
fe-accounts-journal.13|Account form modal edit mode pre-fills values and submits update payload.|AC16.21.2 edit mode pre-fills values and submits update payload
fe-accounts-journal.14|Account form modal surfaces API errors and field validation feedback.|AC16.21.3 shows validation and API errors in create flow
@$fe/__tests__/journalEntryFormComponent.test.tsx|P2
fe-accounts-journal.15|Journal entry form loads account options and enforces balanced double-entry totals.|AC16.21.4 loads account options and shows balanced/unbalanced state
fe-accounts-journal.16|Journal entry form creates draft entries with normalized line amounts and optional posting.|AC16.21.5 submits create-draft payload with normalized amounts
fe-accounts-journal.17|Journal entry form supports dynamic line add/remove and submit-time error handling.|AC16.21.6 supports add and remove line interactions
@$fe/__tests__/uiGapAudit.processingVisibility.test.tsx|P2
fe-processing.2|The transfers-in-flight card of `/upload` lists pending transfers with line items `{from_account, to_account, amount, initiated_date, days_outstanding}`.|AC15.7.3 — Upload page transfers-in-flight card renders pending transfers|-|decision-5-processing-account
fe-processing.3|Pending entries older than 7 days render a warning badge on the listing row.|AC15.7.4 — warning badge for >7 day pending
@$be/ledger/test_signature_surgery.py|P1
signature.1|Processing transfer legs are built once and persisted.|test_processing_transfers_use_the_post_entry_front_door|P0
signature.2|System-account and processing APIs require callers to supply the owning currency explicitly.|test_processing_apis_require_explicit_currency
signature.3|Nominal account balances and base-currency account balances use separate typed functions with caller-supplied explicit base currency.|test_account_balance_currency_spaces_are_explicit
@$be/ledger/test_decision_anchor.py|P0
79.1|A source-derived or manual financial journal command carries a typed DecisionAnchor that pins one authoritative TraceRecord, tenant scope, exact target version.|test_decision_anchor_rejects_noncurrent_or_mismatched_authority
79.2|All product source/reviewed writes use submit_anchored_journal_entry.|test_submit_anchored_journal_entry_is_idempotent_and_conflicts_on_new_authority
79.3|The public manual journal command cannot select source_type or source_id.|test_manual_journal_api_creates_an_attested_anchor_without_source_impersonation
79.4|Journal source metadata and decision-anchor fields are immutable.|test_anchor_provenance_is_immutable_and_legacy_rows_remain_unproven
79.6|A whole-production-tree writer scan permits raw JournalEntry construction and persistence only at the ledger's private anchored-command boundary.|test_production_financial_writers_have_one_anchored_persistence_boundary
79.5|Reconciliation and unresolved-source reads consume the one ledger current-anchor query, which joins the JournalEntry decision id to audit's public current-authority projection.|test_current_anchored_journal_entries_rejects_stale_or_mismatched_authority
79.7|Trace emission and decision-anchored ledger persistence share the caller-owned unit of work.|test_anchored_command_sink_failure_rolls_back_trace_and_ledger
79.9|A journal entry stores the base currency that validated it at creation.|test_AC_ledger_79_9_post_uses_the_base_currency_stored_on_the_draft
79.10|A journal line stores its zero-based position in the creating command.|test_AC_ledger_79_10_post_does_not_depend_on_the_database_row_order
79.11|A manual journal command expresses each amount and FX rate at the decimal scale that journal_lines stores.|test_AC_ledger_79_11_post_does_not_depend_on_the_decimal_scale_of_the_request
80.1|List_journal_contributions publishes posted or reconciled journal facts with their exact current DecisionAnchor and line/account data.|test_AC_ledger_80_1_publishes_only_current_decision_anchored_journal_facts|:exact
80.2|Ledger_trace_policy_registry publishes the complete policy decoder required by package consumers.|test_AC_ledger_80_2_publishes_decision_policy_registry|:exact
@$be/ledger/test_ledger_authority_boundary.py|P0|done|exact
80.3|External statements are staged.|test_AC_ledger_80_3_external_statement_staging_rejects_processing_account
80.4|Submit_anchored_journal_entry enforces DecisionAnchor validation and double-entry balance in base currency.|test_AC_ledger_80_4_gateway_enforces_double_entry_balance_and_rejection_preserves_clean_ledger
80.5|Bypassing the authoritative ledger submission gateway and attempting direct database insertion triggers physical constraint or deferred trigger rejection with zero journal state pollution.|test_AC_ledger_80_5_direct_database_bypass_interception
@$be/ledger/test_anchored_batch.py|P1
anchored-batch.1|Submit_anchored_journal_entries persists the entries that one submit_anchored_journal_entry call per command persists.|test_AC_ledger_anchored_batch_1_batch_persists_the_entries_of_one_submit_per_command
anchored-batch.2|The batch port issues a number of SQL statements that does not grow with the number of commands, at most 10.|test_AC_ledger_anchored_batch_2_batch_statement_count_does_not_grow_with_the_set
anchored-batch.3|A resubmitted batch returns the same entries and persists no entry.|test_AC_ledger_anchored_batch_3_batch_is_idempotent_and_refuses_a_different_owner_of_a_target
anchored-batch.4|One command with an invalid anchor persists none of the commands of its batch.|test_AC_ledger_anchored_batch_4_one_invalid_command_persists_none_of_the_set
anchored-batch.5|Post_immediately decides for each command of a batch.|test_AC_ledger_anchored_batch_5_post_immediately_decides_for_each_command
anchored-batch.6|Commands that share a source target keep the single path.|test_AC_ledger_anchored_batch_6_commands_that_share_a_target_keep_the_single_path
anchored-batch.7|The Processing-account rule of a batch applies to the accounts of each command, not to the accounts of the whole batch.|test_AC_ledger_anchored_batch_7_the_processing_account_rule_applies_to_the_accounts_of_each_command
anchored-batch.8|Post_journal_entries applies the checks of post_journal_entry to each entry and flushes once.|test_AC_ledger_anchored_batch_8_post_journal_entries_checks_each_entry_like_post_journal_entry
anchored-batch.9|The existence read of a batch names at most one chunk of targets in each statement and refuses a target with two owners.|test_AC_ledger_anchored_batch_9_target_read_is_chunked_and_refuses_two_owners
@-|P1
opening-position.9|The legacy opening-entry API retains its positive base-currency JournalEntry contract.|$be/ledger/test_opening_entry_compatibility.py::test_legacy_opening_entry_rejects_nonpositive_without_writes|P0
opening-position.7|The production migration preserves prior rejected history, installs immutable opening facts.|$be/ledger/test_opening_position_migration.py::test_opening_migration_preserves_history_and_enforces_immutability|P0
78.1|ConfidenceTier owns the one worst_confidence_tier rank function.|$be/ledger/test_confidence_tier_owner.py::test_AC_ledger_78_1_worst_confidence_tier_is_single_homed
3.6|Journal service operations handle non-existent entries cleanly.|$be/ledger/test_journal_service.py::test_journal_router_direct
void-memo.1|Voiding an entry whose memo fills the memo column posts a reversal.|$be/ledger/test_journal_memo_limit.py::test_AC_ledger_void_memo_1_voiding_an_entry_with_a_full_memo_posts_a_cut_reversal_memo|P0
9.4|Pydantic account/journal schemas validate their inputs.|$be/accounting/test_schemas.py::test_account_create_valid
10.5|DELETE /statements/{id} succeeds for a valid owner.|$be/accounting/test_delete_endpoints.py::test_delete_statement
12.6|Statement validation rejects invalid statement balance and transaction states.|$be/accounting/test_validation.py::test_validate_balance_mismatch|P0
14.6|Account deletion blocked by the immutability invariant returns a clean HTTP 409, not a leaked 500.|$be/api/test_users_router.py::test_delete_user_with_immutable_entries_returns_409
14.7|A database built by `alembic upgrade head` holds the same ledger functions and triggers as a database built from the ORM metadata.|$be/infra/test_trigger_function_drift.py::test_AC_ledger_14_7_alembic_and_orm_schemas_hold_the_same_functions_and_triggers
71.5|The Processing account and every default account of a user are created once, however many requests of that user create them together.|$be/ledger/test_default_account_race.py::test_AC_ledger_71_5_a_second_request_neither_waits_for_the_open_transaction_nor_creates_a_row|P0
71.6|A read never creates the Processing account.|$be/ledger/test_processing_read_only.py::test_AC_ledger_71_6_a_page_view_creates_no_processing_account|P0
76.7|Transfer detection is idempotent.|$be/reconciliation/test_transfer_idempotency.py::test_transfer_out_duplicate_detection_skipped|P0
transfer-clearing.1|An isolated user uploads two statements whose legs form one transfer, matches transfers and approves both statements.|$e2e/test_transfer_processing_journey.py::test_transfer_between_accounts_clears_through_processing
34.1|Entry/Leg make double-entry a value object.|$be/ledger/test_entry.py::test_AC12_34_1_balanced_entry_constructs
77.1|A brand-new user can register, log in, create their first ledger accounts, post a first manual journal entry.|$be/integration/test_onboarding_e2e.py::test_AC1_9_1_first_run_registration_account_entry_journey|P0:property
processing.1|GET /api/accounts/processing/summary returns {pending_count, pending_total, current_balance, currency, oldest_pending_date}.|$be/ledger/test_processing_account_endpoints.py::test_processing_summary_aggregates_unpaired
api-vectors.1|The serialized GET /api/accounts response recomputed from fixed deterministic inputs equals the committed common/ledger/conformance/vectors.json.|$be/schemas/test_api_response_vectors.py::test_AC_ledger_api_vectors_1_accounts_list_matches_committed_vector
fe-accounts-journal.18|Journal entry details expose line account, direction, amount.|$fe/__tests__/detailViewComponents.test.tsx::AC16.25.3 journal entry details mobile line cards expose all line fields
fe-accounts2.1|Accounts page mobile filters and account rows avoid document-level horizontal scroll and content overlap.|apps/frontend/playwright/mobile-ux.spec.ts::AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls|P0
first-use.1|Opening balances start without an invented date.|$fe/__tests__/openingBalanceModal.test.tsx::AC-ledger.first-use.1 explicitly applies the prior-period date without posting|P0
first-use.2|An isolated user creates an SGD asset account in the browser and records an opening balance on a fixed date.|$e2e/test_opening_balance_browser_journey.py::test_opening_balance_recorded_through_browser|P0
fe-accounts2.4|ConfidenceBadge mounted on every transaction row in Stage 1 review, Stage 2 listing.|$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.2 — Journal page surfaces ConfidenceBadge tier|P2
fe-processing.5|Pending transfers are discoverable from the Audit hub.|$fe/__tests__/auditHub.test.tsx::AC15.7.6 aggregates the verify-on-demand machinery as deep-linking cards
fe-processing.6|The sidebar Processing badge was removed with the Advanced drawer.|$fe/__tests__/sidebarAndTabs.test.tsx::AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)
fe-accounts-tab.1|The chart of accounts shows in the Accounts tab of `/settings`.|$fe/__tests__/settingsPage.test.tsx::AC-ledger.fe-accounts-tab.1 shows the chart of accounts in the Accounts tab that ?tab=accounts opens
79.8|An Alembic upgrade over a balanced, posted legacy journal entry preserves the immutable accounting fact.|$be/ledger/test_historical_authority_migration.py::test_AC_ledger_79_8_posted_legacy_entry_upgrades_without_mutation|P0
2832.1|Get_or_create_unexplained_gap_equity_account provisions system equity account 3198 per currency.|$be/extraction/test_statement_opening_guards.py::test_AC_ledger_2832_1_unexplained_gap_equity_account_and_superseding_opening_position|:exact
""",
    ),
    concepts=concepts(
        """
accounting_equation|common/ledger/readme.md#accounting-equation|Assets = Liabilities + Equity + (Income - Expenses) invariant.|docs/agents/red-lines.md,apps/backend/tests/ledger/test_accounting_equation.py|-|accounting|concept
decimal_monetary_rule|common/ledger/readme.md#decimal-rule|All monetary amounts MUST use Python Decimal, never float; money rounds via banker's HALF_EVEN.|AGENTS.md,docs/agents/red-lines.md,apps/backend/tests/accounting/test_decimal_safety.py|apps/backend/tests/accounting/test_decimal_safety.py,apps/backend/tests/audit/money/test_money.py|accounting|concept
double_entry_bookkeeping|common/ledger/readme.md#entry-balance|Every JournalEntry must have balanced debits and credits.|docs/agents/red-lines.md,apps/backend/tests/ledger/test_accounting.py|-|accounting|concept
processing_account|common/ledger/readme.md|Unconfirmed in-transit funds; balance 0 means transfer paired.|common/extraction/confirmation-workflow.md,common/reconciliation/reconciliation.md|-|accounting|concept
transaction_boundary|common/ledger/readme.md#async-tx-boundary|Routers commit(); Services flush() only.|docs/agents/red-lines.md,apps/backend/tests/ledger/test_accounting_integration.py|-|accounting|concept
"""
    ),
)

TEST_ROOTS: tuple[str, ...] = (
    "apps/backend/tests/ledger/",
    "tests/tooling/test_ledger_module.py",
    "tests/tooling/test_ledger_package.py",
)
