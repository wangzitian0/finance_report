import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    ExtractionMethod,
    ParseJob,
    RetryableStatementIngestionError,
    StatementEvidenceType,
)
from src.extraction.base.normalization_engine import compute_transaction_identity_hash, sanitize_account_last4
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.statement_summary import StatementSummary
from tests.extraction._statement_run_helpers import make_account
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import (
    execute_statement_ingestion as parse_statement_background,
    parse_and_load_statement_projection,
    run_for,
)


def _mock_payload(ai_value):
    return {
        "institution": "DBS",
        "account_last4": ai_value,
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "1100.00",
        "transactions": [{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}],
    }


async def test_parse_document_and_db_sanitize_account_last4(db, test_user):
    uid, service = test_user.id, ExtractionService()
    for ai_value, expected in [
        ("553-3", "5533"),
        ("ABCDE", "BCDE"),
        ("12号34", "1234"),
        ("1234-5678-9012", "9012"),
        ("----", None),
        ("", None),
        (None, None),
        ("  5 5 3 3  ", "5533"),
        ("X", "X"),
        ("AB", "AB"),
    ]:
        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=_mock_payload(ai_value))):
            result = await service.parse_document(
                DocumentSource.resolve(path=Path("/tmp/test_sanitize.pdf"), content=b"dummy"),
                institution="DBS",
                user_id=uuid4(),
            )
        assert (
            result.account_last4 == expected
            and (expected is None or (len(expected) <= 4 and expected.isalnum()))
            and (ai_value != "553-3" or result.balance_validated is True)
        )

    account = await make_account(db, uid, f"DBS {uuid4().hex[:8]}")
    with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=_mock_payload("553-3"))):
        _, stmt, _ = await parse_and_load_statement_projection(
            service,
            db=db,
            source=DocumentSource.resolve(path=Path("/tmp/test_persist.pdf"), content=b"dummy"),
            institution="DBS",
            user_id=uid,
            account_id=account.id,
        )
    await db.commit()
    saved = await db.get(StatementSummary, stmt.id)
    assert saved is not None and saved.account_last4 == "5533"

    for account_last4, raises in (("553-3", True), ("5533", False), (None, False)):
        s = StatementSummaryFactory.build(
            id=uuid4(),
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_hash=f"v4_{uuid4().hex[:8]}",
            institution="DBS",
            account_last4=account_last4,
        )
        db.add(s)
        if raises:
            with pytest.raises(Exception, match="value too long|StringDataRightTruncation"):
                await db.flush()
            await db.rollback()
        else:
            await db.commit()
            assert (await db.get(StatementSummary, s.id)).account_last4 == account_last4


@pytest.mark.parametrize("fail_commit", [False, True])
async def test_background_task_dirty_last4_and_commit_failure(db, test_user, monkeypatch, fail_commit):
    sid, uid = uuid4(), test_user.id
    account = await make_account(db, uid, f"DBS {uuid4().hex[:8]}")
    db.add(
        StatementSummaryFactory.build(
            id=sid, user_id=uid, status=BankStatementStatus.PARSING, file_hash=f"bg_{sid.hex[:8]}", institution="DBS"
        )
    )
    await db.commit()
    original_commit, armed = AsyncSession.commit, False

    async def maybe_fail_commit(session_self):
        nonlocal armed
        if armed:
            armed = False
            raise RuntimeError("Simulated DB commit failure")
        return await original_commit(session_self)

    if fail_commit:
        monkeypatch.setattr(AsyncSession, "commit", maybe_fail_commit)

    async def mock_parse(*args, **kwargs):
        nonlocal armed
        session = kwargs["db"]
        summary = await session.get(StatementSummary, sid)
        (
            summary.account_last4,
            summary.account_id,
            summary.currency,
            summary.period_start,
            summary.period_end,
            summary.opening_balance,
            summary.closing_balance,
            summary.confidence_score,
            summary.balance_validated,
            summary.validation_error,
            summary.status,
        ) = (
            "5533",
            account.id,
            "SGD",
            date(2025, 1, 1),
            date(2025, 1, 31),
            Decimal("1000.00"),
            Decimal("1000.00"),
            90,
            True,
            None,
            BankStatementStatus.APPROVED,
        )
        res = build_statement_extraction_result(
            source=args[1],
            file_type="pdf",
            statement=summary,
            transactions=[],
            provider_payload={"transactions": []},
            model="fixture-model",
            provider="fixture-provider",
            method=ExtractionMethod.GOLDEN_FIXTURE,
            is_brokerage=False,
            evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
            positions=[],
        )
        summary.extraction_metadata = {"statement_extraction_result": res.to_payload()}
        await session.flush()
        armed = fail_commit
        return [res]

    monkeypatch.setattr("src.extraction.extension.service.ExtractionService.parse_documents", mock_parse)
    job = ParseJob(
        statement_id=sid,
        run_id=await run_for(db, sid),
        filename="test.pdf",
        institution="DBS",
        user_id=uid,
        account_id=account.id,
        file_hash=f"bg_{sid.hex[:8]}",
        storage_key="test_path",
    )
    if fail_commit:
        with pytest.raises(RetryableStatementIngestionError, match="Simulated DB commit failure"):
            await parse_statement_background(job=job, content=b"dummy", session_maker=create_session_maker_from_db(db))
        db.expire_all()
        assert ((s := await db.get(StatementSummary, sid)).status, s.validation_error) == (
            BankStatementStatus.PARSING,
            None,
        )
    else:
        await parse_statement_background(job=job, content=b"dummy", session_maker=create_session_maker_from_db(db))
        db.expire_all()
        assert (
            (s := await db.get(StatementSummary, sid)).status,
            s.account_last4,
            s.confidence_score,
            s.balance_validated,
        ) == (BankStatementStatus.APPROVED, "5533", 90, True)


@pytest.mark.parametrize("kind", ["data_error", "integrity_error"])
async def test_handle_parse_failure_after_db_error(db, test_user, kind):
    sid = uuid4()
    stmt = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash=f"cas_{sid.hex[:8]}",
        institution="DBS",
    )
    db.add(stmt)
    await db.commit()
    try:
        if kind == "data_error":
            stmt.account_last4 = "TOOLONG"
            await db.flush()
        else:
            await db.execute(text("INSERT INTO nonexistent_cascade_table VALUES (1)"))
    except Exception:
        pass
    msg = "StringDataRightTruncationError: account_last4" if kind == "data_error" else "Integrity violation test"
    await handle_parse_failure(StatementSummary(id=sid), db, message=msg)
    res = await db.get(StatementSummary, sid)
    assert res is not None and res.status == BankStatementStatus.REJECTED and msg.split(":")[0] in res.validation_error


@pytest.mark.no_db
def test_sanitize_account_last4_and_identity_hash_invariants():
    cases = [
        ("553-3", "5533"),
        ("6789", "6789"),
        ("A", "A"),
        ("AB", "AB"),
        ("ABC", "ABC"),
        ("ABCD", "ABCD"),
        ("ABCDE", "BCDE"),
        ("A" * 100, "AAAA"),
        ("1" * 1000, "1111"),
        ("-", None),
        ("----", None),
        ("...", None),
        ("!@#$%^&*()", None),
        ("🏦💰", None),
        ("\t\n\r", None),
        ("  ", None),
        ("A-B-C-D", "ABCD"),
        ("---A", "A"),
        ("A---", "A"),
        ("1.2.3.4", "1234"),
        ("(1234)", "1234"),
        ("*5533*", "5533"),
        ("acct#5533", "5533"),
        ("１２３４", None),
        ("ＡＢＣＤ", None),
        ("账户5533", "5533"),
        ("口座1234", "1234"),
        ("계좌5533", "5533"),
        (None, None),
        ("", None),
        ("   ", None),
        ("abcd", "abcd"),
        ("ABCD", "ABCD"),
        ("AbCd", "AbCd"),
    ]
    for input_val, expected in cases:
        res = sanitize_account_last4(input_val)
        assert res == expected and (res is None or (len(res) <= 4 and res.isalnum()))
    for random_input in ("a" * i + "-" * j + "1" * k for i in range(4) for j in range(3) for k in range(4)):
        expected_alnum = re.sub("[^a-zA-Z0-9]", "", random_input)
        assert sanitize_account_last4(random_input) == (expected_alnum[-4:] if expected_alnum else None)

    assert (
        compute_transaction_identity_hash(legacy_hash="abc123def456", currency="sgd", custody_scope="account:1111-2222")
        == hashlib.sha256(b"v2|SGD|account:1111-2222|abc123def456").hexdigest()
    )
    assert (
        len(
            {
                compute_transaction_identity_hash("hash1", "SGD", "account:1"),
                compute_transaction_identity_hash("hash1", "USD", "account:1"),
                compute_transaction_identity_hash("hash1", "SGD", "account:2"),
            }
        )
        == 3
    )
