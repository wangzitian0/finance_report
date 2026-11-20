from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy import select

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType
from src.extraction import BankStatementStatus, EconomicIntent, Stage1Status
from src.extraction.extension import statement_validation as statement_validation_mod
from src.extraction.extension.evidence_graph_materialization import EvidenceGraphMaterializationService
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.platform import DomainError
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.extension.review_queue import accept_match as accept_match_service
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.request_context import RequestContext
from src.routers import reconciliation as reconciliation_router, statements as statements_router
from src.schemas.extraction import ResolveConflictsRequest, Stage1ApprovalRequest
from src.schemas.reconciliation import ConsistencyCheckRunRequest, ReconciliationMatchBatchRequest, ResolveCheckRequest
from tests.api._statement_router_fixtures import add_reviewed_disposition_rule, add_txn, build_statement, create_statement_account
from tests.factories import UserFactory
from tests.statement_ingestion import anchored_reviewed_posting_inputs


async def _seed_approved_statement_with_txn(db, user_id, name: str = "DBS", amount: Decimal = Decimal("50.00"), description: str = "Payment", txn_date: date = date(2025, 1, 15), direction: str = "OUT"):
    account = await create_statement_account(db, user_id, f"{name} Account")
    statement = build_statement(user_id, f"hash_{uuid4().hex[:8]}", 90)
    statement.status, statement.account_id = BankStatementStatus.APPROVED, account.id
    db.add(statement)
    await db.commit()
    txn = await add_txn(db, statement, txn_date=txn_date, description=description, amount=amount, direction=direction)
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return account, statement, txn


async def _seed_approved_statement_with_posted_txn(db, user_id, name: str = "DBS", amount: Decimal = Decimal("50.00"), description: str = "Payment", txn_date: date = date(2025, 1, 15), direction: str = "OUT", intent: EconomicIntent = EconomicIntent.EXPENSE, source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED):
    account, statement, txn = await _seed_approved_statement_with_txn(db, user_id, name=name, amount=amount, description=description, txn_date=txn_date, direction=direction)
    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(db, user_id=user_id, transaction=txn, intent=intent)
    entry = await create_entry_from_txn(db, txn, user_id=user_id, auto_post=True, source_type=source_type, disposition=decision, counter_account=counter_account, source_decision=source_decision, trace_emitter=trace_emitter, base_currency="SGD")
    await db.flush()
    return account, statement, txn, entry


def _chk(uid, *, ctype=CheckType.DUPLICATE, cstat=CheckStatus.PENDING, run_id: str | None = None, related=None, sev: str = "high") -> ConsistencyCheck:
    return ConsistencyCheck(user_id=uid, run_id=run_id, check_type=ctype, status=cstat, related_txn_ids=related or ["txn1"], details={"count": 1}, severity=sev)


def _match(txn_id, *, eids=None, score: int = 85, run_id: str | None = None) -> ReconciliationMatch:
    return ReconciliationMatch(atomic_txn_id=txn_id, journal_entry_ids=eids or [], run_id=run_id, match_score=score, status=ReconciliationStatus.PENDING_REVIEW, version=1)


async def test_stage2_queue_checks_and_resolution(db, test_user):
    ctx = RequestContext(db, test_user.id)
    eq, el = await reconciliation_router.get_stage2_review_queue(ctx), await reconciliation_router.list_consistency_checks(ctx)
    assert (eq.pending_matches, eq.consistency_checks, eq.has_unresolved_checks, el.total, el.items) == ([], [], False, 0, [])

    _, stmt, txn = await _seed_approved_statement_with_txn(db, test_user.id, "Stage 2 Queue")
    db.add(_match(txn.id, score=75))
    await db.commit()
    res = await reconciliation_router.get_stage2_review_queue(ctx)
    assert len(res.pending_matches) == 1 and (res.pending_matches[0].status, res.pending_matches[0].match_score, res.pending_matches[0].confidence_tier) == ("pending_review", 75, "MEDIUM")

    run_res = await reconciliation_router.run_stage2_checks(request=ConsistencyCheckRunRequest(statement_id=stmt.id), ctx=ctx)
    assert run_res.total >= 0 and isinstance(run_res.items, list)
    with pytest.raises(DomainError) as exc_404:
        await reconciliation_router.run_stage2_checks(request=ConsistencyCheckRunRequest(statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000")), ctx=ctx)
    assert exc_404.value.status_code == status.HTTP_404_NOT_FOUND

    c1, c2 = _chk(test_user.id, related=["txn1", "txn2"]), _chk(test_user.id, ctype=CheckType.TRANSFER_PAIR, cstat=CheckStatus.APPROVED, sev="medium")
    db.add_all([c1, c2])
    await db.commit()
    await db.refresh(c1)
    assert (await reconciliation_router.list_consistency_checks(ctx, status=CheckStatus.PENDING)).items[0].check_type == CheckType.DUPLICATE
    assert (await reconciliation_router.list_consistency_checks(ctx, check_type=CheckType.TRANSFER_PAIR)).items[0].status == CheckStatus.APPROVED

    for cid, req, code in ((c1.id, ResolveCheckRequest(action="invalid"), 400), (statements_router.UUID("00000000-0000-0000-0000-000000000000"), ResolveCheckRequest(action="approve"), 404)):
        with pytest.raises(DomainError) as exc:
            await reconciliation_router.resolve_consistency_check(check_id=cid, request=req, ctx=ctx)
        assert exc.value.status_code == code

    with pytest.raises(DomainError) as exc_blk:
        await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="accept", match_ids=[]), ctx=ctx)
    assert exc_blk.value.status_code == status.HTTP_409_CONFLICT and "unresolved" in exc_blk.value.detail
    resolved = await reconciliation_router.resolve_consistency_check(check_id=c1.id, request=ResolveCheckRequest(action="approve", note="Looks fine"), ctx=ctx)
    assert (resolved.status, resolved.resolution_note) == (CheckStatus.APPROVED, "Looks fine")


@pytest.mark.parametrize(("txns_spec", "closing"), [([("Duplicate deposit", "20.00", "IN"), ("Duplicate deposit", "20.00", "IN")], "140.00"), ([("Transfer out", "20.00", "OUT"), ("Transfer in", "20.00", "IN")], "100.00")])
async def test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts(db, test_user, txns_spec, closing):
    acc = await create_statement_account(db, test_user.id, f"Stage1 Conflict {uuid4().hex[:4]}")
    stmt = build_statement(test_user.id, f"hash_{uuid4().hex[:8]}", 90)
    stmt.status, stmt.stage1_status, stmt.account_id, stmt.opening_balance, stmt.closing_balance = BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, acc.id, Decimal("100.00"), Decimal(closing)
    db.add(stmt)
    await db.commit()
    for desc, amt, dir_ in txns_spec:
        await add_txn(db, stmt, txn_date=date(2025, 1, 15), description=desc, amount=Decimal(amt), direction=dir_)
    await db.commit()
    with pytest.raises(DomainError) as exc:
        await statements_router.approve_statement_stage1(statement_id=stmt.id, request=Stage1ApprovalRequest(notes=None), ctx=RequestContext(db, test_user.id))
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST and "unresolved duplicate or transfer-pair" in exc.value.detail


async def test_conflict_confirmation_has_no_action_field_and_needs_no_body(client, db, test_user):
    """#2958: the route records one confirmation for the statement. It takes no action and links no rows."""
    assert "action" not in ResolveConflictsRequest.model_fields
    stmt = build_statement(test_user.id, "hash_stage1_confirm_no_body", 90)
    stmt.status = BankStatementStatus.PARSED
    db.add(stmt)
    await db.commit()
    assert stmt.stage1_conflicts_resolved_at is None
    for body in (None, {}, {"note": "rows checked"}):
        response = await client.post(f"/statements/{stmt.id}/conflict-resolutions", json=body)
        assert (response.status_code, response.json()["resolved"]) == (status.HTTP_200_OK, True)
    await db.refresh(stmt)
    assert stmt.stage1_conflicts_resolved_at is not None


async def test_AC16_34_resolve_conflicts_and_reject_reset(db, test_user):
    uid, ctx = test_user.id, RequestContext(db, test_user.id)
    acc = await create_statement_account(db, uid, "Resolve Conflict Account")
    stmt = build_statement(uid, "hash_stage1_resolve", 90)
    stmt.status, stmt.stage1_status, stmt.account_id, stmt.opening_balance, stmt.closing_balance = BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, acc.id, Decimal("100.00"), Decimal("140.00")
    db.add(stmt)
    await db.commit()
    for _ in range(2):
        await add_txn(db, stmt, txn_date=date(2025, 1, 15), description="Duplicate deposit", amount=Decimal("20.00"), direction="IN")
    await add_reviewed_disposition_rule(db, user_id=uid, keyword="duplicate deposit", account_type=AccountType.INCOME, category="SALARY")
    await db.commit()

    with pytest.raises(DomainError) as exc_blk:
        await statements_router.approve_statement_stage1(statement_id=stmt.id, request=Stage1ApprovalRequest(), ctx=ctx)
    assert exc_blk.value.status_code == status.HTTP_400_BAD_REQUEST
    assert (await statements_router.resolve_review_conflicts(statement_id=stmt.id, request=ResolveConflictsRequest(), ctx=ctx)).resolved is True
    assert (await statements_router.get_review_conflicts(statement_id=stmt.id, ctx=ctx)).resolved is True
    approved = await statements_router.approve_statement_stage1(statement_id=stmt.id, request=Stage1ApprovalRequest(), ctx=ctx)
    assert (approved.id, approved.status) == (stmt.id, BankStatementStatus.APPROVED)

    with pytest.raises(DomainError) as exc_404:
        await statements_router.resolve_review_conflicts(statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"), request=ResolveConflictsRequest(), ctx=ctx)
    assert exc_404.value.status_code == status.HTTP_404_NOT_FOUND

    stmt2 = build_statement(uid, "hash_stage1_resolve_reset", 90)
    stmt2.status = BankStatementStatus.PARSED
    db.add(stmt2)
    await db.commit()
    await statements_router.resolve_review_conflicts(statement_id=stmt2.id, request=ResolveConflictsRequest(), ctx=ctx)
    await db.refresh(stmt2)
    assert stmt2.stage1_conflicts_resolved_at is not None
    await statement_validation_mod.reject_statement(db, stmt2.id, uid, reason="reparse")
    await db.commit()
    await db.refresh(stmt2)
    assert stmt2.stage1_conflicts_resolved_at is None


async def test_AC16_32_3_and_AC19_11_1_queue_and_run_id_scoping(db, test_user):
    ctx = RequestContext(db, test_user.id)
    db.add_all([_chk(test_user.id, run_id="run-queue", related=[f"txn-{i}"]) for i in range(55)])
    db.add_all([_chk(test_user.id, run_id="run-123", related=["txn-in-run"]), _chk(test_user.id, run_id="run-456", related=["txn-other-run"])])
    await db.commit()
    assert len((await reconciliation_router.get_stage2_review_queue(ctx)).consistency_checks) == 57
    listed = await reconciliation_router.list_consistency_checks(ctx, run_id="run-123")
    assert listed.total == 1 and listed.items[0].related_txn_ids == ["txn-in-run"]

    uid2 = (await UserFactory.create_async(db)).id
    ctx2 = RequestContext(db, uid2)
    _, _, txn_in, _ = await _seed_approved_statement_with_posted_txn(db, uid2, "DBS Run Scope")
    _, _, txn_out = await _seed_approved_statement_with_txn(db, uid2, "DBS Other Run")
    m_in, m_out = _match(txn_in.id, score=95, run_id="run-123"), _match(txn_out.id, score=95, run_id="run-456")
    db.add_all([m_in, m_out])
    await db.commit()
    assert [str(m.id) for m in (await reconciliation_router.get_stage2_review_queue(ctx2, run_id="run-123")).pending_matches] == [str(m_in.id)]
    assert (await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="accept", match_ids=[m_in.id, m_out.id], run_id="run-123"), ctx=ctx2)).approved_count == 1
    await db.refresh(m_in)
    await db.refresh(m_out)
    assert (m_in.status, m_out.status) == (ReconciliationStatus.ACCEPTED, ReconciliationStatus.PENDING_REVIEW)


async def test_batch_accept_reject_idempotency_errors_and_evidence_graph(db, test_user):
    uid, ctx = test_user.id, RequestContext(db, test_user.id)
    _, _, txn_ref, entry_ref = await _seed_approved_statement_with_posted_txn(db, uid, "DBS Ref", txn_date=date(2025, 1, 16))
    _, _, txn_exist, entry_exist = await _seed_approved_statement_with_posted_txn(db, uid, "DBS Existing", txn_date=date(2025, 1, 18))
    m_ref, m_exist = _match(txn_ref.id, eids=[str(entry_ref.id)]), _match(txn_exist.id)
    db.add_all([m_ref, m_exist])
    await db.commit()
    r1 = await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="accept", match_ids=[m_ref.id, m_exist.id]), ctx=ctx)
    await db.refresh(m_ref)
    await db.refresh(m_exist)
    await db.refresh(entry_ref)
    await db.refresh(entry_exist)
    assert (r1.approved_count, r1.journal_entries_reconciled, m_ref.status, entry_ref.status, m_exist.journal_entry_ids, entry_exist.status) == (2, 2, ReconciliationStatus.ACCEPTED, JournalEntryStatus.RECONCILED, [str(entry_exist.id)], JournalEntryStatus.RECONCILED)

    _, stmt_miss, txn_miss = await _seed_approved_statement_with_txn(db, uid, "DBS Miss", txn_date=date(2025, 1, 17))
    txn_miss_id = txn_miss.id
    m_miss = _match(txn_miss_id)
    db.add(m_miss)
    await db.commit()
    with pytest.raises(DomainError) as exc_miss:
        await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="accept", match_ids=[m_miss.id]), ctx=ctx)
    assert exc_miss.value.status_code == 400 and "Authoritative economic disposition" in str(exc_miss.value.detail)
    await db.rollback()
    await db.refresh(m_miss)
    await db.refresh(stmt_miss)
    assert m_miss.status == ReconciliationStatus.PENDING_REVIEW and m_miss.journal_entry_ids == []
    assert list((await db.execute(select(JournalEntry).where(JournalEntry.user_id == uid, JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES), JournalEntry.source_id == txn_miss_id))).scalars()) == []

    _, _, txn_retry, _ = await _seed_approved_statement_with_posted_txn(db, uid, "DBS Retry", txn_date=date(2025, 1, 18))
    m_retry = _match(txn_retry.id)
    db.add(m_retry)
    await db.commit()
    first = await accept_match_service(db, str(m_retry.id), user_id=uid)
    await db.commit()
    second = await accept_match_service(db, str(m_retry.id), user_id=uid)
    await db.commit()
    assert (second.status, second.version, second.journal_entry_ids) == (ReconciliationStatus.ACCEPTED, first.version, list(first.journal_entry_ids or []))

    _, _, txn_bad = await _seed_approved_statement_with_txn(db, uid, "DBS Bad", txn_date=date(2025, 1, 19))
    _, _, txn_rej = await _seed_approved_statement_with_txn(db, uid, "DBS Rej", txn_date=date(2025, 1, 19))
    other_txn = await add_txn(db, stmt_miss, txn_date=date(2025, 1, 19), description="Diff", amount=Decimal("100.00"), direction="OUT")
    db.add(other_txn)
    await db.commit()
    await db.refresh(other_txn)
    dec, c_acc, s_dec, emitter = await anchored_reviewed_posting_inputs(db, user_id=uid, transaction=other_txn, intent=EconomicIntent.EXPENSE)
    e_bad = await create_entry_from_txn(db, other_txn, user_id=uid, auto_post=True, disposition=dec, counter_account=c_acc, source_decision=s_dec, trace_emitter=emitter, base_currency="SGD")
    m_bad, m_rej = _match(txn_bad.id, eids=[str(e_bad.id)]), _match(txn_rej.id, score=70)
    db.add_all([m_bad, m_rej])
    await db.commit()
    with pytest.raises(DomainError) as exc_amt:
        await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="accept", match_ids=[m_bad.id]), ctx=ctx)
    assert exc_amt.value.status_code == 400 and "Amount mismatch" in exc_amt.value.detail
    assert (await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="reject", match_ids=[]), ctx=ctx)).rejected_count == 0
    assert (await reconciliation_router.batch_update_matches(payload=ReconciliationMatchBatchRequest(action="reject", match_ids=[m_rej.id]), ctx=ctx)).rejected_count == 1

    acc_inact, _, txn_inact = await _seed_approved_statement_with_txn(db, uid, "DBS Inactive", txn_date=date(2025, 1, 20))
    acc_inact.is_active = False
    await db.commit()
    dec2, ca2, sd2, em2 = await anchored_reviewed_posting_inputs(db, user_id=uid, transaction=txn_inact, intent=EconomicIntent.EXPENSE)
    with pytest.raises(ValueError, match="active asset"):
        await create_entry_from_txn(db, txn_inact, user_id=uid, auto_post=True, disposition=dec2, counter_account=ca2, source_decision=sd2, trace_emitter=em2, base_currency="SGD")
    assert await db.scalar(select(Account.id).where(Account.user_id == uid, Account.name.in_(("Income - Uncategorized", "Expense - Uncategorized"))).limit(1)) is None

    _, _, g_txn, g_entry = await _seed_approved_statement_with_posted_txn(db, uid, "DBS Graph", txn_date=date(2025, 1, 21), description="Evidence salary", direction="IN", intent=EconomicIntent.INCOME, source_type=JournalEntrySourceType.AUTO_PARSED)
    g_txn_id, g_entry_id, g_line_ids = g_txn.id, g_entry.id, [item.id for item in g_entry.lines]
    assert (g_entry.source_type, g_entry.source_id) == (JournalEntrySourceType.AUTO_PARSED, g_txn_id)
    await db.commit()
    await EvidenceGraphMaterializationService().materialize_for_entity(db, user_id=uid, entity_type="journal_entry", entity_id=g_entry_id)
    await db.commit()
    nodes = {(n.node_kind, n.entity_type, n.entity_id): n for n in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == uid))).scalars()}
    edges = {(e.from_node_id, e.to_node_id, e.relation) for e in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == uid))).scalars()}
    le_node = nodes["ledger_entry", "journal_entry", g_entry_id]
    assert (nodes["atomic_fact", "atomic_transaction", g_txn_id].id, le_node.id, "posted_as") in edges
    assert {(le_node.id, nodes["ledger_line", "journal_line", lid].id, "contains") for lid in g_line_ids} <= edges
