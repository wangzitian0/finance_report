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
* No ``llm`` edge yet: the OCR/vision call sites still reach the provider via
  their own httpx path; routing them through ``src.llm`` (threading
  ``user_id``, the AC-llm.4.5 documented follow-up) ADDS ``llm`` to
  ``depends_on`` when it lands.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="extraction",
    klass="core",
    # Draft until the EPIC-003/013 ACs land in ``roadmap`` (the same PR decides
    # the authority tier from the migrated ACs' proof mix).
    status="draft",
    tier=None,
    depends_on=["audit", "platform", "observability", "config"],
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
        "CurrencyUnresolvedError",
        "DeduplicationService",
        "EvidenceGraphIntegrationService",
        "EvidenceGraphMaterializationService",
        "EvidenceLineageService",
        "ExtractionError",
        "ExtractionService",
        "SYSTEM_PROMPT",
        "build_csv_mapping_prompt",
        "compute_confidence_score",
        "detect_balance_chain_break",
        "dual_write_layer2",
        "get_parsing_prompt",
        "looks_like_brokerage_document",
        "looks_like_brokerage_payload",
        "parse_brokerage_csv_payload",
        "parse_brokerage_positions",
        "resolve_custody_account_id",
        "resolve_ingest_currency",
        "resolve_transaction_currency",
        "validate_balance",
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
    # Filled by the EPIC-003/013 AC migration (same PR, later commit); the
    # package goes status="active" with its authority tier decided there.
    roadmap=[],
)
