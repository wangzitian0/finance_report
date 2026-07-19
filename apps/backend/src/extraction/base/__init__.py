"""``extraction.base`` — pure extraction values and validation calculus.

Pure functions over parsed payloads (dicts/Decimals): per-currency balance
closure, balance-chain continuity, confidence scoring and threshold routing.
No ORM, no network, no LLM — the extension pipeline calls DOWN into these.
"""

from __future__ import annotations

from src.extraction.base.contribution import ResolvedStatementContribution
from src.extraction.base.disposition import (
    DispositionCommand,
    DispositionContext,
    DispositionDecision,
    DispositionMode,
    DispositionPolicy,
    DispositionStatus,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementDispositionPolicySnapshot,
    StatementTransaction,
)
from src.extraction.base.result import (
    SOURCE_CAPABILITIES,
    ExtractedPositionFact,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceCapability,
    SourceCapabilityStatus,
    SourceProvenance,
    StatementBalanceFact,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.base.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    supports_reviewed_statement_envelope,
)
from src.extraction.base.types import (
    DocumentSource,
    ExtractedTransactionRow,
    ParseJob,
    RetryableStatementIngestionError,
    StatementIngestionConfigurationError,
    StatementIngestionError,
    StatementIngestionOutcome,
    StatementIngestionStatus,
)

__all__ = [
    "DispositionCommand",
    "DispositionContext",
    "DispositionDecision",
    "DispositionMode",
    "DispositionPolicy",
    "DispositionStatus",
    "DocumentSource",
    "EconomicIntent",
    "ExtractionMethod",
    "ExtractedPositionFact",
    "ExtractedTransactionRow",
    "ExtractedTransactionFact",
    "IntentProposal",
    "IntentProposalOrigin",
    "ParseJob",
    "RetryableStatementIngestionError",
    "ResolvedStatementContribution",
    "ReviewedStatementEnvelopeCommand",
    "SourceCapability",
    "SOURCE_CAPABILITIES",
    "SourceCapabilityStatus",
    "SourceProvenance",
    "StatementBalanceFact",
    "StatementExtractionResult",
    "StatementIngestionConfigurationError",
    "StatementIngestionError",
    "StatementIngestionOutcome",
    "StatementIngestionStatus",
    "StatementDispositionPolicySnapshot",
    "StatementSourceType",
    "StatementTransaction",
    "supports_reviewed_statement_envelope",
]
