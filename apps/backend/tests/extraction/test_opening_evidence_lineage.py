"""Source-backed starting-stock navigation uses current business authority."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.config_app import set_base_currency
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.ledger import JournalEntry, JournalLine, initialize_opening_positions
from src.routers.evidence import get_evidence_lineage
from tests.extraction.test_source_ingestion_integrity import _parse, _payload, _source, _store_result
from tests.factories import AccountFactory, UserFactory
from tests.statement_ingestion import posting_dependencies


async def _opening(db, user_id, amount, *, dormant=False):
    await set_base_currency(db, "SGD")
    account = AccountFactory.build(user_id=user_id, currency="SGD")
    db.add(account)
    await db.flush()
    document, statement = await _source(db, user_id, account=account)
    result = await _parse(
        _payload(opening_balance=None, closing_balance=None, transactions=[])
        if dormant
        else _payload(opening_balance=str(amount), closing_balance=str(amount + Decimal("10"))),
        db=db,
        user_id=user_id,
        account_id=account.id,
        source=DocumentSource.resolve(
            path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
        ),
    )
    await _store_result(db, statement, result)
    if dormant:
        from src.extraction.extension.reviewed_statement_envelope import (
            ReviewedStatementEnvelopeCommand,
            confirm_reviewed_statement_envelope,
        )

        await confirm_reviewed_statement_envelope(
            db,
            user_id=user_id,
            statement_id=statement.id,
            command=ReviewedStatementEnvelopeCommand(
                source_result_digest=result.content_digest,
                account_id=account.id,
                currency="SGD",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 31),
                opening_balance=amount,
                closing_balance=amount,
                rationale="Synthetic dormant source header confirmed.",
            ),
            trace_emitter=posting_dependencies().trace_emitter_factory(db),
        )
    await try_auto_post_statement_opening_balance(db, statement, user_id, dependencies=posting_dependencies())
    await db.flush()
    return account, document, statement


async def _lineage(db, user_id, entity_type, entity_id):
    return await get_evidence_lineage(
        db=db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        node_kind=None,
        direction="upstream",
        max_depth=6,
    )


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_sourced_opening_reaches_pdf(db, test_user, amount):
    """AC-extraction.opening-lineage.1: real posting preserves opening source ancestry."""
    account, document, _ = await _opening(db, test_user.id, amount)
    from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry, TraceScope
    from src.extraction import extraction_trace_policy_registry
    from src.ledger import ledger_trace_policy_registry, list_opening_positions

    position = (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0]
    assert position.source_decision is not None
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry(
            (*extraction_trace_policy_registry().policies, *ledger_trace_policy_registry().policies)
        ),
    )
    pending, visited = [position.decision.decision_id], set()
    while pending:
        record_id = pending.pop()
        if record_id in visited:
            continue
        visited.add(record_id)
        record = await repository.get(TraceScope.tenant(test_user.id), record_id)
        assert record is not None
        pending.extend(record.parent_ids)
    assert position.source_decision.decision_id in visited
    response = await _lineage(db, test_user.id, "opening_position", account.id)
    assert response.anchor is not None
    assert document.id in {node.entity_id for node in response.nodes if node.entity_type == "uploaded_document"}
    before = len((await db.execute(select(EvidenceEdge))).scalars().all())
    await _lineage(db, test_user.id, "opening_position", account.id)
    assert len((await db.execute(select(EvidenceEdge))).scalars().all()) == before
    lines = (await db.execute(select(JournalLine).where(JournalLine.account_id == account.id))).scalars().all()
    assert bool(lines) == bool(amount)
    for line in lines:
        response = await _lineage(db, test_user.id, "journal_line", line.id)
        assert document.id in {node.entity_id for node in response.nodes if node.entity_type == "uploaded_document"}


async def test_cached_opening_lineage_rejects_retired_source(db, test_user):
    """AC-extraction.opening-lineage.2: cached source edges cannot bypass current eligibility."""
    account, _, statement = await _opening(db, test_user.id, Decimal("1000"))
    await _lineage(db, test_user.id, "opening_position", account.id)
    before = (await db.execute(select(EvidenceNode.id))).scalars().all()
    statement.status = BankStatementStatus.RETIRED
    await db.flush()
    with pytest.raises(HTTPException) as error:
        await _lineage(db, test_user.id, "opening_position", account.id)
    assert error.value.status_code == 409
    assert (await db.execute(select(EvidenceNode.id))).scalars().all() == before


async def test_foreign_opening_is_empty_and_void_cached_journal_is_blocked(db, test_user):
    """AC-extraction.opening-lineage.2: tenant and void lifecycle checks survive graph caching."""
    account, _, _ = await _opening(db, test_user.id, Decimal("1000"))
    other = await UserFactory.create_async(db, email=f"opening-lineage-{uuid4()}@example.invalid")
    assert (await _lineage(db, other.id, "opening_position", account.id)).anchor is None
    assert (await _lineage(db, other.id, "opening_position", uuid4())).anchor is None
    line = (await db.execute(select(JournalLine).where(JournalLine.account_id == account.id))).scalars().one()
    await _lineage(db, test_user.id, "journal_line", line.id)
    entry = await db.get(JournalEntry, line.journal_entry_id)
    from src.ledger import void_journal_entry

    await void_journal_entry(
        db, entry.id, reason="Synthetic opening correction", user_id=test_user.id, base_currency="SGD"
    )
    with pytest.raises(HTTPException) as error:
        await _lineage(db, test_user.id, "journal_line", line.id)
    assert error.value.status_code == 409


async def test_manual_opening_has_no_fabricated_pdf(db, test_user):
    """AC-extraction.opening-lineage.3: an unsourced manual opening has only ledger evidence."""
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={account.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    response = await _lineage(db, test_user.id, "journal_entry", entry.id)
    assert response.anchor is not None
    assert not any(node.entity_type == "uploaded_document" for node in response.nodes)
    # An unrelated PDF on the account may still be reparsed: manual stock
    # must not be relabeled as a source-backed opening.
    document, statement = await _source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
    )
    first = await _parse(_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source)
    await _store_result(db, statement, first)
    second = await _parse(
        _payload(institution="Synthetic corrected header"),
        db=db,
        user_id=test_user.id,
        account_id=account.id,
        source=source,
    )
    assert second.result_id != first.result_id
    assert not any(
        node.entity_type == "uploaded_document"
        for node in (await _lineage(db, test_user.id, "journal_entry", entry.id)).nodes
    )


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_dormant_posted_source_reparse_requires_correction(db, test_user, amount):
    """AC-extraction.opening-lineage.4: source-only stock is protected without transaction journals."""
    from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
    from src.ledger import list_opening_positions

    account, document, statement = await _opening(db, test_user.id, amount, dormant=True)
    response = await _lineage(db, test_user.id, "opening_position", account.id)
    assert document.id in {node.entity_id for node in response.nodes if node.entity_type == "uploaded_document"}
    original_result_id = statement.current_extraction_result_id
    original_position = (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0]
    with pytest.raises(TransactionIdentityReviewRequired, match="correction review"):
        await _parse(
            _payload(opening_balance=str(amount + 100), closing_balance=str(amount + 100), transactions=[]),
            db=db,
            user_id=test_user.id,
            account_id=account.id,
            source=DocumentSource.resolve(
                path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
            ),
        )
    await db.refresh(statement)
    assert statement.current_extraction_result_id == original_result_id
    assert (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0] == original_position


async def test_cached_opening_lineage_rejects_revoked_source(db, test_user):
    """AC-extraction.opening-lineage.2: a real source decision supersession invalidates cached PDF edges."""
    from datetime import UTC, datetime

    from src.audit import TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
    from src.extraction.extension.extraction_trace import ExtractionPromotionTracePolicy
    from src.ledger import list_opening_positions

    account, _, _ = await _opening(db, test_user.id, Decimal("0"))
    await _lineage(db, test_user.id, "opening_position", account.id)
    position = (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0]
    policy = ExtractionPromotionTracePolicy()
    now = datetime.now(UTC)
    observation = TraceRecord.observation(
        scope=TraceScope.tenant(test_user.id),
        target=position.source_decision.target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("extraction", "bank_statement", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id="synthetic-source-revocation",
        evidence_manifest_digest=position.source_decision.target.version,
        occurred_at=now,
        reason_code="extraction_review_required",
        score=None,
    )
    revoked = TraceRecord.decision(
        scope=TraceScope.tenant(test_user.id),
        target=position.source_decision.target,
        policy=policy,
        execution_id=observation.execution_id,
        occurred_at=now,
        parents=(observation,),
        supersedes_id=position.source_decision.decision_id,
    )
    await posting_dependencies().trace_emitter_factory(db).emit_many((observation, revoked))
    with pytest.raises(HTTPException) as error:
        await _lineage(db, test_user.id, "opening_position", account.id)
    assert error.value.status_code == 409
