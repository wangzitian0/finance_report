"""Processing-account in-transit transfer summary and pending queue queries."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import to_money
from src.ledger import (
    find_processing_account,
    find_transfer_pairs,
    get_processing_balance,
    get_unpaired_transfers,
    list_processing_transfer_legs,
)
from src.reconciliation.base.processing_summary import ProcessingTransferSummary
from src.reconciliation.extension.scoring import score_description
from src.reconciliation.extension.transfer_pairs import paired_transfer_entry_ids


async def _paired_transfer_scope(
    db: AsyncSession,
    user_id: UUID,
    *,
    default_currency: str,
) -> tuple[str, set[UUID]]:
    processing_account = await find_processing_account(db, user_id)
    currency = processing_account.currency if processing_account else default_currency
    persisted_paired_ids = await paired_transfer_entry_ids(db, user_id=user_id)
    pairs = await find_transfer_pairs(
        db,
        user_id,
        currency=currency,
        description_scorer=score_description,
        exclude_entry_ids=persisted_paired_ids,
    )
    paired_ids = {pair.out_entry.id for pair in pairs} | {pair.in_entry.id for pair in pairs} | persisted_paired_ids
    return currency, paired_ids


async def get_processing_transfer_summary(
    db: AsyncSession,
    user_id: UUID,
    *,
    default_currency: str,
) -> ProcessingTransferSummary:
    """Return unpaired in-transit transfer summary for the Processing virtual account."""
    currency, paired_ids = await _paired_transfer_scope(db, user_id, default_currency=default_currency)
    unpaired = [
        item
        for item in await get_unpaired_transfers(db, user_id, currency=currency)
        if item["entry_id"] not in paired_ids
    ]
    debits = sum((item["amount"] for item in unpaired if item["direction"] == "OUT"), start=Decimal("0"))
    credits = sum((item["amount"] for item in unpaired if item["direction"] == "IN"), start=Decimal("0"))
    return ProcessingTransferSummary(
        pending_count=len(unpaired),
        pending_total=to_money(abs(debits - credits)),
        current_balance=to_money(await get_processing_balance(db, user_id, currency=currency)),
        currency=currency,
        oldest_pending_date=min((item["date"] for item in unpaired), default=None),
    )


async def list_pending_processing_transfers(
    db: AsyncSession,
    user_id: UUID,
    *,
    default_currency: str,
) -> list[dict[str, Any]]:
    """Return pending unpaired transfer legs in the Processing pipeline."""
    currency, paired_ids = await _paired_transfer_scope(db, user_id, default_currency=default_currency)
    return [
        leg
        for leg in await list_processing_transfer_legs(db, user_id, currency=currency)
        if leg["entry_id"] not in paired_ids
    ]
