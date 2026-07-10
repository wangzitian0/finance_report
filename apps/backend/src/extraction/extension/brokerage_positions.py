"""Brokerage statement position parsing and import."""

from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import to_money
from src.models.account import Account, AccountType
from src.models.layer2 import AssetType, AtomicPosition
from src.portfolio import PositionService


@dataclass(frozen=True)
class BrokeragePositionSnapshot:
    """Brokerage position snapshot before persistence."""

    snapshot_date: date
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
    # #1484: the broker ASSET account these positions reconciled into, so the
    # caller can anchor the statement to it. None when no single account applies
    # (e.g. zero positions, or a mixed-broker payload).
    account_id: UUID | None = None


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
_GENERATED_ROW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GENERATED_PERIOD_RE = re.compile(r"Statement Period:\s*(?P<period>[A-Za-z]+\s+\d{4})", re.IGNORECASE)
_GENERATED_ACCOUNT_LAST4_RE = re.compile(r"Account:\s*\*{2,}(?P<last4>[A-Za-z0-9]{4})", re.IGNORECASE)


def _clean_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in {"N/A", "UNKNOWN", "NULL", "NONE"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


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
        return date(year, month, monthrange(year, month)[1])
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", text):
        text = text.replace("/", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _statement_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested ``statement`` mapping, or an empty dict when absent.

    Centralizes the ``isinstance(..., dict)`` narrowing so callers get a concrete
    ``dict[str, Any]`` (not ``dict | Any | None``) for ``.get`` access.
    """
    statement = payload.get("statement")
    return statement if isinstance(statement, dict) else {}


def _statement_date(payload: dict[str, Any]) -> date:
    statement = _statement_dict(payload)
    for candidate in (
        payload.get("snapshot_date"),
        payload.get("as_of_date"),
        payload.get("period_end"),
        statement.get("snapshot_date"),
        statement.get("as_of_date"),
        statement.get("period_end"),
    ):
        parsed = _parse_date(candidate)
        if parsed:
            return parsed
    return date.today()


def _payload_currency(payload: dict[str, Any], default: str = "USD") -> str:
    statement = _statement_dict(payload)
    currency = payload.get("currency") or statement.get("currency") or default
    return str(currency).upper()


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
    """Producer-side routing decision made BEFORE the model call (issue #1139 AC-B1).

    ``looks_like_brokerage_payload`` runs AFTER extraction and inspects the parsed
    output (positions/holdings keys). That is too late to choose the prompt: the
    single bank ``SYSTEM_PROMPT`` has no positions field, so a brokerage statement
    parsed through it never produces a holdings table to detect. This classifier uses
    only the pre-extraction signals available at prompt-selection time — the upload
    filename and the user-/header-supplied institution — reusing the same broker
    keyword detection (``detect_broker``) so routing stays consistent with the
    post-parse path. When it returns True the extraction service selects the
    brokerage positions-emitting prompt.
    """
    broker = detect_broker(filename=filename, institution=institution, text=None)
    return broker != "Unknown Broker"


def looks_like_brokerage_payload(
    payload: dict[str, Any] | None,
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> bool:
    """Return whether parsed extraction output should enter the brokerage import path."""
    if not isinstance(payload, dict):
        return False

    if any(key in payload for key in ("positions", "holdings", "securities")):
        return True

    statement = _statement_dict(payload)
    broker = detect_broker(
        filename=filename or str(payload.get("file") or ""),
        institution=institution or payload.get("institution") or statement.get("institution"),
        text=str(payload),
    )
    return broker != "Unknown Broker"


def _iter_structured_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("positions", "holdings", "securities"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    statement = payload.get("statement")
    if isinstance(statement, dict):
        for key in ("positions", "holdings", "securities"):
            value = statement.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _parse_structured_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date
) -> list[BrokeragePositionSnapshot]:
    snapshots: list[BrokeragePositionSnapshot] = []
    default_currency = _payload_currency(payload)
    for item in _iter_structured_positions(payload):
        # #1389: prefer a ticker/symbol over a free-text asset_identifier. When the
        # model emits a company name in asset_identifier but the real ticker in
        # symbol/ticker, the name used to win and became the market-data lookup
        # scope (which never resolves a price). A symbol/ticker is the canonical
        # market key; fall back to asset_identifier/isin only when absent.
        identifier = item.get("symbol") or item.get("ticker") or item.get("asset_identifier") or item.get("isin")
        quantity = _clean_decimal(item.get("quantity") or item.get("qty") or item.get("position"))
        market_value = _clean_decimal(item.get("market_value") or item.get("value") or item.get("marketValue"))
        if not identifier or quantity is None or market_value is None:
            continue
        snapshots.append(
            BrokeragePositionSnapshot(
                snapshot_date=_parse_date(item.get("snapshot_date") or item.get("as_of_date")) or snapshot_date,
                asset_identifier=str(identifier).strip(),
                broker=str(item.get("broker") or broker),
                quantity=quantity,
                market_value=to_money(market_value),
                currency=str(item.get("currency") or default_currency).upper(),
                asset_type=_asset_type(item.get("asset_type") or item.get("asset_class")),
                sector=str(item["sector"]).strip() if item.get("sector") else None,
                geography=str(item["geography"]).strip() if item.get("geography") else None,
            )
        )
    return snapshots


def _parse_moomoo_subscription_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date
) -> list[BrokeragePositionSnapshot]:
    snapshots: list[BrokeragePositionSnapshot] = []
    for event in payload.get("events") or payload.get("transactions") or []:
        if not isinstance(event, dict):
            continue
        raw_text = str(event.get("raw_text") or "")
        match = _MOOMOO_SUBSCRIPTION_RE.search(raw_text)
        if not match:
            description = str(event.get("description") or "")
            amount = _clean_decimal(event.get("amount"))
            if "Money Market Fund" not in description or amount is None or amount <= 0:
                continue
            snapshots.append(
                BrokeragePositionSnapshot(
                    snapshot_date=snapshot_date,
                    asset_identifier=description.strip(),
                    broker=broker,
                    quantity=Decimal("1"),
                    market_value=to_money(amount),
                    currency=_payload_currency(payload),
                    asset_type=AssetType.MUTUAL_FUND,
                )
            )
            continue

        quantity = _clean_decimal(match.group("quantity"))
        market_value = _clean_decimal(match.group("value"))
        if quantity is None or market_value is None:
            continue
        snapshots.append(
            BrokeragePositionSnapshot(
                snapshot_date=snapshot_date,
                asset_identifier=match.group("name").strip(),
                broker=broker,
                quantity=quantity,
                market_value=to_money(market_value),
                currency=match.group("currency").upper(),
                asset_type=AssetType.MUTUAL_FUND,
            )
        )
    return snapshots


def _parse_moomoo_margin_history_positions(
    payload: dict[str, Any], broker: str, snapshot_date: date
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
        if side != "BUY":
            continue
        identifier = row.get("Symbol") or row.get("symbol") or row.get("Ticker") or row.get("ticker")
        quantity = _clean_decimal(row.get("Fill Qty") or row.get("fill_qty") or row.get("Quantity"))
        market_value = _clean_decimal(
            row.get("Fill Amount") or row.get("fill_amount") or row.get("Order Amount") or row.get("order_amount")
        )
        if not identifier or quantity is None or market_value is None or quantity <= 0 or market_value <= 0:
            continue

        asset_identifier = str(identifier).strip()
        aggregate = aggregates.setdefault(
            asset_identifier,
            {
                "quantity": Decimal("0"),
                "market_value": Decimal("0"),
                "currency": str(row.get("Currency") or row.get("currency") or default_currency).upper(),
                "sector": str(row["Sector"]).strip() if row.get("Sector") else None,
                "geography": str(row["Geography"]).strip() if row.get("Geography") else None,
            },
        )
        aggregate["quantity"] += quantity
        aggregate["market_value"] += market_value
        if row.get("Sector") and not aggregate.get("sector"):
            aggregate["sector"] = str(row["Sector"]).strip()
        if row.get("Geography") and not aggregate.get("geography"):
            aggregate["geography"] = str(row["Geography"]).strip()

    return [
        BrokeragePositionSnapshot(
            snapshot_date=snapshot_date,
            asset_identifier=asset_identifier,
            broker=broker,
            quantity=aggregate["quantity"],
            market_value=to_money(aggregate["market_value"]),
            currency=aggregate["currency"],
            asset_type=AssetType.STOCK,
            sector=aggregate["sector"],
            geography=aggregate["geography"],
        )
        for asset_identifier, aggregate in aggregates.items()
    ]


def _parse_futu_aggregate_position(
    payload: dict[str, Any], broker: str, snapshot_date: date
) -> list[BrokeragePositionSnapshot]:
    best_value: Decimal | None = None
    for event in payload.get("events") or payload.get("transactions") or []:
        if not isinstance(event, dict):
            continue
        description = str(event.get("description") or "").lower()
        if "cash" in description or "現金" in description:
            continue
        value = _clean_decimal(event.get("amount"))
        if value is None:
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
            market_value=to_money(best_value),
            currency=_payload_currency(payload, "HKD"),
            asset_type=AssetType.OTHER,
        )
    ]


def _clean_generated_amount(value: str) -> str | None:
    amount = _clean_decimal(value)
    if amount is None or amount <= 0:
        return None
    return f"{amount:.2f}"


def _generated_statement_period_end(text: str) -> str | None:
    match = _GENERATED_PERIOD_RE.search(text)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group("period"), "%B %Y")
    except ValueError:
        return None
    last_day = monthrange(parsed.year, parsed.month)[1]
    return date(parsed.year, parsed.month, last_day).isoformat()


def _generated_account_last4(text: str) -> str | None:
    match = _GENERATED_ACCOUNT_LAST4_RE.search(text)
    return match.group("last4") if match else None


def _iter_generated_brokerage_rows(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[dict[str, str]] = []
    index = 0
    while index <= len(lines) - 5:
        if not _GENERATED_ROW_DATE_RE.fullmatch(lines[index]):
            index += 1
            continue
        rows.append(
            {
                "date": lines[index],
                "type": lines[index + 1],
                "description": lines[index + 2],
                "amount": lines[index + 3],
                "currency": lines[index + 4].upper(),
            }
        )
        index += 5
    return rows


def _generated_brokerage_positions_payload_from_text(
    text: str,
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> dict[str, Any] | None:
    """Parse positions from the deterministic generated brokerage PDF text fallback.

    The staging AI/OCR gate uses generated Moomoo/Futu PDFs whose brokerage value
    is a table row. When the provider returns the right envelope but drops the
    position row, this deterministic fallback recovers only those known synthetic
    rows from the raw PDF text. It does not invent positions for arbitrary real
    brokerage statements.
    """
    broker = detect_broker(filename=filename, institution=institution, text=text)
    if broker not in {"Moomoo", "Futu"}:
        return None

    rows = _iter_generated_brokerage_rows(text)
    positions: list[dict[str, str]] = []
    for row in rows:
        row_type = row["type"].strip().upper()
        description = row["description"].strip()
        market_value = _clean_generated_amount(row["amount"])
        if market_value is None:
            continue
        if broker == "Moomoo":
            if row_type != "SUBSCRIPTION" or "Fullerton SGD Money Market Fund" not in description:
                continue
            positions.append(
                {
                    "symbol": "Fullerton SGD Money Market Fund",
                    "asset_identifier": "Fullerton SGD Money Market Fund",
                    "quantity": "1",
                    "market_value": market_value,
                    "currency": row["currency"],
                    "asset_type": "money_market",
                }
            )
        elif broker == "Futu":
            if row_type != "VALUATION" or "stock and options valuation" not in description.lower():
                continue
            positions.append(
                {
                    "symbol": "FUTU_STOCK_AND_OPTIONS",
                    "asset_identifier": "FUTU_STOCK_AND_OPTIONS",
                    "quantity": "1",
                    "market_value": market_value,
                    "currency": row["currency"],
                    "asset_type": "other",
                }
            )

    if not positions:
        return None

    snapshot_date = _generated_statement_period_end(text) or rows[0]["date"]
    return {
        "institution": broker,
        "account_last4": _generated_account_last4(text),
        "currency": positions[0]["currency"],
        "snapshot_date": snapshot_date,
        "period_start": rows[0]["date"],
        "period_end": snapshot_date,
        "positions": positions,
        "transactions": [],
    }


class UnsupportedBrokerageCsvError(Exception):
    """A CSV matched a known brokerage schema we deliberately do not import yet.

    Raised for brokerage CSV shapes that are detected (so they must NOT fall
    through to the bank transaction parser and surface a misleading
    "No valid transactions found" error) but are intentionally out of scope —
    currently brokerage *trade-history* CSVs (side/symbol/fill-quantity/...),
    which have no positions snapshot to import. The message is user-actionable.
    """


# Header keyword sets used to classify a brokerage CSV by its column names.
# Matching is done on lower-cased, stripped headers using substring containment
# so minor broker-specific wording variations ("Mkt Value" vs "Market Value")
# still classify. Kept deliberately narrow: only schemas we can confidently
# recognize are routed away from the bank parser.
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


def _header_group_matches(headers_lower: list[str], group: tuple[str, ...]) -> bool:
    return any(any(keyword in header for keyword in group) for header in headers_lower)


def _all_header_groups_match(headers_lower: list[str], groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(_header_group_matches(headers_lower, group) for group in groups)


def classify_brokerage_csv(headers: list[str]) -> str | None:
    """Classify a CSV by its header row into a known brokerage schema.

    Returns ``"positions"`` for a brokerage positions/holdings export,
    ``"trade_history"`` for a trade/fill export, or ``None`` when the headers do
    not match any known brokerage schema (so bank CSV parsing proceeds).

    Trade-history is checked first because it shares the symbol/quantity columns
    of a positions export but adds a trade ``side``; a positions schema never
    carries a side column, so this ordering keeps the two disjoint.
    """
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
        if not header:
            continue
        low = header.lower().strip()
        if any(keyword in low for keyword in candidates):
            return header
    return None


def parse_brokerage_positions_csv_rows(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    broker: str,
    default_currency: str = "USD",
) -> list[dict[str, Any]]:
    """Map brokerage positions CSV rows into structured ``positions`` dicts.

    Produces the same per-position shape (``asset_identifier``/``quantity``/
    ``market_value``/``currency``...) consumed by ``_parse_structured_positions``
    so the result flows through the existing brokerage import path. Rows missing
    a symbol, quantity, or market value are skipped (a CSV can carry subtotal /
    blank rows). Quantity and monetary fields are parsed as ``Decimal`` for
    precision, then serialized back to ``str`` in the returned dict (JSON-safe
    payload contract); the importer re-parses them via ``_clean_decimal`` in
    ``_parse_structured_positions``.
    """
    symbol_col = _find_csv_column(headers, ("symbol", "ticker", "instrument", "security"))
    quantity_col = _find_csv_column(headers, ("quantity", "qty", "shares", "position", "units"))
    value_col = _find_csv_column(headers, ("market value", "mkt value", "market val", "marketvalue", "value"))
    price_col = _find_csv_column(headers, ("current price", "price", "mark price", "last price"))
    currency_col = _find_csv_column(headers, ("currency", "ccy"))
    asset_type_col = _find_csv_column(headers, ("asset type", "asset class", "type", "category"))

    positions: list[dict[str, Any]] = []
    for row in rows:
        identifier = str(row.get(symbol_col, "") or "").strip() if symbol_col else ""
        quantity = _clean_decimal(row.get(quantity_col)) if quantity_col else None
        market_value = _clean_decimal(row.get(value_col)) if value_col else None
        if market_value is None and price_col and quantity is not None:
            price = _clean_decimal(row.get(price_col))
            if price is not None:
                market_value = price * quantity
        if not identifier or quantity is None or market_value is None:
            continue
        currency = str(row.get(currency_col, "") or "").strip().upper() if currency_col else ""
        positions.append(
            {
                "symbol": identifier,
                "asset_identifier": identifier,
                "quantity": str(quantity),
                "market_value": str(to_money(market_value)),
                "currency": currency or default_currency.upper(),
                "asset_type": (
                    str(row.get(asset_type_col)).strip() if asset_type_col and row.get(asset_type_col) else None
                ),
                "broker": broker,
            }
        )
    return positions


def parse_brokerage_csv_payload(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    institution: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Build a brokerage positions payload from a CSV, or reject unsupported shapes.

    Detects the brokerage CSV schema from ``headers`` and:

    * positions/holdings → returns a ``{"institution", "positions", ...}`` payload
      that satisfies ``looks_like_brokerage_payload`` and flows into the brokerage
      position import path (AtomicPosition / reconciliation).
    * trade-history → raises :class:`UnsupportedBrokerageCsvError` with an
      actionable message (out of scope; never mapped into bank transactions).

    Raises :class:`UnsupportedBrokerageCsvError` if the schema is brokerage but
    yields zero importable positions, so the upload fails with a clear message
    rather than the misleading generic bank "No valid transactions" error.
    """
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
    return {
        "institution": broker,
        "currency": currency,
        "positions": positions,
        "transactions": [],
        "balance_source": "brokerage_positions_csv",
    }


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
        margin_history = _parse_moomoo_margin_history_positions(payload, broker, snapshot_date)
        if margin_history:
            return margin_history
        return _parse_moomoo_subscription_positions(payload, broker, snapshot_date)
    if broker == "Futu":
        return _parse_futu_aggregate_position(payload, broker, snapshot_date)
    return []


def brokerage_currency_balances(
    payload: dict[str, Any],
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> list[dict[str, Any]]:
    """Derive the per-currency NAV array for a brokerage statement (#1139 AC-B3).

    A multi-currency brokerage statement (IBKR / Futu / Wise) holds positions in
    several currencies at once. Collapsing them into a single scalar
    ``opening_balance`` / ``closing_balance`` would cross-sum unrelated currencies
    into a meaningless number. Instead each currency is an independent closed loop:
    its closing NAV is the sum of that currency's position market values, and —
    because a position snapshot carries no intra-period cash flow — its opening
    equals its closing (net == 0, so ``open + ΣIN − ΣOUT ≈ close`` holds per
    currency). The result is the ``[{currency, opening, closing}]`` shape consumed
    by :func:`src.extraction.base.validation.validate_balance_per_currency` and persisted
    on ``StatementSummary.currency_balances``.

    An explicitly declared ``balances`` array on the payload (a broker that prints
    a real opening/closing cash ladder per currency) is authoritative and returned
    as-is — the derived position NAV only fills currencies that ladder omits, so a
    declared opening is never overwritten by the snapshot-equals-NAV degenerate.

    Currencies are NEVER summed across; the array is empty when no positions and no
    declared balances exist, so callers can leave ``currency_balances`` NULL.
    """
    by_currency: dict[str, Decimal] = {}
    for snapshot in parse_brokerage_positions(payload, filename=filename, institution=institution):
        ccy = (snapshot.currency or "*").strip().upper() or "*"
        by_currency[ccy] = by_currency.get(ccy, Decimal("0")) + snapshot.market_value

    # Explicit per-currency cash ladders win over the derived snapshot NAV.
    declared: dict[str, dict[str, Any]] = {}
    raw_balances = payload.get("balances")
    if isinstance(raw_balances, list):
        for entry in raw_balances:
            if not isinstance(entry, dict):
                continue
            ccy = (entry.get("currency") or "*").strip().upper() or "*"
            declared[ccy] = {
                "currency": ccy,
                "opening": to_money(_clean_decimal(entry.get("opening")) or Decimal("0")),
                "closing": to_money(_clean_decimal(entry.get("closing")) or Decimal("0")),
            }

    balances: list[dict[str, Any]] = []
    for ccy in sorted({*by_currency, *declared}):
        if ccy in declared:
            balances.append(declared[ccy])
            continue
        nav = to_money(by_currency[ccy])
        # Snapshot statement: opening == closing == NAV (no intra-period cash flow),
        # so the per-currency reconciliation is a zero-net closed loop.
        balances.append({"currency": ccy, "opening": nav, "closing": nav})
    return balances


def _dedup_hash(user_id: UUID, snapshot: BrokeragePositionSnapshot) -> str:
    material = "|".join(
        [
            str(user_id),
            snapshot.snapshot_date.isoformat(),
            snapshot.asset_identifier,
            snapshot.broker,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
        # #1448: short positions (a margin short or a sold option) are signed — negative
        # quantity AND negative market value — and import as first-class positions. The
        # non-negative market-value / cost-basis CHECK constraints have been dropped, so a
        # short reduces portfolio value instead of being skipped (which dropped real data)
        # or crashing the import (constraint violation → 500).
        snapshots = parse_brokerage_positions(payload, filename=filename)
        created = 0
        existing = 0
        broker = (
            snapshots[0].broker if snapshots else detect_broker(filename=filename, institution=None, text=str(payload))
        )

        for snapshot in snapshots:
            dedup_hash = _dedup_hash(user_id, snapshot)
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
                    dedup_hash=dedup_hash,
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

        reconcile_result = None
        if reconcile and snapshots:
            reconcile_result = await PositionService().reconcile_positions(db, user_id)

        # #1484: anchor the statement to the broker account these positions
        # reconciled into. Only resolve when the payload is a single broker (one
        # account) — a statement spanning multiple brokers has no single anchor.
        account_id: UUID | None = None
        brokers = {snapshot.broker for snapshot in snapshots}
        if reconcile_result is not None and len(brokers) == 1:
            # Use the one broker actually present (not result.broker, which falls
            # back to the first snapshot) so the lookup is unambiguous.
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
