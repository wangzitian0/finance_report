"""Deterministic economic disposition for statement transactions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from src.extraction.orm.layer2 import TransactionDirection


class EconomicIntent(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    EXPENSE_REFUND = "expense_refund"
    TRANSFER = "transfer"
    INVESTMENT_PURCHASE = "investment_purchase"
    INVESTMENT_SALE = "investment_sale"
    LOAN_PRINCIPAL = "loan_principal"
    LOAN_INTEREST = "loan_interest"
    CARD_REPAYMENT = "card_repayment"
    UNKNOWN = "unknown"


class IntentProposalOrigin(StrEnum):
    """Closed provenance for a proposed economic intent."""

    REVIEWED_RULE = "reviewed_rule"
    LIVE_LLM = "live_llm"
    RECONCILIATION_FACT = "reconciliation_fact"
    MANUAL_ADJUDICATION = "manual_adjudication"


class DispositionStatus(StrEnum):
    AUTHORITATIVE = "authoritative"
    REVIEW = "review"
    EXCLUDED = "excluded"
    ALREADY_COVERED = "already_covered"


class DispositionMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class StatementDispositionPolicySnapshot:
    """Immutable runtime policy facts attached to a statement disposition decision."""

    schema_version: str
    policy_version: str
    mode: DispositionMode
    machine_confidence_threshold: Decimal
    pnl_effect_confidence_threshold: Decimal
    unknown_intent_outcome: str
    ambiguous_intent_outcome: str
    live_llm_proposals_enabled: bool
    deployment_git_sha: str

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("unsupported statement disposition policy snapshot schema version")
        if not self.policy_version.strip() or len(self.policy_version) > 50:
            raise ValueError("statement disposition policy version is required")
        if not isinstance(self.mode, DispositionMode):
            raise TypeError("statement disposition mode must be DispositionMode")
        for threshold in (self.machine_confidence_threshold, self.pnl_effect_confidence_threshold):
            if not isinstance(threshold, Decimal) or not Decimal("0") <= threshold <= Decimal("1"):
                raise ValueError("statement disposition confidence thresholds must be Decimals within [0, 1]")
        if self.unknown_intent_outcome != "review" or self.ambiguous_intent_outcome != "review":
            raise ValueError("unknown and ambiguous statement intent must route to review")
        if not isinstance(self.live_llm_proposals_enabled, bool):
            raise TypeError("live LLM proposal state must be bool")
        if not self.deployment_git_sha.strip() or len(self.deployment_git_sha) > 64:
            raise ValueError("deployment git SHA is required and must fit the trace contract")

    def semantic_payload(self) -> dict[str, str | bool]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "mode": self.mode.value,
            "machine_confidence_threshold": str(self.machine_confidence_threshold),
            "pnl_effect_confidence_threshold": str(self.pnl_effect_confidence_threshold),
            "unknown_intent_outcome": self.unknown_intent_outcome,
            "ambiguous_intent_outcome": self.ambiguous_intent_outcome,
            "live_llm_proposals_enabled": self.live_llm_proposals_enabled,
            "deployment_git_sha": self.deployment_git_sha,
        }

    @property
    def semantic_digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.semantic_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @property
    def trace_version(self) -> str:
        """Keep exact runtime facts inside TraceRecord's immutable assertion version."""
        return (
            f"v{self.schema_version}|{self.policy_version}|{self.mode.value}|"
            f"machine:{self.machine_confidence_threshold}|pnl:{self.pnl_effect_confidence_threshold}|"
            f"unknown:{self.unknown_intent_outcome}|ambiguous:{self.ambiguous_intent_outcome}|"
            f"llm:{int(self.live_llm_proposals_enabled)}|git:{self.deployment_git_sha}"
        )


def intent_matches_counter_account(intent: EconomicIntent, account_type: str) -> bool:
    """Return whether a counter-account side can represent an economic intent.

    The policy consumes the account type as a string so its value-object layer
    stays independent of ledger ORM classes. Every writer must use this one
    table instead of inferring P&L meaning from transaction direction.
    """
    compatible_types = {
        EconomicIntent.INCOME: {"INCOME"},
        EconomicIntent.EXPENSE: {"EXPENSE"},
        EconomicIntent.EXPENSE_REFUND: {"EXPENSE"},
        EconomicIntent.LOAN_INTEREST: {"EXPENSE"},
        EconomicIntent.INVESTMENT_PURCHASE: {"ASSET"},
        EconomicIntent.INVESTMENT_SALE: {"ASSET"},
        EconomicIntent.LOAN_PRINCIPAL: {"LIABILITY"},
        EconomicIntent.CARD_REPAYMENT: {"LIABILITY"},
        EconomicIntent.TRANSFER: {"ASSET"},
    }
    return account_type in compatible_types.get(intent, set())


@dataclass(frozen=True, slots=True)
class StatementTransaction:
    transaction_id: UUID
    transaction_date: date
    amount: Decimal
    currency: str
    direction: TransactionDirection
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or self.amount <= 0:
            raise ValueError("transaction amount must be a positive Decimal")
        if not isinstance(self.direction, TransactionDirection):
            raise TypeError("direction must be TransactionDirection")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if not self.description.strip():
            raise ValueError("description is required")


@dataclass(frozen=True, slots=True)
class IntentProposal:
    schema_version: str
    policy_version: str
    origin: IntentProposalOrigin
    intent: EconomicIntent
    category: str | None
    confidence: Decimal | None
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("unsupported intent proposal schema version")
        if not self.policy_version.strip():
            raise ValueError("intent policy version is required")
        if not isinstance(self.origin, IntentProposalOrigin):
            raise TypeError("intent proposal origin must be IntentProposalOrigin")
        if not isinstance(self.intent, EconomicIntent):
            raise TypeError("intent must be EconomicIntent")
        if self.origin is IntentProposalOrigin.MANUAL_ADJUDICATION:
            if self.confidence is not None:
                raise ValueError("manual adjudication cannot claim machine confidence")
        elif not isinstance(self.confidence, Decimal) or not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("machine intent confidence must be a Decimal within [0, 1]")
        if not self.evidence or any(not value.strip() for value in self.evidence):
            raise ValueError("intent evidence is required")


@dataclass(frozen=True, slots=True)
class DispositionContext:
    accepted_transfer_match: bool = False
    counter_account_id: UUID | None = None
    counter_account_type: str | None = None


@dataclass(frozen=True, slots=True)
class DispositionCommand:
    counter_account_id: UUID
    debit_role: str
    credit_role: str

    def __post_init__(self) -> None:
        if {self.debit_role, self.credit_role} != {"custody", "counter"}:
            raise ValueError("command must balance custody and counter roles")


@dataclass(frozen=True, slots=True)
class DispositionDecision:
    transaction_id: UUID
    policy_version: str
    status: DispositionStatus
    intent: EconomicIntent
    category: str | None
    reason_code: str
    command: DispositionCommand | None
    pnl_effect: bool
    mode: DispositionMode

    @property
    def should_apply(self) -> bool:
        return self.mode is DispositionMode.ENFORCE and self.status is DispositionStatus.AUTHORITATIVE

    @property
    def semantic_digest(self) -> str:
        command = None
        if self.command:
            command = {
                "counter_account_id": str(self.command.counter_account_id),
                "debit_role": self.command.debit_role,
                "credit_role": self.command.credit_role,
            }
        payload = {
            "transaction_id": str(self.transaction_id),
            "policy_version": self.policy_version,
            "status": self.status.value,
            "intent": self.intent.value,
            "category": self.category,
            "reason_code": self.reason_code,
            "command": command,
            "pnl_effect": self.pnl_effect,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DispositionPolicy:
    """One policy from typed intent and context to balanced command or review."""

    version: str = "disposition-v1"
    authoritative_threshold: Decimal = Decimal("0.85")

    def decide(
        self,
        transaction: StatementTransaction,
        *,
        proposal: IntentProposal | None,
        context: DispositionContext,
        mode: DispositionMode = DispositionMode.ENFORCE,
    ) -> DispositionDecision:
        if proposal is None:
            return self._review(transaction, EconomicIntent.UNKNOWN, "intent_missing", mode=mode)
        if (
            proposal.origin is not IntentProposalOrigin.MANUAL_ADJUDICATION
            and proposal.confidence is not None
            and proposal.confidence < self.authoritative_threshold
        ):
            return self._review(transaction, proposal.intent, "intent_below_threshold", proposal.category, mode)
        if proposal.intent is EconomicIntent.TRANSFER:
            return DispositionDecision(
                transaction.transaction_id,
                self.version,
                DispositionStatus.ALREADY_COVERED if context.accepted_transfer_match else DispositionStatus.REVIEW,
                proposal.intent,
                None,
                "accepted_transfer_match" if context.accepted_transfer_match else "transfer_unmatched",
                None,
                False,
                mode,
            )
        if proposal.intent is EconomicIntent.UNKNOWN:
            return self._review(transaction, proposal.intent, "intent_unsupported", mode=mode)
        if context.counter_account_id is None:
            return self._review(transaction, proposal.intent, "counter_account_missing", proposal.category, mode)
        if context.counter_account_type is not None and not intent_matches_counter_account(
            proposal.intent, context.counter_account_type
        ):
            return self._review(
                transaction, proposal.intent, "intent_counter_account_conflict", proposal.category, mode
            )

        required_direction = {
            EconomicIntent.INCOME: TransactionDirection.IN,
            EconomicIntent.EXPENSE: TransactionDirection.OUT,
            EconomicIntent.EXPENSE_REFUND: TransactionDirection.IN,
            EconomicIntent.INVESTMENT_PURCHASE: TransactionDirection.OUT,
            EconomicIntent.INVESTMENT_SALE: TransactionDirection.IN,
            EconomicIntent.LOAN_PRINCIPAL: None,
            EconomicIntent.LOAN_INTEREST: TransactionDirection.OUT,
            EconomicIntent.CARD_REPAYMENT: TransactionDirection.OUT,
        }[proposal.intent]
        if required_direction is not None and transaction.direction is not required_direction:
            return self._review(transaction, proposal.intent, "intent_direction_conflict", proposal.category, mode)
        pnl_intents = {
            EconomicIntent.INCOME,
            EconomicIntent.EXPENSE,
            EconomicIntent.EXPENSE_REFUND,
            EconomicIntent.LOAN_INTEREST,
        }
        if proposal.intent in pnl_intents and not proposal.category:
            return self._review(transaction, proposal.intent, "pnl_category_missing", mode=mode)

        custody_debit = transaction.direction is TransactionDirection.IN
        command = DispositionCommand(
            context.counter_account_id,
            "custody" if custody_debit else "counter",
            "counter" if custody_debit else "custody",
        )
        return DispositionDecision(
            transaction.transaction_id,
            self.version,
            DispositionStatus.AUTHORITATIVE,
            proposal.intent,
            proposal.category,
            "policy_authoritative",
            command,
            proposal.intent in pnl_intents,
            mode,
        )

    def _review(
        self,
        transaction: StatementTransaction,
        intent: EconomicIntent,
        reason: str,
        category: str | None = None,
        mode: DispositionMode = DispositionMode.ENFORCE,
    ) -> DispositionDecision:
        return DispositionDecision(
            transaction.transaction_id,
            self.version,
            DispositionStatus.REVIEW,
            intent,
            category,
            reason,
            None,
            False,
            mode,
        )
