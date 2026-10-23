"""A failed brokerage import stays visible on the statement until a retry succeeds (#2648).

Before #2648 a failed import left no trace: the statement stayed ``parsed`` with its old note, so
the upload list showed "Ready to review" and "Review & Approve" for a file whose import failed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.extraction import (
    BROKERAGE_IMPORT_FAILED_MESSAGE,
    BROKERAGE_IMPORT_FAILED_NOTICE,
    BankStatementStatus,
    BrokerageImportRejectedError,
    StatementSummary,
)
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import build_statement

PARSE_NOTE = "Source CSV does not declare opening and closing balances"


def _import_result() -> SimpleNamespace:
    return SimpleNamespace(
        broker="Interactive Brokers",
        parsed_positions=2,
        created_atomic_positions=2,
        existing_atomic_positions=0,
        reconcile_created=2,
        reconcile_updated=0,
        reconcile_disposed=0,
        skipped=0,
        account_id=None,
    )


async def _listed(db, user_id) -> dict:
    response = await statements_router.list_statements(db=db, user_id=user_id)
    return {item.id: item for item in response.items}


async def test_AC_extraction_2648_1_failed_brokerage_import_is_recorded_and_a_retry_clears_it(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: a brokerage import that raises keeps the statement ``parsed``, records
    ``BROKERAGE_IMPORT_FAILED_MESSAGE`` and lists the statement with ``brokerage_import_failed=True``.
    A later import that succeeds clears both. The original import error still reaches the caller."""
    user_id = test_user.id  # the router commits, which expires the fixture user
    statement = build_statement(user_id, "ibkr-positions-2648", 20)
    statement.institution = "Interactive Brokers"
    statement.validation_error = PARSE_NOTE
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    async def failing_import(*_args, **_kwargs):
        raise RuntimeError("positions payload has no ticker column")

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", failing_import)
    with pytest.raises(RuntimeError, match="no ticker column"):
        await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)

    failed = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert failed is not None
    assert failed.status is BankStatementStatus.PARSED
    assert failed.validation_error == BROKERAGE_IMPORT_FAILED_MESSAGE
    listed = (await _listed(db, user_id))[statement_id]
    assert listed.brokerage_import_failed is True
    assert listed.validation_error == BROKERAGE_IMPORT_FAILED_MESSAGE

    async def working_import(*_args, **_kwargs):
        return _import_result()

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", working_import)
    response = await statements_router.import_brokerage_statement_positions(
        statement_id=statement_id, db=db, user_id=user_id
    )
    assert response.created_atomic_positions == 2

    cleared = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert cleared is not None
    assert cleared.validation_error is None
    listed = (await _listed(db, user_id))[statement_id]
    assert listed.brokerage_import_failed is False


async def test_AC_extraction_2648_1_a_successful_import_keeps_an_unrelated_note(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: a successful import clears only the failed-import note."""
    user_id = test_user.id  # the router commits, which expires the fixture user
    statement = build_statement(user_id, "ibkr-positions-2648-note", 95)
    statement.validation_error = PARSE_NOTE
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    async def working_import(*_args, **_kwargs):
        return _import_result()

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", working_import)
    await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)

    kept = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert kept is not None
    assert kept.validation_error == PARSE_NOTE
    assert (await _listed(db, user_id))[statement_id].brokerage_import_failed is False


async def test_AC_extraction_2648_1_a_rejected_import_records_its_specific_reason(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: a source that the import rejects (HTTP 422, #2649) records its own
    reason, so the upload list shows the remedy. The generic message is only for a missing reason."""
    user_id = test_user.id  # the router commits, which expires the fixture user
    statement = build_statement(user_id, "ibkr-positions-2648-422", 20)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    reason = (
        "The positions source does not state an as-of date for 2 of 2 positions. "
        "The import needs the date that the source states."
    )

    async def rejecting_import(*_args, **_kwargs):
        raise BrokerageImportRejectedError("brokerage_snapshot_date_missing", reason)

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", rejecting_import)
    with pytest.raises(BrokerageImportRejectedError):
        await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)

    rejected = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert rejected is not None
    assert rejected.validation_error == f"{BROKERAGE_IMPORT_FAILED_NOTICE} {reason}"
    listed = (await _listed(db, user_id))[statement_id]
    assert listed.brokerage_import_failed is True
    assert listed.validation_error == f"{BROKERAGE_IMPORT_FAILED_NOTICE} {reason}"
