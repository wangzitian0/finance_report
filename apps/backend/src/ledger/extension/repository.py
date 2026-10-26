"""Private journal persistence implementation for the anchored command boundary.

Only ``anchored_posting`` may create a new financial fact through this module's
private ``_create_anchored_journal_entry`` sink. Posting and voiding remain published
lifecycle verbs; voiding creates its reversal through the system anchored command.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import src.config
from src.audit import JournalEntrySourceType, normalize_source_type
from src.audit.money import Currency
from src.ledger.base.decision_anchor import DecisionAnchor
from src.ledger.base.memo import fit_journal_memo
from src.ledger.base.processing import PROCESSING_ACCOUNT_CODE
from src.ledger.base.validators import (
    JournalEntryPostingProtocol,
    JournalLinePostingProtocol,
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
)
from src.ledger.orm.account import Account
from src.ledger.orm.journal import (
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    active_journal_entry_filter,
)

__all__ = [
    "active_journal_entry_filter",
    "post_journal_entries",
    "post_journal_entry",
    "validate_line_account_ownership",
    "void_journal_entry",
]


async def _set_transaction_base_currency(db: AsyncSession, base_currency: str | None) -> str:
    """Keep PostgreSQL's deferred ledger invariant aligned with Python validation."""
    normalized = Currency.of(base_currency or src.config.settings.base_currency).code
    await db.execute(
        text("SELECT set_config('finance_report.base_currency', :base_currency, true)"),
        {"base_currency": normalized},
    )
    return normalized


def _historical_reversal_base_currency(
    lines: list[JournalLine],
    *,
    fallback_base_currency: str | None,
) -> str:
    """Recover the base currency under which the posted lines were validated."""
    fallback = Currency.of(fallback_base_currency or src.config.settings.base_currency).code
    fx_free_currencies = {Currency.of(line.currency or fallback).code for line in lines if line.fx_rate is None}
    if not fx_free_currencies:
        raise ValidationError("Cannot determine historical base currency: all lines have FX rates")
    if len(fx_free_currencies) > 1:
        currencies = ", ".join(sorted(fx_free_currencies))
        raise ValidationError(f"Cannot determine historical base currency from FX-free lines: {currencies}")

    historical_base = next(iter(fx_free_currencies), fallback)
    validate_journal_balance(cast("list[JournalLinePostingProtocol]", lines), base_currency=historical_base)
    validate_fx_rates(cast("list[JournalLinePostingProtocol]", lines), base_currency=historical_base)
    return historical_base


async def validate_line_account_ownership(
    db: AsyncSession,
    user_id: UUID,
    account_ids: set[UUID],
) -> dict[UUID, Account]:
    """Load and validate that every line account belongs to the current user."""
    if not account_ids:
        return {}

    result = await db.execute(select(Account).where(Account.id.in_(account_ids)))
    accounts = {account.id: account for account in result.scalars().all()}

    missing = account_ids - set(accounts)
    if missing:
        raise ValidationError(f"Account {next(iter(missing))} not found")

    if any(account.user_id != user_id for account in accounts.values()):
        raise ValidationError("Account does not belong to user")

    return accounts


@dataclass(frozen=True, slots=True)
class AnchoredEntryDraft:
    """The persistence-neutral fields of one anchored journal entry before it exists."""

    entry_date: date
    memo: str
    lines_data: list[dict]
    source_type: JournalEntrySourceType
    source_id: UUID | None
    decision_anchor: DecisionAnchor


async def _create_anchored_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    *,
    base_currency: str | None = None,
    decision_anchor: DecisionAnchor,
) -> JournalEntry:
    base_currency = await _set_transaction_base_currency(db, base_currency)
    accounts = await validate_line_account_ownership(
        db,
        user_id,
        {line_data["account_id"] for line_data in lines_data},
    )
    entry, lines = _build_anchored_journal_entry(
        user_id,
        AnchoredEntryDraft(
            entry_date=entry_date,
            memo=memo,
            lines_data=lines_data,
            source_type=source_type,
            source_id=source_id,
            decision_anchor=decision_anchor,
        ),
        accounts=accounts,
        base_currency=base_currency,
    )
    db.add(entry)
    db.add_all(lines)
    await db.flush()
    return entry


async def _create_anchored_journal_entries(
    db: AsyncSession,
    user_id: UUID,
    drafts: Sequence[AnchoredEntryDraft],
    *,
    base_currency: str | None = None,
) -> list[JournalEntry]:
    """Create many draft entries with one account read and one flush.

    Each entry equals the one that ``_create_anchored_journal_entry`` creates for the same draft. No
    entry is added to the session before every draft has passed its checks.
    """
    if not drafts:
        return []
    base_currency = await _set_transaction_base_currency(db, base_currency)
    accounts = await validate_line_account_ownership(
        db,
        user_id,
        {line_data["account_id"] for draft in drafts for line_data in draft.lines_data},
    )
    built = [
        _build_anchored_journal_entry(user_id, draft, accounts=accounts, base_currency=base_currency)
        for draft in drafts
    ]
    db.add_all([entry for entry, _lines in built])
    db.add_all([line for _entry, lines in built for line in lines])
    await db.flush()
    return [entry for entry, _lines in built]


def _build_anchored_journal_entry(
    user_id: UUID,
    draft: AnchoredEntryDraft,
    *,
    accounts: dict[UUID, Account],
    base_currency: str,
) -> tuple[JournalEntry, list[JournalLine]]:
    """Check one draft against the ledger rules and build its entry and lines. Nothing is persisted."""
    entry_date, memo, lines_data = draft.entry_date, draft.memo, draft.lines_data
    source_type, source_id, decision_anchor = draft.source_type, draft.source_id, draft.decision_anchor
    normalized_source = normalize_source_type(source_type)
    # ``accounts`` may hold the accounts of other drafts. The rules apply to the accounts of this draft.
    draft_accounts = {line_data["account_id"]: accounts[line_data["account_id"]] for line_data in lines_data}
    if normalized_source != JournalEntrySourceType.SYSTEM:
        for account in draft_accounts.values():
            if account.code == PROCESSING_ACCOUNT_CODE:
                raise ValidationError(
                    f"Processing account (code {PROCESSING_ACCOUNT_CODE}) is reserved for internal transfer reconciliation and cannot be used in {normalized_source.value} journal entries"
                )

    entry_pk = uuid4()
    entry = JournalEntry(
        id=entry_pk,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=normalized_source,
        source_id=source_id,
        decision_anchor_id=decision_anchor.decision_id,
        decision_authority_state=JournalEntryAuthorityState.ANCHORED,
        base_currency=base_currency,
    )

    lines: list[JournalLine] = []
    default_currency = base_currency
    for line_no, line_data in enumerate(lines_data):
        account_id = line_data["account_id"]
        line = JournalLine(
            id=uuid4(),
            journal_entry_id=entry_pk,
            line_no=line_no,
            account_id=account_id,
            direction=line_data["direction"],
            amount=line_data["amount"],
            currency=(line_data.get("currency") or default_currency).upper(),
            fx_rate=line_data.get("fx_rate"),
            event_type=line_data.get("event_type"),
            tags=line_data.get("tags"),
        )
        account_obj = accounts.get(account_id)
        if account_obj is not None:
            line.account = account_obj
        lines.append(line)

    validate_journal_balance(cast("list[JournalLinePostingProtocol]", lines), base_currency=base_currency)
    validate_fx_rates(cast("list[JournalLinePostingProtocol]", lines), base_currency=base_currency)

    entry.lines = lines
    return entry, lines


async def _load_entry_with_lines(db: AsyncSession, entry_id: UUID) -> JournalEntry | None:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
    )
    return result.scalar_one_or_none()


async def post_journal_entry(
    db: AsyncSession,
    entry_id: UUID | JournalEntry,
    user_id: UUID,
    *,
    base_currency: str | None = None,
) -> JournalEntry:
    """
    Post a journal entry from draft to posted status.

    Args:
        db: Database session
        entry_id: Journal entry UUID or existing JournalEntry instance
        user_id: User UUID for security check
        base_currency: Used only for a draft written before revision 0067. A newer
            draft is validated under the base currency stored at its creation (#2539).

    Returns:
        Posted journal entry

    Raises:
        ValidationError: If entry cannot be posted
    """
    entry: JournalEntry | None
    if isinstance(entry_id, JournalEntry):
        entry = entry_id
        if not entry.lines:
            entry = await _load_entry_with_lines(db, entry.id)
    else:
        entry = await _load_entry_with_lines(db, entry_id)

    if not entry:
        raise ValidationError(f"Journal entry {entry_id} not found")
    if entry.user_id != user_id:
        raise ValidationError("Journal entry does not belong to user")
    if entry.status != JournalEntryStatus.DRAFT:
        raise ValidationError(f"Can only post draft entries, current status: {entry.status}")

    base_currency = await _set_transaction_base_currency(db, entry.stored_base_currency(base_currency))

    validate_journal_posting_invariants(cast("JournalEntryPostingProtocol", entry), base_currency=base_currency)

    from src.ledger.extension.anchored_posting import validate_manual_journal_entry_for_post

    await validate_manual_journal_entry_for_post(db, user_id=user_id, entry=entry, base_currency=base_currency)

    entry.status = JournalEntryStatus.POSTED
    entry.updated_at = datetime.now(UTC)
    await db.flush()

    return entry


async def post_journal_entries(
    db: AsyncSession,
    entries: Sequence[JournalEntry],
    user_id: UUID,
    *,
    base_currency: str | None = None,
) -> list[JournalEntry]:
    """Post many draft entries with one flush.

    Each entry gets the checks and the result of ``post_journal_entry``. An entry whose lines are not
    loaded is read again with its lines, as ``post_journal_entry`` does.
    """
    from src.ledger.extension.anchored_posting import validate_manual_journal_entry_for_post

    transaction_base: str | None = None
    for loaded_entry in entries:
        entry = loaded_entry if loaded_entry.lines else await _load_entry_with_lines(db, loaded_entry.id)
        if entry is None:
            raise ValidationError(f"Journal entry {loaded_entry.id} not found")
        if entry.user_id != user_id:
            raise ValidationError("Journal entry does not belong to user")
        if entry.status != JournalEntryStatus.DRAFT:
            raise ValidationError(f"Can only post draft entries, current status: {entry.status}")
        entry_base = entry.stored_base_currency(base_currency)
        if entry_base != transaction_base:
            transaction_base = await _set_transaction_base_currency(db, entry_base)
        validate_journal_posting_invariants(cast("JournalEntryPostingProtocol", entry), base_currency=entry_base)
        await validate_manual_journal_entry_for_post(db, user_id=user_id, entry=entry, base_currency=entry_base)
        entry.status = JournalEntryStatus.POSTED
        entry.updated_at = datetime.now(UTC)
    await db.flush()
    return list(entries)


async def void_journal_entry(
    db: AsyncSession,
    entry_id: UUID,
    reason: str,
    user_id: UUID,
    *,
    base_currency: str | None = None,
    allow_reconciled: bool = False,
) -> JournalEntry:
    """
    Void a posted journal entry by creating a reversal entry.

    Args:
        db: Database session
        entry_id: Journal entry UUID to void
        reason: Reason for voiding
        user_id: User UUID for security check

    Returns:
        Reversal journal entry

    Raises:
        ValidationError: If entry cannot be voided
    """
    # Get original entry
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
    entry = result.scalar_one_or_none()

    if not entry:
        raise ValidationError(f"Journal entry {entry_id} not found")
    if entry.user_id != user_id:
        raise ValidationError("Journal entry does not belong to user")
    allowed_statuses = (
        (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED) if allow_reconciled else (JournalEntryStatus.POSTED,)
    )
    if entry.status not in allowed_statuses:
        raise ValidationError("Can only void posted entries")

    # Load lines
    await db.refresh(entry, ["lines"])
    historical_base = _historical_reversal_base_currency(
        entry.lines,
        fallback_base_currency=base_currency,
    )
    await _set_transaction_base_currency(db, historical_base)

    # Keep a correction on the same anchored command boundary as every other
    # new financial fact. The original entry id is the immutable source identity.
    from src.ledger.extension.anchored_posting import submit_system_journal_entry

    reversal_entry = await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry.entry_date,
        memo=fit_journal_memo(f"VOID: {entry.memo}"),
        lines_data=[
            {
                "account_id": line.account_id,
                "direction": Direction.CREDIT if line.direction == Direction.DEBIT else Direction.DEBIT,
                "amount": line.amount,
                "currency": line.currency,
                "fx_rate": line.fx_rate,
                "event_type": line.event_type,
                "tags": line.tags,
            }
            for line in entry.lines
        ],
        base_currency=historical_base,
        operation="void-reversal",
        source_id=entry.id,
    )

    # Update original entry
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = reason
    entry.void_reversal_entry_id = reversal_entry.id
    entry.updated_at = datetime.now(UTC)

    await db.flush()
    # The lifecycle service returns a complete aggregate. Callers may commit
    # before inspecting reversal lines, where async lazy loading is invalid.
    await db.refresh(reversal_entry, ["lines"])
    return reversal_entry
