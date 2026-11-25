from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.config import settings
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
from src.extraction.extension.disposition_policy import statement_disposition_policy_for_user
from src.extraction.extension.disposition_trace import build_disposition_trace_records


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({"schema_version": "2"}, ValueError),
        ({"policy_version": ""}, ValueError),
        ({"mode": "enforce"}, TypeError),
        ({"machine_confidence_threshold": Decimal("1.01")}, ValueError),
        ({"unknown_intent_outcome": "accept"}, ValueError),
        ({"live_llm_proposals_enabled": 1}, TypeError),
        ({"deployment_git_sha": ""}, ValueError),
    ],
)
def test_statement_disposition_policy_snapshot_rejects_invalid_contract_values(updates, error):
    with pytest.raises(error):
        replace(current_statement_disposition_policy_snapshot(), **updates)


def _transaction(
    direction: TransactionDirection, *, description: str = "opaque recorded description"
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
    confidence: Decimal = Decimal("0.95"),
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


def test_AC_extraction_disposition_1_2_never_uses_direction_and_separates_pnl():
    policy = DispositionPolicy()
    incoming, outgoing = (
        policy.decide(_transaction(TransactionDirection.IN), proposal=None, context=DispositionContext()),
        policy.decide(_transaction(TransactionDirection.OUT), proposal=None, context=DispositionContext()),
    )
    assert (incoming.status, outgoing.status, incoming.command, outgoing.command) == (
        DispositionStatus.REVIEW,
        DispositionStatus.REVIEW,
        None,
        None,
    )
    assert "uncategorized" not in repr((incoming, outgoing)).lower()

    txn = _transaction(TransactionDirection.OUT)
    transfer = policy.decide(
        txn, proposal=_proposal(EconomicIntent.TRANSFER), context=DispositionContext(accepted_transfer_match=True)
    )
    assert (transfer.status, transfer.command, transfer.pnl_effect) == (DispositionStatus.ALREADY_COVERED, None, False)
    for intent in (EconomicIntent.INVESTMENT_PURCHASE, EconomicIntent.LOAN_PRINCIPAL, EconomicIntent.CARD_REPAYMENT):
        miss = policy.decide(txn, proposal=_proposal(intent), context=DispositionContext())
        assert (miss.status, miss.command, miss.pnl_effect) == (DispositionStatus.REVIEW, None, False)

    cid = uuid4()
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
    for desc, direction, intent, category, pnl_effect in cases:
        dec = policy.decide(
            _transaction(direction, description=desc),
            proposal=_proposal(intent, category=category),
            context=DispositionContext(counter_account_id=cid),
        )
        assert dec.command is not None and (
            dec.status,
            dec.command.counter_account_id,
            dec.command.debit_role,
            dec.command.credit_role,
            dec.pnl_effect,
        ) == (
            DispositionStatus.AUTHORITATIVE,
            cid,
            "custody" if direction is TransactionDirection.IN else "counter",
            "counter" if direction is TransactionDirection.IN else "custody",
            pnl_effect,
        ), desc


def test_AC_extraction_disposition_rollout_and_trace_authority():
    policy, cid = DispositionPolicy(), uuid4()
    txn = _transaction(TransactionDirection.IN)
    decisions = {
        mode: policy.decide(
            txn,
            proposal=_proposal(EconomicIntent.INCOME, category="SALARY"),
            context=DispositionContext(counter_account_id=cid),
            mode=mode,
        )
        for mode in DispositionMode
    }
    assert len({d.semantic_digest for d in decisions.values()}) == 1 and all(
        d.status is DispositionStatus.AUTHORITATIVE for d in decisions.values()
    )
    assert (
        decisions[DispositionMode.OFF].should_apply,
        decisions[DispositionMode.OBSERVE].should_apply,
        decisions[DispositionMode.ENFORCE].should_apply,
    ) == (False, False, True)

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
    for origin, intent, direction, category, confidence, expected_auth in cases:
        tx = _transaction(direction)
        prop = _proposal(intent, category=category, origin=origin, confidence=confidence)
        dec = policy.decide(
            tx,
            proposal=prop,
            context=DispositionContext(
                accepted_transfer_match=origin is IntentProposalOrigin.RECONCILIATION_FACT, counter_account_id=cid
            ),
        )
        cand, _inv, guard, disp = build_disposition_trace_records(
            user_id=uuid4(),
            execution_id=f"test:{tx.transaction_id}",
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
            transaction=tx,
            proposal=prop,
            decision=dec,
        )
        assert (
            (
                cand.authority.package,
                cand.authority.tier,
                cand.authority.proof_kind,
                cand.authority.provenance,
                cand.authority.execution_stage,
                cand.score.value if cand.score is not None else None,
            ),
            guard.authority.tier,
            disp.authority.tier,
        ) == (expected_auth, "CODE-ONLY", "CODE-ONLY")


@pytest.mark.parametrize(
    ("origin", "intent", "direction", "category"),
    [
        (IntentProposalOrigin.LIVE_LLM, EconomicIntent.EXPENSE, TransactionDirection.OUT, "OTHER_EXPENSE"),
        (IntentProposalOrigin.LIVE_LLM, EconomicIntent.INCOME, TransactionDirection.IN, "OTHER_INCOME"),
        (IntentProposalOrigin.REVIEWED_RULE, EconomicIntent.EXPENSE, TransactionDirection.OUT, "DINING"),
    ],
)
def test_AC_extraction_disposition_transfer_fact_1_accepted_match_outranks_non_manual(
    origin, intent, direction, category
):
    dec = DispositionPolicy().decide(
        _transaction(direction),
        proposal=_proposal(intent, category=category, origin=origin, confidence=Decimal("0.95")),
        context=DispositionContext(accepted_transfer_match=True, counter_account_id=uuid4()),
    )
    assert (dec.status, dec.reason_code, dec.command, dec.pnl_effect) == (
        DispositionStatus.ALREADY_COVERED,
        "accepted_transfer_match",
        None,
        False,
    )


def test_AC_extraction_disposition_transfer_fact_2_3_and_auto_accept_snapshot():
    p_dec = DispositionPolicy().decide(
        _transaction(TransactionDirection.OUT),
        proposal=_proposal(
            EconomicIntent.EXPENSE, category="DINING", origin=IntentProposalOrigin.MANUAL_ADJUDICATION, confidence=None
        ),
        context=DispositionContext(accepted_transfer_match=True, counter_account_id=uuid4()),
    )
    m_dec = DispositionPolicy().decide(
        _transaction(TransactionDirection.OUT),
        proposal=_proposal(
            EconomicIntent.EXPENSE, category="DINING", origin=IntentProposalOrigin.LIVE_LLM, confidence=Decimal("0.95")
        ),
        context=DispositionContext(accepted_transfer_match=False, counter_account_id=uuid4()),
    )
    assert (p_dec.status, p_dec.pnl_effect, m_dec.status, m_dec.pnl_effect) == (
        DispositionStatus.AUTHORITATIVE,
        True,
        DispositionStatus.AUTHORITATIVE,
        True,
    )


async def test_AC_extraction_auto_accept_8_snapshot_records_user_classification_setting(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    test_user.ai_settings = {"enable_ai_classification": False}
    await db.flush()
    off_snap = current_statement_disposition_policy_snapshot(
        policy=await statement_disposition_policy_for_user(db, test_user.id)
    )
    test_user.ai_settings = {"enable_ai_classification": True}
    await db.flush()
    on_snap = current_statement_disposition_policy_snapshot(
        policy=await statement_disposition_policy_for_user(db, test_user.id)
    )
    assert (off_snap.live_llm_proposals_enabled, on_snap.live_llm_proposals_enabled) == (False, True)
