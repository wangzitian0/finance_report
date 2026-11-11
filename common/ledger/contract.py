"""PackageContract for ``ledger``."""

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
DegenerateEntryError DecisionAnchor DecisionAnchorError Direction Entry JournalAuditLog
JournalEntry JournalEntryAuthorityState JournalEntryStatus JournalLine
JournalLineContribution LedgerError Leg MAX_JOURNAL_LINE_AMOUNT MAX_JOURNAL_LINE_FX_RATE
PROCESSING_ACCOUNT_CODE ProcessingAccount ProcessingCurrencyConflictError
ResolvedJournalContribution RevaluationError StatementCoverageRow
TransferAccountCurrencyMismatchError TransferPair UnbalancedEntryError ValidationError
account_service active_journal_entry_filter calculate_account_balance
calculate_account_balances calculate_account_balances_in_base_currency
calculate_reconciliation_adjustment calculate_unrealized_fx_gains
current_anchored_journal_entries find_processing_account create_transfer_in_entry
create_transfer_out_entry derive_confidence_tier detect_transfer_pattern
find_transfer_pairs fit_journal_memo get_account_statement_coverage
get_opening_balance_readiness get_or_create_processing_account get_processing_balance
get_unpaired_transfers initialize_opening_positions journal_command_target
ledger_trace_policy_registry list_journal_contributions list_processing_transfer_legs
post_entry submit_anchored_journal_entries submit_anchored_journal_entry
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
@$be/ledger/test_opening_position.py
opening-position.8||test_source_opening_retains_pdf_ancestor
opening-position.1||test_manual_approval_posts_opening
opening-position.2||test_concurrent_opening_initialization
opening-position.3||test_zero_and_per_account_readiness
opening-position.4||test_foreign_opening_and_missing_rate
opening-position.5||test_opening_projection_and_immutability
opening-position.6||test_opening_projection_preserves_date
statement-category.1||test_statement_category_is_pinned
@$be/ledger/test_opening_position_query_budget.py|P1
opening-position.10||test_AC_ledger_opening_position_10_projection_reads_fixed_statements_and_only_opening_entries
opening-position.11||test_AC_ledger_opening_position_11_projection_reads_only_the_decisions_it_needs
@$be/accounting/test_accounts_service.py
1.1|Creating an account with valid data persists it with the correct type, code.|test_create_account
9.1|The Account model supports the required fields and types.|^
1.2||test_get_account_success
1.3||test_get_account_not_found
1.4||test_update_account_success
1.5||test_update_account_not_found
1.6||test_list_accounts|P1
@$be/ledger/test_accounting.py
2.1||test_balanced_entry_passes
2.2||test_unbalanced_entry_fails
2.3|A single-line entry is rejected.|test_single_line_entry_fails
9.3|JournalLine enforces debit/credit direction and positive-amount rules.|^
2.4|Decimal amounts retain full precision through validation.|test_decimal_precision
8.2|Decimal precision is maintained through arithmetic.|^
2.5|A non-base-currency line requires an fx_rate.|test_fx_rate_required_for_non_base_currency
11.4|Multi-currency entries require an fx_rate on non-base lines.|^
2.7||test_missing_currency_balances_as_base_currency
@$be/ledger/test_accounting_integration.py
2.6||test_post_unbalanced_entry_rejected
3.1||test_post_journal_entry_success
3.2||test_post_journal_entry_already_posted_fails
3.5||test_void_journal_entry_creates_reversal
4.1||test_calculate_balance_for_asset_account
4.2||test_calculate_balance_for_income_account
4.3||test_draft_entries_not_included_in_balance
5.3||test_accounting_equation_holds
7.1||test_create_journal_entry_uses_flush_not_commit
13.1||test_AC2_13_1_create_journal_entry_rejects_cross_user_account
13.2||test_AC2_13_2_journal_lines_reject_cross_user_account_at_db_boundary
13.3||test_AC2_13_3_balance_queries_ignore_cross_user_entry_headers
@$be/ledger/test_accounting_equation.py
3.3|A posted entry cannot be reposted.|test_posted_entry_cannot_be_reposted
9.2|The JournalEntry model supports the required fields and status flow.|^
3.4||test_posted_entry_status_immutable_via_direct_update
5.1||test_accounting_equation_holds_with_all_account_types
5.2||test_accounting_equation_violation_detected
6.1||test_max_amount_boundary|P1
6.2||test_min_amount_boundary|P1
6.3||test_amount_precision_loss_detection|P1
6.4||test_many_lines_complex_salary_correct|P1
@$be/ledger/test_journal_delete_and_validation.py|P1
3.7||test_create_unbalanced_entry_returns_error
7.5||test_delete_draft_entry_success
@$be/ledger/test_accounting_service_errors.py|P1
3.8||test_post_journal_entry_errors
3.9||test_void_journal_entry_errors
3.10||test_post_journal_entry_success
3.11||test_void_journal_entry_success
@$be/ledger/test_multicurrency_integrity.py
3.12||test_void_preserves_historical_base_after_effective_currency_change
3.13||test_void_rejects_all_fx_entry_without_historical_basis
12.1||test_AC2_12_1_multicurrency_entry_balances_in_base_currency
12.2||test_AC2_12_2_accounting_equation_uses_base_currency_balances
signature.4||test_effective_usd_base_drives_posting_trigger_and_equation
@$be/ledger/test_accounting_balances.py|P1
4.4|Balances aggregate correctly by account type.|test_calculate_account_balances_by_type
4.6|Account-balance calculation across types is covered end to end.|^
4.5||test_calculate_account_balances_empty_list
@$be/ledger/test_journal_router_errors.py|P1
7.2|Journal router error paths return clean errors.|test_create_entry_validation_error
10.4|API error behaviour for missing/invalid resources is correct.|^
2576.1||test_AC_ledger_2576_1_journal_wire_bounds_and_tags_validation
@$be/ledger/test_journal_router_additional.py|P1
7.3||test_get_entry_not_found
7.4||test_create_entry_validation_error
@$be/api/test_journal_router.py|P1
7.6||test_void_journal_entry
7.7||test_delete_journal_entry
@$be/accounting/test_decimal_safety.py
8.1||test_float_injection_safety
8.3||test_scientific_notation_rejection|P1
@$be/accounting/test_accounts_endpoints.py
10.1||test_accounts_endpoints
2674.1||test_AC_ledger_2674_1_system_accounts_cannot_be_updated_or_deleted|P1
@$be/ledger/test_journal_endpoints.py
10.2|The journal-entry endpoints behave correctly.|test_journal_entry_endpoints
10.3|The posting/voiding endpoints behave correctly.|^
@$be/ledger/test_ledger_schema_invariants.py
14.1||test_AC2_14_1_posted_entry_requires_two_lines_at_database_boundary
14.2||test_AC2_14_2_posted_entry_must_balance_in_base_currency
14.3||test_AC2_14_3_non_base_posted_lines_require_positive_fx_rate
14.4||test_AC2_14_4_posted_entries_and_lines_are_immutable_but_drafts_are_editable
14.5||test_AC2_14_5_void_transition_requires_reversal_relationship
14.8||test_AC_ledger_14_8_reconcile_posted_usd_entry_uses_row_base_currency|P1
14.9||test_AC_ledger_14_9_immutability_guard_rejects_base_currency_mutation|P1
@$be/ledger/test_opening_balance.py
15.1||test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet
15.2||test_AC2_15_2_single_asset_opening_balance_offsets_into_equity
15.3||test_AC2_15_3_unknown_account_is_rejected
15.4||test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists
15.5||test_AC2_15_5_non_base_currency_is_rejected
15.6||test_AC2_15_6_account_currency_mismatch_is_rejected
15.7||test_AC2_15_7_system_account_target_is_rejected
@$be/ledger/test_opening_balance_readiness.py|P1
16.1||test_AC2_16_1_activity_without_opening_entry_needs_opening_balance
16.2||test_AC2_16_2_readiness_endpoint_returns_status
@$be/ledger/test_processing_account.py
71.1||test_processing_account_created_on_first_call
71.2||test_processing_account_idempotent
71.3||test_processing_account_hidden_from_list
71.4||test_processing_account_per_user
72.1||test_transfer_out_to_processing
72.2||test_transfer_in_from_processing
72.3||test_paired_transfers_zero_balance
73.1||test_unpaired_transfer_visible_in_processing_balance
73.2||test_accounting_equation_holds_with_processing
74.1||test_detect_transfer_keywords
74.2||test_detect_transfer_no_description
74.3||test_auto_pair_transfers_above_threshold
74.4||test_AC_ledger_74_4_find_transfer_pairs_orders_and_excludes_paired_before_limit
75.1||test_amount_exact_match
75.2||test_amount_close_match
75.3||test_description_partial_match|P1
75.4||test_date_three_day_diff|P1
@$be/reconciliation/test_transfer_integration.py
76.1||test_transfer_detected_creates_processing_entry
76.2||test_transfer_detection_skips_when_no_account_linked
76.3||test_transfer_in_creates_correct_processing_entry
76.4||test_auto_pair_transfers_same_amount_same_date
76.5||test_unpaired_transfer_leaves_processing_nonzero
76.6||test_non_transfer_transaction_proceeds_to_normal_matching
@$t/test_ledger_module.py|P1
34.2||test_AC12_34_2_ledger_module_converges_by_role
34.3||test_AC12_34_3_model_layer_never_imports_a_service
34.4||test_AC12_34_4_investment_postings_use_ledger_post
34.5||test_AC12_34_5_remaining_posting_paths_guard_balance_with_entry
34.6||test_AC12_34_6_ledger_owns_posting_pipeline_no_upward_edge
@$be/ledger/test_ledger_shift_left.py
journeys.1|Creating a cash asset account.|test_account_creation_cash_and_bank
journeys.2|Creating a bank asset account.|^
journeys.3|Updating an account's name via the API reflects the new name.|test_account_update_and_delete|P1
journeys.4|Deleting an account with no transactions removes it.|^|P1
journeys.5|A simple two-account expense entry is created in draft status with correct amounts.|test_journal_entry_balancing_and_validation
journeys.8|An unbalanced journal entry (debits != credits) is rejected.|^
journeys.6|Voiding a posted journal entry transitions it to void state.|test_journal_entry_post_and_void_reversal
journeys.7|Posting a draft journal entry transitions it to posted state.|^
journeys.9|Journal entry create/read/update/delete.|^|P1
journeys.10||test_income_recording_balance_update
journeys.11|A credit card spend posts a balanced entry against the liability account.|test_credit_card_spend_and_repayment_invariants
journeys.12|A credit card repayment posts a balanced entry reducing the liability.|^
journeys.13|An internal transfer between two of the user's own accounts posts a balanced entry.|^
journeys.14|A split transaction across multiple expense categories posts one balanced multi-line entry.|^
@$be/reporting/test_fx_revaluation.py|P1
fxrevaluation.1||test_returns_negated_balance_for_liability_account
fxrevaluation.3||test_none_revaluation_skipped
@$fe/__tests__/accountsPage.test.tsx|P2
api-vectors.2|The frontend accounts page test consumes the committed ledger conformance vector verbatim as its mock data.|AC16.15.2 renders grouped accounts and supports type filters|P1
fe-accounts-journal.2|Accounts page renders grouped account cards and type filters on successful fetch.|^
fe-accounts-journal.1||AC16.15.1 renders loading and error retry states
fe-accounts-journal.3||AC16.15.3 delete action confirms and calls delete API with success toast
fe-accounts-journal.4||AC16.15.7 edit button opens modal with account data
fe-accounts-journal.5||AC16.15.8 Add Account button opens create modal
fe-accounts-journal.6||AC16.15.9 modal onSuccess triggers account list refresh
fe-accounts-journal.7||AC16.15.10 modal onClose closes modal and clears editing state
fe-accounts2.2||AC2.15.8 opens the guided opening-balance modal and refreshes on success|P1
fe-accounts2.3||AC2.16.3 shows a readiness nudge and opens the modal when opening balances are missing|P1
@$fe/__tests__/journalPage.test.tsx|P2
fe-accounts-journal.8||AC16.16.5 renders error state and retries loading entries
fe-accounts-journal.9||AC16.16.6 filters entries by status and renders totals
fe-accounts-journal.10|Journal page draft actions post and delete entries with API calls.|AC16.16.7 and AC16.16.8 handles draft post/delete and posted void flows
fe-accounts-journal.11|Journal page void flow submits reason and refreshes entries.|^
@$fe/__tests__/accountFormModalComponent.test.tsx|P2
fe-accounts-journal.12||AC16.21.1 create mode submits normalized payload and closes on success
fe-accounts-journal.13||AC16.21.2 edit mode pre-fills values and submits update payload
fe-accounts-journal.14||AC16.21.3 shows validation and API errors in create flow
@$fe/__tests__/journalEntryFormComponent.test.tsx|P2
fe-accounts-journal.15||AC16.21.4 loads account options and shows balanced/unbalanced state
fe-accounts-journal.16||AC16.21.5 submits create-draft payload with normalized amounts
fe-accounts-journal.17||AC16.21.6 supports add and remove line interactions
@$fe/__tests__/uiGapAudit.processingVisibility.test.tsx|P2
fe-processing.2||AC15.7.3 — Upload page transfers-in-flight card renders pending transfers|-|decision-5-processing-account
fe-processing.3||AC15.7.4 — warning badge for >7 day pending
@$be/ledger/test_signature_surgery.py|P1
signature.1||test_processing_transfers_use_the_post_entry_front_door|P0
signature.2||test_processing_apis_require_explicit_currency
signature.3||test_account_balance_currency_spaces_are_explicit
@$be/ledger/test_decision_anchor.py
79.1||test_decision_anchor_rejects_noncurrent_or_mismatched_authority
79.2||test_submit_anchored_journal_entry_is_idempotent_and_conflicts_on_new_authority
79.3||test_manual_journal_api_creates_an_attested_anchor_without_source_impersonation
79.4||test_anchor_provenance_is_immutable_and_legacy_rows_remain_unproven
79.6||test_production_financial_writers_have_one_anchored_persistence_boundary
79.5||test_current_anchored_journal_entries_rejects_stale_or_mismatched_authority
79.7||test_anchored_command_sink_failure_rolls_back_trace_and_ledger
79.9||test_AC_ledger_79_9_post_uses_the_base_currency_stored_on_the_draft
79.10||test_AC_ledger_79_10_post_does_not_depend_on_the_database_row_order
79.11||test_AC_ledger_79_11_post_does_not_depend_on_the_decimal_scale_of_the_request
80.1||test_AC_ledger_80_1_publishes_only_current_decision_anchored_journal_facts
80.2||test_AC_ledger_80_2_publishes_decision_policy_registry
@$be/ledger/test_ledger_authority_boundary.py
80.3||test_AC_ledger_80_3_external_statement_staging_rejects_processing_account
80.4||test_AC_ledger_80_4_gateway_enforces_double_entry_balance_and_rejection_preserves_clean_ledger
80.5||test_AC_ledger_80_5_direct_database_bypass_interception
@$be/ledger/test_anchored_batch.py|P1
anchored-batch.1||test_AC_ledger_anchored_batch_1_batch_persists_the_entries_of_one_submit_per_command
anchored-batch.2||test_AC_ledger_anchored_batch_2_batch_statement_count_does_not_grow_with_the_set
anchored-batch.3||test_AC_ledger_anchored_batch_3_batch_is_idempotent_and_refuses_a_different_owner_of_a_target
anchored-batch.4||test_AC_ledger_anchored_batch_4_one_invalid_command_persists_none_of_the_set
anchored-batch.5||test_AC_ledger_anchored_batch_5_post_immediately_decides_for_each_command
anchored-batch.6||test_AC_ledger_anchored_batch_6_commands_that_share_a_target_keep_the_single_path
anchored-batch.7||test_AC_ledger_anchored_batch_7_the_processing_account_rule_applies_to_the_accounts_of_each_command
anchored-batch.8||test_AC_ledger_anchored_batch_8_post_journal_entries_checks_each_entry_like_post_journal_entry
anchored-batch.9||test_AC_ledger_anchored_batch_9_target_read_is_chunked_and_refuses_two_owners
@$be/ledger/test_opening_entry_compatibility.py
opening-position.9||test_legacy_opening_entry_rejects_nonpositive_without_writes
@$be/ledger/test_opening_position_migration.py
opening-position.7||test_opening_migration_preserves_history_and_enforces_immutability
@$be/ledger/test_confidence_tier_owner.py|P1
78.1||test_AC_ledger_78_1_worst_confidence_tier_is_single_homed
@$be/ledger/test_journal_service.py|P1
3.6||test_journal_router_direct
@$be/ledger/test_journal_memo_limit.py
void-memo.1||test_AC_ledger_void_memo_1_voiding_an_entry_with_a_full_memo_posts_a_cut_reversal_memo
@$be/accounting/test_schemas.py|P1
9.4||test_account_create_valid
@$be/accounting/test_delete_endpoints.py|P1
10.5||test_delete_statement
@$be/accounting/test_validation.py
12.6||test_validate_balance_mismatch
@$be/api/test_users_router.py|P1
14.6||test_delete_user_with_immutable_entries_returns_409
@$be/infra/test_trigger_function_drift.py|P1
14.7||test_AC_ledger_14_7_alembic_and_orm_schemas_hold_the_same_functions_and_triggers
@$be/ledger/test_default_account_race.py
71.5||test_AC_ledger_71_5_a_second_request_neither_waits_for_the_open_transaction_nor_creates_a_row
@$be/ledger/test_processing_read_only.py
71.6||test_AC_ledger_71_6_a_page_view_creates_no_processing_account
@$be/reconciliation/test_transfer_idempotency.py
76.7||test_transfer_out_duplicate_detection_skipped
@$e2e/test_transfer_processing_journey.py|P1
transfer-clearing.1||test_transfer_between_accounts_clears_through_processing
@$be/ledger/test_entry.py|P1
34.1||test_AC12_34_1_balanced_entry_constructs
@$be/integration/test_onboarding_e2e.py|P0|done|property
77.1||test_AC1_9_1_first_run_registration_account_entry_journey
@$be/ledger/test_processing_account_endpoints.py|P1
processing.1||test_processing_summary_aggregates_unpaired
@$be/schemas/test_api_response_vectors.py|P1
api-vectors.1||test_AC_ledger_api_vectors_1_accounts_list_matches_committed_vector
@$fe/__tests__/detailViewComponents.test.tsx|P1
fe-accounts-journal.18||AC16.25.3 journal entry details mobile line cards expose all line fields
@apps/frontend/playwright/mobile-ux.spec.ts
fe-accounts2.1||AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls
@$fe/__tests__/openingBalanceModal.test.tsx
first-use.1||AC-ledger.first-use.1 explicitly applies the prior-period date without posting
@$e2e/test_opening_balance_browser_journey.py
first-use.2||test_opening_balance_recorded_through_browser
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P2
fe-accounts2.4||AC18.5.2 — Journal page surfaces ConfidenceBadge tier
@$fe/__tests__/auditHub.test.tsx|P1
fe-processing.5||AC15.7.6 aggregates the verify-on-demand machinery as deep-linking cards
@$fe/__tests__/sidebarAndTabs.test.tsx|P1
fe-processing.6||AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)
@$fe/__tests__/settingsPage.test.tsx|P1
fe-accounts-tab.1||AC-ledger.fe-accounts-tab.1 shows the chart of accounts in the Accounts tab that ?tab=accounts opens
@$be/ledger/test_historical_authority_migration.py
79.8||test_AC_ledger_79_8_posted_legacy_entry_upgrades_without_mutation
@$be/extraction/test_statement_opening_guards.py|P1
2832.1||test_AC_ledger_2832_1_unexplained_gap_equity_account_and_superseding_opening_position
""",
    ),
    concepts=concepts(
        """
accounting_equation|common/ledger/readme.md#accounting-equation|Assets = Liabilities + Equity + (Income - Expenses) invariant.|docs/agents/red-lines.md,apps/backend/tests/ledger/test_accounting_equation.py|-|accounting|concept
decimal_monetary_rule|common/ledger/readme.md#decimal-rule|All monetary amounts MUST use Python Decimal, never float.|AGENTS.md,docs/agents/red-lines.md,apps/backend/tests/accounting/test_decimal_safety.py|apps/backend/tests/accounting/test_decimal_safety.py,apps/backend/tests/audit/money/test_money.py|accounting|concept
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
