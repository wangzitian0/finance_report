"""Brokerage statement position parsing and import."""

from __future__ import annotations

import hashlib
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer2 import AssetType, AtomicPosition
from src.money import to_money
from src.services.assets import AssetService


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


def _statement_date(payload: dict[str, Any]) -> date:
    statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
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
    statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
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

    statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
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
        identifier = item.get("asset_identifier") or item.get("symbol") or item.get("ticker") or item.get("isin")
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


def parse_brokerage_positions(
    payload: dict[str, Any],
    *,
    filename: str | None = None,
    institution: str | None = None,
) -> list[BrokeragePositionSnapshot]:
    """Parse brokerage position snapshots from structured or fallback payloads."""
    statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
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
    by :func:`src.services.validation.validate_balance_per_currency` and persisted
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
            reconcile_result = await AssetService().reconcile_positions(db, user_id)

        return BrokerageImportResult(
            broker=broker,
            parsed_positions=len(snapshots),
            created_atomic_positions=created,
            existing_atomic_positions=existing,
            reconcile_created=reconcile_result.created if reconcile_result else 0,
            reconcile_updated=reconcile_result.updated if reconcile_result else 0,
            reconcile_disposed=reconcile_result.disposed if reconcile_result else 0,
            skipped=reconcile_result.skipped if reconcile_result else 0,
        )
