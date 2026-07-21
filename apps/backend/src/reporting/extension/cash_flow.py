"""Authoritative cash-touch event projection and cash-flow generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
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
from src.observability import ErrorIds, get_logger
from src.reporting.extension import fx_gateway
from src.reporting.extension._core import _REPORT_STATUSES, _line_total
from src.reporting.extension.reporting_calc import ReportError, _normalize_currency, _quantize_money

logger = get_logger(__name__)
_PROCESSING_ACCOUNT = ProcessingAccount()
_AUTO_BANK_ACCOUNT_CODE = "AUTO-BANK"

CashActivity = Literal["Operating", "Investing", "Financing"]
_EXPLICIT_EVENT_ACTIVITIES: dict[str, CashActivity] = {
    "investment_buy": "Investing",
    "investment_sell": "Investing",
}
_EXPLICIT_EVENT_COMPANIONS: dict[str, frozenset[str]] = {
    "investment_buy": frozenset({"investment_buy"}),
    "investment_sell": frozenset({"investment_sell", "investment_realized_pnl"}),
}


@dataclass(frozen=True, slots=True)
class _CashEvent:
    """One tenant-safe journal event that touches an authoritative cash identity."""

    entry: JournalEntry
    cash_lines: tuple[tuple[JournalLine, Account], ...]
    counterpart_lines: tuple[tuple[JournalLine, Account], ...]

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

        counterpart_types = {account.type for _line, account in self.counterpart_lines}
        if counterpart_types and counterpart_types <= {AccountType.INCOME, AccountType.EXPENSE}:
            # P&L accounts are unambiguous operating evidence. Balance-sheet
            # account types cannot distinguish AR/AP settlement from investing
            # or financing, so unsupported events deliberately remain unproven.
            return "Operating"
        return None


def _cash_delta(line: JournalLine) -> Decimal:
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
) -> tuple[_CashEvent, ...]:
    """Load complete entries only when both the entry and every account belong to the tenant."""
    stmt = _cash_event_rows_statement(user_id, end_date=end_date)
    grouped: dict[UUID, tuple[JournalEntry, list[tuple[JournalLine, Account]]]] = {}
    for line, account, entry in (await db.execute(stmt)).all():
        grouped.setdefault(entry.id, (entry, []))[1].append((line, account))

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
) -> Select[tuple[JournalLine, Account, JournalEntry]]:
    """Build the complete-entry query so tenant predicates remain directly provable."""
    foreign_line = aliased(JournalLine)
    foreign_account = aliased(Account)
    voided_entry = aliased(JournalEntry)
    has_foreign_account = exists(
        select(foreign_line.id)
        .join(foreign_account, foreign_line.account_id == foreign_account.id)
        .where(foreign_line.journal_entry_id == JournalEntry.id)
        .where(foreign_account.user_id != user_id)
    )
    return (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalEntry.user_id == user_id)
        .where(Account.user_id == user_id)
        .where(~has_foreign_account)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(~exists(select(voided_entry.id).where(voided_entry.void_reversal_entry_id == JournalEntry.id)))
        .where(JournalEntry.entry_date <= end_date)
        .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
    )


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
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")
    target_currency = _normalize_currency(currency)

    accounts = list(
        (await db.execute(select(Account).where(Account.user_id == user_id).where(Account.is_active.is_(True))))
        .scalars()
        .all()
    )
    account_by_id = {account.id: account for account in accounts}
    explicit_cash_identity = cash_account_ids is not None
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
        selected_ids = {account_id for account_id in cash_account_ids if account_id in account_by_id}
        exact_selected_ids = set(selected_ids)

    # Processing is a ledger-defined cash equivalent: including it makes both legs
    # of an in-transit internal transfer neutral without name inference.
    selected_ids.update(
        account.id
        for account in accounts
        if account.is_system and account.code == _PROCESSING_ACCOUNT.code and account.type == AccountType.ASSET
    )
    effective_cash_ids = frozenset(selected_ids)
    events = await _load_cash_events(db, user_id, end_date=end_date, cash_account_ids=effective_cash_ids)

    fx_needs: set[tuple[str, str, date, date | None, date | None]] = set()
    for event in events:
        for line, _account in event.cash_lines:
            source = line.currency.upper()
            if source == target_currency:
                continue
            fx_needs.add((source, target_currency, start_date, None, None))
            fx_needs.add((source, target_currency, end_date, None, None))
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

    def converted_delta(line: JournalLine, rate_date: date) -> Decimal:
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
    unclassified_cash = Decimal("0")
    proof_reasons: set[str] = set()
    if not explicit_cash_identity:
        proof_reasons.add("cash_identity_compatibility_fallback")
    elif not exact_selected_ids:
        proof_reasons.add("cash_identity_missing")

    for event in events:
        if not event.has_authoritative_decision:
            proof_reasons.add("cash_event_decision_unproven")
        if event.entry.entry_date < start_date:
            beginning_cash += sum(
                (converted_delta(line, start_date) for line, _account in event.cash_lines), Decimal("0")
            )
        ending_cash += sum((converted_delta(line, end_date) for line, _account in event.cash_lines), Decimal("0"))
        if not (start_date <= event.entry.entry_date <= end_date):
            continue

        movement = sum(
            (converted_delta(line, event.entry.entry_date) for line, _account in event.cash_lines), Decimal("0")
        )
        if movement == Decimal("0"):
            continue
        activity = event.activity
        if activity is None:
            unclassified_cash += movement
            proof_reasons.add("cash_event_classification_ambiguous")
            event_lineage.append(
                _event_lineage(
                    event,
                    activity=None,
                    reason_code="cash_event_classification_ambiguous",
                )
            )
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
        event_lineage.append(_event_lineage(event, activity=activity, reason_code=None))
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
    classified_activity = operating_total + investing_total + financing_total
    net_cash_flow = _quantize_money(ending_cash - beginning_cash)
    fx_effect = _quantize_money(net_cash_flow - classified_activity - unclassified_cash)
    bridge_total = _quantize_money(classified_activity + unclassified_cash + fx_effect)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "operating": operating_items,
        "investing": investing_items,
        "financing": financing_items,
        "summary": {
            "operating_activities": operating_total,
            "investing_activities": investing_total,
            "financing_activities": financing_total,
            "net_cash_flow": net_cash_flow,
            "beginning_cash": _quantize_money(beginning_cash),
            "ending_cash": _quantize_money(ending_cash),
        },
        "cash_bridge": {
            "classified_activity": _quantize_money(classified_activity),
            "unclassified_cash": _quantize_money(unclassified_cash),
            "fx_effect": fx_effect,
            "cash_delta": net_cash_flow,
            "reconciles": bridge_total == net_cash_flow,
        },
        "event_lineage": event_lineage,
        "proof_state": "proven" if not proof_reasons else "unproven",
        "proof_reasons": sorted(proof_reasons),
    }
