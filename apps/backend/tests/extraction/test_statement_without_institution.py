"""A statement whose model reply has no institution keeps its rows and waits for a reviewer (#3167)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from src.audit import canonical_json_digest
from src.extraction import BankStatementStatus, DocumentSource, Stage1Status
from src.extraction.base.result import StatementExtractionResult
from src.extraction.base.reviewed_statement_envelope import supports_reviewed_statement_envelope
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    confirm_reviewed_statement_envelope,
    persist_statement_extraction_result,
    require_current_statement_envelope_trust,
)
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.ledger import Account, JournalEntry
from src.platform import ValidationFailedError
from tests.extraction._statement_run_helpers import (
    integrity_store_result,
    make_account,
    migration_db_url,
    run_alembic,
)
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

_ROWS = [
    {"date": "2026-03-02", "description": "Salary credit", "amount": "2000.00", "direction": "IN"},
    {"date": "2026-03-05", "description": "Rent payment", "amount": "1200.00", "direction": "OUT"},
    {"date": "2026-03-20", "description": "Groceries", "amount": "80.00", "direction": "OUT"},
]
_INSTITUTION_REASON = "Source is missing required facts: institution"


def _reply(institution: str | None, **changes) -> dict:
    return {
        "institution": institution,
        "account_last4": "5678",
        "currency": "SGD",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "opening_balance": "1000.00",
        "closing_balance": "1720.00",
        "transactions": [dict(row) for row in _ROWS],
        **changes,
    }


def _printed_statement(tag: str) -> bytes:
    """A PDF whose text layer prints the balances and the amount of each row. The tag makes the bytes unique."""
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(72, 720, f"Statement {tag} Opening: 1000.00 Closing: 1720.00")
    for index, row in enumerate(_ROWS):
        page.drawString(72, 700 - index * 16, f"{row['date']} {row['description']} {row['amount']}")
    page.showPage()
    page.save()
    return buffer.getvalue()


async def _parse(
    db, user_id, *, reply_institution: str | None, upload_institution: str | None, account_id=None, **reply_changes
):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_reply(reply_institution, **reply_changes))
    tag = uuid4().hex
    return await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=user_id,
        source=DocumentSource.resolve(path=Path(f"{tag}.pdf"), content=_printed_statement(tag)),
        institution=upload_institution,
        account_id=account_id,
    )


async def _count(db, model, user_id) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))


def _command(result: StatementExtractionResult, account_id, **changes) -> ReviewedStatementEnvelopeCommand:
    values = {
        "source_result_digest": result.content_digest,
        "account_id": account_id,
        "currency": "SGD",
        "period_start": date(2026, 3, 1),
        "period_end": date(2026, 3, 31),
        "opening_balance": Decimal("1000.00"),
        "closing_balance": Decimal("1720.00"),
        "rationale": "The reviewer read the bank name on the paper statement.",
        **changes,
    }
    return ReviewedStatementEnvelopeCommand(**values)


async def test_reply_without_institution_keeps_the_rows_and_waits_for_review(db, test_user):
    result, statement, transactions = await _parse(db, test_user.id, reply_institution=None, upload_institution=None)

    assert (
        statement.status,
        statement.stage1_status,
        len(transactions),
        len(result.transactions),
        result.institution,
        statement.institution,
        result.missing_required_facts,
        result.review_reasons,
        statement.validation_error,
        result.requires_review,
        result.balance_validated,
        statement.account_id,
        await _count(db, Account, test_user.id),
        await _count(db, BankCustodyBinding, test_user.id),
        await _count(db, JournalEntry, test_user.id),
    ) == (
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
        3,
        3,
        None,
        None,
        ("institution",),
        (_INSTITUTION_REASON,),
        _INSTITUTION_REASON,
        True,
        True,
        None,
        0,
        0,
        0,
    )


async def test_reply_without_institution_is_not_auto_approved_on_a_selected_account(db, test_user):
    """The same upload with an institution is an auto-approve candidate. The missing institution alone stops it."""
    with_account = await make_account(db, test_user.id, name="Selected at upload A")
    named, named_statement, _ = await _parse(
        db, test_user.id, reply_institution="ACME", upload_institution=None, account_id=with_account.id
    )
    other_account = await make_account(db, test_user.id, name="Selected at upload B")
    unnamed, unnamed_statement, rows = await _parse(
        db, test_user.id, reply_institution=None, upload_institution=None, account_id=other_account.id
    )

    assert (
        named.missing_required_facts,
        named_statement.status,
        unnamed.missing_required_facts,
        unnamed_statement.status,
        unnamed_statement.account_id,
        len(rows),
        await _count(db, BankCustodyBinding, test_user.id),
        await _count(db, JournalEntry, test_user.id),
    ) == (
        (),
        BankStatementStatus.APPROVED,
        ("institution",),
        BankStatementStatus.PARSED,
        other_account.id,
        3,
        1,
        0,
    )


async def test_position_snapshot_without_institution_is_still_rejected():
    """The envelope confirmation takes transaction ledgers only, so no review can state the broker."""
    positions = [{"symbol": "AAPL", "quantity": "15", "price": "212.40", "market_value": "3186.00", "currency": "USD"}]
    reply = {"institution": None, "snapshot_date": "2026-06-30", "currency": "USD", "positions": positions}
    parsed = []
    for upload_institution in (None, "SynthBroker"):
        service = ExtractionService()
        service.extract_financial_data = AsyncMock(return_value=dict(reply))
        source = DocumentSource.resolve(path=Path("positions.pdf"), content=uuid4().bytes)
        try:
            result = await service.parse_document(source, institution=upload_institution, user_id=uuid4())
            parsed.append((result.institution, len(result.positions)))
        except ExtractionError as error:
            parsed.append(str(error))

    assert parsed == ["Institution is required; extraction cannot invent source identity", ("SynthBroker", 1)]


async def test_institution_given_at_upload_is_kept_when_the_reply_has_none(db, test_user):
    result, statement, transactions = await _parse(db, test_user.id, reply_institution=None, upload_institution="ACME")

    assert (
        statement.status,
        len(transactions),
        result.institution,
        statement.institution,
        result.missing_required_facts,
        result.review_reasons,
        statement.validation_error,
        (await db.execute(select(BankCustodyBinding.institution))).scalars().all(),
    ) == (BankStatementStatus.APPROVED, 3, "ACME", "ACME", (), (), None, ["ACME"])


async def test_envelope_confirmation_must_state_the_missing_institution(db, test_user):
    result, statement, _ = await _parse(db, test_user.id, reply_institution=None, upload_institution=None)
    await integrity_store_result(db, statement, result)
    account = await make_account(db, test_user.id, name="Reviewer account")
    emitter = posting_dependencies().trace_emitter_factory(db)

    with pytest.raises(ValidationFailedError, match="institution"):
        await require_current_statement_envelope_trust(db, statement=statement)
    with pytest.raises(ValidationFailedError, match="state the institution"):
        await confirm_reviewed_statement_envelope(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(result, account.id),
            trace_emitter=emitter,
        )
    refused_state = (statement.institution, statement.account_id, statement.validation_error)

    envelope = await confirm_reviewed_statement_envelope(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(result, account.id, institution="  Reviewed Bank  "),
        trace_emitter=emitter,
    )
    await require_current_statement_envelope_trust(db, statement=statement)

    assert (
        supports_reviewed_statement_envelope(result),
        refused_state,
        envelope.institution,
        statement.institution,
        statement.account_id,
        statement.status,
        statement.validation_error,
        (await db.execute(select(BankCustodyBinding.institution, BankCustodyBinding.account_id))).tuples().all(),
        await _count(db, JournalEntry, test_user.id),
    ) == (
        True,
        (None, None, _INSTITUTION_REASON),
        "Reviewed Bank",
        "Reviewed Bank",
        account.id,
        BankStatementStatus.PARSED,
        None,
        [("Reviewed Bank", account.id)],
        0,
    )


async def test_reparse_of_the_same_result_keeps_the_institution_of_the_reviewer(db, test_user):
    result, statement, _ = await _parse(db, test_user.id, reply_institution=None, upload_institution=None)
    stored = await integrity_store_result(db, statement, result)
    account = await make_account(db, test_user.id, name="Reviewer account")
    await confirm_reviewed_statement_envelope(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(result, account.id, institution="Reviewed Bank"),
        trace_emitter=posting_dependencies().trace_emitter_factory(db),
    )

    # A second parse of the same source writes the source institution (none) to the statement again.
    statement.institution = None
    await db.flush()
    with pytest.raises(ValidationFailedError, match="diverges from its current reviewed envelope"):
        await require_current_statement_envelope_trust(db, statement=statement)
    await persist_statement_extraction_result(
        db, statement=statement, result=result, source_trace_record_id=stored.source_trace_record_id
    )

    assert statement.institution == "Reviewed Bank"
    await require_current_statement_envelope_trust(db, statement=statement)


async def test_envelope_confirmation_refuses_an_institution_that_differs_from_the_source(db, test_user):
    # A statement without a period is review-only, so the envelope confirmation is open for it.
    result, statement, _ = await _parse(
        db, test_user.id, reply_institution="ACME", upload_institution=None, period_start=None, period_end=None
    )
    await integrity_store_result(db, statement, result)
    account_id = statement.account_id
    emitter = posting_dependencies().trace_emitter_factory(db)

    with pytest.raises(ValidationFailedError, match="Confirmed institution must match the declared source fact"):
        await confirm_reviewed_statement_envelope(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(result, account_id, institution="Other Bank"),
            trace_emitter=emitter,
        )
    envelope = await confirm_reviewed_statement_envelope(
        db, user_id=test_user.id, statement_id=statement.id, command=_command(result, account_id), trace_emitter=emitter
    )

    assert (result.missing_required_facts, envelope.institution, statement.institution) == (("period",), None, "ACME")


async def test_review_api_shows_no_institution_and_takes_the_institution_of_the_reviewer(client, db, test_user):
    result, statement, _ = await _parse(db, test_user.id, reply_institution=None, upload_institution=None)
    await integrity_store_result(db, statement, result)
    account = await make_account(db, test_user.id, name="Reviewer account")
    await db.commit()
    body = {
        "source_result_digest": result.content_digest,
        "account_id": str(account.id),
        "currency": "SGD",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "opening_balance": "1000.00",
        "closing_balance": "1720.00",
        "rationale": "The reviewer read the bank name on the paper statement.",
    }
    url = f"/statements/{statement.id}"

    review = await client.get(f"{url}/review")
    approval = await client.post(f"{url}/approvals", json={"expected_source_result_digest": result.content_digest})
    refused = await client.post(f"{url}/review-envelopes", json=body)
    too_long = await client.post(f"{url}/review-envelopes", json={**body, "institution": "B" * 101})
    confirmed = await client.post(f"{url}/review-envelopes", json={**body, "institution": "Reviewed Bank"})
    after = await client.get(f"{url}/review")

    assert (
        review.status_code,
        review.json()["institution"],
        review.json()["source_missing_facts"],
        review.json()["source_envelope_reviewable"],
        len(review.json()["transactions"]),
        approval.status_code,
        "institution" in approval.text,
        refused.status_code,
        "must state the institution" in refused.text,
        too_long.status_code,
        confirmed.status_code,
        confirmed.json()["institution"],
        after.json()["institution"],
        after.json()["reviewed_envelope"]["institution"],
        after.json()["account_id"],
        await _count(db, JournalEntry, test_user.id),
    ) == (
        200,
        None,
        ["institution"],
        True,
        3,
        400,
        True,
        400,
        True,
        422,
        200,
        "Reviewed Bank",
        "Reviewed Bank",
        "Reviewed Bank",
        str(account.id),
        0,
    )


def test_envelope_command_trims_the_institution_and_limits_its_length():
    values = {
        "source_result_digest": "a" * 64,
        "account_id": uuid4(),
        "currency": "SGD",
        "period_start": date(2026, 3, 1),
        "period_end": date(2026, 3, 31),
        "opening_balance": Decimal("1000.00"),
        "closing_balance": Decimal("1720.00"),
        "rationale": "Same rationale.",
    }
    with pytest.raises(ValueError, match="institution"):
        ReviewedStatementEnvelopeCommand(**values, institution=" ")
    with pytest.raises(ValueError, match="100 characters"):
        ReviewedStatementEnvelopeCommand(**values, institution="B" * 101)

    assert (
        ReviewedStatementEnvelopeCommand(**values, institution=" " + "B" * 100 + " ").institution,
        ReviewedStatementEnvelopeCommand(**values).institution,
    ) == ("B" * 100, None)


def test_envelope_command_digest_includes_the_institution():
    result_digest, account_id = "a" * 64, uuid4()
    values = {
        "source_result_digest": result_digest,
        "account_id": account_id,
        "currency": "SGD",
        "period_start": date(2026, 3, 1),
        "period_end": date(2026, 3, 31),
        "opening_balance": Decimal("1000.00"),
        "closing_balance": Decimal("1720.00"),
        "rationale": "Same rationale.",
    }
    without = ReviewedStatementEnvelopeCommand(**values)
    first = ReviewedStatementEnvelopeCommand(**values, institution="First Bank")
    second = ReviewedStatementEnvelopeCommand(**values, institution="Second Bank")
    # A command without an institution keeps the digest that stored envelopes hold.
    stored_formula = canonical_json_digest(
        {
            "source_result_digest": result_digest,
            "account_id": str(account_id),
            "currency": "SGD",
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "opening_balance": "1000.00",
            "closing_balance": "1720.00",
            "rationale": "Same rationale.",
        },
        default=str,
    )

    assert (without.digest, len({without.digest, first.digest, second.digest})) == (stored_formula, 3)


async def test_result_payload_round_trips_with_and_without_an_institution(db, test_user):
    unnamed, _, _ = await _parse(db, test_user.id, reply_institution=None, upload_institution=None)
    named, _, _ = await _parse(db, test_user.id, reply_institution="ACME", upload_institution=None)
    unnamed_payload, named_payload = unnamed.to_payload(), named.to_payload()

    assert (
        unnamed_payload["institution"],
        StatementExtractionResult.from_payload(unnamed_payload),
        StatementExtractionResult.from_payload(unnamed_payload).missing_required_facts,
        named_payload["institution"],
        StatementExtractionResult.from_payload(named_payload),
        StatementExtractionResult.from_payload(named_payload).missing_required_facts,
    ) == (None, unnamed, ("institution",), "ACME", named, ())
    with pytest.raises(ValueError, match="institution"):
        StatementExtractionResult.from_payload({**named_payload, "institution": "  "})


def test_migration_0080_makes_the_institution_optional_and_refuses_a_downgrade_with_a_null_row():
    from sqlalchemy import create_engine, text

    name = f"fr_3167_institution_{uuid4().hex[:12]}"
    admin = create_engine(migration_db_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = migration_db_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id, statement_id = uuid4(), uuid4()
    nullable = text(
        "SELECT table_name, is_nullable FROM information_schema.columns WHERE column_name = 'institution' "
        "AND table_name IN ('statement_summaries', 'reviewed_statement_envelopes', 'bank_custody_bindings') "
        "ORDER BY table_name"
    )
    try:
        run_alembic(database_url, "upgrade", "0079_position_cost_nullable")
        with engine.begin() as connection:
            before = connection.execute(nullable).tuples().all()
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) "
                    "VALUES (:id, :email, 'x', '{}', NOW(), NOW())"
                ),
                {"id": user_id, "email": f"{name}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO statement_summaries (id, user_id, file_hash, sub_account_key, institution, status, "
                    "created_at, updated_at) VALUES (:id, :user_id, :file_hash, '', 'ACME', 'parsed', NOW(), NOW())"
                ),
                {"id": statement_id, "user_id": user_id, "file_hash": "b" * 64},
            )
        run_alembic(database_url, "upgrade", "0080_stmt_institution_nullable")
        with engine.begin() as connection:
            after = connection.execute(nullable).tuples().all()
            connection.execute(
                text("UPDATE statement_summaries SET institution = NULL WHERE id = :id"), {"id": statement_id}
            )
        with pytest.raises(AssertionError, match="1 statement_summaries rows have no institution"):
            run_alembic(database_url, "downgrade", "0079_position_cost_nullable")
        with engine.begin() as connection:
            kept = connection.execute(text("SELECT institution FROM statement_summaries")).scalars().all()
            connection.execute(
                text("UPDATE statement_summaries SET institution = 'ACME' WHERE id = :id"), {"id": statement_id}
            )
        run_alembic(database_url, "downgrade", "0079_position_cost_nullable")
        with engine.connect() as connection:
            downgraded = connection.execute(nullable).tuples().all()
        run_alembic(database_url, "upgrade", "head")
        # The model parity check needs the head revision, so it runs after the last upgrade.
        run_alembic(database_url, "check")

        assert (before, after, kept, downgraded) == (
            [("bank_custody_bindings", "NO"), ("statement_summaries", "NO")],
            [
                ("bank_custody_bindings", "NO"),
                ("reviewed_statement_envelopes", "YES"),
                ("statement_summaries", "YES"),
            ],
            [None],
            [("bank_custody_bindings", "NO"), ("statement_summaries", "NO")],
        )
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
