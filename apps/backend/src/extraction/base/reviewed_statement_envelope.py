"""Pure command value for reviewed statement-envelope confirmation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.extraction.base.result import StatementEvidenceType, StatementExtractionResult

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONEY_QUANTUM = Decimal("0.01")
_ENVELOPE_REVIEWABLE_FACTS = frozenset({"statement_currency", "period", "balances"})


def _digest(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def supports_reviewed_statement_envelope(result: StatementExtractionResult) -> bool:
    """Whether this source's missing facts can be proven by a cash envelope."""
    return (
        result.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
        and bool(result.missing_required_facts)
        and set(result.missing_required_facts) <= _ENVELOPE_REVIEWABLE_FACTS
    )


@dataclass(frozen=True, slots=True)
class ReviewedStatementEnvelopeCommand:
    """One complete reviewer assertion over an exact raw result identity."""

    source_result_digest: str
    account_id: UUID
    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    rationale: str

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.source_result_digest):
            raise ValueError("source_result_digest must be a lowercase sha256")
        if not isinstance(self.account_id, UUID):
            raise TypeError("account_id must be a UUID")
        normalized_currency = self.currency.strip().upper()
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValueError("currency must be an ISO three-letter code")
        object.__setattr__(self, "currency", normalized_currency)
        if not isinstance(self.period_start, date) or not isinstance(self.period_end, date):
            raise TypeError("period bounds must be dates")
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        for name in ("opening_balance", "closing_balance"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise TypeError(f"{name} must be a finite Decimal")
            if value.quantize(_MONEY_QUANTUM) != value:
                raise ValueError(f"{name} must have at most two decimal places")
        rationale = self.rationale.strip()
        if not rationale:
            raise ValueError("rationale is required")
        if len(rationale) > 2000:
            raise ValueError("rationale exceeds 2000 characters")
        object.__setattr__(self, "rationale", rationale)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "source_result_digest": self.source_result_digest,
                "account_id": str(self.account_id),
                "currency": self.currency,
                "period_start": self.period_start.isoformat(),
                "period_end": self.period_end.isoformat(),
                "opening_balance": str(self.opening_balance),
                "closing_balance": str(self.closing_balance),
                "rationale": self.rationale,
            }
        )
