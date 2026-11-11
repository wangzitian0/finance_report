"""Machine-checkable PackageContract for ``extraction``."""

from __future__ import annotations

from common.meta.package_contract import (
    CommandBoundary,
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="extraction",
    status="active",
    tier="LLM-LED",
    depends_on="audit identity ledger llm observability platform pricing runtime".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/extraction", "fe": None},
    context=ContextScope(
        purpose="Own source-document ingestion, parsing, validation.",
        in_scope=[
            "Uploaded-document and statement source lifecycle, parsed facts.",
            "Document parsing, confidence/balance validation, review disposition.",
            "Extraction-owned AtomicTransaction and AtomicPosition facts and source-to-fact evidence lineage.",
        ],
        out_of_scope=[
            "Double-entry journal ownership, account policy, and final ledger facts.",
            "Model-provider configuration, shared financial value/assurance ownership.",
            "Portfolio valuation, pricing resolution, reconciliation matching.",
        ],
    ),
    relationships=rels(
        "extraction",
        """
audit|published-language|Uses audit monetary, quantity, source-type.
audit|consumer-port|Consumes audit TraceRecord ports to attach evidence to extraction decisions.
identity|published-language|Uses the identity-owned user language to scope source documents and parsing work.
ledger|consumer-port|Uses ledger command and account ports to submit reviewed, dispositioned financial facts.
llm|published-language|Uses the LLM facade's typed OCR/vision/JSON call language.
observability|published-language|Uses published safe logging, PII, and parse-outcome telemetry language.
platform|composition|Uses platform persistence mixins and shared application exceptions.
pricing|published-language|Uses pricing FX-rate lookup and ExchangeRateLookup port language for cross-currency statement posting.
runtime|consumer-port|Consumes the runtime storage port and redaction helper for source content.
""",
    ),
    units=units(
        """
StatementSummary|agg
@ent|-|UploadedDocument AtomicTransaction AtomicPosition ClassificationRule TransactionClassification CorrectionLog EvidenceNode EvidenceEdge
resolve_transaction_identity|svc|extension/transaction_identity.py
effective_statement_transaction_filter|svc|extension/transaction_membership.py
@vo|base/source_vocabulary.py|RuleType DocumentType DocumentStatus TransactionDirection ClassificationStatus BankStatementStatus Stage1Status
@proj|-|ManagedPositionSnapshot EvidenceLineageService EvidenceGraphMaterializationService
ExtractionService|svc|extension/service.py
StatementIngestionUseCase|svc|extension/statement_parsing.py
@fac|-|build_statement_ingestion_use_case extraction_trace_policy_registry
DeduplicationService|svc|extension/deduplication.py
BrokeragePositionImportService|svc|extension/brokerage_positions.py
EvidenceGraphIntegrationService|svc|extension/evidence_graph_integration.py
snapshot_currencies|svc|extension/currencies.py
AtomicTransactionRepository|repo
BalanceChainViolated|ev
@vo|base/types.py|DocumentSource ExtractedTransactionRow ParseJob RetireStatementCommand StatementIngestionOutcome StatementIngestionStatus StatementPostingOutcome StatementPostingStatus
retire_statement|svc|extension/source_lifecycle.py
StatementExtractionResult|vo|base/result.py
ResolvedStatementContribution|vo|base/contribution.py
@svc|extension/statement_contribution.py|resolve_statement_contribution list_statement_contributions
ReviewedStatementEnvelopeCommand|vo|base/reviewed_statement_envelope.py
confirm_reviewed_statement_envelope|svc|extension/reviewed_statement_envelope.py
SourceCapability|vo|base/source_capability.py
DispositionPolicy|svc
@vo|base/disposition.py|DispositionDecision StatementDispositionPolicySnapshot IntentProposal IntentProposalOrigin
@svc|extension/disposition_trace.py|build_disposition_trace_records emit_disposition_trace_records
current_statement_disposition_policy_snapshot|svc|extension/disposition_policy.py
"""
    ),
    interface="""
AssetType AtomicPosition AtomicTransaction BankStatementStatus
BrokerageImportRejectedError BrokeragePositionImportService ClassificationRule
ClassificationStatus CorrectionLoopService CostBasisMethod CurrencyUnresolvedError
DEFAULT_MAX_DEPTH DeduplicationService DispositionCommand DispositionContext
DocumentSource DocumentStatus DocumentType EvidenceEdge
EvidenceGraphIntegrationService EvidenceGraphMaterializationService
EvidenceLineageService EvidenceNode EvidenceTraversalStep ExtractedPositionFact
ExtractionError ExtractionService ExtractedTransactionFact ExtractedTransactionRow
ExtractionMethod ManagedPosition PositionStatus ParseJob
RetryableStatementIngestionError RetireStatementCommand
ReviewedStatementEnvelopeCommand ReviewedStatementEnvelopeConflict RuleType
DispositionDecision DispositionMode DispositionPolicy DispositionStatus
ClassificationSuggestion SuggestionCorrectionError EconomicIntent IntentProposal
IntentProposalOrigin SourceCapability SourceCapabilityStatus SOURCE_CAPABILITIES
SourceProvenance SYSTEM_PROMPT Stage1Status StatementBalanceFact
StatementClassificationBusy StatementIngestionConfigurationError
StatementIngestionError StatementIngestionOutcome StatementIngestionStatus
StatementIngestionUseCase StatementDispositionPolicySnapshot
StatementExtractionResult ResolvedStatementContribution StatementEvidenceType
StatementPostingDependencies StatementPostingOutcome StatementPostingStatus
StatementSourceType StatementTransaction StatementEventSource StatementSummary
TransactionCategory TransactionClassification TransactionDirection UploadedDocument
BROKERAGE_IMPORT_FAILED_MESSAGE BROKERAGE_IMPORT_FAILURE_KEY
BROKERAGE_IMPORTABLE_STATUSES brokerage_import_failure_reason
clear_brokerage_import_failure record_brokerage_import_failure
_brokerage_import_not_ready_reason _brokerage_payload_from_persisted_extraction
_brokerage_payload_from_statement approve_statement_workflow
applied_rows_the_policy_accepts auto_create_posted_entries_for_statement
auto_accept_preference backfill_classifications build_csv_mapping_prompt
build_disposition_trace_records build_statement_ingestion_use_case
compute_confidence_score confirm_reviewed_statement_envelope create_entry_from_txn
get_or_create_account current_reviewed_statement_envelope
current_statement_disposition_policy_snapshot detect_balance_chain_break
balance_sheet_booking classification_suggestions classify_by_effective_policy
classify_statement_by_effective_policy lock_statement_classification
effective_auto_accept effective_classification effective_reconciliation
general_account_name reconciliation_enabled settle_drafts_after_posting
statement_disposition_policy_for_user apply_suggestion_feedback dual_write_layer2
emit_disposition_trace_records edit_and_approve extraction_trace_policy_registry
find_in_flight_parse_id get_correction_stats get_current_statement_extraction_result
get_known_storage_paths get_parsing_prompt get_statement_coverage_rows
get_statement_event_sources get_uploaded_document_filenames
looks_like_brokerage_document looks_like_brokerage_payload
parse_brokerage_csv_payload parse_brokerage_positions pending_stage1_review_filter
persist_statement_extraction_result record_correction resolve_statement_contribution
list_statement_contributions register_position_reconciler register_statement_source
reject_json_floats reject_statement_workflow retire_statement
resolve_custody_account_id resolve_ingest_currency resolve_statement_conflicts
resolve_bank_custody_account is_bank_custody_source is_preclassification_in_progress
coverage_bank_custody_account_ids resolve_statement_posting_account
resolve_statement_transactions effective_statement_transaction_filter
resolve_transaction_currency run_parsing_supervisor set_opening_balance
snapshot_currencies submit_parse_pipeline supports_reviewed_statement_envelope
validate_balance validate_balance_chain validation
""".split(),
    events=[],
    command_boundaries=[
        CommandBoundary(
            symbol="ReviewedStatementEnvelopeCommand",
            version="1",
            proof="apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_1_preserves_source_absence_until_typed_command",
        )
    ],
    invariants=invs(
        """
@$t/test_extraction_package.py
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_extraction_1_1_only_all_is_the_published_language
converges-by-layer|The package converges into base/ + extension/ + data/.|test_AC_extraction_1_2_converges_by_layer
base-layer-pure|Base/ never imports the package's own extension/ or data/, the ORM, or any network client.|test_AC_extraction_1_3_base_layer_is_pure
passes-own-governance-gate|Check_package_contract validates extraction with no violations.|test_AC_extraction_1_4_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "extraction",
        """
@$be/extraction/test_bank_custody_binding.py|P0
custody-binding.7|The additive custody migration installs the unique identity key.|test_real_custody_migration_installs_unique_key
custody-binding.1|Custody identity survives account display-name edits and sequential imports.|test_rename_preserves_source_custody
custody-binding.2|Concurrent first imports allocate one account and database uniqueness rejects a second binding.|test_concurrent_first_imports_share_one_binding
custody-binding.3|Exact institution, tenant, suffix.|test_custody_key_dimensions_remain_separate
custody-binding.4|Only unambiguous owned current source evidence may adopt an existing account.|test_historical_custody_adoption
custody-binding.5|Explicit account selection cannot bypass owner, currency, active asset type, or existing custody identity.|test_explicit_account_cannot_bypass_custody
custody-binding.6|Rejected or rolled-back new imports leave no orphan custody binding or account.|test_rejected_parse_does_not_leave_orphan_custody
@$be/extraction/test_human_source_review.py|P1
human-source-review.1|A complete balanced single-currency bank cash source below the shared auto-promotion threshold exposes explicit human envelope confirmation.|test_complete_dormant_source_human_confirmation
human-source-review.2|Human envelope commands fill only absent facts and cannot contradict declared source dates, currency, or balances.|test_human_confirmation_cannot_rewrite_known_source
human-source-review.3|An exact current human envelope takes precedence over machine promotion.|test_revoked_human_review_cannot_authorize_source
@$fe/__tests__/statementDetailReview.test.tsx|P1
human-source-review.4|The statement review UI offers the server-authorized confirmation form even.|complete dormant source offers explicit human confirmation
reviewed-envelope.6|Stage-1 review exposes required envelope confirmation and validation reasons, offers a cash envelope only for source facts it can prove.|AC-extraction.reviewed-envelope.6 confirms missing source envelope facts before approval|P0:invariant
fe-stage1-review.7|Statement page shows an error fallback and supports retry.|AC16.18.4 shows loading feedback while review data is pending|P2
fe-stage1-review.8|Statement page disables approve when balance validation fails.|AC16.18.5 disables approve when balance validation fails|P2
fe-stage1-review.9|Statement page approve and reject actions call the APIs and update the same page.|AC16.18.6 approves and rejects in place on the statement page without leaving it|P2
fe-stage1-review.13|Stage 1 approval stays enabled.|AC16.31.2 keeps approval enabled when intra-statement closing matches and shows 3198 cross-period gap notice|P0
fe-stage1-review.14|Stage 1 balance validation UI reports prior-period gap and intra-statement closing checks separately.|AC16.32.2 shows prior period anchor and closing balance validation states separately|P0
fe-stage1-review.17|Statement review page provides auto-filling default categories.|AC-extraction.fe-stage1-review.17 supports auto_fill_default_categories via auto-fill action on classification review
fe-stage1-review.25|The statement page shows the preview panel only for a PDF, PNG or JPG source.|AC-extraction.fe-stage1-review.25 shows the preview panel for a PDF source and none for a CSV source
fe-stage1-review.28|The statement page shows Import to Portfolio only for a brokerage statement, collapses the PDF preview card height.|AC-extraction.fe-stage1-review.28 hides Import to Portfolio on bank statements and collapses unavailable PDF preview
fe-ia-extraction.4|The statement review page keeps a persistent plain-language explanation and a single action that opens the unmatched queue scoped to that exact statement, with a return target back to its statement page.|AC-extraction.fe-ia-extraction.4 routes economic-review conflicts to the exact statement queue|P0
2826.2|On /statements/[id], review query updates sync directly into the rendered statement transactions.|AC-extraction.2826.2 enables custody account selection when account_id is null even without envelope confirmation
@$be/extraction/test_opening_evidence_lineage.py|P1
opening-lineage.4|A changed reparse of a source that established current opening stock requires correction review even with zero transactions or zero stock and preserves the prior source result and opening authority.|test_dormant_posted_source_reparse_requires_correction
opening-lineage.1|Current authoritative source-backed opening positions.|test_sourced_opening_reaches_pdf
opening-lineage.2|Opening lineage refuses retired, revoked, void, or mismatched source authority even.|test_cached_opening_lineage_rejects_retired_source
opening-lineage.3|Standalone manual opening balances retain honest journal lineage.|test_manual_opening_has_no_fabricated_pdf
@$be/extraction/test_source_ingestion_integrity.py|P1|done|property
persistence-proof.2|Only effective current-source transactions may enter downstream queues or actions.|test_effective_membership_excludes_superseded_sources
source-conservation.1|An unparseable transaction row cannot silently disappear behind a successful net-balance proof.|test_bad_dates_cannot_hide_offsetting_transactions
source-conservation.2|Paged extraction preserves every currency balance and rejects conflicting account or balance declarations.|test_paged_currency_and_account_conservation
transaction-identity.1|Distinct custody accounts and currencies retain independent atomic transactions.|test_identity_distinguishes_custody_and_currency
transaction-identity.2|A versioned identity may reuse a legacy atomic UUID and hash only.|test_legacy_identity_reuse_preserves_history
transaction-identity.3|An ambiguous historical identity is explicitly reviewable.|test_ambiguous_legacy_identity_is_reviewable
transaction-identity.4|Concurrent equal identities resolve to one atomic fact and source lineage remains complete.|test_concurrent_identity_upsert
retry-identity.1|Retry after failed institution detection uses the recovered source institution.|test_retry_discards_provisional_institution
source-routing.1|A typed bank extraction with an empty positions array remains a bank transaction ledger.|test_bank_result_never_routes_as_brokerage
source-routing.2|An explicitly typed brokerage snapshot with zero positions still routes to brokerage review.|test_empty_brokerage_snapshot_remains_reviewable
persistence-proof.1|Reparse retains historical atomic identities and lineage, exposes only the current source result.|test_reparse_preserves_history_and_current_membership
@$t/test_extraction_vocabulary.py|P0|done|property
source-vocabulary.1|Source-domain enum members have one pure base-layer owner with unchanged string values and no direct dependency on persistence or application configuration.|test_source_vocabulary_values_are_stable
source-vocabulary.3|Retired source-enum owners and ORM vocabulary imports cannot return.|test_source_vocabulary_has_one_owner
@$be/extraction/test_csv_parsing.py|P0|done|property
1.2|Parse CSV (DBS).|test_parse_dbs_csv
1.3|Parse CSV (Wise).|test_parse_wise_csv
1.4|Parse CSV (Generic).|test_parse_generic_csv_with_amount_column
1.5|Parse CSV with BOM.|test_parse_csv_with_bom|P1
2476.1|A CSV statement export that declares both opening and closing balances records balance_source=declared_in_csv_export and is not capped by the missing_from_csv_export completeness flag.|test_AC_extraction_2476_1_declared_csv_balances_are_not_marked_missing|P1
@$be/extraction/test_extraction.py|P0|done|property
2.1|Balance Validation (Pass).|test_balance_valid
2.2|Balance Validation (Fail).|test_balance_invalid
3.2|Medium Confidence (Review).|test_medium_confidence
3.3|Low Confidence (Manual).|test_low_confidence_empty_transactions
101.1|Valid balances pass validation.|test_balance_valid
101.2|Invalid balances fail validation.|test_balance_invalid
101.3|Small differences are tolerated.|test_balance_tolerance
102.1|Complete data gets high confidence (Auto-Accept).|test_high_confidence
102.3|No transactions lowers confidence (Manual).|test_low_confidence_empty_transactions
103.1|Verify DBS fixture has correct structure.|test_dbs_fixture_structure
103.2|Verify DBS fixture balances reconcile.|test_dbs_balance_reconciliation
103.3|Verify MariBank fixture has sanitized merchant names.|test_maribank_fixture_descriptions_carry_no_pii
103.4|Verify GXS fixture has daily interest entries.|test_gxs_fixture_daily_interest
103.5|Verify all fixtures have valid dates.|test_all_fixtures_have_dates
104.1|Verify default parsing prompt.|test_get_parsing_prompt_default
104.2|Verify DBS-specific prompt.|test_get_parsing_prompt_dbs
104.3|Verify CMB-specific prompt.|test_get_parsing_prompt_cmb
104.4|Verify with unknown institution returns base prompt.|test_get_parsing_prompt_unknown_institution
104.5|Verify Futu-specific prompt.|test_get_parsing_prompt_futu
104.6|Verify GXS-specific prompt.|test_get_parsing_prompt_gxs
104.7|Verify MariBank-specific prompt.|test_get_parsing_prompt_maribank
105.2|PNG images use 'image_url' type.|test_png_uses_image_url_type
105.3|JPG images use 'image_url' type.|test_jpg_uses_image_url_type
105.4|JPEG images use 'image_url' type.|test_jpeg_uses_image_url_type
106.1|CSV parsing raises error when institution is None.|test_csv_requires_institution
106.2|Parse_document accepts institution=None for PDFs.|test_parse_document_accepts_none_institution_for_pdf
106.3|Parse_document accepts force_model parameter.|test_parse_document_accepts_force_model
107.5|Verify _safe_date with valid input.|test_safe_date_valid
107.6|Verify _safe_date with invalid format.|test_safe_date_invalid_format
107.7|Verify _safe_date with empty input.|test_safe_date_empty
107.8|Verify _safe_decimal with valid input.|test_safe_decimal_valid
107.9|Verify _safe_decimal with invalid input.|test_safe_decimal_invalid
107.10|Verify _safe_decimal with None.|test_safe_decimal_none
107.11|Verify _safe_decimal None required.|test_safe_decimal_none_required
107.12|Verify compute_confidence with missing transactions key.|test_compute_confidence_missing_transactions
108.1|Verify consistent chain scores 10.|test_consistent_chain
108.2|Verify inconsistent chain scores 0.|test_inconsistent_chain
108.3|Verify single transaction.|test_single_txn
108.4|Verify no balance after.|test_no_balance_after
108.5|Verify empty list.|test_empty_list
108.6|Verify partial consistency.|test_partial_consistency
108.7|Verify all currencies match.|test_all_match_header
108.8|Verify no currencies match.|test_none_match
108.9|Verify no header currency.|test_no_header_uses_most_common
108.10|Verify no currencies in transactions.|test_no_currencies
108.11|Verify empty list (currency).|test_empty_list
108.12|Verify mixed currencies partial.|test_mixed_currencies_partial
108.13|Verify missing currencies penalized.|test_missing_currencies_penalized
109.1|Verify full score with all factors.|test_full_score_with_all_factors
109.2|Verify no new factors caps at 85.|test_no_new_factors_caps_at_85
115.1|Brokerage statement with a single transaction is penalized below the review/auto-approve band.|test_brokerage_single_txn_penalized|P1
115.2|Brokerage statement with a plausible transaction count is not penalized.|test_brokerage_sufficient_txns_not_penalized|P1
115.3|Non-brokerage statement with one transaction keeps its existing score.|test_bank_single_txn_not_penalized|P1
115.4|`is_brokerage` defaults to False so existing callers are unaffected.|test_default_is_not_brokerage|P1
115.5|The cap uses the persisted transaction count, not the raw extracted count.|test_effective_count_uses_persisted_not_extracted|P1
@$be/extraction/test_pdf_parsing.py|P1|done|property
2.3|Completeness Validation.|test_missing_required_fields_detected
2.4|Bank statement balance mismatches preserve validation_error details.|test_parse_document_bank_balance_mismatch_records_validation_error|P0
4.1|Invalid Parse Not Persisted.|test_extraction_error_not_persisted|P0
4.3|Extraction Timeout.|test_extraction_timeout_raises_error
5.2|File Size Limit.|test_upload_file_exceeds_10mb_limit
@$be/extraction/test_extraction_flow.py|P0|done|property
2.5|CSV transaction exports without statement balances remain reviewable.|test_parse_document_csv_without_statement_balances_remains_reviewable
4.2|Unsupported File Type.|test_parse_document_unsupported_type|P1
5.3|Model Selection Flow.|test_parse_document_csv_success|P1
5.4|Extraction Flow Tests.|test_parsed_statement_sets_stage1_pending_review
1622.8|A statement routed to parsed/review carries stage1_status = pending_review explicitly.|test_parsed_statement_sets_stage1_pending_review|P1:-
@$be/api/test_statements_approval.py|P0|done|property
3.1|High Confidence (Auto-Accept).|test_auto_approve_high_confidence_statement_creates_posted_entries
6.1|Unique Prior Mapping.|test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account
6.3|Ambiguous Mapping Blocked.|test_approve_statement_stage1_blocks_ambiguous_account_mapping
6.4|Explicit First-Upload Account Creation.|test_approve_statement_stage1_creates_account_with_explicit_confirmation
6.5|Prior Mapping Requires Confirmed Statement.|test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping
6.6|Source Period Unique Before Posting.|test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting
statement-memo.1|A statement row whose description is longer than the memo column of the journal entry posts one entry.|test_AC_extraction_statement_memo_1_approval_posts_a_row_with_a_long_description|:-
reviewed-envelope.4|Stage-1 approval consumes complete source facts or a current valid reviewed-envelope decision.|test_AC_extraction_reviewed_envelope_4_approval_uses_reviewed_envelope_and_disposition|:invariant
disposition.5|Stage 1 source confirmation returns a committed pending-review outcome, never a successful approval.|test_AC_extraction_disposition_5_stage1_requires_economic_review|:invariant
disposition.6|Before a Stage 1 disposition can create a ledger command, its emitted source decision must be authoritative.|test_AC_extraction_disposition_6_auto_post_requires_authoritative_trace_decision|:invariant
2822.2|POST /statements/{id}/review/approve accepts an explicit account_id in Stage1ApprovalRequest to bind a user-owned active asset custody account.|test_AC_extraction_2822_2_approve_binds_explicit_account_id_and_review_reports_preclassification_in_progress|P1
2826.1|StatementReviewResponse inherits BankStatementResponse and get_statement_for_review delegates base payload construction to compose_statement_response.|test_AC_extraction_2826_1_review_response_inherits_bank_statement_response|P1
@$e2e/test_accounts_and_statements_ui_journey.py|P0|done|property
5.1|Full Upload Flow.|test_statement_detail_and_review_surface
813.12|A statement upload's full browser journey returns a 2xx with an id, the row appears in the statement list.|test_statement_detail_and_review_surface
@$be/api/test_statements_router.py|P1|done|property
5.6|Invalid file extension should return 400.|test_upload_invalid_extension
5.7|PDF/image uploads may omit model and use the default OCR pipeline.|test_upload_uses_default_ocr_pipeline_for_pdf|:invariant
5.8|Upload rejects models without image modalities.|test_upload_rejects_text_only_model
5.9|Upload then list statements and transactions.|test_list_and_transactions_flow
5.10|Review queue includes reviewable parsed statements and supports approve/reject.|test_pending_review_and_decisions
5.11|Missing statement returns 404.|test_get_statement_not_found
5.12|File exceeding 10MB limit returns 413.|test_upload_file_too_large
5.13|Extraction failure marks statement as rejected.|test_upload_extraction_failure
5.14|Retry on missing statement returns 404.|test_retry_statement_not_found
5.15|Retry rejects models without image modalities.|test_retry_rejects_text_only_model
5.16|Retry returns 503 if source retrieval fails.|test_retry_statement_storage_failure
5.17|Retry on statement not in parsed/rejected status returns 400.|test_retry_statement_invalid_status
5.18|Retrying a statement in PARSING status is allowed.|test_retry_statement_parsing_allowed
5.19|Retry parsing with stronger model succeeds.|test_retry_statement_success
5.20|Retry extraction failure returns 422.|test_retry_statement_extraction_failure
5.21|Upload rejects models not in the OpenRouter catalog.|test_upload_statement_rejects_invalid_model
5.22|Upload rejects a model lacking image/PDF modality (400).|test_upload_statement_rejects_model_without_image_modality
5.23|Retry rejects a model not in the catalogue (400).|test_retry_statement_rejects_invalid_model
5.24|Background parse error should be caught and logged.|test_background_parse_error_logging
5.25|Background retry error should be caught and logged.|test_background_retry_error_logging
105.1|PDF payloads use provider-compatible `file` or `image_url` shapes.|test_build_statement_storage_key_sanitizes_extension|P0
121.3|The retry endpoint accepts a balance-invalid statement at its `PARSED` resting state.|test_AC13_21_3_retry_accepts_parsed_resting_state|P0
121.6|CSV upload with a missing institution fails synchronously with HTTP 400 and an actionable message.|test_AC13_21_6_csv_missing_institution_rejected_sync|P0
stage1-validation.9|A Stage 1 pending_review -> rejected transition triggers re-parse.|test_stage1_reject_triggers_reparse|P0
document-delivery.1|Stage 1 statement review PDF previews use short-lived presigned URLs for sandboxed iframe embedding.|test_AC16_33_4_get_statement_for_review_uses_short_presign_ttl|P0
document-delivery.2|The Stage 1 PDF preview streams bytes same-origin.|test_AC16_33_5_get_statement_document_streams_bytes_same_origin|P0
statement-list.4|GET /api/statements/{id} and GET /api/statements/{id}/transactions return each statement transaction with its 1-based source_row ordinal from StatementExtractionResult.transactions and order rows by source_row.|test_AC_extraction_statement_list_4_transactions_expose_source_row_in_source_order|:-
1913.9|Accepting a statement upload persists and binds its immutable ODS source artifact.|test_AC_extraction_1913_9_upload_registers_source_before_dispatch|P0:invariant
@$be/reconciliation/test_review_queue.py|P1
6.2|No Silent Fallback Posting.|test_create_entry_from_txn_auto_post_requires_account_mapping|P0:property
1801.3|Create_entry_from_txn reads the Layer-3 classification and requires its reviewed account and authoritative disposition command.|test_create_entry_from_txn_uses_layer3_classification_account
1801.4|Without a Layer-3 classification and authoritative disposition, an outflow is routed to review and creates no ledger entry.|test_create_entry_from_txn_outflow_without_disposition_requires_review
1801.5|Without a Layer-3 classification and authoritative disposition, an inflow is routed to review and creates no ledger entry.|test_create_entry_from_txn_inflow_without_disposition_requires_review
1779.1|Journal-entry creation for a foreign-currency transaction resolves a missing FX rate.|test_create_entry_from_txn_lazy_loads_missing_fx_rate|:property
@$be/accounting/test_account_statement_coverage.py|P1|done|property
7.1|Latest Confirmed Source.|test_account_coverage_reports_latest_confirmed_balance_and_stale_status
7.2|Adjacent Opening Continuity.|test_account_coverage_detects_adjacent_opening_balance_mismatch
7.3|Missing/Overlapping/Duplicate Periods.|test_account_coverage_reports_missing_overlapping_and_duplicate_ranges
7.4|Broker Daily Snapshot Override.|test_account_coverage_accepts_broker_monthly_cadence_with_daily_snapshot_override
@$be/extraction/test_storage_sweep.py|P1|done|property
8.1|Delete old orphaned storage objects.|test_sweep_deletes_orphaned_object
8.2|Preserve objects with DB records.|test_sweep_skips_known_db_objects
8.3|Skip recent in-flight uploads.|test_sweep_skips_recent_objects
8.4|No-op without configured S3 bucket.|test_sweep_skips_when_no_bucket_configured
8.5|Return zero for empty statement prefix.|test_sweep_returns_zero_when_no_objects
8.6|Handle storage listing errors.|test_sweep_handles_storage_list_error
8.7|Handle object delete errors.|test_sweep_handles_delete_error
8.8|Paginate storage keys and normalize timestamps.|test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps
8.9|Convert storage client listing errors.|test_list_storage_keys_raises_on_client_error
8.10|Exit runner on stop event.|test_run_storage_sweep_exits_on_stop_event
8.11|Log runner deletion counts.|test_run_storage_sweep_logs_when_objects_deleted
8.12|Continue runner after unexpected sweep exception.|test_run_storage_sweep_handles_exception
8.13|Disable runner by feature flag.|test_run_storage_sweep_disabled_by_feature_flag
8.14|Grace period + interval config defaults match issue #356.|test_grace_period_and_interval_defaults_match_issue_356
8.15|Sweep grace-period cutoff is config-driven, not a hardcoded constant.|test_sweep_reads_grace_period_from_config
8.16|Sweep runner wait interval is read from config.|test_run_storage_sweep_reads_interval_from_config
@$be/extraction/test_statement_result_contract.py|P1|done|property
11.1|A source with only one statement-period bound is rejected.|test_AC_extraction_11_1_partial_period_rejects_without_copying
11.2|Transaction-row dates remain observations and cannot establish an absent statement period.|test_AC_extraction_11_2_transaction_dates_do_not_establish_statement_period
11.3|A transaction without a source-declared transaction date is rejected.|test_AC_extraction_11_3_missing_transaction_date_rejects
112.1|The canonical SourceCapability registry contains exactly one semantic entry for every product source class and contains no testing paths.|test_AC_extraction_source_capability_1_declares_semantics_not_test_paths|P0
result-envelope.1|Every live, CSV, cassette.|test_AC_extraction_result_envelope_1_rejects_unknown_versions_and_defaults|P0
result-envelope.2|A StatementExtractionResult round-trips exact bank and brokerage balances, transactions, positions, confidence, warnings, provenance, source closing values, stable identity.|test_AC_extraction_result_envelope_2_round_trips_complete_facts|P0:invariant
source-capability.1|Extraction publishes one stable semantic SourceCapability per source class.|test_AC_extraction_source_capability_1_declares_semantics_not_test_paths|P0
@$be/extraction/test_statement_brokerage_import_bridge.py|P1|done|property
12.1|A brokerage holdings statement with no opening/closing balances persists `balance_validated=None`.|test_AC3_12_1_brokerage_without_balances_reports_balance_validated_none_not_vacuous_true
304.7|Upload Parse-to-Import Bridge.|test_parse_statement_background_imports_brokerage_positions|P0:-
@$be/extraction/test_extraction_error_paths.py|P1
118.1|The vision path uses the multimodal model only.|test_a_service_has_one_multimodal_model_role|:property
118.2|When the vision model raises a non-retryable provider error, no other model is tried.|test_vision_path_does_not_fall_back_to_another_model_on_a_non_retryable_error|:property
111.1|Dual-write handles a duplicate document identity by selecting and continuing with the canonical database winner.|test_dual_write_layer2_integrity_error_is_non_fatal|:property
812.6|OCR/vision provider fallback, timeout.|test_extract_financial_data_shared_ocr_vision_skips_layout_parser
812.4|PDF with private URL logs warning and raises ExtractionError.|test_extract_financial_data_pdf_private_url_raises
812.5|Image with private URL logs warning and raises ExtractionError.|test_extract_financial_data_image_private_url_raises
1622.10|A hard parse failure persists an UploadedDocument.|test_handle_parse_failure_persists_failed_document_lineage
parse-robustness.1|A statement transaction whose description is null, empty, blank or absent keeps its row with the description "Unknown".|test_parse_document_uses_placeholder_for_missing_description
@$be/extraction/test_tolerant_date_parsing.py|P1|done|property
119.1|Common non-ISO date formats parse; empty/garbage return None.|test_AC13_19_1_tolerant_parse_date_accepts_non_iso_formats
119.2|A Chinese-format statement parses instead of being rejected.|test_AC13_19_2_chinese_format_statement_parses_instead_of_aborting
119.3|Unparseable transaction dates are explicitly quarantined.|test_AC13_19_3_one_bad_row_date_is_quarantined
119.4|The model is the primary date normalizer.|test_AC13_19_4_parsing_prompt_instructs_iso_date_normalization
@$be/extraction/test_json_repair.py|P1|done|property
114.1|A markdown json-fenced object is recovered.|test_strips_json_code_fence
114.2|Surrounding prose and a bare fence reduce to the outermost balanced object.|test_strips_bare_code_fence_and_prose
114.3|An already-clean object round-trips unchanged.|test_clean_object_is_preserved
114.4|Content with no recoverable JSON object returns None.|test_unrecoverable_returns_none
114.5|The extraction loop salvages a fenced response.|test_fenced_response_is_salvaged
114.6|A response with no recoverable JSON still fails with a `json_parse` extraction failure.|test_unrecoverable_response_still_fails
114.7|When a small example object precedes the real extraction, the largest object is recovered.|test_prefers_largest_object_when_example_precedes_real
114.8|A complete object followed by trailing unbalanced-brace junk still recovers the complete object.|test_complete_object_then_trailing_unbalanced_brace
114.9|A leading unmatched brace.|test_leading_unbalanced_brace_then_real_object
2813.2|Ai_json_max_tokens defaults to 32768.|test_AC_extraction_2813_2_truncated_outer_statement_does_not_salvage_inner_transaction
@$be/reconciliation/test_source_type.py|P0|done|property
110.1|Source type stamped on manual entry creation.|test_source_type_stamped_on_create
110.2|Auto-match records trusted anchor.|test_auto_match_records_anchor_without_mutating_posted_source_type
110.5|Source_type cannot be downgraded.|test_source_type_no_downgrade|P1
110.6|The manual journal API rejects caller-selected source_type values.|test_public_journal_api_rejects_caller_selected_source_type|P1
@$t/test_source_capability_proof.py|P0|done|property
112.2|Every supported automated SourceCapability resolves to both deterministic PR proof and release-validation proof.|test_AC_extraction_112_2_supported_capabilities_require_release_proof
112.3|A gap SourceCapability cannot be claimed as covered by the positive semantic proof graph.|test_AC_extraction_112_3_gap_capabilities_cannot_claim_proof
@$be/extraction/test_deduplication.py|P1|done|property
111.2|Malformed transaction source lineage requires review.|test_upsert_scoped_atomic_transaction_handles_non_list_source_documents
122.1|Two distinct same-date/same-amount/same-direction rows sharing one running `balance_after` hash differently within one document.|test_AC13_22_1_same_balance_distinct_rows_do_not_collapse|P0
406.8|AtomicTransaction persists the extracted balance_after.|test_upsert_persists_balance_after|:-
216.1|Distinct running balances hash differently.|test_running_balance_distinguishes_identical_transactions|P0:-
@$be/extraction/test_extraction_determinism.py|P0|done|property
113.1|Pure scoring + routing functions return identical results.|test_scoring_and_routing_are_deterministic
113.2|Re-parsing identical model output yields identical confidence/status/validation_error.|test_repeated_parse_yields_identical_confidence_status_validation
113.3|Each payload class routes consistently across N parses.|test_routing_is_consistent_per_payload_class
121.2|_Superseded by AC-extraction.2009.2._ A parsed bank statement that fails balance reconciliation is now BLOCKING.|test_AC20_9_2_balance_invalid_parse_is_quarantined
121.5|_Superseded by AC-extraction.2009.2._ The same balance-mismatch payload routes deterministically.|test_routing_is_consistent_per_payload_class
@$be/extraction/test_dual_write_layer2.py|P0|done|property
122.2|A parsed statement with two same-date/same-amount deposits separated by a carried-forward/brought-forward balance repeat persists both deposits and the running-balance chain reconciles.|test_AC13_22_2_page_boundary_duplicate_deposit_survives
213.1|Parsing populates Layer 1/2 by default.|test_dual_write_enabled_by_default|:-
1622.9|UploadedDocument.status advances to completed once a successful parse is persisted.|test_dual_write_marks_document_completed|P1:-
@$be/extraction/test_seed_determinism.py|P1|done|property
116.2|Extraction forwards the configured `ai_json_seed` to the model call.|test_extraction_forwards_configured_seed
116.3|Extraction pins `temperature=0` / `do_sample=False` alongside the seed.|test_extraction_decoding_is_deterministic_by_default
116.4|Empty `AI_JSON_SEED` parses as None (omitted) instead of raising.|test_empty_seed_env_is_treated_as_none
116.5|The seed is off by default.|test_seed_is_off_by_default
@$be/extraction/test_self_consistency.py|P1|done|property
117.1|A reconciling first parse is returned without retry.|test_reconciles_first_attempt_single_call
117.2|A failing parse is retried and the reconciling result wins.|test_retries_until_reconciles
117.3|When no attempt reconciles, the smallest-difference result is kept.|test_keeps_best_when_none_reconcile
117.4|Brokerage payloads are not retried.|test_brokerage_is_not_retried
117.5|Attempt 0 uses the configured seed; retries vary it.|test_seed_varies_per_attempt
117.6|`AI_EXTRACT_MAX_ATTEMPTS=1` keeps single-shot behavior.|test_max_attempts_one_disables_retry
117.7|A structurally-invalid parse does not win "best" over a numerically-close parse.|test_structurally_invalid_parse_does_not_win_as_best
117.8|If every attempt is structurally invalid, the last parse is returned.|test_all_invalid_returns_last_parse
117.9|A transient extraction error on a retry attempt keeps the earlier usable parse.|test_transient_retry_error_keeps_earlier_usable_parse
117.10|If every attempt raises, the error propagates.|test_all_attempts_error_reraises
117.11|A transient error on the first attempt does not abort.|test_first_attempt_error_then_success_recovers
117.12|An error after an earlier usable parse keeps trying remaining attempts.|test_error_mid_run_does_not_skip_remaining_attempts
@$be/extraction/test_chain_break_detector.py|P1|done|property
120.1|AC-C1: detector pinpoints the exact break index on a crafted chain with a dropped row.|test_AC13_20_1_detector_finds_break_index_on_dropped_row
120.2|AC-C1: a clean running-balance chain reports no break.|test_AC13_20_2_clean_chain_reports_no_break
120.3|AC-C1: detection is Decimal-based and tolerant within `BALANCE_TOLERANCE`.|test_AC13_20_3_detector_is_decimal_tolerant
@$be/extraction/test_parse_user_deletion_lifecycle.py|P0|done|property
123.2|Parse-failure lineage write re-checks user existence and skips the FK-violating insert.|test_AC13_23_2_failed_lineage_skips_when_user_deleted
123.3|The failure handler rolls back.|test_AC13_23_3_failure_handler_rolls_back_before_reading_orm
@$be/extraction/test_classification_service.py|P0
212.1|Re-applying the same rule version to the same atomic transaction is idempotent and returns the existing classification.|test_apply_rules_is_idempotent_for_existing_transaction_rule_version
1801.1|RuleType.ML_MODEL rule matching is RETIRED.|test_AC18_1_3_ml_rule_matching_is_retired|P1
1801.2|Classification priority is KEYWORD > REGEX.|test_classification_priority_keyword_over_regex|P1
classification-priority.1|Among same-type rule matches, the newest rule version wins deterministically.|test_same_type_rules_prefer_newer_version
@$be/extraction/test_statement_summary_conform.py|P0
215.3|Custody account resolves from a Layer-2 atomic transaction.|test_resolve_custody_account_from_atomic_txn
215.4|The resolver returns None.|test_resolve_returns_none_without_account
215.5|The resolver normalizes a {'documents'.|test_resolve_handles_dict_wrapper_source_documents
215.6|The resolver skips junk entries, non-bank-statement sources.|test_resolve_ignores_invalid_and_non_bank_sources
215.7|A non-list/non-dict source_documents value resolves to None.|test_resolve_returns_none_for_non_list_source_documents
215.8|The first source document with a confirmed account wins.|test_resolve_preserves_source_document_order
215.9|A known source document with no confirmed custody account resolves to None.|test_resolve_returns_none_when_no_source_has_account
413.6|Currency_balances JSONB persists a per-currency balance array additively to the scalar columns.|test_AC1_currency_balances_jsonb_round_trips|P1
@$be/extraction/test_brokerage_csv_routing.py|P1
332.1|Brokerage positions CSV is mapped into a positions payload.|test_AC17_32_1_brokerage_positions_csv_produces_positions_payload
332.2|Brokerage trade-history CSV raises an actionable unsupported- document error, not the generic bank 'No valid transactions' failure.|test_AC17_32_2_brokerage_trade_history_csv_raises_actionable_error
332.3|Bank transaction CSV parsing is unaffected by brokerage CSV detection.|test_AC17_32_3_bank_csv_unaffected_by_brokerage_detection
@$be/extraction/test_brokerage_position_extraction_wiring.py|P0
304.9|AC-B1 Producer routing: brokerage docs select the positions prompt.|test_AC_B1_looks_like_brokerage_document_routes_by_filename_and_institution
304.10|AC-B2 Brokerage positions output schema flows into AtomicPosition-ready snapshots.|test_AC_B2_positions_prompt_payload_is_understood_by_consumer_parser
304.11|AC-B5 Zero-position brokerage doc is surfaced as a visible review flag.|test_AC_B5_zero_position_brokerage_doc_raises_visible_review_flag|P1
304.12|AC-B4/B6 Moomoo holdings TABLE extracts and imports.|test_AC_B4_AC_B6_moomoo_positions_table_extracts_and_imports
304.13|AC-B3 A multi-currency brokerage position snapshot never fabricates opening/closing cash balances from position market values or cross-sums currencies.|test_AC_B3_multi_currency_brokerage_does_not_fabricate_cash_balances
@$be/llm/test_llm_led_blocking_gate.py|P0
2009.2|LLM-LED tier balance-chain failure is a BLOCKING runtime gate.|test_AC20_9_2_imbalanced_bank_extraction_is_quarantined_not_parsed
2009.3|LLM-LED tier dedup-conservation failure is an INDEPENDENT blocking gate.|test_AC20_9_3_within_doc_dedup_collapse_is_quarantined
2009.4|LLM-LED tier gate is fail-closed.|test_AC20_9_4_declared_missing_balance_is_review_only
2009.5|The prior 'imbalanced bank statement → parsed/review' behavior no longer exists.|test_AC20_9_5_imbalanced_no_longer_routes_to_parsed_review
2009.6|No false reject: a balanced, dedup-consistent bank-statement extraction still flows.|test_AC20_9_6_valid_extraction_passes_gate_unchanged
2009.7|Each LLM-LED gate failure mode emits a distinct structured reason code and a distinct PII-free metric kind, with no institution name or account identifier in the signal.|test_AC20_9_7_each_failure_mode_has_distinct_reason_and_metric
2009.8|A db-backed quarantine persists the terminal `rejected` status to the statement row, writing no Layer-2 financial rows.|test_AC20_9_8_quarantined_statement_persists_rejected_not_stuck_parsing
@$be/infra/test_evidence_lineage_contract.py|P1
1807.1|The Evidence Graph SSOT defines nodes as auditable states, edges as transformation processes, allowed foundation node/edge fields, traversal direction.|test_AC18_7_1_evidence_lineage_ssot_defines_graph_semantics
1807.3|SQLAlchemy models expose EvidenceNode and EvidenceEdge with JSONB properties and user-owned isolation.|test_AC18_7_3_evidence_lineage_models_expose_jsonb_user_owned_graph_tables
@$be/extraction/test_evidence_lineage.py|P1
1807.4|The evidence lineage service supports idempotent node and edge upsert keyed by user, entity identity, node kind, relation.|test_AC18_7_4_node_and_edge_upserts_are_idempotent
1807.5|The evidence lineage service resolves entity nodes and traverses upstream and downstream paths only within the authenticated user's scope.|test_AC18_7_5_traversal_resolves_upstream_and_downstream_by_entity|P0
1807.6|Evidence lineage traversal enforces a default maximum depth and never walks unbounded graphs.|test_AC18_7_6_traversal_enforces_depth_limit
1807.7|Evidence Graph foundation tests cover node creation, edge creation, duplicate upsert behavior, upstream traversal, downstream traversal, depth limit.|test_AC18_7_5_cross_user_edges_and_traversal_are_blocked|P0
@$be/extraction/test_evidence_graph_materialization.py|P1
1808.1|Statement upload creates a source_document node for the uploaded source.|test_AC18_10_4_direct_entity_materialization_branches_are_idempotent
1808.2|Layer 2 lineage creates atomic_fact nodes for atomic transactions and deduped_into edges from the source_document that produced them.|test_AC18_10_4_direct_entity_materialization_branches_are_idempotent
1810.1|The Evidence Graph SSOT defines the graph as an audit projection, business tables as source of truth.|test_AC18_10_7_missing_and_cross_user_requests_return_explicit_blockers
1810.2|New source-to-ledger workflows materialize graph nodes and edges in the same database transaction as their owning business facts.|test_AC18_10_2_graph_writes_share_the_business_transaction
1810.4|Lazy materialization is idempotent and only uses strong relationships such as owned source IDs, transaction lineage.|test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts|P0
1810.6|Lazy repair never mutates accounting facts, report amounts, ledger balances, or legacy JournalEntry.source_type/source_id values.|test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts|P0
1810.7|Tests cover request-time lazy repair, repeated-read idempotency, cross-user blocking, unknown provenance blockers.|test_AC18_10_7_materialization_caps_and_unknown_sources_return_blockers
@$be/api/test_review_router.py|P1
1808.3|Journal posting creates ledger_entry and ledger_line nodes, links extracted or atomic transaction facts to the ledger entry with posted_as.|test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph
1808.6|Existing JournalEntry.source_type/source_id semantics remain backward-compatible.|test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph
@$be/api/test_personal_report_package_contract.py|P1
1808.4|Package traceability preserves the reviewed source decision.|test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary
1808.5|Unknown or unsupported JournalEntry.source_id values produce explicit blocker codes and never fabricate statement, atomic, or document anchors.|test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions|P0
1808.7|Tests cover source downstream impact, reviewed transaction to ledger decision ancestry.|test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary
disposition.7|Every disposition TraceRecord binds the exact versioned runtime policy snapshot.|test_AC_extraction_disposition_7_frozen_package_persists_trace_bound_policy_snapshot|P0:invariant
@$be/api/test_evidence_lineage_router.py|P1
1809.1|An authenticated Evidence Graph lineage API resolves an owned graph node by entity_type, entity_id.|test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions
1809.2|The lineage API supports upstream, downstream.|test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions
1809.3|Missing, unsupported, or cross-user entity identities return explicit empty/blocker state and never fabricate source, ledger, or report anchors.|test_AC18_9_3_lineage_api_returns_blocker_for_missing_or_cross_user_anchor|P0
1810.3|The lineage API attempts one bounded deterministic materialization pass.|test_AC18_10_3_AC18_10_4_lineage_api_lazily_materializes_historical_journal_line
1831.1|Evidence Graph node and edge DTO properties are constrained by closed typed Pydantic models per node kind and edge relation.|test_AC18_31_1_node_properties_are_typed_and_round_trip
1831.2|A genuine materialization failure returns a non-2xx status with a structured EvidenceLineageError detail.|test_AC18_31_2_failure_status_distinguishes_genuine_failure_from_empty|P0
@$be/extraction/test_correction_service.py|P1
1802.1|The CorrectionLog model records the original and corrected categories.|test_record_correction_stores_corrected_category
1802.2|The corrections API records and retrieves correction stats, scoped to the owning user.|test_AC18_2_2_record_correction_rejects_cross_user_corrected_account
1802.3|Few-shot examples from corrections are injected into the extraction prompt.|test_prompt_injection_with_corrections
1802.4|The correction cache has a 1-hour TTL and also invalidates immediately.|test_few_shot_cache_invalidates
@$be/extraction/test_correction_loop.py|P1
1814.1|The correction corpus is derived from CorrectionLog, keyed by the transaction pattern, capturing proposed vs corrected.|test_AC18_14_1_corpus_is_derived_from_corrections_keyed_by_pattern
1814.2|Replaying the corpus as priors strictly lowers the held-out low-confidence proportion.|test_AC18_14_2_replay_lowers_low_confidence_proportion_when_patterns_recur
1814.3|The service builds the corpus from the persisted correction store, scoped to the user.|test_AC18_14_3_service_builds_corpus_from_persisted_corrections
1814.4|The service replays the live corpus and measures the held-out reduction.|test_AC18_14_4_service_replay_measures_held_out_reduction
@$be/extraction/test_transaction_classification.py|P1|done|property
1815.1|The classification policy is a versioned, effective-dated, immutable object.|test_AC18_15_1_policy_is_effective_dated_and_immutable
1815.2|The classify pass is reproducible.|test_AC18_15_2_classify_is_reproducible_for_same_inputs
1815.3|Model output is constrained to the policy's closed catalog.|test_AC18_15_3_off_catalog_proposal_is_rejected_never_applied
1815.4|With auto_accept_ai_suggestions off.|test_AC18_15_4_confidence_gate_applies_reviews_or_tails
1815.5|The model never touches money.|test_AC18_15_5_model_never_touches_money|P0
1815.6|Commit_basis=False computes verdicts under a candidate policy.|test_AC18_15_6_pro_forma_writes_nothing
1815.7|A user's deterministic rule wins.|test_AC18_15_7_user_rule_prepass_wins_over_model
1815.8|Enable_ai_classification controls only live model proposals.|test_AC18_15_8_flag_off_skips_llm_not_deterministic_rules
non-pnl-categories.1|With auto_accept_ai_suggestions off.|test_AC_extraction_non_pnl_categories_1_balance_sheet_class_is_never_applied|P0
non-pnl-categories.2|With auto_accept_ai_suggestions off.|test_AC_extraction_non_pnl_categories_2_other_buckets_never_auto_apply|P0
non-pnl-categories.3|Policy v1 stays frozen with its 18 income and expense classes.|test_AC_extraction_non_pnl_categories_3_policy_v1_stays_frozen_and_v2_adds_the_four_classes
non-pnl-categories.4|The classification prompt names the four balance-sheet classes, says.|test_AC_extraction_non_pnl_categories_4_prompt_names_the_new_classes
accept-ai-suggestions.4|Classification_suggestions returns the latest applied or draft classification of each transaction with its category, score, account and applied flag.|test_AC_extraction_accept_ai_suggestions_4_reader_returns_the_latest_classification_per_transaction
1817.1|Every classification entry seam has a production call site and the core pass is wired to a live seam.|test_AC18_17_1_no_classify_writer_is_defined_but_uninvoked|P0
1817.3|Reports consume exactly one classification source and only APPLIED rows.|test_AC18_17_3_reports_read_only_applied_classifications|P0
ai-classification-default.1|The code default of enable_ai_classification is true.|test_AC_extraction_ai_classification_default_1_new_user_gets_model_proposals
@$be/extraction/test_classification_migration.py|P0|done|property
1816.1|Publishing a new policy version leaves every already-covered period's as-reported income statement byte-identical.|test_AC18_16_1_new_policy_version_never_restates_covered_periods
1816.2|The income statement has reviewed categorized leaf lines.|test_AC18_16_2_import_produces_categorized_income_statement
1816.3|With enable_ai_classification off and no matching reviewed rule, the import path writes zero classification rows and routes unknown economic meaning to review.|test_AC18_16_3_flag_off_routes_unknown_meaning_to_review|P1
1816.4|The one-time backfill classifies each not-yet-classified transaction once under its own effective policy.|test_AC18_16_4_backfill_is_idempotent_dated_append_only|P1
1816.5|Re-running classification never rewrites posted journal entries or lines.|test_AC18_16_5_reclassification_never_rewrites_posted_entries
@$be/api/test_statement_ai_suggestion_accept.py|P1|done|property
accept-ai-suggestions.1|The one-click approval posts a row that has a usable draft AI suggestion to the suggested account and category, as a reviewed disposition.|test_AC_extraction_accept_ai_suggestions_1_auto_fill_posts_the_draft_category_and_account|P0
accept-ai-suggestions.3|A draft suggestion whose account type contradicts the direction of the row is not used.|test_AC_extraction_accept_ai_suggestions_3_a_suggestion_that_contradicts_the_direction_falls_back
accept-ai-suggestions.5|The one-click approval leaves a row that the classifier already applied to the normal posting.|test_AC_extraction_accept_ai_suggestions_5_applied_rows_keep_their_ai_category|P0
classification-hardening.4|The one-click approval leaves an applied row to the normal posting only.|test_AC_extraction_classification_hardening_4_an_applied_row_that_the_policy_refuses_gets_the_default
classification-hardening.8|The one-click approval settles the drafts of a row that it posts.|test_AC_extraction_classification_hardening_8_the_approval_settles_the_drafts_it_decided
@$be/api/test_statement_one_click_balance_sheet.py|P0|done|property
accept-ai-suggestions.2|The one-click approval posts a base-currency row that the AI named a transfer or a card repayment as a Processing transfer leg.|test_AC_extraction_accept_ai_suggestions_2_a_gxs_shaped_statement_reaches_approved
accept-ai-suggestions.6|Posting clears the validation note "Economic review required.|test_AC_extraction_accept_ai_suggestions_6_posting_clears_only_the_economic_review_note|P1
accept-ai-suggestions.7|The one-click approval posts a row that the AI named a loan principal to the account Loans Payable.|test_AC_extraction_accept_ai_suggestions_7_a_loan_or_a_trade_posts_to_a_balance_sheet_account
@$be/extraction/test_classification_hardening.py|P1|done|property
classification-hardening.1|The classification answer maps to rows by the index that the model echoes for each item.|test_AC_extraction_classification_hardening_1_inconsistent_indexes_give_no_proposal|P0
classification-hardening.3|A row that has a live classification under a newer policy version loses its older model rows.|test_AC_extraction_classification_hardening_3_a_newer_policy_supersedes_older_model_rows
classification-hardening.5|The classification call to the model carries the id of the statement owner.|test_AC_extraction_classification_hardening_5_the_provider_call_carries_the_user
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P1|done|property
classification-hardening.6|The AI suggestions page shows the effect that the server reports for a decision, not the promise of the button.|AC-extraction.classification-hardening.6 — shows the effect that the server reports and the server refusal
fe-remainder-extraction.1|Audit Trail panel on transaction detail page lists chronological `{timestamp, actor, action, old_value, new_value}` from `GET /api/transactions/{id}/audit`.|AC18.5.6 — Audit Trail panel renders provenance|P2:-
@$be/extraction/test_auto_accept.py|P0|done|property
auto-accept.2|With the setting on, the classifier applies a suggestion at the review score or above.|test_AC_extraction_auto_accept_2_a_review_band_proposal_is_applied
auto-accept.3|With the setting on, a row that the model answered but could not place gets an applied row on the general income or expense account of its direction.|test_AC_extraction_auto_accept_3_a_row_that_the_model_cannot_place_gets_the_general_account
auto-accept.4|A row that the model did not answer gets no row and no general account.|test_AC_extraction_auto_accept_4_no_answer_writes_nothing
auto-accept.5|With the setting on, a loan principal and an investment trade at the review score or above get an applied row on Loans Payable and Investments, with an explicit intent by direction.|test_AC_extraction_auto_accept_5_a_loan_or_a_trade_is_applied_with_an_explicit_intent
auto-accept.6|With the setting on, the next pass applies the drafts that the review path left.|test_AC_extraction_auto_accept_6_existing_drafts_are_promoted|P1
auto-accept.12|The classifier asks the model only for the rows that have no classification row under the current policy version.|test_AC_extraction_auto_accept_12_a_row_that_has_its_row_is_not_asked_again|P1
@$be/api/test_statement_auto_accept.py|P0|done|property
auto-accept.7|With the setting on, one approval of a statement posts every row.|test_AC_extraction_auto_accept_7_one_approval_posts_every_row_of_the_statement
auto-accept.8|The disposition policy of a user with the setting on has the score gate 0 and its own version string, disposition-v1-accept-any-score.|test_AC_extraction_auto_accept_8_the_policy_threshold_follows_the_setting|P1
auto-accept.9|The posting itself books the balance-sheet classes for a user with the setting on.|test_AC_extraction_auto_accept_9_transfers_loans_and_trades_post_without_a_click
auto-accept.10|A high-confidence statement posts.|test_AC_extraction_auto_accept_10_a_high_confidence_statement_posts_when_it_is_parsed
@$be/api/test_classifications_router.py|P1|done|property
auto-accept.11|The classification backfill counts the candidates that got a row in the run.|test_AC_extraction_auto_accept_11_backfill_counts_the_rows_it_wrote_and_does_not_retry_them
1817.2|POST /classifications/backfill classifies the caller's not-yet-classified transactions under each transaction's own effective policy, never duplicates or rewrites an existing classification on re-run.|test_AC18_17_2_backfill_endpoint_classifies_then_is_idempotent
@$be/extraction/test_statements_shift_left.py|P0|done|property
804.1|Statement upload (CSV) end-to-end journey.|test_statement_upload_csv_direct_parsing
804.2|Statement list and get end-to-end journey.|test_statement_list_and_get_details
804.3|Statement full flow (upload -> parse -> approve) end-to-end journey.|test_statement_full_approval_and_posting_flow
@$be/review/test_statement_validation.py|P1|done|property
stage1-validation.1|Stage 1 balance validation tolerance is 0.001 USD, not the looser 0.10 USD Stage 2 reconciliation-scoring tolerance.|test_within_tolerance|P0
stage1-validation.2|Validate_balance_chain raises ValueError.|test_statement_not_found_raises
stage1-validation.3|_get_opening_balance falls back to the statement's own opening_balance.|test_opening_balance_from_statement_when_no_manual_no_prev
stage1-validation.4|_get_opening_balance uses the statement's own opening_balance for intra-statement validation.|test_opening_balance_from_prev_statement
stage1-validation.5|Reject_statement without a reason clears validation_error.|test_reject_without_reason
stage1-validation.6|Edit_and_approve is unconditionally unsupported.|test_edit_and_approve_is_unsupported
stage1-validation.7|Every service method that mutates a pending_review statement enforces user_id ownership.|test_get_statement_for_update_wrong_user_raises
stage1-validation.8|A Stage 1 pending_review -> approved transition requires the balance delta to be <= 0.001 USD.|test_approve_with_invalid_balance_raises|P0
2832.1|Validate_balance_chain validates intra-statement self-consistency independently of prior statement closing balances, returning cross_period_delta, cross_period_match, previous_closing_balance.|test_AC_extraction_2832_1_non_consecutive_statement_validates_intra_statement_and_reports_cross_period_delta
@$be/extraction/test_source_balance_check.py|P1|done|property
closing-balance-source.1|The closing-balance source check compares the stored closing balance with the numbers in the PDF text.|test_AC_extraction_closing_balance_source_1_computed_closing_is_flagged
closing-balance-source.3|The closing-balance source check reads the group separators U+2009 and U+2019.|test_AC_extraction_closing_balance_source_3_reads_more_group_separators|P2
@$be/api/test_statements_list_budget.py|P1
statement-list.1|GET /api/statements issues the same number of SQL statements for 3 statements and for 12 statements.|test_AC_extraction_statement_list_1_sql_count_does_not_grow_with_statement_count
statement-list.2|GET /api/statements and GET /api/statements/pending-review have no include_transactions parameter and return BankStatementListItemResponse items.|test_AC_extraction_statement_list_2_list_has_no_transactions_option
statement-list.3|The batched document lookup of GET /api/statements ignores a document of another user and falls back to the key.|test_AC_extraction_statement_list_3_document_lookup_keeps_user_isolation_and_hash_fallback
@$be/extraction/test_statement_classify_after_parse.py|P1
statement-classify.1|Each row of the statement has one stored answer and the model was asked once for each row.|test_AC_extraction_statement_classify_1_parse_classifies_and_approve_makes_zero_model_calls
statement-classify.2|A model error, an unexpected error or a timeout in the pass.|test_AC_extraction_statement_classify_2_a_failed_phase_leaves_the_rows_to_the_approve
statement-classify.3|An approval during the pass waits for the lock of the statement, then asks the model for no row that has an answer.|test_AC_extraction_statement_classify_3_approve_waits_for_a_running_phase_and_asks_no_second_time
statement-classify.4|The pass classifies a row under the policy in effect on the date of that row.|test_AC_extraction_statement_classify_4_each_row_gets_the_policy_of_its_own_date
statement-classify.5|Ingestion, review and approval of two CSV statements write the classifications, entries, trace graph and report values that main at d213429b2 wrote for the same fixture and the same fake model.|test_AC_extraction_statement_classify_5_state_after_parse_classify_approve_equals_main
2813.3|_propose_batch passes deterministic decode parameters for active indexed policies.|test_AC_extraction_2813_3_propose_batch_pins_deterministic_decode_and_recovers_auto_post|:property
@$be/extraction/test_statement_approve_budget.py|P1
statement-approve.2|Approving a statement of 80 rows posts 80 entries with at most 160 SQL statements.|test_AC_extraction_statement_approve_2_sql_count_of_80_rows_is_bounded
statement-approve.3|Each row above 8 adds at most half an SQL statement to the approval of a statement.|test_AC_extraction_statement_approve_3_extra_rows_cost_a_bounded_number_of_statements
@$be/extraction/test_statement_posting_batch.py|P1
statement-approve.4|Emit_disposition_trace_records_many returns the records that emit_disposition_trace_records returns for each input, with a number of SQL statements that does not grow with the inputs.|test_AC_extraction_statement_approve_4_batch_disposition_records_equal_the_single_records
statement-approve.5|Authorize_financial_commands_many returns the decision anchors that authorize_financial_command returns for each request, with a number of SQL statements that does not grow with the requests.|test_AC_extraction_statement_approve_5_batch_command_anchors_equal_the_single_anchors
statement-approve.6|Create_entries_from_txns creates the entries that create_entry_from_txn creates for the same requests, keeps its checks and its error mapping.|test_AC_extraction_statement_approve_6_batch_entries_equal_the_single_entries
@$be/api/test_statement_pipeline.py|P0|done|property
1913.1|Statement parse dispatch is config-gated.|test_AC19_13_1_dispatch_falls_back_to_asyncio_when_prefect_unset
1913.2|With PREFECT_API_URL set, submit_parse_pipeline submits a Prefect flow run with serializable params only and returns None.|test_AC19_13_2_dispatch_submits_serializable_params_to_prefect
@$be/extraction/test_statement_ingestion_use_case.py|P0|done|property
1913.4|API fallback and Prefect durable execution both invoke the same explicitly composed StatementIngestionUseCase.|test_AC_extraction_1913_4_api_and_prefect_use_same_composed_use_case
1913.5|Statement ingestion dependencies are immutable constructor fields.|test_AC_extraction_1913_5_incomplete_composition_fails_before_job
1913.6|Unexpected application or infrastructure failures raise a typed retryable ingestion error and never rewrite the statement as a source-quality rejection.|test_AC_extraction_1913_6_application_error_does_not_reject_source
1913.7|A fresh worker interpreter composes every required statement-ingestion port.|test_AC_extraction_1913_7_fresh_worker_composes_without_main
1913.8|Retrying the same statement finalization is idempotent by statement and atomic-transaction identity and cannot duplicate ledger effects.|test_AC_extraction_1913_8_retry_does_not_duplicate_financial_effects|:invariant
ingestion-trace.1|The typed extraction result, its CODE-only integrity guard.|test_AC_extraction_ingestion_trace_1_is_atomic_with_statement_facts|:invariant
ingestion-trace.2|Re-emitting the same extraction or disposition decision is content-idempotent.|test_AC_extraction_ingestion_trace_2_retries_are_idempotent_and_changes_supersede|:invariant
@$be/extraction/test_reviewed_statement_envelope.py|P0|done|invariant
reviewed-envelope.1|Absent source currency, period.|test_AC_extraction_reviewed_envelope_1_preserves_source_absence_until_typed_command
reviewed-envelope.2|A reviewed-envelope command is pinned to the exact current source-result digest and a user-owned custody account.|test_AC_extraction_reviewed_envelope_2_rejects_invalid_or_stale_commands_atomically
reviewed-envelope.3|A successful command appends an auditable review decision with the exact immutable source-result trace as parent and exposes a confirmed-envelope projection.|test_AC_extraction_reviewed_envelope_3_appends_trace_and_preserves_source_payload
reviewed-envelope.5|A reparse invalidates a prior confirmation for a different source-result digest.|test_AC_extraction_reviewed_envelope_5_reparse_and_retry_are_explicit
reviewed-envelope.7|The database rejects direct UPDATE or DELETE of persisted source-result and reviewed-envelope facts.|test_AC_extraction_reviewed_envelope_7_database_rejects_fact_mutation
@$be/extraction/test_statement_contribution.py|P0|done|invariant
statement-contribution.1|Resolve_statement_contribution publishes the exact current immutable StatementExtractionResult.|test_AC_extraction_statement_contribution_1_preserves_exact_position_source_result
statement-contribution.2|A contribution is authoritative only.|test_AC_extraction_statement_contribution_2_reviewed_envelope_pins_exact_decision
statement-contribution.3|Malformed, missing, non-authoritative, stale, cross-tenant, or target-mismatched source facts or decisions return an explicit unproven contribution and never grant trust to a package consumer.|test_AC_extraction_statement_contribution_3_fails_closed_without_current_decision
statement-contribution.4|A statement contribution publishes the exact confirmed custody account identity with its input refs.|test_AC_extraction_statement_contribution_4_publishes_confirmed_custody_account
@$be/extraction/test_disposition_policy.py|P0|done|property
disposition.1|DispositionPolicy is the only statement-to-ledger semantic boundary.|test_AC_extraction_disposition_1_never_uses_direction_as_intent
disposition.2|Transfers, investment and liability principal.|test_AC_extraction_disposition_2_principal_and_transfer_never_enter_pnl|:invariant
disposition.4|IntentProposal carries one closed proposal origin.|test_AC_extraction_disposition_4_trace_authority_follows_explicit_proposal_origin|:invariant
disposition-rollout.1|Off, observe, and enforce execute the same versioned disposition calculation.|test_AC_extraction_disposition_rollout_1_modes_share_one_decision
disposition-transfer-fact.1|A transaction that reconciliation accepted as a transfer leg is already covered by its Processing entry.|test_AC_extraction_disposition_transfer_fact_1_accepted_match_outranks_a_non_manual_proposal
disposition-transfer-fact.2|A person who adjudicates one transaction is not overridden by the accepted transfer match.|test_AC_extraction_disposition_transfer_fact_2_a_person_still_decides_for_the_transaction|P1
disposition-transfer-fact.3|A row without an accepted transfer match keeps its model proposal.|test_AC_extraction_disposition_transfer_fact_3_without_a_match_the_model_proposal_applies|P1
@$fe/__tests__/StatementUploader.test.tsx|P1
api-vectors.2|The frontend statement uploader test consumes the committed extraction conformance vector verbatim as its mock data.|AC8.4.1 requires a file and calls completion callback after successful upload
fe-remainder-extraction.4|The primary statement uploader rejects `.csv` files by extension.|AC19.15.3 statement uploader rejects csv and csv uploader rejects non-csv, each enforcing its own kind's extensions
2823.1|StatementDetailPage polls review.|AC-extraction.2823.1 uploads multiple selected files in one batch
@$fe/__tests__/statementsPage.test.tsx|P1
fe-stage1-review.1|Statements page renders loading, error, empty, and populated states.|AC16.14.10 AC22.1.8 renders the uploader and upload history (loading, error, empty, populated)|P2
fe-stage1-review.2|Statements page enables polling when parsing status is present.|AC16.14.11 AC22.11.1 enables polling with an honest parsing state (no fabricated progress)|P2
fe-stage1-review.3|Statements page delete action calls delete API and toast on confirm.|AC16.14.12 delete action calls delete API and toast|P2
fe-stage1-review.16|Upload-history parsing polls are single-flight.|AC-extraction.fe-stage1-review.16 keeps upload polling single-flight and supersedes stale work
fe-stage1-review.18|UploadPage exposes View Report action for approved statements and Review & Approve for parsed statements.|AC-extraction.fe-stage1-review.18 exposes View Report action for approved statements and Review & Approve for parsed statements|P2
fe-stage1-review.20|The Upload page shows parse progress, the workflow notices and the transfers still in flight on one page.|AC-extraction.fe-stage1-review.20 shows workflow notices and in-flight transfers on the upload page
fe-upload-layout.4|An upload row of a failed brokerage import shows "Import failed" and its reason.|AC-extraction.fe-upload-layout.4 shows a failed brokerage import as Import failed with Retry, never as parsing or ready
fe-ia-extraction.2|The statement-parsing state shows an honest indeterminate indicator with a typical-duration expectation.|AC16.14.11 AC22.11.1 enables polling with an honest parsing state (no fabricated progress)
fe-remainder-extraction.2|The Upload page exposes exactly three intake entries.|AC19.15.1 exposes exactly three intake entries: one statement uploader plus CSV and Manual
fe-remainder-extraction.3|The CSV import and Manual records entries are folded by default.|AC19.15.2 keeps secondary intake passive: CSV and Manual folded, no per-class checklist, no readiness fetch
@$fe/__tests__/statementDetailPage.test.tsx|P2
fe-stage1-review.4|Statement detail page loads statement data and renders parsed transactions summary.|AC16.18.1 loads detail data and renders transactions
fe-stage1-review.5|The statement page shows Approve and Reject only.|AC16.18.2 shows approve and reject only while the statement is parsed
fe-stage1-review.6|Statement detail page retry action posts retry API and refreshes data.|AC16.18.3 retry parse posts retry API and refreshes
fe-stage1-review.15|Statement-detail parsing polls are single-flight.|AC-extraction.fe-stage1-review.15 keeps detail polling single-flight and aborts active work on teardown|P1
fe-stage1-review.19|The statement page `/statements/[id]` is the one page for a statement.|AC-extraction.fe-stage1-review.19 shows the PDF original beside the extracted transactions on one page|P1
@apps/frontend/playwright/mobile-ux.spec.ts|P0
fe-stage1-review.10|Stage 1 statement review shows read-only transaction cards on phone widths, with approve and reject actions visible.|AC16.26.1 stage 1 mobile review exposes read-only transaction cards and completion actions
fe-stage1-review.11|Stage 1 desktop review keeps the transaction review surface readable at 1440px with the sidebar visible.|AC8.13.82/AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px
@$fe/__tests__/TransactionTable.test.tsx|P1
fe-stage1-review.21|The desktop transaction table of the statement page has no Status column.|AC-extraction.fe-stage1-review.21 shows the status under the description, not in a column, and only with a statement status
fe-stage1-review.23|The statement transaction table puts the LOW rows on top, on desktop and on mobile.|AC-extraction.fe-stage1-review.23 pins the low-confidence rows on top and keeps the other rows in statement order
fe-stage1-review.24|A statement row read from the API has no invented status.|AC-extraction.fe-stage1-review.24 shows no pending chip on an approved statement read from the API
fe-stage1-review.27|A statement row with no confidence tier has no confidence in the view model.|AC-extraction.fe-stage1-review.27 shows a row with no confidence tier as not rated, not pinned and not counted
@apps/frontend/playwright/statement-review-path.spec.ts|P1
fe-stage1-review.22|At a 1280 px viewport the description column of the statement table beside the PDF is at least 120 px wide.|AC-extraction.fe-stage1-review.22 keeps the description readable beside a PDF preview at 1280 px
fe-stage1-review.26|At 1280x800 and at 375x812 the first row of the statement table is its lowest-confidence row.|AC-extraction.fe-stage1-review.26 puts the low row first and in full on one page scroll (${label})
@apps/frontend/playwright/upload-page-layout.spec.ts|P1
fe-upload-layout.1|At a 375 px viewport `/upload` has no horizontal overflow, also with file names that are long tokens.|AC-extraction.fe-upload-layout.1 has no horizontal overflow at 375 px
fe-upload-layout.2|At 375x812 the file list of `/upload` starts within 1.5 viewports.|AC-extraction.fe-upload-layout.2 starts the file list within 1.5 viewports at 375x812
fe-upload-layout.3|At 375 px and at 1280 px a file whose brokerage import failed shows "Import failed", the reason, "Retry import" and Delete.|AC-extraction.fe-upload-layout.3 shows a failed import as Import failed with Retry and Delete (${label})
fe-upload-layout.6|At 390x844 on `/upload`, statement cards have zero overlapping badges and buttons, filenames display at least 18 characters.|AC-extraction.fe-upload-layout.6 stacks mobile upload cards and transfers without overlap or clipping at 390x844
@$be/integration/test_statement_opening_balance_auto_post.py|P1|done|property
1833.1|The extracted opening balance is posted as a guided opening-balance entry against the system Opening Balance Equity account.|test_AC_extraction_1833_1_auto_approve_posts_validated_opening_balance
1833.2|A follow-up period import for the same account posts its transactions but never a second opening-balance entry.|test_AC_extraction_1833_2_second_import_does_not_duplicate_opening_balance
1833.3|The opening-balance post is never gated on created_count.|test_AC_extraction_1833_3_zero_created_count_still_posts_opening_balance|P0
@$be/extraction/test_paged_vision_extraction.py|P1|done|property
1832.1|Vision extraction covers EVERY page of a PDF.|test_AC_extraction_1832_1_multi_batch_pdf_extracts_once_per_batch_and_merges|P0
1832.2|Paged-extraction merge is pure and deterministic.|test_AC_extraction_1832_2_merge_semantics
1832.3|Documents above the total-page ceiling fail with an explicit, page-count-naming error.|test_AC_extraction_1832_3_total_page_ceiling_is_an_explicit_error
2595.1|Vision PDF extraction bounds peak memory by rendering one page batch at a time on demand, shrinking the PyMuPDF store.|test_AC_extraction_2595_1_thirty_page_scanned_pdf_parse_bounds_peak_memory
2595.2|When a PDF document exceeds PDF_VISION_MAX_TOTAL_IMAGE_BYTES of cumulative rendered vision payloads even.|test_AC_extraction_2595_2_total_rendered_byte_ceiling_raises_explicit_error
2813.1|Small PDFs extract in a single shot.|test_AC_extraction_2813_1_staged_head_tail_meta_and_body_batches
@$be/extraction/test_signature_seams.py|P0|done|property
signature-seams.1|A single frozen ParseJob value object crosses the upload, in-process worker.|test_AC_extraction_signature_seams_1_parse_job_round_trips_prefect_params
signature-seams.2|DocumentSource resolves the document path, content, URL, content hash.|test_AC_extraction_signature_seams_2_document_source_is_the_only_parse_input
signature-seams.3|Parse_document delegates CSV and vision source extraction to separate typed paths.|test_AC_extraction_signature_seams_3_csv_and_vision_paths_are_separate
signature-seams.4|Parsed transaction rows carry dedup_hash, balance_after, occurrence_index.|test_AC_extraction_signature_seams_4_typed_rows_and_failure_contract
@$be/extraction/test_source_lifecycle.py|P0|done|property
source-lifecycle.1|Stage-1 approval validates every declared currency independently and never permits opposite differences in distinct currencies to cancel.|test_AC_extraction_source_lifecycle_1_approval_is_per_currency
source-lifecycle.2|Concurrent ingestion of one user-owned content digest converges on one canonical UploadedDocument and immutable extraction-result identity.|test_AC_extraction_source_lifecycle_2_two_sessions_share_source_identity
source-lifecycle.3|A source-identity uniqueness conflict is isolated by a savepoint.|test_AC_extraction_source_lifecycle_3_conflict_preserves_outer_session
source-lifecycle.4|Ordinary statement removal is an idempotent retire transition that preserves source results, reviewed envelopes, transactions.|test_AC_extraction_source_lifecycle_4_retire_preserves_history
source-lifecycle.5|Retirement changes durable reference state.|test_AC_extraction_source_lifecycle_5_retire_does_not_delete_storage
source-lifecycle.6|Rollback, commit failure, restart.|test_AC_extraction_source_lifecycle_6_failure_and_retry_converge
source-lifecycle.7|The audited lifecycle boundary accepts typed UUID, currency, Decimal, date.|test_AC_extraction_source_lifecycle_7_boundary_is_typed
source-lifecycle.8|Physical purge is absent from ordinary statement lifecycle commands and remains a separately governed cross-package operation.|test_AC_extraction_source_lifecycle_8_ordinary_api_has_no_purge_path
source-lifecycle.10|Counterfactual tests exercise cross-currency cancellation, independent-session conflict, failed commit, storage outage, retry.|test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked
@$be/extraction/test_csv_declared_balance_routing.py|P1|done|property
2504.1|A CSV statement export that declares both balances and does not reconcile stays parsed with its rows.|test_AC_extraction_2504_1_an_unreconciled_declared_csv_stays_reviewable
2822.1|Bank CSV profiles resolve optional row-level Currency and Balance columns.|test_AC_extraction_2822_1_csv_with_currency_and_balance_columns_reaches_authoritative_confidence
@$fe/__tests__/sourceEnvelopeCreateAccount.test.tsx|P1
2477.1|When a user has no active asset custody accounts on the statement review page, the source-envelope confirmation card offers an inline create-account action that creates an asset account in the statement currency and selects it.|AC-extraction.2477.1 offers to create an asset account when the user has none
2832.3|SourceEnvelopeConfirmation filters custody accounts by envelopeDraft.currency and offers inline account creation whenever no existing asset account matches the statement currency.|AC-extraction.2832.3 filters custody accounts by currency and offers inline creation when no account matches the statement currency
@$be/portfolio/test_brokerage_position_parsing.py|P1|done|property
2672.1|The fixture-fitted brokerage PDF text fallback is deleted.|test_AC_extraction_2672_1_moomoo_margin_history_nets_sell_rows_and_drops_disposed_positions
2661.1|Parse_brokerage_positions_csv_rows and parse_brokerage_csv_payload resolve optional row-level date columns and populate position snapshot_date and statement period_end/period_start.|test_AC_extraction_2661_1_positions_csv_with_date_column_imports_without_422
@-|P0|done|property
transaction-identity.6|A changed re-parse of a statement raises the review error.|$be/extraction/test_reparse_guard_legs.py::test_AC_extraction_transaction_identity_6_a_changed_reparse_after_a_leg_needs_review|:-
default-account.1|The classifier and the one-click approval resolve a default account with one resolver, get_or_create_account.|$be/extraction/test_default_account_resolution.py::test_AC_extraction_default_account_1_an_inactive_default_account_is_not_the_default|P1
source-vocabulary.2|Persistence adapters and the published extraction interface use the same domain enum objects.|$be/extraction/test_source_vocabulary.py::test_source_enum_persistence_compatibility
1.1|Parse DBS PDF.|$be/extraction/test_extraction_invariants.py::test_balance_chain_invariant_holds_for_consistent_statements|:invariant
5.5|Statement Parsing Supervisor.|$be/extraction/test_statement_parsing_supervisor.py::test_reset_stale_parsing_jobs_marks_rejected|P1
9.1|Parsing cases that fail audit are recorded in an SSOT registry.|$t/test_extraction_failed_case_registry.py::test_AC3_9_1_extraction_failed_case_registry_preserves_audit_cases_without_parser_expansion
10.1|Statement parsing owns fact-forward settlement evidence capture and must preserve source metadata needed by framework readiness.|$t/test_framework_reporting_epic_contract.py::test_AC3_10_1_statement_parsing_is_source_capture_not_framework_policy
110.3|Stage-1 approval preserves AUTO_PARSED provenance and never manufactures USER_CONFIRMED trust.|$be/extraction/test_source_type_promotion.py::test_stage1_approve_preserves_auto_parsed_provenance
110.4|Manual entry wins over auto_parsed in conflict.|$be/infra/test_migrations.py::test_AC13_10_4_source_type_migration_handles_missing_legacy_enum_label
121.1|`route_by_threshold` routes a balance-invalid bank statement to `PARSED`, never `uploaded`, regardless of score.|$be/accounting/test_validation.py::test_AC13_21_1_balance_invalid_routes_to_parsed_review
116.1|A provided seed is forwarded in the streaming request payload.|$be/ai/test_ai_streaming.py::test_stream_ai_json_forwards_zai_knobs_and_seed|P1
123.1|User deletion is refused with HTTP 409.|$be/api/test_users_router.py::test_AC13_23_1_delete_user_with_in_flight_parse_returns_409
407.2|Get_few_shot_examples respects default limit and caches results.|$be/extraction/test_correction_service_cache.py::test_get_few_shot_examples_cache_hit_and_limit|P1:-
813.10|Multi-brokerage PDF upload → position import → latest portfolio value, with value consistency asserted.|$e2e/test_brokerage_upload_to_portfolio_value.py::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value
813.11|A DBS bank statement PDF's full browser journey.|$e2e/test_statement_full_journey.py::test_dbs_statement_full_journey
2502.1|`approve_statement_workflow` / `reject_statement_workflow` own the ordered transition -> side-effect -> commit sequence as one unit.|$be/api/test_statement_workflow_service.py::test_statement_workflow_service|P1
1807.2|The Alembic migration creates evidence_nodes and evidence_edges with user-scoped entity lookup and edge traversal indexes.|$be/infra/test_evidence_lineage_migration_contract.py::test_AC18_7_2_evidence_lineage_migration_creates_tables_and_indexes|P1:-
1802.5|Top_corrections is typed as a TopCorrection Pydantic model in the corrections stats response, not a bare dict.|$be/api/test_corrections_router.py::test_AC18_2_5_top_corrections_is_typed_pydantic_model|P1:-
non-pnl-categories.5|With auto_accept_ai_suggestions off.|$be/integration/test_non_pnl_classification_posting.py::test_AC_extraction_non_pnl_categories_5_unmatched_transfer_waits_for_review
classification-hardening.2|POST /ai/feedback changes the draft classification or pending reconciliation match of the current user and names the effect.|$be/api/test_ai_feedback_effects.py::test_AC_extraction_classification_hardening_2_reject_supersedes_the_draft
classification-hardening.7|A decision of the user outlives a later model pass.|$be/extraction/test_classification_user_decisions.py::test_AC_extraction_classification_hardening_7_a_corrected_draft_survives_a_newer_policy
auto-accept.1|The setting auto_accept_ai_suggestions has the code default true.|$be/api/test_user_settings_router.py::test_AC_extraction_auto_accept_1_the_code_default_is_on_and_a_user_can_turn_it_off
auto-accept.13|On a pinned staging deployment, one isolated user keeps the product defaults and uploads the committed GXS statement.|$e2e/test_zero_click_statement_journey.py::test_upload_alone_produces_the_base_tables_and_the_three_statements
stage1-validation.10|Stage 1 approval tolerance and extraction/reconciliation scoring tolerance remain separate, intentionally documented policies.|$be/review/test_tolerance_policy.py::test_ac16_22_7_tolerance_policy_constants_are_intentional
stage1-routing.1|On a pinned staging deployment, one isolated user uploads two generated PDF statements.|$e2e/test_stage1_routing_journey.py::test_stage1_accepts_clean_source_and_reviews_broken_source|:-
closing-balance-source.2|Parse_document sends a PDF bank statement to review.|$be/extraction/test_closing_balance_source_wiring.py::test_AC_extraction_closing_balance_source_2_computed_closing_goes_to_review|P1
statement-classify.6|The pass counts each outcome in the counter finance.statement_classification.outcome.|$be/infra/test_telemetry_metrics.py::test_AC_extraction_statement_classify_6_classification_outcome_counter_labels_each_outcome|P1:-
statement-approve.1|Approving two statements writes the journal entries, lines, decision anchors, trace graph, evidence graph and report values that main at bba3aa84 wrote for the same fixture.|$be/extraction/test_statement_approve_equivalence.py::test_AC_extraction_statement_approve_1_state_equals_the_pre_change_golden|P1:-
1804.1|AI CSV parsing handles an unknown institution as a fallback column-mapping path.|$be/extraction/test_ai_csv_parsing.py::test_ai_csv_parsing_returns_valid_mapping|P1
1913.3|The durable-parse deployment the worker registers resolves to exactly the name PARSE_DEPLOYMENT that the API submits runs to.|$be/tooling/test_prefect_deployment_registration.py::test_AC_extraction_1913_3_registration_script_targets_the_deployment_api_submits_to|P1
1913.10|A staging deploy pins the durable statement canary's checkout to its emitted commit SHA and its live-health assertion to the release tag that the deploy receiver has verified resolves to that SHA.|$t/test_post_merge_e2e_gates.py::test_AC_extraction_1913_10_staging_statement_canary_is_sha_pinned_and_blocking
disposition.3|A reviewed recorded-description rule traverses.|$be/integration/test_statement_disposition_semantic_oracle.py::test_AC_extraction_disposition_3_reviewed_description_oracle_reaches_exact_report_lines|:invariant
disposition-transfer-fact.4|Statement posting creates no second entry for an accepted transfer leg.|$be/integration/test_transfer_leg_classification_conflict.py::test_AC_extraction_disposition_transfer_fact_4_applied_model_category_does_not_repost_a_matched_leg
api-vectors.1|The serialized statement upload/status responses recomputed from fixed deterministic inputs equal the committed common/extraction/conformance/vectors.json.|$be/schemas/test_api_response_vectors.py::test_AC_extraction_api_vectors_1_statement_upload_matches_committed_vector|P1:-
fe-stage1-review.12|Frontend tests mount each new component and assert primary affordance renders.|$fe/__tests__/epic016Components.test.tsx::mounts PdfPreviewPane and asserts primary affordance (AC16.23.6)|P2:-
fe-upload-layout.5|After a successful brokerage import.|$fe/__tests__/statementDetailPage.coverage.test.tsx::AC-extraction.fe-upload-layout.5 marks the portfolio reads stale after a successful import on the statement page|P1:-
2648.1|A brokerage import that fails keeps the statement `parsed`, keeps `validation_error`.|$be/api/test_brokerage_import_failure_state.py::test_AC_extraction_2648_1_failed_import_is_recorded_beside_the_note_and_a_success_clears_it|P1:invariant
fe-ia-extraction.1|The page shows a visible plain-language reason and an in-place action.|$fe/__tests__/reviewActionBar.test.tsx::AC22.5.2 enables Approve and shows no blocker when nothing is wrong|P1:-
fe-ia-extraction.3|The statement detail page is composed from extracted sub-components with unchanged behavior.|$fe/__tests__/statementDetailParts.test.tsx::AC22.17.3 renders title, status badge, description and confidence|P1:-
1832.4|The physical bank account auto-created for a statement is deleted if that same parse call created it and the extraction is then quarantined by the LLM-LED invariant gate.|$be/integration/test_statement_reject_cleans_up_orphan_account.py::test_AC_extraction_1832_4_rejected_parse_deletes_the_account_it_just_created|P1
source-lifecycle.9|Governance detail derives detector, proof-strength, exact target SHA, issue, progress.|$be/extraction/test_source_lifecycle_governance.py::test_AC_extraction_source_lifecycle_9_governance_detail_is_exact
2832.2|Reconcile_account_statement_chain anchors the earliest approved statement S_0 to 3199 Opening Balance Equity, posts or voids 3198 Unexplained Statement Gap Equity entries for adjacent statement pairs with /delta/ > 0.10.|$be/extraction/test_statement_opening_guards.py::test_AC_extraction_2832_2_reconcile_statement_chain_anchors_out_of_order_and_gap_plugs|:invariant
2888.1|Reject or retire of a statement voids the entries of a row only.|$be/extraction/test_statement_release_ownership.py::test_AC_extraction_2888_1_reject_of_duplicate_keeps_entries_of_the_approved_original
2888.2|Retire_statement releases the ledger entries and the reconciliation matches of the rows that a statement alone owns, also.|$be/reconciliation/test_statement_release.py::test_AC_extraction_2888_2_retire_of_parsed_statement_releases_its_transfer_leg
2723.1|Persist_statement_extraction_result re-applies the active ReviewedStatementEnvelope projection.|$be/extraction/test_source_envelope_confirmation.py::test_AC_extraction_2723_1_same_digest_retry_and_reconfirm_preserve_reviewed_envelope_projection|P1:invariant
2899.1|Each CTE of effective_statement_transaction_filter keeps alive the object whose address forms its anonymous name.|$be/extraction/test_transaction_membership.py::test_AC_extraction_2899_1_filter_ctes_keep_their_name_owner_alive
2970.1|Statement approval returns before the planner statistics refresh ends. A background task coalesces requests, bounds the run with two timeouts, and logs a failure.|$be/api/test_statement_workflow_service.py::test_AC_extraction_2970_1_approve_returns_while_the_refresh_is_pending|P1
""",
    ),
    concepts=concepts(
        """
source_capability_registry|apps/backend/src/extraction/base/source_capability.py|Canonical semantic registry for product source classes, their support status, accepted evidence, produced facts, review semantics, and traceability target.|common/extraction/readme.md#sourcecapability-registry,vision.md,common/testing/source_capability_proof.py|apps/backend/tests/extraction/test_statement_result_contract.py,tests/tooling/test_source_capability_proof.py|source|registry
confidence_tier_rollup|common/extraction/confirmation-workflow.md#confidence-tier-rollup|Confidence-tier rollup that makes extraction confidence load-bearing for promotion.|common/extraction/readme.md#confidence-scoring|-|extraction|concept
confirmation_workflow|common/extraction/confirmation-workflow.md|Cross-cutting pending_review state machine (Stage 1 & 2).|common/reconciliation/reconciliation.md,common/ledger/readme.md|-|extraction|concept
confirmation_workflow_states|common/extraction/confirmation-workflow.md#state-machine|Stage 1 & Stage 2 confirmation state transitions (the cross-cutting state machine).|common/reconciliation/readme.md#state-machine|-|reconciliation|concept
evidence_lineage|common/extraction/evidence-lineage.md|Generic Evidence Graph for source-to-ledger-to-report audit lineage.|docs/project/EPIC-018.ai-driven-pipeline.md,common/workflow/workflow-events.md,common/reporting/reporting.md,apps/backend/tests/extraction/test_evidence_graph_materialization.py|-|evidence|concept
extraction_confidence_tiers|common/extraction/readme.md#confidence-scoring|Extraction confidence score weighting and ≥85 / 60-84 / <60 routing tiers.|common/reconciliation/readme.md#thresholds,common/extraction/confirmation-workflow.md#confidence-tier-rollup|-|extraction|concept
extraction_failed_case_registry|common/extraction/audit-failed-cases.yaml|Sanitized registry for parsing cases that fail audit without expanding deterministic parser scope.|common/extraction/readme.md,docs/project/EPIC-003.statement-parsing.md|tests/tooling/test_extraction_failed_case_registry.py|extraction|registry
extraction_pipeline|common/extraction/readme.md|Gemini Vision document parsing and validation pipeline.|common/reconciliation/reconciliation.md,apps/backend/tests/extraction/test_dual_write_layer2.py|-|extraction|concept
"""
    ),
    governance=[
        GovernanceInitiative(
            id="source-lifecycle-convergence",
            title="Source-fact lifecycle and failure convergence",
            issue="https://github.com/wangzitian0/finance_report/issues/1995",
            depends_on=["meta/governance-control-plane"],
            guarantees=[
                GovernanceGuarantee(
                    id="per-currency-approval",
                    statement="Approval proves each declared currency without scalar cancellation.",
                    affected_acs=["AC-extraction.source-lifecycle.1"],
                    detector="cross-currency-stage1-validation-paths",
                    target="0 cross-currency scalar approval paths",
                    lock="ci.backend",
                    proof="source-lifecycle-per-currency-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="one-source-identity",
                    statement="Concurrent ingestion converges on one canonical source identity.",
                    affected_acs=["AC-extraction.source-lifecycle.2"],
                    detector="duplicate-canonical-source-identities",
                    target="0 duplicate source identities",
                    lock="ci.backend",
                    proof="source-lifecycle-two-session-identity",
                    required_proof_strength="concurrency",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="session-recovery",
                    statement="Dedup conflicts preserve the outer database session.",
                    affected_acs=["AC-extraction.source-lifecycle.3"],
                    detector="unprotected-source-dedup-conflicts",
                    target="0 unprotected conflict sites",
                    lock="ci.backend",
                    proof="source-lifecycle-savepoint-recovery",
                    required_proof_strength="concurrency",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="append-only-retirement",
                    statement="Ordinary removal retires and preserves source history.",
                    affected_acs=["AC-extraction.source-lifecycle.4"],
                    detector="destructive-statement-lifecycle-paths",
                    target="0 destructive ordinary lifecycle paths",
                    lock="ci.backend",
                    proof="source-lifecycle-history-preservation",
                    required_proof_strength="schema",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="storage-db-consistency",
                    statement="Retirement cannot split object state from database source truth.",
                    affected_acs=["AC-extraction.source-lifecycle.5"],
                    detector="storage-database-split-lifecycle-paths",
                    target="0 split lifecycle paths",
                    lock="ci.backend",
                    proof="source-lifecycle-storage-failure",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="failure-convergence",
                    statement="Failure and retry preserve canonical lifecycle cardinality.",
                    affected_acs=["AC-extraction.source-lifecycle.6"],
                    detector="non-idempotent-source-lifecycle-retries",
                    target="0 retry cardinality drift",
                    lock="ci.backend",
                    proof="source-lifecycle-failure-retry",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="typed-command-boundary",
                    statement="Financial lifecycle inputs cross typed extraction boundaries.",
                    affected_acs=["AC-extraction.source-lifecycle.7"],
                    detector="untyped-source-lifecycle-boundaries",
                    target="0 untyped audited boundaries",
                    lock="ci.backend",
                    proof="source-lifecycle-signature-contract",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="purge-boundary",
                    statement="Ordinary extraction commands cannot physically purge source facts.",
                    affected_acs=["AC-extraction.source-lifecycle.8"],
                    detector="ordinary-api-physical-purge-paths",
                    target="0 ordinary purge paths",
                    lock="ci.backend",
                    proof="source-lifecycle-purge-boundary",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="exact-governance-detail",
                    statement="Control-plane detail exposes exact current proof and enforcement facts.",
                    affected_acs=["AC-extraction.source-lifecycle.9"],
                    detector="source-lifecycle-governance-join-gaps",
                    target="0 missing detail facts",
                    lock="ci.backend",
                    proof="source-lifecycle-governance-detail",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="counterfactual-lock",
                    statement="The adversarial lifecycle matrix remains executable and blocking.",
                    affected_acs=["AC-extraction.source-lifecycle.10"],
                    detector="missing-source-lifecycle-counterfactuals",
                    target="0 missing counterfactuals",
                    lock="ci.backend",
                    proof="source-lifecycle-counterfactual-matrix",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
            ],
        )
    ],
)
