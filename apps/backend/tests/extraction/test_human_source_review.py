from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.audit import TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
from src.config_app import set_base_currency
from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    StatementBalanceFact,
    StatementSourceType,
    resolve_statement_contribution,
    supports_reviewed_statement_envelope,
)
from src.extraction.extension.reviewed_statement_envelope import ReviewedEnvelopeDecisionTracePolicy
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.ledger import JournalEntry, list_opening_positions
from tests.api._statement_router_fixtures import approve_reviewed
from tests.extraction._statement_run_helpers import make_account
from tests.extraction.test_reviewed_statement_envelope import _missing_source_result
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


async def _dormant(db, user_id, amount=Decimal("1000")):
    await set_base_currency(db, "SGD", user_id=user_id)
    account = await make_account(db, user_id, name="Dormant Bank")
    document, statement = await _source(db, user_id, account=account)
    pdf_bytes = _pdf_with_text(f"Opening Balance {amount:.2f} Closing Balance {amount:.2f}")
    source = DocumentSource.resolve(path=Path(document.file_path), content=pdf_bytes, content_hash=document.file_hash)
    result = await _parse(
        _payload(opening_balance=str(amount), closing_balance=str(amount), transactions=[]),
        db=db,
        user_id=user_id,
        account_id=account.id,
        source=source,
    )
    record = await _store_result(db, statement, result)
    await db.commit()
    command = {
        "source_result_digest": result.content_digest,
        "account_id": str(account.id),
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": str(amount),
        "closing_balance": str(amount),
        "rationale": "I checked the original source and confirm there was no activity this month.",
    }
    assert result.confidence == Decimal("0.60") and result.missing_required_facts == () and not result.requires_review
    return account, document, statement, result, record, command


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_complete_dormant_source_human_confirmation(client, db, test_user, amount):
    account, document, statement, result, record, command = await _dormant(db, test_user.id, amount)
    review = await client.get(f"/statements/{statement.id}/review")
    before = await approve_reviewed(client, statement.id, {})
    confirmation = await client.post(f"/statements/{statement.id}/review-envelopes", json=command)
    repeated = await client.post(f"/statements/{statement.id}/review-envelopes", json=command)
    contribution = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    approved = await approve_reviewed(client, statement.id, {})
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    lineage = await client.get(
        "/statements/evidence-lineage", params={"entity_type": "opening_position", "entity_id": str(account.id)}
    )
    await db.refresh(statement)
    await db.refresh(record)
    assert (
        review.status_code,
        review.json()["source_envelope_reviewable"],
        review.json()["source_missing_facts"],
        before.status_code,
        confirmation.status_code,
        repeated.json()["id"],
        contribution.state,
        contribution.decision.target.kind,
        approved.status_code,
        len(positions),
        positions[0].amount,
        positions[0].source_decision,
        positions[0].journal_entry_id is None,
        lineage.status_code,
        statement.confidence_score,
        record.payload == result.to_payload(),
        record.payload["confidence"],
    ) == (
        200,
        True,
        [],
        400,
        200,
        confirmation.json()["id"],
        "authoritative",
        "reviewed_statement_envelope",
        200,
        1,
        amount,
        contribution.decision,
        amount == 0,
        200,
        60,
        True,
        "0.6",
    )
    assert str(document.id) in {
        n["entity_id"] for n in lineage.json()["nodes"] if n["entity_type"] == "uploaded_document"
    }


@pytest.mark.parametrize(
    "change",
    [
        {"opening_balance": "9000", "closing_balance": "9000"},
        {"period_start": "2024-12-01"},
        {"period_end": "2025-02-28"},
        {"currency": "USD"},
        {"source_result_digest": "f" * 64},
    ],
)
async def test_human_confirmation_cannot_rewrite_known_source(client, db, test_user, change):
    _, _, statement, result, record, command = await _dormant(db, test_user.id)
    response = await client.post(f"/statements/{statement.id}/review-envelopes", json={**command, **change})
    assert (
        response.status_code,
        record.payload == result.to_payload(),
        await list_opening_positions(db, user_id=test_user.id, as_of=date.max),
    ) == (400, True, ())


async def test_human_confirmation_ownership_and_custody_guards(client, db, test_user):
    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    conflicting = await make_account(db, test_user.id, name="Conflicting Bank")
    other = await UserFactory.create_async(db)
    foreign = await make_account(db, other.id, name="Foreign Bank")
    await db.commit()
    rebind = await client.post(
        f"/statements/{statement.id}/review-envelopes", json={**command, "account_id": str(conflicting.id)}
    )
    foreign_acct = await client.post(
        f"/statements/{statement.id}/review-envelopes", json={**command, "account_id": str(foreign.id)}
    )
    await db.refresh(statement)
    _, _, foreign_statement, _, _, foreign_command = await _dormant(db, other.id)
    foreign_stmt = await client.post(f"/statements/{foreign_statement.id}/review-envelopes", json=foreign_command)
    assert (
        rebind.status_code,
        str(statement.account_id),
        foreign_acct.status_code,
        foreign_stmt.status_code in (400, 404),
    ) == (400, command["account_id"], 400, True)


async def test_revoked_retired_and_stale_reparse_envelope_guards(client, db, test_user):
    account, document, statement, _, record, command = await _dormant(db, test_user.id)
    confirmation = await client.post(f"/statements/{statement.id}/review-envelopes", json=command)
    current = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    policy, now = ReviewedEnvelopeDecisionTracePolicy(), datetime.now(UTC)
    obs = TraceRecord.observation(
        scope=TraceScope.tenant(test_user.id),
        target=current.decision.target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("review", "withdrawn", "1"),
        authority=policy.authority,
        result=TraceResult.FAIL,
        execution_id="synthetic-review-withdrawal",
        evidence_manifest_digest=current.decision.target.version,
        occurred_at=now,
        reason_code="human_review_withdrawn",
        score=None,
    )
    revoked = TraceRecord.decision(
        scope=TraceScope.tenant(test_user.id),
        target=current.decision.target,
        policy=policy,
        execution_id=obs.execution_id,
        occurred_at=now,
        parents=(obs,),
        supersedes_id=current.decision.decision_id,
    )
    await posting_dependencies().trace_emitter_factory(db).emit_many((obs, revoked))
    await db.commit()
    after_revoke = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    approve_revoked = await approve_reviewed(client, statement.id, {})
    assert (
        confirmation.status_code,
        after_revoke.state,
        after_revoke.decision,
        approve_revoked.status_code,
        (await db.execute(select(JournalEntry))).scalars().all(),
    ) == (200, "unproven", None, 400, [])

    result2 = await _parse(
        _payload(
            opening_balance="1000", closing_balance="1000", transactions=[], institution="Corrected source header"
        ),
        db=db,
        user_id=test_user.id,
        account_id=account.id,
        source=DocumentSource.resolve(
            path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
        ),
    )
    replacement = await _store_result(db, statement, result2)
    await db.commit()
    stale_resp = await client.post(f"/statements/{statement.id}/review-envelopes", json=command)
    after_reparse = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    assert (
        replacement.id != record.id,
        await db.get(StatementExtractionResultRecord, record.id) is not None,
        stale_resp.status_code,
        after_reparse.state,
    ) == (True, True, 400, "unproven")


async def test_retired_source_cannot_be_resurrected_by_confirmation(client, db, test_user):
    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    statement.status = BankStatementStatus.RETIRED
    await db.commit()
    resp = await client.post(f"/statements/{statement.id}/review-envelopes", json=command)
    await db.refresh(statement)
    assert (resp.status_code, statement.status) == (400, BankStatementStatus.RETIRED)


def test_complete_cash_review_eligibility_keeps_healthy_sources_automatic():
    result = replace(
        _missing_source_result(source_digest="a" * 64),
        statement_currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        balances=(StatementBalanceFact("SGD", Decimal("100"), Decimal("110")),),
        confidence=Decimal("0.75"),
        balance_validated=True,
    )
    assert not result.requires_review and supports_reviewed_statement_envelope(result)
    assert not any(
        supports_reviewed_statement_envelope(r)
        for r in (
            replace(result, confidence=Decimal("0.85")),
            replace(result, balance_validated=False),
            replace(result, source_type=StatementSourceType.BROKERAGE),
            replace(result, balances=(*result.balances, StatementBalanceFact("USD", Decimal("1"), Decimal("1")))),
        )
    )
