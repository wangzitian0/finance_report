"""Brokerage import error contract (#2649).

A parsed positions CSV with no as-of date made ``POST /statements/{id}/brokerage/import``
return HTTP 500 with ``request_id: null`` on staging v0.2.27. These tests use the AAA/BBB
rows of ``test_brokerage_csv_routing.py`` and a client that returns a 500 response
instead of raising, as uvicorn does in production.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy import func, select

from src.audit.money import Currency, InvalidCurrencyError
from src.config import settings
from src.extraction import BankStatementStatus, parse_brokerage_csv_payload, parse_brokerage_positions
from src.extraction.extension.service import ExtractionService
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

        log_warning = MagicMock()
        log_exception = MagicMock()
        monkeypatch.setattr(statements_router.logger, "warning", log_warning)
        monkeypatch.setattr(statements_router.logger, "exception", log_exception)
        response = await app_client.post(
            f"/statements/{statement_id}/brokerage/import",
            headers={"X-Request-ID": sent_request_id},
        )
    StorageService._checked_buckets.clear()

    assert response.status_code == 422, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id="brokerage_snapshot_date_missing")
    detail = response.json()["detail"]
    assert "does not state an as-of date for 2 of 2 positions" in detail
    assert "Upload the broker statement PDF" in detail
    assert await _atomic_position_count(db, user_id) == 0
    # A rejected source is a warning without a traceback, not an error-level failure.
    failed_events = [call for call in log_warning.call_args_list if call.args[0] == "statement.brokerage_import.failed"]
    assert len(failed_events) == 1
    assert failed_events[0].kwargs["error_type"] == "BrokerageImportRejectedError"
    assert failed_events[0].kwargs["request_id"] == sent_request_id
    assert log_exception.call_args_list == []


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
    import_calls: list[str] = []
    if case == "import_fails_unexpectedly":

        async def fail_import(*_args, **_kwargs):
            import_calls.append(case)
            raise RuntimeError("issue 2649 unexpected import failure")

        monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", fail_import)

    # The outer task holds another id, as after an earlier request in the same task. The
    # response must still carry the id of this request.
    structlog.contextvars.bind_contextvars(request_id="stale-outer-request-id")
    try:
        if case == "rate_limited":
            with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
                response = await app_client.post(path, headers={"X-Request-ID": sent_request_id})
        else:
            response = await app_client.post(path, headers={"X-Request-ID": sent_request_id})
    finally:
        structlog.contextvars.unbind_contextvars("request_id")

    assert response.status_code == expected_status, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=expected_error_id)
    # The 500 must come from the failing import, not from an earlier step.
    assert import_calls == (["import_fails_unexpectedly"] if case == "import_fails_unexpectedly" else [])


def _payload(period_end: str = "2026-01-31", **position_overrides: str) -> dict:
    position = {"symbol": "AAA", "quantity": "10", "market_value": "1000.00", "currency": "USD"}
    return {
        "institution": "Interactive Brokers",
        "statement": {"period_end": period_end, "currency": "USD"},
        "positions": [{**position, **position_overrides}],
    }


_OUT_OF_RANGE = "brokerage_position_out_of_range"


def _broker_payload(institution: str, **rows: list[dict[str, str]]) -> dict:
    """A dated payload for the broker-specific parsers (Futu valuation, Moomoo rows)."""
    return {"institution": institution, "statement": {"period_end": "2026-01-31", "currency": "SGD"}, **rows}


def _futu_valuation(amount: str) -> dict[str, str]:
    return {"date": "2026-01-31", "description": "Stock and options valuation", "amount": amount}


def _margin_buy(fill_qty: str, fill_amount: str) -> dict[str, str]:
    return {"Side": "BUY", "Symbol": "AAA", "Fill Qty": fill_qty, "Fill Amount": fill_amount, "Currency": "USD"}


def _money_market(amount: str) -> dict[str, str]:
    return {"date": "2026-01-31", "description": "Fullerton SGD Money Market Fund", "amount": amount}


def _subscription(value: str) -> dict[str, str]:
    return {"raw_text": f"Subscription REF1 Fullerton Fund SGD 2026/01/31 Settled 1.00 10 {value}"}


_UNSTORABLE_CASES = [
    ("month_13", _payload(period_end="2026-13"), "brokerage_snapshot_date_missing", "as-of date"),
    ("quantity_too_large", _payload(quantity="1000000000000"), _OUT_OF_RANGE, "the quantity 1000000000000 is out"),
    (
        "quantity_rounds_over_column",
        _payload(quantity="999999999999.9999995"),
        _OUT_OF_RANGE,
        "the quantity 999999999999.9999995 is out of range",
    ),
    ("quantity_nan", _payload(quantity="NaN"), _OUT_OF_RANGE, "Position 'AAA': the quantity 'NaN' is not a number."),
    (
        "market_value_above_column",
        _payload(market_value="10000000000000000"),
        _OUT_OF_RANGE,
        "the market_value 10000000000000000.00 is out of range",
    ),
    ("market_value_too_many_digits", _payload(market_value="1e40"), _OUT_OF_RANGE, "the market value 1E+40 is out"),
    (
        "market_value_infinity",
        _payload(market_value="Infinity"),
        _OUT_OF_RANGE,
        "Position 'AAA': the market_value 'Infinity' is not a number.",
    ),
    (
        "market_value_nan",
        _payload(market_value="NaN"),
        _OUT_OF_RANGE,
        "Position 'AAA': the market_value 'NaN' is not a number.",
    ),
    (
        "identifier_too_long",
        _payload(symbol="A" * 101),
        _OUT_OF_RANGE,
        "the asset_identifier has 101 characters. The limit is 100.",
    ),
    ("identifier_with_nul", _payload(symbol="AA\x00A"), _OUT_OF_RANGE, "the asset_identifier contains a NUL"),
    ("currency_too_long", _payload(currency="USDT"), _OUT_OF_RANGE, "the currency has 4 characters. The limit is 3."),
    (
        "currency_not_iso",
        _payload(currency="ABC"),
        _OUT_OF_RANGE,
        "the currency 'ABC' is not an ISO-4217 code. The app converts and prices only ISO-4217 currencies",
    ),
    (
        "currency_cnh",
        _payload(currency="CNH"),
        _OUT_OF_RANGE,
        "the currency 'CNH' (the offshore renminbi) is not an ISO-4217 code. The app converts and prices only "
        "ISO-4217 currencies, and it has no FX rate for this code. Restate the amounts in an ISO-4217 currency "
        "(for example CNY)",
    ),
    (
        "futu_valuation_too_many_digits",
        _broker_payload("Futu", events=[_futu_valuation("1e40")]),
        _OUT_OF_RANGE,
        "'FUTU_STOCK_AND_OPTIONS': the market value 1E+40 is out",
    ),
    (
        "futu_valuation_nan",
        _broker_payload("Futu", events=[_futu_valuation("NaN")]),
        _OUT_OF_RANGE,
        "Position 'Stock and options valuation': the market_value 'NaN' is not a number.",
    ),
    (
        "moomoo_margin_fill_qty_nan",
        _broker_payload("Moomoo", margin_history_rows=[_margin_buy("NaN", "100.00")]),
        _OUT_OF_RANGE,
        "Position 'AAA': the quantity 'NaN' is not a number.",
    ),
    (
        "moomoo_margin_amount_too_many_digits",
        _broker_payload("Moomoo", margin_history_rows=[_margin_buy("1", "1e40")]),
        _OUT_OF_RANGE,
        "'AAA': the market value 1.000000000000000000000000000E+40 is out",
    ),
    (
        "moomoo_money_market_too_many_digits",
        _broker_payload("Moomoo", events=[_money_market("1e40")]),
        _OUT_OF_RANGE,
        "'Fullerton SGD Money Market Fund': the market value 1E+40 is out",
    ),
    (
        "moomoo_money_market_nan",
        _broker_payload("Moomoo", events=[_money_market("NaN")]),
        _OUT_OF_RANGE,
        "Position 'Fullerton SGD Money Market Fund': the market_value 'NaN' is not a number.",
    ),
    (
        "moomoo_subscription_too_many_digits",
        _broker_payload("Moomoo", events=[_subscription("1" + "0" * 40)]),
        _OUT_OF_RANGE,
        "'Fullerton Fund': the market value 1" + "0" * 40 + " is out",
    ),
]


@pytest.mark.parametrize(
    ("case", "payload", "expected_error_id", "reason_text"),
    _UNSTORABLE_CASES,
    ids=[case[0] for case in _UNSTORABLE_CASES],
)
async def test_AC_portfolio_brokerage_import_12_unstorable_positions_return_422_reason(
    app_client, db, test_user, case, payload, expected_error_id, reason_text
):
    """AC-portfolio.brokerage-import.12: a position that the columns cannot store returns 422, never 500."""
    user_id = test_user.id
    sent_request_id = f"issue-2649-{case}-{uuid4()}"
    response = await app_client.post(
        "/portfolio/brokerage/import",
        json={"filename": "positions.json", "payload": payload},
        headers={"X-Request-ID": sent_request_id},
    )

    assert response.status_code == 422, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=expected_error_id)
    assert reason_text in response.json()["detail"]
    assert await _atomic_position_count(db, user_id) == 0


async def test_AC_portfolio_brokerage_import_12_quantity_is_stored_as_the_column_rounds(app_client, db, test_user):
    """AC-portfolio.brokerage-import.12: a quantity with more decimals than the column imports, rounded as Postgres does."""
    user_id = test_user.id
    payload = _payload(quantity="2.0000005")
    payload["positions"].append({"symbol": "BBB", "quantity": "1e-20000", "market_value": "5.00", "currency": "USD"})

    response = await app_client.post("/portfolio/brokerage/import", json={"filename": "p.json", "payload": payload})

    assert response.status_code == 200, response.text
    assert response.json()["created_atomic_positions"] == 2
    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    # Half away from zero at 6 places, as numeric(18,6) rounds; a tiny exponent stores as zero.
    assert {row.asset_identifier: row.quantity for row in rows} == {"AAA": Decimal("2.000001"), "BBB": Decimal("0")}


def test_AC_portfolio_brokerage_import_12_money_layer_reads_no_cnh():
    """AC-portfolio.brokerage-import.12: the money and FX layers read no CNH, so the import must not store it.

    On main a CNH position imported with 200, then ``GET /portfolio/holdings`` and the next import
    returned 500 with ``InvalidCurrencyError``. If ``Currency`` learns CNH, revisit the 422 above.
    """
    with pytest.raises(InvalidCurrencyError):
        Currency("CNH")


_SUBTOTAL_CSV = b"""Symbol,Quantity,Market Value,Currency
AAA,10,1000.00,USD
,nan,1100.00,USD
"""


async def _csv_upload_payload() -> dict:
    return await ExtractionService()._parse_csv_content(_SUBTOTAL_CSV, "Interactive Brokers")


@pytest.mark.parametrize(
    "case",
    ["csv_subtotal_row", "structured_row_without_symbol", "moomoo_margin_row_without_symbol", "moomoo_cash_event"],
)
async def test_AC_portfolio_brokerage_import_12_rows_that_are_not_positions_skip_before_amounts(case):
    """AC-portfolio.brokerage-import.12: a NaN amount in a row that is not a position does not reject the file."""
    if case == "csv_subtotal_row":
        # The upload path: a subtotal row with no symbol and ``nan`` was skipped on main.
        payload = await _csv_upload_payload()
        snapshots = parse_brokerage_positions(payload, filename="positions.csv")
    else:
        rows = {
            "structured_row_without_symbol": _payload(),
            "moomoo_margin_row_without_symbol": _broker_payload(
                "Moomoo", margin_history_rows=[_margin_buy("10", "1000.00")]
            ),
            "moomoo_cash_event": _broker_payload("Moomoo", events=[_money_market("1000.00")]),
        }[case]
        if case == "structured_row_without_symbol":
            rows["positions"].append({"quantity": "NaN", "market_value": "1.00", "currency": "USD"})
        elif case == "moomoo_margin_row_without_symbol":
            rows["margin_history_rows"].append({"Side": "BUY", "Fill Qty": "NaN", "Fill Amount": "1.00"})
        else:
            rows["events"].append({"date": "2026-01-31", "description": "Cash interest", "amount": "NaN"})
        snapshots = parse_brokerage_positions(rows)

    assert len(snapshots) == 1
    assert snapshots[0].market_value == Decimal("1000.00")


_CSV_REMEDY = "The CSV import does not read a date column. Upload the broker statement PDF"
_DOCUMENT_REMEDY = "The parser did not read a statement date from this document. Retry the parse"
_PAYLOAD_REMEDY = "Give the source a statement period_end or a snapshot_date for each position"


@pytest.mark.parametrize(
    ("filename", "remedy"),
    [
        ("positions.csv", _CSV_REMEDY),
        ("statement.pdf", _DOCUMENT_REMEDY),
        ("scan.JPG", _DOCUMENT_REMEDY),
        ("payload.json", _PAYLOAD_REMEDY),
        (None, _PAYLOAD_REMEDY),
    ],
)
async def test_AC_portfolio_brokerage_import_11_undated_remedy_follows_the_source_type(app_client, filename, remedy):
    """AC-portfolio.brokerage-import.11: the 422 remedy for a missing date matches the source type."""
    payload = parse_brokerage_csv_payload(_POSITIONS_HEADERS, _POSITIONS_ROWS, institution="Interactive Brokers")
    body = {"payload": payload} if filename is None else {"filename": filename, "payload": payload}

    response = await app_client.post("/portfolio/brokerage/import", json=body)

    assert response.status_code == 422, response.text
    assert response.json()["error_id"] == "brokerage_snapshot_date_missing"
    detail = response.json()["detail"]
    # Exactly one remedy, and it is the one for this source type.
    assert [text for text in (_CSV_REMEDY, _DOCUMENT_REMEDY, _PAYLOAD_REMEDY) if text in detail] == [remedy]
