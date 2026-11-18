from __future__ import annotations

import inspect
from typing import get_type_hints
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import BankStatementStatus, DocumentStatus, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.extension.deduplication import dual_write_layer2
from src.extraction.extension.source_lifecycle import (
    RetireStatementCommand,
    SourceIdentityCommand,
    resolve_source_identity,
    retire_statement,
)
from src.extraction.extension.statement_validation import _raise_if_balance_chain_invalid, validate_balance_chain
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.reviewed_statement_envelope import ReviewedStatementEnvelope, StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.request_context import RequestContext
from src.routers import statements as statements_router
from tests.extraction._statement_run_helpers import (
    lifecycle_atomic as _atomic,
    lifecycle_document as _document,
    lifecycle_history_fixture as _history_fixture,
    lifecycle_identity as _identity,
    lifecycle_summary as _summary,
    verify_counterfactual_404_matrix,
    verify_failure_and_retry_convergence,
    verify_two_sessions_share_identity_and_result,
)


@pytest.mark.parametrize(
    ("file_hash", "declared", "txns", "check_key"),
    [
        (
            "per-currency-approval",
            [
                {"currency": "SGD", "opening": "0.00", "closing": "0.00"},
                {"currency": "USD", "opening": "0.00", "closing": "0.00"},
            ],
            [("SGD", TransactionDirection.IN, "10.00"), ("USD", TransactionDirection.OUT, "10.00")],
            "closing_match",
        ),
        (
            "legacy-scalar-multi-currency",
            None,
            [("SGD", TransactionDirection.IN, "10.00"), ("USD", TransactionDirection.OUT, "10.00")],
            "declared_balance",
        ),
        (
            "mismatched-primary-currency",
            [{"currency": "USD", "opening": "0.00", "closing": "0.00"}],
            [],
            "primary_only",
        ),
    ],
)
async def test_AC_extraction_source_lifecycle_1_approval_is_per_currency(
    db: AsyncSession, test_user, file_hash, declared, txns, check_key
) -> None:
    doc = _document(test_user.id, file_hash=file_hash)
    db.add(doc)
    await db.flush()
    stmt = _summary(test_user.id, file_hash=doc.file_hash, uploaded_document_id=doc.id)
    stmt.currency_balances = declared
    db.add(stmt)
    db.add_all([_atomic(test_user.id, doc.id, currency=c, direction=d, amount=a) for c, d, a in txns])
    await db.flush()
    result = await validate_balance_chain(db, stmt.id)
    assert result["balance_valid"] is False
    if check_key == "primary_only":
        assert next(r for r in result["per_currency"] if r["currency"] == "SGD")["declared_balance"] is False
    else:
        assert {r["currency"] for r in result["per_currency"]} == {"SGD", "USD"} and all(
            r[check_key] is False for r in result["per_currency"]
        )
    with pytest.raises(ValueError, match="currency"):
        _raise_if_balance_chain_invalid(result)


async def test_AC_extraction_source_lifecycle_2_two_sessions_share_source_identity(
    db: AsyncSession, db_engine, test_user
) -> None:
    await verify_two_sessions_share_identity_and_result(db, db_engine, test_user)


async def test_AC_extraction_source_lifecycle_3_conflict_preserves_outer_session(db_engine, test_user) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    command = _identity(test_user.id, file_hash="recoverable-source-conflict")
    async with maker() as winner_session:
        winner, created = await resolve_source_identity(winner_session, command)
        assert created is True
        await winner_session.commit()
    async with maker() as loser_session:
        observed, created = await resolve_source_identity(loser_session, command)
        assert created is False and observed.id == winner.id
        summary = _summary(test_user.id, file_hash="outer-session-still-usable")
        loser_session.add(summary)
        await loser_session.commit()
        assert summary.id is not None


async def test_AC_extraction_source_lifecycle_4_retire_preserves_history(db: AsyncSession, test_user) -> None:
    statement, document = await _history_fixture(db, test_user.id)
    before = {
        m: await db.scalar(select(func.count()).select_from(m))
        for m in (StatementExtractionResultRecord, ReviewedStatementEnvelope, AtomicTransaction, UploadedDocument)
    }
    retired = await retire_statement(
        db, RetireStatementCommand(statement_id=statement.id, user_id=test_user.id), base_currency="SGD"
    )
    repeated = await retire_statement(
        db, RetireStatementCommand(statement_id=statement.id, user_id=test_user.id), base_currency="SGD"
    )
    await db.commit()
    await db.refresh(document)
    assert (retired.id, retired.status, document.status) == (
        repeated.id,
        BankStatementStatus.RETIRED,
        DocumentStatus.RETIRED,
    ) and retired.id == statement.id
    assert {m: await db.scalar(select(func.count()).select_from(m)) for m in before} == before


async def test_AC_extraction_source_lifecycle_5_retire_does_not_delete_storage(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement, _ = await _history_fixture(db, test_user.id)
    await db.commit()
    monkeypatch.setattr(
        statements_router, "StorageService", lambda: (_ for _ in ()).throw(RuntimeError("object storage unavailable"))
    )
    await statements_router.delete_statement(statement.id, RequestContext(db, test_user.id))
    assert (await db.get(StatementSummary, statement.id)).status is BankStatementStatus.RETIRED


async def test_AC_extraction_source_lifecycle_6_failure_and_retry_converge(
    db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await verify_failure_and_retry_convergence(db, db_engine, test_user, monkeypatch)


def test_AC_extraction_source_lifecycle_7_boundary_is_typed() -> None:
    id_hints, ret_hints = get_type_hints(SourceIdentityCommand), get_type_hints(RetireStatementCommand)
    assert (id_hints["user_id"], id_hints["document_type"], ret_hints["statement_id"], ret_hints["user_id"]) == (
        UUID,
        DocumentType,
        UUID,
        UUID,
    )
    ann = str(inspect.signature(dual_write_layer2).parameters["transactions"].annotation)
    assert "ExtractedTransactionRow" in ann and "dict" not in ann


def test_AC_extraction_source_lifecycle_8_ordinary_api_has_no_purge_path() -> None:
    source = inspect.getsource(statements_router.delete_statement)
    assert (
        "retire_statement(" in source
        and "delete_object" not in source
        and "db.delete" not in source
        and "purge" not in source.casefold()
    )


async def test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked(db: AsyncSession, test_user) -> None:
    await verify_counterfactual_404_matrix(db, test_user)
