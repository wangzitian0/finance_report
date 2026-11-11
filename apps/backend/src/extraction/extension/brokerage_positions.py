"""Brokerage statement position parsing and import."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, cast
from uuid import UUID

from sqlalchemy import Numeric, String, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import text_digest
from src.audit.money import Currency, InvalidCurrencyError, to_money
from src.extraction.extension._base import _tolerant_parse_date
from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.ledger import Account, AccountType
from src.platform import BaseAppException

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class PositionReconcileOutcome(Protocol):
    """Duck-typed reconcile summary matching ``portfolio``'s ``ReconcileResult``."""

    created: int
    updated: int
    disposed: int
    skipped: int


# L2 port wired at L4 startup (``main.py``) to avoid a ``portfolio`` <-> ``extraction`` cycle (#1675 D5c).
_position_reconciler: Callable[[AsyncSession, UUID], Awaitable[PositionReconcileOutcome]] | None = None


def register_position_reconciler(
    reconciler: Callable[[AsyncSession, UUID], Awaitable[PositionReconcileOutcome]],
) -> None:
    """Wire the managed-position reconciler."""
    global _position_reconciler
    _position_reconciler = reconciler


def _get_position_reconciler() -> Callable[[AsyncSession, UUID], Awaitable[PositionReconcileOutcome]]:
    if _position_reconciler is None:
        raise RuntimeError(
            "brokerage_positions.register_position_reconciler() was never called — "
            "main.py wires it at startup (#1675 D5c); a test exercising this path "
            "must call it too."
        )
    return _position_reconciler


@dataclass(frozen=True)
class BrokeragePositionSnapshot:
    """Brokerage position snapshot before persistence."""

    snapshot_date: date | None
    asset_identifier: str
    broker: str
    quantity: Decimal
    market_value: Decimal
    currency: str
    asset_type: AssetType | None = None
    sector: str | None = None
    geography: str | None = None


@dataclass(frozen=True)
class BrokerageImportResult:
    """Result of importing brokerage positions."""

    broker: str
    parsed_positions: int
    created_atomic_positions: int
    existing_atomic_positions: int
    reconcile_created: int
    reconcile_updated: int
    reconcile_disposed: int
    skipped: int
    account_id: UUID | None = None


BROKERAGE_SNAPSHOT_DATE_MISSING = "brokerage_snapshot_date_missing"
BROKERAGE_POSITION_OUT_OF_RANGE = "brokerage_position_out_of_range"


class BrokerageImportRejectedError(BaseAppException, ValueError):
    """HTTP 422 rejection when parsed source positions fail validation (#2649)."""

    def __init__(self, error_id: str, message: str) -> None:
        super().__init__(error_id=error_id, message=message, status_code=422)


_BROKER_ALIASES = (
    ("Interactive Brokers", ("interactive brokers", "ibkr", "ib llc")),
    ("Moomoo", ("moomoo", "futu sg")),
    ("Futu", ("futu", "富途")),
)

_MOOMOO_SUBSCRIPTION_RE = re.compile(
    r"Subscription\s+\S+\s+(?P<name>.+?)\s+(?P<currency>[A-Z]{3})\s+"
    r"\d{4}/\d{2}/\d{2}\s+\S+\s+(?P<price>[\d,.]+)\s+"
    r"(?P<quantity>[\d,.]+)\s+(?P<value>[\d,.]+)",
    re.IGNORECASE,
)


def _clean_decimal(value: Any, *, field: str = "amount", row: object | None = None) -> Decimal | None:
    """Parse an amount, return ``None`` for empty/non-numeric text, and reject NaN/Infinity (#2649)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        parsed = value
    else:
        text = str(value).strip().replace(",", "")
        if not text or text.upper() in {"N/A", "UNKNOWN", "NULL", "NONE"}:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
    if not parsed.is_finite():
        subject = f"Position {str(row).strip()[:40]!r}: the {field}" if row is not None else f"The {field}"
        raise BrokerageImportRejectedError(
            BROKERAGE_POSITION_OUT_OF_RANGE, f"{subject} {str(value)[:40]!r} is not a number."
        )
    return parsed


def _position_money(identifier: object, value: Decimal) -> Decimal:
    """Round a position market value to cents, or reject out-of-range precision (#2649)."""
    try:
        return to_money(value)
    except InvalidOperation as exc:
        raise BrokerageImportRejectedError(
            BROKERAGE_POSITION_OUT_OF_RANGE,
            f"Position {str(identifier).strip()[:40]!r}: the market value {value} is out of range.",
        ) from exc


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.upper() == "UNKNOWN":
        return None
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = (int(part) for part in text.split("-"))
        try:
            return date(year, month, monthrange(year, month)[1])
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", text):
        text = text.replace("/", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _coerce_date(value: Any) -> date | None:
    """Parse ISO, YYYY-MM, or common non-ISO date strings into a date (#2661)."""
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed
    if value is None:
        return None
    text = str(value).strip()
    return None if re.fullmatch(r"\d{4}-\d{2}", text) else _tolerant_parse_date(text)


def _statement_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return nested ``statement`` mapping or an empty dict."""
    statement = payload.get("statement")
    return statement if isinstance(statement, dict) else {}


def _statement_date(payload: dict[str, Any]) -> date | None:
    statement = _statement_dict(payload)
    for container in (payload, statement):
        for key in ("snapshot_date", "as_of_date", "period_end"):
            if parsed := _parse_date(container.get(key)):
                return parsed
    return None


def _payload_currency(payload: dict[str, Any], default: str = "USD") -> str:
    statement = _statement_dict(payload)
    return str(payload.get("currency") or statement.get("currency") or default).upper()


def _asset_type(value: Any) -> AssetType | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    aliases = {
        "fund": AssetType.MUTUAL_FUND,
        "money_market": AssetType.MUTUAL_FUND,
        "stock_and_options": AssetType.OTHER,
        "equity": AssetType.STOCK,
    }
    if text in aliases:
        return aliases[text]
    try:
        return AssetType(text)
    except ValueError:
        return None


def detect_broker(*, filename: str | None, institution: str | None, text: str | None) -> str:
    """Detect broker from filename, institution, or extracted text."""
    haystack = " ".join(part for part in (filename, institution, text) if part).lower()
    for broker, aliases in _BROKER_ALIASES:
        if any(alias in haystack for alias in aliases):
            return broker
    return "Unknown Broker"


def looks_like_brokerage_document(
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> bool:
    """Pre-extraction prompt routing check using filename and institution (#1139 AC-B1)."""
    return detect_broker(filename=filename, institution=institution, text=None) != "Unknown Broker"


def looks_like_brokerage_payload(
    payload: dict[str, Any] | None,
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> bool:
    """Return whether parsed extraction output should enter the brokerage import path."""
    if not isinstance(payload, dict):
        return False
    if payload.get("source_type") in {"bank_statement", "brokerage_statement"}:
        return payload["source_type"] == "brokerage_statement"
    if any(payload.get(key) for key in ("positions", "holdings", "securities")):
        return True
    statement = _statement_dict(payload)
    broker = detect_broker(
        filename=filename or str(payload.get("file") or ""),
        institution=institution or payload.get("institution") or statement.get("institution"),
        text=str(payload),
    )
    return broker != "Unknown Broker"


def _iter_structured_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for container in (payload, _statement_dict(payload)):
        for key in ("positions", "holdings", "securities"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _optional_str(value: Any) -> str | None:
    return str(value).strip() if value else None


def _parse_structured_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date | None
) -> list[BrokeragePositionSnapshot]:
    snapshots: list[BrokeragePositionSnapshot] = []
    default_currency = _payload_currency(payload)
    for item in _iter_structured_positions(payload):
        # Prefer ticker/symbol over free-text asset_identifier for market-data lookup (#1389).
        identifier = item.get("symbol") or item.get("ticker") or item.get("asset_identifier") or item.get("isin")
        if not identifier:
            continue
        quantity = _clean_decimal(
            item.get("quantity") or item.get("qty") or item.get("position"), field="quantity", row=identifier
        )
        market_value = _clean_decimal(
            item.get("market_value") or item.get("value") or item.get("marketValue"),
            field="market_value",
            row=identifier,
        )
        if quantity is None or market_value is None:
            continue
        snapshots.append(
            BrokeragePositionSnapshot(
                snapshot_date=_parse_date(item.get("snapshot_date") or item.get("as_of_date")) or snapshot_date,
                asset_identifier=str(identifier).strip(),
                broker=str(item.get("broker") or broker),
                quantity=quantity,
                market_value=_position_money(identifier, market_value),
                currency=str(item.get("currency") or default_currency).upper(),
                asset_type=_asset_type(item.get("asset_type") or item.get("asset_class")),
                sector=_optional_str(item.get("sector")),
                geography=_optional_str(item.get("geography")),
            )
        )
    return snapshots


def _parse_moomoo_subscription_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date | None
) -> list[BrokeragePositionSnapshot]:
    snapshots: list[BrokeragePositionSnapshot] = []
    for event in payload.get("events") or payload.get("transactions") or []:
        if not isinstance(event, dict):
            continue
        match = _MOOMOO_SUBSCRIPTION_RE.search(str(event.get("raw_text") or ""))
        if not match:
            if str(event.get("direction") or "").strip().upper() == "OUT":
                continue
            description = str(event.get("description") or "")
            if "Money Market Fund" not in description or any(
                token in description.lower() for token in _FUTU_NON_POSITION_EVENT_TOKENS
            ):
                continue
            amount = _clean_decimal(event.get("amount"), field="market_value", row=description)
            if amount is None or amount <= 0:
                continue
            snapshots.append(
                BrokeragePositionSnapshot(
                    snapshot_date=snapshot_date,
                    asset_identifier=description.strip(),
                    broker=broker,
                    quantity=Decimal("1"),
                    market_value=_position_money(description, amount),
                    currency=_payload_currency(payload),
                    asset_type=AssetType.MUTUAL_FUND,
                )
            )
            continue

        name = match.group("name")
        quantity = _clean_decimal(match.group("quantity"), field="quantity", row=name)
        market_value = _clean_decimal(match.group("value"), field="market_value", row=name)
        if quantity is None or market_value is None or quantity <= 0 or market_value <= 0:
            continue
        snapshots.append(
            BrokeragePositionSnapshot(
                snapshot_date=snapshot_date,
                asset_identifier=name.strip(),
                broker=broker,
                quantity=quantity,
                market_value=_position_money(name, market_value),
                currency=match.group("currency").upper(),
                asset_type=AssetType.MUTUAL_FUND,
            )
        )
    return snapshots


def _parse_moomoo_margin_history_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date | None
) -> list[BrokeragePositionSnapshot]:
    rows = payload.get("margin_history_rows")
    if not isinstance(rows, list):
        return []

    aggregates: dict[str, dict[str, Any]] = {}
    default_currency = _payload_currency(payload)
    for row in rows:
        if not isinstance(row, dict):
            continue
        side = str(row.get("Side") or row.get("side") or "").strip().upper()
        if side not in {"BUY", "SELL"}:
            continue
        identifier = row.get("Symbol") or row.get("symbol") or row.get("Ticker") or row.get("ticker")
        if not identifier:
            continue
        quantity = _clean_decimal(
            row.get("Fill Qty") or row.get("fill_qty") or row.get("Quantity"), field="quantity", row=identifier
        )
        market_value = _clean_decimal(
            row.get("Fill Amount") or row.get("fill_amount") or row.get("Order Amount") or row.get("order_amount"),
            field="market_value",
            row=identifier,
        )
        if quantity is None or market_value is None or quantity <= 0 or market_value <= 0:
            continue

        asset_identifier = str(identifier).strip()
        if side == "BUY":
            aggregate = aggregates.setdefault(
                asset_identifier,
                {
                    "quantity": Decimal("0"),
                    "market_value": Decimal("0"),
                    "currency": str(row.get("Currency") or row.get("currency") or default_currency).upper(),
                    "sector": None,
                    "geography": None,
                },
            )
            aggregate["quantity"] += quantity
            aggregate["market_value"] += market_value
            for attr, col in (("sector", "Sector"), ("geography", "Geography")):
                if row.get(col) and not aggregate[attr]:
                    aggregate[attr] = _optional_str(row[col])
        else:
            existing_aggregate = aggregates.get(asset_identifier)
            if existing_aggregate is None or existing_aggregate["quantity"] <= 0:
                continue
            prev_qty: Decimal = existing_aggregate["quantity"]
            new_qty = prev_qty - quantity
            if new_qty <= 0:
                existing_aggregate["quantity"] = Decimal("0")
                existing_aggregate["market_value"] = Decimal("0")
            else:
                existing_aggregate["quantity"] = new_qty
                existing_aggregate["market_value"] = existing_aggregate["market_value"] * (new_qty / prev_qty)

    return [
        BrokeragePositionSnapshot(
            snapshot_date=snapshot_date,
            asset_identifier=asset_identifier,
            broker=broker,
            quantity=aggregate["quantity"],
            market_value=_position_money(asset_identifier, aggregate["market_value"]),
            currency=aggregate["currency"],
            asset_type=AssetType.STOCK,
            sector=aggregate["sector"],
            geography=aggregate["geography"],
        )
        for asset_identifier, aggregate in aggregates.items()
        if aggregate["quantity"] > 0
    ]


_FUTU_NON_POSITION_EVENT_TOKENS: tuple[str, ...] = (
    "cash",
    "現金",
    "现金",
    "fee",
    "费用",
    "費用",
    "手续费",
    "手續費",
    "dividend",
    "股息",
    "interest",
    "利息",
    "deposit",
    "入金",
    "withdrawal",
    "出金",
    "rebate",
    "redemption",
    "distribution",
    "yield",
    "coupon",
    "sweep",
    "tax",
    "stamp",
    "duty",
    "charge",
)


def _parse_futu_aggregate_position(
    payload: dict[str, Any], broker: str, snapshot_date: date | None
) -> list[BrokeragePositionSnapshot]:
    best_value: Decimal | None = None
    for event in payload.get("events") or payload.get("transactions") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("direction") or "").strip().upper() == "OUT":
            continue
        description = str(event.get("description") or "").lower()
        if any(token in description for token in _FUTU_NON_POSITION_EVENT_TOKENS):
            continue
        value = _clean_decimal(event.get("amount"), field="market_value", row=event.get("description") or "event")
        if value is None or value <= 0:
            continue
        if "valuation" in description or best_value is None or value > best_value:
            best_value = value
    if best_value is None:
        return []
    return [
        BrokeragePositionSnapshot(
            snapshot_date=snapshot_date,
            asset_identifier="FUTU_STOCK_AND_OPTIONS",
            broker=broker,
            quantity=Decimal("1"),
            market_value=_position_money("FUTU_STOCK_AND_OPTIONS", best_value),
            currency=_payload_currency(payload, "HKD"),
            asset_type=AssetType.OTHER,
        )
    ]


class UnsupportedBrokerageCsvError(Exception):
    """Raised when a CSV matches an unsupported brokerage schema (e.g. trade history)."""


_BROKERAGE_POSITIONS_REQUIRED_GROUPS: tuple[tuple[str, ...], ...] = (
    ("symbol", "ticker", "instrument", "security"),
    ("quantity", "qty", "shares", "position", "units"),
    ("market value", "mkt value", "market val", "value", "marketvalue"),
)
_BROKERAGE_TRADE_HISTORY_REQUIRED_GROUPS: tuple[tuple[str, ...], ...] = (
    ("side", "action", "buy/sell", "b/s"),
    ("symbol", "ticker", "instrument", "security"),
    ("fill quantity", "fill qty", "filled quantity", "filled qty", "quantity", "qty"),
    ("fill price", "filled price", "price", "trade price"),
)


def _all_header_groups_match(headers_lower: list[str], groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(any(any(keyword in header for keyword in group) for header in headers_lower) for group in groups)


def classify_brokerage_csv(headers: list[str]) -> str | None:
    """Classify CSV headers into ``"positions"``, ``"trade_history"``, or ``None``."""
    headers_lower = [h.lower().strip() for h in headers if h]
    if not headers_lower:
        return None
    if _all_header_groups_match(headers_lower, _BROKERAGE_TRADE_HISTORY_REQUIRED_GROUPS):
        return "trade_history"
    if _all_header_groups_match(headers_lower, _BROKERAGE_POSITIONS_REQUIRED_GROUPS):
        return "positions"
    return None


def _find_csv_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the original-cased header whose lower form contains any candidate."""
    for header in headers:
        if header and any(keyword in header.lower().strip() for keyword in candidates):
            return header
    return None


_CSV_DATE_COLUMN_CANDIDATES: tuple[str, ...] = (
    "as of date",
    "as of",
    "asof date",
    "asof",
    "snapshot date",
    "period end",
    "statement date",
    "report date",
    "valuation date",
    "date",
)


def _find_csv_date_column(headers: list[str]) -> str | None:
    """Return the original-cased header matching a recognized date column (#2661)."""
    normalized_pairs = [(header, re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()) for header in headers if header]
    for candidate in _CSV_DATE_COLUMN_CANDIDATES:
        for header, normalized in normalized_pairs:
            if normalized == candidate:
                return header
    return None


def parse_brokerage_positions_csv_rows(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    broker: str,
    default_currency: str = "USD",
) -> list[dict[str, Any]]:
    """Map brokerage positions CSV rows into structured JSON-safe ``positions`` dicts."""
    symbol_col = _find_csv_column(headers, ("symbol", "ticker", "instrument", "security"))
    quantity_col = _find_csv_column(headers, ("quantity", "qty", "shares", "position", "units"))
    value_col = _find_csv_column(headers, ("market value", "mkt value", "market val", "marketvalue", "value"))
    price_col = _find_csv_column(headers, ("current price", "price", "mark price", "last price"))
    currency_col = _find_csv_column(headers, ("currency", "ccy"))
    asset_type_col = _find_csv_column(headers, ("asset type", "asset class", "type", "category"))
    date_col = _find_csv_date_column(headers)

    positions: list[dict[str, Any]] = []
    for row in rows:
        identifier = str(row.get(symbol_col, "") or "").strip() if symbol_col else ""
        if not identifier:
            continue
        quantity = _clean_decimal(row.get(quantity_col), field="quantity", row=identifier) if quantity_col else None
        market_value = _clean_decimal(row.get(value_col), field="market_value", row=identifier) if value_col else None
        if market_value is None and price_col and quantity is not None:
            price = _clean_decimal(row.get(price_col), field="price", row=identifier)
            if price is not None:
                market_value = price * quantity
        if quantity is None or market_value is None:
            continue
        currency = str(row.get(currency_col, "") or "").strip().upper() if currency_col else ""
        row_date = _coerce_date(row.get(date_col)) if date_col else None
        position_item: dict[str, Any] = {
            "symbol": identifier,
            "asset_identifier": identifier,
            "quantity": str(quantity),
            "market_value": str(to_money(market_value)),
            "currency": currency or default_currency.upper(),
            "asset_type": _optional_str(row.get(asset_type_col)) if asset_type_col else None,
            "broker": broker,
        }
        if row_date is not None:
            position_item["snapshot_date"] = row_date.isoformat()
        positions.append(position_item)
    return positions


def parse_brokerage_csv_payload(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    institution: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Build a brokerage positions payload from a CSV, or raise ``UnsupportedBrokerageCsvError``."""
    broker = detect_broker(filename=filename, institution=institution, text=None)
    if broker == "Unknown Broker":
        broker = institution

    schema = classify_brokerage_csv(headers)
    if schema == "trade_history":
        raise UnsupportedBrokerageCsvError(
            f"Brokerage trade-history CSV detected for {institution}. Trade-history import is not "
            "supported yet — please upload a positions/holdings CSV (symbol, quantity, market value) "
            "or the brokerage account statement (PDF) instead."
        )
    if schema != "positions":
        raise UnsupportedBrokerageCsvError(
            f"CSV for {institution} did not match a supported brokerage positions schema."
        )

    positions = parse_brokerage_positions_csv_rows(headers, rows, broker=broker)
    if not positions:
        raise UnsupportedBrokerageCsvError(
            f"Brokerage positions CSV detected for {institution} but no importable positions were "
            "found (need symbol, quantity, and market value columns with values)."
        )
    currency = positions[0]["currency"]
    payload: dict[str, Any] = {
        "institution": broker,
        "currency": currency,
        "positions": positions,
        "transactions": [],
        "balance_source": "brokerage_positions_csv",
    }
    row_dates = sorted(
        parsed_date.isoformat()
        for pos in positions
        if (parsed_date := _coerce_date(pos.get("snapshot_date"))) is not None
    )
    if row_dates:
        earliest_date, latest_date = row_dates[0], row_dates[-1]
        payload.update(
            {
                "snapshot_date": latest_date,
                "period_start": earliest_date,
                "period_end": latest_date,
                "statement": {
                    "period_start": earliest_date,
                    "period_end": latest_date,
                    "currency": currency,
                },
            }
        )
    return payload


def parse_brokerage_positions(
    payload: dict[str, Any],
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> list[BrokeragePositionSnapshot]:
    """Parse brokerage position snapshots from structured or fallback payloads."""
    statement = _statement_dict(payload)
    broker = detect_broker(
        filename=filename or str(payload.get("file") or ""),
        institution=institution or payload.get("institution") or statement.get("institution"),
        text=str(payload),
    )
    snapshot_date = _statement_date(payload)

    structured = _parse_structured_positions(payload, broker, snapshot_date)
    if structured:
        return structured
    if broker == "Moomoo":
        return _parse_moomoo_margin_history_positions(
            payload, broker, snapshot_date
        ) or _parse_moomoo_subscription_positions(payload, broker, snapshot_date)
    if broker == "Futu":
        return _parse_futu_aggregate_position(payload, broker, snapshot_date)
    return []


def brokerage_currency_balances(
    payload: dict[str, Any],
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> list[dict[str, Any]]:
    """Return only source-declared brokerage balance ladders."""
    declared: dict[str, dict[str, Any]] = {}
    _ = (filename, institution)
    raw_balances = payload.get("balances")
    if isinstance(raw_balances, list):
        for entry in raw_balances:
            if not isinstance(entry, dict):
                continue
            ccy = (entry.get("currency") or "*").strip().upper() or "*"
            opening = _clean_decimal(entry.get("opening"), field=f"{ccy} opening balance")
            closing = _clean_decimal(entry.get("closing"), field=f"{ccy} closing balance")
            if opening is None or closing is None:
                continue
            declared[ccy] = {
                "currency": ccy,
                "opening": to_money(opening),
                "closing": to_money(closing),
            }
    return [declared[ccy] for ccy in sorted(declared)]


_NON_ISO_BROKER_CURRENCIES: dict[str, str] = {"CNH": "the offshore renminbi"}
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})


def _unpriceable_currency_reason(code: str) -> str:
    """Explain a non-ISO-4217 currency rejection and user remedy (#2649)."""
    known = _NON_ISO_BROKER_CURRENCIES.get(code)
    name = f"{code!r} ({known})" if known else repr(code)
    return (
        f"the currency {name} is not an ISO-4217 code. The app converts and prices only ISO-4217 "
        "currencies, and it has no FX rate for this code. Restate the amounts in an ISO-4217 currency "
        f"{'(for example CNY) ' if code == 'CNH' else ''}or in the account currency, then import again."
    )


def _undated_remedy(filename: str | None) -> str:
    """Return source-type-specific remedy when positions carry no as-of date (#2649)."""
    extension = Path(filename).suffix.lower() if filename else ""
    if extension == ".csv":
        return "The CSV import does not read a date column. Upload the broker statement PDF that shows the as-of date."
    if extension in _DOCUMENT_EXTENSIONS:
        return (
            "The parser did not read a statement date from this document. Retry the parse, "
            "or upload a statement page that shows the as-of date."
        )
    return "Give the source a statement period_end or a snapshot_date for each position, then import again."


def _storable_snapshots(snapshots: list[BrokeragePositionSnapshot]) -> list[BrokeragePositionSnapshot]:
    """Validate and round snapshots against ``AtomicPosition`` column limits (#2649)."""
    columns = AtomicPosition.__table__.c
    storable: list[BrokeragePositionSnapshot] = []
    for snapshot in snapshots:
        label = snapshot.asset_identifier[:40]

        def reject(reason: str, label: str = label) -> NoReturn:
            raise BrokerageImportRejectedError(BROKERAGE_POSITION_OUT_OF_RANGE, f"Position {label!r}: {reason}")

        for field in ("asset_identifier", "broker", "currency", "sector", "geography"):
            text = getattr(snapshot, field)
            limit = cast(String, columns[field].type).length
            if text is not None and "\x00" in text:
                reject(f"the {field} contains a NUL character.")
            if text is not None and limit is not None and len(text) > limit:
                reject(f"the {field} has {len(text)} characters. The limit is {limit}.")
        try:
            Currency(snapshot.currency)
        except InvalidCurrencyError:
            reject(_unpriceable_currency_reason(snapshot.currency))
        rounded: dict[str, Decimal] = {}
        for field in ("quantity", "market_value"):
            amount = getattr(snapshot, field)
            numeric = cast(Numeric, columns[field].type)
            if numeric.precision is None or numeric.scale is None:
                continue
            integer_digits = numeric.precision - numeric.scale
            try:
                rounded[field] = amount.quantize(Decimal(1).scaleb(-numeric.scale), rounding=ROUND_HALF_UP)
            except InvalidOperation:
                reject(f"the {field} {amount} is out of range.")
            if abs(rounded[field]) >= Decimal(10) ** integer_digits:
                reject(
                    f"the {field} {amount} is out of range. "
                    f"The limit is {integer_digits} digits before the decimal point."
                )
        storable.append(
            replace(
                snapshot,
                quantity=rounded.get("quantity", snapshot.quantity),
                market_value=rounded.get("market_value", snapshot.market_value),
            )
        )
    return storable


def _dedup_hash(user_id: UUID, snapshot: BrokeragePositionSnapshot) -> str:
    if snapshot.snapshot_date is None:
        raise ValueError("Brokerage position snapshot date is required for import")
    return text_digest(
        "|".join([str(user_id), snapshot.snapshot_date.isoformat(), snapshot.asset_identifier, snapshot.broker])
    )


class BrokeragePositionImportService:
    """Import parsed brokerage positions into AtomicPosition then reconcile."""

    async def import_positions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        payload: dict[str, Any],
        filename: str | None = None,
        source_document_id: str | None = None,
        reconcile: bool = True,
    ) -> BrokerageImportResult:
        # Short positions (#1448) carry signed negative quantity and market value.
        snapshots = parse_brokerage_positions(payload, filename=filename)
        if source_document_id is not None:
            if "\x00" in source_document_id:
                raise BrokerageImportRejectedError(
                    BROKERAGE_POSITION_OUT_OF_RANGE,
                    "The source_document_id contains a NUL character.",
                )
            if len(source_document_id) > 255:
                raise BrokerageImportRejectedError(
                    BROKERAGE_POSITION_OUT_OF_RANGE,
                    f"The source_document_id has {len(source_document_id)} characters. The limit is 255.",
                )
        undated = sum(1 for snapshot in snapshots if snapshot.snapshot_date is None)
        if undated:
            raise BrokerageImportRejectedError(
                BROKERAGE_SNAPSHOT_DATE_MISSING,
                f"The positions source does not state an as-of date for {undated} of "
                f"{len(snapshots)} positions. The import needs the date that the source states. "
                f"{_undated_remedy(filename)}",
            )
        snapshots = _storable_snapshots(snapshots)
        created = 0
        existing = 0
        broker = (
            snapshots[0].broker if snapshots else detect_broker(filename=filename, institution=None, text=str(payload))
        )

        for snapshot in snapshots:
            insert_result = await db.execute(
                postgresql_insert(AtomicPosition)
                .values(
                    user_id=user_id,
                    snapshot_date=snapshot.snapshot_date,
                    asset_identifier=snapshot.asset_identifier,
                    broker=snapshot.broker,
                    quantity=snapshot.quantity,
                    market_value=snapshot.market_value,
                    currency=snapshot.currency,
                    asset_type=snapshot.asset_type,
                    sector=snapshot.sector,
                    geography=snapshot.geography,
                    dedup_hash=_dedup_hash(user_id, snapshot),
                    source_documents={
                        "documents": [
                            {
                                "doc_id": source_document_id,
                                "doc_type": "brokerage_statement",
                                "broker": snapshot.broker,
                            }
                        ]
                    },
                )
                .on_conflict_do_nothing(constraint="uq_atomic_positions_user_dedup_hash")
                .returning(AtomicPosition.id)
            )
            if insert_result.scalar_one_or_none() is None:
                existing += 1
            else:
                created += 1

        reconcile_result = await _get_position_reconciler()(db, user_id) if reconcile and snapshots else None

        account_id: UUID | None = None
        brokers = {snapshot.broker for snapshot in snapshots}
        if reconcile_result is not None and len(brokers) == 1:
            (single_broker,) = brokers
            account_id = await db.scalar(
                select(Account.id)
                .where(Account.user_id == user_id)
                .where(Account.name == single_broker)
                .where(Account.type == AccountType.ASSET)
            )

        return BrokerageImportResult(
            broker=broker,
            parsed_positions=len(snapshots),
            created_atomic_positions=created,
            existing_atomic_positions=existing,
            reconcile_created=reconcile_result.created if reconcile_result else 0,
            reconcile_updated=reconcile_result.updated if reconcile_result else 0,
            reconcile_disposed=reconcile_result.disposed if reconcile_result else 0,
            skipped=reconcile_result.skipped if reconcile_result else 0,
            account_id=account_id,
        )
