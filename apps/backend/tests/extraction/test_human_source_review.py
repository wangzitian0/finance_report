"""Explicit human recovery for complete low-confidence cash statement sources."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.config_app import set_base_currency
from src.extraction import DocumentSource, resolve_statement_contribution
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.ledger import JournalEntry, list_opening_positions
from tests.extraction.test_source_ingestion_integrity import _parse, _payload, _source, _store_result
from tests.factories import AccountFactory, UserFactory
from tests.statement_ingestion import posting_dependencies


async def _dormant(db, user_id, amount=Decimal("1000")):
    await set_base_currency(db, "SGD")
    account = AccountFactory.build(user_id=user_id, currency="SGD")
    db.add(account)
    await db.flush()
    document, statement = await _source(db, user_id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
    )
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
    assert result.confidence == Decimal("0.75")
    assert result.missing_required_facts == () and not result.requires_review
    return account, document, statement, result, record, command


@pytest.mark.parametrize("amount", [Decimal("1000"), Decimal("0")])
async def test_complete_dormant_source_human_confirmation(client, db, test_user, amount):
    """AC-extraction.human-source-review.1: a real human command unlocks dormant source stock."""
    account, document, statement, result, record, command = await _dormant(db, test_user.id, amount)
    review = await client.get(f"/statements/{statement.id}/review")
    assert review.status_code == 200
    assert review.json()["source_envelope_reviewable"] is True
    assert review.json()["source_missing_facts"] == []
    before = await client.post(f"/statements/{statement.id}/review/approve", json={})
    assert before.status_code == 400
    confirmation = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert confirmation.status_code == 200, confirmation.text
    repeated = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert repeated.json()["id"] == confirmation.json()["id"]
    contribution = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    assert contribution.state == "authoritative"
    assert contribution.decision.target.kind == "reviewed_statement_envelope"
    approved = await client.post(f"/statements/{statement.id}/review/approve", json={})
    assert approved.status_code == 200, approved.text
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert len(positions) == 1 and positions[0].amount == amount
    assert positions[0].source_decision == contribution.decision
    assert (positions[0].journal_entry_id is None) == (amount == 0)
    lineage = await client.get(
        "/evidence/lineage", params={"entity_type": "opening_position", "entity_id": str(account.id)}
    )
    assert lineage.status_code == 200
    assert str(document.id) in {
        node["entity_id"] for node in lineage.json()["nodes"] if node["entity_type"] == "uploaded_document"
    }
    await db.refresh(statement)
    assert statement.confidence_score == 75
    await db.refresh(record)
    assert record.payload == result.to_payload()
    assert record.payload["confidence"] == "0.75"


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
    """AC-extraction.human-source-review.2: balanced invented values do not become source truth."""
    _, _, statement, result, record, command = await _dormant(db, test_user.id)
    response = await client.post(f"/statements/{statement.id}/review/envelope", json={**command, **change})
    assert response.status_code == 400
    assert record.payload == result.to_payload()
    assert await list_opening_positions(db, user_id=test_user.id, as_of=date.max) == ()


async def test_human_confirmation_rejects_foreign_owner(client, db, test_user):
    """AC-extraction.human-source-review.2: source and custody ownership are independently enforced."""
    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    other = await UserFactory.create_async(db)
    foreign = AccountFactory.build(user_id=other.id, currency="SGD")
    db.add(foreign)
    await db.commit()
    response = await client.post(
        f"/statements/{statement.id}/review/envelope", json={**command, "account_id": str(foreign.id)}
    )
    assert response.status_code == 400
    _, _, foreign_statement, _, _, foreign_command = await _dormant(db, other.id)
    response = await client.post(f"/statements/{foreign_statement.id}/review/envelope", json=foreign_command)
    assert response.status_code in (400, 404)


async def test_revoked_human_review_cannot_authorize_source(client, db, test_user):
    """AC-extraction.human-source-review.3: superseding human authority invalidates posting trust."""
    from src.audit import TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
    from src.extraction.extension.reviewed_statement_envelope import ReviewedEnvelopeDecisionTracePolicy

    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    confirmation = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert confirmation.status_code == 200
    current = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    policy = ReviewedEnvelopeDecisionTracePolicy()
    now = datetime.now(UTC)
    observation = TraceRecord.observation(
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
        execution_id=observation.execution_id,
        occurred_at=now,
        parents=(observation,),
        supersedes_id=current.decision.decision_id,
    )
    await posting_dependencies().trace_emitter_factory(db).emit_many((observation, revoked))
    await db.commit()
    current = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    assert current.state == "unproven" and current.decision is None
    response = await client.post(f"/statements/{statement.id}/review/approve", json={})
    assert response.status_code == 400
    assert (await db.execute(select(JournalEntry))).scalars().all() == []


async def test_stale_human_envelope_cannot_cross_reparse(client, db, test_user):
    """AC-extraction.human-source-review.3: a review remains pinned to its actual result version."""
    account, document, statement, _, record, command = await _dormant(db, test_user.id)
    confirmation = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert confirmation.status_code == 200
    result = await _parse(
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
    replacement = await _store_result(db, statement, result)
    await db.commit()
    assert replacement.id != record.id
    assert await db.get(StatementExtractionResultRecord, record.id) is not None
    response = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert response.status_code == 400
    current = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    assert current.state == "unproven"


async def test_retired_source_cannot_be_resurrected_by_confirmation(client, db, test_user):
    """AC-extraction.human-source-review.3: confirmation cannot restore a retired source lifecycle."""
    from src.extraction import BankStatementStatus

    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    statement.status = BankStatementStatus.RETIRED
    await db.commit()
    response = await client.post(f"/statements/{statement.id}/review/envelope", json=command)
    assert response.status_code == 400
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.RETIRED


def test_complete_cash_review_eligibility_keeps_healthy_sources_automatic():
    """AC-extraction.human-source-review.1: eligibility is narrow and independent of completeness."""
    from dataclasses import replace

    from src.extraction import StatementBalanceFact, StatementSourceType, supports_reviewed_statement_envelope
    from tests.extraction.test_reviewed_statement_envelope import _missing_source_result

    result = replace(
        _missing_source_result(source_digest="a" * 64),
        statement_currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        balances=(StatementBalanceFact("SGD", Decimal("100"), Decimal("110")),),
        confidence=Decimal("0.75"),
        balance_validated=True,
    )
    assert not result.requires_review
    assert supports_reviewed_statement_envelope(result)
    assert not supports_reviewed_statement_envelope(replace(result, confidence=Decimal("0.85")))
    assert not supports_reviewed_statement_envelope(replace(result, balance_validated=False))
    assert not supports_reviewed_statement_envelope(replace(result, source_type=StatementSourceType.BROKERAGE))
    assert not supports_reviewed_statement_envelope(
        replace(result, balances=(*result.balances, StatementBalanceFact("USD", Decimal("1"), Decimal("1"))))
    )


async def test_human_review_cannot_rebind_known_bank_custody(client, db, test_user):
    """AC-extraction.human-source-review.2: human confirmation uses the shared bank custody owner."""
    _, _, statement, _, _, command = await _dormant(db, test_user.id)
    conflicting = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(conflicting)
    await db.commit()
    response = await client.post(
        f"/statements/{statement.id}/review/envelope",
        json={**command, "account_id": str(conflicting.id)},
    )
    assert response.status_code == 400
    await db.refresh(statement)
    assert str(statement.account_id) == command["account_id"]
