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
* ``UploadedDocument`` moved from the unregistered ``src/models/`` into
  ``orm/layer1.py`` (#1675 D3); its ``platform``/``runtime`` readers now go
  through the published ``extension/uploaded_document_reads.py`` lookups
  instead of importing the ORM class. The rest of the fact family followed in
  D4+D5c (``orm/layer2-4.py``, ``orm/evidence.py``, ``orm/correction.py``)
  after every cross-domain ``relationship()`` (to ``Account``/``User``) was
  replaced by bare FK id columns + explicit reads; downstream domains import
  the published entity names. ``portfolio`` left ``depends_on`` in the same
  step: the one extraction→portfolio call (position reconciliation after a
  brokerage import) is inverted through ``register_position_reconciler``,
  wired by ``main.py``, so portfolio can import this package's entities
  without a cycle. ``StatementSummary``/statement enums completed the move in
  #1675 D6 (``orm/statement_summary.py`` and source lifecycle enums), the
  final models-decentralization slice: the workflow package directly consumes
  extraction's published ``StatementEventSource`` read model, while
  ``ledger``/``identity``
  (same rank, dependency-cycle — both readers extraction itself
  ``depends_on``) read through their own registered ports
  (``register_statement_coverage_reader`` / ``register_in_flight_parse_checker``),
  each remain wired by ``main.py`` to avoid their existing same-rank cycles.
* ``confidence_metric`` / ``confidence_tier`` (journal-confidence metric
  snapshots) are NOT this package's — they read ledger's aggregates and stay
  in ``services/`` pending the reporting/observability re-home.
* The OCR layout-parsing call routes through ``src.llm``'s ``ocr_layout_call``
  chokepoint (#1670), which is why ``llm`` is now a declared dependency. The
  JSON/vision call sites already went through ``llm`` via
  ``src.llm``'s ``stream_ai_json`` (physically ``llm/extension/streaming.py``
  since #1670's fold). Threading per-user provider binding (``user_id``)
  into these OCR/vision/json call sites — so a BYO-provider user's own model
  is used, not just the deployment default — is a separate, still-pending
  follow-up (AC-llm.4.5), independent of the ``llm`` dependency edge itself.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ac,
    CommandBoundary,
    ConceptRecord,
    ContextRelation,
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
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
    depends_on=[
        "audit",
        "identity",
        "ledger",
        "llm",
        "observability",
        "platform",
        # ``portfolio`` was dropped (#1675 D5c): the former direct
        # ``PositionService`` import is now ``register_position_reconciler``,
        # an inverted port wired by main.py. ``pricing`` was dropped the same
        # way: the former FX-rate-lookup import (review-queue journal
        # promotion, #1610 P2's pricing.get_exchange_rate) is now
        # ``register_fx_rate_provider``, also wired by main.py — extraction
        # no longer imports either package directly.
        "runtime",
    ],
    context=ContextScope(
        purpose="Own source-document ingestion, parsing, validation, and evidence lineage that turn supported financial documents into reviewable source facts.",
        in_scope=[
            "uploaded-document and statement source lifecycle, parsed facts, and provenance",
            "document parsing, confidence/balance validation, review disposition, and corrections",
            "extraction-owned AtomicTransaction and AtomicPosition facts and source-to-fact evidence lineage",
        ],
        out_of_scope=[
            "double-entry journal ownership, account policy, and final ledger facts",
            "model-provider configuration, shared financial value/assurance ownership, and storage infrastructure",
            "portfolio valuation, pricing resolution, reconciliation matching, and report presentation",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="audit",
            consumer="extraction",
            mode="published-language",
            reason="Uses audit monetary, quantity, source-type, and invariant language while retaining source-document semantics.",
        ),
        ContextRelation(
            provider="audit",
            consumer="extraction",
            mode="consumer-port",
            reason="Consumes audit TraceRecord ports to attach evidence to extraction decisions without owning assurance authority or persistence.",
        ),
        ContextRelation(
            provider="identity",
            consumer="extraction",
            mode="published-language",
            reason="Uses the identity-owned user language to scope source documents and parsing work.",
        ),
        ContextRelation(
            provider="ledger",
            consumer="extraction",
            mode="consumer-port",
            reason="Uses ledger command and account ports to submit reviewed, dispositioned financial facts without owning double-entry state.",
        ),
        ContextRelation(
            provider="llm",
            consumer="extraction",
            mode="published-language",
            reason="Uses the LLM facade's typed OCR/vision/JSON call language while keeping document parsing and acceptance policy in extraction.",
        ),
        ContextRelation(
            provider="observability",
            consumer="extraction",
            mode="published-language",
            reason="Uses published safe logging, PII, and parse-outcome telemetry language.",
        ),
        ContextRelation(
            provider="platform",
            consumer="extraction",
            mode="composition",
            reason="Uses platform persistence mixins and shared application exceptions without owning the substrate.",
        ),
        ContextRelation(
            provider="runtime",
            consumer="extraction",
            mode="consumer-port",
            reason="Consumes the runtime storage port and redaction helper for source content without owning environment dependency configuration.",
        ),
    ],
    roles=["base", "extension", "data"],
    units=[
        # ── base: the pure validation/confidence calculus lives in
        # base/validation.py; its functions are published via the interface.
        # (Not declared as units: KIND_LAYER has no pure-function kind homed in
        # base — the base-layer-pure invariant is the guard instead.)
        # ── aggregates/entities: taxonomy-only (module unset — the gate skips
        # placement checks; the mapped classes live in orm/, #1675 D5c-D6) ──
        Unit(name="StatementSummary", kind=Kind.AGGREGATE_ROOT),
        Unit(name="UploadedDocument", kind=Kind.ENTITY),
        Unit(name="AtomicTransaction", kind=Kind.ENTITY),
        # The alias row is persistence owned by the identity resolver, not a
        # separate pure domain entity. Bind the behavior to its actual owner.
        Unit(
            name="resolve_transaction_identity",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/transaction_identity.py",
        ),
        Unit(
            name="effective_statement_transaction_filter",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/transaction_membership.py",
        ),
        Unit(name="AtomicPosition", kind=Kind.ENTITY),
        Unit(name="ClassificationRule", kind=Kind.ENTITY),
        Unit(
            name="RuleType", kind=Kind.VALUE_OBJECT, module="base/source_vocabulary.py"
        ),
        Unit(
            name="DocumentType",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(
            name="DocumentStatus",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(
            name="TransactionDirection",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(
            name="ClassificationStatus",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(
            name="BankStatementStatus",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(
            name="Stage1Status",
            kind=Kind.VALUE_OBJECT,
            module="base/source_vocabulary.py",
        ),
        Unit(name="TransactionClassification", kind=Kind.ENTITY),
        # ``ManagedPosition`` is portfolio's aggregate.  Extraction physically
        # hosts the schema-preserving current-position row as a source-derived
        # projection, but does not claim the investment-position concept.
        Unit(name="ManagedPositionSnapshot", kind=Kind.PROJECTION),
        Unit(name="CorrectionLog", kind=Kind.ENTITY),
        Unit(name="EvidenceNode", kind=Kind.ENTITY),
        Unit(name="EvidenceEdge", kind=Kind.ENTITY),
        # ── extension: the parsing pipeline + adapters ──
        Unit(
            name="ExtractionService",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/service.py",
        ),
        Unit(
            name="StatementIngestionUseCase",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/statement_parsing.py",
        ),
        Unit(
            name="build_statement_ingestion_use_case",
            kind=Kind.FACTORY,
        ),
        Unit(
            name="extraction_trace_policy_registry",
            kind=Kind.FACTORY,
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
        # extraction's contribution to FX-scope discovery (#1641) — the
        # distinct currencies on the user's imported AtomicPosition snapshots,
        # composed by the delivery layer into pricing's crawl scopes.
        Unit(
            name="snapshot_currencies",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/currencies.py",
        ),
        # dual-write persistence verbs (upsert by dedup_hash). Declared as the
        # repository IMPL half only via taxonomy for now: carving the base
        # port out of the raw-AsyncSession verbs is an unscheduled design option;
        # until it receives an AC the unit is taxonomy-only.
        Unit(name="AtomicTransactionRepository", kind=Kind.REPOSITORY),
        # ── data: evidence lineage read-models ──
        # Taxonomy-only: the lineage read/write paths are still entangled
        # (integration instantiates the lineage reader; materialization uses an
        # integration helper), so the physical files sit in extension/ and the
        # clean data/ split is an unscheduled package-internal design option.
        Unit(name="EvidenceLineageService", kind=Kind.PROJECTION),
        Unit(name="EvidenceGraphMaterializationService", kind=Kind.PROJECTION),
        # ── reserved: the balance-chain violation as a domain event (today it
        # is only metrics-logged; publishing via the platform outbox is the
        # planned upgrade — package-internal, not a re-cutover) ──
        Unit(name="BalanceChainViolated", kind=Kind.DOMAIN_EVENT),
        Unit(name="DocumentSource", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(
            name="ExtractedTransactionRow",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(name="ParseJob", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(
            name="RetireStatementCommand",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="retire_statement",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/source_lifecycle.py",
        ),
        Unit(
            name="StatementExtractionResult",
            kind=Kind.VALUE_OBJECT,
            module="base/result.py",
        ),
        # #1681: the only source-result/position payload reporting may consume.
        # It resolves an immutable source version and its current TraceRecord
        # decision before the reporting package can freeze either.
        Unit(
            name="ResolvedStatementContribution",
            kind=Kind.VALUE_OBJECT,
            module="base/contribution.py",
        ),
        Unit(
            name="resolve_statement_contribution",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/statement_contribution.py",
        ),
        Unit(
            name="list_statement_contributions",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/statement_contribution.py",
        ),
        Unit(
            name="ReviewedStatementEnvelopeCommand",
            kind=Kind.VALUE_OBJECT,
            module="base/reviewed_statement_envelope.py",
        ),
        Unit(
            name="confirm_reviewed_statement_envelope",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/reviewed_statement_envelope.py",
        ),
        Unit(
            name="SourceCapability",
            kind=Kind.VALUE_OBJECT,
            module="base/source_capability.py",
        ),
        Unit(
            name="DispositionPolicy",
            kind=Kind.DOMAIN_SERVICE,
        ),
        Unit(
            name="DispositionDecision",
            kind=Kind.VALUE_OBJECT,
            module="base/disposition.py",
        ),
        Unit(
            name="StatementDispositionPolicySnapshot",
            kind=Kind.VALUE_OBJECT,
            module="base/disposition.py",
        ),
        Unit(
            name="IntentProposal",
            kind=Kind.VALUE_OBJECT,
            module="base/disposition.py",
        ),
        Unit(
            name="IntentProposalOrigin",
            kind=Kind.VALUE_OBJECT,
            module="base/disposition.py",
        ),
        Unit(
            name="build_disposition_trace_records",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/disposition_trace.py",
        ),
        Unit(
            name="emit_disposition_trace_records",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/disposition_trace.py",
        ),
        Unit(
            name="current_statement_disposition_policy_snapshot",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/disposition_policy.py",
        ),
        Unit(
            name="StatementIngestionOutcome",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="StatementIngestionStatus",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="StatementPostingOutcome",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="StatementPostingStatus",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
    ],
    implementations={"be": "apps/backend/src/extraction", "fe": None},
    interface=[
        "AssetType",
        "AtomicPosition",
        "AtomicTransaction",
        "BankStatementStatus",
        "BrokeragePositionImportService",
        "ClassificationRule",
        "ClassificationStatus",
        "CorrectionLoopService",
        "CostBasisMethod",
        "CurrencyUnresolvedError",
        "DEFAULT_MAX_DEPTH",
        "DeduplicationService",
        "DispositionCommand",
        "DispositionContext",
        "DocumentSource",
        "DocumentStatus",
        "DocumentType",
        "EvidenceEdge",
        "EvidenceGraphIntegrationService",
        "EvidenceGraphMaterializationService",
        "EvidenceLineageService",
        "EvidenceNode",
        "EvidenceTraversalStep",
        "ExtractedPositionFact",
        "ExtractionError",
        "ExtractionService",
        "ExtractedTransactionFact",
        "ExtractedTransactionRow",
        "ExtractionMethod",
        "ManagedPosition",
        "PositionStatus",
        "ParseJob",
        "RetryableStatementIngestionError",
        "RetireStatementCommand",
        "ReviewedStatementEnvelopeCommand",
        "ReviewedStatementEnvelopeConflict",
        "RuleType",
        "DispositionDecision",
        "DispositionMode",
        "DispositionPolicy",
        "DispositionStatus",
        "EconomicIntent",
        "IntentProposal",
        "IntentProposalOrigin",
        "SourceCapability",
        "SourceCapabilityStatus",
        "SOURCE_CAPABILITIES",
        "SourceProvenance",
        "SYSTEM_PROMPT",
        "Stage1Status",
        "StatementBalanceFact",
        "StatementIngestionConfigurationError",
        "StatementIngestionError",
        "StatementIngestionOutcome",
        "StatementIngestionStatus",
        "StatementIngestionUseCase",
        "StatementDispositionPolicySnapshot",
        "StatementExtractionResult",
        "ResolvedStatementContribution",
        "StatementEvidenceType",
        "StatementPostingDependencies",
        "StatementPostingOutcome",
        "StatementPostingStatus",
        "StatementSourceType",
        "StatementTransaction",
        "StatementEventSource",
        "StatementSummary",
        "TransactionClassification",
        "TransactionDirection",
        "UploadedDocument",
        "_brokerage_import_not_ready_reason",
        "_brokerage_payload_from_persisted_extraction",
        "_brokerage_payload_from_statement",
        "approve_statement_workflow",
        "auto_create_posted_entries_for_statement",
        "backfill_classifications",
        "build_csv_mapping_prompt",
        "build_disposition_trace_records",
        "build_statement_ingestion_use_case",
        "compute_confidence_score",
        "confirm_reviewed_statement_envelope",
        "create_entry_from_txn",
        "current_reviewed_statement_envelope",
        "current_statement_disposition_policy_snapshot",
        "detect_balance_chain_break",
        "dual_write_layer2",
        "emit_disposition_trace_records",
        "edit_and_approve",
        "extraction_trace_policy_registry",
        "find_in_flight_parse_id",
        "find_uploaded_document_filename_by_hash",
        "get_correction_stats",
        "get_current_statement_extraction_result",
        "get_known_storage_paths",
        "get_parsing_prompt",
        "get_statement_coverage_rows",
        "get_statement_event_sources",
        "get_uploaded_document_filename",
        "get_uploaded_document_filenames",
        "looks_like_brokerage_document",
        "looks_like_brokerage_payload",
        "parse_brokerage_csv_payload",
        "parse_brokerage_positions",
        "pending_stage1_review_filter",
        "persist_statement_extraction_result",
        "record_correction",
        "resolve_statement_contribution",
        "list_statement_contributions",
        "register_fx_rate_provider",
        "register_position_reconciler",
        "register_statement_source",
        "reject_json_floats",
        "reject_statement_workflow",
        "retire_statement",
        "resolve_custody_account_id",
        "resolve_ingest_currency",
        "resolve_statement_conflicts",
        "resolve_bank_custody_account",
        "is_bank_custody_source",
        "resolve_statement_posting_account",
        "resolve_statement_transactions",
        "effective_statement_transaction_filter",
        "resolve_transaction_currency",
        "run_parsing_supervisor",
        "set_opening_balance",
        "snapshot_currencies",
        "submit_parse_pipeline",
        "supports_reviewed_statement_envelope",
        "validate_balance",
        "validate_balance_chain",
        "validation",
    ],
    command_boundaries=[
        CommandBoundary(
            symbol="ReviewedStatementEnvelopeCommand",
            version="1",
            proof=(
                "apps/backend/tests/extraction/test_reviewed_statement_envelope.py"
                "::test_AC_extraction_reviewed_envelope_1_preserves_source_absence_until_typed_command"
            ),
        )
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
    # The EPIC-003 + EPIC-013 ACs, migrated per Decision A. AC3.3.2/AC3.5.10/
    # AC3.6.4 (groups 3/5/6) were the last 3 EPIC-003 rows migrated (2026-07-14):
    # their legacy {tier:HU}{proof:evidence} marker predates the tier->proof
    # matrix and was never revisited; the underlying tests are ordinary
    # deterministic assertions, so proof_kind="property" applies cleanly under
    # this package's LLM-LED tier — no authority-tier conflict. (standard-preserving
    # move; the EPIC table rows were deleted in the same commit). Numeric
    # AC-<pkg>.<group>.<seq> grammar with reserved group blocks (the ledger
    # precedent): **1–12 = EPIC-003** (leading epic number dropped) and
    # **101–123 = EPIC-013** (group + 100, so the two EPICs' group numbers
    # cannot collide). Original ids are kept as trailing comments. A one-off
    # migration from a third EPIC (e.g. EPIC-001's AC1.6.2) uses a word-slug
    # group instead of claiming a new numeric block, so it can never collide
    # with EPIC-003's/EPIC-013's reserved ranges.
    roadmap=[
        ac(
            "AC-extraction.custody-binding.7",
            "The additive custody migration installs the unique identity key without rewriting retained sources or journal history.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_real_custody_migration_installs_unique_key",
        ),
        ac(
            "AC-extraction.custody-binding.1",
            "Custody identity survives account display-name edits and sequential imports.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_rename_preserves_source_custody",
        ),
        ac(
            "AC-extraction.custody-binding.2",
            "Concurrent first imports allocate one account and database uniqueness rejects a second binding.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_concurrent_first_imports_share_one_binding",
        ),
        ac(
            "AC-extraction.custody-binding.3",
            "Exact institution, tenant, suffix, and currency remain separate custody dimensions; brokerage sources never allocate bank bindings.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_custody_key_dimensions_remain_separate",
        ),
        ac(
            "AC-extraction.custody-binding.4",
            "Only unambiguous owned current source evidence may adopt an existing account; conflicting or corrupt history blocks.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_historical_custody_adoption",
        ),
        ac(
            "AC-extraction.custody-binding.5",
            "Explicit account selection cannot bypass owner, currency, active asset type, or existing custody identity.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_explicit_account_cannot_bypass_custody",
        ),
        ac(
            "AC-extraction.custody-binding.6",
            "Rejected or rolled-back new imports leave no orphan custody binding or account.",
            "apps/backend/tests/extraction/test_bank_custody_binding.py::test_rejected_parse_does_not_leave_orphan_custody",
        ),
        ac(
            "AC-extraction.human-source-review.1",
            "A complete balanced single-currency bank cash source below the shared auto-promotion threshold exposes explicit human envelope confirmation without changing confidence, completeness, or raw facts.",
            "apps/backend/tests/extraction/test_human_source_review.py::test_complete_dormant_source_human_confirmation",
            priority="P1",
        ),
        ac(
            "AC-extraction.human-source-review.2",
            "Human envelope commands fill only absent facts and cannot contradict declared source dates, currency, or balances; stale digests and foreign custody are denied.",
            "apps/backend/tests/extraction/test_human_source_review.py::test_human_confirmation_cannot_rewrite_known_source",
            priority="P1",
        ),
        ac(
            "AC-extraction.human-source-review.3",
            "An exact current human envelope takes precedence over machine promotion; stale or revoked review cannot authorize posting or fall back to machine authority.",
            "apps/backend/tests/extraction/test_human_source_review.py::test_revoked_human_review_cannot_authorize_source",
            priority="P1",
        ),
        ac(
            "AC-extraction.human-source-review.4",
            "The statement review UI offers the server-authorized confirmation form even when missing source facts are empty and blocks approval until confirmation.",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::complete dormant source offers explicit human confirmation",
            priority="P1",
        ),
        ac(
            "AC-extraction.opening-lineage.4",
            "A changed reparse of a source that established current opening stock requires correction review even with zero transactions or zero stock and preserves the prior source result and opening authority.",
            "apps/backend/tests/extraction/test_opening_evidence_lineage.py::test_dormant_posted_source_reparse_requires_correction",
            priority="P1",
        ),
        ac(
            "AC-extraction.opening-lineage.1",
            "Current authoritative source-backed opening positions, including zero without a journal, expose bounded idempotent PDF lineage through their account identity and opening journal lines.",
            "apps/backend/tests/extraction/test_opening_evidence_lineage.py::test_sourced_opening_reaches_pdf",
            priority="P1",
        ),
        ac(
            "AC-extraction.opening-lineage.2",
            "Opening lineage refuses retired, revoked, void, or mismatched source authority even when graph edges were previously materialized, and foreign accounts reveal no owned anchor.",
            "apps/backend/tests/extraction/test_opening_evidence_lineage.py::test_cached_opening_lineage_rejects_retired_source",
            priority="P1",
        ),
        ac(
            "AC-extraction.opening-lineage.3",
            "Standalone manual opening balances retain honest journal lineage without inventing an uploaded PDF source.",
            "apps/backend/tests/extraction/test_opening_evidence_lineage.py::test_manual_opening_has_no_fabricated_pdf",
            priority="P1",
        ),
        ac(
            "AC-extraction.persistence-proof.2",
            "Only effective current-source transactions may enter downstream queues or actions; superseded facts stay queryable, and unattached legacy records remain explicitly eligible.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_effective_membership_excludes_superseded_sources",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-conservation.1",
            "An unparseable transaction row cannot silently disappear behind a successful net-balance proof; the source remains reachable with an explicit failure.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_bad_dates_cannot_hide_offsetting_transactions",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-conservation.2",
            "Paged extraction preserves every currency balance and rejects conflicting account or balance declarations without inventing source facts.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_paged_currency_and_account_conservation",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.transaction-identity.5",
            "Legacy atomic upsert retains its keyword-capture contract and rejects unsupported custody keywords; the additive scoped upsert accepts an explicit validated custody account without changing existing callers' argument binding.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_legacy_upsert_preserves_keyword_capture",
        ),
        ac(
            "AC-extraction.transaction-identity.1",
            "Distinct custody accounts and currencies retain independent atomic transactions while exact imports of the same custody fact remain idempotent.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_identity_distinguishes_custody_and_currency",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.transaction-identity.2",
            "A versioned identity may reuse a legacy atomic UUID and hash only after source custody and currency agree, without changing historical facts.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_legacy_identity_reuse_preserves_history",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.transaction-identity.3",
            "An ambiguous historical identity is explicitly reviewable while a novel transaction without custody remains source-isolated.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_ambiguous_legacy_identity_is_reviewable",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.transaction-identity.4",
            "Concurrent equal identities resolve to one atomic fact and source lineage remains complete.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_concurrent_identity_upsert",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.retry-identity.1",
            "Retry after failed institution detection uses the recovered source institution rather than the provisional upload placeholder.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_retry_discards_provisional_institution",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-routing.1",
            "A typed bank extraction with an empty positions array remains a bank transaction ledger through metadata recovery.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_bank_result_never_routes_as_brokerage",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-routing.2",
            "An explicitly typed brokerage snapshot with zero positions still routes to brokerage review.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_empty_brokerage_snapshot_remains_reviewable",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.persistence-proof.1",
            "Reparse retains historical atomic identities and lineage, exposes only the current source result, and checkpoints identify the persisted statement and storage source.",
            "apps/backend/tests/extraction/test_source_ingestion_integrity.py::test_reparse_preserves_history_and_current_membership",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-vocabulary.1",
            "Source-domain enum members have one pure base-layer owner with unchanged string values and no direct dependency on persistence or application configuration.",
            "tests/tooling/test_extraction_vocabulary.py::test_source_vocabulary_values_are_stable",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-vocabulary.2",
            "Persistence adapters and the published extraction interface use the same domain enum objects; named SQL enum bindings retain their stored values.",
            "apps/backend/tests/extraction/test_source_vocabulary.py::test_source_enum_persistence_compatibility",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-vocabulary.3",
            "Retired source-enum owners and ORM vocabulary imports cannot return; extraction base has zero direct reverse ORM dependencies.",
            "tests/tooling/test_extraction_vocabulary.py::test_source_vocabulary_has_one_owner",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.fx-port.1",
            "Extraction's FX-rate registration exposes the exact pricing lookup shape without Callable[..., Any] erasure.",
            "tests/tooling/test_s3_pr_d_structure.py::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders",
        ),
        ac(
            "AC-extraction.1.1",
            "Parse DBS PDF",
            "apps/backend/tests/extraction/test_extraction_invariants.py::test_balance_chain_invariant_holds_for_consistent_statements",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.1.2",
            "Parse CSV (DBS)",
            "apps/backend/tests/extraction/test_csv_parsing.py::test_parse_dbs_csv",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1.3",
            "Parse CSV (Wise)",
            "apps/backend/tests/extraction/test_csv_parsing.py::test_parse_wise_csv",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1.4",
            "Parse CSV (Generic)",
            "apps/backend/tests/extraction/test_csv_parsing.py::test_parse_generic_csv_with_amount_column",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1.5",
            "Parse CSV with BOM",
            "apps/backend/tests/extraction/test_csv_parsing.py::test_parse_csv_with_bom",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.2.1",
            "Balance Validation (Pass)",
            "apps/backend/tests/extraction/test_extraction.py::test_balance_valid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.2.2",
            "Balance Validation (Fail)",
            "apps/backend/tests/extraction/test_extraction.py::test_balance_invalid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.2.3",
            "Completeness Validation",
            "apps/backend/tests/extraction/test_pdf_parsing.py::test_missing_required_fields_detected",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.2.4",
            "Bank statement balance mismatches preserve validation_error details",
            "apps/backend/tests/extraction/test_pdf_parsing.py::test_parse_document_bank_balance_mismatch_records_validation_error",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.2.5",
            "CSV transaction exports without statement balances remain reviewable",
            "apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_csv_without_statement_balances_remains_reviewable",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.3.1",
            "High Confidence (Auto-Accept)",
            "apps/backend/tests/api/test_statements_router.py::test_auto_approve_high_confidence_statement_creates_posted_entries",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.3.2",
            "Medium Confidence (Review)",
            "apps/backend/tests/extraction/test_extraction.py::test_medium_confidence",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.3.3",
            "Low Confidence (Manual)",
            "apps/backend/tests/extraction/test_extraction.py::test_low_confidence_empty_transactions",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.4.1",
            "Invalid Parse Not Persisted",
            "apps/backend/tests/extraction/test_pdf_parsing.py::test_extraction_error_not_persisted",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.4.2",
            "Unsupported File Type",
            "apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_unsupported_type",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.4.3",
            "Extraction Timeout",
            "apps/backend/tests/extraction/test_pdf_parsing.py::test_extraction_timeout_raises_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.1",
            "Full Upload Flow",
            "tests/e2e/test_accounts_and_statements_ui_journey.py::test_statement_detail_and_review_surface",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.2",
            "File Size Limit",
            "apps/backend/tests/extraction/test_pdf_parsing.py::test_upload_file_exceeds_10mb_limit",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.3",
            "Model Selection Flow",
            "apps/backend/tests/extraction/test_extraction_flow.py::test_parse_document_csv_success",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.4",
            "Extraction Flow Tests",
            "apps/backend/tests/extraction/test_extraction_flow.py::test_parsed_statement_sets_stage1_pending_review",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.5",
            "Statement Parsing Supervisor",
            "apps/backend/tests/extraction/test_statement_parsing_supervisor.py::test_reset_stale_parsing_jobs_marks_rejected",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.6",
            "Invalid file extension should return 400.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_invalid_extension",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.7",
            "PDF/image uploads may omit model and use the default OCR pipeline.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_uses_default_ocr_pipeline_for_pdf",
            priority="P1",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.5.8",
            "Upload rejects models without image modalities.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_rejects_text_only_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.9",
            "Upload then list statements and transactions.",
            "apps/backend/tests/api/test_statements_router.py::test_list_and_transactions_flow",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.10",
            "Review queue includes reviewable parsed statements and supports approve/reject.",
            "apps/backend/tests/api/test_statements_router.py::test_pending_review_and_decisions",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.11",
            "Missing statement returns 404.",
            "apps/backend/tests/api/test_statements_router.py::test_get_statement_not_found",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.12",
            "File exceeding 10MB limit returns 413.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_file_too_large",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.13",
            "Extraction failure marks statement as rejected.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_extraction_failure",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.14",
            "Retry on missing statement returns 404.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_not_found",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.15",
            "Retry rejects models without image modalities.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_rejects_text_only_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.16",
            "Retry returns 503 if source retrieval fails, preserving the persisted prior status and validation error without dispatching parse work.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_storage_failure",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.17",
            "Retry on statement not in parsed/rejected status returns 400.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_invalid_status",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.18",
            "Verify that retrying a statement in PARSING status is allowed.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_parsing_allowed",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.19",
            "Retry parsing with stronger model succeeds.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_success",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.20",
            "Retry extraction failure returns 422.",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_extraction_failure",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.21",
            "Upload rejects models not in the OpenRouter catalog.",
            "apps/backend/tests/api/test_statements_router.py::test_upload_statement_rejects_invalid_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.22",
            "Upload rejects a model lacking image/PDF modality (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_",
            "apps/backend/tests/api/test_statements_router.py::test_upload_statement_rejects_model_without_image_modality",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.23",
            "Retry rejects a model not in the catalogue (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_",
            "apps/backend/tests/api/test_statements_router.py::test_retry_statement_rejects_invalid_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.24",
            "Background parse error should be caught and logged.",
            "apps/backend/tests/api/test_statements_router.py::test_background_parse_error_logging",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.5.25",
            "Background retry error should be caught and logged.",
            "apps/backend/tests/api/test_statements_router.py::test_background_retry_error_logging",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.1",
            "Unique Prior Mapping",
            "apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.2",
            "No Silent Fallback Posting",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_auto_post_requires_account_mapping",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.3",
            "Ambiguous Mapping Blocked",
            "apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_ambiguous_account_mapping",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.4",
            "Explicit First-Upload Account Creation",
            "apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_creates_account_with_explicit_confirmation",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.5",
            "Prior Mapping Requires Confirmed Statement",
            "apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.6.6",
            "Source Period Unique Before Posting",
            "apps/backend/tests/api/test_statements_router.py::test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.7.1",
            "Latest Confirmed Source",
            "apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_reports_latest_confirmed_balance_and_stale_status",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.7.2",
            "Adjacent Opening Continuity",
            "apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_detects_adjacent_opening_balance_mismatch",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.7.3",
            "Missing/Overlapping/Duplicate Periods",
            "apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_reports_missing_overlapping_and_duplicate_ranges",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.7.4",
            "Broker Daily Snapshot Override",
            "apps/backend/tests/accounting/test_account_statement_coverage.py::test_account_coverage_accepts_broker_monthly_cadence_with_daily_snapshot_override",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.1",
            "Delete old orphaned storage objects",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_deletes_orphaned_object",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.2",
            "Preserve objects with DB records",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_skips_known_db_objects",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.3",
            "Skip recent in-flight uploads",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_skips_recent_objects",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.4",
            "No-op without configured S3 bucket",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_skips_when_no_bucket_configured",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.5",
            "Return zero for empty statement prefix",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_returns_zero_when_no_objects",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.6",
            "Handle storage listing errors",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_handles_storage_list_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.7",
            "Handle object delete errors",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_handles_delete_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.8",
            "Paginate storage keys and normalize timestamps",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.9",
            "Convert storage client listing errors",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_list_storage_keys_raises_on_client_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.10",
            "Exit runner on stop event",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_run_storage_sweep_exits_on_stop_event",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.11",
            "Log runner deletion counts",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_run_storage_sweep_logs_when_objects_deleted",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.12",
            "Continue runner after unexpected sweep exception",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_run_storage_sweep_handles_exception",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.13",
            "Disable runner by feature flag",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_run_storage_sweep_disabled_by_feature_flag",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.14",
            "Grace period + interval config defaults match issue #356 (24h / daily)",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_grace_period_and_interval_defaults_match_issue_356",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.15",
            "Sweep grace-period cutoff is config-driven, not a hardcoded constant",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_sweep_reads_grace_period_from_config",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.8.16",
            "Sweep runner wait interval is read from config",
            "apps/backend/tests/extraction/test_storage_sweep.py::test_run_storage_sweep_reads_interval_from_config",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.9.1",
            "Parsing cases that fail audit are recorded in an SSOT registry without expanding deterministic parser scope or committing real documents",
            "tests/tooling/test_extraction_failed_case_registry.py::test_AC3_9_1_extraction_failed_case_registry_preserves_audit_cases_without_parser_expansion",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.10.1",
            "Statement parsing owns fact-forward settlement evidence capture and must preserve source metadata needed by framework readiness while leaving US/HK policy decisions to EPIC-020",
            "tests/tooling/test_framework_reporting_epic_contract.py::test_AC3_10_1_statement_parsing_is_source_capture_not_framework_policy",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.11.1",
            "A source with only one statement-period bound is rejected rather than copying the present bound",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_11_1_partial_period_rejects_without_copying",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.11.2",
            "Transaction-row dates remain observations and cannot establish an absent statement period",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_11_2_transaction_dates_do_not_establish_statement_period",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.11.3",
            "A transaction without a source-declared transaction date is rejected instead of receiving a synthetic date",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_11_3_missing_transaction_date_rejects",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.12.1",
            "A brokerage holdings statement with no opening/closing balances persists `balance_validated=None` (not a vacuous `0==0` true)",
            "apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py::test_AC3_12_1_brokerage_without_balances_reports_balance_validated_none_not_vacuous_true",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.101.1",
            "Test that valid balances pass validation",
            "apps/backend/tests/extraction/test_extraction.py::test_balance_valid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.101.2",
            "Test that invalid balances fail validation",
            "apps/backend/tests/extraction/test_extraction.py::test_balance_invalid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.101.3",
            "Test that small differences are tolerated",
            "apps/backend/tests/extraction/test_extraction.py::test_balance_tolerance",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.102.1",
            "Test that complete data gets high confidence (Auto-Accept)",
            "apps/backend/tests/extraction/test_extraction.py::test_high_confidence",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.102.3",
            "Test that no transactions lowers confidence (Manual)",
            "apps/backend/tests/extraction/test_extraction.py::test_low_confidence_empty_transactions",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.103.1",
            "Test DBS fixture has correct structure",
            "apps/backend/tests/extraction/test_extraction.py::test_dbs_fixture_structure",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.103.2",
            "Test DBS fixture balances reconcile",
            "apps/backend/tests/extraction/test_extraction.py::test_dbs_balance_reconciliation",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.103.3",
            "Test MariBank fixture has sanitized merchant names",
            "apps/backend/tests/extraction/test_extraction.py::test_maribank_fixture_descriptions_carry_no_pii",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.103.4",
            "Test GXS fixture has daily interest entries",
            "apps/backend/tests/extraction/test_extraction.py::test_gxs_fixture_daily_interest",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.103.5",
            "Test all fixtures have valid dates",
            "apps/backend/tests/extraction/test_extraction.py::test_all_fixtures_have_dates",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.1",
            "Test default parsing prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_default",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.2",
            "Test DBS-specific prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_dbs",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.3",
            "Test CMB-specific prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_cmb",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.4",
            "Test with unknown institution returns base prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_unknown_institution",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.5",
            "Test Futu-specific prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_futu",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.6",
            "Test GXS-specific prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_gxs",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.104.7",
            "Test MariBank-specific prompt",
            "apps/backend/tests/extraction/test_extraction.py::test_get_parsing_prompt_maribank",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.105.1",
            "Test that PDF payloads use provider-compatible `file` or `image_url` shapes",
            "apps/backend/tests/api/test_statements_router.py::test_build_statement_storage_key_sanitizes_extension",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.105.2",
            "Test that PNG images use 'image_url' type",
            "apps/backend/tests/extraction/test_extraction.py::test_png_uses_image_url_type",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.105.3",
            "Test that JPG images use 'image_url' type",
            "apps/backend/tests/extraction/test_extraction.py::test_jpg_uses_image_url_type",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.105.4",
            "Test that JPEG images use 'image_url' type",
            "apps/backend/tests/extraction/test_extraction.py::test_jpeg_uses_image_url_type",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.106.1",
            "Test that CSV parsing raises error when institution is None",
            "apps/backend/tests/extraction/test_extraction.py::test_csv_requires_institution",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.106.2",
            "Test that parse_document accepts institution=None for PDFs (AI auto-detect)",
            "apps/backend/tests/extraction/test_extraction.py::test_parse_document_accepts_none_institution_for_pdf",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.106.3",
            "Test that parse_document accepts force_model parameter",
            "apps/backend/tests/extraction/test_extraction.py::test_parse_document_accepts_force_model",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.5",
            "Test _safe_date with valid input",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_date_valid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.6",
            "Test _safe_date with invalid format",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_date_invalid_format",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.7",
            "Test _safe_date with empty input",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_date_empty",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.8",
            "Test _safe_decimal with valid input",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_valid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.9",
            "Test _safe_decimal with invalid input",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_invalid",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.10",
            "Test _safe_decimal with None",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_none",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.11",
            "Test _safe_decimal None required",
            "apps/backend/tests/extraction/test_extraction.py::test_safe_decimal_none_required",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.107.12",
            "Test compute_confidence with missing transactions key",
            "apps/backend/tests/extraction/test_extraction.py::test_compute_confidence_missing_transactions",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.1",
            "Test consistent chain scores 10",
            "apps/backend/tests/extraction/test_extraction.py::test_consistent_chain",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.2",
            "Test inconsistent chain scores 0",
            "apps/backend/tests/extraction/test_extraction.py::test_inconsistent_chain",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.3",
            "Test single transaction",
            "apps/backend/tests/extraction/test_extraction.py::test_single_txn",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.4",
            "Test no balance after",
            "apps/backend/tests/extraction/test_extraction.py::test_no_balance_after",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.5",
            "Test empty list",
            "apps/backend/tests/extraction/test_extraction.py::test_empty_list",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.6",
            "Test partial consistency",
            "apps/backend/tests/extraction/test_extraction.py::test_partial_consistency",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.7",
            "Test all currencies match",
            "apps/backend/tests/extraction/test_extraction.py::test_all_match_header",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.8",
            "Test no currencies match",
            "apps/backend/tests/extraction/test_extraction.py::test_none_match",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.9",
            "Test no header currency",
            "apps/backend/tests/extraction/test_extraction.py::test_no_header_uses_most_common",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.10",
            "Test no currencies in transactions",
            "apps/backend/tests/extraction/test_extraction.py::test_no_currencies",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.11",
            "Test empty list (currency)",
            "apps/backend/tests/extraction/test_extraction.py::test_empty_list",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.12",
            "Test mixed currencies partial",
            "apps/backend/tests/extraction/test_extraction.py::test_mixed_currencies_partial",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.108.13",
            "Test missing currencies penalized",
            "apps/backend/tests/extraction/test_extraction.py::test_missing_currencies_penalized",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.109.1",
            "Test full score with all factors",
            "apps/backend/tests/extraction/test_extraction.py::test_full_score_with_all_factors",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.109.2",
            "Test no new factors caps at 85",
            "apps/backend/tests/extraction/test_extraction.py::test_no_new_factors_caps_at_85",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.115.1",
            "Brokerage statement with a single transaction is penalized below the review/auto-approve band",
            "apps/backend/tests/extraction/test_extraction.py::test_brokerage_single_txn_penalized",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.115.2",
            "Brokerage statement with a plausible transaction count is not penalized",
            "apps/backend/tests/extraction/test_extraction.py::test_brokerage_sufficient_txns_not_penalized",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.115.3",
            "Non-brokerage (bank) statement with one transaction keeps its existing score",
            "apps/backend/tests/extraction/test_extraction.py::test_bank_single_txn_not_penalized",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.115.4",
            "`is_brokerage` defaults to False so existing callers are unaffected",
            "apps/backend/tests/extraction/test_extraction.py::test_default_is_not_brokerage",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.115.5",
            "The cap uses the persisted transaction count (after skipped rows), not the raw extracted count",
            "apps/backend/tests/extraction/test_extraction.py::test_effective_count_uses_persisted_not_extracted",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.118.1",
            "The vision model list appends `VISION_FALLBACK_MODELS` after the primary OCR/vision model, deduplicated and order-preserving, so more than one model is attempted on the vision path",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_extract_financial_data_shared_ocr_vision_skips_layout_parser",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.118.2",
            "When the primary vision model raises a non-retryable provider error (e.g. a 400), the vision path attempts the configured vision fallback model and succeeds instead of failing the upload",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_vision_path_falls_back_to_secondary_model_on_non_retryable_error",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.119.1",
            "Common non-ISO date formats parse; empty/garbage return None",
            "apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_1_tolerant_parse_date_accepts_non_iso_formats",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.119.2",
            "A Chinese-format statement parses instead of being rejected",
            "apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_2_chinese_format_statement_parses_instead_of_aborting",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.119.3",
            "Unparseable transaction dates are explicitly quarantined; a partial transaction set cannot become trusted source truth",
            "apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_3_one_bad_row_date_is_quarantined",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.119.4",
            "The model is the primary date normalizer: the prompt instructs converting any source format to ISO YYYY-MM-DD (parser is only a fallback)",
            "apps/backend/tests/extraction/test_tolerant_date_parsing.py::test_AC13_19_4_parsing_prompt_instructs_iso_date_normalization",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.1",
            "A markdown json-fenced object (multi-line and single-line) is recovered",
            "apps/backend/tests/extraction/test_json_repair.py::test_strips_json_code_fence",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.2",
            "Surrounding prose and a bare fence reduce to the outermost balanced object",
            "apps/backend/tests/extraction/test_json_repair.py::test_strips_bare_code_fence_and_prose",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.3",
            "An already-clean object round-trips unchanged",
            "apps/backend/tests/extraction/test_json_repair.py::test_clean_object_is_preserved",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.4",
            "Content with no recoverable JSON object returns None; braces inside strings do not truncate",
            "apps/backend/tests/extraction/test_json_repair.py::test_unrecoverable_returns_none",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.5",
            "The extraction loop salvages a fenced response instead of rejecting the upload",
            "apps/backend/tests/extraction/test_json_repair.py::test_fenced_response_is_salvaged",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.6",
            "A response with no recoverable JSON still fails through the model-chain path",
            "apps/backend/tests/extraction/test_json_repair.py::test_unrecoverable_response_still_fails",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.7",
            "When a small example object precedes the real (larger) extraction, the largest object is recovered (not the example)",
            "apps/backend/tests/extraction/test_json_repair.py::test_prefers_largest_object_when_example_precedes_real",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.8",
            "A complete object followed by trailing unbalanced-brace junk still recovers the complete object",
            "apps/backend/tests/extraction/test_json_repair.py::test_complete_object_then_trailing_unbalanced_brace",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.114.9",
            "A leading unmatched brace (junk) before the real object does not stop the scan — the real object is recovered",
            "apps/backend/tests/extraction/test_json_repair.py::test_leading_unbalanced_brace_then_real_object",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.1",
            "Source type stamped on manual entry creation",
            "apps/backend/tests/reconciliation/test_source_type.py::test_source_type_stamped_on_create",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.2",
            "Auto-match records trusted anchor without mutating posted source_type",
            "apps/backend/tests/reconciliation/test_source_type.py::test_auto_match_records_anchor_without_mutating_posted_source_type",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.3",
            "Stage-1 approval preserves AUTO_PARSED provenance and never manufactures USER_CONFIRMED trust; later reviewed reconciliation is the only source-type promotion boundary.",
            "apps/backend/tests/extraction/test_source_type_promotion.py::test_stage1_approve_preserves_auto_parsed_provenance",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.4",
            "Manual entry wins over auto_parsed in conflict",
            "apps/backend/tests/infra/test_migrations.py::test_AC13_10_4_source_type_migration_handles_missing_legacy_enum_label",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.5",
            "source_type cannot be downgraded",
            "apps/backend/tests/reconciliation/test_source_type.py::test_source_type_no_downgrade",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.110.6",
            "The manual journal API rejects caller-selected source_type values",
            "apps/backend/tests/reconciliation/test_source_type.py::test_public_journal_api_rejects_caller_selected_source_type",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.112.1",
            "The canonical SourceCapability registry contains exactly one semantic entry for every product source class and contains no testing paths",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_source_capability_1_declares_semantics_not_test_paths",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.112.2",
            "Every supported automated SourceCapability resolves to both deterministic PR proof and release-validation proof",
            "tests/tooling/test_source_capability_proof.py::test_AC_extraction_112_2_supported_capabilities_require_release_proof",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.112.3",
            "A gap SourceCapability cannot be claimed as covered by the positive semantic proof graph",
            "tests/tooling/test_source_capability_proof.py::test_AC_extraction_112_3_gap_capabilities_cannot_claim_proof",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.111.1",
            "Dual-write handles a duplicate document identity by selecting and continuing with the canonical database winner without failing or duplicating the source row.",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_dual_write_layer2_integrity_error_is_non_fatal",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.111.2",
            "Malformed transaction source lineage requires review rather than unproven identity adoption.",
            "apps/backend/tests/extraction/test_deduplication.py::test_upsert_atomic_transaction_handles_non_list_source_documents",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.113.1",
            "Pure scoring + routing functions return identical results across N runs on the same input.",
            "apps/backend/tests/extraction/test_extraction_determinism.py::test_scoring_and_routing_are_deterministic",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.113.2",
            "Re-parsing identical model output yields identical confidence/status/validation_error across N parses.",
            "apps/backend/tests/extraction/test_extraction_determinism.py::test_repeated_parse_yields_identical_confidence_status_validation",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.113.3",
            "Each payload class (bank-valid, bank-balance-invalid, brokerage) routes consistently across N parses.",
            "apps/backend/tests/extraction/test_extraction_determinism.py::test_routing_is_consistent_per_payload_class",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.121.1",
            "`route_by_threshold` routes a balance-invalid bank statement to `PARSED` (review), never `uploaded`, regardless of score.",
            "apps/backend/tests/accounting/test_validation.py::test_AC13_21_1_balance_invalid_routes_to_parsed_review",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.121.2",
            "_Superseded by AC-extraction.2009.2 (#1352)._ A parsed bank statement that fails balance reconciliation is now BLOCKING: it is quarantined to `REJECTED` (not `PARSED`/review) with `stage1_status=REJECTED` and a typed `validation_error` reason code.",
            "apps/backend/tests/extraction/test_extraction_determinism.py::test_AC20_9_2_balance_invalid_parse_is_quarantined",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.121.3",
            "The retry endpoint accepts a balance-invalid statement at its `PARSED` resting state.",
            "apps/backend/tests/api/test_statements_router.py::test_AC13_21_3_retry_accepts_parsed_resting_state",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.121.5",
            "_Superseded by AC-extraction.2009.2 (#1352)._ The same balance-mismatch payload routes deterministically across N parses to the same status — now `REJECTED` (the LLM-LED blocking gate), not `PARSED`.",
            "apps/backend/tests/extraction/test_extraction_determinism.py::test_routing_is_consistent_per_payload_class",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.121.6",
            "CSV upload with a missing institution fails synchronously with HTTP 400 and an actionable message.",
            "apps/backend/tests/api/test_statements_router.py::test_AC13_21_6_csv_missing_institution_rejected_sync",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.122.1",
            "Two distinct same-date/same-amount/same-direction rows sharing one running `balance_after` hash differently within one document (via `occurrence_index`), while a re-uploaded identical row still collapses across documents.",
            "apps/backend/tests/extraction/test_deduplication.py::test_AC13_22_1_same_balance_distinct_rows_do_not_collapse",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.122.2",
            "A parsed statement with two same-date/same-amount deposits separated by a carried-forward/brought-forward balance repeat persists both deposits and the running-balance chain reconciles.",
            "apps/backend/tests/extraction/test_dual_write_layer2.py::test_AC13_22_2_page_boundary_duplicate_deposit_survives",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.116.1",
            "A provided seed is forwarded in the streaming request payload",
            "apps/backend/tests/ai/test_ai_streaming.py::test_stream_ai_json_forwards_zai_knobs_and_seed",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.116.2",
            "Extraction forwards the configured `ai_json_seed` to the model call",
            "apps/backend/tests/extraction/test_seed_determinism.py::test_extraction_forwards_configured_seed",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.116.3",
            "Extraction pins `temperature=0` / `do_sample=False` alongside the seed",
            "apps/backend/tests/extraction/test_seed_determinism.py::test_extraction_decoding_is_deterministic_by_default",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.116.4",
            "Empty `AI_JSON_SEED` parses as None (omitted) instead of raising",
            "apps/backend/tests/extraction/test_seed_determinism.py::test_empty_seed_env_is_treated_as_none",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.116.5",
            "The seed is off (None) by default so it is never sent to providers that reject it (e.g. glm-4.6v)",
            "apps/backend/tests/extraction/test_seed_determinism.py::test_seed_is_off_by_default",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.1",
            "A reconciling first parse is returned without retry",
            "apps/backend/tests/extraction/test_self_consistency.py::test_reconciles_first_attempt_single_call",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.2",
            "A failing parse is retried and the reconciling result wins",
            "apps/backend/tests/extraction/test_self_consistency.py::test_retries_until_reconciles",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.3",
            "When no attempt reconciles, the smallest-difference result is kept",
            "apps/backend/tests/extraction/test_self_consistency.py::test_keeps_best_when_none_reconcile",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.4",
            "Brokerage payloads are not retried",
            "apps/backend/tests/extraction/test_self_consistency.py::test_brokerage_is_not_retried",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.5",
            "Attempt 0 uses the configured seed; retries vary it (seed+1, seed+2 …)",
            "apps/backend/tests/extraction/test_self_consistency.py::test_seed_varies_per_attempt",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.6",
            "`AI_EXTRACT_MAX_ATTEMPTS=1` keeps single-shot behavior",
            "apps/backend/tests/extraction/test_self_consistency.py::test_max_attempts_one_disables_retry",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.7",
            'A structurally-invalid parse (balance uncomputable, difference 0) does not win "best" over a numerically-close parse',
            "apps/backend/tests/extraction/test_self_consistency.py::test_structurally_invalid_parse_does_not_win_as_best",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.8",
            "If every attempt is structurally invalid, the last parse is returned so `parse_document` reports the failure",
            "apps/backend/tests/extraction/test_self_consistency.py::test_all_invalid_returns_last_parse",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.9",
            "A transient extraction error on a retry attempt keeps the earlier usable parse (no upload regression)",
            "apps/backend/tests/extraction/test_self_consistency.py::test_transient_retry_error_keeps_earlier_usable_parse",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.10",
            "If every attempt raises, the error propagates so the upload fails as in the single-call path",
            "apps/backend/tests/extraction/test_self_consistency.py::test_all_attempts_error_reraises",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.11",
            "A transient error on the first attempt does not abort; a later reconciling attempt is returned",
            "apps/backend/tests/extraction/test_self_consistency.py::test_first_attempt_error_then_success_recovers",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.117.12",
            "An error after an earlier usable parse keeps trying remaining attempts; a later reconciling parse still wins",
            "apps/backend/tests/extraction/test_self_consistency.py::test_error_mid_run_does_not_skip_remaining_attempts",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.1",
            "AC-C1: detector pinpoints the exact break index on a crafted chain with a dropped row",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_1_detector_finds_break_index_on_dropped_row",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.2",
            "AC-C1: a clean running-balance chain reports no break",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_2_clean_chain_reports_no_break",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.3",
            "AC-C1: detection is Decimal-based and tolerant within `BALANCE_TOLERANCE` (no float drift)",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_3_detector_is_decimal_tolerant",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.4",
            "AC-C2: on balance mismatch with a detected break, the repair hook is invoked exactly once",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_4_repair_hook_invoked_once_on_mismatch",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.5",
            "AC-C2: a clean/reconciling chain never invokes the repair hook",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_5_repair_hook_not_invoked_on_clean_chain",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.6",
            "AC-C2: when no repair backend is injected, the hook is a safe no-op returning the original payload",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_6_repair_is_safe_noop_without_backend",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.7",
            "AC-C3: the synthetic dropped-row fixture drives the detector to the correct index and triggers the repair hook",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_7_regression_fixture_detects_and_repairs",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.120.8",
            "AC-C3: the clean-bank dropped-row regression-corpus fixture triggers the chain-break detector + `repair_under_extraction` end-to-end through `ExtractionService._extract_with_balance_retry` with an injected `RegionReExtractor` (recall stays a soft metric)",
            "apps/backend/tests/extraction/test_chain_break_repair.py::test_AC13_20_8_corpus_fixture_triggers_repair_end_to_end",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.123.1",
            "User deletion is refused with HTTP 409 (actionable message) while the user has a statement in the `PARSING` (in-flight) state; with no in-flight parse the delete still succeeds (204)",
            "apps/backend/tests/api/test_users_router.py::test_AC13_23_1_delete_user_with_in_flight_parse_returns_409",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.123.2",
            "Parse-failure lineage write re-checks user existence and skips the FK-violating insert (no `IntegrityError`) when the owning user is gone",
            "apps/backend/tests/extraction/test_parse_user_deletion_lifecycle.py::test_AC13_23_2_failed_lineage_skips_when_user_deleted",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.123.3",
            "The failure handler rolls back before reading ORM attributes (cached `statement_id`); the original error is preserved/logged and never masked by `PendingRollbackError`",
            "apps/backend/tests/extraction/test_parse_user_deletion_lifecycle.py::test_AC13_23_3_failure_handler_rolls_back_before_reading_orm",
            proof_kind="property",
        ),
        # AC-extraction.* migrated from EPIC-011 groups 11.13, 11.15 (#1419-pattern AC move).
        ac(
            "AC-extraction.212.1",
            "Re-applying the same rule version to the same atomic transaction is idempotent and returns the existing classification without inserting duplicates. Was EPIC-011 AC11.12.1.",
            "apps/backend/tests/extraction/test_classification_service.py::test_apply_rules_is_idempotent_for_existing_transaction_rule_version",
        ),
        ac(
            "AC-extraction.213.1",
            "Parsing populates Layer 1/2 by default, without any feature-flag override. Was EPIC-011 AC11.13.1.",
            "apps/backend/tests/extraction/test_dual_write_layer2.py::test_dual_write_enabled_by_default",
        ),
        ac(
            "AC-extraction.215.3",
            "Custody account resolves from a Layer-2 atomic transaction via the conform (DWD-native). Was EPIC-011 AC11.15.3.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_custody_account_from_atomic_txn",
        ),
        ac(
            "AC-extraction.215.4",
            "The resolver returns None when the source statement has no confirmed custody account. Was EPIC-011 AC11.15.4.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_returns_none_without_account",
        ),
        ac(
            "AC-extraction.215.5",
            "The resolver normalizes a {'documents': [...]} source-documents wrapper. Was EPIC-011 AC11.15.5.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_handles_dict_wrapper_source_documents",
        ),
        ac(
            "AC-extraction.215.6",
            "The resolver skips junk entries, non-bank-statement sources, and invalid UUIDs. Was EPIC-011 AC11.15.6.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_ignores_invalid_and_non_bank_sources",
        ),
        ac(
            "AC-extraction.215.7",
            "A non-list/non-dict source_documents value resolves to None. Was EPIC-011 AC11.15.7.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_returns_none_for_non_list_source_documents",
        ),
        ac(
            "AC-extraction.215.8",
            "The first source document (in order) with a confirmed account wins. Was EPIC-011 AC11.15.8.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_preserves_source_document_order",
        ),
        ac(
            "AC-extraction.215.9",
            "A known source document with no confirmed custody account resolves to None. Was EPIC-011 AC11.15.9.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_resolve_returns_none_when_no_source_has_account",
        ),
        # AC-extraction.* migrated from EPIC-017 groups 17.32 (#1419-pattern AC move).
        ac(
            "AC-extraction.332.1",
            "Brokerage positions CSV is mapped into a positions payload (not a bank parse failure) so it reaches the brokerage import path. Was EPIC-017 AC17.32.1.",
            "apps/backend/tests/extraction/test_brokerage_csv_routing.py::test_AC17_32_1_brokerage_positions_csv_produces_positions_payload",
            priority="P1",
        ),
        ac(
            "AC-extraction.332.2",
            "Brokerage trade-history CSV raises an actionable unsupported- document error, not the generic bank 'No valid transactions' failure. Was EPIC-017 AC17.32.2.",
            "apps/backend/tests/extraction/test_brokerage_csv_routing.py::test_AC17_32_2_brokerage_trade_history_csv_raises_actionable_error",
            priority="P1",
        ),
        ac(
            "AC-extraction.332.3",
            "Bank transaction CSV parsing is unaffected by brokerage CSV detection (no regression). Was EPIC-017 AC17.32.3.",
            "apps/backend/tests/extraction/test_brokerage_csv_routing.py::test_AC17_32_3_bank_csv_unaffected_by_brokerage_detection",
            priority="P1",
        ),
        # Row-level moves out of mixed EPIC groups (per-EPIC hundred-block
        # ids: EPIC-004->4xx, EPIC-008->8xx, EPIC-011->2xx, EPIC-016->16xx,
        # EPIC-017->3xx, EPIC-020->20xx; seq preserved).
        ac(
            "AC-extraction.406.8",
            "AtomicTransaction persists the extracted balance_after so the conflict guard can disambiguate distinct-but-identical transactions. Was EPIC-004 AC4.6.8.",
            "apps/backend/tests/extraction/test_deduplication.py::test_upsert_persists_balance_after",
            priority="P1",
        ),
        ac(
            "AC-extraction.407.2",
            "get_few_shot_examples respects default limit and caches results. Was EPIC-004 AC4.7.2.",
            "apps/backend/tests/extraction/test_correction_service_cache.py::test_get_few_shot_examples_cache_hit_and_limit",
            priority="P1",
        ),
        ac(
            "AC-extraction.413.6",
            "currency_balances JSONB persists a per-currency balance array additively to the scalar columns. Was EPIC-004 AC4.13.6.",
            "apps/backend/tests/extraction/test_statement_summary_conform.py::test_AC1_currency_balances_jsonb_round_trips",
            priority="P1",
        ),
        ac(
            "AC-extraction.812.6",
            "OCR/vision provider fallback, timeout, and empty-response errors are deterministic. Was EPIC-008 AC8.12.6.",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_extract_financial_data_shared_ocr_vision_skips_layout_parser",
            priority="P1",
        ),
        ac(
            "AC-extraction.812.4",
            "PDF with private URL logs warning and raises ExtractionError (lines 393->403, 416->426). Was EPIC-008 AC8.12.4.",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_extract_financial_data_pdf_private_url_raises",
            priority="P1",
        ),
        ac(
            "AC-extraction.812.5",
            "Image with private URL logs warning and raises ExtractionError (else branch 416->426). Was EPIC-008 AC8.12.5.",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_extract_financial_data_image_private_url_raises",
            priority="P1",
        ),
        ac(
            "AC-extraction.813.10",
            "Multi-brokerage PDF upload → position import → latest portfolio value, with value consistency asserted (#1826 G-value-oracle): every imported holding carries a positive quantity and market value, and the balance sheet's market-valuation lines cover the holdings' total market value. The generated PDFs randomize amounts, so the exact-Decimal oracle for this proof lives in the blocking twin (AC-portfolio.valuation.1). Was EPIC-008 AC8.13.10.",
            "tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.813.11",
            "A DBS bank statement PDF's full browser journey: upload with an explicit OCR model selection, poll until parsed (failing/skipping on a rejected AI/OCR status rather than hanging), the detail page shows transactions, Start Review -> Approve transitions the statement to approved, and the journey grades extraction against the committed fixture's ground truth (#1826 G-value-oracle): opening/closing balances equal the expected-JSON values exactly, and after the guided opening-balance flow the balance sheet reports the ACTUAL closing balance, not the period's net flow. Was EPIC-008 AC8.13.1-.5 / .7 (migration closeout wave 3, #1663).",
            "tests/e2e/test_bench_v2_ui_golden_paths.py::test_case_1_four_month_rollforward_ui",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.813.12",
            "A statement upload's full browser journey (institution name + explicit model selection + PDF upload) returns a 2xx with an id, the row appears in the statement list, and the statement is immediately fetchable via the API in a valid status (never silently rejected without a gate check). Was EPIC-008 AC8.13.8 (migration closeout wave 3, #1663).",
            "tests/e2e/test_accounts_and_statements_ui_journey.py::test_statement_detail_and_review_surface",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.216.1",
            "Distinct running balances hash differently; identical/absent balances collapse. Was EPIC-011 AC11.16.1.",
            "apps/backend/tests/extraction/test_deduplication.py::test_running_balance_distinguishes_identical_transactions",
        ),
        ac(
            "AC-extraction.1622.8",
            "A statement routed to parsed/review carries stage1_status = pending_review explicitly (never NULL). Was EPIC-016 AC16.22.8.",
            "apps/backend/tests/extraction/test_extraction_flow.py::test_parsed_statement_sets_stage1_pending_review",
            priority="P1",
        ),
        ac(
            "AC-extraction.1622.9",
            "UploadedDocument.status advances to completed once a successful parse is persisted (no longer stuck at uploaded). Was EPIC-016 AC16.22.9.",
            "apps/backend/tests/extraction/test_dual_write_layer2.py::test_dual_write_marks_document_completed",
            priority="P1",
        ),
        ac(
            "AC-extraction.1622.10",
            "A hard parse failure persists an UploadedDocument (status failed) so the uploaded raw file stays traceable from the rejected statement. Was EPIC-016 AC16.22.10.",
            "apps/backend/tests/extraction/test_extraction_error_paths.py::test_handle_parse_failure_persists_failed_document_lineage",
            priority="P1",
        ),
        ac(
            "AC-extraction.304.7",
            "Upload Parse-to-Import Bridge. Was EPIC-017 AC17.4.7.",
            "apps/backend/tests/extraction/test_statement_brokerage_import_bridge.py::test_parse_statement_background_imports_brokerage_positions",
        ),
        ac(
            "AC-extraction.304.9",
            "AC-B1 Producer routing: brokerage docs select the positions prompt before the model call (filename/institution), bank docs keep the bank prompt. Was EPIC-017 AC17.4.9.",
            "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py::test_AC_B1_looks_like_brokerage_document_routes_by_filename_and_institution",
        ),
        ac(
            "AC-extraction.304.10",
            "AC-B2 Brokerage positions output schema flows into AtomicPosition-ready snapshots via the existing consumer parser. Was EPIC-017 AC17.4.10.",
            "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py::test_AC_B2_positions_prompt_payload_is_understood_by_consumer_parser",
        ),
        ac(
            "AC-extraction.304.11",
            "AC-B5 Zero-position brokerage doc is surfaced as a visible review flag (stage1 pending-review + note). Was EPIC-017 AC17.4.11.",
            "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py::test_AC_B5_zero_position_brokerage_doc_raises_visible_review_flag",
            priority="P1",
        ),
        ac(
            "AC-extraction.304.12",
            "AC-B4/B6 Moomoo holdings TABLE extracts and imports: AtomicPosition rows == table rows with exact market_value (#1088). Was EPIC-017 AC17.4.12.",
            "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py::test_AC_B4_AC_B6_moomoo_positions_table_extracts_and_imports",
        ),
        ac(
            "AC-extraction.304.13",
            "AC-B3 A multi-currency brokerage position snapshot never fabricates opening/closing cash balances from position market values or cross-sums currencies; a per-currency balance array is persisted only when the source declares exact balance facts (#1139). Was EPIC-017 AC17.4.13.",
            "apps/backend/tests/extraction/test_brokerage_position_extraction_wiring.py::test_AC_B3_multi_currency_brokerage_does_not_fabricate_cash_balances",
        ),
        ac(
            "AC-extraction.2009.2",
            "LLM-LED tier (event→L2) balance-chain failure is a BLOCKING runtime gate: a bank-statement extraction whose chain does not reconcile (opening + ΣIN − ΣOUT ≠ closing beyond the Decimal tolerance) is quarantined to the rejected terminal state with a typed reason code and never reaches parsed/trusted report-input state; code may reject, never author. Was EPIC-020 AC20.9.2.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_2_imbalanced_bank_extraction_is_quarantined_not_parsed",
        ),
        ac(
            "AC-extraction.2009.3",
            "LLM-LED tier dedup-conservation failure is an INDEPENDENT blocking gate: a within-document dedup collapse (post-dedup row count ≠ conserved pre-dedup count) quarantines the extraction with a reason code DISTINCT from the balance-chain reason. Was EPIC-020 AC20.9.3.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_3_within_doc_dedup_collapse_is_quarantined",
        ),
        ac(
            "AC-extraction.2009.4",
            "LLM-LED tier gate is fail-closed without inventing source facts: an explicitly missing bank opening/closing balance is retained only as a review-required result, never zero-filled or promoted; an unevaluable asserted invariant still has a typed pure-gate quarantine path. Was EPIC-020 AC20.9.4.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_4_declared_missing_balance_is_review_only",
        ),
        ac(
            "AC-extraction.2009.5",
            "The prior 'imbalanced bank statement → parsed/review' behavior no longer exists: routing a true balance-chain failure no longer returns parsed. Was EPIC-020 AC20.9.5.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_5_imbalanced_no_longer_routes_to_parsed_review",
        ),
        ac(
            "AC-extraction.2009.6",
            "No false reject: a balanced, dedup-consistent bank-statement extraction still flows through to its prior parsed/approved resting state unchanged by the gate. Was EPIC-020 AC20.9.6.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_6_valid_extraction_passes_gate_unchanged",
        ),
        ac(
            "AC-extraction.2009.7",
            "Each LLM-LED gate failure mode emits a distinct structured reason code and a distinct PII-free metric kind (balance vs dedup vs unevaluable), with no institution name or account identifier in the signal. Was EPIC-020 AC20.9.7.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_7_each_failure_mode_has_distinct_reason_and_metric",
        ),
        ac(
            "AC-extraction.2009.8",
            "A db-backed quarantine persists the terminal `rejected` status to the statement row, writing no Layer-2 financial rows, instead of leaving an upload stuck in `parsing`. Was EPIC-020 AC20.9.8.",
            "apps/backend/tests/llm/test_llm_led_blocking_gate.py::test_AC20_9_8_quarantined_statement_persists_rejected_not_stuck_parsing",
        ),
        ac(
            "AC-extraction.2502.1",
            "`approve_statement_workflow` / `reject_statement_workflow` (`src.extraction.extension.statement_workflow`) own the ordered transition -> side-effect -> commit sequence as one unit (approve: transition, auto-post, commit; reject: transition, commit, refresh), and the statements router delegates to these workflow functions directly instead of inlining approve/reject + commit. Was EPIC-025 AC25.2.1.",
            "apps/backend/tests/api/test_statement_workflow_service.py::test_statement_workflow_service",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-review.1",
            "get_pending_stage1_review returns an empty list for a user with no pending-review statements. Was EPIC-001 AC1.6.2 (migration closeout wave 3, #1663).",
            "apps/backend/tests/review/test_statement_validation.py::test_returns_empty_when_none_pending",
            priority="P1",
        ),
        # ── group 1807: Evidence Graph foundation — nodes, edges, upsert,
        # bounded traversal (was EPIC-018 AC18.7.1-7, migration closeout
        # continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1807.1",
            "The Evidence Graph SSOT defines nodes as auditable states, edges as transformation processes, allowed foundation node/edge fields, traversal direction, and append-only edge rules.",
            "apps/backend/tests/infra/test_evidence_lineage_contract.py::test_AC18_7_1_evidence_lineage_ssot_defines_graph_semantics",
            priority="P1",
        ),
        ac(
            "AC-extraction.1807.2",
            "The Alembic migration creates evidence_nodes and evidence_edges with user-scoped entity lookup and edge traversal indexes.",
            "apps/backend/tests/infra/test_evidence_lineage_migration_contract.py::test_AC18_7_2_evidence_lineage_migration_creates_tables_and_indexes",
            priority="P1",
        ),
        ac(
            "AC-extraction.1807.3",
            "SQLAlchemy models expose EvidenceNode and EvidenceEdge with JSONB properties and user-owned isolation.",
            "apps/backend/tests/infra/test_evidence_lineage_contract.py::test_AC18_7_3_evidence_lineage_models_expose_jsonb_user_owned_graph_tables",
            priority="P1",
        ),
        ac(
            "AC-extraction.1807.4",
            "The evidence lineage service supports idempotent node and edge upsert keyed by user, entity identity, node kind, relation, and edge endpoints.",
            "apps/backend/tests/extraction/test_evidence_lineage.py::test_AC18_7_4_node_and_edge_upserts_are_idempotent",
            priority="P1",
        ),
        ac(
            "AC-extraction.1807.5",
            "The evidence lineage service resolves entity nodes and traverses upstream and downstream paths only within the authenticated user's scope.",
            "apps/backend/tests/extraction/test_evidence_lineage.py::test_AC18_7_5_traversal_resolves_upstream_and_downstream_by_entity",
        ),
        ac(
            "AC-extraction.1807.6",
            "Evidence lineage traversal enforces a default maximum depth and never walks unbounded graphs.",
            "apps/backend/tests/extraction/test_evidence_lineage.py::test_AC18_7_6_traversal_enforces_depth_limit",
            priority="P1",
        ),
        ac(
            "AC-extraction.1807.7",
            "Evidence Graph foundation tests cover node creation, edge creation, duplicate upsert behavior, upstream traversal, downstream traversal, depth limit, and cross-user isolation.",
            "apps/backend/tests/extraction/test_evidence_lineage.py::test_AC18_7_5_cross_user_edges_and_traversal_are_blocked",
        ),
        # ── group 1808: Evidence Graph source-to-report integration (was
        # EPIC-018 AC18.8.1-7, migration closeout continuation, #1663 /
        # #1715) ──
        ac(
            "AC-extraction.1808.1",
            "Statement upload creates a source_document node for the uploaded source (uploaded_document); the legacy extracted_record middle node was removed in EPIC-011 Stage 3 with the bank_statements tables.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_4_direct_entity_materialization_branches_are_idempotent",
            priority="P1",
        ),
        ac(
            "AC-extraction.1808.2",
            "Layer 2 lineage creates atomic_fact nodes for atomic transactions and deduped_into edges from the source_document (uploaded document) that produced them.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_4_direct_entity_materialization_branches_are_idempotent",
            priority="P1",
        ),
        ac(
            "AC-extraction.1808.3",
            "Journal posting creates ledger_entry and ledger_line nodes, links extracted or atomic transaction facts to the ledger entry with posted_as, and links the ledger entry to its lines with contains.",
            "apps/backend/tests/api/test_statements_router.py::test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph",
            priority="P1",
        ),
        ac(
            "AC-extraction.1808.4",
            "Package traceability preserves the reviewed source decision through the ledger DecisionAnchor graph and never reconstructs extraction identity from source_id.",
            "apps/backend/tests/api/test_personal_report_package_contract.py::test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary",
            priority="P1",
        ),
        ac(
            "AC-extraction.1808.5",
            "Unknown or unsupported JournalEntry.source_id values produce explicit blocker codes and never fabricate statement, atomic, or document anchors.",
            "apps/backend/tests/api/test_personal_report_package_contract.py::test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions",
        ),
        ac(
            "AC-extraction.1808.6",
            "Existing JournalEntry.source_type/source_id semantics remain backward-compatible while Evidence Graph writes add supplemental audit lineage.",
            "apps/backend/tests/api/test_statements_router.py::test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph",
            priority="P1",
        ),
        ac(
            "AC-extraction.1808.7",
            "Tests cover source downstream impact, reviewed transaction to ledger decision ancestry, and report display without a shadow source-identity resolver.",
            "apps/backend/tests/api/test_personal_report_package_contract.py::test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary",
            priority="P1",
        ),
        # ── group 1809: Evidence Graph navigation UX — backend API contract
        # (was EPIC-018 AC18.9.1-3, migration closeout continuation, #1663 /
        # #1715). AC18.9.4-6 (frontend lineage panel) stay in EPIC-018 —
        # extraction is a backend-only package (fe=None). ──
        ac(
            "AC-extraction.1809.1",
            "An authenticated Evidence Graph lineage API resolves an owned graph node by entity_type, entity_id, and optional node_kind.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions",
            priority="P1",
        ),
        ac(
            "AC-extraction.1809.2",
            "The lineage API supports upstream, downstream, and both-direction traversal with bounded depth and returns stable node and edge DTOs.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions",
            priority="P1",
        ),
        ac(
            "AC-extraction.1809.3",
            "Missing, unsupported, or cross-user entity identities return explicit empty/blocker state and never fabricate source, ledger, or report anchors.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_9_3_lineage_api_returns_blocker_for_missing_or_cross_user_anchor",
        ),
        # ── group 1810: Evidence Graph lazy materialization and consistency
        # guardrails (was EPIC-018 AC18.10.1-7, migration closeout
        # continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1810.1",
            "The Evidence Graph SSOT defines the graph as an audit projection, business tables as source of truth, and a blocker taxonomy for drift states.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_5_detector_reports_missing_orphan_and_cross_user_drift",
            priority="P1",
        ),
        ac(
            "AC-extraction.1810.2",
            "New source-to-ledger workflows materialize graph nodes and edges in the same database transaction as their owning business facts.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_2_graph_writes_share_the_business_transaction",
            priority="P1",
        ),
        ac(
            "AC-extraction.1810.3",
            "The lineage API attempts one bounded deterministic materialization pass when an owned anchor or required local path is missing for historical data.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_10_3_AC18_10_4_lineage_api_lazily_materializes_historical_journal_line",
            priority="P1",
        ),
        ac(
            "AC-extraction.1810.4",
            "Lazy materialization is idempotent and only uses strong relationships such as owned source IDs, transaction lineage, and journal_line.journal_entry_id; it never infers links from fuzzy amount, date, or description similarity.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts",
        ),
        ac(
            "AC-extraction.1810.5",
            "An operator-safe dry-run detector reports missing graph nodes, graph nodes pointing to missing business entities, dangling edges, cross-user edges, incomplete lineage, and ambiguous or unsupported provenance.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_5_detector_reports_missing_orphan_and_cross_user_drift",
        ),
        ac(
            "AC-extraction.1810.6",
            "The detector and lazy repair never mutate accounting facts, report amounts, ledger balances, or legacy JournalEntry.source_type/source_id values.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts",
        ),
        ac(
            "AC-extraction.1810.7",
            "Tests cover request-time lazy repair, repeated-read idempotency, dry-run no-write behavior, cross-user blocking, unknown provenance blockers, dangling/orphan detection, and request-level write caps.",
            "apps/backend/tests/extraction/test_evidence_graph_materialization.py::test_AC18_10_7_materialization_caps_and_unknown_sources_return_blockers",
            priority="P1",
        ),
        # ── group 1831: Evidence Graph typed properties and fail-fast
        # materialization (was EPIC-018 AC18.31.1-2, migration closeout
        # continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1831.1",
            "Evidence Graph node and edge DTO properties are constrained by closed typed Pydantic models per node kind and edge relation (monetary amounts stay Decimal-as-string, never float), preserving the existing JSON shape and tolerating legacy/partial rows.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_31_1_node_properties_are_typed_and_round_trip",
            priority="P1",
        ),
        ac(
            "AC-extraction.1831.2",
            "A genuine materialization failure (cross-user, write-cap, or unsupported provenance) returns a non-2xx status with a structured EvidenceLineageError detail, while an absent anchor stays a 200 empty/blocker result.",
            "apps/backend/tests/api/test_evidence_lineage_router.py::test_AC18_31_2_failure_status_distinguishes_genuine_failure_from_empty",
        ),
        # ── group 1801: classification retirement — the pre-classify-node
        # rule matching path (was EPIC-018 AC18.1.3-4, migration closeout
        # continuation, #1663 / #1715). AC18.1.1 is already proven by
        # AC-extraction.104.1 (was AC13.4.1); AC18.1.2 stays dead/unverified
        # — the columns it describes were dropped by migration 0029
        # (bank_statement_transactions table removed), see the EPIC-018 doc
        # note. AC18.1.5/.6 are proven below (1801.3-5). ──
        ac(
            "AC-extraction.1801.1",
            "RuleType.ML_MODEL rule matching is RETIRED (EPIC #1483 cleanup) — even an active ML_MODEL rule never applies, since it read AI signals (suggested_category/category_confidence) that no producer ever wrote; it survives only as the classification-policy anchor row type for the classify node (AC18.15).",
            "apps/backend/tests/extraction/test_classification_service.py::test_AC18_1_3_ml_rule_matching_is_retired",
            priority="P1",
        ),
        ac(
            "AC-extraction.1801.2",
            "Classification priority is KEYWORD > REGEX; an absent classification supplies no posting command (the ML tier moved to the classify node, AC18.15).",
            "apps/backend/tests/extraction/test_classification_service.py::test_classification_priority_keyword_over_regex",
            priority="P1",
        ),
        ac(
            "AC-extraction.1801.3",
            "create_entry_from_txn reads the Layer-3 classification and requires its reviewed account and authoritative disposition command before it can create a statement entry.",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_uses_layer3_classification_account",
            priority="P1",
        ),
        ac(
            "AC-extraction.1801.4",
            "Without a Layer-3 classification and authoritative disposition, an outflow is routed to review and creates no ledger entry.",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_outflow_without_disposition_requires_review",
            priority="P1",
        ),
        ac(
            "AC-extraction.1801.5",
            "Without a Layer-3 classification and authoritative disposition, an inflow is routed to review and creates no ledger entry.",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_inflow_without_disposition_requires_review",
            priority="P1",
        ),
        # ── group classification-priority: descending rule-version priority
        # within the same rule type (was EPIC-011 AC11.12.2, second half —
        # the keyword>regex half of that row already lives at
        # AC-extraction.1801.2). Distinct from group 1801 since its legacy
        # home is EPIC-011, not EPIC-018. ──
        ac(
            "AC-extraction.classification-priority.1",
            "Among same-type rule matches, the newest rule version wins deterministically.",
            "apps/backend/tests/extraction/test_classification_service.py::test_same_type_rules_prefer_newer_version",
        ),
        # ── group 1802: correction feedback substrate — CorrectionLog,
        # stats, few-shot injection, cache (was EPIC-018 AC18.2.1-5,
        # migration closeout continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1802.1",
            "The CorrectionLog model records the original and corrected categories.",
            "apps/backend/tests/extraction/test_correction_service.py::test_record_correction_stores_corrected_category",
            priority="P1",
        ),
        ac(
            "AC-extraction.1802.2",
            "The corrections API records and retrieves correction stats, scoped to the owning user.",
            "apps/backend/tests/extraction/test_correction_service.py::test_AC18_2_2_record_correction_rejects_cross_user_corrected_account",
            priority="P1",
        ),
        ac(
            "AC-extraction.1802.3",
            "Few-shot examples from corrections are injected into the extraction prompt.",
            "apps/backend/tests/extraction/test_correction_service.py::test_prompt_injection_with_corrections",
            priority="P1",
        ),
        ac(
            "AC-extraction.1802.4",
            "The correction cache has a 1-hour TTL and also invalidates immediately after recording a new correction.",
            "apps/backend/tests/extraction/test_correction_service.py::test_few_shot_cache_invalidates",
            priority="P1",
        ),
        ac(
            "AC-extraction.1802.5",
            "top_corrections is typed as a TopCorrection Pydantic model in the corrections stats response, not a bare dict.",
            "apps/backend/tests/api/test_corrections_router.py::test_AC18_2_5_top_corrections_is_typed_pydantic_model",
            priority="P1",
        ),
        # ── group 1814: correction feedback loop — corpus derived from
        # CorrectionLog, replayed as priors (was EPIC-018 AC18.14.1-4,
        # migration closeout continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1814.1",
            "The correction corpus is derived from CorrectionLog (no sidecar), keyed by the transaction pattern, capturing proposed vs corrected.",
            "apps/backend/tests/extraction/test_correction_loop.py::test_AC18_14_1_corpus_is_derived_from_corrections_keyed_by_pattern",
            priority="P1",
        ),
        ac(
            "AC-extraction.1814.2",
            "Replaying the corpus as priors strictly lowers the held-out low-confidence proportion when correction patterns recur, and invents no reduction when they do not.",
            "apps/backend/tests/extraction/test_correction_loop.py::test_AC18_14_2_replay_lowers_low_confidence_proportion_when_patterns_recur",
            priority="P1",
        ),
        ac(
            "AC-extraction.1814.3",
            "The service builds the corpus from the persisted correction store, scoped to the user.",
            "apps/backend/tests/extraction/test_correction_loop.py::test_AC18_14_3_service_builds_corpus_from_persisted_corrections",
            priority="P1",
        ),
        ac(
            "AC-extraction.1814.4",
            "The service replays the live corpus and measures the held-out reduction: recurring correction patterns ground the held-out split so the measured low-confidence proportion provably drops.",
            "apps/backend/tests/extraction/test_correction_loop.py::test_AC18_14_4_service_replay_measures_held_out_reduction",
            priority="P1",
        ),
        # ── group 1815: transaction classify node — construct (was
        # EPIC-018 AC18.15.1-8, migration closeout continuation, #1663 /
        # #1715) ──
        ac(
            "AC-extraction.1815.1",
            "The classification policy is a versioned, effective-dated, immutable object: policy_for(as_of) head-selects the latest version whose effective_from <= as_of, and an effective version can never be mutated.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_1_policy_is_effective_dated_and_immutable",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.2",
            "The classify pass is reproducible: identical (transactions, policy, proposals) produce identical outcomes, each stamped with the policy version.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_2_classify_is_reproducible_for_same_inputs",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.3",
            "Model output is constrained to the policy's closed catalog: an off-catalog proposal is rejected, and the LLM boundary parses prompt-driven JSON with code-owned clamping and a graceful per-transaction None fallback.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_3_off_catalog_proposal_is_rejected_never_applied",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.4",
            "The confidence gate disposes deterministically: >= auto threshold becomes an APPLIED classification, the review band becomes a DRAFT visible to the ai_feedback 60-84 queue, and lower confidence writes no posting authority.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_4_confidence_gate_applies_reviews_or_tails",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.5",
            "The model never touches money: proposals cannot express an amount, the node imports no posting primitives, and transaction Decimal amounts pass through classification untouched.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_5_model_never_touches_money",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.6",
            "commit_basis=False computes verdicts under a candidate policy without writing the basis-of-record: no classifications, no policy rules, no accounts.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_6_pro_forma_writes_nothing",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.7",
            "A user's deterministic rule wins before the model is consulted, and having no rules is a no-op pre-pass, not an error.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_7_user_rule_prepass_wins_over_model",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1815.8",
            "enable_ai_classification controls only live model proposals. Reviewed deterministic rules still classify their matching transactions; unmatched transactions become explicit no-proposal review cases rather than receiving a fallback category. Its production consumers are exactly the posting path and the backfill/re-extract router.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_15_8_flag_off_skips_llm_not_deterministic_rules",
            priority="P1",
            proof_kind="property",
        ),
        # ── group 1816: transaction classification — migrate (was EPIC-018
        # AC18.16.1-5, migration closeout continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1816.1",
            "Publishing a new policy version leaves every already-covered period's as-reported income statement byte-identical: each transaction classifies under the policy in effect on its own txn_date, and a full recompute after publishing stays prospective.",
            "apps/backend/tests/extraction/test_classification_migration.py::test_AC18_16_1_new_policy_version_never_restates_covered_periods",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1816.2",
            "After a real statement import with the flag on, the income statement has reviewed categorized leaf lines, and the persisted classification records retain non-null model scores.",
            "apps/backend/tests/extraction/test_classification_migration.py::test_AC18_16_2_import_produces_categorized_income_statement",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1816.3",
            "With enable_ai_classification off and no matching reviewed rule, the import path writes zero classification rows and routes unknown economic meaning to review without ledger promotion.",
            "apps/backend/tests/extraction/test_classification_migration.py::test_AC18_16_3_flag_off_routes_unknown_meaning_to_review",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1816.4",
            "The one-time backfill classifies each not-yet-classified transaction once under its own effective policy; a re-run is a no-op (idempotent, dated, append-only).",
            "apps/backend/tests/extraction/test_classification_migration.py::test_AC18_16_4_backfill_is_idempotent_dated_append_only",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1816.5",
            "Re-running classification never rewrites posted journal entries or lines — the category is a projection over the immutable ledger, not an edit of it.",
            "apps/backend/tests/extraction/test_classification_migration.py::test_AC18_16_5_reclassification_never_rewrites_posted_entries",
            proof_kind="property",
        ),
        # ── group 1817: transaction classification — cleanup (was EPIC-018
        # AC18.17.1-3, migration closeout continuation, #1663 / #1715) ──
        ac(
            "AC-extraction.1817.1",
            "Every classification entry seam has a production call site and the core pass is wired to a live seam (AST gate) — a defined-but-uninvoked classify writer fails CI.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_17_1_no_classify_writer_is_defined_but_uninvoked",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1817.2",
            "POST /classifications/backfill classifies the caller's not-yet-classified transactions under each transaction's own effective policy, never duplicates or rewrites an existing classification on re-run, and is flag-gated (off => zero classifications).",
            "apps/backend/tests/api/test_classifications_router.py::test_AC18_17_2_backfill_endpoint_classifies_then_is_idempotent",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1817.3",
            "Reports consume exactly one classification source and only APPLIED rows — the DRAFT review band and SUPERSEDED history never leak into as-reported figures.",
            "apps/backend/tests/extraction/test_transaction_classification.py::test_AC18_17_3_reports_read_only_applied_classifications",
            proof_kind="property",
        ),
        # ── group 1779: journal-entry FX posting — lazy-load instead of
        # failing closed on a missing rate (#1779) ──
        ac(
            "AC-extraction.1779.1",
            "Journal-entry creation for a foreign-currency transaction resolves a missing FX rate through the same on-demand lazy-load chain (stored inverse -> USD-bridge derivation -> live provider fetch, persisted to fx_rates) that reporting and internal transfers already opt into via lazy_load=True, instead of failing closed immediately; it still fails closed with a clear error when even that chain cannot resolve a rate, since a posted entry cannot exist without one.",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_create_entry_from_txn_lazy_loads_missing_fx_rate",
            priority="P1",
            proof_kind="property",
        ),
        # ── group 804: Phase 3 statement import & parsing e2e journeys (was
        # EPIC-008 AC8.4.1-3, #1821 Wave A pending-package move) ──
        ac(
            "AC-extraction.804.1",
            "Statement upload (CSV) end-to-end journey.",
            "apps/backend/tests/extraction/test_statements_shift_left.py::test_statement_upload_csv_direct_parsing",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.804.2",
            "Statement list and get end-to-end journey.",
            "apps/backend/tests/extraction/test_statements_shift_left.py::test_statement_list_and_get_details",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.804.3",
            "Statement full flow (upload -> parse -> approve) end-to-end journey.",
            "apps/backend/tests/extraction/test_statements_shift_left.py::test_statement_full_approval_and_posting_flow",
            proof_kind="property",
        ),
        # ── group stage1-validation: Stage 1 statement review/approval
        # (src.extraction.extension.statement_validation), was EPIC-016
        # AC16.1.1/AC16.3.1-6/AC16.22.1/AC16.22.2/AC16.22.5-7 (#1821 Wave A
        # pending-package move). AC16.1.1 and AC16.22.5 both cited the same
        # tolerance test and are merged into .1; AC16.3.6 and AC16.22.6 both
        # cited the same ownership test and are merged into .7. AC16.3.5's
        # original wording ("edit_and_approve raises ValueError when balance
        # is still invalid after edits") was stale — the feature is now
        # unconditionally unsupported; .6 states the current behavior. The
        # EPIC's own test names for what are now .1 and .8 were also stale
        # (test_validate_balance_chain_within_tolerance() and
        # test_approve_statement_invalid_balance_fails do not exist); the real
        # test functions are cited below. ──
        ac(
            "AC-extraction.stage1-validation.1",
            "Stage 1 balance validation tolerance is 0.001 USD, not the looser 0.10 USD Stage 2 reconciliation-scoring tolerance.",
            "apps/backend/tests/review/test_statement_validation.py::test_within_tolerance",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.2",
            "validate_balance_chain raises ValueError when the statement is not found.",
            "apps/backend/tests/review/test_statement_validation.py::test_statement_not_found_raises",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.3",
            "_get_opening_balance falls back to the statement's own opening_balance when no previous statement exists.",
            "apps/backend/tests/review/test_statement_validation.py::test_opening_balance_from_statement_when_no_manual_no_prev",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.4",
            "_get_opening_balance uses the previous statement's closing_balance when one is available.",
            "apps/backend/tests/review/test_statement_validation.py::test_opening_balance_from_prev_statement",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.5",
            "reject_statement without a reason clears validation_error.",
            "apps/backend/tests/review/test_statement_validation.py::test_reject_without_reason",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.6",
            "edit_and_approve is unconditionally unsupported — Stage 1 correction only happens via reject + re-parse, never a partial field edit, regardless of the resulting balance.",
            "apps/backend/tests/review/test_statement_validation.py::test_edit_and_approve_is_unsupported",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.7",
            "Every service method that mutates a pending_review statement enforces user_id ownership (e.g. _get_statement_for_update raises ValueError for a mismatched user_id).",
            "apps/backend/tests/review/test_statement_validation.py::test_get_statement_for_update_wrong_user_raises",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.8",
            "A Stage 1 pending_review -> approved transition requires the balance delta to be <= 0.001 USD.",
            "apps/backend/tests/review/test_statement_validation.py::test_approve_with_invalid_balance_raises",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.9",
            "A Stage 1 pending_review -> rejected transition triggers re-parse.",
            "apps/backend/tests/api/test_statements_router.py::test_stage1_reject_triggers_reparse",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.stage1-validation.10",
            "Stage 1 approval tolerance and extraction/reconciliation scoring tolerance remain separate, intentionally documented policies.",
            "apps/backend/tests/review/test_tolerance_policy.py::test_ac16_22_7_tolerance_policy_constants_are_intentional",
            proof_kind="property",
        ),
        # ── group document-delivery: Stage 1 PDF preview presign/streaming
        # (was EPIC-016 AC16.33.4/AC16.33.5's backend half, #1821 Wave A
        # pending-package move; the frontend embedding half stays fe-only) ──
        ac(
            "AC-extraction.document-delivery.1",
            "Stage 1 statement review PDF previews use short-lived presigned URLs for sandboxed iframe embedding.",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_33_4_get_statement_for_review_uses_short_presign_ttl",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.document-delivery.2",
            "The Stage 1 PDF preview streams bytes same-origin via GET /api/statements/{id}/document for sandboxed blob: object URL embedding (backend half; also proven not-found -> 404 and storage-error -> 502 by test_AC16_33_5_get_statement_document_404_when_no_document / test_AC16_33_5_get_statement_document_storage_error_maps_to_502 in the same file).",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_33_5_get_statement_document_streams_bytes_same_origin",
            proof_kind="property",
        ),
        # ── group 1804: AI CSV parsing fallback for unknown institutions (was
        # EPIC-018 AC18.4.3, #1821 Wave A pending-package move) ──
        ac(
            "AC-extraction.1804.1",
            "AI CSV parsing handles an unknown institution as a fallback column-mapping path.",
            "apps/backend/tests/extraction/test_ai_csv_parsing.py::test_ai_csv_parsing_returns_valid_mapping",
            priority="P1",
            proof_kind="property",
        ),
        # ── group 1913: durable orchestration via Prefect (was EPIC-019
        # AC19.13.1/AC19.13.2, #1821 Wave A pending-package move) ──
        ac(
            "AC-extraction.1913.1",
            "Statement parse dispatch is config-gated: with PREFECT_API_URL unset, submit_parse_pipeline runs the existing in-process asyncio.create_task fallback (no Prefect import) and returns the task to track (also proven for the fallback's exception-consumer registration by test_AC19_13_1_dispatch_registers_exception_consumer_on_fallback in the same file).",
            "apps/backend/tests/api/test_statement_pipeline.py::test_AC19_13_1_dispatch_falls_back_to_asyncio_when_prefect_unset",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.2",
            "With PREFECT_API_URL set, submit_parse_pipeline submits a Prefect flow run with serializable params only (no raw bytes, no session maker) and returns None.",
            "apps/backend/tests/api/test_statement_pipeline.py::test_AC19_13_2_dispatch_submits_serializable_params_to_prefect",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.3",
            "The durable-parse deployment the worker registers (scripts/register_prefect_deployment.py) resolves to exactly the (flow, deployment) name PARSE_DEPLOYMENT that the API submits runs to — a name drift between the two would make every submitted run silently unrunnable. The script deploys from LOCAL source (code already baked into the worker's own image, promote-not-rebuild) against the process-type 'default' work pool, with no Docker build/push step; the worker's container entrypoint runs this registration (idempotent — upserts by name) before polling for work.",
            "apps/backend/tests/tooling/test_prefect_deployment_registration.py::test_AC_extraction_1913_3_registration_script_targets_the_deployment_api_submits_to",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.4",
            "API fallback and Prefect durable execution both invoke the same explicitly composed StatementIngestionUseCase; their adapters own transport only and never call a parallel parsing pipeline.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_1913_4_api_and_prefect_use_same_composed_use_case",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.5",
            "Statement ingestion dependencies are immutable constructor fields, and incomplete composition fails before a ParseJob starts without consulting mutable module-global provider registrations.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_1913_5_incomplete_composition_fails_before_job",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.6",
            "Unexpected application or infrastructure failures raise a typed retryable ingestion error and never rewrite the statement as a source-quality rejection.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_1913_6_application_error_does_not_reject_source",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.7",
            "A fresh worker interpreter composes every required statement-ingestion port without importing src.main or relying on API-process side effects.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_1913_7_fresh_worker_composes_without_main",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1913.8",
            "Retrying the same statement finalization is idempotent by statement and atomic-transaction identity and cannot duplicate ledger effects.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_1913_8_retry_does_not_duplicate_financial_effects",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.1913.9",
            "Accepting a statement upload persists and binds its immutable ODS source artifact before asynchronous dispatch, so the 202 response, reparse, and subsequent source-to-fact enrichment all resolve the same file path and display filename without transient ORM attributes.",
            "apps/backend/tests/api/test_statements_router.py::test_AC_extraction_1913_9_upload_registers_source_before_dispatch",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.1913.10",
            "A staging deploy pins the durable statement canary's checkout to its emitted commit SHA and its live-health assertion to the release tag that the deploy receiver has verified resolves to that SHA; it fails the deploy workflow when a required upload, parse, import, or value journey fails; comprehensive audit replay remains diagnostic evidence.",
            "tests/tooling/test_post_merge_e2e_gates.py::test_AC_extraction_1913_10_staging_statement_canary_is_sha_pinned_and_blocking",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.ingestion-trace.1",
            "The typed extraction result, its CODE-only integrity guard, and its promotion decision flush in the same unit of work as statement facts; trace persistence failure rolls back every financial effect.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_ingestion_trace_1_is_atomic_with_statement_facts",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.ingestion-trace.2",
            "Re-emitting the same extraction or disposition decision is content-idempotent, while a changed decision appends an explicit superseding head over the same stable target/assertion lineage.",
            "apps/backend/tests/extraction/test_statement_ingestion_use_case.py::test_AC_extraction_ingestion_trace_2_retries_are_idempotent_and_changes_supersede",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.result-envelope.1",
            "Every live, CSV, cassette, and persisted statement fact uses one strictly versioned StatementExtractionResult; unknown versions and structurally malformed facts fail before review or disposition. Its evidence type, not institution class, determines whether a cash ledger requires balances or a position snapshot requires positions. The declared statement currency is a distinct ledger source fact, not an inferred transaction or balance currency. Truthfully absent source facts remain explicit and review-only; they can never be promoted or turned into a disposition command.",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_result_envelope_1_rejects_unknown_versions_and_defaults",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.result-envelope.2",
            "A StatementExtractionResult round-trips exact bank and brokerage balances, transactions, positions, confidence, warnings, provenance, source closing values, stable identity, and content digest.",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_result_envelope_2_round_trips_complete_facts",
            proof_kind="invariant",
        ),
        # ── group reviewed-envelope: human confirmation is a separate,
        # version-bound fact, never an edit of the immutable extraction result
        # (#1912, extraction child of #1834 / #950). ──
        ac(
            "AC-extraction.reviewed-envelope.1",
            "Absent source currency, period, and balances remain explicit source absence until a typed reviewer command confirms one complete envelope; parser, router, and account defaults cannot fabricate them.",
            "apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_1_preserves_source_absence_until_typed_command",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.2",
            "A reviewed-envelope command is pinned to the exact current source-result digest and a user-owned custody account; stale, cross-user, partial, invalid, or balance-inconsistent input changes no source, review, or ledger fact.",
            "apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_2_rejects_invalid_or_stale_commands_atomically",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.3",
            "A successful command appends an auditable review decision with the exact immutable source-result trace as parent and exposes a confirmed-envelope projection without mutating the source payload.",
            "apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_3_appends_trace_and_preserves_source_payload",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.4",
            "Stage-1 approval consumes complete source facts or a current valid reviewed-envelope decision, while server-derived economic disposition remains a separate mandatory posting guard.",
            "apps/backend/tests/api/test_statements_router.py::test_AC_extraction_reviewed_envelope_4_approval_uses_reviewed_envelope_and_disposition",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.5",
            "A reparse invalidates a prior confirmation for a different source-result digest; identical command retries are idempotent and changed retries conflict or append an explicit superseding review fact, never overwrite one.",
            "apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_5_reparse_and_retry_are_explicit",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.6",
            "Stage-1 review exposes required envelope confirmation and validation reasons, offers a cash envelope only for source facts it can prove, and enables approval only after a current valid reviewed envelope exists.",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC-extraction.reviewed-envelope.6 confirms missing source envelope facts before approval",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.reviewed-envelope.7",
            "The database rejects direct UPDATE or DELETE of persisted source-result and reviewed-envelope facts; their tenant/statement references are restrictive rather than cross-domain cascading writes.",
            "apps/backend/tests/extraction/test_reviewed_statement_envelope.py::test_AC_extraction_reviewed_envelope_7_database_rejects_fact_mutation",
            proof_kind="invariant",
        ),
        # ── group statement-contribution: source-to-package boundary (#1681) ──
        ac(
            "AC-extraction.statement-contribution.1",
            "resolve_statement_contribution publishes the exact current immutable StatementExtractionResult, including its transaction and position facts, record identity, digest, uploaded-document reference, and decision id without reconstructing a cassette or exposing extraction ORM rows to consumers.",
            "apps/backend/tests/extraction/test_statement_contribution.py::test_AC_extraction_statement_contribution_1_preserves_exact_position_source_result",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.statement-contribution.2",
            "A contribution is authoritative only when its exact current source version has a current authoritative extraction-promotion or reviewed-envelope TraceRecord decision; provenance, confidence, source class, or import time cannot substitute for that decision.",
            "apps/backend/tests/extraction/test_statement_contribution.py::test_AC_extraction_statement_contribution_2_reviewed_envelope_pins_exact_decision",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.statement-contribution.3",
            "Malformed, missing, non-authoritative, stale, cross-tenant, or target-mismatched source facts or decisions return an explicit unproven contribution and never grant trust to a package consumer; authoritative contributions carry no reason code and unproven contributions carry no decision id.",
            "apps/backend/tests/extraction/test_statement_contribution.py::test_AC_extraction_statement_contribution_3_fails_closed_without_current_decision",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.statement-contribution.4",
            "A statement contribution publishes the exact confirmed custody account identity with its input refs. An authoritative bank-statement contribution without that identity fails closed instead of leaving package consumers to infer an account from institution or account names.",
            "apps/backend/tests/extraction/test_statement_contribution.py::test_AC_extraction_statement_contribution_4_publishes_confirmed_custody_account",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.source-capability.1",
            "Extraction publishes one stable semantic SourceCapability per source class without pytest paths; manual-trusted and gap capabilities cannot masquerade as automatic statement parsing.",
            "apps/backend/tests/extraction/test_statement_result_contract.py::test_AC_extraction_source_capability_1_declares_semantics_not_test_paths",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.disposition.1",
            "DispositionPolicy is the only statement-to-ledger semantic boundary: it returns balanced command intent, explicit review, or exclusion and never infers economic meaning from cash direction.",
            "apps/backend/tests/extraction/test_disposition_policy.py::test_AC_extraction_disposition_1_never_uses_direction_as_intent",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.disposition.2",
            "Transfers, investment and liability principal, and card repayment cannot enter profit or loss; missing account context or unsupported intent is routed to review instead of Uncategorized.",
            "apps/backend/tests/extraction/test_disposition_policy.py::test_AC_extraction_disposition_2_principal_and_transfer_never_enter_pnl",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.disposition.3",
            "A reviewed recorded-description rule traverses through proposal origin, accounting intent/category, DispositionDecision, posted ledger command, and report line for salary, grocery, expense refund, dividend, fee, transfer, investment purchase/sale, loan principal/interest, and card repayment. Only declared P&L intents may affect profit or loss.",
            "apps/backend/tests/integration/test_statement_disposition_semantic_oracle.py::test_AC_extraction_disposition_3_reviewed_description_oracle_reaches_exact_report_lines",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.disposition.4",
            "IntentProposal carries one closed proposal origin. Trace authority is derived only from that origin: reviewed deterministic rules are CODE-ONLY, live model proposals are LLM-LED and require the existing CODE-ONLY promotion guard, and accepted reconciliation facts are CODE-LED. Manual adjudication is reconciliation-owned CODE-ONLY/manual evidence without a machine-confidence score. Economic intent never infers authority.",
            "apps/backend/tests/extraction/test_disposition_policy.py::test_AC_extraction_disposition_4_trace_authority_follows_explicit_proposal_origin",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.disposition.5",
            "Stage 1 source confirmation returns a committed pending-review outcome, never a successful approval, when DispositionPolicy has no authoritative command for any statement transaction.",
            "apps/backend/tests/api/test_statements_router.py::test_AC_extraction_disposition_5_stage1_requires_economic_review",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.disposition.6",
            "Before a Stage 1 disposition can create a ledger command, its emitted source decision must be authoritative. Missing or non-authoritative trace output routes the statement to pending review with no journal entry.",
            "apps/backend/tests/api/test_statements_router.py::test_AC_extraction_disposition_6_auto_post_requires_authoritative_trace_decision",
            proof_kind="invariant",
        ),
        ac(
            "AC-extraction.disposition-rollout.1",
            "Off, observe, and enforce execute the same versioned disposition calculation; rollout mode controls command application only and cannot change or bypass the decision.",
            "apps/backend/tests/extraction/test_disposition_policy.py::test_AC_extraction_disposition_rollout_1_modes_share_one_decision",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.disposition.7",
            "Every disposition TraceRecord binds the exact versioned runtime policy snapshot (mode, machine and P&L authority thresholds, unknown/ambiguous routing, live-proposal state, and deployment commit); a newly frozen package persists and reopens the same structured snapshot and disclosure without recomputing it from current settings.",
            "apps/backend/tests/api/test_personal_report_package_contract.py::test_AC_extraction_disposition_7_frozen_package_persists_trace_bound_policy_snapshot",
            proof_kind="invariant",
        ),
        # ── group api-vectors: backend-owned API response conformance
        # vectors (#1827 G-contract-reddens, pattern from #1167). The wire
        # shape of the POST /api/statements/upload 202 envelope and the
        # parsed GET /api/statements/{id} envelope is committed as
        # common/extraction/conformance/vectors.json; the backend drift test
        # recomputes it and the frontend loads the same file as mock data. ──
        ac(
            "AC-extraction.api-vectors.1",
            "The serialized statement upload/status responses (BankStatementResponse wire shape, decimal-string balances, IN/OUT transaction directions, internally balance-consistent parsed vector) recomputed from fixed deterministic inputs equal the committed common/extraction/conformance/vectors.json, so a serializer change without vector regeneration reds CI (#1827).",
            "apps/backend/tests/schemas/test_api_response_vectors.py::test_AC_extraction_api_vectors_1_statement_upload_matches_committed_vector",
            priority="P1",
        ),
        ac(
            "AC-extraction.api-vectors.2",
            "The frontend statement uploader test consumes the committed extraction conformance vector (202 upload envelope) verbatim as its mock data via the shared fixture helper, so a regenerated breaking wire shape reds the frontend suite (#1827).",
            "apps/frontend/src/__tests__/StatementUploader.test.tsx::AC8.4.1 requires a file and calls completion callback after successful upload",
            priority="P1",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ac(
            "AC-extraction.fe-stage1-review.1",
            "Statements page renders loading, error, empty, and populated states",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC16.14.10 AC22.1.8 renders the uploader and upload history (loading, error, empty, populated)",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.2",
            "Statements page enables polling when parsing status is present",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC16.14.11 AC22.11.1 enables polling with an honest parsing state (no fabricated progress)",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.3",
            "Statements page delete action calls delete API and toast on confirm",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC16.14.12 delete action calls delete API and toast",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.4",
            "Statement detail page loads statement data and renders parsed transactions summary",
            "apps/frontend/src/__tests__/statementDetailPage.test.tsx::AC16.18.1 loads detail data and renders transactions",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.5",
            "Statement detail page is read-only for approval actions: no Approve/Reject buttons render, and it never calls the approve/reject APIs",
            "apps/frontend/src/__tests__/statementDetailPage.test.tsx::AC16.18.2 detail page is read-only for approval actions",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.6",
            "Statement detail page retry action posts retry API and refreshes data",
            "apps/frontend/src/__tests__/statementDetailPage.test.tsx::AC16.18.3 retry parse posts retry API and refreshes",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.7",
            "Statement review page shows error fallback and supports retry",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.18.4 shows loading feedback while review data is pending",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.8",
            "Statement review page disables approve when balance validation fails",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.18.5 disables approve when balance validation fails",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.9",
            "Statement review page approve and reject actions call APIs and navigate back to statements",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.18.6 approves the statement and routes back to statement detail",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.10",
            "Stage 1 statement review shows read-only transaction cards on phone widths (inline editing was removed in EPIC-011 Stage 3; correct a mis-parse via reject + re-parse), with approve and reject actions visible without horizontal dragging",
            "apps/frontend/playwright/mobile-ux.spec.ts::AC16.26.1 stage 1 mobile review exposes read-only transaction cards and completion actions",
        ),
        ac(
            "AC-extraction.fe-stage1-review.11",
            "Stage 1 desktop review keeps the transaction review surface readable at 1440px with the sidebar visible without local horizontal clipping",
            "apps/frontend/playwright/mobile-ux.spec.ts::AC8.13.82/AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px",
        ),
        ac(
            "AC-extraction.fe-stage1-review.12",
            "Frontend tests mount each new component (PdfPreviewPane, TransactionTable, ConflictResolutionDialog, BottomTabBar) and assert primary affordance renders",
            "apps/frontend/src/__tests__/epic016Components.test.tsx::mounts PdfPreviewPane and asserts primary affordance (AC16.23.6)",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-stage1-review.13",
            "Stage 1 approval is disabled unless both opening and closing balance validation match",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.31.2 disables approval when opening balance validation fails",
        ),
        ac(
            "AC-extraction.fe-stage1-review.14",
            "Stage 1 balance validation UI reports opening and closing checks separately so reviewers see the same gate enforced by the backend",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.32.2 shows opening and closing balance validation states separately",
        ),
        ac(
            "AC-extraction.fe-stage1-review.15",
            "Statement-detail parsing polls are single-flight; page teardown or statement-id change aborts the active read, and only the latest page-owned response may update status, errors, or toasts; an explicit retry refresh supersedes an older polling read",
            "apps/frontend/src/__tests__/statementDetailPage.test.tsx::AC-extraction.fe-stage1-review.15 keeps detail polling single-flight and aborts active work on teardown",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-stage1-review.16",
            "Upload-history parsing polls are single-flight; page teardown aborts the active read, while upload/delete completion supersedes an older read so stale rows cannot be restored",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC-extraction.fe-stage1-review.16 keeps upload polling single-flight and supersedes stale work",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-stage1-review.17",
            "Statement review page provides auto-filling default categories via autoFill action on classification review",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC-extraction.fe-stage1-review.17 supports auto_fill_default_categories via auto-fill action on classification review",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-stage1-review.18",
            "UploadPage exposes View Report action for approved statements and Review & Approve for parsed statements",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC-extraction.fe-stage1-review.18 exposes View Report action for approved statements and Review & Approve for parsed statements",
            priority="P2",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ac(
            "AC-extraction.fe-ia-extraction.1",
            "When the statement-review Approve action is blocked (balance validation failed or unresolved duplicate/transfer-pair conflicts), the page shows a visible plain-language reason and an in-place action (open the conflict-resolution dialog, or re-parse the statement) without leaving the page",
            "apps/frontend/src/__tests__/reviewActionBar.test.tsx::AC22.5.2 enables Approve and shows no blocker when nothing is wrong",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-ia-extraction.2",
            "The statement-parsing state shows an honest indeterminate indicator with a typical-duration expectation, and never renders a fabricated fixed-percentage progress bar",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC16.14.11 AC22.11.1 enables polling with an honest parsing state (no fabricated progress)",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-ia-extraction.3",
            "The statement detail page is composed from extracted sub-components (header/summary and the transactions/section blocks) with unchanged behavior",
            "apps/frontend/src/__tests__/statementDetailParts.test.tsx::AC22.17.3 renders title, status badge, description and review link",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-ia-extraction.4",
            "When Stage 1 approval requires economic review, the statement review page keeps a persistent plain-language explanation and a single action that opens the unmatched queue scoped to that exact statement, with a return target back to its review page.",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC-extraction.fe-ia-extraction.4 routes economic-review conflicts to the exact statement queue",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ac(
            "AC-extraction.fe-remainder-extraction.1",
            "Audit Trail panel on transaction detail page lists chronological `{timestamp, actor, action, old_value, new_value}` from `GET /api/transactions/{id}/audit`, including AI-applied changes labeled with actor `ai`",
            "apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.6 — Audit Trail panel renders provenance",
            priority="P2",
        ),
        ac(
            "AC-extraction.fe-remainder-extraction.2",
            "The Upload page exposes exactly three intake entries — one primary statement uploader (the AI identifies the type; the user never pre-classifies), one CSV import, and one Manual records entry — with no per-source-class checklist",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC19.15.1 exposes exactly three intake entries: one statement uploader plus CSV and Manual",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-remainder-extraction.3",
            "The CSV import and Manual records entries are folded (collapsed) by default so they stay passive, the retired per-source-class checklist does not return, and the page does not fetch report readiness merely to render intake",
            "apps/frontend/src/__tests__/statementsPage.test.tsx::AC19.15.2 keeps secondary intake passive: CSV and Manual folded, no per-class checklist, no readiness fetch",
            priority="P1",
        ),
        ac(
            "AC-extraction.fe-remainder-extraction.4",
            'The primary statement uploader (`kind="statement"`) rejects `.csv` files by extension before setting a selected file, and the CSV import uploader (`kind="csv"`) rejects non-csv files and accepts `.csv` — each intake entry enforces its own kind\'s file-extension restriction, independent of the shared `all`-kind default',
            "apps/frontend/src/__tests__/StatementUploader.test.tsx::AC19.15.3 statement uploader rejects csv and csv uploader rejects non-csv, each enforcing its own kind's extensions",
            priority="P1",
        ),
        # ── group 1833: auto-approve posts the chain-validated opening
        # balance so the balance sheet shows balances, not net flow (#1833) ──
        ac(
            "AC-extraction.1833.1",
            "When a high-confidence statement auto-approves (its running-balance chain reconciled), the extracted opening balance is posted as a guided opening-balance entry against the system Opening Balance Equity account, so the asset account's ledger balance equals the statement's closing balance, including signed balances. Explicit zero creates immutable starting-stock evidence without a monetary journal. Foreign currency uses historical FX; missing opening facts or FX block the posting unit of work atomically. Manual approval uses the same path.",
            "apps/backend/tests/integration/test_statement_opening_balance_auto_post.py::test_AC_extraction_1833_1_auto_approve_posts_validated_opening_balance",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1833.2",
            "A follow-up period import for the same account posts its transactions but never a second opening-balance entry: existing authoritative per-account starting-stock evidence is reused without creating a second opening journal. Invalid or missing starting stock remains an actionable posting blocker.",
            "apps/backend/tests/integration/test_statement_opening_balance_auto_post.py::test_AC_extraction_1833_2_second_import_does_not_duplicate_opening_balance",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1833.3",
            "The opening-balance post is never gated on created_count: a high-confidence, balance-validated statement whose transactions are all excluded from posting (internal-transfer matches, or already posted by a prior call) still gets its opening balance posted. Idempotency against re-posting is enforced per-account (does this account already have an authoritative opening-position evidence), not by created_count or by date-ordering alone — covering two statements that share the same period_start, where date-ordering alone would not catch a re-attempt.",
            "apps/backend/tests/integration/test_statement_opening_balance_auto_post.py::test_AC_extraction_1833_3_zero_created_count_still_posts_opening_balance",
            proof_kind="property",
        ),
        # ── group 1832: paginated full-document vision extraction — the
        # per-request page cap must never silently truncate a document (#1832) ──
        ac(
            "AC-extraction.1832.1",
            "Vision extraction covers EVERY page of a PDF: documents longer than the per-request page cap are rendered in full, extracted through one model call per page batch (each call sees only its own pages plus part-scoped prompt rules), and the per-part payloads are merged into one whole-document extraction — the pre-#1832 silent truncation, which made the running-balance chain mathematically guaranteed to fail for any statement longer than the cap, is gone.",
            "apps/backend/tests/extraction/test_paged_vision_extraction.py::test_AC_extraction_1832_1_multi_batch_pdf_extracts_once_per_batch_and_merges",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1832.2",
            "Paged-extraction merge is pure and deterministic: transactions/positions concatenate in page order, scalar metadata takes the first non-empty part value, opening balance comes from the first part that saw one, closing balance from the last.",
            "apps/backend/tests/extraction/test_paged_vision_extraction.py::test_AC_extraction_1832_2_merge_semantics",
            priority="P1",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.1832.3",
            "Documents above the total-page ceiling fail with an explicit, page-count-naming error before any model call — an honest bound, never silent truncation.",
            "apps/backend/tests/extraction/test_paged_vision_extraction.py::test_AC_extraction_1832_3_total_page_ceiling_is_an_explicit_error",
            priority="P1",
            proof_kind="property",
        ),
        # ── group 1832.4: a rejected parse must not leave the physical bank
        # account it just auto-created cluttering the chart of accounts (#1832
        # staging QA follow-up) ──
        ac(
            "AC-extraction.1832.4",
            "The physical bank account auto-created for a statement (#1444) is deleted if that same parse call created it and the extraction is then quarantined by the LLM-LED invariant gate (REJECTED) — a rejected parse must never leave a balance-0.00, provenance-less zombie account. An account reused from an earlier statement (get-or-create hit) is never deleted, even when the later statement is rejected; the cleanup itself double-checks no other NON-REJECTED statement or journal line references the account before deleting it — other rejected statements sharing the account_id carry no journal lines and no trusted data, so they are not counted as a real reference.",
            "apps/backend/tests/integration/test_statement_reject_cleans_up_orphan_account.py::test_AC_extraction_1832_4_rejected_parse_deletes_the_account_it_just_created",
            priority="P1",
            proof_kind="property",
        ),
        # ── issue #1866 PR-B: the extraction orchestration boundary carries
        # cohesive typed values instead of repeating primitive parameter
        # clusters or attaching transient persistence data to ORM instances. ──
        ac(
            "AC-extraction.signature-seams.1",
            "A single frozen ParseJob value object crosses the upload, in-process worker, and Prefect boundaries; its explicit to/from Prefect conversion round-trips UUIDs and contains no bytes or database/session objects.",
            "apps/backend/tests/extraction/test_signature_seams.py::test_AC_extraction_signature_seams_1_parse_job_round_trips_prefect_params",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.signature-seams.2",
            "DocumentSource resolves the document path, content, URL, content hash, and display filename once before parsing; CSV and vision extraction then consume that immutable source.",
            "apps/backend/tests/extraction/test_signature_seams.py::test_AC_extraction_signature_seams_2_document_source_is_the_only_parse_input",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.signature-seams.3",
            "parse_document delegates CSV and vision source extraction to separate typed paths while preserving the shared validation and persistence pipeline.",
            "apps/backend/tests/extraction/test_signature_seams.py::test_AC_extraction_signature_seams_3_csv_and_vision_paths_are_separate",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.signature-seams.4",
            "Parsed transaction rows carry dedup_hash, balance_after, occurrence_index, and currency resolution as a typed immutable DTO; Layer-2 persistence accepts AsyncSession and never reads transient attributes from ORM objects or filters failure arguments with inspect.signature. ParseJob also owns the failure-lineage identity instead of repeating its fields.",
            "apps/backend/tests/extraction/test_signature_seams.py::test_AC_extraction_signature_seams_4_typed_rows_and_failure_contract",
            proof_kind="property",
        ),
        # #1970: one extraction-owned source lifecycle, reusing the existing
        # ingestion/result/envelope aggregates rather than adding a platform.
        ac(
            "AC-extraction.source-lifecycle.1",
            "Stage-1 approval validates every declared currency independently and never permits opposite differences in distinct currencies to cancel.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_1_approval_is_per_currency",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.2",
            "Concurrent ingestion of one user-owned content digest converges on one canonical UploadedDocument and immutable extraction-result identity.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_2_two_sessions_share_source_identity",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.3",
            "A source-identity uniqueness conflict is isolated by a savepoint; the outer session selects the winner and remains usable for deterministic commit.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_3_conflict_preserves_outer_session",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.4",
            "Ordinary statement removal is an idempotent retire transition that preserves source results, reviewed envelopes, transactions, and lineage.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_4_retire_preserves_history",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.5",
            "Retirement changes durable reference state without deleting object content, so object-storage failure cannot split source truth from database truth.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_5_retire_does_not_delete_storage",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.6",
            "Rollback, commit failure, restart, and repeated lifecycle commands converge on the same canonical source state without duplicate financial facts.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_6_failure_and_retry_converge",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.7",
            "The audited lifecycle boundary accepts typed UUID, currency, Decimal, date, and immutable transaction/result values rather than list-of-dict financial payloads.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_7_boundary_is_typed",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.8",
            "Physical purge is absent from ordinary statement lifecycle commands and remains a separately governed cross-package operation.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_8_ordinary_api_has_no_purge_path",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.9",
            "Governance detail derives detector, proof-strength, exact target SHA, issue, progress, and live enforcement state for every source-lifecycle guarantee.",
            "apps/backend/tests/extraction/test_source_lifecycle_governance.py::test_AC_extraction_source_lifecycle_9_governance_detail_is_exact",
            proof_kind="property",
        ),
        ac(
            "AC-extraction.source-lifecycle.10",
            "Counterfactual tests exercise cross-currency cancellation, independent-session conflict, failed commit, storage outage, retry, and retained history.",
            "apps/backend/tests/extraction/test_source_lifecycle.py::test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked",
            proof_kind="property",
        ),
    ],
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
    concepts=[
        ConceptRecord(
            key="source_capability_registry",
            owner="apps/backend/src/extraction/base/source_capability.py",
            description=(
                "Canonical semantic registry for product source classes, their support "
                "status, accepted evidence, produced facts, review semantics, and "
                "traceability target."
            ),
            cross_refs=[
                "common/extraction/readme.md#sourcecapability-registry",
                "vision.md",
                "common/testing/source_capability_proof.py",
            ],
            proofs=[
                "apps/backend/tests/extraction/test_statement_result_contract.py",
                "tests/tooling/test_source_capability_proof.py",
            ],
            family="source",
            kind="registry",
        ),
        ConceptRecord(
            key="confidence_tier_rollup",
            owner="common/extraction/confirmation-workflow.md#confidence-tier-rollup",
            description=(
                "Confidence-tier rollup that makes extraction confidence load-bearing for "
                "promotion."
            ),
            cross_refs=["common/extraction/readme.md#confidence-scoring"],
            family="extraction",
            kind="concept",
        ),
        ConceptRecord(
            key="confirmation_workflow",
            owner="common/extraction/confirmation-workflow.md",
            description="Cross-cutting pending_review state machine (Stage 1 & 2).",
            cross_refs=[
                "common/reconciliation/reconciliation.md",
                "common/ledger/readme.md",
            ],
            family="extraction",
            kind="concept",
        ),
        ConceptRecord(
            key="confirmation_workflow_states",
            owner="common/extraction/confirmation-workflow.md#state-machine",
            description=(
                "Stage 1 & Stage 2 confirmation state transitions (the cross-cutting state "
                "machine)."
            ),
            cross_refs=["common/reconciliation/readme.md#state-machine"],
            family="reconciliation",
            kind="concept",
        ),
        ConceptRecord(
            key="evidence_lineage",
            owner="common/extraction/evidence-lineage.md",
            description="Generic Evidence Graph for source-to-ledger-to-report audit lineage.",
            cross_refs=[
                "docs/project/EPIC-018.ai-driven-pipeline.md",
                "common/workflow/workflow-events.md",
                "common/reporting/reporting.md",
                "apps/backend/tests/extraction/test_evidence_graph_materialization.py",
            ],
            family="evidence",
            kind="concept",
        ),
        ConceptRecord(
            key="extraction_confidence_tiers",
            owner="common/extraction/readme.md#confidence-scoring",
            description="Extraction confidence score weighting and ≥85 / 60-84 / <60 routing tiers.",
            cross_refs=[
                "common/reconciliation/readme.md#thresholds",
                "common/extraction/confirmation-workflow.md#confidence-tier-rollup",
            ],
            family="extraction",
            kind="concept",
        ),
        ConceptRecord(
            key="extraction_failed_case_registry",
            owner="common/extraction/audit-failed-cases.yaml",
            description=(
                "Sanitized registry for parsing cases that fail audit without expanding "
                "deterministic parser scope."
            ),
            cross_refs=[
                "common/extraction/readme.md",
                "docs/project/EPIC-003.statement-parsing.md",
            ],
            proofs=["tests/tooling/test_extraction_failed_case_registry.py"],
            family="extraction",
            kind="registry",
        ),
        ConceptRecord(
            key="extraction_pipeline",
            owner="common/extraction/readme.md",
            description="Gemini Vision document parsing and validation pipeline.",
            cross_refs=[
                "common/reconciliation/reconciliation.md",
                "apps/backend/tests/extraction/test_dual_write_layer2.py",
            ],
            family="extraction",
            kind="concept",
        ),
    ],
)
