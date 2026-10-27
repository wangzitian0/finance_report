"""Authoritative cash-touch event projection and cash-flow generation."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.audit import JournalEntrySourceType
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalLine,
    ProcessingAccount,
)
from src.ledger.orm.journal import active_journal_entry_filter
from src.observability import ErrorIds, get_logger
from src.reporting.base.cash_flow_calculator import calculate_cash_flow_bridge
from src.reporting.extension import fx_gateway
from src.reporting.extension._core import _line_total
from src.reporting.extension.reporting_calc import ReportError, _normalize_currency, _quantize_money

logger = get_logger(__name__)
_PROCESSING_ACCOUNT = ProcessingAccount()
_AUTO_BANK_ACCOUNT_CODE = "AUTO-BANK"

#: Plain-language cause and next action for each cash-flow proof reason (#2466).
#: Every reason that ``generate_cash_flow`` emits has one entry here.
CASH_FLOW_UNPROVEN_FALLBACK_TEXT = (
    "Cash-flow event classification or lineage is unproven and cannot authorize a package."
)
CASH_FLOW_PROOF_REASON_TEXT: dict[str, str] = {
    "opening_coverage_starts_after_period": (
        "Your statements start after the first day of this period. "
        "Upload the earlier statements or choose a period that starts on or after your first statement."
    ),
    "opening_position_unproven": (
        "An opening balance has no confirmed source decision. Review and approve the statement that carries it."
    ),
    "cash_identity_compatibility_fallback": (
        "No bank account is marked as cash from a statement. Approve a bank statement so its account becomes cash."
    ),
    "cash_identity_missing": (
        "No cash account matches a statement custody account. Confirm the account of your bank statement."
    ),
    "cash_event_decision_unproven": (
        "A cash movement has no confirmed source decision. Review the pending statement rows."
    ),
    "cash_event_classification_ambiguous": (
        "A cash movement is not classified as operating, investing, or financing. Set the category of that entry."
    ),
}


def cash_flow_proof_reason_text(reason_code: str) -> str:
    """Return the user-facing text for one cash-flow proof reason."""
    return CASH_FLOW_PROOF_REASON_TEXT.get(reason_code, CASH_FLOW_UNPROVEN_FALLBACK_TEXT)


CashActivity = Literal["Operating", "Investing", "Financing"]
_EXPLICIT_EVENT_ACTIVITIES: dict[str, CashActivity] = {
    "investment_buy": "Investing",
    "investment_sell": "Investing",
}
_EXPLICIT_EVENT_COMPANIONS: dict[str, frozenset[str]] = {
    "investment_buy": frozenset({"investment_buy"}),
    "investment_sell": frozenset({"investment_sell", "investment_realized_pnl"}),
}
_STATEMENT_SOURCE_TYPES: frozenset[JournalEntrySourceType] = frozenset(
    {
        JournalEntrySourceType.AUTO_PARSED,
        JournalEntrySourceType.USER_CONFIRMED,
        JournalEntrySourceType.SYSTEM,
    }
)
_STATEMENT_CATEGORY_ACTIVITIES: dict[str, tuple[CashActivity, AccountType]] = {
    "LOAN_PRINCIPAL": ("Financing", AccountType.LIABILITY),
    "INVESTMENT_TRADE": ("Investing", AccountType.ASSET),
}
_SECTIONS = ("operating", "investing", "financing")
#: Line id of the lineage records of unclassified cash events (#2583).
CASH_FLOW_UNCLASSIFIED_LINE_ID = "unclassified"
#: Line id of the lineage records of opening stock that the period first evidences (#2583).
CASH_FLOW_OPENING_STOCK_LINE_ID = "opening_stock"
_FIXED_LINE_IDS = frozenset({CASH_FLOW_UNCLASSIFIED_LINE_ID, CASH_FLOW_OPENING_STOCK_LINE_ID})


@dataclass(frozen=True, slots=True)
class _EntryFacts:
    """The journal-entry columns that cash-event classification and lineage read."""

    id: UUID
    entry_date: date
    memo: str
    source_type: JournalEntrySourceType
    source_id: UUID | None
    decision_anchor_id: UUID | None
    decision_authority_state: JournalEntryAuthorityState


@dataclass(frozen=True, slots=True)
class _LineFacts:
    """The journal-line columns that cash-event classification and lineage read."""

    id: UUID
    direction: Direction
    amount: Decimal
    currency: str
    event_type: str | None
    economic_category: str | None


@dataclass(frozen=True, slots=True)
class _CashEvent:
    """One tenant-safe journal event that touches an authoritative cash identity."""

    entry: _EntryFacts
    cash_lines: tuple[tuple[_LineFacts, Account], ...]
    counterpart_lines: tuple[tuple[_LineFacts, Account], ...]

    @property
    def has_authoritative_decision(self) -> bool:
        return (
            self.entry.decision_authority_state == JournalEntryAuthorityState.ANCHORED
            and self.entry.decision_anchor_id is not None
        )

    @property
    def activity(self) -> CashActivity | None:
        cash_event_types = {line.event_type for line, _account in self.cash_lines}
        has_authoritative_producer = (
            self.entry.source_type == JournalEntrySourceType.SYSTEM and self.has_authoritative_decision
        )
        if has_authoritative_producer and len(cash_event_types) == 1:
            event_type = next(iter(cash_event_types))
            if event_type is not None:
                explicit_activity = _EXPLICIT_EVENT_ACTIVITIES.get(event_type)
                allowed_companions = _EXPLICIT_EVENT_COMPANIONS.get(event_type, frozenset())
                counterpart_event_types = {line.event_type for line, _account in self.counterpart_lines}
                if explicit_activity is not None and counterpart_event_types <= allowed_companions:
                    return explicit_activity

        if (
            self.entry.source_type in _STATEMENT_SOURCE_TYPES
            and self.has_authoritative_decision
            and len(self.cash_lines) == 1
            and len(self.counterpart_lines) == 1
        ):
            cash_line, _cash_account = self.cash_lines[0]
            counter_line, counter_account = self.counterpart_lines[0]
            category = counter_line.economic_category
            if (
                cash_line.event_type == "bank_txn"
                and counter_line.event_type == "bank_txn"
                and isinstance(category, str)
            ):
                expected = _STATEMENT_CATEGORY_ACTIVITIES.get(category)
                if expected is not None and counter_account.type == expected[1]:
                    return expected[0]

        counterpart_types = {account.type for _line, account in self.counterpart_lines}
        if counterpart_types and counterpart_types <= {AccountType.INCOME, AccountType.EXPENSE}:
            # P&L accounts are unambiguous operating evidence. Balance-sheet
            # account types cannot distinguish AR/AP settlement from investing
            # or financing, so unsupported events deliberately remain unproven.
            return "Operating"
        return None


def _cash_delta(line: _LineFacts) -> Decimal:
    return line.amount if line.direction == Direction.DEBIT else -line.amount


def _event_lineage(
    event: _CashEvent,
    *,
    activity: CashActivity | None,
    reason_code: str | None,
) -> dict[str, object]:
    all_lines = (*event.cash_lines, *event.counterpart_lines)
    return {
        "journal_entry_id": event.entry.id,
        "journal_line_ids": [line.id for line, _account in all_lines],
        "source_type": event.entry.source_type.value,
        "source_id": event.entry.source_id,
        "decision_anchor_id": event.entry.decision_anchor_id,
        "decision_authority_state": event.entry.decision_authority_state.value,
        "event_types": sorted({line.event_type for line, _account in all_lines if line.event_type is not None}),
        "activity": activity,
        "reason_code": reason_code,
    }


async def _load_cash_events(
    db: AsyncSession,
    user_id: UUID,
    *,
    end_date: date,
    cash_account_ids: frozenset[UUID],
    account_by_id: dict[UUID, Account],
) -> tuple[_CashEvent, ...]:
    """Load complete entries only when both the entry and every account belong to the tenant.

    The read selects columns, not ORM rows: one year of data has about 2000 lines (#2583).
    ``account_by_id`` holds the accounts of the tenant. The read adds an account that the
    caller did not load, for example an account that a concurrent request created.
    """
    stmt = _cash_event_rows_statement(user_id, end_date=end_date, cash_account_ids=cash_account_ids)
    rows = (await db.execute(stmt)).all()
    missing_account_ids = {row.account_id for row in rows}.difference(account_by_id)
    if missing_account_ids:
        added = await db.execute(
            select(Account).where(Account.user_id == user_id).where(Account.id.in_(missing_account_ids))
        )
        account_by_id.update((account.id, account) for account in added.scalars())
    grouped: dict[UUID, tuple[_EntryFacts, list[tuple[_LineFacts, Account]]]] = {}
    for row in rows:
        group = grouped.get(row.entry_id)
        if group is None:
            group = grouped[row.entry_id] = (
                _EntryFacts(
                    id=row.entry_id,
                    entry_date=row.entry_date,
                    memo=row.memo,
                    source_type=row.source_type,
                    source_id=row.source_id,
                    decision_anchor_id=row.decision_anchor_id,
                    decision_authority_state=row.decision_authority_state,
                ),
                [],
            )
        line = _LineFacts(
            id=row.line_id,
            direction=row.direction,
            amount=row.amount,
            currency=row.currency,
            event_type=row.event_type,
            economic_category=row.economic_category,
        )
        group[1].append((line, account_by_id[row.account_id]))

    events: list[_CashEvent] = []
    for entry, lines in grouped.values():
        cash_lines = tuple(pair for pair in lines if pair[1].id in cash_account_ids)
        if not cash_lines:
            continue
        events.append(
            _CashEvent(
                entry=entry,
                cash_lines=cash_lines,
                counterpart_lines=tuple(pair for pair in lines if pair[1].id not in cash_account_ids),
            )
        )
    return tuple(events)


def _cash_event_rows_statement(
    user_id: UUID,
    *,
    end_date: date,
    cash_account_ids: frozenset[UUID] | None = None,
) -> Select[tuple[Any, ...]]:
    """Build the complete-entry query so tenant predicates remain directly provable.

    Each row holds the columns of ``_LineFacts`` and ``_EntryFacts`` and the line's account id.
    """
    foreign_line = aliased(JournalLine)
    foreign_account = aliased(Account)
    cash_line = aliased(JournalLine)
    has_foreign_account = exists(
        select(foreign_line.id)
        .join(foreign_account, foreign_line.account_id == foreign_account.id)
        .where(foreign_line.journal_entry_id == JournalEntry.id)
        .where(foreign_account.user_id != user_id)
    )
    stmt = (
        select(
            JournalLine.id.label("line_id"),
            JournalLine.direction,
            JournalLine.amount,
            JournalLine.currency,
            JournalLine.event_type,
            JournalLine.tags["economic_category"].astext.label("economic_category"),
            Account.id.label("account_id"),
            JournalEntry.id.label("entry_id"),
            JournalEntry.entry_date,
            JournalEntry.memo,
            JournalEntry.source_type,
            JournalEntry.source_id,
            JournalEntry.decision_anchor_id,
            JournalEntry.decision_authority_state,
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalEntry.user_id == user_id)
        .where(Account.user_id == user_id)
        .where(~has_foreign_account)
        .where(active_journal_entry_filter(JournalEntry))
        .where(JournalEntry.entry_date <= end_date)
        .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
    )
    if cash_account_ids is not None:
        has_cash_leg = exists(
            select(cash_line.id)
            .where(cash_line.journal_entry_id == JournalEntry.id)
            .where(cash_line.account_id.in_(cash_account_ids))
        )
        stmt = stmt.where(has_cash_leg)
    return stmt


@dataclass(frozen=True, slots=True)
class _LineRecord:
    """One lineage record of the period and the statement line that shows it (#2583)."""

    line_id: str
    entry_date: date
    memo: str
    amount: Decimal
    lineage: dict[str, object]

    def event(self) -> dict[str, object]:
        return {**self.lineage, "entry_date": self.entry_date, "memo": self.memo, "amount": self.amount}


@dataclass(frozen=True, slots=True)
class _CashFlowBuild:
    document: dict[str, object]
    records: tuple[_LineRecord, ...]


def cash_flow_period(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    """Return the requested cash-flow period. The default is the year to date of the end date."""
    resolved_end_date = end_date or date.today()
    return start_date or date(resolved_end_date.year, 1, 1), resolved_end_date


def cash_flow_line_id(item: Mapping[str, Any]) -> str:
    """Return the id of the statement line that shows one activity item (#2583).

    Items with equal category, description and account id are on one line. The description
    holds the flow direction and the counterpart names, so each line has one direction.
    """
    category = str(item["category"])
    key = "\x1f".join((category, str(item.get("description") or ""), str(item.get("account_id") or "")))
    return f"{category.lower()}-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


async def generate_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    cash_account_ids: frozenset[UUID] | None = None,
) -> dict[str, object]:
    """Generate cash flow from journal-entry cash-touch events, never account-period inference."""
    build = await _build_cash_flow(
        db, user_id, start_date=start_date, end_date=end_date, currency=currency, cash_account_ids=cash_account_ids
    )
    return build.document


async def cash_flow_line_events(
    db: AsyncSession,
    user_id: UUID,
    *,
    line_id: str,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    cash_account_ids: frozenset[UUID] | None = None,
) -> list[dict[str, object]] | None:
    """Return the lineage records of one statement line in document order, or None for no line (#2583).

    The records come from the builder of ``generate_cash_flow``. Each record adds the entry
    date, the entry memo and the cash movement to its lineage. The line ids are the ids of
    ``cash_flow_preview`` and the two fixed ids of the unclassified and opening-stock records.
    """
    build = await _build_cash_flow(
        db, user_id, start_date=start_date, end_date=end_date, currency=currency, cash_account_ids=cash_account_ids
    )
    events = [record.event() for record in build.records if record.line_id == line_id]
    if not events and line_id not in _FIXED_LINE_IDS:
        return None
    return events


def cash_flow_preview(document: Mapping[str, Any]) -> dict[str, object]:
    """Project a cash-flow document to its bounded preview (#2583).

    Each section has one line for each ``cash_flow_line_id``, with the sum and the count of its
    items, largest absolute amount first. ``lineage_summary`` counts the lineage records.
    ``cash_flow_line_events`` returns the records of one line.
    """
    preview: dict[str, object] = {
        key: value for key, value in document.items() if key not in (*_SECTIONS, "event_lineage")
    }
    for section in _SECTIONS:
        lines: dict[str, dict[str, Any]] = {}
        for item in document.get(section) or ():
            line_id = cash_flow_line_id(item)
            amount = Decimal(str(item["amount"]))
            line = lines.get(line_id)
            if line is None:
                lines[line_id] = {**item, "line_id": line_id, "amount": amount, "event_count": 1}
            else:
                line["amount"] += amount
                line["event_count"] += 1
        for line in lines.values():
            line["amount"] = _quantize_money(line["amount"])
        preview[section] = sorted(lines.values(), key=lambda line: (-abs(line["amount"]), line["line_id"]))
    reasons = Counter(record["reason_code"] for record in document.get("event_lineage") or ())
    preview["lineage_summary"] = {
        "event_count": sum(reasons.values()),
        "classified_event_count": reasons[None],
        "unclassified_event_count": reasons["cash_event_classification_ambiguous"],
        "opening_stock_event_count": reasons["opening_stock"],
    }
    return preview


def _line_record(event: _CashEvent, line_id: str, amount: Decimal, lineage: dict[str, object]) -> _LineRecord:
    return _LineRecord(
        line_id=line_id,
        entry_date=event.entry.entry_date,
        memo=event.entry.memo,
        amount=_quantize_money(amount),
        lineage=lineage,
    )


def _select_cash_account_ids(
    accounts: Sequence[Account], cash_account_ids: frozenset[UUID] | None
) -> tuple[frozenset[UUID], frozenset[UUID]]:
    """Return the cash accounts of a cash flow and the exact identities among them.

    With no explicit identity, a name match selects the cash accounts (a compatibility fallback).
    The system Processing account is a ledger-defined cash equivalent and is always included.
    """
    account_ids = {account.id for account in accounts}
    exact_selected_ids: set[UUID] = set()
    if cash_account_ids is None:
        keywords = ("cash", "bank", "checking", "savings", "money market", "petty cash")
        selected_ids = {
            account.id
            for account in accounts
            if account.type == AccountType.ASSET
            and (
                account.code == _AUTO_BANK_ACCOUNT_CODE or any(keyword in account.name.lower() for keyword in keywords)
            )
        }
    else:
        selected_ids = {account_id for account_id in cash_account_ids if account_id in account_ids}
        exact_selected_ids = set(selected_ids)

    # Processing is a ledger-defined cash equivalent: including it makes both legs
    # of an in-transit internal transfer neutral without name inference.
    selected_ids.update(
        account.id
        for account in accounts
        if account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET
    )
    return frozenset(selected_ids), frozenset(exact_selected_ids)


async def cash_opening_positions(
    db: AsyncSession, user_id: UUID, *, as_of: date, cash_account_ids: frozenset[UUID]
) -> tuple[Any, ...]:
    """The opening positions of the cash accounts, effective on or before ``as_of``."""
    from src.ledger import list_opening_positions

    return tuple(
        position
        for position in await list_opening_positions(db, user_id=user_id, as_of=as_of)
        if position.account_id in cash_account_ids
    )


def opening_coverage_start(opening_positions: Iterable[Any]) -> date | None:
    """The first day that a cash-flow period can start with the opening position of every cash account.

    It is the latest effective date of the positions. A period that starts before it has the proof
    reason ``opening_coverage_starts_after_period``. Report period bounds read this function (#2646).
    """
    return max((position.effective_date for position in opening_positions), default=None)


@dataclass(frozen=True, slots=True)
class CashCoverage:
    """``opening_coverage_start`` of a set of cash accounts, and the accounts that set it."""

    start: date | None
    #: The names of the cash accounts whose opening position is on ``start``, sorted.
    limiting_account_names: tuple[str, ...]
    #: The latest approved statement period end on or before ``as_of`` (#2726).
    latest_statement_end: date | None = None


async def cash_coverage(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of: date,
    cash_account_id_sets: Sequence[frozenset[UUID] | None],
    latest_statement_end: date | None = None,
) -> CashCoverage:
    """The coverage start over the cash accounts that ``generate_cash_flow`` selects for each id set.

    ``None`` in ``cash_account_id_sets`` stands for the name-match selection. The latest opening
    over the union is the latest of the per-set bounds, so a period that starts on it passes the
    check of every set. One read of the accounts and one of the opening positions.
    """
    accounts = list((await db.execute(select(Account).where(Account.user_id == user_id))).scalars().all())
    cash_ids: set[UUID] = set()
    for ids in cash_account_id_sets:
        cash_ids.update(_select_cash_account_ids(accounts, ids)[0])
    positions = await cash_opening_positions(db, user_id, as_of=as_of, cash_account_ids=frozenset(cash_ids))
    start = opening_coverage_start(positions)
    names = {account.id: account.name for account in accounts}
    limiting = sorted({names[p.account_id] for p in positions if p.effective_date == start and p.account_id in names})
    return CashCoverage(
        start=start,
        limiting_account_names=tuple(limiting),
        latest_statement_end=latest_statement_end,
    )


async def _build_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None,
    cash_account_ids: frozenset[UUID] | None,
) -> _CashFlowBuild:
    """Build the cash-flow document and its line records in one pass over the cash events."""
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")
    target_currency = _normalize_currency(currency)

    accounts = list((await db.execute(select(Account).where(Account.user_id == user_id))).scalars().all())
    account_by_id = {account.id: account for account in accounts}
    explicit_cash_identity = cash_account_ids is not None
    effective_cash_ids, exact_selected_ids = _select_cash_account_ids(accounts, cash_account_ids)
    events = await _load_cash_events(
        db, user_id, end_date=end_date, cash_account_ids=effective_cash_ids, account_by_id=account_by_id
    )
    opening_positions = await cash_opening_positions(db, user_id, as_of=end_date, cash_account_ids=effective_cash_ids)
    proven_openings = {
        (position.journal_entry_id, position.account_id): position
        for position in opening_positions
        if position.state == "authoritative" and position.decision is not None
    }

    fx_needs: set[tuple[str, str, date, date | None, date | None]] = set()
    for event in events:
        for line, _account in event.cash_lines:
            source = line.currency.upper()
            if source == target_currency:
                continue
            fx_needs.add((source, target_currency, end_date, None, None))
            if event.entry.entry_date < start_date:
                fx_needs.add((source, target_currency, start_date, None, None))
            if start_date <= event.entry.entry_date <= end_date:
                fx_needs.add((source, target_currency, event.entry.entry_date, None, None))

    fx_rates = fx_gateway.PrefetchedFxRates(lazy_load=True)
    if fx_needs:
        try:
            await fx_rates.prefetch(db, list(fx_needs))
        except fx_gateway.FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for cash flow", error_id=ErrorIds.REPORT_GENERATION_FAILED, error=str(exc)
            )
            raise ReportError(str(exc)) from exc

    def converted_delta(line: _LineFacts, rate_date: date) -> Decimal:
        source = line.currency.upper()
        rate = Decimal("1") if source == target_currency else fx_rates.get_rate(source, target_currency, rate_date)
        if rate is None:
            raise ReportError(f"No FX rate available for {source}/{target_currency} on {rate_date}")
        return _cash_delta(line) * rate

    beginning_cash = Decimal("0")
    ending_cash = Decimal("0")
    operating_items: list[dict[str, object]] = []
    investing_items: list[dict[str, object]] = []
    financing_items: list[dict[str, object]] = []
    event_lineage: list[dict[str, object]] = []
    records: list[_LineRecord] = []
    unclassified_cash = Decimal("0")
    opening_stock_adjustment = Decimal("0")
    proof_reasons: set[str] = set()
    if not explicit_cash_identity:
        proof_reasons.add("cash_identity_compatibility_fallback")
    elif not exact_selected_ids:
        proof_reasons.add("cash_identity_missing")

    for position in opening_positions:
        if position.state != "authoritative" or position.decision is None:
            proof_reasons.add("opening_position_unproven")
    coverage_start = opening_coverage_start(opening_positions)
    if coverage_start is not None and coverage_start > start_date:
        proof_reasons.add("opening_coverage_starts_after_period")

    for event in events:
        beginning_movement = Decimal("0")
        if event.entry.entry_date < start_date:
            beginning_movement = sum(
                (converted_delta(line, start_date) for line, _account in event.cash_lines), Decimal("0")
            )
            beginning_cash += beginning_movement
        ending_movement = sum((converted_delta(line, end_date) for line, _account in event.cash_lines), Decimal("0"))
        ending_cash += ending_movement
        if not event.has_authoritative_decision and (
            beginning_movement != Decimal("0") or ending_movement != Decimal("0")
        ):
            proof_reasons.add("cash_event_decision_unproven")
        if not (start_date <= event.entry.entry_date <= end_date):
            continue

        opening_lines = tuple(
            (line, account)
            for line, account in event.cash_lines
            if (position := proven_openings.get((event.entry.id, account.id))) is not None
            and position.effective_date == event.entry.entry_date
            and position.currency == line.currency
            and position.amount == _cash_delta(line)
        )
        opening_amount = sum(
            (converted_delta(line, event.entry.entry_date) for line, _account in opening_lines), Decimal("0")
        )
        if opening_lines:
            if event.entry.entry_date == start_date:
                beginning_cash += opening_amount
            else:
                opening_stock_adjustment += opening_amount
            lineage = _event_lineage(event, activity=None, reason_code="opening_stock")
            event_lineage.append(lineage)
            records.append(_line_record(event, CASH_FLOW_OPENING_STOCK_LINE_ID, opening_amount, lineage))
        opening_line_ids = {line.id for line, _account in opening_lines}
        movement = sum(
            (
                converted_delta(line, event.entry.entry_date)
                for line, _account in event.cash_lines
                if line.id not in opening_line_ids
            ),
            Decimal("0"),
        )
        if movement == Decimal("0"):
            continue
        activity = event.activity
        if activity is None:
            unclassified_cash += movement
            proof_reasons.add("cash_event_classification_ambiguous")
            lineage = _event_lineage(event, activity=None, reason_code="cash_event_classification_ambiguous")
            event_lineage.append(lineage)
            records.append(_line_record(event, CASH_FLOW_UNCLASSIFIED_LINE_ID, movement, lineage))
            continue
        counterpart_accounts = {account.id: account for _line, account in event.counterpart_lines}
        item = {
            "category": activity,
            "subcategory": ", ".join(sorted(account.name for account in counterpart_accounts.values())),
            "amount": _quantize_money(movement),
            "description": f"{'Inflow' if movement > 0 else 'Outflow'} - "
            + ", ".join(sorted(account.name for account in counterpart_accounts.values())),
            "account_id": next(iter(counterpart_accounts)) if len(counterpart_accounts) == 1 else None,
        }
        lineage = _event_lineage(event, activity=activity, reason_code=None)
        event_lineage.append(lineage)
        records.append(_line_record(event, cash_flow_line_id(item), movement, lineage))
        if activity == "Operating":
            operating_items.append(item)
        elif activity == "Investing":
            investing_items.append(item)
        else:
            financing_items.append(item)

    for items in (operating_items, investing_items, financing_items):
        items.sort(key=lambda item: abs(Decimal(str(item["amount"]))), reverse=True)

    operating_total = _line_total(operating_items)
    investing_total = _line_total(investing_items)
    financing_total = _line_total(financing_items)
    calculated_fx_effect = Decimal("0")
    if bool(fx_needs):
        for event in events:
            for line, _account in event.cash_lines:
                source = line.currency.upper()
                if source == target_currency:
                    continue
                if event.entry.entry_date < start_date:
                    calculated_fx_effect += converted_delta(line, end_date) - converted_delta(line, start_date)
                elif start_date <= event.entry.entry_date <= end_date:
                    calculated_fx_effect += converted_delta(line, end_date) - converted_delta(
                        line, event.entry.entry_date
                    )
    fx_effect = _quantize_money(calculated_fx_effect)

    bridge = calculate_cash_flow_bridge(
        beginning_cash=beginning_cash,
        ending_cash=ending_cash,
        operating_total=operating_total,
        investing_total=investing_total,
        financing_total=financing_total,
        unclassified_cash=unclassified_cash,
        opening_stock_adjustment=opening_stock_adjustment,
        fx_effect=fx_effect,
    )

    document: dict[str, object] = {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "operating": operating_items,
        "investing": investing_items,
        "financing": financing_items,
        "summary": {
            "operating_activities": bridge.operating_total,
            "investing_activities": bridge.investing_total,
            "financing_activities": bridge.financing_total,
            "net_cash_flow": bridge.net_cash_flow,
            "beginning_cash": _quantize_money(beginning_cash),
            "ending_cash": _quantize_money(ending_cash),
        },
        "cash_bridge": {
            "classified_activity": bridge.classified_activity,
            "unclassified_cash": _quantize_money(unclassified_cash),
            "fx_effect": bridge.fx_effect,
            "opening_stock_adjustment": _quantize_money(opening_stock_adjustment),
            "cash_delta": bridge.cash_delta,
            "discrepancy": bridge.discrepancy,
            "reconciles": bridge.reconciles,
        },
        "event_lineage": event_lineage,
        "proof_state": "proven" if not proof_reasons else "unproven",
        "proof_reasons": sorted(proof_reasons),
    }
    return _CashFlowBuild(document=document, records=tuple(records))
