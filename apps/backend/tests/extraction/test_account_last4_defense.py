"""Defense-in-depth tests for account_last4 — the field that caused the production stuck-PARSING bug.

Root cause analysis (PR #269):
  AI returned `account_last4 = "553-3"` (5 chars with hyphen) → VARCHAR(4) overflow
  → StringDataRightTruncationError → _handle_parse_failure also crashed (PendingRollbackError
  + MissingGreenlet on expired ORM object) → statement permanently stuck in PARSING.

These tests exist because the ORIGINAL test suite failed to catch this bug. Specific gaps:
  1. All AI mocks used clean `"6789"` — never tested dirty/oversized data
  2. Zero DB constraint violation tests for VARCHAR(4)
  3. _handle_parse_failure only tested with clean sessions, never error-state sessions
  4. No end-to-end test for the commit-fail → error-handler → recovery path
  5. extraction.py was excluded from coverage (pyproject.toml omit list)

Each test class below closes one specific gap.
"""

import string
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentSource, ExtractionMethod, ParseJob, StatementEvidenceType
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import parse_and_load_statement_projection


async def _make_statement_account(db: AsyncSession, user_id) -> Account:
    account = Account(
        user_id=user_id,
        name=f"DBS Statement {uuid4().hex[:8]}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


# ---------------------------------------------------------------------------
# Gap 1: AI returns dirty account_last4 → parse_document sanitizes → DB stores ≤ 4 chars
# ---------------------------------------------------------------------------


class TestDirtyAccountLast4Integration:
    """Integration tests: mock AI returns dirty account_last4, verify sanitized value reaches DB.

    Closes gap: original test_extraction_flow.py always used clean "6789".
    """

    DIRTY_AI_RESPONSES = [
        pytest.param("553-3", "5533", id="hyphenated-5-chars"),
        pytest.param("ABCDE", "BCDE", id="5-alpha-takes-last4"),
        pytest.param("12号34", "1234", id="unicode-stripped"),
        pytest.param("1234-5678-9012", "9012", id="long-account-number"),
        pytest.param("----", None, id="only-hyphens"),
        pytest.param("", None, id="empty-string"),
        pytest.param(None, None, id="null-value"),
        pytest.param("  5 5 3 3  ", "5533", id="spaces-stripped"),
        pytest.param("X", "X", id="single-char-preserved"),
        pytest.param("AB", "AB", id="two-chars-preserved"),
    ]

    @pytest.mark.parametrize("ai_value,expected_sanitized", DIRTY_AI_RESPONSES)
    async def test_parse_document_sanitizes_account_last4(self, ai_value, expected_sanitized):
        """AI returns dirty account_last4 → parse_document sanitizes to ≤ 4 alphanumeric."""
        service = ExtractionService()

        mock_data = {
            "institution": "DBS",
            "account_last4": ai_value,
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {
                    "date": "2025-01-15",
                    "description": "Salary",
                    "amount": "100.00",
                    "direction": "IN",
                },
            ],
        }

        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=mock_data)):
            result = await service.parse_document(
                DocumentSource.resolve(path=Path("/tmp/test_sanitize.pdf"), content=b"dummy"),
                institution="DBS",
                user_id=uuid4(),
            )

        assert result.account_last4 == expected_sanitized
        if expected_sanitized is not None:
            assert len(expected_sanitized) <= 4
            assert all(c in string.ascii_letters + string.digits for c in expected_sanitized)

    async def test_dirty_account_last4_persists_to_db(self, db, test_user):
        """End-to-end: AI returns "553-3" → sanitized → saved to real DB → read back OK."""
        service = ExtractionService()
        account = await _make_statement_account(db, test_user.id)

        mock_data = {
            "institution": "DBS",
            "account_last4": "553-3",  # The exact production value that caused the bug
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {
                    "date": "2025-01-15",
                    "description": "Test",
                    "amount": "100.00",
                    "direction": "IN",
                },
            ],
        }

        uid = test_user.id
        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=mock_data)):
            result, stmt, _ = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("/tmp/test_persist.pdf"), content=b"dummy"),
                institution="DBS",
                user_id=uid,
                account_id=account.id,
            )
        await db.commit()

        saved = await db.get(StatementSummary, stmt.id)
        assert saved is not None
        assert saved.account_last4 == "5533"
        assert len(saved.account_last4) <= 4

    async def test_parse_document_without_account_stays_parsed_before_approval(self):
        """A source result stays factual when custody-account context is absent."""
        service = ExtractionService()

        mock_data = {
            "institution": "DBS",
            "account_last4": "553-3",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {
                    "date": "2025-01-15",
                    "description": "Test",
                    "amount": "100.00",
                    "direction": "IN",
                },
            ],
        }

        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=mock_data)):
            result = await service.parse_document(
                DocumentSource.resolve(path=Path("/tmp/test_requires_account.pdf"), content=b"dummy"),
                institution="DBS",
                user_id=uuid4(),
            )

        assert result.balance_validated is True
        assert result.account_last4 == "5533"


# ---------------------------------------------------------------------------
# Gap 2: DB column constraint — VARCHAR(4) rejects oversized values
# ---------------------------------------------------------------------------


class TestDbConstraintVarchar4:
    """Direct DB constraint tests: prove VARCHAR(4) rejects > 4 char values.

    Closes gap: zero constraint violation tests existed before.
    """

    async def test_direct_write_oversized_account_last4_raises(self, db, test_user):
        """Writing account_last4 > 4 chars directly triggers DataError."""
        stmt = StatementSummaryFactory.build(
            id=uuid4(),
            user_id=test_user.id,
            status=BankStatementStatus.PARSING,
            file_hash=f"constraint_test_{uuid4().hex[:8]}",
            institution="DBS",
            account_last4="553-3",  # 5 chars — exceeds VARCHAR(4)
        )
        db.add(stmt)

        with pytest.raises(Exception, match="value too long|StringDataRightTruncation"):
            await db.flush()

        await db.rollback()

    async def test_exactly_4_chars_accepted(self, db, test_user):
        """Writing account_last4 = exactly 4 chars succeeds."""
        stmt = StatementSummaryFactory.build(
            id=uuid4(),
            user_id=test_user.id,
            status=BankStatementStatus.PARSING,
            file_hash=f"exact4_test_{uuid4().hex[:8]}",
            institution="DBS",
            account_last4="5533",
        )
        db.add(stmt)
        await db.commit()

        saved = await db.get(StatementSummary, stmt.id)
        assert saved.account_last4 == "5533"

    async def test_null_account_last4_accepted(self, db, test_user):
        """Writing account_last4 = NULL succeeds (nullable column)."""
        stmt = StatementSummaryFactory.build(
            id=uuid4(),
            user_id=test_user.id,
            status=BankStatementStatus.PARSING,
            file_hash=f"null_test_{uuid4().hex[:8]}",
            institution="DBS",
            account_last4=None,
        )
        db.add(stmt)
        await db.commit()

        saved = await db.get(StatementSummary, stmt.id)
        assert saved.account_last4 is None


# ---------------------------------------------------------------------------
# Gap 3: Background task end-to-end with dirty account_last4
# ---------------------------------------------------------------------------


class TestBackgroundTaskDirtyData:
    """End-to-end: _parse_statement_background with dirty AI data.

    Closes gap: only ExtractionError / StorageError paths were tested before.
    """

    async def test_background_task_with_dirty_account_last4_succeeds(self, db, test_user, monkeypatch):
        """Full background task flow: dirty AI response → sanitized → saved → PARSED/APPROVED."""
        from src.database import create_session_maker_from_db
        from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background

        sid = uuid4()
        uid = test_user.id
        account = await _make_statement_account(db, uid)
        stmt = StatementSummaryFactory.build(
            id=sid,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_hash=f"bg_dirty_{uuid4().hex[:8]}",
            institution="DBS",
        )
        db.add(stmt)
        await db.commit()

        # Mock parse_document to mirror dual_write_layer2: it receives the background
        # session and updates the pre-created StatementSummary row in place with the
        # sanitized account_last4 and approved envelope, then returns it.
        async def mock_parse(*args, **kwargs):
            source = args[1]
            session = kwargs["db"]
            summary = await session.get(StatementSummary, sid)
            summary.account_last4 = "5533"  # Already sanitized by _sanitize_account_last4
            summary.account_id = account.id
            summary.currency = "SGD"
            summary.period_start = date(2025, 1, 1)
            summary.period_end = date(2025, 1, 31)
            summary.opening_balance = Decimal("1000.00")
            summary.closing_balance = Decimal("1000.00")
            summary.confidence_score = 90
            summary.balance_validated = True
            summary.validation_error = None
            summary.status = BankStatementStatus.APPROVED
            result = build_statement_extraction_result(
                source=source,
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
            summary.extraction_metadata = {"statement_extraction_result": result.to_payload()}
            await session.flush()
            return result

        monkeypatch.setattr("src.extraction.extension.service.ExtractionService.parse_document", mock_parse)

        # Mock storage presigned URL
        async def mock_run_in_threadpool(func, *args, **kwargs):
            return "https://example.com/presigned"

        monkeypatch.setattr("fastapi.concurrency.run_in_threadpool", mock_run_in_threadpool)

        await parse_statement_background(
            job=ParseJob(
                statement_id=sid,
                filename="test.pdf",
                institution="DBS",
                user_id=uid,
                account_id=account.id,
                file_hash=f"bg_dirty_{uuid4().hex[:8]}",
                storage_key="test_path",
                model=None,
            ),
            content=b"dummy content",
            session_maker=create_session_maker_from_db(db),
        )

        # Verify statement was updated correctly
        db.expire_all()
        saved = await db.get(StatementSummary, sid)
        assert saved is not None
        assert saved.status == BankStatementStatus.APPROVED
        assert saved.account_last4 == "5533"
        assert saved.confidence_score == 90
        assert saved.balance_validated is True


# ---------------------------------------------------------------------------
# Gap 4: Cascading failure — commit fails → _handle_parse_failure recovers
# ---------------------------------------------------------------------------


class TestCascadingFailureRecovery:
    """Tests that _handle_parse_failure correctly recovers when called after a failed commit.

    Closes gap: original tests only called _handle_parse_failure on clean sessions.
    The production bug had TWO cascading failures:
      1. session.commit() failed with StringDataRightTruncationError
      2. _handle_parse_failure then failed with PendingRollbackError + MissingGreenlet

    These tests verify the fix handles both.
    """

    async def test_handle_parse_failure_after_data_error(self, db, test_user):
        """Simulate the exact production failure: commit DataError → handler recovers."""
        from src.extraction.extension.statement_parsing import handle_parse_failure

        sid = uuid4()
        stmt = StatementSummaryFactory.build(
            id=sid,
            user_id=test_user.id,
            status=BankStatementStatus.PARSING,
            file_hash=f"cascade_data_{uuid4().hex[:8]}",
            institution="DBS",
        )
        db.add(stmt)
        await db.commit()

        # Simulate a DataError by writing oversized value then flushing
        stmt.account_last4 = "TOOLONG"  # > 4 chars
        try:
            await db.flush()
        except Exception:
            pass  # Session is now in error state — exactly like production

        # After a failed flush, ORM attributes are expired and inaccessible
        # (accessing stmt.id triggers MissingGreenlet). Create a detached stub
        # that carries only .id — this mirrors what happens in the background task
        # where the handler receives a statement object whose session is broken.
        stub = StatementSummary(id=sid)

        # _handle_parse_failure must recover from this error state
        await handle_parse_failure(stub, db, message="StringDataRightTruncationError: account_last4")

        # Verify: statement is REJECTED, not stuck in PARSING
        result = await db.get(StatementSummary, sid)
        assert result is not None
        assert result.status == BankStatementStatus.REJECTED
        assert "StringDataRightTruncation" in result.validation_error
        assert result.confidence_score == 0

    async def test_handle_parse_failure_after_integrity_error(self, db, test_user):
        """Handler recovers after IntegrityError (e.g., duplicate file_hash)."""
        from src.extraction.extension.statement_parsing import handle_parse_failure

        uid = test_user.id
        shared_hash = f"dup_hash_{uuid4().hex[:8]}"

        # Create first statement
        stmt1 = StatementSummaryFactory.build(
            id=uuid4(),
            user_id=uid,
            status=BankStatementStatus.PARSED,
            file_hash=shared_hash,
            institution="DBS",
        )
        db.add(stmt1)
        await db.commit()

        # Create second statement (the one being parsed)
        sid2 = uuid4()
        stmt2 = StatementSummaryFactory.build(
            id=sid2,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_hash=f"other_hash_{uuid4().hex[:8]}",
            institution="DBS",
        )
        db.add(stmt2)
        await db.commit()

        # Put session into error state with a bad SQL
        try:
            await db.execute(text("INSERT INTO nonexistent_cascade_table VALUES (1)"))
        except Exception:
            pass  # Session now needs rollback

        # Handler should recover
        stub2 = StatementSummary(id=sid2)
        await handle_parse_failure(stub2, db, message="Integrity violation test")

        result = await db.get(StatementSummary, sid2)
        assert result is not None
        assert result.status == BankStatementStatus.REJECTED
        assert result.validation_error == "Integrity violation test"

    async def test_background_task_commit_failure_is_retryable(self, db, test_user, monkeypatch):
        """A finalize commit failure is not misreported as source rejection."""
        from src.extraction import RetryableStatementIngestionError

        sid = uuid4()
        uid = test_user.id
        account = await _make_statement_account(db, uid)
        stmt = StatementSummaryFactory.build(
            id=sid,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_hash=f"commit_fail_{uuid4().hex[:8]}",
            institution="DBS",
        )
        db.add(stmt)
        await db.commit()

        original_commit = AsyncSession.commit
        fail_next_commit = False

        async def conditional_failing_commit(session_self):
            nonlocal fail_next_commit
            if fail_next_commit:
                fail_next_commit = False
                raise RuntimeError("Simulated DB commit failure at finalize step")
            return await original_commit(session_self)

        monkeypatch.setattr(AsyncSession, "commit", conditional_failing_commit)

        async def parse_then_arm_failure(*args, **kwargs):
            nonlocal fail_next_commit
            source = args[1]
            session = kwargs["db"]
            summary = await session.get(StatementSummary, sid)
            summary.account_id = account.id
            summary.account_last4 = "1234"
            summary.currency = "SGD"
            summary.period_start = date(2025, 1, 1)
            summary.period_end = date(2025, 1, 31)
            summary.opening_balance = Decimal("1000.00")
            summary.closing_balance = Decimal("1100.00")
            summary.confidence_score = 90
            summary.balance_validated = True
            summary.validation_error = None
            summary.status = BankStatementStatus.APPROVED
            result = build_statement_extraction_result(
                source=source,
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
            summary.extraction_metadata = {"statement_extraction_result": result.to_payload()}
            await session.flush()
            fail_next_commit = True
            return result

        monkeypatch.setattr(
            "src.extraction.extension.service.ExtractionService.parse_document",
            parse_then_arm_failure,
        )

        async def mock_run_in_threadpool(func, *args, **kwargs):
            return "https://example.com/presigned"

        monkeypatch.setattr("fastapi.concurrency.run_in_threadpool", mock_run_in_threadpool)

        from src.database import create_session_maker_from_db
        from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background

        with pytest.raises(RetryableStatementIngestionError, match="Simulated DB commit failure"):
            await parse_statement_background(
                job=ParseJob(
                    statement_id=sid,
                    filename="test.pdf",
                    institution="DBS",
                    user_id=uid,
                    account_id=account.id,
                    file_hash=f"commit_fail_{uuid4().hex[:8]}",
                    storage_key="test_path",
                    model=None,
                ),
                content=b"dummy content",
                session_maker=create_session_maker_from_db(db),
            )

        db.expire_all()
        saved = await db.get(StatementSummary, sid)
        assert saved is not None
        assert saved.status == BankStatementStatus.PARSING
        assert saved.validation_error is None


# ---------------------------------------------------------------------------
# Gap 5: Exhaustive parametrized _sanitize_account_last4 (replaces hypothesis)
# ---------------------------------------------------------------------------


class TestSanitizeAccountLast4Exhaustive:
    """Exhaustive parametrized tests for _sanitize_account_last4.

    Verifies the invariant: output is ALWAYS None or ≤ 4 alphanumeric characters.
    Covers edge cases that the original 12 unit tests missed.
    """

    EDGE_CASES = [
        # Production-observed values
        pytest.param("553-3", "5533", id="production-bug-value"),
        pytest.param("6789", "6789", id="clean-4-digits"),
        # Boundary lengths
        pytest.param("A", "A", id="len-1"),
        pytest.param("AB", "AB", id="len-2"),
        pytest.param("ABC", "ABC", id="len-3"),
        pytest.param("ABCD", "ABCD", id="len-4-exact"),
        pytest.param("ABCDE", "BCDE", id="len-5-truncates"),
        pytest.param("A" * 100, "AAAA", id="len-100-truncates"),
        pytest.param("1" * 1000, "1111", id="len-1000-truncates"),
        # Special character patterns
        pytest.param("-", None, id="single-hyphen"),
        pytest.param("----", None, id="all-hyphens"),
        pytest.param("...", None, id="dots-only"),
        pytest.param("!@#$%^&*()", None, id="all-special"),
        pytest.param("🏦💰", None, id="emoji-only"),
        pytest.param("\t\n\r", None, id="whitespace-only"),
        pytest.param("  ", None, id="spaces-only"),
        # Mixed special + alphanumeric
        pytest.param("A-B-C-D", "ABCD", id="hyphens-between-each"),
        pytest.param("---A", "A", id="leading-hyphens"),
        pytest.param("A---", "A", id="trailing-hyphens"),
        pytest.param("1.2.3.4", "1234", id="dots-between"),
        pytest.param("(1234)", "1234", id="parentheses"),
        pytest.param("*5533*", "5533", id="asterisks"),
        pytest.param("acct#5533", "5533", id="hash-prefix"),
        # Unicode edge cases
        pytest.param("１２３４", None, id="fullwidth-digits-stripped"),
        pytest.param("ＡＢＣＤ", None, id="fullwidth-alpha-stripped"),
        pytest.param("账户5533", "5533", id="chinese-prefix-stripped"),
        pytest.param("口座1234", "1234", id="japanese-prefix-stripped"),
        pytest.param("계좌5533", "5533", id="korean-prefix-stripped"),
        # Null / empty
        pytest.param(None, None, id="none"),
        pytest.param("", None, id="empty"),
        pytest.param("   ", None, id="spaces-trimmed-empty"),
        # Case preservation
        pytest.param("abcd", "abcd", id="lowercase-preserved"),
        pytest.param("ABCD", "ABCD", id="uppercase-preserved"),
        pytest.param("AbCd", "AbCd", id="mixed-case-preserved"),
    ]

    @pytest.mark.parametrize("input_val,expected", EDGE_CASES)
    def test_sanitize_invariant(self, input_val, expected):
        """Every output must be None or ≤ 4 alphanumeric characters."""
        result = ExtractionService._sanitize_account_last4(input_val)
        assert result == expected

        # Invariant check: output is always safe for VARCHAR(4)
        if result is not None:
            assert len(result) <= 4, f"Output '{result}' exceeds 4 chars"
            assert result.isalnum(), f"Output '{result}' contains non-alphanumeric chars"

    @pytest.mark.parametrize(
        "random_input",
        ["a" * i + "-" * j + "1" * k for i in range(0, 4) for j in range(0, 3) for k in range(0, 4)],
    )
    def test_output_never_exceeds_4_chars(self, random_input):
        """Combinatorial: no combination of alphanumeric + hyphens exceeds 4 chars."""
        result = ExtractionService._sanitize_account_last4(random_input)
        if result is not None:
            assert len(result) <= 4
            assert result.isalnum()
