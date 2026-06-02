"""Stage 1 posting guard contract.

This module is the single place that decides whether a reviewed statement may
create posted journal entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Text, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, BankStatement, BankStatementTransaction
from src.models.consistency_check import CheckStatus, ConsistencyCheck

ACCOUNT_MAPPING_REQUIRED_DETAIL = "Account mapping required before posting. Confirm the target account before posting."
INVALID_ACCOUNT_MAPPING_DETAIL = "Statement account mapping is invalid. Confirm the target account before posting."
UNRESOLVED_CHECKS_DETAIL = "Cannot approve statement while there are unresolved consistency checks for this statement."


@dataclass(frozen=True)
class Stage1PostingContext:
    """Validated data needed to post Stage 1 statement transactions."""

    statement: BankStatement
    transactions: list[BankStatementTransaction]


async def require_statement_posting_account(
    db: AsyncSession,
    *,
    statement: BankStatement,
    user_id: UUID,
) -> Account:
    """Return the explicit statement account, or fail before any posting."""
    if not statement.account_id:
        raise ValueError(ACCOUNT_MAPPING_REQUIRED_DETAIL)

    account_result = await db.execute(
        select(Account).where(Account.id == statement.account_id).where(Account.user_id == user_id)
    )
    account = account_result.scalar_one_or_none()
    if account:
        return account
    raise ValueError(INVALID_ACCOUNT_MAPPING_DETAIL)


async def assert_no_unresolved_checks_for_statement(
    db: AsyncSession,
    *,
    user_id: UUID,
    transactions: list[BankStatementTransaction],
) -> None:
    """Fail Stage 1 approval while statement-related consistency checks are pending."""
    txn_ids = {str(txn.id) for txn in transactions}
    if not txn_ids:
        return

    pending_checks_result = await db.execute(
        select(ConsistencyCheck.id)
        .where(ConsistencyCheck.user_id == user_id)
        .where(ConsistencyCheck.status == CheckStatus.PENDING)
        .where(ConsistencyCheck.related_txn_ids.has_any(array(sorted(txn_ids), type_=Text)))
        .limit(1)
    )
    if pending_checks_result.scalar_one_or_none():
        raise ValueError(UNRESOLVED_CHECKS_DETAIL)


async def load_stage1_posting_context(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement: BankStatement,
) -> Stage1PostingContext:
    """Load statement transactions and enforce approval guards shared by Stage 1 paths."""
    txn_result = await db.execute(
        select(BankStatementTransaction).where(BankStatementTransaction.statement_id == statement.id)
    )
    transactions = list(txn_result.scalars().all())
    await assert_no_unresolved_checks_for_statement(db, user_id=user_id, transactions=transactions)
    return Stage1PostingContext(statement=statement, transactions=transactions)


async def create_statement_account_from_confirmation(
    db: AsyncSession,
    *,
    statement: BankStatement,
    user_id: UUID,
) -> Account:
    """Create and bind a statement account after explicit Stage 1 user confirmation."""
    if statement.account_id:
        return await require_statement_posting_account(db, statement=statement, user_id=user_id)

    currency = (statement.currency or "SGD").strip().upper()
    institution = (statement.institution or "").strip()
    account_name = institution or "Statement Account"
    if statement.account_last4:
        account_name = f"{account_name} *{statement.account_last4.strip()}"

    account = Account(
        user_id=user_id,
        name=account_name,
        type=AccountType.ASSET,
        currency=currency,
        description=f"Created from confirmed statement import {statement.original_filename}",
    )
    db.add(account)
    await db.flush()
    statement.account_id = account.id
    await db.flush()
    return account
