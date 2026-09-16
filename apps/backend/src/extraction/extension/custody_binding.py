"""Resolve exact bank custody independently of a mutable account display name."""

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money.currency import normalize_currency_code
from src.extraction.base.result import StatementEvidenceType, StatementExtractionResult, StatementSourceType
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentType
from src.extraction.extension._base import ExtractionError
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalLine


@dataclass(frozen=True, slots=True)
class BankCustodyAllocation:
    account: Account
    binding: BankCustodyBinding
    account_created: bool
    binding_created: bool


def is_bank_custody_source(source: StatementExtractionResult | None, document: UploadedDocument | None) -> bool:
    """Prefer typed source evidence; retain legacy bank routing without absorbing brokerage."""
    if source is not None:
        return (
            source.source_type is StatementSourceType.BANK
            and source.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
        )
    return document is None or document.document_type is not DocumentType.BROKERAGE_STATEMENT


async def validate_custody_account(
    db: AsyncSession, *, user_id: UUID, account_id: UUID, currency: str | None
) -> Account:
    account = await db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise ExtractionError("Custody account must be owned by the importing user")
    if account.type != AccountType.ASSET or account.is_system:
        raise ExtractionError("Custody account must be a non-system asset account")
    if not account.is_active:
        raise ExtractionError("Custody account is archived; an active account is required")
    if currency is not None and account.currency != normalize_currency_code(currency):
        raise ExtractionError("Custody account currency does not match the source")
    return account


async def _historical_account_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution: str,
    account_last4: str,
    currency: str,
    allow_unproven: bool = False,
) -> set[UUID]:
    """Adopt retained sources only after the immutable source and custody agree."""
    statements = (
        (
            await db.execute(
                select(StatementSummary)
                .outerjoin(
                    StatementExtractionResultRecord,
                    StatementExtractionResultRecord.id == StatementSummary.current_extraction_result_id,
                )
                .where(
                    StatementSummary.user_id == user_id,
                    or_(
                        and_(
                            StatementSummary.institution == institution,
                            StatementSummary.account_last4 == account_last4,
                            StatementSummary.currency == currency,
                        ),
                        and_(
                            StatementExtractionResultRecord.payload["institution"].astext == institution,
                            StatementExtractionResultRecord.payload["account_last4"].astext == account_last4,
                            StatementExtractionResultRecord.payload["statement_currency"].astext == currency,
                        ),
                    ),
                    StatementSummary.account_id.is_not(None),
                    StatementSummary.status != BankStatementStatus.REJECTED,
                )
            )
        )
        .scalars()
        .all()
    )
    accounts: set[UUID] = set()
    for statement in statements:
        if (statement.institution, statement.account_last4, statement.currency) != (
            institution,
            account_last4,
            currency,
        ):
            raise ExtractionError("Historical custody projection contradicts its immutable source")
        document = (
            await db.get(UploadedDocument, statement.uploaded_document_id) if statement.uploaded_document_id else None
        )
        source = (
            await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
            if statement.current_extraction_result_id
            else None
        )
        if document is None or document.user_id != user_id or document.file_hash != statement.file_hash:
            raise ExtractionError("Historical custody source needs review before account adoption")
        if document.document_type is DocumentType.BROKERAGE_STATEMENT:
            raise ExtractionError("Historical custody is a brokerage source, not a bank account")
        if source is None:
            if statement.current_extraction_result_id is not None or not allow_unproven:
                raise ExtractionError(
                    "Historical custody lacks immutable evidence; explicitly select its owned account to resolve"
                )
        else:
            if (
                source.user_id != user_id
                or source.statement_id != statement.id
                or source.source_content_digest != document.file_hash
            ):
                raise ExtractionError("Historical custody source ownership or digest is inconsistent")
            try:
                result = StatementExtractionResult.from_payload(source.payload)
            except (ValueError, TypeError, KeyError) as exc:
                raise ExtractionError("Historical custody source is not valid typed evidence") from exc
            if (
                result.source_type is not StatementSourceType.BANK
                or result.evidence_type is not StatementEvidenceType.TRANSACTION_LEDGER
                or result.content_digest != source.content_digest
                or result.source_content_digest != document.file_hash
                or (result.institution, result.account_last4, result.statement_currency)
                != (institution, account_last4, currency)
            ):
                raise ExtractionError("Historical custody identity contradicts its immutable source")
        if statement.account_id is None:
            continue
        try:
            account = await validate_custody_account(
                db, user_id=user_id, account_id=statement.account_id, currency=currency
            )
        except ExtractionError as exc:
            raise ExtractionError(f"Historical custody account needs review: {exc}") from exc
        accounts.add(account.id)
    return accounts


async def resolve_bank_custody(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution: str,
    account_last4: str,
    currency: str,
    account_id: UUID | None = None,
    create_if_missing: bool = True,
) -> BankCustodyAllocation:
    currency = normalize_currency_code(currency)
    if not institution or not account_last4 or not currency:
        raise ExtractionError("Bank custody requires exact institution, account suffix, and currency")
    lock_key = json.dumps([str(user_id), institution, account_last4, currency], separators=(",", ":"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"bank-custody:{lock_key}"}
    )
    explicit = (
        await validate_custody_account(db, user_id=user_id, account_id=account_id, currency=currency)
        if account_id
        else None
    )
    binding = await db.scalar(
        select(BankCustodyBinding).where(
            BankCustodyBinding.user_id == user_id,
            BankCustodyBinding.institution == institution,
            BankCustodyBinding.account_last4 == account_last4,
            BankCustodyBinding.currency == currency,
        )
    )
    if binding is not None:
        bound_account = await validate_custody_account(
            db, user_id=user_id, account_id=binding.account_id, currency=currency
        )
        if explicit is not None and explicit.id != bound_account.id:
            raise ExtractionError("Explicit custody account contradicts the existing source binding")
        return BankCustodyAllocation(bound_account, binding, False, False)
    history = await _historical_account_ids(
        db,
        user_id=user_id,
        institution=institution,
        account_last4=account_last4,
        currency=currency,
        allow_unproven=explicit is not None,
    )
    if len(history) > 1:
        raise ExtractionError("Ambiguous historical custody accounts require explicit correction review")
    if explicit is not None and history and explicit.id not in history:
        raise ExtractionError("Explicit custody account contradicts historical source custody")
    account = explicit
    if account is None and history:
        account = await validate_custody_account(db, user_id=user_id, account_id=next(iter(history)), currency=currency)
    created = account is None
    if account is None:
        if not create_if_missing:
            raise ExtractionError(
                "Account mapping required before posting. No established custody matches the source identity."
            )
        account = Account(
            user_id=user_id,
            name=f"{institution} ••{account_last4}",
            type=AccountType.ASSET,
            currency=currency,
            code="AUTO-BANK",
        )
        db.add(account)
        await db.flush()
    binding = BankCustodyBinding(
        user_id=user_id, institution=institution, account_last4=account_last4, currency=currency, account_id=account.id
    )
    db.add(binding)
    await db.flush()
    return BankCustodyAllocation(account, binding, created, True)


async def release_rejected_custody(db: AsyncSession, allocation: BankCustodyAllocation) -> None:
    """Release only this parse's unused allocation, under its transaction key lock."""
    if not allocation.binding_created:
        return
    used_source = await db.scalar(
        select(StatementSummary.id)
        .where(
            StatementSummary.account_id == allocation.account.id,
            StatementSummary.status != BankStatementStatus.REJECTED,
        )
        .limit(1)
    )
    used_journal = await db.scalar(
        select(JournalLine.id).where(JournalLine.account_id == allocation.account.id).limit(1)
    )
    if used_source is not None or used_journal is not None:
        return
    await db.delete(allocation.binding)
    await db.flush()
    if allocation.account_created:
        await db.delete(allocation.account)
        await db.flush()


async def resolve_bank_custody_account(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution: str,
    account_last4: str,
    currency: str,
    account_id: UUID | None = None,
    create_if_missing: bool = True,
) -> Account:
    """Public custody boundary for explicit creation, selection, and mapped posting."""
    try:
        allocation = await resolve_bank_custody(
            db,
            user_id=user_id,
            institution=institution,
            account_last4=account_last4,
            currency=currency,
            account_id=account_id,
            create_if_missing=create_if_missing,
        )
    except ExtractionError as exc:
        raise ValueError(str(exc)) from exc
    return allocation.account
