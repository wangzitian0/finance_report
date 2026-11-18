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
from src.extraction import BankStatementStatus, parse_brokerage_csv_payload, parse_brokerage_positions, wait_for_parse_tasks
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.statement_summary import StatementSummary
from src.routers import portfolio as portfolio_router
from src.runtime import StorageService
from tests.extraction.test_brokerage_csv_routing import BROKERAGE_POSITIONS_CSV
from tests.factories import StatementSummaryFactory

_POSITIONS_HEADERS = ["Symbol", "Quantity", "Current Price", "Market Value", "Currency", "P&L"]
_POSITIONS_ROWS = [{"Symbol": "AAA", "Quantity": "10", "Market Value": "1000.00", "Currency": "USD"}, {"Symbol": "BBB", "Quantity": "5", "Market Value": "100.00", "Currency": "USD"}]
_OUT_OF_RANGE = "brokerage_position_out_of_range"


def _payload(period_end: str = "2026-01-31", **overrides: str) -> dict:
    return {"institution": "Interactive Brokers", "statement": {"period_end": period_end, "currency": "USD"}, "positions": [{"symbol": "AAA", "quantity": "10", "market_value": "1000.00", "currency": "USD", **overrides}]}


def _broker_payload(institution: str, **rows) -> dict:
    return {"institution": institution, "statement": {"period_end": "2026-01-31", "currency": "SGD"}, **rows}


def _assert_carries_request_id(response, *, sent_request_id: str, error_id: str) -> None:
    body = response.json()
    assert (body["error_id"], body["request_id"], response.headers.get("X-Request-ID")) == (error_id, sent_request_id, sent_request_id), body


async def _atomic_position_count(db, user_id: UUID) -> int:
    return await db.scalar(select(func.count()).select_from(AtomicPosition).where(AtomicPosition.user_id == user_id))


@pytest_asyncio.fixture
async def app_client(client):
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test", headers=dict(client.headers)) as app_http:
        yield app_http


async def test_AC_portfolio_brokerage_import_11_dateless_positions_csv_returns_422_reason(app_client, db, test_user, monkeypatch):
    user_id = test_user.id
    for k, v in (("s3_endpoint", None), ("s3_access_key", "testing"), ("s3_secret_key", "testing"), ("s3_bucket", "issue-2649-positions-csv")):
        monkeypatch.setattr(settings, k, v)
    StorageService._checked_buckets.clear()
    sent_request_id = f"issue-2649-{uuid4()}"
    with mock_aws():
        upload = await app_client.post("/statements", files={"file": ("positions.csv", BROKERAGE_POSITIONS_CSV, "text/csv")}, data={"institution": "Interactive Brokers"})
        assert upload.status_code == 202, upload.text
        statement_id = UUID(upload.json()["id"])
        await wait_for_parse_tasks()
        db.expire_all()
        statement = await db.get(StatementSummary, statement_id)
        log_warning, log_exception = MagicMock(), MagicMock()
        monkeypatch.setattr(portfolio_router.logger, "warning", log_warning)
        monkeypatch.setattr(portfolio_router.logger, "exception", log_exception)
        response = await app_client.post("/portfolio/brokerage-imports", json={"statement_id": str(statement_id)}, headers={"X-Request-ID": sent_request_id})
    StorageService._checked_buckets.clear()
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id="brokerage_snapshot_date_missing")
    failed = [c for c in log_warning.call_args_list if c.args[0] == "statement.brokerage_import.failed"]
    assert (
        statement.status,
        statement.period_end,
        response.status_code,
        "does not state an as-of date for 2 of 2 positions" in response.json()["detail"],
        "Upload the broker statement PDF" in response.json()["detail"],
        await _atomic_position_count(db, user_id),
        len(failed),
        failed[0].kwargs["error_type"],
        failed[0].kwargs["request_id"],
        log_exception.call_args_list,
    ) == (BankStatementStatus.PARSED, None, 422, True, True, 0, 1, "BrokerageImportRejectedError", sent_request_id, [])


async def test_AC_portfolio_brokerage_import_11_dated_positions_import_and_undated_reject(app_client, db, test_user):
    payload = parse_brokerage_csv_payload(_POSITIONS_HEADERS, _POSITIONS_ROWS, institution="Interactive Brokers")
    undated = await app_client.post("/portfolio/brokerage-imports", json={"filename": "positions.csv", "payload": payload})
    assert (undated.status_code, undated.json()["error_id"], bool(undated.json()["request_id"]), await _atomic_position_count(db, test_user.id)) == (422, "brokerage_snapshot_date_missing", True, 0)
    dated = await app_client.post("/portfolio/brokerage-imports", json={"filename": "positions.csv", "payload": {**payload, "statement": {"period_end": "2026-01-31", "currency": "USD"}}})
    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert (dated.status_code, dated.json()["created_atomic_positions"], {(r.asset_identifier, r.quantity, r.market_value) for r in rows}) == (200, 2, {("AAA", Decimal("10"), Decimal("1000.00")), ("BBB", Decimal("5"), Decimal("100.00"))})


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_error_id"),
    [("statement_missing", 404, "not_found"), ("statement_id_malformed", 422, "unprocessable_entity"), ("statement_not_parsed", 400, "bad_request"), ("import_fails_unexpectedly", 500, "internal_error"), ("rate_limited", 429, "too_many_requests")],
)
async def test_AC_platform_27_4_brokerage_import_errors_carry_request_id(app_client, db, test_user, monkeypatch, case, expected_status, expected_error_id):
    from src.main import api_rate_limiter

    sent_request_id = f"issue-2649-{case}-{uuid4()}"
    body: dict[str, object] = {"statement_id": "not-a-uuid" if case == "statement_id_malformed" else str(uuid4())}
    if case in {"statement_not_parsed", "import_fails_unexpectedly"}:
        statement = StatementSummaryFactory.build(user_id=test_user.id, status=BankStatementStatus.PARSING if case == "statement_not_parsed" else BankStatementStatus.PARSED, institution="Interactive Brokers")
        db.add(statement)
        await db.commit()
        body = {"statement_id": str(statement.id)}
    import_calls: list[str] = []
    if case == "import_fails_unexpectedly":
        async def fail_import(*_args, **_kwargs):
            import_calls.append(case)
            raise RuntimeError("issue 2649 unexpected import failure")

        monkeypatch.setattr(portfolio_router._brokerage_import_service, "import_positions", fail_import)
    structlog.contextvars.bind_contextvars(request_id="stale-outer-request-id")
    try:
        if case == "rate_limited":
            with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
                response = await app_client.post("/portfolio/brokerage-imports", json=body, headers={"X-Request-ID": sent_request_id})
        else:
            response = await app_client.post("/portfolio/brokerage-imports", json=body, headers={"X-Request-ID": sent_request_id})
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    assert response.status_code == expected_status, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=expected_error_id)
    assert import_calls == (["import_fails_unexpectedly"] if case == "import_fails_unexpectedly" else [])


_UNSTORABLE_CASES = [
    ("month_13", _payload(period_end="2026-13"), "brokerage_snapshot_date_missing", "as-of date"),
    ("quantity_too_large", _payload(quantity="1000000000000"), _OUT_OF_RANGE, "the quantity 1000000000000 is out"),
    ("quantity_rounds_over_column", _payload(quantity="999999999999.9999995"), _OUT_OF_RANGE, "the quantity 999999999999.9999995 is out of range"),
    ("quantity_nan", _payload(quantity="NaN"), _OUT_OF_RANGE, "Position 'AAA': the quantity 'NaN' is not a number."),
    ("market_value_above_column", _payload(market_value="10000000000000000"), _OUT_OF_RANGE, "the market_value 10000000000000000.00 is out of range"),
    ("market_value_too_many_digits", _payload(market_value="1e40"), _OUT_OF_RANGE, "the market value 1E+40 is out"),
    ("market_value_infinity", _payload(market_value="Infinity"), _OUT_OF_RANGE, "Position 'AAA': the market_value 'Infinity' is not a number."),
    ("market_value_nan", _payload(market_value="NaN"), _OUT_OF_RANGE, "Position 'AAA': the market_value 'NaN' is not a number."),
    ("identifier_too_long", _payload(symbol="A" * 101), _OUT_OF_RANGE, "the asset_identifier has 101 characters. The limit is 100."),
    ("identifier_with_nul", _payload(symbol="AA\x00A"), _OUT_OF_RANGE, "the asset_identifier contains a NUL"),
    ("currency_too_long", _payload(currency="USDT"), _OUT_OF_RANGE, "the currency has 4 characters. The limit is 3."),
    ("currency_not_iso", _payload(currency="ABC"), _OUT_OF_RANGE, "the currency 'ABC' is not an ISO-4217 code. The app converts and prices only ISO-4217 currencies"),
    ("currency_cnh", _payload(currency="CNH"), _OUT_OF_RANGE, "the currency 'CNH' (the offshore renminbi) is not an ISO-4217 code. The app converts and prices only ISO-4217 currencies, and it has no FX rate for this code. Restate the amounts in an ISO-4217 currency (for example CNY)"),
    ("futu_valuation_too_many_digits", _broker_payload("Futu", events=[{"date": "2026-01-31", "description": "Stock and options valuation", "amount": "1e40"}]), _OUT_OF_RANGE, "'FUTU_STOCK_AND_OPTIONS': the market value 1E+40 is out"),
    ("futu_valuation_nan", _broker_payload("Futu", events=[{"date": "2026-01-31", "description": "Stock and options valuation", "amount": "NaN"}]), _OUT_OF_RANGE, "Position 'Stock and options valuation': the market_value 'NaN' is not a number."),
    ("moomoo_margin_fill_qty_nan", _broker_payload("Moomoo", margin_history_rows=[{"Side": "BUY", "Symbol": "AAA", "Fill Qty": "NaN", "Fill Amount": "100.00", "Currency": "USD"}]), _OUT_OF_RANGE, "Position 'AAA': the quantity 'NaN' is not a number."),
    ("moomoo_margin_amount_too_many_digits", _broker_payload("Moomoo", margin_history_rows=[{"Side": "BUY", "Symbol": "AAA", "Fill Qty": "1", "Fill Amount": "1e40", "Currency": "USD"}]), _OUT_OF_RANGE, "'AAA': the market value 1.000000000000000000000000000E+40 is out"),
    ("moomoo_money_market_too_many_digits", _broker_payload("Moomoo", events=[{"date": "2026-01-31", "description": "Fullerton SGD Money Market Fund", "amount": "1e40"}]), _OUT_OF_RANGE, "'Fullerton SGD Money Market Fund': the market value 1E+40 is out"),
    ("moomoo_money_market_nan", _broker_payload("Moomoo", events=[{"date": "2026-01-31", "description": "Fullerton SGD Money Market Fund", "amount": "NaN"}]), _OUT_OF_RANGE, "Position 'Fullerton SGD Money Market Fund': the market_value 'NaN' is not a number."),
    ("moomoo_subscription_too_many_digits", _broker_payload("Moomoo", events=[{"raw_text": f"Subscription REF1 Fullerton Fund SGD 2026/01/31 Settled 1.00 10 {'1' + '0' * 40}"}]), _OUT_OF_RANGE, "'Fullerton Fund': the market value 1" + "0" * 40 + " is out"),
]


@pytest.mark.parametrize(("case", "payload", "expected_error_id", "reason_text"), _UNSTORABLE_CASES, ids=[c[0] for c in _UNSTORABLE_CASES])
async def test_AC_portfolio_brokerage_import_12_unstorable_positions_return_422_reason(app_client, db, test_user, case, payload, expected_error_id, reason_text):
    sent_request_id = f"issue-2649-{case}-{uuid4()}"
    response = await app_client.post("/portfolio/brokerage-imports", json={"filename": "positions.json", "payload": payload}, headers={"X-Request-ID": sent_request_id})
    assert response.status_code == 422, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=expected_error_id)
    assert (reason_text in response.json()["detail"], await _atomic_position_count(db, test_user.id)) == (True, 0)


async def test_AC_portfolio_brokerage_import_12_quantity_rounding_and_money_guard(app_client, db, test_user):
    with pytest.raises(InvalidCurrencyError):
        Currency("CNH")
    payload = _payload(quantity="2.0000005")
    payload["positions"].append({"symbol": "BBB", "quantity": "1e-20000", "market_value": "5.00", "currency": "USD"})
    response = await app_client.post("/portfolio/brokerage-imports", json={"filename": "p.json", "payload": payload})
    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert (response.status_code, response.json()["created_atomic_positions"], {r.asset_identifier: r.quantity for r in rows}) == (200, 2, {"AAA": Decimal("2.000001"), "BBB": Decimal("0")})


@pytest.mark.parametrize("case", ["csv_subtotal_row", "structured_row_without_symbol", "moomoo_margin_row_without_symbol", "moomoo_cash_event"])
async def test_AC_portfolio_brokerage_import_12_rows_that_are_not_positions_skip_before_amounts(case):
    if case == "csv_subtotal_row":
        payload = await ExtractionService()._parse_csv_content(b"Symbol,Quantity,Market Value,Currency\nAAA,10,1000.00,USD\n,nan,1100.00,USD\n", "Interactive Brokers")
    elif case == "structured_row_without_symbol":
        payload = _payload()
        payload["positions"].append({"quantity": "NaN", "market_value": "1.00", "currency": "USD"})
    elif case == "moomoo_margin_row_without_symbol":
        payload = _broker_payload("Moomoo", margin_history_rows=[{"Side": "BUY", "Symbol": "AAA", "Fill Qty": "10", "Fill Amount": "1000.00", "Currency": "USD"}, {"Side": "BUY", "Fill Qty": "NaN", "Fill Amount": "1.00"}])
    else:
        payload = _broker_payload("Moomoo", events=[{"date": "2026-01-31", "description": "Fullerton SGD Money Market Fund", "amount": "1000.00"}, {"date": "2026-01-31", "description": "Cash interest", "amount": "NaN"}])
    snapshots = parse_brokerage_positions(payload, filename="positions.csv" if case == "csv_subtotal_row" else None)
    assert (len(snapshots), snapshots[0].market_value) == (1, Decimal("1000.00"))


_CSV_REMEDY = "The CSV import does not read a date column. Upload the broker statement PDF"
_DOCUMENT_REMEDY = "The parser did not read a statement date from this document. Retry the parse"
_PAYLOAD_REMEDY = "Give the source a statement period_end or a snapshot_date for each position"


@pytest.mark.parametrize(("filename", "remedy"), [("positions.csv", _CSV_REMEDY), ("statement.pdf", _DOCUMENT_REMEDY), ("scan.JPG", _DOCUMENT_REMEDY), ("payload.json", _PAYLOAD_REMEDY), (None, _PAYLOAD_REMEDY)])
async def test_AC_portfolio_brokerage_import_11_undated_remedy_follows_the_source_type(app_client, filename, remedy):
    payload = parse_brokerage_csv_payload(_POSITIONS_HEADERS, _POSITIONS_ROWS, institution="Interactive Brokers")
    response = await app_client.post("/portfolio/brokerage-imports", json={"payload": payload} if filename is None else {"filename": filename, "payload": payload})
    detail = response.json()["detail"]
    assert (response.status_code, response.json()["error_id"], [t for t in (_CSV_REMEDY, _DOCUMENT_REMEDY, _PAYLOAD_REMEDY) if t in detail]) == (422, "brokerage_snapshot_date_missing", [remedy])


@pytest.mark.parametrize(("source_document_id", "reason_text"), [("doc-\x00-id", "source_document_id contains a NUL character"), ("d" * 256, "source_document_id has 256 characters. The limit is 255.")])
async def test_AC_portfolio_brokerage_import_13_invalid_source_document_id_and_legacy_currency_return_422(app_client, db, test_user, source_document_id, reason_text):
    sent_request_id = f"issue-2661-{uuid4()}"
    response = await app_client.post("/portfolio/brokerage-imports", json={"filename": "positions.json", "payload": _payload(), "source_document_id": source_document_id}, headers={"X-Request-ID": sent_request_id})
    assert response.status_code == 422, response.text
    _assert_carries_request_id(response, sent_request_id=sent_request_id, error_id=_OUT_OF_RANGE)
    assert (reason_text in response.json()["detail"], await _atomic_position_count(db, test_user.id)) == (True, 0)
