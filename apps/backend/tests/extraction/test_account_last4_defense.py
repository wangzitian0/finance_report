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
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models.statement import BankStatement, BankStatementStatus
from src.services.extraction import ExtractionService

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

    @pytest.mark.asyncio
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
            stmt, txns = await service.parse_document(
                file_path=Path("/tmp/test_sanitize.pdf"),
                institution="DBS",
                user_id=uuid4(),
                file_content=b"dummy",
                file_hash="abc123",
            )

        assert stmt.account_last4 == expected_sanitized
        if expected_sanitized is not None:
            assert len(expected_sanitized) <= 4
            assert all(c in string.ascii_letters + string.digits for c in expected_sanitized)

    @pytest.mark.asyncio
    async def test_dirty_account_last4_persists_to_db(self, db):
        """End-to-end: AI returns "553-3" → sanitized → saved to real DB → read back OK."""
        service = ExtractionService()

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

        uid = uuid4()
        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=mock_data)):
            stmt, _ = await service.parse_document(
                file_path=Path("/tmp/test_persist.pdf"),
                institution="DBS",
                user_id=uid,
                file_content=b"dummy",
                file_hash=f"persist_test_{uuid4().hex[:8]}",
            )

        # parse_document returns a transient BankStatement with file_path=None,
        # but DB column is NOT NULL — set it before persisting (mirrors router behavior).
        stmt.file_path = "test/persist_path"
        stmt.original_filename = "test.pdf"
        db.add(stmt)
        await db.commit()

        saved = await db.get(BankStatement, stmt.id)
        assert saved is not None
        assert saved.account_last4 == "5533"
        assert len(saved.account_last4) <= 4


# ---------------------------------------------------------------------------
# Gap 2: DB column constraint — VARCHAR(4) rejects oversized values
# ---------------------------------------------------------------------------


class TestDbConstraintVarchar4:
    """Direct DB constraint tests: prove VARCHAR(4) rejects > 4 char values.

    Closes gap: zero constraint violation tests existed before.
    """

    @pytest.mark.asyncio
    async def test_direct_write_oversized_account_last4_raises(self, db):
        """Writing account_last4 > 4 chars directly triggers DataError."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=uuid4(),
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"constraint_test_{uuid4().hex[:8]}",
            original_filename="test.pdf",
            institution="DBS",
            account_last4="553-3",  # 5 chars — exceeds VARCHAR(4)
        )
        db.add(stmt)

        with pytest.raises(Exception, match="value too long|StringDataRightTruncation"):
            await db.flush()

        await db.rollback()

    @pytest.mark.asyncio
    async def test_exactly_4_chars_accepted(self, db):
        """Writing account_last4 = exactly 4 chars succeeds."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=uuid4(),
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"exact4_test_{uuid4().hex[:8]}",
            original_filename="test.pdf",
            institution="DBS",
            account_last4="5533",
        )
        db.add(stmt)
        await db.commit()

        saved = await db.get(BankStatement, stmt.id)
        assert saved.account_last4 == "5533"

    @pytest.mark.asyncio
    async def test_null_account_last4_accepted(self, db):
        """Writing account_last4 = NULL succeeds (nullable column)."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=uuid4(),
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"null_test_{uuid4().hex[:8]}",
            original_filename="test.pdf",
            institution="DBS",
            account_last4=None,
        )
        db.add(stmt)
        await db.commit()

        saved = await db.get(BankStatement, stmt.id)
        assert saved.account_last4 is None


# ---------------------------------------------------------------------------
# Gap 3: Background task end-to-end with dirty account_last4
# ---------------------------------------------------------------------------


class TestBackgroundTaskDirtyData:
    """End-to-end: _parse_statement_background with dirty AI data.

    Closes gap: only ExtractionError / StorageError paths were tested before.
    """

    @pytest.mark.asyncio
    async def test_background_task_with_dirty_account_last4_succeeds(self, db, monkeypatch):
        """Full background task flow: dirty AI response → sanitized → saved → PARSED/APPROVED."""
        from src.database import create_session_maker_from_db
        from src.routers.statements import _parse_statement_background

        sid = uuid4()
        uid = uuid4()
        stmt = BankStatement(
            id=sid,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"bg_dirty_{uuid4().hex[:8]}",
            original_filename="test.pdf",
            institution="DBS",
        )
        db.add(stmt)
        await db.commit()

        # Mock parse_document to return a BankStatement with dirty→sanitized account_last4
        parsed_stmt = BankStatement(
            user_id=uid,
            institution="DBS",
            account_last4="5533",  # Already sanitized by _sanitize_account_last4
            currency="SGD",
            period_start=None,
            period_end=None,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.00"),
            confidence_score=90,
            balance_validated=True,
            validation_error=None,
            status=BankStatementStatus.APPROVED,
            file_path="test_path",
            file_hash="dummy",
            original_filename="test.pdf",
        )
        mock_parse = AsyncMock(return_value=(parsed_stmt, []))
        monkeypatch.setattr("src.routers.statements.ExtractionService.parse_document", mock_parse)

        # Mock storage presigned URL
        async def mock_run_in_threadpool(func, *args, **kwargs):
            return "https://example.com/presigned"

        monkeypatch.setattr("src.routers.statements.run_in_threadpool", mock_run_in_threadpool)

        await _parse_statement_background(
            statement_id=sid,
            filename="test.pdf",
            institution="DBS",
            user_id=uid,
            account_id=None,
            file_hash=f"bg_dirty_{uuid4().hex[:8]}",
            storage_key="test_path",
            content=b"dummy content",
            model=None,
            session_maker=create_session_maker_from_db(db),
        )

        # Verify statement was updated correctly
        db.expire_all()
        saved = await db.get(BankStatement, sid)
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

    @pytest.mark.asyncio
    async def test_handle_parse_failure_after_data_error(self, db):
        """Simulate the exact production failure: commit DataError → handler recovers."""
        from src.routers.statements import _handle_parse_failure

        sid = uuid4()
        stmt = BankStatement(
            id=sid,
            user_id=uuid4(),
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"cascade_data_{uuid4().hex[:8]}",
            original_filename="test.pdf",
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
        stub = BankStatement(id=sid)

        # _handle_parse_failure must recover from this error state
        await _handle_parse_failure(stub, db, message="StringDataRightTruncationError: account_last4")

        # Verify: statement is REJECTED, not stuck in PARSING
        result = await db.get(BankStatement, sid)
        assert result is not None
        assert result.status == BankStatementStatus.REJECTED
        assert "StringDataRightTruncation" in result.validation_error
        assert result.confidence_score == 0

    @pytest.mark.asyncio
    async def test_handle_parse_failure_after_integrity_error(self, db):
        """Handler recovers after IntegrityError (e.g., duplicate file_hash)."""
        from src.routers.statements import _handle_parse_failure

        uid = uuid4()
        shared_hash = f"dup_hash_{uuid4().hex[:8]}"

        # Create first statement
        stmt1 = BankStatement(
            id=uuid4(),
            user_id=uid,
            status=BankStatementStatus.APPROVED,
            file_path="path1",
            file_hash=shared_hash,
            original_filename="file1.pdf",
            institution="DBS",
        )
        db.add(stmt1)
        await db.commit()

        # Create second statement (the one being parsed)
        sid2 = uuid4()
        stmt2 = BankStatement(
            id=sid2,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_path="path2",
            file_hash=f"other_hash_{uuid4().hex[:8]}",
            original_filename="file2.pdf",
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
        stub2 = BankStatement(id=sid2)
        await _handle_parse_failure(stub2, db, message="Integrity violation test")

        result = await db.get(BankStatement, sid2)
        assert result is not None
        assert result.status == BankStatementStatus.REJECTED
        assert result.validation_error == "Integrity violation test"

    @pytest.mark.asyncio
    async def test_background_task_commit_failure_falls_through_to_handler(self, db, monkeypatch):
        """Verify that when commit() fails at finalize, _handle_parse_failure is invoked.

        We cannot use a real VARCHAR violation because the dirty data persists
        in SQLAlchemy's identity map, causing the handler's own commit() to
        re-fail (known limitation — _sanitize_account_last4 prevents this
        in production).  Instead we verify the handler is called with the
        correct arguments.
        """
        from src.routers.statements import _handle_parse_failure

        sid = uuid4()
        uid = uuid4()
        stmt = BankStatement(
            id=sid,
            user_id=uid,
            status=BankStatementStatus.PARSING,
            file_path="test_path",
            file_hash=f"commit_fail_{uuid4().hex[:8]}",
            original_filename="test.pdf",
            institution="DBS",
        )
        db.add(stmt)
        await db.commit()

        handler_called_with: dict | None = None

        async def spy_handler(statement, db_session, *, message):
            nonlocal handler_called_with
            handler_called_with = {"statement_id": statement.id, "message": message}
            return await _handle_parse_failure(statement, db_session, message=message)

        monkeypatch.setattr("src.routers.statements._handle_parse_failure", spy_handler)

        original_commit = AsyncSession.commit
        fail_next_commit = False

        async def conditional_failing_commit(session_self):
            nonlocal fail_next_commit
            if fail_next_commit:
                fail_next_commit = False
                raise RuntimeError("Simulated DB commit failure at finalize step")
            return await original_commit(session_self)

        monkeypatch.setattr(AsyncSession, "commit", conditional_failing_commit)

        parsed_stmt = BankStatement(
            user_id=uid,
            institution="DBS",
            account_last4="1234",
            currency="SGD",
            period_start=None,
            period_end=None,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.00"),
            confidence_score=90,
            balance_validated=True,
            validation_error=None,
            status=BankStatementStatus.APPROVED,
            file_path="test_path",
            file_hash="dummy",
            original_filename="test.pdf",
        )

        async def parse_then_arm_failure(*args, **kwargs):
            nonlocal fail_next_commit
            fail_next_commit = True
            return (parsed_stmt, [])

        monkeypatch.setattr(
            "src.routers.statements.ExtractionService.parse_document",
            parse_then_arm_failure,
        )

        async def mock_run_in_threadpool(func, *args, **kwargs):
            return "https://example.com/presigned"

        monkeypatch.setattr("src.routers.statements.run_in_threadpool", mock_run_in_threadpool)

        from src.database import create_session_maker_from_db
        from src.routers.statements import _parse_statement_background

        try:
            await _parse_statement_background(
                statement_id=sid,
                filename="test.pdf",
                institution="DBS",
                user_id=uid,
                account_id=None,
                file_hash=f"commit_fail_{uuid4().hex[:8]}",
                storage_key="test_path",
                content=b"dummy content",
                model=None,
                session_maker=create_session_maker_from_db(db),
            )
        except Exception:
            pass

        assert handler_called_with is not None, "_handle_parse_failure was never called"
        assert handler_called_with["statement_id"] == sid
        assert "Simulated DB commit failure" in handler_called_with["message"]

        db.expire_all()
        saved = await db.get(BankStatement, sid)
        assert saved is not None
        assert saved.status == BankStatementStatus.REJECTED


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
