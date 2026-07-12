"""``extraction`` — the backend implementation of the ``extraction`` package (#1421).

The statement-parsing bounded context: documents in (PDF/image/CSV), verified
financial facts out. It owns the source→fact half of the pipeline — parsing
(vision-LLM + per-institution CSV), per-currency balance validation and
balance-chain continuity, dedup by content hash, brokerage detection, and the
evidence lineage that links every extracted fact to its source document.

Files converge by layer (common/meta/migration-standard.md): ``base/`` holds
the pure validation/confidence calculus; ``extension/`` the parsing pipeline
(``ExtractionService`` + format mixins), dedup + dual-write repository verbs,
brokerage classification, prompts, and the evidence write path; ``orm/`` the
ORM entities this package owns. ``UploadedDocument`` moved here from
``src/models/`` (#1675 D3) — its only cross-domain coupling was a plain FK
column (no ``relationship()``), and its two former L1-infra readers
(``platform``/``runtime``) now go through the published read-only lookups in
``extension/uploaded_document_reads.py`` instead of importing the ORM class,
closing the infra-imports-domain layering violation that blocked the first
attempt. ``AtomicTransaction``/``AtomicPosition`` (layer2.py) stay in the
unregistered ``src/models/`` until their own genuine cross-domain
``relationship()`` navigation (to ``Account``/``User``) is converted to id +
explicit interface lookups (D4).

The names re-exported below are the entire public surface (``__all__`` must
equal ``contract.interface``). Downstream domains reference AtomicTransaction
rows BY ID (Decision B) — this package never exposes another domain's
aggregates.
"""

from __future__ import annotations

# ``validation`` is also published as a module handle: call sites and tests
# monkeypatch its functions (``validation.validate_balance = …``) and need one
# canonical module object to patch.
from src.extraction.base import validation
from src.extraction.base.validation import (
    compute_confidence_score,
    detect_balance_chain_break,
    validate_balance,
)
from src.extraction.extension.brokerage_positions import (
    BrokeragePositionImportService,
    looks_like_brokerage_document,
    looks_like_brokerage_payload,
    parse_brokerage_csv_payload,
    parse_brokerage_positions,
)
from src.extraction.extension.brokerage_statement_payload import (
    _brokerage_import_not_ready_reason,
    _brokerage_payload_from_persisted_extraction,
    _brokerage_payload_from_statement,
)
from src.extraction.extension.correction_loop import CorrectionLoopService
from src.extraction.extension.correction_service import (
    get_correction_stats,
    record_correction,
)
from src.extraction.extension.currencies import snapshot_currencies
from src.extraction.extension.currency_resolution import (
    CurrencyUnresolvedError,
    resolve_ingest_currency,
    resolve_transaction_currency,
)
from src.extraction.extension.deduplication import (
    DeduplicationService,
    dual_write_layer2,
)
from src.extraction.extension.evidence_graph_integration import (
    EvidenceGraphIntegrationService,
)
from src.extraction.extension.evidence_graph_materialization import (
    EvidenceGraphMaterializationService,
)
from src.extraction.extension.evidence_lineage import (
    DEFAULT_MAX_DEPTH,
    EvidenceLineageService,
    EvidenceTraversalStep,
)
from src.extraction.extension.prompts.csv_mapping import build_csv_mapping_prompt
from src.extraction.extension.prompts.statement import SYSTEM_PROMPT, get_parsing_prompt
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing_supervisor import (
    run_parsing_supervisor,
)
from src.extraction.extension.statement_pipeline import submit_parse_pipeline
from src.extraction.extension.statement_posting import (
    auto_create_posted_entries_for_statement,
    register_transfer_exclusions_provider,
    resolve_statement_posting_account,
)
from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.extension.statement_validation import (
    edit_and_approve,
    pending_stage1_review_filter,
    resolve_statement_conflicts,
    resolve_statement_transactions,
    set_opening_balance,
    validate_balance_chain,
)
from src.extraction.extension.statement_workflow import (
    approve_statement_workflow,
    reject_statement_workflow,
)
from src.extraction.extension.transaction_classification import (
    backfill_classifications,
)
from src.extraction.extension.uploaded_document_reads import (
    find_uploaded_document_filename_by_hash,
    get_known_storage_paths,
    get_uploaded_document_filename,
    get_uploaded_document_filenames,
)

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
from src.extraction.orm.layer1 import DocumentStatus, DocumentType, UploadedDocument

__all__ = [
    "BrokeragePositionImportService",
    "CorrectionLoopService",
    "CurrencyUnresolvedError",
    "DEFAULT_MAX_DEPTH",
    "DeduplicationService",
    "DocumentStatus",
    "DocumentType",
    "EvidenceGraphIntegrationService",
    "EvidenceGraphMaterializationService",
    "EvidenceLineageService",
    "EvidenceTraversalStep",
    "ExtractionError",
    "ExtractionService",
    "SYSTEM_PROMPT",
    "UploadedDocument",
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
    "find_uploaded_document_filename_by_hash",
    "get_correction_stats",
    "get_known_storage_paths",
    "get_parsing_prompt",
    "get_uploaded_document_filename",
    "get_uploaded_document_filenames",
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
    "register_transfer_exclusions_provider",
    "resolve_statement_posting_account",
    "resolve_statement_transactions",
    "resolve_transaction_currency",
    "run_parsing_supervisor",
    "set_opening_balance",
    "snapshot_currencies",
    "submit_parse_pipeline",
    "validate_balance",
    "validate_balance_chain",
    "validation",
]
