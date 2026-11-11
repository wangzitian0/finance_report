"""Authoritative cash-touch event projection and cash-flow generation."""

from __future__ import annotations

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

from src.audit import JournalEntrySourceType, text_digest
from src.config_app import get_effective_base_currency
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalLine,
    ProcessingAccount,
    account_service,
)
from src.ledger.orm.journal import active_journal_entry_filter
from src.pricing import PrefetchedFxRates
from src.reporting.base.cash_flow_calculator import calculate_cash_flow_bridge
from src.reporting.extension._core import _line_total, _load_accounts, _prefetch_fx_rates
from src.reporting.extension.reporting_calc import ReportError, _normalize_currency, _quantize_money

_PROCESSING_ACCOUNT = ProcessingAccount()
_AUTO_BANK_ACCOUNT_CODE = "AUTO-BANK"

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
CASH_FLOW_UNCLASSIFIED_LINE_ID = "unclassified"
CASH_FLOW_OPENING_STOCK_LINE_ID = "opening_stock"
_FIXED_LINE_IDS = frozenset({CASH_FLOW_UNCLASSIFIED_LINE_ID, CASH_FLOW_OPENING_STOCK_LINE_ID})


@dataclass(frozen=True, slots=True)
class _EntryFacts:
    id: UUID
    entry_date: date
    memo: str
    source_type: JournalEntrySourceType
    source_id: UUID | None
    decision_anchor_id: UUID | None
    decision_authority_state: JournalEntryAuthorityState


@dataclass(frozen=True, slots=True)
class _LineFacts:
    id: UUID
    direction: Direction
    amount: Decimal
    currency: str
    event_type: str | None
    economic_category: str | None


@dataclass(frozen=True, slots=True)
class _CashEvent:
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
                if (
                    explicit_activity is not None
                    and {line.event_type for line, _ in self.counterpart_lines} <= allowed_companions
                ):
                    return explicit_activity

        if (
            self.entry.source_type in _STATEMENT_SOURCE_TYPES
            and self.has_authoritative_decision
            and len(self.cash_lines) == 1
            and len(self.counterpart_lines) == 1
        ):
            cash_line, _ = self.cash_lines[0]
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
    """Load complete cash-touching entries belonging solely to the tenant (#2583)."""
    rows = (
        await db.execute(_cash_event_rows_statement(user_id, end_date=end_date, cash_account_ids=cash_account_ids))
    ).all()
    missing_account_ids = {row.account_id for row in rows}.difference(account_by_id)
    if missing_account_ids:
        added = await db.scalars(select(Account).where(Account.user_id == user_id, Account.id.in_(missing_account_ids)))
        account_by_id.update((account.id, account) for account in added)
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
        group[1].append(
            (
                _LineFacts(
                    id=row.line_id,
                    direction=row.direction,
                    amount=row.amount,
                    currency=row.currency,
                    event_type=row.event_type,
                    economic_category=row.economic_category,
                ),
                account_by_id[row.account_id],
            )
        )

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
    """Build the complete-entry query so tenant predicates remain directly provable."""
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
            select(cash_line.id).where(
                cash_line.journal_entry_id == JournalEntry.id,
                cash_line.account_id.in_(cash_account_ids),
            )
        )
        stmt = stmt.where(has_cash_leg)
    return stmt


@dataclass(frozen=True, slots=True)
class _LineRecord:
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
    """Return the requested cash-flow period (defaults to year-to-date of end_date)."""
    resolved_end_date = end_date or date.today()
    return start_date or date(resolved_end_date.year, 1, 1), resolved_end_date


def cash_flow_line_id(item: Mapping[str, Any]) -> str:
    """Return deterministic statement line ID for an activity item (#2583)."""
    category = str(item["category"])
    key = "\x1f".join((category, str(item.get("description") or ""), str(item.get("account_id") or "")))
    return f"{category.lower()}-{text_digest(key)[:16]}"


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
    return (
        await _build_cash_flow(
            db, user_id, start_date=start_date, end_date=end_date, currency=currency, cash_account_ids=cash_account_ids
        )
    ).document


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
    """Return lineage records of one statement line in document order, or None for unknown line (#2583)."""
    build = await _build_cash_flow(
        db, user_id, start_date=start_date, end_date=end_date, currency=currency, cash_account_ids=cash_account_ids
    )
    events = [record.event() for record in build.records if record.line_id == line_id]
    return None if not events and line_id not in _FIXED_LINE_IDS else events


def cash_flow_preview(document: Mapping[str, Any]) -> dict[str, object]:
    """Project a cash-flow document to its bounded preview (#2583)."""
    preview: dict[str, object] = {
        key: value for key, value in document.items() if key not in (*_SECTIONS, "event_lineage")
    }
    for section in _SECTIONS:
        lines: dict[str, dict[str, Any]] = {}
        for item in document.get(section) or ():
            line_id = cash_flow_line_id(item)
            amount = Decimal(str(item["amount"]))
            if (line := lines.get(line_id)) is None:
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
    """Return effective cash account IDs (including system Processing) and exact selected IDs."""
    account_ids = {account.id for account in accounts}
    exact_selected_ids: set[UUID] = set()
    if cash_account_ids is None:
        keywords = ("cash", "bank", "checking", "savings", "money market", "petty cash")
        selected_ids = {
            account.id
            for account in accounts
            if account.type == AccountType.ASSET
            and (account.code == _AUTO_BANK_ACCOUNT_CODE or any(kw in account.name.lower() for kw in keywords))
        }
    else:
        selected_ids = {account_id for account_id in cash_account_ids if account_id in account_ids}
        exact_selected_ids = set(selected_ids)

    selected_ids.update(
        account.id
        for account in accounts
        if account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET
    )
    return frozenset(selected_ids), frozenset(exact_selected_ids)


async def cash_opening_positions(
    db: AsyncSession, user_id: UUID, *, as_of: date, cash_account_ids: frozenset[UUID]
) -> tuple[Any, ...]:
    """Return opening positions of cash accounts effective on or before as_of."""
    from src.ledger import list_opening_positions

    return tuple(
        position
        for position in await list_opening_positions(db, user_id=user_id, as_of=as_of)
        if position.account_id in cash_account_ids
    )


def opening_coverage_start(opening_positions: Iterable[Any]) -> date | None:
    """Return the latest effective date among opening positions (#2646)."""
    return max((position.effective_date for position in opening_positions), default=None)


@dataclass(frozen=True, slots=True)
class CashCoverage:
    start: date | None
    limiting_account_names: tuple[str, ...]
    latest_statement_end: date | None = None


async def cash_coverage(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of: date,
    cash_account_id_sets: Sequence[frozenset[UUID] | None],
    latest_statement_end: date | None = None,
) -> CashCoverage:
    """Return coverage start over the union of cash accounts selected by each ID set."""
    accounts = await _load_accounts(db, user_id)
    cash_ids: set[UUID] = set()
    for ids in cash_account_id_sets:
        cash_ids.update(_select_cash_account_ids(accounts, ids)[0])
    positions = await cash_opening_positions(db, user_id, as_of=as_of, cash_account_ids=frozenset(cash_ids))
    start = opening_coverage_start(positions)
    names = {account.id: account.name for account in accounts}
    limiting = sorted({names[p.account_id] for p in positions if p.effective_date == start and p.account_id in names})
    return CashCoverage(start=start, limiting_account_names=tuple(limiting), latest_statement_end=latest_statement_end)


async def _build_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None,
    cash_account_ids: frozenset[UUID] | None,
) -> _CashFlowBuild:
    """Build the cash-flow document and its line records in one pass over cash events."""
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")
    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))

    accounts = await _load_accounts(db, user_id)
    account_by_id = {account.id: account for account in accounts}
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
            elif event.entry.entry_date <= end_date:
                fx_needs.add((source, target_currency, event.entry.entry_date, None, None))

    fx_rates = await _prefetch_fx_rates(db, list(fx_needs), "cash flow", prefetched_cls=PrefetchedFxRates)

    def converted_delta(line: _LineFacts, rate_date: date) -> Decimal:
        source = line.currency.upper()
        rate = Decimal("1") if source == target_currency else fx_rates.get_rate(source, target_currency, rate_date)
        if rate is None:
            raise ReportError(f"No FX rate available for {source}/{target_currency} on {rate_date}")
        return _cash_delta(line) * rate

    beginning_cash = Decimal("0")
    ending_cash = Decimal("0")
    activity_items: dict[CashActivity, list[dict[str, object]]] = {
        "Operating": [],
        "Investing": [],
        "Financing": [],
    }
    event_lineage: list[dict[str, object]] = []
    records: list[_LineRecord] = []
    unclassified_cash = Decimal("0")
    opening_stock_adjustment = Decimal("0")
    proof_reasons: set[str] = set()
    if cash_account_ids is None:
        proof_reasons.add("cash_identity_compatibility_fallback")
    elif not exact_selected_ids:
        proof_reasons.add("cash_identity_missing")

    if any(position.state != "authoritative" or position.decision is None for position in opening_positions):
        proof_reasons.add("opening_position_unproven")
    coverage_start = opening_coverage_start(opening_positions)
    if coverage_start is not None and coverage_start > start_date:
        proof_reasons.add("opening_coverage_starts_after_period")

    for event in events:
        beginning_movement = (
            sum((converted_delta(line, start_date) for line, _ in event.cash_lines), Decimal("0"))
            if event.entry.entry_date < start_date
            else Decimal("0")
        )
        beginning_cash += beginning_movement
        ending_movement = sum((converted_delta(line, end_date) for line, _ in event.cash_lines), Decimal("0"))
        ending_cash += ending_movement
        if not event.has_authoritative_decision and (beginning_movement or ending_movement):
            proof_reasons.add("cash_event_decision_unproven")
        if not (start_date <= event.entry.entry_date <= end_date):
            continue

        opening_lines = tuple(
            (line, account)
            for line, account in event.cash_lines
            if (
                (position := proven_openings.get((event.entry.id, account.id))) is not None
                and position.effective_date == event.entry.entry_date
                and position.currency == line.currency
                and position.amount == _cash_delta(line)
            )
            or (
                line.event_type == account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE
                and event.entry.source_type == JournalEntrySourceType.SYSTEM
                and event.has_authoritative_decision
            )
        )
        if opening_lines:
            opening_amount = sum(
                (converted_delta(line, event.entry.entry_date) for line, _ in opening_lines), Decimal("0")
            )
            if event.entry.entry_date == start_date:
                beginning_cash += opening_amount
            else:
                opening_stock_adjustment += opening_amount
            lineage = _event_lineage(event, activity=None, reason_code="opening_stock")
            event_lineage.append(lineage)
            records.append(_line_record(event, CASH_FLOW_OPENING_STOCK_LINE_ID, opening_amount, lineage))

        opening_line_ids = {line.id for line, _ in opening_lines}
        movement = sum(
            (
                converted_delta(line, event.entry.entry_date)
                for line, _ in event.cash_lines
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
        names_label = ", ".join(sorted(account.name for account in counterpart_accounts.values()))
        item = {
            "category": activity,
            "subcategory": names_label,
            "amount": _quantize_money(movement),
            "description": f"{'Inflow' if movement > 0 else 'Outflow'} - {names_label}",
            "account_id": next(iter(counterpart_accounts)) if len(counterpart_accounts) == 1 else None,
        }
        lineage = _event_lineage(event, activity=activity, reason_code=None)
        event_lineage.append(lineage)
        records.append(_line_record(event, cash_flow_line_id(item), movement, lineage))
        activity_items[activity].append(item)

    operating_items = activity_items["Operating"]
    investing_items = activity_items["Investing"]
    financing_items = activity_items["Financing"]
    for items in (operating_items, investing_items, financing_items):
        items.sort(key=lambda item: abs(Decimal(str(item["amount"]))), reverse=True)

    operating_total = _line_total(operating_items)
    investing_total = _line_total(investing_items)
    financing_total = _line_total(financing_items)
    calculated_fx_effect = Decimal("0")
    if fx_needs:
        for event in events:
            ref_date = start_date if event.entry.entry_date < start_date else event.entry.entry_date
            if ref_date <= end_date:
                for line, _ in event.cash_lines:
                    if line.currency.upper() != target_currency:
                        calculated_fx_effect += converted_delta(line, end_date) - converted_delta(line, ref_date)
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
    if fx_needs and bridge.discrepancy != Decimal("0.00"):
        from src.reporting.base.balance_sheet_calculator import absorb_translation_rounding

        adjusted_fx_effect = absorb_translation_rounding(
            cta_adjustment=fx_effect,
            residual=bridge.discrepancy,
            rounded_figure_count=len(operating_items) + len(investing_items) + len(financing_items) + 4,
        )
        if adjusted_fx_effect != fx_effect:
            bridge = calculate_cash_flow_bridge(
                beginning_cash=beginning_cash,
                ending_cash=ending_cash,
                operating_total=operating_total,
                investing_total=investing_total,
                financing_total=financing_total,
                unclassified_cash=unclassified_cash,
                opening_stock_adjustment=opening_stock_adjustment,
                fx_effect=adjusted_fx_effect,
            )

    return _CashFlowBuild(
        document={
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
        },
        records=tuple(records),
    )
