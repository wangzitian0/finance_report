"""Versioned custody identity and conservative adoption of legacy atomic facts."""

import hashlib
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.extension._base import ExtractionError
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account


class TransactionIdentityReviewRequired(ExtractionError):
    """Existing source identity cannot be adopted without a custody review."""


def versioned_transaction_hash(legacy_hash: str, currency: str, custody_scope: str) -> str:
    """Version salt prevents v1/v2 ambiguity without changing historical hashes."""
    return hashlib.sha256(f"v2|{currency.strip().upper()}|{custody_scope}|{legacy_hash}".encode()).hexdigest()


async def source_custody_scope(
    db: AsyncSession, *, user_id: UUID, document_id: UUID, account_id: UUID | None = None
) -> str:
    document = await db.get(UploadedDocument, document_id)
    if document is not None and document.user_id != user_id:
        raise ValueError("Transaction source belongs to another user")
    summary = await db.scalar(
        select(StatementSummary).where(
            StatementSummary.user_id == user_id, StatementSummary.uploaded_document_id == document_id
        )
    )
    source_account = summary.account_id if summary is not None else None
    if account_id is not None and source_account is not None and account_id != source_account:
        raise TransactionIdentityReviewRequired("Transaction identity requires review: source custody changed")
    account_id = account_id or source_account
    if account_id is not None:
        account = await db.get(Account, account_id)
        if account is None or account.user_id != user_id:
            raise ValueError("Transaction custody account belongs to another user or is missing")
        return f"account:{account_id}"
    # Unknown custody is never a claim that two documents are the same account.
    return f"source:{document.file_hash if document is not None else document_id}"


async def resolve_transaction_identity(
    db: AsyncSession, *, user_id: UUID, legacy_hash: str, currency: str, custody_scope: str
) -> tuple[str, AtomicTransaction | None]:
    """Serialize one v2 identity and conservatively resolve a historical alias."""
    identity_hash = versioned_transaction_hash(legacy_hash, currency, custody_scope)
    lock_id = int.from_bytes(bytes.fromhex(identity_hash)[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:identity_lock)"), {"identity_lock": lock_id})
    alias = await db.get(AtomicTransactionIdentity, (user_id, "v2", identity_hash))
    if alias is not None:
        existing = await db.get(AtomicTransaction, alias.atomic_txn_id)
        if (
            existing is None
            or existing.user_id != user_id
            or existing.currency != currency
            or alias.currency != currency
            or alias.custody_scope != custody_scope
        ):
            raise TransactionIdentityReviewRequired("Transaction identity requires review: inconsistent alias")

    candidate_ids = select(AtomicTransactionIdentity.atomic_txn_id).where(
        AtomicTransactionIdentity.user_id == user_id, AtomicTransactionIdentity.legacy_hash == legacy_hash
    )
    candidates = list(
        (
            await db.scalars(
                select(AtomicTransaction).where(
                    AtomicTransaction.user_id == user_id,
                    or_(AtomicTransaction.dedup_hash == legacy_hash, AtomicTransaction.id.in_(candidate_ids)),
                )
            )
        ).all()
    )
    compatible: list[AtomicTransaction] = []
    for candidate in candidates:
        if candidate.currency != currency:
            continue
        sources = candidate.source_documents if isinstance(candidate.source_documents, list) else []
        scopes: set[str] = set()
        for source in sources:
            try:
                document_id = UUID(source["doc_id"])
            except (ValueError, KeyError, TypeError):
                raise TransactionIdentityReviewRequired(
                    "Transaction identity requires review: incomplete legacy lineage"
                ) from None
            scopes.add(await source_custody_scope(db, user_id=user_id, document_id=document_id))
            summary = await db.scalar(
                select(StatementSummary).where(
                    StatementSummary.user_id == user_id, StatementSummary.uploaded_document_id == document_id
                )
            )
            if summary is not None:
                currencies = {bucket["currency"] for bucket in (summary.currency_balances or [])}
                if summary.currency:
                    currencies.add(summary.currency)
                if currencies and currency not in currencies:
                    raise TransactionIdentityReviewRequired(
                        "Transaction identity requires review: conflicting legacy currency"
                    )
        if len(scopes) != 1:
            raise TransactionIdentityReviewRequired("Transaction identity requires review: conflicting legacy custody")
        candidate_scope = next(iter(scopes))
        if candidate_scope == custody_scope:
            compatible.append(candidate)
        elif candidate.dedup_hash == legacy_hash and (
            candidate_scope.startswith("source:") or custody_scope.startswith("source:")
        ):
            raise TransactionIdentityReviewRequired("Transaction identity requires review: missing legacy custody")
        # A v2 source-isolated fact or a proven different account is a novel
        # event. Its current source still requires custody review before posting.
    if alias is not None and (len(compatible) != 1 or compatible[0].id != alias.atomic_txn_id):
        raise TransactionIdentityReviewRequired("Transaction identity requires review: alias custody no longer agrees")
    if len(compatible) > 1:
        raise TransactionIdentityReviewRequired("Transaction identity requires review: multiple historical candidates")
    return identity_hash, compatible[0] if compatible else None


async def bind_transaction_identity(
    db: AsyncSession, *, transaction: AtomicTransaction, identity_hash: str, legacy_hash: str, custody_scope: str
) -> None:
    """Caller owns the identity lock and transaction; old hashes/UUIDs never change."""
    if await db.get(AtomicTransactionIdentity, (transaction.user_id, "v2", identity_hash)) is not None:
        return
    db.add(
        AtomicTransactionIdentity(
            user_id=transaction.user_id,
            identity_version="v2",
            identity_hash=identity_hash,
            legacy_hash=legacy_hash,
            atomic_txn_id=transaction.id,
            currency=transaction.currency,
            custody_scope=custody_scope,
        )
    )
