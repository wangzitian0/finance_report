"""Brokerage import error contract (#2649).

A parsed positions CSV with no as-of date made ``POST /statements/{id}/brokerage/import``
return HTTP 500 with ``request_id: null`` on staging v0.2.27. These tests use the AAA/BBB
rows of ``test_brokerage_csv_routing.py`` and a client that returns a 500 response
instead of raising, as uvicorn does in production.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy import func, select

from src.config import settings
from src.extraction import BankStatementStatus, parse_brokerage_csv_payload
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.statement_summary import StatementSummary
from src.routers import statements as statements_router
from src.routers.statements import wait_for_parse_tasks
from src.runtime import StorageService
from tests.extraction.test_brokerage_csv_routing import BROKERAGE_POSITIONS_CSV
from tests.factories import StatementSummaryFactory

_POSITIONS_HEADERS = ["Symbol", "Quantity", "Current Price", "Market Value", "Currency", "P&L"]
_POSITIONS_ROWS = [
    {"Symbol": "AAA", "Quantity": "10", "Market Value": "1000.00", "Currency": "USD"},
    {"Symbol": "BBB", "Quantity": "5", "Market Value": "100.00", "Currency": "USD"},
]


@pytest_asyncio.fixture
async def app_client(client):
    """Authenticated client that returns the 500 response instead of raising the app error."""
    from src.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test", headers=dict(client.headers)) as app_http:
        yield app_http


def _assert_carries_request_id(response, *, sent_request_id: str, error_id: str) -> None:
    """The body and the header carry the request id that the caller sent."""
    body = response.json()
    assert body["error_id"] == error_id, body
    assert body["request_id"] == sent_request_id, body
    assert response.headers.get("X-Request-ID") == sent_request_id


async def _atomic_position_count(db, user_id: UUID) -> int:
    return await db.scalar(select(func.count()).select_from(AtomicPosition).where(AtomicPosition.user_id == user_id))


async def test_AC_portfolio_brokerage_import_11_dateless_positions_csv_returns_422_reason(
    app_client, db, test_user, monkeypatch
):
    """AC-portfolio.brokerage-import.11: the AAA/BBB positions CSV parses, then the import returns 422, not 500."""
    # The router rolls back the shared session, which expires ORM rows. Read the id first.
    user_id = test_user.id
    monkeypatch.setattr(settings, "s3_endpoint", None)
    monkeypatch.setattr(settings, "s3_access_key", "testing")
    monkeypatch.setattr(settings, "s3_secret_key", "testing")
    monkeypatch.setattr(settings, "s3_bucket", "issue-2649-positions-csv")
    StorageService._checked_buckets.clear()
    sent_request_id = f"issue-2649-{uuid4()}"
    with mock_aws():
        upload = await app_client.post(
            "/statements/upload",
            files={"file": ("positions.csv", BROKERAGE_POSITIONS_CSV, "text/csv")},
            data={"institution": "Interactive Brokers"},
        )
        assert upload.status_code == 202, upload.text
        statement_id = UUID(upload.json()["id"])
        await wait_for_parse_tasks()
        db.expire_all()
        statement = await db.get(StatementSummary, statement_id)
        # Precondition of the staging failure: the file parses, and the source states no date.
        assert statement is not None
        assert statement.status == BankStatementStatus.PARSED, statement.validation_error
        assert statement.period_end is None

        response = await app_client.post(
            f"/statements/{statement_id}/brokerage/import",
            headers={"X-Request-ID": sent_request_id},
        )
    StorageService._checked_buckets.clear()

    assert response.status_code == 422, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id="brokerage_snapshot_date_missing")
    detail = response.json()["detail"]
    assert "does not state an as-of date for 2 of 2 positions" in detail
    assert await _atomic_position_count(db, user_id) == 0


async def test_AC_portfolio_brokerage_import_11_dated_positions_import_and_undated_reject(app_client, db, test_user):
    """AC-portfolio.brokerage-import.11: the same rows import with a source date and return 422 without one."""
    user_id = test_user.id
    payload = parse_brokerage_csv_payload(_POSITIONS_HEADERS, _POSITIONS_ROWS, institution="Interactive Brokers")

    undated = await app_client.post(
        "/portfolio/brokerage/import", json={"filename": "positions.csv", "payload": payload}
    )
    assert undated.status_code == 422, undated.text
    assert undated.json()["error_id"] == "brokerage_snapshot_date_missing"
    assert undated.json()["request_id"]
    assert await _atomic_position_count(db, user_id) == 0

    dated_payload = {**payload, "statement": {"period_end": "2026-01-31", "currency": "USD"}}
    dated = await app_client.post(
        "/portfolio/brokerage/import", json={"filename": "positions.csv", "payload": dated_payload}
    )
    assert dated.status_code == 200, dated.text
    assert dated.json()["created_atomic_positions"] == 2
    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    assert {(row.asset_identifier, row.quantity, row.market_value) for row in rows} == {
        ("AAA", Decimal("10"), Decimal("1000.00")),
        ("BBB", Decimal("5"), Decimal("100.00")),
    }


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_error_id"),
    [
        ("statement_missing", 404, "not_found"),
        ("statement_id_malformed", 422, "unprocessable_entity"),
        ("statement_not_parsed", 400, "bad_request"),
        ("import_fails_unexpectedly", 500, "internal_error"),
        ("rate_limited", 429, "too_many_requests"),
    ],
)
async def test_AC_platform_27_4_brokerage_import_errors_carry_request_id(
    app_client, db, test_user, monkeypatch, case, expected_status, expected_error_id
):
    """AC-platform.27.4: each error response of the import endpoint carries the request id in body and header."""
    from src.main import api_rate_limiter

    sent_request_id = f"issue-2649-{case}-{uuid4()}"
    path = f"/statements/{uuid4()}/brokerage/import"
    if case == "statement_id_malformed":
        path = "/statements/not-a-uuid/brokerage/import"
    if case in {"statement_not_parsed", "import_fails_unexpectedly"}:
        status = BankStatementStatus.PARSING if case == "statement_not_parsed" else BankStatementStatus.PARSED
        statement = StatementSummaryFactory.build(
            user_id=test_user.id, status=status, institution="Interactive Brokers"
        )
        db.add(statement)
        await db.commit()
        path = f"/statements/{statement.id}/brokerage/import"
    if case == "import_fails_unexpectedly":

        async def fail_import(*_args, **_kwargs):
            raise RuntimeError("issue 2649 unexpected import failure")

        monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", fail_import)

    if case == "rate_limited":
        with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
            response = await app_client.post(path, headers={"X-Request-ID": sent_request_id})
    else:
        response = await app_client.post(path, headers={"X-Request-ID": sent_request_id})

    assert response.status_code == expected_status, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=expected_error_id)
