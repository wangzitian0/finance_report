"""Economic-disposition contract tests for statement transactions."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.extraction import (
    DispositionContext,
    DispositionMode,
    DispositionPolicy,
    DispositionStatus,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
    TransactionDirection,
    current_statement_disposition_policy_snapshot,
)
from src.extraction.extension.disposition_trace import build_disposition_trace_records


@pytest.mark.parametrize(
    ("updates", "error"),
    (
        ({"schema_version": "2"}, ValueError),
        ({"policy_version": ""}, ValueError),
        ({"mode": "enforce"}, TypeError),
        ({"machine_confidence_threshold": Decimal("1.01")}, ValueError),
        ({"unknown_intent_outcome": "accept"}, ValueError),
        ({"live_llm_proposals_enabled": 1}, TypeError),
        ({"deployment_git_sha": ""}, ValueError),
    ),
)
def test_statement_disposition_policy_snapshot_rejects_invalid_contract_values(updates, error):
    snapshot = current_statement_disposition_policy_snapshot()

    with pytest.raises(error):
        replace(snapshot, **updates)


def _transaction(
    direction: TransactionDirection,
    *,
    description: str = "opaque recorded description",
) -> StatementTransaction:
    return StatementTransaction(
        transaction_id=uuid4(),
        transaction_date=date(2026, 1, 5),
        amount=Decimal("100.00"),
        currency="SGD",
        direction=direction,
        description=description,
    )


def _proposal(
    intent: EconomicIntent,
    *,
    category: str | None = None,
    origin: IntentProposalOrigin = IntentProposalOrigin.REVIEWED_RULE,
    confidence: Decimal | None = Decimal("0.95"),
) -> IntentProposal:
    return IntentProposal(
        schema_version="1",
        policy_version="economic-intent-v1",
        origin=origin,
        intent=intent,
        category=category,
        confidence=confidence,
        evidence=("recorded-description",),
    )


def test_AC_extraction_disposition_1_never_uses_direction_as_intent():
    """AC-extraction.disposition.1: direction alone never creates P&L authority."""
    policy = DispositionPolicy()

    incoming = policy.decide(_transaction(TransactionDirection.IN), proposal=None, context=DispositionContext())
    outgoing = policy.decide(_transaction(TransactionDirection.OUT), proposal=None, context=DispositionContext())

    assert incoming.status is DispositionStatus.REVIEW
    assert outgoing.status is DispositionStatus.REVIEW
    assert incoming.command is None
    assert outgoing.command is None
    assert "uncategorized" not in repr((incoming, outgoing)).lower()


def test_AC_extraction_disposition_2_principal_and_transfer_never_enter_pnl():
    """AC-extraction.disposition.2: balance-sheet flows cannot leak into P&L."""
    policy = DispositionPolicy()
    transaction = _transaction(TransactionDirection.OUT)

    transfer = policy.decide(
        transaction,
        proposal=_proposal(EconomicIntent.TRANSFER),
        context=DispositionContext(accepted_transfer_match=True),
    )
    assert transfer.status is DispositionStatus.ALREADY_COVERED
    assert transfer.command is None

    for intent in (
        EconomicIntent.INVESTMENT_PURCHASE,
        EconomicIntent.LOAN_PRINCIPAL,
        EconomicIntent.CARD_REPAYMENT,
    ):
        missing_context = policy.decide(
            transaction,
            proposal=_proposal(intent),
            context=DispositionContext(),
        )
        assert missing_context.status is DispositionStatus.REVIEW
        assert missing_context.command is None
        assert missing_context.pnl_effect is False


def test_disposition_policy_semantic_table_yields_exact_commands():
    """Pure-policy table: recorded semantics determine exact accounting roles."""
    policy = DispositionPolicy()
    counter_account_id = uuid4()
    cases = (
        ("Salary", TransactionDirection.IN, EconomicIntent.INCOME, "SALARY", True),
        ("Groceries", TransactionDirection.OUT, EconomicIntent.EXPENSE, "GROCERIES", True),
        ("Merchant refund", TransactionDirection.IN, EconomicIntent.EXPENSE_REFUND, "GROCERIES", True),
        ("Cash dividend", TransactionDirection.IN, EconomicIntent.INCOME, "DIVIDEND", True),
        ("Broker fee", TransactionDirection.OUT, EconomicIntent.EXPENSE, "INVESTMENT_FEE", True),
        ("Buy security", TransactionDirection.OUT, EconomicIntent.INVESTMENT_PURCHASE, None, False),
        ("Sell security", TransactionDirection.IN, EconomicIntent.INVESTMENT_SALE, None, False),
        ("Loan drawdown", TransactionDirection.IN, EconomicIntent.LOAN_PRINCIPAL, None, False),
        ("Loan repayment", TransactionDirection.OUT, EconomicIntent.LOAN_PRINCIPAL, None, False),
        ("Loan interest", TransactionDirection.OUT, EconomicIntent.LOAN_INTEREST, "LOAN_INTEREST", True),
        ("Card repayment", TransactionDirection.OUT, EconomicIntent.CARD_REPAYMENT, None, False),
    )

    for description, direction, intent, category, pnl_effect in cases:
        decision = policy.decide(
            _transaction(direction, description=description),
            proposal=_proposal(intent, category=category),
            context=DispositionContext(counter_account_id=counter_account_id),
        )

        assert decision.status is DispositionStatus.AUTHORITATIVE, description
        assert decision.command is not None
        assert decision.command.counter_account_id == counter_account_id
        assert decision.command.debit_role == ("custody" if direction is TransactionDirection.IN else "counter")
        assert decision.command.credit_role == ("counter" if direction is TransactionDirection.IN else "custody")
        assert decision.pnl_effect is pnl_effect

    transfer = policy.decide(
        _transaction(TransactionDirection.OUT, description="Own-account transfer"),
        proposal=_proposal(EconomicIntent.TRANSFER),
        context=DispositionContext(accepted_transfer_match=True),
    )
    assert transfer.status is DispositionStatus.ALREADY_COVERED
    assert transfer.command is None
    assert transfer.pnl_effect is False


def test_AC_extraction_disposition_rollout_1_modes_share_one_decision():
    """AC-extraction.disposition-rollout.1: mode changes application, never calculation."""
    policy = DispositionPolicy()
    transaction = _transaction(TransactionDirection.IN)
    proposal = _proposal(EconomicIntent.INCOME, category="SALARY")
    context = DispositionContext(counter_account_id=uuid4())

    decisions = {
        mode: policy.decide(transaction, proposal=proposal, context=context, mode=mode) for mode in DispositionMode
    }

    assert {decision.semantic_digest for decision in decisions.values()}.__len__() == 1
    assert all(decision.status is DispositionStatus.AUTHORITATIVE for decision in decisions.values())
    assert decisions[DispositionMode.OFF].should_apply is False
    assert decisions[DispositionMode.OBSERVE].should_apply is False
    assert decisions[DispositionMode.ENFORCE].should_apply is True


def test_AC_extraction_disposition_4_trace_authority_follows_explicit_proposal_origin():
    """AC-extraction.disposition.4: trace authority is derived from origin, never intent."""
    policy = DispositionPolicy()
    counter_account_id = uuid4()
    cases = (
        (
            IntentProposalOrigin.REVIEWED_RULE,
            EconomicIntent.INCOME,
            TransactionDirection.IN,
            "SALARY",
            Decimal("0.95"),
            ("extraction", "CODE-ONLY", "exact", "deterministic", "product.runtime", Decimal("0.95")),
        ),
        (
            IntentProposalOrigin.LIVE_LLM,
            EconomicIntent.INCOME,
            TransactionDirection.IN,
            "SALARY",
            Decimal("0.95"),
            ("extraction", "LLM-LED", "invariant", "live_llm", "product.runtime", Decimal("0.95")),
        ),
        (
            IntentProposalOrigin.RECONCILIATION_FACT,
            EconomicIntent.TRANSFER,
            TransactionDirection.OUT,
            None,
            Decimal("0.95"),
            ("extraction", "CODE-LED", "property", "deterministic", "product.runtime", Decimal("0.95")),
        ),
        (
            IntentProposalOrigin.MANUAL_ADJUDICATION,
            EconomicIntent.EXPENSE,
            TransactionDirection.OUT,
            "DINING",
            None,
            ("reconciliation", "CODE-ONLY", "exact", "manual", "manual.adjudication", None),
        ),
    )

    for origin, intent, direction, category, confidence, expected_authority in cases:
        transaction = _transaction(direction)
        proposal = _proposal(intent, category=category, origin=origin, confidence=confidence)
        decision = policy.decide(
            transaction,
            proposal=proposal,
            context=DispositionContext(
                accepted_transfer_match=origin is IntentProposalOrigin.RECONCILIATION_FACT,
                counter_account_id=counter_account_id,
            ),
        )
        candidate, _invariant, guard, disposition = build_disposition_trace_records(
            user_id=uuid4(),
            execution_id=f"test:{transaction.transaction_id}",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
            transaction=transaction,
            proposal=proposal,
            decision=decision,
        )

        assert (
            candidate.authority.package,
            candidate.authority.tier,
            candidate.authority.proof_kind,
            candidate.authority.provenance,
            candidate.authority.execution_stage,
            candidate.score.value if candidate.score is not None else None,
        ) == expected_authority
        assert guard.authority.tier == "CODE-ONLY"
        assert disposition.authority.tier == "CODE-ONLY"
