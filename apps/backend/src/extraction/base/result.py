"""Versioned source-to-fact contract for statement extraction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid5

from src.extraction.base.source_capability import (
    SOURCE_CAPABILITIES as SOURCE_CAPABILITIES,
    SourceCapability as SourceCapability,
    SourceCapabilityStatus as SourceCapabilityStatus,
)

SCHEMA_VERSION = "2"
_LEGACY_SCHEMA_VERSION = "1"
_SUPPORTED_SCHEMA_VERSIONS = frozenset((SCHEMA_VERSION, _LEGACY_SCHEMA_VERSION))
_NAMESPACE = UUID("31c166a8-56ae-4e2b-a5f3-ef169b2b2976")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StatementSourceType(StrEnum):
    BANK = "bank_statement"
    BROKERAGE = "brokerage_statement"


class StatementEvidenceType(StrEnum):
    """The source-evidence shape that determines required facts.

    Institution class answers where the statement came from; evidence type answers
    which source facts must exist before the result can cross a promotion boundary.
    A brokerage cash ledger therefore never pretends to be a position snapshot.
    """

    TRANSACTION_LEDGER = "transaction_ledger"
    POSITION_SNAPSHOT = "position_snapshot"


class ExtractionMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LIVE_LLM = "live_llm"
    GOLDEN_FIXTURE = "golden_fixture"


def _text(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _currency(value: str) -> str:
    value = value.strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError("currency must be a three-letter code")
    return value


def _confidence(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must use Decimal")
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{name} must be within [0, 1]")
    return value


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    intake_mode: str
    method: ExtractionMethod
    provider: str
    model: str

    def __post_init__(self) -> None:
        for name in ("intake_mode", "provider", "model"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.method, ExtractionMethod):
            raise TypeError("method must be ExtractionMethod")


@dataclass(frozen=True, slots=True)
class StatementBalanceFact:
    currency: str
    opening: Decimal
    closing: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _currency(self.currency))
        if not isinstance(self.opening, Decimal) or not isinstance(self.closing, Decimal):
            raise TypeError("balances must use Decimal")


@dataclass(frozen=True, slots=True)
class ExtractedTransactionFact:
    fact_id: str
    transaction_date: date
    description: str
    amount: Decimal
    direction: str
    currency: str | None
    balance_after: Decimal | None
    confidence: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _text(self.fact_id, "transaction fact_id"))
        object.__setattr__(self, "description", _text(self.description, "description"))
        if self.currency is not None:
            object.__setattr__(self, "currency", _currency(self.currency))
        if self.direction not in {"IN", "OUT"}:
            raise ValueError("transaction direction must be IN or OUT")
        if not isinstance(self.amount, Decimal) or self.amount <= 0:
            raise ValueError("transaction amount must be a positive Decimal")
        if self.balance_after is not None and not isinstance(self.balance_after, Decimal):
            raise TypeError("balance_after must use Decimal")
        if self.confidence is not None:
            _confidence(self.confidence, "transaction confidence")


@dataclass(frozen=True, slots=True)
class ExtractedPositionFact:
    fact_id: str
    symbol: str
    quantity: Decimal
    market_value: Decimal
    currency: str
    confidence: Decimal | None
    asset_type: str | None = None
    sector: str | None = None
    geography: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _text(self.fact_id, "position fact_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "position symbol"))
        object.__setattr__(self, "currency", _currency(self.currency))
        if not isinstance(self.quantity, Decimal) or not isinstance(self.market_value, Decimal):
            raise TypeError("position values must use Decimal")
        if self.confidence is not None:
            _confidence(self.confidence, "position confidence")


@dataclass(frozen=True, slots=True)
class StatementExtractionResult:
    """Complete immutable result shared by every extraction transport."""

    producer_version: str
    source_content_digest: str
    source_type: StatementSourceType
    evidence_type: StatementEvidenceType
    institution: str
    account_last4: str | None
    period_start: date | None
    period_end: date | None
    balances: tuple[StatementBalanceFact, ...]
    transactions: tuple[ExtractedTransactionFact, ...]
    positions: tuple[ExtractedPositionFact, ...]
    confidence: Decimal
    balance_validated: bool | None
    warnings: tuple[str, ...]
    review_reasons: tuple[str, ...]
    provenance: SourceProvenance
    statement_currency: str | None = None
    schema_version: str = SCHEMA_VERSION
    content_digest: str = field(init=False)
    result_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported statement extraction schema version: {self.schema_version}")
        object.__setattr__(self, "producer_version", _text(self.producer_version, "producer_version"))
        if not _SHA256.fullmatch(self.source_content_digest):
            raise ValueError("source_content_digest must be lowercase sha256")
        if not isinstance(self.source_type, StatementSourceType):
            raise TypeError("source_type must be StatementSourceType")
        if not isinstance(self.evidence_type, StatementEvidenceType):
            raise TypeError("evidence_type must be StatementEvidenceType")
        if self.statement_currency is not None:
            object.__setattr__(self, "statement_currency", _currency(self.statement_currency))
        object.__setattr__(self, "institution", _text(self.institution, "institution"))
        if self.account_last4 is not None and not re.fullmatch(r"[A-Za-z0-9]{1,4}", self.account_last4):
            raise ValueError("account_last4 must contain one to four ASCII alphanumeric characters")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("statement period bounds must both be present or both be absent")
        if self.period_start is not None and self.period_end is not None and self.period_start > self.period_end:
            raise ValueError("invalid statement period")
        if len({item.currency for item in self.balances}) != len(self.balances):
            raise ValueError("balances must be unique by currency")
        _confidence(self.confidence, "statement confidence")
        for name in ("warnings", "review_reasons"):
            if any(not item.strip() for item in getattr(self, name)):
                raise ValueError(f"{name} cannot contain blanks")
        digest = hashlib.sha256(
            json.dumps(self._semantic_payload(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "result_id", uuid5(_NAMESPACE, digest))

    @classmethod
    def create(cls, **values: Any) -> StatementExtractionResult:
        return cls(**values)

    @property
    def missing_required_facts(self) -> tuple[str, ...]:
        """Facts required before this result may cross the promotion boundary."""
        return self.required_fact_kinds(
            evidence_type=self.evidence_type,
            period_start=self.period_start,
            period_end=self.period_end,
            # A multi-currency source may declare units only on its exact
            # opening/closing buckets; those are source facts, unlike a
            # transaction-row currency which cannot establish the envelope.
            has_statement_currency=self.statement_currency is not None or bool(self.balances),
            has_balances=bool(self.balances),
            has_positions=bool(self.positions),
            has_unresolved_transaction_currency=any(item.currency is None for item in self.transactions),
        )

    @staticmethod
    def required_fact_kinds(
        *,
        evidence_type: StatementEvidenceType,
        period_start: date | None,
        period_end: date | None,
        has_statement_currency: bool,
        has_balances: bool,
        has_positions: bool,
        has_unresolved_transaction_currency: bool,
    ) -> tuple[str, ...]:
        """Return the one promotion policy used by every extraction transport."""
        missing: list[str] = []
        if evidence_type is StatementEvidenceType.TRANSACTION_LEDGER and not has_statement_currency:
            missing.append("statement_currency")
        if period_start is None or period_end is None:
            missing.append("period")
        if evidence_type is StatementEvidenceType.TRANSACTION_LEDGER and not has_balances:
            missing.append("balances")
        if evidence_type is StatementEvidenceType.POSITION_SNAPSHOT and not has_positions:
            missing.append("positions")
        if has_unresolved_transaction_currency:
            missing.append("transaction_currency")
        return tuple(missing)

    @staticmethod
    def required_fact_labels(fact_kinds: tuple[str, ...]) -> tuple[str, ...]:
        """Translate stable fact identifiers into one human review explanation."""
        labels = {
            "statement_currency": "statement currency",
            "period": "statement period",
            "balances": "opening and closing balances",
            "positions": "positions",
            "transaction_currency": "transaction currency",
        }
        return tuple(labels[kind] for kind in fact_kinds)

    @property
    def requires_review(self) -> bool:
        """Whether source-fact completeness alone blocks automated promotion."""
        return bool(self.missing_required_facts)

    def _semantic_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "source_content_digest": self.source_content_digest,
            "source_type": self.source_type.value,
            "institution": self.institution,
            "account_last4": self.account_last4,
            "period_start": self.period_start.isoformat() if self.period_start is not None else None,
            "period_end": self.period_end.isoformat() if self.period_end is not None else None,
            "balances": [
                {"currency": x.currency, "opening": str(x.opening), "closing": str(x.closing)} for x in self.balances
            ],
            "transactions": [
                {
                    "fact_id": x.fact_id,
                    "transaction_date": x.transaction_date.isoformat(),
                    "description": x.description,
                    "amount": str(x.amount),
                    "direction": x.direction,
                    "currency": x.currency,
                    "balance_after": str(x.balance_after) if x.balance_after is not None else None,
                    "confidence": str(x.confidence) if x.confidence is not None else None,
                }
                for x in self.transactions
            ],
            "positions": [
                {
                    "fact_id": x.fact_id,
                    "symbol": x.symbol,
                    "quantity": str(x.quantity),
                    "market_value": str(x.market_value),
                    "currency": x.currency,
                    "confidence": str(x.confidence) if x.confidence is not None else None,
                    "asset_type": x.asset_type,
                    "sector": x.sector,
                    "geography": x.geography,
                }
                for x in self.positions
            ],
            "confidence": str(self.confidence),
            "balance_validated": self.balance_validated,
            "warnings": list(self.warnings),
            "review_reasons": list(self.review_reasons),
            "provenance": {
                "intake_mode": self.provenance.intake_mode,
                "method": self.provenance.method.value,
                "provider": self.provenance.provider,
                "model": self.provenance.model,
            },
        }
        if self.schema_version != _LEGACY_SCHEMA_VERSION:
            payload["evidence_type"] = self.evidence_type.value
            payload["statement_currency"] = self.statement_currency
        return payload

    def to_payload(self) -> dict[str, Any]:
        return {**self._semantic_payload(), "content_digest": self.content_digest, "result_id": str(self.result_id)}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> StatementExtractionResult:
        schema_version = payload["schema_version"]
        if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported statement extraction schema version: {schema_version}")
        source_type = StatementSourceType(payload["source_type"])
        evidence_type_value = payload.get("evidence_type")
        if evidence_type_value is None:
            if schema_version != _LEGACY_SCHEMA_VERSION:
                raise ValueError("statement extraction evidence_type is required")
            # Legacy payloads did not distinguish a brokerage cash ledger from
            # an empty position snapshot. Treat the ambiguous historical shape
            # as a ledger, which keeps it review-bound when balance facts are absent.
            evidence_type = (
                StatementEvidenceType.POSITION_SNAPSHOT
                if source_type is StatementSourceType.BROKERAGE and payload.get("positions")
                else StatementEvidenceType.TRANSACTION_LEDGER
            )
        else:
            evidence_type = StatementEvidenceType(evidence_type_value)
        if schema_version == _LEGACY_SCHEMA_VERSION:
            legacy_balance_currencies = {item["currency"] for item in payload["balances"]}
            statement_currency = next(iter(legacy_balance_currencies)) if len(legacy_balance_currencies) == 1 else None
        else:
            statement_currency = payload["statement_currency"]
        result = cls(
            schema_version=schema_version,
            producer_version=payload["producer_version"],
            source_content_digest=payload["source_content_digest"],
            source_type=source_type,
            evidence_type=evidence_type,
            institution=payload["institution"],
            account_last4=payload.get("account_last4"),
            period_start=date.fromisoformat(payload["period_start"]) if payload["period_start"] else None,
            period_end=date.fromisoformat(payload["period_end"]) if payload["period_end"] else None,
            balances=tuple(
                StatementBalanceFact(x["currency"], Decimal(x["opening"]), Decimal(x["closing"]))
                for x in payload["balances"]
            ),
            transactions=tuple(
                ExtractedTransactionFact(
                    x["fact_id"],
                    date.fromisoformat(x["transaction_date"]),
                    x["description"],
                    Decimal(x["amount"]),
                    x["direction"],
                    x["currency"],
                    Decimal(x["balance_after"]) if x["balance_after"] is not None else None,
                    Decimal(x["confidence"]) if x["confidence"] is not None else None,
                )
                for x in payload["transactions"]
            ),
            positions=tuple(
                ExtractedPositionFact(
                    x["fact_id"],
                    x["symbol"],
                    Decimal(x["quantity"]),
                    Decimal(x["market_value"]),
                    x["currency"],
                    Decimal(x["confidence"]) if x["confidence"] is not None else None,
                    x.get("asset_type"),
                    x.get("sector"),
                    x.get("geography"),
                )
                for x in payload["positions"]
            ),
            confidence=Decimal(payload["confidence"]),
            balance_validated=payload["balance_validated"],
            warnings=tuple(payload["warnings"]),
            review_reasons=tuple(payload["review_reasons"]),
            provenance=SourceProvenance(
                intake_mode=payload["provenance"]["intake_mode"],
                method=ExtractionMethod(payload["provenance"]["method"]),
                provider=payload["provenance"]["provider"],
                model=payload["provenance"]["model"],
            ),
            statement_currency=statement_currency,
        )
        if payload.get("content_digest") != result.content_digest or payload.get("result_id") != str(result.result_id):
            raise ValueError("statement extraction identity mismatch")
        return result
