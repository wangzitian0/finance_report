"""Resolve posted journal facts through their current DecisionAnchor."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import TraceDecisionRef, TraceScope, VersionedTraceRef, current_authoritative_trace_decision_projection
from src.ledger.base.contribution import JournalLineContribution, ResolvedJournalContribution
from src.ledger.orm.account import Account
from src.ledger.orm.journal import JournalEntry, JournalEntryStatus, JournalLine


async def list_journal_contributions(
    db: AsyncSession,
    *,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> tuple[ResolvedJournalContribution, ...]:
    """Publish only ledger-owned facts with explicit current-authority state."""
    decisions = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery(
        "ledger_contribution_decisions"
    )
    rows = await db.execute(
        select(
            JournalEntry,
            JournalLine,
            Account,
            decisions.c.decision_id,
            decisions.c.target_kind,
            decisions.c.target_id,
            decisions.c.target_version,
            decisions.c.assertion_kind,
            decisions.c.assertion_id,
            decisions.c.assertion_version,
        )
        .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(decisions, decisions.c.decision_id == JournalEntry.decision_anchor_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= end_date)
        .where(JournalEntry.status.in_((JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)))
        .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
    )
    grouped: dict[UUID, tuple[JournalEntry, TraceDecisionRef | None, list[JournalLineContribution]]] = {}
    for (
        entry,
        line,
        account,
        decision_id,
        target_kind,
        target_id,
        target_version,
        assertion_kind,
        assertion_id,
        assertion_version,
    ) in rows:
        decision = (
            TraceDecisionRef(
                decision_id=decision_id,
                target=VersionedTraceRef(target_kind, target_id, target_version),
                assertion=VersionedTraceRef(assertion_kind, assertion_id, assertion_version),
            )
            if decision_id is not None
            else None
        )
        current = grouped.get(entry.id)
        if current is None:
            current = (entry, decision, [])
            grouped[entry.id] = current
        current[2].append(
            JournalLineContribution(
                line_id=line.id,
                account_id=account.id,
                account_type=account.type,
                direction=line.direction,
                amount=line.amount,
                currency=line.currency,
            )
        )
    return tuple(
        ResolvedJournalContribution(
            entry_id=entry.id,
            entry_date=entry.entry_date,
            lines=tuple(lines),
            state="authoritative" if decision is not None else "unproven",
            reason_code=None if decision is not None else "missing_current_decision_anchor",
            decision=decision,
        )
        for entry, decision, lines in grouped.values()
    )
