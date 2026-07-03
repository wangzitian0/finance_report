"""``extraction`` — the backend implementation of the ``extraction`` package (#1421).

The statement-parsing bounded context: documents in (PDF/image/CSV), verified
financial facts out. It owns the source→fact half of the pipeline — parsing
(vision-LLM + per-institution CSV), per-currency balance validation and
balance-chain continuity, dedup by content hash, brokerage detection, and the
evidence lineage that links every extracted fact to its source document.

Files converge by layer (common/meta/migration-standard.md): ``base/`` holds
the pure validation/confidence calculus; ``extension/`` the parsing pipeline
(``ExtractionService`` + format mixins), dedup + dual-write repository verbs,
brokerage classification, prompts, and the evidence write path; ``data/`` the
evidence lineage read-models. The ORM entities (UploadedDocument /
AtomicTransaction / AtomicPosition) stay in the unregistered ``src/models/``
until their cross-domain FKs are cut (Stage-4 scope; ledger/llm precedent).

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
from src.extraction.extension.evidence_lineage import EvidenceLineageService
from src.extraction.extension.prompts.csv_mapping import build_csv_mapping_prompt
from src.extraction.extension.prompts.statement import SYSTEM_PROMPT, get_parsing_prompt
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_summary import resolve_custody_account_id

__all__ = [
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
]
