"""Stage 1 statement validation transition tests (DWD conform model)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction import DocumentType, UploadedDocument
from src.extraction.extension.statement_validation import (
    BALANCE_TOLERANCE,
    _has_unresolved_statement_conflicts,
    approve_statement,
    edit_and_approve,
    get_pending_stage1_review,
    reject_statement,
    set_opening_balance,
    validate_balance_chain,
)
from src.ledger import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary


def _conflict_txn(
    *,
    balance_after: Decimal | None,
    description: str = "Buy to Open NIO Inc NIO",
    amount: Decimal = Decimal("1033.50"),
    direction: TransactionDirection = TransactionDirection.OUT,
    txn_date: date = date(2025, 6, 25),
) -> AtomicTransaction:
    """Build an in-memory AtomicTransaction for conflict-guard unit tests (not persisted)."""
    return AtomicTransaction(
        id=uuid4(),
        user_id=uuid4(),
        txn_date=txn_date,
        amount=amount,
        direction=direction,
        description=description,
        currency="USD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[],
        balance_after=balance_after,
    )


class TestDuplicateGuardBalanceAfter:
    """The Stage-1 conflict guard must stay consistent with the dedup disambiguator."""

    def test_duplicate_guard_distinguishes_by_balance_after(self):
        """AC-reconciliation.source-type-transfer.5: AC4.6.6: Two transactions identical in date/description/amount/direction but with
        different running balances (balance_after) are NOT flagged as duplicate candidates --
        the dedup layer already deemed them distinct, so the guard must not re-collapse them."""
        txns = [
            _conflict_txn(balance_after=Decimal("5000.00")),
            _conflict_txn(balance_after=Decimal("3966.50")),
        ]
        assert _has_unresolved_statement_conflicts(txns) is False

    def test_duplicate_guard_flags_when_balance_after_equal_or_absent(self):
        """AC-reconciliation.source-type-transfer.6: AC4.6.7: Identical transactions with equal or absent balance_after remain flagged
        as duplicate candidates (genuinely ambiguous -> needs human review)."""
        equal_balance = [
            _conflict_txn(balance_after=Decimal("5000.00")),
            _conflict_txn(balance_after=Decimal("5000.00")),
        ]
        assert _has_unresolved_statement_conflicts(equal_balance) is True

        no_balance = [
            _conflict_txn(balance_after=None),
            _conflict_txn(balance_after=None),
        ]
        assert _has_unresolved_statement_conflicts(no_balance) is True


DEFAULT_ACCOUNT_NAME = "Statement Validation Default Account"


def test_AC18_13_5_balance_chain_decision_routes_through_promotion_gate():
    """AC-audit.41.5: AC18.13.5: Stage-1 balance approval is disposed by the promotion gate, preserving the exact messages."""
    from src.extraction.extension.statement_validation import _raise_if_balance_chain_invalid

    ok = {"opening_match": True, "closing_match": True, "opening_delta": "0", "closing_delta": "0"}
    _raise_if_balance_chain_invalid(ok)  # both invariants pass -> authoritative -> no raise

    with pytest.raises(ValueError, match="Opening balance mismatch"):
        _raise_if_balance_chain_invalid(
            {"opening_match": False, "closing_match": True, "opening_delta": "0.5", "closing_delta": "0"}
        )
    with pytest.raises(ValueError, match="Balance mismatch"):
        _raise_if_balance_chain_invalid(
            {"opening_match": True, "closing_match": False, "opening_delta": "0", "closing_delta": "0.5"}
        )
    with pytest.raises(ValueError, match="Balance still invalid after edits"):
        _raise_if_balance_chain_invalid(
            {"opening_match": True, "closing_match": False, "opening_delta": "0", "closing_delta": "0.5"},
            after_edits=True,
        )


@pytest.fixture
def user_id(test_user):
    return test_user.id


async def _default_account_id(db, user_id):
    result = await db.execute(
        select(Account.id).where(Account.user_id == user_id, Account.name == DEFAULT_ACCOUNT_NAME).limit(1)
    )
    account_id = result.scalar_one_or_none()
    if account_id is not None:
        return account_id

    account = Account(
        id=uuid4(),
        user_id=user_id,
        name=DEFAULT_ACCOUNT_NAME,
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.flush()
    return account.id


async def _make_statement(
    db,
    user_id,
    *,
    file_hash: str,
    account_id=None,
    opening_balance: Decimal | None = None,
    closing_balance: Decimal | None = None,
    manual_opening_balance: Decimal | None = None,
    period_start: date | None = date(2024, 1, 1),
    period_end: date | None = date(2024, 1, 31),
    status: BankStatementStatus = BankStatementStatus.PARSED,
    stage1_status: Stage1Status | None = None,
    confidence_score: int | None = None,
) -> StatementSummary:
    """Create an ODS document + linked StatementSummary conform envelope."""
    doc = UploadedDocument(
        id=uuid4(),
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()

    if account_id is None:
        account_id = await _default_account_id(db, user_id)

    statement = StatementSummary(
        id=uuid4(),
        user_id=user_id,
        uploaded_document_id=doc.id,
        account_id=account_id,
        file_hash=file_hash,
        institution="Test Bank",
        currency="USD",
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        manual_opening_balance=manual_opening_balance,
        status=status,
        stage1_status=stage1_status,
        confidence_score=confidence_score,
    )
    db.add(statement)
    await db.flush()
    return statement


async def _add_txn(
    db,
    statement: StatementSummary,
    *,
    amount: Decimal,
    direction: TransactionDirection = TransactionDirection.IN,
    txn_date: date = date(2024, 1, 15),
    description: str = "Deposit",
    reference: str | None = None,
) -> AtomicTransaction:
    txn = AtomicTransaction(
        id=uuid4(),
        user_id=statement.user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        reference=reference,
        currency="USD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[
            {
                "doc_id": str(statement.uploaded_document_id),
                "doc_type": DocumentType.BANK_STATEMENT.value,
            }
        ],
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.fixture
async def statement_with_transactions(db, user_id):
    stmt = await _make_statement(
        db,
        user_id,
        file_hash="hash123",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
    )
    await _add_txn(db, stmt, amount=Decimal("100.00"), direction=TransactionDirection.IN)
    return stmt


class TestValidateBalanceChain:
    async def test_exact_match(self, db, statement_with_transactions):
        """AC1.1.1 Verify exact balance match when calculated closing matches stated closing."""
        result = await validate_balance_chain(db, statement_with_transactions.id)

        assert result["opening_match"] is True
        assert result["closing_match"] is True
        assert Decimal(result["closing_delta"]) == Decimal("0.00")
        assert result["calculated_closing"] == "1100.00"

    async def test_within_tolerance(self, db, user_id):
        """AC1.1.2 AC16.1.1 AC16.22.5: Verify 0.0009 USD delta passes 0.001 tolerance."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash456",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.0009"),
        )
        await _add_txn(db, stmt, amount=Decimal("100.00"), direction=TransactionDirection.IN)

        result = await validate_balance_chain(db, stmt.id)
        assert result["closing_match"] is True
        assert Decimal(result["closing_delta"]) == Decimal("0.0009")
        assert Decimal(result["closing_delta"]) <= BALANCE_TOLERANCE

    async def test_exact_tolerance_boundary_passes(self, db, user_id):
        """AC16.1.1: Verify a 0.001 USD balance delta is still accepted."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_boundary",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.001"),
        )
        await _add_txn(db, stmt, amount=Decimal("100.00"), direction=TransactionDirection.IN)

        result = await validate_balance_chain(db, stmt.id)
        assert result["closing_match"] is True
        assert Decimal(result["closing_delta"]) == BALANCE_TOLERANCE

    async def test_exceeds_tolerance(self, db, user_id):
        """AC1.1.3 AC16.1.1: Verify balance mismatch when delta exceeds 0.001 USD."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash789",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.01"),
        )
        await _add_txn(db, stmt, amount=Decimal("100.00"), direction=TransactionDirection.IN)

        result = await validate_balance_chain(db, stmt.id)
        assert result["closing_match"] is False
        assert Decimal(result["closing_delta"]) > BALANCE_TOLERANCE

    async def test_manual_opening_balance(self, db, user_id):
        """AC1.1.4 Verify opening balance chain validation using manual override."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash111",
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("150.00"),
            manual_opening_balance=Decimal("100.00"),
        )
        await _add_txn(db, stmt, amount=Decimal("50.00"), direction=TransactionDirection.IN)

        result = await validate_balance_chain(db, stmt.id)
        assert result["opening_balance"] == "100.00"
        assert result["calculated_closing"] == "150.00"


class TestApproveStatement:
    async def test_approve_with_valid_balance(self, db, statement_with_transactions, user_id):
        """AC1.2.1 Approve statement when balance chain is valid."""
        stmt = await approve_statement(db, statement_with_transactions.id, user_id)

        assert stmt.stage1_status == Stage1Status.APPROVED
        assert stmt.status == BankStatementStatus.APPROVED
        assert stmt.balance_validation_result is not None
        assert stmt.balance_validation_result["closing_match"] is True

    async def test_approve_with_invalid_balance_raises(self, db, user_id):
        """AC1.2.2 AC16.22.1: Reject approval attempt when balance chain is invalid."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash222",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("2000.00"),
        )
        await _add_txn(
            db, stmt, amount=Decimal("10.00"), direction=TransactionDirection.IN, description="Small deposit"
        )

        with pytest.raises(ValueError, match="Balance mismatch"):
            await approve_statement(db, stmt.id, user_id)

    async def test_approve_with_opening_mismatch_raises(self, db, user_id):
        """AC16.22.1 AC16.31.2: Approval requires both opening and closing balance validation."""
        account = Account(
            id=uuid4(),
            user_id=user_id,
            name="Opening mismatch account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        await _make_statement(
            db,
            user_id,
            file_hash="hash_opening_prev",
            account_id=account.id,
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("100.00"),
            status=BankStatementStatus.APPROVED,
            stage1_status=Stage1Status.APPROVED,
        )
        current = await _make_statement(
            db,
            user_id,
            file_hash="hash_opening_current",
            account_id=account.id,
            opening_balance=Decimal("120.00"),
            closing_balance=Decimal("150.00"),
            period_start=date(2024, 2, 1),
            period_end=date(2024, 2, 29),
        )
        await _add_txn(
            db, current, amount=Decimal("50.00"), direction=TransactionDirection.IN, txn_date=date(2024, 2, 15)
        )

        validation = await validate_balance_chain(db, current.id)
        assert validation["opening_match"] is False
        assert validation["closing_match"] is True

        with pytest.raises(ValueError, match="Opening balance mismatch"):
            await approve_statement(db, current.id, user_id)


class TestRejectStatement:
    async def test_reject_sets_status(self, db, statement_with_transactions, user_id):
        """AC1.3.1 Reject statement and update status."""
        stmt = await reject_statement(db, statement_with_transactions.id, user_id, reason="Test rejection")

        assert stmt.stage1_status == Stage1Status.REJECTED
        assert stmt.status == BankStatementStatus.REJECTED
        assert stmt.validation_error == "Test rejection"


class TestEditAndApprove:
    async def test_edit_and_approve_is_unsupported(self, db, statement_with_transactions, user_id):
        """AC1.4.1 Editing parsed transactions is unsupported; reviewers must reject + re-parse."""
        with pytest.raises(ValueError, match="unsupported"):
            await edit_and_approve(
                db,
                statement_with_transactions.id,
                user_id,
                [],
            )


class TestSetOpeningBalance:
    async def test_set_opening_balance(self, db, statement_with_transactions, user_id):
        """AC1.5.1 Set manual opening balance for a statement."""
        stmt = await set_opening_balance(
            db,
            statement_with_transactions.id,
            user_id,
            Decimal("500.00"),
        )

        assert stmt.manual_opening_balance == Decimal("500.00")


class TestGetPendingStage1Review:
    async def test_returns_parsed_statements(self, db, user_id):
        """AC1.6.1 get_pending_stage1_review returns explicit pending or legacy parsed statements."""
        # Medium-confidence PARSED with no stage1_status -> should be returned
        stmt_medium = await _make_statement(
            db,
            user_id,
            file_hash="hash_pend",
            period_start=None,
            period_end=None,
            confidence_score=70,
        )
        # PARSED with stage1_status=PENDING_REVIEW -> should be returned
        stmt_review = await _make_statement(
            db,
            user_id,
            file_hash="hash_review",
            period_start=None,
            period_end=None,
            stage1_status=Stage1Status.PENDING_REVIEW,
            confidence_score=90,
        )
        # Legacy high-confidence PARSED with no stage1_status should remain reviewable.
        stmt_high_legacy = await _make_statement(
            db,
            user_id,
            file_hash="hash_high",
            period_start=None,
            period_end=None,
            confidence_score=90,
        )
        # APPROVED -> should NOT be returned
        stmt_approved = await _make_statement(
            db,
            user_id,
            file_hash="hash_approved",
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("0.00"),
            status=BankStatementStatus.APPROVED,
            stage1_status=Stage1Status.APPROVED,
        )

        result = await get_pending_stage1_review(db, user_id)
        ids = {s.id for s in result}
        assert stmt_medium.id in ids
        assert stmt_review.id in ids
        assert stmt_high_legacy.id in ids
        assert stmt_approved.id not in ids

    async def test_returns_empty_when_none_pending(self, db, user_id):
        """AC-extraction.stage1-review.1: AC1.6.2 get_pending_stage1_review returns empty when no pending statements."""
        result = await get_pending_stage1_review(db, user_id)
        assert result == []


class TestValidateBalanceChainEdgeCases:
    async def test_statement_not_found_raises(self, db):
        """AC16.3.1 validate_balance_chain raises ValueError when statement not found."""
        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="Statement not found"):
            await validate_balance_chain(db, non_existent_id)

    async def test_opening_balance_from_statement_when_no_manual_no_prev(self, db, user_id):
        """AC16.3.2 _get_opening_balance falls back to opening_balance when no prev statement."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_no_prev",
            opening_balance=Decimal("500.00"),
            closing_balance=Decimal("700.00"),
            period_start=date(2024, 3, 1),
            period_end=date(2024, 3, 31),
        )
        await _add_txn(
            db, stmt, amount=Decimal("200.00"), direction=TransactionDirection.IN, txn_date=date(2024, 3, 15)
        )

        result = await validate_balance_chain(db, stmt.id)
        # No prev statement, falls back to opening_balance
        assert result["opening_balance"] == "500.00"
        assert result["closing_match"] is True

    async def test_opening_balance_from_prev_statement(self, db, user_id):
        """AC16.3.3 _get_opening_balance uses prev statement closing_balance when available."""
        await _make_statement(
            db,
            user_id,
            file_hash="hash_prev_old",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1200.00"),
            status=BankStatementStatus.APPROVED,
        )
        curr_stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_curr_new",
            opening_balance=Decimal("999.00"),
            closing_balance=Decimal("1350.00"),
            period_start=date(2024, 2, 1),
            period_end=date(2024, 2, 29),
        )
        await _add_txn(
            db,
            curr_stmt,
            amount=Decimal("150.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 2, 15),
            description="Transfer",
        )

        result = await validate_balance_chain(db, curr_stmt.id)
        # Opening balance comes from prev stmt closing_balance (1200.00)
        assert result["opening_balance"] == "1200.00"
        assert result["calculated_closing"] == "1350.00"
        assert result["closing_match"] is True

    async def test_get_statement_for_update_wrong_user_raises(self, db, user_id, statement_with_transactions):
        """AC16.3.6 AC16.22.6: pending_review mutations enforce user_id ownership."""
        wrong_user_id = uuid4()
        with pytest.raises(ValueError, match="Statement not found or access denied"):
            await approve_statement(db, statement_with_transactions.id, wrong_user_id)


class TestRejectStatementEdgeCases:
    async def test_reject_without_reason(self, db, statement_with_transactions, user_id):
        """AC16.3.4 reject_statement without reason does not set validation_error."""
        stmt = await reject_statement(db, statement_with_transactions.id, user_id)

        assert stmt.stage1_status == Stage1Status.REJECTED
        assert stmt.status == BankStatementStatus.REJECTED
        assert stmt.validation_error is None


class TestEditAndApproveEdgeCases:
    async def test_edit_and_approve_rejects_field_edits(self, db, user_id):
        """AC16.3.5 edit_and_approve is unsupported even when edits target real txn fields."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_edit_ok",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.00"),
        )
        txn = await _add_txn(
            db, stmt, amount=Decimal("50.00"), direction=TransactionDirection.IN, description="Old desc"
        )
        edits = [
            {
                "txn_id": str(txn.id),
                "amount": "100.00",
                "description": "Updated Deposit",
                "direction": "IN",
            }
        ]
        with pytest.raises(ValueError, match="unsupported"):
            await edit_and_approve(db, stmt.id, user_id, edits)

    async def test_edit_and_approve_unsupported_with_empty_edits(self, db, user_id):
        """AC16.3.5 edit_and_approve raises unsupported regardless of balance validity."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_edit_fail",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("5000.00"),
        )
        await _add_txn(db, stmt, amount=Decimal("10.00"), direction=TransactionDirection.IN, description="Small")

        with pytest.raises(ValueError, match="unsupported"):
            await edit_and_approve(db, stmt.id, user_id, [])


class TestValidateBalanceChainAdditionalBranches:
    async def test_no_period_start_and_null_opening_falls_back_to_zero(self, db, user_id):
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_no_period_start",
            opening_balance=None,
            closing_balance=Decimal("25.00"),
            period_start=None,
            period_end=date(2024, 3, 31),
        )
        await _add_txn(db, stmt, amount=Decimal("25.00"), direction=TransactionDirection.IN, txn_date=date(2024, 3, 15))

        result = await validate_balance_chain(db, stmt.id)
        assert result["opening_balance"] == "0"
        assert result["calculated_closing"] == "25.00"
        assert result["closing_match"] is True

    async def test_opening_balance_uses_matching_account_only(self, db, user_id):
        matching_account_id = uuid4()
        other_account_id = uuid4()

        db.add_all(
            [
                Account(
                    id=matching_account_id,
                    user_id=user_id,
                    name="Main Account",
                    type=AccountType.ASSET,
                    currency="USD",
                ),
                Account(
                    id=other_account_id,
                    user_id=user_id,
                    name="Other Account",
                    type=AccountType.ASSET,
                    currency="USD",
                ),
            ]
        )
        await db.flush()

        await _make_statement(
            db,
            user_id,
            file_hash="hash_other_account",
            account_id=other_account_id,
            opening_balance=Decimal("10.00"),
            closing_balance=Decimal("2000.00"),
            status=BankStatementStatus.APPROVED,
        )
        current = await _make_statement(
            db,
            user_id,
            file_hash="hash_current_account",
            account_id=matching_account_id,
            opening_balance=Decimal("500.00"),
            closing_balance=Decimal("550.00"),
            period_start=date(2024, 2, 1),
            period_end=date(2024, 2, 29),
        )
        await _add_txn(
            db, current, amount=Decimal("50.00"), direction=TransactionDirection.IN, txn_date=date(2024, 2, 10)
        )

        result = await validate_balance_chain(db, current.id)
        assert result["opening_balance"] == "500.00"
        assert result["closing_match"] is True


class TestEditAndApproveSelectiveFields:
    async def test_edit_and_approve_unsupported_for_selective_edits(self, db, user_id):
        """edit_and_approve is unsupported even for partial field edits."""
        stmt = await _make_statement(
            db,
            user_id,
            file_hash="hash_selective",
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("900.00"),
        )
        txn = await _add_txn(
            db,
            stmt,
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 7),
            description="Original",
        )

        with pytest.raises(ValueError, match="unsupported"):
            await edit_and_approve(
                db,
                stmt.id,
                user_id,
                [{"txn_id": str(txn.id), "txn_date": date(2024, 1, 9), "reference": "R-9"}],
            )
