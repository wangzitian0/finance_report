"""Resolve posted journal facts through their current DecisionAnchor."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import TraceDecisionRef, TraceScope, VersionedTraceRef, current_authoritative_trace_decisions
from src.ledger.base.contribution import JournalLineContribution, ResolvedJournalContribution
from src.ledger.orm.account import Account
from src.ledger.orm.journal import (
    JournalEntry,
    JournalLine,
    active_journal_entry_filter,
)


async def list_journal_contributions(
    db: AsyncSession,
    *,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> tuple[ResolvedJournalContribution, ...]:
    """Publish only ledger-owned facts with explicit current-authority state.

    The query reads the columns of the contribution, not ORM entities. The current-authority
    read covers only the decision anchors of the selected entries (#2602).
    """
    rows = (
        await db.execute(
            select(
                JournalEntry.id,
                JournalEntry.entry_date,
                JournalEntry.decision_anchor_id,
                JournalLine.id,
                Account.id,
                Account.type,
                JournalLine.direction,
                JournalLine.amount,
                JournalLine.currency,
            )
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .join(Account, Account.id == JournalLine.account_id)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.entry_date >= start_date)
            .where(JournalEntry.entry_date <= end_date)
            .where(active_journal_entry_filter(JournalEntry))
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
        )
    ).all()
    authorities = await current_authoritative_trace_decisions(
        db,
        TraceScope.tenant(user_id),
        {anchor_id for _entry_id, _entry_date, anchor_id, *_line in rows if anchor_id is not None},
    )
    grouped: dict[UUID, tuple[date, TraceDecisionRef | None, list[JournalLineContribution]]] = {}
    for entry_id, entry_date, anchor_id, line_id, account_id, account_type, direction, amount, currency in rows:
        current = grouped.get(entry_id)
        if current is None:
            evidence = authorities.get(anchor_id) if anchor_id is not None else None
            decision = (
                TraceDecisionRef(
                    decision_id=evidence.decision_id,
                    target=VersionedTraceRef(evidence.target_kind, evidence.target_id, evidence.target_version),
                    assertion=VersionedTraceRef(
                        evidence.assertion_kind, evidence.assertion_id, evidence.assertion_version
                    ),
                )
                if evidence is not None
                else None
            )
            current = (entry_date, decision, [])
            grouped[entry_id] = current
        current[2].append(
            JournalLineContribution(
                line_id=line_id,
                account_id=account_id,
                account_type=account_type,
                direction=direction,
                amount=amount,
                currency=currency,
            )
        )
    return tuple(
        ResolvedJournalContribution(
            entry_id=entry_id,
            entry_date=entry_date,
            lines=tuple(lines),
            state="authoritative" if decision is not None else "unproven",
            reason_code=None if decision is not None else "missing_current_decision_anchor",
            decision=decision,
        )
        for entry_id, (entry_date, decision, lines) in grouped.items()
    )
