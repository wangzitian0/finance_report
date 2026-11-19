from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.config_app import set_base_currency
from src.extraction import BankStatementStatus, DocumentSource, extraction_trace_policy_registry
from src.extraction.extension.extraction_trace import ExtractionPromotionTracePolicy
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    confirm_reviewed_statement_envelope,
)
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.ledger import (
    JournalEntry,
    JournalLine,
    initialize_opening_positions,
    ledger_trace_policy_registry,
    list_opening_positions,
    void_journal_entry,
)
from src.platform import DomainError
from src.request_context import RequestContext
from src.routers.statements import get_evidence_lineage
from tests.extraction._statement_run_helpers import make_account
from tests.extraction.test_source_ingestion_integrity import _parse, _payload, _source, _store_result
from tests.factories import UserFactory
from tests.statement_ingestion import posting_dependencies


def _pdf_with_text(text: str) -> bytes:
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


async def _opening(db, user_id, amount, *, dormant=False):
    await set_base_currency(db, "SGD", user_id=user_id)
    account = await make_account(db, user_id, name="Opening Lineage Bank")
    document, statement = await _source(db, user_id, account=account)
    closing = amount + Decimal("10")
    payload = (
        _payload(opening_balance=None, closing_balance=None, transactions=[])
        if dormant
        else _payload(opening_balance=str(amount), closing_balance=str(closing))
    )
    pdf_bytes = b"synthetic" if dormant else _pdf_with_text(f"Opening {amount:.2f} Closing {closing:.2f} Deposit 10.00")
    result = await _parse(
        payload,
        db=db,
        user_id=user_id,
        account_id=account.id,
        source=DocumentSource.resolve(
            path=Path(document.file_path), content=pdf_bytes, content_hash=document.file_hash
        ),
    )
    await _store_result(db, statement, result)
    if dormant:
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
        RequestContext(db, user_id),
        entity_type=entity_type,
        entity_id=entity_id,
        node_kind=None,
        direction="upstream",
        max_depth=6,
    )


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_sourced_opening_reaches_pdf(db, test_user, amount):
    account, document, _ = await _opening(db, test_user.id, amount)
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
        if (rid := pending.pop()) not in visited:
            visited.add(rid)
            record = await repository.get(TraceScope.tenant(test_user.id), rid)
            assert record is not None
            pending.extend(record.parent_ids)
    response = await _lineage(db, test_user.id, "opening_position", account.id)
    before_edges = len((await db.execute(select(EvidenceEdge))).scalars().all())
    await _lineage(db, test_user.id, "opening_position", account.id)
    lines = (await db.execute(select(JournalLine).where(JournalLine.account_id == account.id))).scalars().all()
    assert (
        position.source_decision.decision_id in visited,
        response.anchor is not None,
        document.id in {n.entity_id for n in response.nodes if n.entity_type == "uploaded_document"},
        len((await db.execute(select(EvidenceEdge))).scalars().all()),
        bool(lines),
    ) == (True, True, True, before_edges, bool(amount))
    assert all(
        [
            document.id
            in {
                n.entity_id
                for n in (await _lineage(db, test_user.id, "journal_line", ln.id)).nodes
                if n.entity_type == "uploaded_document"
            }
            for ln in lines
        ]
    )


async def test_cached_opening_lineage_rejects_retired_void_and_revoked_and_isolates_tenant(db, test_user):
    account, _, statement = await _opening(db, test_user.id, Decimal("1000"))
    await _lineage(db, test_user.id, "opening_position", account.id)
    other = await UserFactory.create_async(db, email=f"opening-lineage-{uuid4()}@example.invalid")
    assert (
        (await _lineage(db, other.id, "opening_position", account.id)).anchor,
        (await _lineage(db, other.id, "opening_position", uuid4())).anchor,
    ) == (None, None)

    before_nodes = (await db.execute(select(EvidenceNode.id))).scalars().all()
    statement.status = BankStatementStatus.RETIRED
    await db.flush()
    with pytest.raises(DomainError) as err1:
        await _lineage(db, test_user.id, "opening_position", account.id)
    assert (err1.value.status_code, (await db.execute(select(EvidenceNode.id))).scalars().all()) == (409, before_nodes)

    u2 = await UserFactory.create_async(db, email=f"opening-lineage-2-{uuid4()}@example.invalid")
    account2, _, _ = await _opening(db, u2.id, Decimal("1000"))
    line = (await db.execute(select(JournalLine).where(JournalLine.account_id == account2.id))).scalars().one()
    await _lineage(db, u2.id, "journal_line", line.id)
    await void_journal_entry(
        db,
        (await db.get(JournalEntry, line.journal_entry_id)).id,
        reason="Synthetic opening correction",
        user_id=u2.id,
        base_currency="SGD",
    )

    u3 = await UserFactory.create_async(db, email=f"opening-lineage-3-{uuid4()}@example.invalid")
    account3, _, _ = await _opening(db, u3.id, Decimal("0"))
    await _lineage(db, u3.id, "opening_position", account3.id)
    pos, policy, now = (
        (await list_opening_positions(db, user_id=u3.id, as_of=date.max))[-1],
        ExtractionPromotionTracePolicy(),
        datetime.now(UTC),
    )
    obs = TraceRecord.observation(
        scope=TraceScope.tenant(u3.id),
        target=pos.source_decision.target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("extraction", "bank_statement", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id="synthetic-source-revocation",
        evidence_manifest_digest=pos.source_decision.target.version,
        occurred_at=now,
        reason_code="extraction_review_required",
        score=None,
    )
    await (
        posting_dependencies()
        .trace_emitter_factory(db)
        .emit_many(
            (
                obs,
                TraceRecord.decision(
                    scope=TraceScope.tenant(u3.id),
                    target=pos.source_decision.target,
                    policy=policy,
                    execution_id=obs.execution_id,
                    occurred_at=now,
                    parents=(obs,),
                    supersedes_id=pos.source_decision.decision_id,
                ),
            )
        )
    )
    for uid, kind, eid in ((u2.id, "journal_line", line.id), (u3.id, "opening_position", account3.id)):
        with pytest.raises(DomainError) as err:
            await _lineage(db, uid, kind, eid)
        assert err.value.status_code == 409


async def test_manual_opening_has_no_fabricated_pdf(db, test_user):
    account = await make_account(db, test_user.id, name="Manual Opening Bank")
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={account.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    response = await _lineage(db, test_user.id, "journal_entry", entry.id)
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
    assert (
        response.anchor is not None
        and not any(n.entity_type == "uploaded_document" for n in response.nodes)
        and second.result_id != first.result_id
    )
    assert not any(
        n.entity_type == "uploaded_document"
        for n in (await _lineage(db, test_user.id, "journal_entry", entry.id)).nodes
    )


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_dormant_posted_source_reparse_requires_correction(db, test_user, amount):
    account, document, statement = await _opening(db, test_user.id, amount, dormant=True)
    response = await _lineage(db, test_user.id, "opening_position", account.id)
    assert document.id in {n.entity_id for n in response.nodes if n.entity_type == "uploaded_document"}
    orig_id, orig_pos = (
        statement.current_extraction_result_id,
        (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0],
    )
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
    assert (
        statement.current_extraction_result_id,
        (await list_opening_positions(db, user_id=test_user.id, as_of=date.max))[0],
    ) == (orig_id, orig_pos)
