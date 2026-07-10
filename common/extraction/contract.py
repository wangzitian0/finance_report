"""The ``extraction`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__init__.__all__``
(``implementations["be"]`` = ``apps/backend/src/extraction``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways edge.

## What this package is

The statement-parsing bounded context (EPIC-003/EPIC-013 → #1421): documents
in (PDF/image/CSV), verified financial facts out. It owns the **source→fact**
half of the money pipeline — parsing (vision-LLM + per-institution CSV),
per-currency balance closure and balance-chain continuity, dedup by content
hash, brokerage detection/positions, and the evidence lineage that links every
extracted fact to its source document.

## Ownership boundaries

* **AtomicTransaction is extraction's aggregate**: downstream domains
  (reconciliation / reporting) reference its rows **by id** (Decision B) —
  the Stage-4 parallelism anchor.
* The ORM entities (``UploadedDocument`` / ``AtomicTransaction`` /
  ``AtomicPosition``) stay in the unregistered ``src/models/`` until their
  cross-domain FKs are cut (Stage-4 scope; ledger/llm precedent).
* ``confidence_metric`` / ``confidence_tier`` (journal-confidence metric
  snapshots) are NOT this package's — they read ledger's aggregates and stay
  in ``services/`` pending the reporting/observability re-home.
* The OCR layout-parsing call routes through ``src.llm``'s ``ocr_layout_call``
  chokepoint (#1670), which is why ``llm`` is now a declared dependency. The
  JSON/vision call sites already went through ``llm`` via
  ``services.ai_streaming``. Threading per-user provider binding (``user_id``)
  into these OCR/vision/json call sites — so a BYO-provider user's own model
  is used, not just the deployment default — is a separate, still-pending
  follow-up (AC-llm.4.5), independent of the ``llm`` dependency edge itself.
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
    name="extraction",
    status="active",
    # LLM-LED: the pipeline's correctness is proven by property tests over the
    # deterministic calculus plus cassette-replay/eval evidence for the
    # vision-LLM path (the authority classifier bands cassette-driven tests as
    # LLM). Non-eval ACs carry proof_kind=property.
    tier="LLM-LED",
    depends_on=["audit", "identity", "ledger", "llm", "observability", "platform", "portfolio", "runtime"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: the pure validation/confidence calculus lives in
        # base/validation.py; its functions are published via the interface.
        # (Not declared as units: KIND_LAYER has no pure-function kind homed in
        # base — the base-layer-pure invariant is the guard instead.)
        # ── aggregates/entities: taxonomy-only (ORM in unregistered models/,
        # FK surgery is Stage-4; see docstring) ──
        Unit(name="StatementSummary", kind=Kind.AGGREGATE_ROOT),
        Unit(name="UploadedDocument", kind=Kind.ENTITY),
        Unit(name="AtomicTransaction", kind=Kind.ENTITY),
        Unit(name="AtomicPosition", kind=Kind.ENTITY),
        # ── extension: the parsing pipeline + adapters ──
        Unit(
            name="ExtractionService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/service.py",
        ),
        Unit(
            name="DeduplicationService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/deduplication.py",
        ),
        Unit(
            name="BrokeragePositionImportService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/brokerage_positions.py",
        ),
        Unit(
            name="EvidenceGraphIntegrationService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/evidence_graph_integration.py",
        ),
        # dual-write persistence verbs (upsert by dedup_hash). Declared as the
        # repository IMPL half only via taxonomy for now: carving the base
        # port out of the raw-AsyncSession verbs is the documented follow-up
        # (todo.md); until then the unit is taxonomy-only.
        Unit(name="AtomicTransactionRepository", kind=Kind.REPOSITORY),
        # ── data: evidence lineage read-models ──
        # Taxonomy-only: the lineage read/write paths are still entangled
        # (integration instantiates the lineage reader; materialization uses an
        # integration helper), so the physical files sit in extension/ and the
        # clean data/ split is documented package-internal follow-up (todo.md).
        Unit(name="EvidenceLineageService", kind=Kind.PROJECTION),
        Unit(name="EvidenceGraphMaterializationService", kind=Kind.PROJECTION),
        # ── reserved: the balance-chain violation as a domain event (today it
        # is only metrics-logged; publishing via the platform outbox is the
        # planned upgrade — package-internal, not a re-cutover) ──
        Unit(name="BalanceChainViolated", kind=Kind.DOMAIN_EVENT),
    ],
    implementations={"be": "apps/backend/src/extraction", "fe": None},
    interface=[
        "BrokeragePositionImportService",
        "CorrectionLoopService",
        "CurrencyUnresolvedError",
        "DEFAULT_MAX_DEPTH",
        "DeduplicationService",
        "EvidenceGraphIntegrationService",
        "EvidenceGraphMaterializationService",
        "EvidenceLineageService",
        "EvidenceTraversalStep",
        "ExtractionError",
        "ExtractionService",
        "SYSTEM_PROMPT",
        "_brokerage_import_not_ready_reason",
        "_brokerage_payload_from_persisted_extraction",
        "_brokerage_payload_from_statement",
        "approve_statement_workflow",
        "auto_create_posted_entries_for_statement",
        "backfill_classifications",
        "build_csv_mapping_prompt",
        "compute_confidence_score",
        "create_entry_from_txn",
        "detect_balance_chain_break",
        "dual_write_layer2",
        "edit_and_approve",
        "get_correction_stats",
        "get_parsing_prompt",
        "looks_like_brokerage_document",
        "looks_like_brokerage_payload",
        "parse_brokerage_csv_payload",
        "parse_brokerage_positions",
        "pending_stage1_review_filter",
        "record_correction",
        "reject_statement_workflow",
        "resolve_custody_account_id",
        "resolve_ingest_currency",
        "resolve_statement_conflicts",
        "resolve_statement_posting_account",
        "resolve_statement_transactions",
        "resolve_transaction_currency",
        "run_parsing_supervisor",
        "set_opening_balance",
        "submit_parse_pipeline",
        "validate_balance",
        "validate_balance_chain",
        "validation",
    ],
    events=[],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_extraction_package.py"
                "::test_AC_extraction_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement=(
                "The package converges into base/ (pure validation calculus) + "
                "extension/ (parsing pipeline) + data/ (evidence read-models); "
                "the old services/extraction + flat service-module homes are gone."
            ),
            test=(
                "tests/tooling/test_extraction_package.py"
                "::test_AC_extraction_1_2_converges_by_layer"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement=(
                "base/ never imports the package's own extension/ or data/, the "
                "ORM, or any network client."
            ),
            test=(
                "tests/tooling/test_extraction_package.py"
                "::test_AC_extraction_1_3_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates extraction with no violations.",
            test=(
                "tests/tooling/test_extraction_package.py"
                "::test_AC_extraction_1_4_package_contract_gate_passes"
            ),
        ),
    ],
    # The EPIC-003 + EPIC-013 ACs, migrated per Decision A. Three EPIC-003
    # rows stay behind in the EPIC (AC3.3.2 / AC3.5.10 / AC3.6.4): they are
    # human-authority rows ({tier:HU}{proof:evidence}), and the tier->proof
    # matrix forbids evidence proofs under this LLM-LED package — a different
    # authority tier is a different owner, same as frontend rows in ledger's
    # cutover. (standard-preserving
    # move; the EPIC table rows were deleted in the same commit). Numeric
    # AC-<pkg>.<group>.<seq> grammar with reserved group blocks (the ledger
    # precedent): **1–12 = EPIC-003** (leading epic number dropped) and
    # **101–123 = EPIC-013** (group + 100, so the two EPICs' group numbers
    # cannot collide). Original ids are kept as trailing comments. A one-off
    # migration from a third EPIC (e.g. EPIC-001's AC1.6.2) uses a word-slug
    # group instead of claiming a new numeric block, so it can never collide
    # with EPIC-003's/EPIC-013's reserved ranges.
    roadmap=[
        ACRecord(
            id="AC-extraction.1.1",
            statement="Parse DBS PDF",  # was AC3.1.1
            test="apps/backend/tests/extraction/test_extraction_invariants.py::test_balance_chain_invariant_holds_for_consistent_statements",
            priority="P0",
            status="done",
            proof_kind="invariant",
        ),
        ACRecord(
            id="AC-extraction.1.2",
            statement="Parse CSV (DBS)",  # was AC3.1.2
            test="apps/backend/tests/extraction/test_csv_parsing.py::test_parse_dbs_csv",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1.3",
            statement="Parse CSV (Wise)",  # was AC3.1.3
            test="apps/backend/tests/extraction/test_csv_parsing.py::test_parse_wise_csv",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1.4",
            statement="Parse CSV (Generic)",  # was AC3.1.4
            test="apps/backend/tests/extraction/test_csv_parsing.py::test_parse_generic_csv_with_amount_column",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1.5",
            statement="Parse CSV with BOM",  # was AC3.1.5
            test="apps/backend/tests/extraction/test_csv_parsing.py::test_parse_csv_with_bom",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.2.1",
            statement="Balance Validation (Pass)",  # was AC3.2.1
            test="apps/backend/tests/extraction/test_extraction.py::test_balance_valid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.2.2",
            statement="Balance Validation (Fail)",  # was AC3.2.2
            test="apps/backend/tests/extraction/test_extraction.py::test_balance_invalid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.2.3",
            statement="Completeness Validation",  # was AC3.2.3
            test="apps/backend/tests/extraction/test_pdf_parsing.py::test_missing_required_fields_detected",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.2.4",
            statement="Bank statement balance mismatches preserve validation_error details",  # was AC3.2.4
            test="apps/backend/tests/extraction/test_pdf_parsing.py::test_parse_document_bank_balance_mismatch_records_validation_error",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.2.5",
            statement="CSV transaction exports without statement balances remain reviewable",  # was AC3.2.5
            test="apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_csv_without_statement_balances_remains_reviewable",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.3.1",
            statement="High Confidence (Auto-Accept)",  # was AC3.3.1
            test="apps/backend/tests/api/test_statements_router.py::test_auto_approve_high_confidence_statement_creates_posted_entries",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.3.3",
            statement="Low Confidence (Manual)",  # was AC3.3.3
            test="apps/backend/tests/extraction/test_extraction.py::test_low_confidence_empty_transactions",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.4.1",
            statement="Invalid Parse Not Persisted",  # was AC3.4.1
            test="apps/backend/tests/extraction/test_pdf_parsing.py::test_extraction_error_not_persisted",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.4.2",
            statement="Unsupported File Type",  # was AC3.4.2
            test="apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_unsupported_type",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.4.3",
            statement="Extraction Timeout",  # was AC3.4.3
            test="apps/backend/tests/extraction/test_pdf_parsing.py::test_extraction_timeout_raises_error",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.1",
            statement="Full Upload Flow",  # was AC3.5.1
            test="tests/e2e/test_statement_upload_e2e.py::test_statement_upload_full_flow",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.2",
            statement="File Size Limit",  # was AC3.5.2
            test="apps/backend/tests/extraction/test_pdf_parsing.py::test_upload_file_exceeds_10mb_limit",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.3",
            statement="Model Selection Flow",  # was AC3.5.3
            test="apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_csv_success",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.4",
            statement="Extraction Flow Tests",  # was AC3.5.4
            test="apps/backend/tests/extraction/test_extraction_flow.py::test_parsed_statement_sets_stage1_pending_review",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.5",
            statement="Statement Parsing Supervisor",  # was AC3.5.5
            test="apps/backend/tests/extraction/test_statement_parsing_supervisor.py::test_reset_stale_parsing_jobs_marks_rejected",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.6",
            statement="Invalid file extension should return 400.",  # was AC3.5.6
            test="apps/backend/tests/api/test_statements_router.py::test_upload_invalid_extension",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.7",
            statement="PDF/image uploads may omit model and use the default OCR pipeline.",  # was AC3.5.7
            test="apps/backend/tests/api/test_statements_router.py::test_upload_uses_default_ocr_pipeline_for_pdf",
            priority="P1",
            status="done",
            proof_kind="invariant",
        ),
        ACRecord(
            id="AC-extraction.5.8",
            statement="Upload rejects models without image modalities.",  # was AC3.5.8
            test="apps/backend/tests/api/test_statements_router.py::test_upload_rejects_text_only_model",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.9",
            statement="Upload then list statements and transactions.",  # was AC3.5.9
            test="apps/backend/tests/api/test_statements_router.py::test_list_and_transactions_flow",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.11",
            statement="Missing statement returns 404.",  # was AC3.5.11
            test="apps/backend/tests/api/test_statements_router.py::test_get_statement_not_found",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.12",
            statement="File exceeding 10MB limit returns 413.",  # was AC3.5.12
            test="apps/backend/tests/api/test_statements_router.py::test_upload_file_too_large",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.13",
            statement="Extraction failure marks statement as rejected.",  # was AC3.5.13
            test="apps/backend/tests/api/test_statements_router.py::test_upload_extraction_failure",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.14",
            statement="Retry on missing statement returns 404.",  # was AC3.5.14
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_not_found",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.15",
            statement="Retry rejects models without image modalities.",  # was AC3.5.15
            test="apps/backend/tests/api/test_statements_router.py::test_retry_rejects_text_only_model",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.16",
            statement="Retry returns 503 if storage fetch fails.",  # was AC3.5.16
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_storage_failure",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.17",
            statement="Retry on statement not in parsed/rejected status returns 400.",  # was AC3.5.17
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_invalid_status",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.18",
            statement="Verify that retrying a statement in PARSING status is allowed.",  # was AC3.5.18
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_parsing_allowed",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.19",
            statement="Retry parsing with stronger model succeeds.",  # was AC3.5.19
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_success",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.20",
            statement="Retry extraction failure returns 422.",  # was AC3.5.20
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_extraction_failure",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.21",
            statement="Upload rejects models not in the OpenRouter catalog.",  # was AC3.5.21
            test="apps/backend/tests/api/test_statements_router.py::test_upload_statement_rejects_invalid_model",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.22",
            statement="Upload rejects a model lacking image/PDF modality (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_",  # was AC3.5.22
            test="apps/backend/tests/api/test_statements_router.py::test_upload_statement_rejects_model_without_image_modality",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.23",
            statement="Retry rejects a model not in the catalogue (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_",  # was AC3.5.23
            test="apps/backend/tests/api/test_statements_router.py::test_retry_statement_rejects_invalid_model",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.24",
            statement="Background parse error should be caught and logged.",  # was AC3.5.24
            test="apps/backend/tests/api/test_statements_router.py::test_background_parse_error_logging",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.5.25",
            statement="Background retry error should be caught and logged.",  # was AC3.5.25
            test="apps/backend/tests/api/test_statements_router.py::test_background_retry_error_logging",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.6.1",
            statement="Unique Prior Mapping",  # was AC3.6.1
            test="apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.6.2",
            statement="No Silent Fallback Posting",  # was AC3.6.2
            test="apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_auto_post_requires_account_mapping",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.6.3",
            statement="Ambiguous Mapping Blocked",  # was AC3.6.3
            test="apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_ambiguous_account_mapping",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.6.5",
            statement="Prior Mapping Requires Confirmed Statement",  # was AC3.6.5
            test="apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.6.6",
            statement="Source Period Unique Before Posting",  # was AC3.6.6
            test="apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.7.1",
            statement="Latest Confirmed Source",  # was AC3.7.1
            test="apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_reports_latest_confirmed_balance_and_stale_status",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.7.2",
            statement="Adjacent Opening Continuity",  # was AC3.7.2
            test="apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_detects_adjacent_opening_balance_mismatch",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.7.3",
            statement="Missing/Overlapping/Duplicate Periods",  # was AC3.7.3
            test="apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_reports_missing_overlapping_and_duplicate_ranges",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.7.4",
            statement="Broker Daily Snapshot Override",  # was AC3.7.4
            test="apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_accepts_broker_monthly_cadence_with_daily_snapshot_override",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.1",
            statement="Delete old orphaned storage objects",  # was AC3.8.1
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_deletes_orphaned_object",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.2",
            statement="Preserve objects with DB records",  # was AC3.8.2
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_skips_known_db_objects",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.3",
            statement="Skip recent in-flight uploads",  # was AC3.8.3
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_skips_recent_objects",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.4",
            statement="No-op without configured S3 bucket",  # was AC3.8.4
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_skips_when_no_bucket_configured",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.5",
            statement="Return zero for empty statement prefix",  # was AC3.8.5
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_returns_zero_when_no_objects",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.6",
            statement="Handle storage listing errors",  # was AC3.8.6
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_handles_storage_list_error",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.7",
            statement="Handle object delete errors",  # was AC3.8.7
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_handles_delete_error",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.8",
            statement="Paginate storage keys and normalize timestamps",  # was AC3.8.8
            test="apps/backend/tests/services/test_storage_sweep.py::test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.9",
            statement="Convert storage client listing errors",  # was AC3.8.9
            test="apps/backend/tests/services/test_storage_sweep.py::test_list_storage_keys_raises_on_client_error",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.10",
            statement="Exit runner on stop event",  # was AC3.8.10
            test="apps/backend/tests/services/test_storage_sweep.py::test_run_storage_sweep_exits_on_stop_event",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.11",
            statement="Log runner deletion counts",  # was AC3.8.11
            test="apps/backend/tests/services/test_storage_sweep.py::test_run_storage_sweep_logs_when_objects_deleted",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.12",
            statement="Continue runner after unexpected sweep exception",  # was AC3.8.12
            test="apps/backend/tests/services/test_storage_sweep.py::test_run_storage_sweep_handles_exception",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.13",
            statement="Disable runner by feature flag",  # was AC3.8.13
            test="apps/backend/tests/services/test_storage_sweep.py::test_run_storage_sweep_disabled_by_feature_flag",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.14",
            statement="Grace period + interval config defaults match issue #356 (24h / daily)",  # was AC3.8.14
            test="apps/backend/tests/services/test_storage_sweep.py::test_grace_period_and_interval_defaults_match_issue_356",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.15",
            statement="Sweep grace-period cutoff is config-driven, not a hardcoded constant",  # was AC3.8.15
            test="apps/backend/tests/services/test_storage_sweep.py::test_sweep_reads_grace_period_from_config",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.8.16",
            statement="Sweep runner wait interval is read from config",  # was AC3.8.16
            test="apps/backend/tests/services/test_storage_sweep.py::test_run_storage_sweep_reads_interval_from_config",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.9.1",
            statement="Parsing cases that fail audit are recorded in an SSOT registry without expanding deterministic parser scope or committing real documents",  # was AC3.9.1
            test="tests/tooling/test_extraction_failed_case_registry.py::test_AC3_9_1_extraction_failed_case_registry_preserves_audit_cases_without_parser_expansion",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.10.1",
            statement="Statement parsing owns fact-forward settlement evidence capture and must preserve source metadata needed by framework readiness while leaving US/HK policy decisions to EPIC-020",  # was AC3.10.1
            test="tests/tooling/test_framework_reporting_epic_contract.py::test_AC3_10_1_statement_parsing_is_source_capture_not_framework_policy",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.11.1",
            statement="A missing `period_start` falls back to `period_end` instead of hard-failing the parse",  # was AC3.11.1
            test="apps/backend/tests/extraction/test_extraction.py::test_AC3_11_1_period_start_falls_back_to_period_end",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.11.2",
            statement="With no period bounds, the statement period is derived from the transaction-date range",  # was AC3.11.2
            test="apps/backend/tests/extraction/test_extraction.py::test_AC3_11_2_period_derived_from_transaction_dates",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.11.3",
            statement="A statement with no period and no transaction dates still rejects (no silent zero-date)",  # was AC3.11.3
            test="apps/backend/tests/extraction/test_extraction.py::test_AC3_11_3_no_resolvable_date_still_raises",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.12.1",
            statement="A brokerage holdings statement with no opening/closing balances persists `balance_validated=None` (not a vacuous `0==0` true)",  # was AC3.12.1
            test="apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py::test_AC3_12_1_brokerage_without_balances_reports_balance_validated_none_not_vacuous_true",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.101.1",
            statement="Test that valid balances pass validation",  # was AC13.1.1
            test="apps/backend/tests/extraction/test_extraction.py::test_balance_valid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.101.2",
            statement="Test that invalid balances fail validation",  # was AC13.1.2
            test="apps/backend/tests/extraction/test_extraction.py::test_balance_invalid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.101.3",
            statement="Test that small differences are tolerated",  # was AC13.1.3
            test="apps/backend/tests/extraction/test_extraction.py::test_balance_tolerance",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.102.1",
            statement="Test that complete data gets high confidence (Auto-Accept)",  # was AC13.2.1
            test="apps/backend/tests/extraction/test_extraction.py::test_high_confidence",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.102.2",
            statement="Test that partial data gets medium confidence (Review)",  # was AC13.2.2
            test="apps/backend/tests/extraction/test_extraction.py::test_medium_confidence",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.102.3",
            statement="Test that no transactions lowers confidence (Manual)",  # was AC13.2.3
            test="apps/backend/tests/extraction/test_extraction.py::test_low_confidence_empty_transactions",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.103.1",
            statement="Test DBS fixture has correct structure",  # was AC13.3.1
            test="apps/backend/tests/extraction/test_extraction.py::test_dbs_fixture_structure",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.103.2",
            statement="Test DBS fixture balances reconcile",  # was AC13.3.2
            test="apps/backend/tests/extraction/test_extraction.py::test_dbs_balance_reconciliation",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.103.3",
            statement="Test MariBank fixture has sanitized merchant names",  # was AC13.3.3
            test="apps/backend/tests/extraction/test_extraction.py::test_maribank_fixture_descriptions_carry_no_pii",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.103.4",
            statement="Test GXS fixture has daily interest entries",  # was AC13.3.4
            test="apps/backend/tests/extraction/test_extraction.py::test_gxs_fixture_daily_interest",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.103.5",
            statement="Test all fixtures have valid dates",  # was AC13.3.5
            test="apps/backend/tests/extraction/test_extraction.py::test_all_fixtures_have_dates",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.1",
            statement="Test default parsing prompt",  # was AC13.4.1
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_default",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.2",
            statement="Test DBS-specific prompt",  # was AC13.4.2
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_dbs",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.3",
            statement="Test CMB-specific prompt",  # was AC13.4.3
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_cmb",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.4",
            statement="Test with unknown institution returns base prompt",  # was AC13.4.4
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_unknown_institution",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.5",
            statement="Test Futu-specific prompt",  # was AC13.4.5
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_futu",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.6",
            statement="Test GXS-specific prompt",  # was AC13.4.6
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_gxs",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.104.7",
            statement="Test MariBank-specific prompt",  # was AC13.4.7
            test="apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_maribank",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.105.1",
            statement="Test that PDF payloads use provider-compatible `file` or `image_url` shapes",  # was AC13.5.1
            test="apps/backend/tests/api/test_statements_router.py::test_build_statement_storage_key_sanitizes_extension",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.105.2",
            statement="Test that PNG images use 'image_url' type",  # was AC13.5.2
            test="apps/backend/tests/extraction/test_extraction.py::test_png_uses_image_url_type",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.105.3",
            statement="Test that JPG images use 'image_url' type",  # was AC13.5.3
            test="apps/backend/tests/extraction/test_extraction.py::test_jpg_uses_image_url_type",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.105.4",
            statement="Test that JPEG images use 'image_url' type",  # was AC13.5.4
            test="apps/backend/tests/extraction/test_extraction.py::test_jpeg_uses_image_url_type",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.106.1",
            statement="Test that CSV parsing raises error when institution is None",  # was AC13.6.1
            test="apps/backend/tests/extraction/test_extraction.py::test_csv_requires_institution",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.106.2",
            statement="Test that parse_document accepts institution=None for PDFs (AI auto-detect)",  # was AC13.6.2
            test="apps/backend/tests/extraction/test_extraction.py::test_parse_document_accepts_none_institution_for_pdf",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.106.3",
            statement="Test that parse_document accepts force_model parameter",  # was AC13.6.3
            test="apps/backend/tests/extraction/test_extraction.py::test_parse_document_accepts_force_model",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.5",
            statement="Test _safe_date with valid input",  # was AC13.7.5
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_date_valid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.6",
            statement="Test _safe_date with invalid format",  # was AC13.7.6
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_date_invalid_format",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.7",
            statement="Test _safe_date with empty input",  # was AC13.7.7
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_date_empty",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.8",
            statement="Test _safe_decimal with valid input",  # was AC13.7.8
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_valid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.9",
            statement="Test _safe_decimal with invalid input",  # was AC13.7.9
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_invalid",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.10",
            statement="Test _safe_decimal with None",  # was AC13.7.10
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_none",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.11",
            statement="Test _safe_decimal None required",  # was AC13.7.11
            test="apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_none_required",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.107.12",
            statement="Test compute_confidence with missing transactions key",  # was AC13.7.12
            test="apps/backend/tests/extraction/test_extraction.py::test_compute_confidence_missing_transactions",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.1",
            statement="Test consistent chain scores 10",  # was AC13.8.1
            test="apps/backend/tests/extraction/test_extraction.py::test_consistent_chain",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.2",
            statement="Test inconsistent chain scores 0",  # was AC13.8.2
            test="apps/backend/tests/extraction/test_extraction.py::test_inconsistent_chain",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.3",
            statement="Test single transaction",  # was AC13.8.3
            test="apps/backend/tests/extraction/test_extraction.py::test_single_txn",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.4",
            statement="Test no balance after",  # was AC13.8.4
            test="apps/backend/tests/extraction/test_extraction.py::test_no_balance_after",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.5",
            statement="Test empty list",  # was AC13.8.5
            test="apps/backend/tests/extraction/test_extraction.py::test_empty_list",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.6",
            statement="Test partial consistency",  # was AC13.8.6
            test="apps/backend/tests/extraction/test_extraction.py::test_partial_consistency",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.7",
            statement="Test all currencies match",  # was AC13.8.7
            test="apps/backend/tests/extraction/test_extraction.py::test_all_match_header",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.8",
            statement="Test no currencies match",  # was AC13.8.8
            test="apps/backend/tests/extraction/test_extraction.py::test_none_match",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.9",
            statement="Test no header currency",  # was AC13.8.9
            test="apps/backend/tests/extraction/test_extraction.py::test_no_header_uses_most_common",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.10",
            statement="Test no currencies in transactions",  # was AC13.8.10
            test="apps/backend/tests/extraction/test_extraction.py::test_no_currencies",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.11",
            statement="Test empty list (currency)",  # was AC13.8.11
            test="apps/backend/tests/extraction/test_extraction.py::test_empty_list",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.12",
            statement="Test mixed currencies partial",  # was AC13.8.12
            test="apps/backend/tests/extraction/test_extraction.py::test_mixed_currencies_partial",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.108.13",
            statement="Test missing currencies penalized",  # was AC13.8.13
            test="apps/backend/tests/extraction/test_extraction.py::test_missing_currencies_penalized",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.109.1",
            statement="Test full score with all factors",  # was AC13.9.1
            test="apps/backend/tests/extraction/test_extraction.py::test_full_score_with_all_factors",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.109.2",
            statement="Test no new factors caps at 85",  # was AC13.9.2
            test="apps/backend/tests/extraction/test_extraction.py::test_no_new_factors_caps_at_85",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.115.1",
            statement="Brokerage statement with a single transaction is penalized below the review/auto-approve band",  # was AC13.15.1
            test="apps/backend/tests/extraction/test_extraction.py::test_brokerage_single_txn_penalized",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.115.2",
            statement="Brokerage statement with a plausible transaction count is not penalized",  # was AC13.15.2
            test="apps/backend/tests/extraction/test_extraction.py::test_brokerage_sufficient_txns_not_penalized",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.115.3",
            statement="Non-brokerage (bank) statement with one transaction keeps its existing score",  # was AC13.15.3
            test="apps/backend/tests/extraction/test_extraction.py::test_bank_single_txn_not_penalized",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.115.4",
            statement="`is_brokerage` defaults to False so existing callers are unaffected",  # was AC13.15.4
            test="apps/backend/tests/extraction/test_extraction.py::test_default_is_not_brokerage",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.115.5",
            statement="The cap uses the persisted transaction count (after skipped rows), not the raw extracted count",  # was AC13.15.5
            test="apps/backend/tests/extraction/test_extraction.py::test_effective_count_uses_persisted_not_extracted",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.118.1",
            statement="The vision model list appends `VISION_FALLBACK_MODELS` after the primary OCR/vision model, deduplicated and order-preserving, so more than one model is attempted on the vision path",  # was AC13.18.1
            test="apps/backend/tests/extraction/test_extraction_error_paths.py::test_extract_financial_data_shared_ocr_vision_skips_layout_parser",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.118.2",
            statement="When the primary vision model raises a non-retryable provider error (e.g. a 400), the vision path attempts the configured vision fallback model and succeeds instead of failing the upload",  # was AC13.18.2
            test="apps/backend/tests/extraction/test_extraction_error_paths.py::test_vision_path_falls_back_to_secondary_model_on_non_retryable_error",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.119.1",
            statement="Common non-ISO date formats parse; empty/garbage return None",  # was AC13.19.1
            test="apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_1_tolerant_parse_date_accepts_non_iso_formats",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.119.2",
            statement="A Chinese-format statement parses instead of being rejected",  # was AC13.19.2
            test="apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_2_chinese_format_statement_parses_instead_of_aborting",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.119.3",
            statement="One unparseable row date is non-fatal — the row is skipped, the rest parse",  # was AC13.19.3
            test="apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_3_one_bad_row_date_is_non_fatal",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.119.4",
            statement="The model is the primary date normalizer: the prompt instructs converting any source format to ISO YYYY-MM-DD (parser is only a fallback)",  # was AC13.19.4
            test="apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_4_parsing_prompt_instructs_iso_date_normalization",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.1",
            statement="A markdown json-fenced object (multi-line and single-line) is recovered",  # was AC13.14.1
            test="apps/backend/tests/extraction/test_json_repair.py::test_strips_json_code_fence",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.2",
            statement="Surrounding prose and a bare fence reduce to the outermost balanced object",  # was AC13.14.2
            test="apps/backend/tests/extraction/test_json_repair.py::test_strips_bare_code_fence_and_prose",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.3",
            statement="An already-clean object round-trips unchanged",  # was AC13.14.3
            test="apps/backend/tests/extraction/test_json_repair.py::test_clean_object_is_preserved",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.4",
            statement="Content with no recoverable JSON object returns None; braces inside strings do not truncate",  # was AC13.14.4
            test="apps/backend/tests/extraction/test_json_repair.py::test_unrecoverable_returns_none",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.5",
            statement="The extraction loop salvages a fenced response instead of rejecting the upload",  # was AC13.14.5
            test="apps/backend/tests/extraction/test_json_repair.py::test_fenced_response_is_salvaged",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.6",
            statement="A response with no recoverable JSON still fails through the model-chain path",  # was AC13.14.6
            test="apps/backend/tests/extraction/test_json_repair.py::test_unrecoverable_response_still_fails",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.7",
            statement="When a small example object precedes the real (larger) extraction, the largest object is recovered (not the example)",  # was AC13.14.7
            test="apps/backend/tests/extraction/test_json_repair.py::test_prefers_largest_object_when_example_precedes_real",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.8",
            statement="A complete object followed by trailing unbalanced-brace junk still recovers the complete object",  # was AC13.14.8
            test="apps/backend/tests/extraction/test_json_repair.py::test_complete_object_then_trailing_unbalanced_brace",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.114.9",
            statement="A leading unmatched brace (junk) before the real object does not stop the scan — the real object is recovered",  # was AC13.14.9
            test="apps/backend/tests/extraction/test_json_repair.py::test_leading_unbalanced_brace_then_real_object",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.1",
            statement="Source type stamped on manual entry creation",  # was AC13.10.1
            test="apps/backend/tests/reconciliation/test_source_type.py::test_source_type_stamped_on_create",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.2",
            statement="Auto-match records trusted anchor without mutating posted source_type",  # was AC13.10.2
            test="apps/backend/tests/reconciliation/test_source_type.py::test_auto_match_records_anchor_without_mutating_posted_source_type",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.3",
            statement="Stage-1 approve promotes to user_confirmed",  # was AC13.10.3
            test="apps/backend/tests/extraction/test_source_type_promotion.py::test_stage1_approve_promotes_source_type",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.4",
            statement="Manual entry wins over auto_parsed in conflict",  # was AC13.10.4
            test="apps/backend/tests/infra/test_migrations.py::test_AC13_10_4_source_type_migration_handles_missing_legacy_enum_label",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.5",
            statement="source_type cannot be downgraded",  # was AC13.10.5
            test="apps/backend/tests/reconciliation/test_source_type.py::test_source_type_no_downgrade",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.110.6",
            statement="All four source_type values accepted by API",  # was AC13.10.6
            test="apps/backend/tests/reconciliation/test_source_type.py::test_all_four_source_type_values_accepted_by_api",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.112.1",
            statement="Source coverage matrix covers every source class named by vision.md with owner EPICs, proof levels, ingestion path, review requirement, traceability target, and test anchors",  # was AC13.12.1
            test="tests/tooling/test_source_coverage_matrix.py::test_AC13_12_1_source_coverage_matrix_covers_vision_source_classes",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.112.2",
            statement="Source coverage matrix rejects source classes whose only proof level is post-merge LLM/OCR unless an explicit exception is recorded",  # was AC13.12.2
            test="tests/tooling/test_source_coverage_matrix.py::test_AC13_12_2_source_coverage_matrix_rejects_llm_only_sources",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.112.3",
            statement="Source coverage matrix requires a gap issue for any source class still classified as a gap",  # was AC13.12.3
            test="tests/tooling/test_source_coverage_matrix.py::test_AC13_12_3_source_coverage_matrix_requires_gap_issue",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.111.1",
            statement="Dual-write handles duplicate document hash / IntegrityError without failing.",  # was AC13.11.1
            test="apps/backend/tests/extraction/test_extraction_error_paths.py::test_dual_write_layer2_integrity_error_is_non_fatal",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.111.2",
            statement="Dedup upsert sanitizes malformed source_documents payloads (transaction).",  # was AC13.11.2
            test="apps/backend/tests/extraction/test_deduplication.py::test_upsert_atomic_transaction_handles_non_list_source_documents",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.113.1",
            statement="Pure scoring + routing functions return identical results across N runs on the same input.",  # was AC13.13.1
            test="apps/backend/tests/extraction/test_extraction_determinism.py::test_scoring_and_routing_are_deterministic",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.113.2",
            statement="Re-parsing identical model output yields identical confidence/status/validation_error across N parses.",  # was AC13.13.2
            test="apps/backend/tests/extraction/test_extraction_determinism.py::test_repeated_parse_yields_identical_confidence_status_validation",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.113.3",
            statement="Each payload class (bank-valid, bank-balance-invalid, brokerage) routes consistently across N parses.",  # was AC13.13.3
            test="apps/backend/tests/extraction/test_extraction_determinism.py::test_routing_is_consistent_per_payload_class",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.1",
            statement="`route_by_threshold` routes a balance-invalid bank statement to `PARSED` (review), never `uploaded`, regardless of score.",  # was AC13.21.1
            test="apps/backend/tests/accounting/test_validation.py::test_AC13_21_1_balance_invalid_routes_to_parsed_review",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.2",
            statement="_Superseded by AC-extraction.2009.2 (#1352)._ A parsed bank statement that fails balance reconciliation is now BLOCKING: it is quarantined to `REJECTED` (not `PARSED`/review) with `stage1_status=REJECTED` and a typed `validation_error` reason code.",  # was AC13.21.2
            test="apps/backend/tests/extraction/test_extraction_determinism.py::test_AC20_9_2_balance_invalid_parse_is_quarantined",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.3",
            statement="The retry endpoint accepts a balance-invalid statement at its `PARSED` resting state.",  # was AC13.21.3
            test="apps/backend/tests/api/test_statements_router.py::test_AC13_21_3_retry_accepts_parsed_resting_state",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.4",
            statement="Report readiness counts the balance-invalid `PARSED` statement as an available input.",  # was AC13.21.4
            test="apps/backend/tests/accounting/test_validation.py::test_AC13_21_4_readiness_counts_parsed_balance_invalid",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.5",
            statement="_Superseded by AC-extraction.2009.2 (#1352)._ The same balance-mismatch payload routes deterministically across N parses to the same status — now `REJECTED` (the LLM-LED blocking gate), not `PARSED`.",  # was AC13.21.5
            test="apps/backend/tests/extraction/test_extraction_determinism.py::test_routing_is_consistent_per_payload_class",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.121.6",
            statement="CSV upload with a missing institution fails synchronously with HTTP 400 and an actionable message.",  # was AC13.21.6
            test="apps/backend/tests/api/test_statements_router.py::test_AC13_21_6_csv_missing_institution_rejected_sync",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.122.1",
            statement="Two distinct same-date/same-amount/same-direction rows sharing one running `balance_after` hash differently within one document (via `occurrence_index`), while a re-uploaded identical row still collapses across documents.",  # was AC13.22.1
            test="apps/backend/tests/extraction/test_deduplication.py::test_AC13_22_1_same_balance_distinct_rows_do_not_collapse",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.122.2",
            statement="A parsed statement with two same-date/same-amount deposits separated by a carried-forward/brought-forward balance repeat persists both deposits and the running-balance chain reconciles.",  # was AC13.22.2
            test="apps/backend/tests/extraction/test_dual_write_layer2.py::test_AC13_22_2_page_boundary_duplicate_deposit_survives",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.116.1",
            statement="A provided seed is forwarded in the streaming request payload",  # was AC13.16.1
            test="apps/backend/tests/ai/test_ai_streaming.py::test_stream_ai_json_forwards_zai_knobs_and_seed",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.116.2",
            statement="Extraction forwards the configured `ai_json_seed` to the model call",  # was AC13.16.2
            test="apps/backend/tests/extraction/test_seed_determinism.py::test_extraction_forwards_configured_seed",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.116.3",
            statement="Extraction pins `temperature=0` / `do_sample=False` alongside the seed",  # was AC13.16.3
            test="apps/backend/tests/extraction/test_seed_determinism.py::test_extraction_decoding_is_deterministic_by_default",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.116.4",
            statement="Empty `AI_JSON_SEED` parses as None (omitted) instead of raising",  # was AC13.16.4
            test="apps/backend/tests/extraction/test_seed_determinism.py::test_empty_seed_env_is_treated_as_none",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.116.5",
            statement="The seed is off (None) by default so it is never sent to providers that reject it (e.g. glm-4.6v)",  # was AC13.16.5
            test="apps/backend/tests/extraction/test_seed_determinism.py::test_seed_is_off_by_default",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.1",
            statement="A reconciling first parse is returned without retry",  # was AC13.17.1
            test="apps/backend/tests/extraction/test_self_consistency.py::test_reconciles_first_attempt_single_call",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.2",
            statement="A failing parse is retried and the reconciling result wins",  # was AC13.17.2
            test="apps/backend/tests/extraction/test_self_consistency.py::test_retries_until_reconciles",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.3",
            statement="When no attempt reconciles, the smallest-difference result is kept",  # was AC13.17.3
            test="apps/backend/tests/extraction/test_self_consistency.py::test_keeps_best_when_none_reconcile",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.4",
            statement="Brokerage payloads are not retried",  # was AC13.17.4
            test="apps/backend/tests/extraction/test_self_consistency.py::test_brokerage_is_not_retried",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.5",
            statement="Attempt 0 uses the configured seed; retries vary it (seed+1, seed+2 …)",  # was AC13.17.5
            test="apps/backend/tests/extraction/test_self_consistency.py::test_seed_varies_per_attempt",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.6",
            statement="`AI_EXTRACT_MAX_ATTEMPTS=1` keeps single-shot behavior",  # was AC13.17.6
            test="apps/backend/tests/extraction/test_self_consistency.py::test_max_attempts_one_disables_retry",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.7",
            statement='A structurally-invalid parse (balance uncomputable, difference 0) does not win "best" over a numerically-close parse',  # was AC13.17.7
            test="apps/backend/tests/extraction/test_self_consistency.py::test_structurally_invalid_parse_does_not_win_as_best",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.8",
            statement="If every attempt is structurally invalid, the last parse is returned so `parse_document` reports the failure",  # was AC13.17.8
            test="apps/backend/tests/extraction/test_self_consistency.py::test_all_invalid_returns_last_parse",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.9",
            statement="A transient extraction error on a retry attempt keeps the earlier usable parse (no upload regression)",  # was AC13.17.9
            test="apps/backend/tests/extraction/test_self_consistency.py::test_transient_retry_error_keeps_earlier_usable_parse",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.10",
            statement="If every attempt raises, the error propagates so the upload fails as in the single-call path",  # was AC13.17.10
            test="apps/backend/tests/extraction/test_self_consistency.py::test_all_attempts_error_reraises",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.11",
            statement="A transient error on the first attempt does not abort; a later reconciling attempt is returned",  # was AC13.17.11
            test="apps/backend/tests/extraction/test_self_consistency.py::test_first_attempt_error_then_success_recovers",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.117.12",
            statement="An error after an earlier usable parse keeps trying remaining attempts; a later reconciling parse still wins",  # was AC13.17.12
            test="apps/backend/tests/extraction/test_self_consistency.py::test_error_mid_run_does_not_skip_remaining_attempts",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.1",
            statement="AC-C1: detector pinpoints the exact break index on a crafted chain with a dropped row",  # was AC13.20.1
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_1_detector_finds_break_index_on_dropped_row",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.2",
            statement="AC-C1: a clean running-balance chain reports no break",  # was AC13.20.2
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_2_clean_chain_reports_no_break",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.3",
            statement="AC-C1: detection is Decimal-based and tolerant within `BALANCE_TOLERANCE` (no float drift)",  # was AC13.20.3
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_3_detector_is_decimal_tolerant",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.4",
            statement="AC-C2: on balance mismatch with a detected break, the repair hook is invoked exactly once",  # was AC13.20.4
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_4_repair_hook_invoked_once_on_mismatch",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.5",
            statement="AC-C2: a clean/reconciling chain never invokes the repair hook",  # was AC13.20.5
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_5_repair_hook_not_invoked_on_clean_chain",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.6",
            statement="AC-C2: when no repair backend is injected, the hook is a safe no-op returning the original payload",  # was AC13.20.6
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_6_repair_is_safe_noop_without_backend",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.7",
            statement="AC-C3: the synthetic dropped-row fixture drives the detector to the correct index and triggers the repair hook",  # was AC13.20.7
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_7_regression_fixture_detects_and_repairs",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.120.8",
            statement="AC-C3: the clean-bank dropped-row regression-corpus fixture triggers the chain-break detector + `repair_under_extraction` end-to-end through `ExtractionService._extract_with_balance_retry` with an injected `RegionReExtractor` (recall stays a soft metric)",  # was AC13.20.8
            test="apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_8_corpus_fixture_triggers_repair_end_to_end",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.123.1",
            statement="User deletion is refused with HTTP 409 (actionable message) while the user has a statement in the `PARSING` (in-flight) state; with no in-flight parse the delete still succeeds (204)",  # was AC13.23.1
            test="apps/backend/tests/api/test_users_router.py::test_AC13_23_1_delete_user_with_in_flight_parse_returns_409",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.123.2",
            statement="Parse-failure lineage write re-checks user existence and skips the FK-violating insert (no `IntegrityError`) when the owning user is gone",  # was AC13.23.2
            test="apps/backend/tests/extraction/test_parse_user_deletion_lifecycle.py::test_AC13_23_2_failed_lineage_skips_when_user_deleted",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.123.3",
            statement="The failure handler rolls back before reading ORM attributes (cached `statement_id`); the original error is preserved/logged and never masked by `PendingRollbackError`",  # was AC13.23.3
            test="apps/backend/tests/extraction/test_parse_user_deletion_lifecycle.py::test_AC13_23_3_failure_handler_rolls_back_before_reading_orm",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        # AC-extraction.* migrated from EPIC-011 groups 11.13, 11.15 (#1419-pattern AC move).
        ACRecord(
            id="AC-extraction.212.1",
            statement=(
                "Re-applying the same rule version to the same atomic "
                "transaction is idempotent and returns the existing "
                "classification without inserting duplicates. Was EPIC-011 "
                "AC11.12.1."
            ),
            test=(
                "apps/backend/tests/extraction/test_classification_service.py"
                "::test_apply_rules_is_idempotent_for_existing_transaction_rule_version"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.213.1",
            statement=(
                "Parsing populates Layer 1/2 by default, without any feature-flag "
                "override. Was EPIC-011 AC11.13.1."
            ),
            test=(
                "apps/backend/tests/extraction/test_dual_write_layer2.py"
                "::test_dual_write_enabled_by_default"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.3",
            statement=(
                "Custody account resolves from a Layer-2 atomic transaction via "
                "the conform (DWD-native). Was EPIC-011 AC11.15.3."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_custody_account_from_atomic_txn"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.4",
            statement=(
                "The resolver returns None when the source statement has no "
                "confirmed custody account. Was EPIC-011 AC11.15.4."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_returns_none_without_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.5",
            statement=(
                "The resolver normalizes a {'documents': [...]} source-documents "
                "wrapper. Was EPIC-011 AC11.15.5."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_handles_dict_wrapper_source_documents"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.6",
            statement=(
                "The resolver skips junk entries, non-bank-statement sources, and "
                "invalid UUIDs. Was EPIC-011 AC11.15.6."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_ignores_invalid_and_non_bank_sources"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.7",
            statement=(
                "A non-list/non-dict source_documents value resolves to None. Was "
                "EPIC-011 AC11.15.7."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_returns_none_for_non_list_source_documents"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.8",
            statement=(
                "The first source document (in order) with a confirmed account "
                "wins. Was EPIC-011 AC11.15.8."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_preserves_source_document_order"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.215.9",
            statement=(
                "A known source document with no confirmed custody account "
                "resolves to None. Was EPIC-011 AC11.15.9."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_resolve_returns_none_when_no_source_has_account"
            ),
            priority="P0",
            status="done",
        ),
        # AC-extraction.* migrated from EPIC-017 groups 17.32 (#1419-pattern AC move).
        ACRecord(
            id="AC-extraction.332.1",
            statement=(
                "Brokerage positions CSV is mapped into a positions payload (not "
                "a bank parse failure) so it reaches the brokerage import path. "
                "Was EPIC-017 AC17.32.1."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_csv_routing.py"
                "::test_AC17_32_1_brokerage_positions_csv_produces_positions_payload"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.332.2",
            statement=(
                "Brokerage trade-history CSV raises an actionable unsupported- "
                "document error, not the generic bank 'No valid transactions' "
                "failure. Was EPIC-017 AC17.32.2."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_csv_routing.py"
                "::test_AC17_32_2_brokerage_trade_history_csv_raises_actionable_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.332.3",
            statement=(
                "Bank transaction CSV parsing is unaffected by brokerage CSV "
                "detection (no regression). Was EPIC-017 AC17.32.3."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_csv_routing.py"
                "::test_AC17_32_3_bank_csv_unaffected_by_brokerage_detection"
            ),
            priority="P1",
            status="done",
        ),
        # Row-level moves out of mixed EPIC groups (per-EPIC hundred-block
        # ids: EPIC-004->4xx, EPIC-008->8xx, EPIC-011->2xx, EPIC-016->16xx,
        # EPIC-017->3xx, EPIC-020->20xx; seq preserved).
        ACRecord(
            id="AC-extraction.406.8",
            statement=(
                "AtomicTransaction persists the extracted balance_after so the "
                "conflict guard can disambiguate distinct-but-identical "
                "transactions. Was EPIC-004 AC4.6.8."
            ),
            test=(
                "apps/backend/tests/extraction/test_deduplication.py"
                "::test_upsert_persists_balance_after"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.407.2",
            statement=(
                "get_few_shot_examples respects default limit and caches results. "
                "Was EPIC-004 AC4.7.2."
            ),
            test=(
                "apps/backend/tests/extraction/test_correction_service_cache.py"
                "::test_get_few_shot_examples_cache_hit_and_limit"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.413.6",
            statement=(
                "currency_balances JSONB persists a per-currency balance array "
                "additively to the scalar columns. Was EPIC-004 AC4.13.6."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_summary_conform.py"
                "::test_AC1_currency_balances_jsonb_round_trips"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.812.6",
            statement=(
                "OCR/vision provider fallback, timeout, and empty-response errors "
                "are deterministic. Was EPIC-008 AC8.12.6."
            ),
            test=(
                "apps/backend/tests/extraction/test_extraction_error_paths.py"
                "::test_extract_financial_data_shared_ocr_vision_skips_layout_parser"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.812.4",
            statement=(
                "PDF with private URL logs warning and raises ExtractionError "
                "(lines 393->403, 416->426). Was EPIC-008 AC8.12.4."
            ),
            test=(
                "apps/backend/tests/extraction/test_extraction_error_paths.py"
                "::test_extract_financial_data_pdf_private_url_raises"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.812.5",
            statement=(
                "Image with private URL logs warning and raises ExtractionError "
                "(else branch 416->426). Was EPIC-008 AC8.12.5."
            ),
            test=(
                "apps/backend/tests/extraction/test_extraction_error_paths.py"
                "::test_extract_financial_data_image_private_url_raises"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.813.10",
            statement=(
                "Multi-brokerage PDF upload → position import → latest portfolio "
                "value. Was EPIC-008 AC8.13.10."
            ),
            test=(
                "tests/e2e/test_brokerage_upload_to_portfolio_value.py"
                "::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.813.11",
            statement=(
                "A DBS bank statement PDF's full browser journey: upload with an "
                "explicit OCR model selection, poll until parsed (failing/skipping "
                "on a rejected AI/OCR status rather than hanging), the detail page "
                "shows transactions, Start Review -> Approve transitions the "
                "statement to approved, and the balance sheet report loads "
                "afterward. Was EPIC-008 AC8.13.1-.5 / .7 (migration closeout wave "
                "3, #1663)."
            ),
            test=(
                "tests/e2e/test_statement_full_journey.py"
                "::test_dbs_statement_full_journey"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.813.12",
            statement=(
                "A statement upload's full browser journey (institution name + "
                "explicit model selection + PDF upload) returns a 2xx with an "
                "id, the row appears in the statement list, and the statement is "
                "immediately fetchable via the API in a valid status (never "
                "silently rejected without a gate check). Was EPIC-008 AC8.13.8 "
                "(migration closeout wave 3, #1663)."
            ),
            test=(
                "tests/e2e/test_statement_upload_e2e.py"
                "::test_statement_upload_full_flow"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.216.1",
            statement=(
                "Distinct running balances hash differently; identical/absent "
                "balances collapse. Was EPIC-011 AC11.16.1."
            ),
            test=(
                "apps/backend/tests/extraction/test_deduplication.py"
                "::test_running_balance_distinguishes_identical_transactions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1622.8",
            statement=(
                "A statement routed to parsed/review carries stage1_status = "
                "pending_review explicitly (never NULL). Was EPIC-016 AC16.22.8."
            ),
            test=(
                "apps/backend/tests/extraction/test_extraction_flow.py"
                "::test_parsed_statement_sets_stage1_pending_review"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1622.9",
            statement=(
                "UploadedDocument.status advances to completed once a successful "
                "parse is persisted (no longer stuck at uploaded). Was EPIC-016 "
                "AC16.22.9."
            ),
            test=(
                "apps/backend/tests/extraction/test_dual_write_layer2.py"
                "::test_dual_write_marks_document_completed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1622.10",
            statement=(
                "A hard parse failure persists an UploadedDocument (status "
                "failed) so the uploaded raw file stays traceable from the "
                "rejected statement. Was EPIC-016 AC16.22.10."
            ),
            test=(
                "apps/backend/tests/extraction/test_extraction_error_paths.py"
                "::test_handle_parse_failure_persists_failed_document_lineage"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.7",
            statement=("Upload Parse-to-Import Bridge. Was EPIC-017 AC17.4.7."),
            test=(
                "apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py"
                "::test_parse_statement_background_imports_brokerage_positions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.9",
            statement=(
                "AC-B1 Producer routing: brokerage docs select the positions "
                "prompt before the model call (filename/institution), bank docs "
                "keep the bank prompt. Was EPIC-017 AC17.4.9."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py"
                "::test_AC_B1_looks_like_brokerage_document_routes_by_filename_and_institution"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.10",
            statement=(
                "AC-B2 Brokerage positions output schema flows into "
                "AtomicPosition-ready snapshots via the existing consumer parser. "
                "Was EPIC-017 AC17.4.10."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py"
                "::test_AC_B2_positions_prompt_payload_is_understood_by_consumer_parser"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.11",
            statement=(
                "AC-B5 Zero-position brokerage doc is surfaced as a visible "
                "review flag (stage1 pending-review + note). Was EPIC-017 "
                "AC17.4.11."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py"
                "::test_AC_B5_zero_position_brokerage_doc_raises_visible_review_flag"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.12",
            statement=(
                "AC-B4/B6 Moomoo holdings TABLE extracts and imports: "
                "AtomicPosition rows == table rows with exact market_value "
                "(#1088). Was EPIC-017 AC17.4.12."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py"
                "::test_AC_B4_AC_B6_moomoo_positions_table_extracts_and_imports"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.304.13",
            statement=(
                "AC-B3 A multi-currency brokerage statement persists a per- "
                "currency NAV array (currency_balances) instead of collapsing to "
                "a single scalar opening/closing: each currency's NAV is the sum "
                "of that currency's positions, every currency round-trips "
                "independently, and no currency is cross-summed into another "
                "(#1139). Was EPIC-017 AC17.4.13."
            ),
            test=(
                "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py"
                "::test_AC_B3_multi_currency_brokerage_emits_per_currency_balances"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.2",
            statement=(
                "LLM-LED tier (event→L2) balance-chain failure is a BLOCKING "
                "runtime gate: a bank-statement extraction whose chain does not "
                "reconcile (opening + ΣIN − ΣOUT ≠ closing beyond the Decimal "
                "tolerance) is quarantined to the rejected terminal state with a "
                "typed reason code and never reaches parsed/trusted report-input "
                "state; code may reject, never author. Was EPIC-020 AC20.9.2."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_2_imbalanced_bank_extraction_is_quarantined_not_parsed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.3",
            statement=(
                "LLM-LED tier dedup-conservation failure is an INDEPENDENT "
                "blocking gate: a within-document dedup collapse (post-dedup row "
                "count ≠ conserved pre-dedup count) quarantines the extraction "
                "with a reason code DISTINCT from the balance-chain reason. Was "
                "EPIC-020 AC20.9.3."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_3_within_doc_dedup_collapse_is_quarantined"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.4",
            statement=(
                "LLM-LED tier gate is fail-closed: when a balance invariant "
                "cannot be evaluated because a bank statement is missing an "
                "opening or closing balance, the extraction never reaches "
                "parsed/trusted state (the parse path refuses it) and the pure "
                "gate quarantines the unevaluable case with a typed reason, "
                "rather than silently passing on a zero-default chain. Was "
                "EPIC-020 AC20.9.4."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_4_unevaluable_balance_fails_closed_not_parsed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.5",
            statement=(
                "The prior 'imbalanced bank statement → parsed/review' behavior "
                "no longer exists: routing a true balance-chain failure no longer "
                "returns parsed. Was EPIC-020 AC20.9.5."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_5_imbalanced_no_longer_routes_to_parsed_review"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.6",
            statement=(
                "No false reject: a balanced, dedup-consistent bank-statement "
                "extraction still flows through to its prior parsed/approved "
                "resting state unchanged by the gate. Was EPIC-020 AC20.9.6."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_6_valid_extraction_passes_gate_unchanged"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.7",
            statement=(
                "Each LLM-LED gate failure mode emits a distinct structured "
                "reason code and a distinct PII-free metric kind (balance vs "
                "dedup vs unevaluable), with no institution name or account "
                "identifier in the signal. Was EPIC-020 AC20.9.7."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_7_each_failure_mode_has_distinct_reason_and_metric"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2009.8",
            statement=(
                "A db-backed quarantine persists the terminal `rejected` "
                "status to the statement row, writing no Layer-2 financial "
                "rows, instead of leaving an upload stuck in `parsing`. Was "
                "EPIC-020 AC20.9.8."
            ),
            test=(
                "apps/backend/tests/llm/test_llm_led_blocking_gate.py"
                "::test_AC20_9_8_quarantined_statement_persists_rejected_not_stuck_parsing"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.2502.1",
            statement=(
                "`approve_statement_workflow` / `reject_statement_workflow` "
                "(`src.extraction.extension.statement_workflow`) own the "
                "ordered transition -> side-effect -> commit sequence as one "
                "unit (approve: transition, auto-post, commit; reject: "
                "transition, commit, refresh), and the statements router "
                "delegates to these workflow functions directly instead of "
                "inlining approve/reject + commit. Was EPIC-025 AC25.2.1."
            ),
            test=(
                "apps/backend/tests/api/test_statement_workflow_service.py"
                "::test_statement_workflow_service"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.stage1-review.1",
            statement=(
                "get_pending_stage1_review returns an empty list for a user with "
                "no pending-review statements. Was EPIC-001 AC1.6.2 (migration "
                "closeout wave 3, #1663)."
            ),
            test=(
                "apps/backend/tests/review/test_statement_validation.py"
                "::test_returns_empty_when_none_pending"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1807: Evidence Graph foundation — nodes, edges, upsert,
        # bounded traversal (was EPIC-018 AC18.7.1-7, migration closeout
        # continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1807.1",
            statement=(
                "The Evidence Graph SSOT defines nodes as auditable states, "
                "edges as transformation processes, allowed foundation node/"
                "edge fields, traversal direction, and append-only edge "
                "rules."
            ),
            test=(
                "apps/backend/tests/infra/test_evidence_lineage_contract.py"
                "::test_AC18_7_1_evidence_lineage_ssot_defines_graph_semantics"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.2",
            statement=(
                "The Alembic migration creates evidence_nodes and "
                "evidence_edges with user-scoped entity lookup and edge "
                "traversal indexes."
            ),
            test=(
                "apps/backend/tests/infra/test_evidence_lineage_migration_contract.py"
                "::test_AC18_7_2_evidence_lineage_migration_creates_tables_and_indexes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.3",
            statement=(
                "SQLAlchemy models expose EvidenceNode and EvidenceEdge "
                "with JSONB properties and user-owned isolation."
            ),
            test=(
                "apps/backend/tests/infra/test_evidence_lineage_contract.py"
                "::test_AC18_7_3_evidence_lineage_models_expose_jsonb_user_owned_graph_tables"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.4",
            statement=(
                "The evidence lineage service supports idempotent node and "
                "edge upsert keyed by user, entity identity, node kind, "
                "relation, and edge endpoints."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_lineage.py"
                "::test_AC18_7_4_node_and_edge_upserts_are_idempotent"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.5",
            statement=(
                "The evidence lineage service resolves entity nodes and "
                "traverses upstream and downstream paths only within the "
                "authenticated user's scope."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_lineage.py"
                "::test_AC18_7_5_traversal_resolves_upstream_and_downstream_by_entity"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.6",
            statement=(
                "Evidence lineage traversal enforces a default maximum "
                "depth and never walks unbounded graphs."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_lineage.py"
                "::test_AC18_7_6_traversal_enforces_depth_limit"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1807.7",
            statement=(
                "Evidence Graph foundation tests cover node creation, edge "
                "creation, duplicate upsert behavior, upstream traversal, "
                "downstream traversal, depth limit, and cross-user "
                "isolation."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_lineage.py"
                "::test_AC18_7_5_cross_user_edges_and_traversal_are_blocked"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 1808: Evidence Graph source-to-report integration (was
        # EPIC-018 AC18.8.1-7, migration closeout continuation, #1663 /
        # #1715) ──
        ACRecord(
            id="AC-extraction.1808.1",
            statement=(
                "Statement upload creates a source_document node for the "
                "uploaded source (uploaded_document); the legacy "
                "extracted_record middle node was removed in EPIC-011 "
                "Stage 3 with the bank_statements tables."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_4_direct_entity_materialization_branches_are_idempotent"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.2",
            statement=(
                "Layer 2 lineage creates atomic_fact nodes for atomic "
                "transactions and deduped_into edges from the "
                "source_document (uploaded document) that produced them."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_4_direct_entity_materialization_branches_are_idempotent"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.3",
            statement=(
                "Journal posting creates ledger_entry and ledger_line "
                "nodes, links extracted or atomic transaction facts to the "
                "ledger entry with posted_as, and links the ledger entry "
                "to its lines with contains."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.4",
            statement=(
                "GET /api/reports/package/traceability can resolve at "
                "least one report line from ledger anchors through "
                "Evidence Graph lineage back to source document anchors."
            ),
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC18_8_4_AC18_8_7_package_traceability_resolves_report_line_to_source_document"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.5",
            statement=(
                "Unknown or unsupported JournalEntry.source_id values "
                "produce explicit blocker codes and never fabricate "
                "statement, atomic, or document anchors."
            ),
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.6",
            statement=(
                "Existing JournalEntry.source_type/source_id semantics "
                "remain backward-compatible while Evidence Graph writes "
                "add supplemental audit lineage."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1808.7",
            statement=(
                "Tests cover three end-to-end graph paths: source document "
                "downstream impact, bank statement transaction to ledger "
                "line, and report line to source document."
            ),
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC18_8_4_AC18_8_7_package_traceability_resolves_report_line_to_source_document"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1809: Evidence Graph navigation UX — backend API contract
        # (was EPIC-018 AC18.9.1-3, migration closeout continuation, #1663 /
        # #1715). AC18.9.4-6 (frontend lineage panel) stay in EPIC-018 —
        # extraction is a backend-only package (fe=None). ──
        ACRecord(
            id="AC-extraction.1809.1",
            statement=(
                "An authenticated Evidence Graph lineage API resolves an "
                "owned graph node by entity_type, entity_id, and optional "
                "node_kind."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1809.2",
            statement=(
                "The lineage API supports upstream, downstream, and "
                "both-direction traversal with bounded depth and returns "
                "stable node and edge DTOs."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1809.3",
            statement=(
                "Missing, unsupported, or cross-user entity identities "
                "return explicit empty/blocker state and never fabricate "
                "source, ledger, or report anchors."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_9_3_lineage_api_returns_blocker_for_missing_or_cross_user_anchor"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 1810: Evidence Graph lazy materialization and consistency
        # guardrails (was EPIC-018 AC18.10.1-7, migration closeout
        # continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1810.1",
            statement=(
                "The Evidence Graph SSOT defines the graph as an audit "
                "projection, business tables as source of truth, and a "
                "blocker taxonomy for drift states."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_5_detector_reports_missing_orphan_and_cross_user_drift"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.2",
            statement=(
                "New source-to-ledger workflows materialize graph nodes "
                "and edges in the same database transaction as their "
                "owning business facts."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_2_graph_writes_share_the_business_transaction"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.3",
            statement=(
                "The lineage API attempts one bounded deterministic "
                "materialization pass when an owned anchor or required "
                "local path is missing for historical data."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_10_3_AC18_10_4_lineage_api_lazily_materializes_historical_journal_line"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.4",
            statement=(
                "Lazy materialization is idempotent and only uses strong "
                "relationships such as owned source IDs, transaction "
                "lineage, and journal_line.journal_entry_id; it never "
                "infers links from fuzzy amount, date, or description "
                "similarity."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.5",
            statement=(
                "An operator-safe dry-run detector reports missing graph "
                "nodes, graph nodes pointing to missing business entities, "
                "dangling edges, cross-user edges, incomplete lineage, and "
                "ambiguous or unsupported provenance."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_5_detector_reports_missing_orphan_and_cross_user_drift"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.6",
            statement=(
                "The detector and lazy repair never mutate accounting "
                "facts, report amounts, ledger balances, or legacy "
                "JournalEntry.source_type/source_id values."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1810.7",
            statement=(
                "Tests cover request-time lazy repair, repeated-read "
                "idempotency, dry-run no-write behavior, cross-user "
                "blocking, unknown provenance blockers, dangling/orphan "
                "detection, and request-level write caps."
            ),
            test=(
                "apps/backend/tests/services/test_evidence_graph_materialization.py"
                "::test_AC18_10_7_materialization_caps_and_unknown_sources_return_blockers"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1831: Evidence Graph typed properties and fail-fast
        # materialization (was EPIC-018 AC18.31.1-2, migration closeout
        # continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1831.1",
            statement=(
                "Evidence Graph node and edge DTO properties are "
                "constrained by closed typed Pydantic models per node kind "
                "and edge relation (monetary amounts stay Decimal-as-"
                "string, never float), preserving the existing JSON shape "
                "and tolerating legacy/partial rows."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_31_1_node_properties_are_typed_and_round_trip"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1831.2",
            statement=(
                "A genuine materialization failure (cross-user, write-cap, "
                "or unsupported provenance) returns a non-2xx status with "
                "a structured EvidenceLineageError detail, while an absent "
                "anchor stays a 200 empty/blocker result."
            ),
            test=(
                "apps/backend/tests/api/test_evidence_lineage_router.py"
                "::test_AC18_31_2_failure_status_distinguishes_genuine_failure_from_empty"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 1801: classification retirement — the pre-classify-node
        # rule matching path (was EPIC-018 AC18.1.3-4, migration closeout
        # continuation, #1663 / #1715). AC18.1.1 is already proven by
        # AC-extraction.104.1 (was AC13.4.1); AC18.1.2/.5/.6 are not
        # verified in this pass — see the EPIC-018 doc note. ──
        ACRecord(
            id="AC-extraction.1801.1",
            statement=(
                "RuleType.ML_MODEL rule matching is RETIRED (EPIC #1483 "
                "cleanup) — even an active ML_MODEL rule never applies, "
                "since it read AI signals (suggested_category/"
                "category_confidence) that no producer ever wrote; it "
                "survives only as the classification-policy anchor row "
                "type for the classify node (AC18.15)."
            ),
            test=(
                "apps/backend/tests/extraction/test_classification_service.py"
                "::test_AC18_1_3_ml_rule_matching_is_retired"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1801.2",
            statement=(
                "Classification priority is KEYWORD > REGEX > Uncategorized "
                "(the ML tier moved to the classify node, AC18.15)."
            ),
            test=(
                "apps/backend/tests/extraction/test_classification_service.py"
                "::test_classification_priority_keyword_over_regex"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1802: correction feedback substrate — CorrectionLog,
        # stats, few-shot injection, cache (was EPIC-018 AC18.2.1-5,
        # migration closeout continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1802.1",
            statement="The CorrectionLog model records the original and corrected categories.",
            test=(
                "apps/backend/tests/extraction/test_correction_service.py"
                "::test_record_correction_stores_corrected_category"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1802.2",
            statement="The corrections API records and retrieves correction stats, scoped to the owning user.",
            test=(
                "apps/backend/tests/extraction/test_correction_service.py"
                "::test_AC18_2_2_record_correction_rejects_cross_user_corrected_account"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1802.3",
            statement="Few-shot examples from corrections are injected into the extraction prompt.",
            test=(
                "apps/backend/tests/extraction/test_correction_service.py"
                "::test_prompt_injection_with_corrections"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1802.4",
            statement=(
                "The correction cache has a 1-hour TTL and also invalidates "
                "immediately after recording a new correction."
            ),
            test=(
                "apps/backend/tests/extraction/test_correction_service.py"
                "::test_few_shot_cache_invalidates"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1802.5",
            statement="top_corrections is typed as a TopCorrection Pydantic model in the corrections stats response, not a bare dict.",
            test=(
                "apps/backend/tests/api/test_corrections_router.py"
                "::test_AC18_2_5_top_corrections_is_typed_pydantic_model"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1814: correction feedback loop — corpus derived from
        # CorrectionLog, replayed as priors (was EPIC-018 AC18.14.1-4,
        # migration closeout continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1814.1",
            statement=(
                "The correction corpus is derived from CorrectionLog (no "
                "sidecar), keyed by the transaction pattern, capturing "
                "proposed vs corrected."
            ),
            test=(
                "apps/backend/tests/services/test_correction_loop.py"
                "::test_AC18_14_1_corpus_is_derived_from_corrections_keyed_by_pattern"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1814.2",
            statement=(
                "Replaying the corpus as priors strictly lowers the "
                "held-out low-confidence proportion when correction "
                "patterns recur, and invents no reduction when they do not."
            ),
            test=(
                "apps/backend/tests/services/test_correction_loop.py"
                "::test_AC18_14_2_replay_lowers_low_confidence_proportion_when_patterns_recur"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1814.3",
            statement="The service builds the corpus from the persisted correction store, scoped to the user.",
            test=(
                "apps/backend/tests/services/test_correction_loop.py"
                "::test_AC18_14_3_service_builds_corpus_from_persisted_corrections"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-extraction.1814.4",
            statement=(
                "The service replays the live corpus and measures the "
                "held-out reduction: recurring correction patterns ground "
                "the held-out split so the measured low-confidence "
                "proportion provably drops."
            ),
            test=(
                "apps/backend/tests/services/test_correction_loop.py"
                "::test_AC18_14_4_service_replay_measures_held_out_reduction"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 1815: transaction classify node — construct (was
        # EPIC-018 AC18.15.1-8, migration closeout continuation, #1663 /
        # #1715) ──
        ACRecord(
            id="AC-extraction.1815.1",
            statement=(
                "The classification policy is a versioned, effective-dated, "
                "immutable object: policy_for(as_of) head-selects the "
                "latest version whose effective_from <= as_of, and an "
                "effective version can never be mutated."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_1_policy_is_effective_dated_and_immutable"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.2",
            statement=(
                "The classify pass is reproducible: identical (transactions, "
                "policy, proposals) produce identical outcomes, each "
                "stamped with the policy version."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_2_classify_is_reproducible_for_same_inputs"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.3",
            statement=(
                "Model output is constrained to the policy's closed "
                "catalog: an off-catalog proposal is rejected, and the LLM "
                "boundary parses prompt-driven JSON with code-owned "
                "clamping and a graceful per-transaction None fallback."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_3_off_catalog_proposal_is_rejected_never_applied"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.4",
            statement=(
                "The confidence gate disposes deterministically: >= auto "
                "threshold becomes an APPLIED classification, the review "
                "band becomes a DRAFT visible to the ai_feedback 60-84 "
                "queue, below stays in the genuine Uncategorized tail."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_4_confidence_gate_applies_reviews_or_tails"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.5",
            statement=(
                "The model never touches money: proposals cannot express "
                "an amount, the node imports no posting primitives, and "
                "transaction Decimal amounts pass through classification "
                "untouched."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_5_model_never_touches_money"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.6",
            statement=(
                "commit_basis=False computes verdicts under a candidate "
                "policy without writing the basis-of-record: no "
                "classifications, no policy rules, no accounts."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_6_pro_forma_writes_nothing"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.7",
            statement=(
                "A user's deterministic rule wins before the model is "
                "consulted, and having no rules is a no-op pre-pass, not "
                "an error."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_7_user_rule_prepass_wins_over_model"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1815.8",
            statement=(
                "The node is inert with enable_ai_classification off (the "
                "default), and its production consumers are exactly the "
                "two declared seams — the posting path and the backfill/"
                "re-extract router; no other module may grow a side-door "
                "into classification."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_15_8_flag_off_is_a_noop"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group 1816: transaction classification — migrate (was EPIC-018
        # AC18.16.1-5, migration closeout continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1816.1",
            statement=(
                "Publishing a new policy version leaves every "
                "already-covered period's as-reported income statement "
                "byte-identical: each transaction classifies under the "
                "policy in effect on its own txn_date, and a full "
                "recompute after publishing stays prospective."
            ),
            test=(
                "apps/backend/tests/services/test_classification_migration.py"
                "::test_AC18_16_1_new_policy_version_never_restates_covered_periods"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1816.2",
            statement=(
                "After a real statement import with the flag on, the "
                "income statement has categorized leaf lines beyond the "
                "two Uncategorized buckets, each with a non-null "
                "confidence tier."
            ),
            test=(
                "apps/backend/tests/services/test_classification_migration.py"
                "::test_AC18_16_2_import_produces_categorized_income_statement"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1816.3",
            statement=(
                "With enable_ai_classification off (the default), the "
                "import path behaves exactly as before this EPIC: only "
                "the two Uncategorized buckets, zero classification rows."
            ),
            test=(
                "apps/backend/tests/services/test_classification_migration.py"
                "::test_AC18_16_3_flag_off_is_byte_identical_to_today"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1816.4",
            statement=(
                "The one-time backfill classifies each not-yet-classified "
                "transaction once under its own effective policy; a "
                "re-run is a no-op (idempotent, dated, append-only)."
            ),
            test=(
                "apps/backend/tests/services/test_classification_migration.py"
                "::test_AC18_16_4_backfill_is_idempotent_dated_append_only"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1816.5",
            statement=(
                "Re-running classification never rewrites posted journal "
                "entries or lines — the category is a projection over the "
                "immutable ledger, not an edit of it."
            ),
            test=(
                "apps/backend/tests/services/test_classification_migration.py"
                "::test_AC18_16_5_reclassification_never_rewrites_posted_entries"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        # ── group 1817: transaction classification — cleanup (was EPIC-018
        # AC18.17.1-3, migration closeout continuation, #1663 / #1715) ──
        ACRecord(
            id="AC-extraction.1817.1",
            statement=(
                "Every classification entry seam has a production call "
                "site and the core pass is wired to a live seam (AST "
                "gate) — a defined-but-uninvoked classify writer fails CI."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_17_1_no_classify_writer_is_defined_but_uninvoked"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1817.2",
            statement=(
                "POST /classifications/backfill classifies the caller's "
                "not-yet-classified transactions under each transaction's "
                "own effective policy, never duplicates or rewrites an "
                "existing classification on re-run, and is flag-gated "
                "(off => zero classifications)."
            ),
            test=(
                "apps/backend/tests/api/test_classifications_router.py"
                "::test_AC18_17_2_backfill_endpoint_classifies_then_is_idempotent"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-extraction.1817.3",
            statement=(
                "Reports consume exactly one classification source and "
                "only APPLIED rows — the DRAFT review band and SUPERSEDED "
                "history never leak into as-reported figures."
            ),
            test=(
                "apps/backend/tests/services/test_transaction_classification.py"
                "::test_AC18_17_3_reports_read_only_applied_classifications"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
    ],
)
