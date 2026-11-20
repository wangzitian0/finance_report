"""Stage 1 statement review and balance-chain validation on StatementSummary."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_BALANCE_TOLERANCE, InvariantResult, evaluate_promotion
from src.audit.money.adopt import balance_check
from src.extraction.base.source_vocabulary import BankStatementStatus, Stage1Status, TransactionDirection
from src.extraction.base.validation import evaluate_statement_balance
from src.extraction.extension.statement_runs import ActiveRunExists, get_active_run
from src.extraction.extension.reviewed_statement_envelope import (
    get_current_statement_extraction_result,
    require_current_statement_envelope_trust,
)
from src.extraction.extension.transaction_identity import (
    resolve_transaction_identity,
    source_custody_scope,
    versioned_transaction_hash,
)
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, account_service
from src.platform import ConflictError, ResourceNotFoundError, ValidationFailedError

BALANCE_TOLERANCE = STATEMENT_BALANCE_TOLERANCE


class BalanceChainValidationError(ValidationFailedError):
    """Raise when statement balance-chain validation fails."""


def pending_stage1_review_filter():
    return or_(
        StatementSummary.stage1_status == Stage1Status.PENDING_REVIEW,
        StatementSummary.stage1_status.is_(None),
    )


async def resolve_statement_transactions(
    db: AsyncSession,
    statement: StatementSummary,
) -> list[AtomicTransaction]:
    """Resolve Layer-2 AtomicTransaction rows ordered by source_row, txn_date, created_at."""
    uploaded_doc_id = getattr(statement, "uploaded_document_id", None)
    if uploaded_doc_id is None:
        return []

    query = select(AtomicTransaction).where(
        AtomicTransaction.user_id == statement.user_id,
        AtomicTransaction.source_documents.contains([{"doc_id": str(uploaded_doc_id)}]),
    )
    metadata = statement.extraction_metadata
    payload = metadata.get("statement_extraction_result") if isinstance(metadata, dict) else None
    if statement.current_extraction_result_id is not None:
        current_result = await get_current_statement_extraction_result(
            db, user_id=statement.user_id, statement_id=statement.id, statement=statement
        )
        if current_result is None:
            raise ValidationFailedError("Current source result is unavailable for transaction resolution")
        payload = current_result.to_payload()
    facts = payload.get("transactions") if isinstance(payload, dict) else None
    if isinstance(facts, list):
        if not facts:
            return []
        scope = await source_custody_scope(db, user_id=statement.user_id, document_id=uploaded_doc_id)
        current_ids = {fact["fact_id"] for fact in facts}
        current_ids.update(
            versioned_transaction_hash(fact["fact_id"], fact["currency"], scope)
            for fact in facts
            if fact.get("currency")
        )
        alias_ids = select(AtomicTransactionIdentity.atomic_txn_id).where(
            AtomicTransactionIdentity.user_id == statement.user_id,
            AtomicTransactionIdentity.identity_version == "v2",
            AtomicTransactionIdentity.identity_hash.in_(current_ids),
        )
        query = query.where(or_(AtomicTransaction.dedup_hash.in_(current_ids), AtomicTransaction.id.in_(alias_ids)))

    rows = list(
        (await db.execute(query.order_by(AtomicTransaction.txn_date, AtomicTransaction.created_at))).scalars().all()
    )
    if isinstance(facts, list):
        if len(rows) != len(facts):
            raise ValidationFailedError(
                "Current source transaction identity requires review: incomplete persisted facts"
            )
        alias_pairs = list(
            (
                await db.execute(
                    select(AtomicTransactionIdentity.atomic_txn_id, AtomicTransactionIdentity.identity_hash).where(
                        AtomicTransactionIdentity.user_id == statement.user_id,
                        AtomicTransactionIdentity.identity_version == "v2",
                        AtomicTransactionIdentity.identity_hash.in_(current_ids),
                    )
                )
            ).all()
        )
        aliased_rows = {txn_id for txn_id, _ in alias_pairs}
        alias_hashes_by_row: dict[UUID, set[str]] = {}
        for txn_id, identity_hash in alias_pairs:
            alias_hashes_by_row.setdefault(txn_id, set()).add(identity_hash)

        ordinals_by_hash: dict[str, list[int]] = {}
        fact_keys: set[tuple[Decimal, str, str, str | None]] = set()
        for idx, fact in enumerate(facts):
            ordinal = idx + 1
            fact_id = fact["fact_id"]
            ordinals_by_hash.setdefault(fact_id, []).append(ordinal)
            if fact.get("currency"):
                v2_hash = versioned_transaction_hash(fact_id, fact["currency"], scope)
                if v2_hash != fact_id:
                    ordinals_by_hash.setdefault(v2_hash, []).append(ordinal)
            fact_keys.add(
                (Decimal(str(fact["amount"])), fact["transaction_date"], fact["direction"], fact.get("currency"))
            )

        used_ordinals: set[int] = set()
        for row in rows:
            row_date = row.txn_date.isoformat()
            row_dir = row.direction.value if hasattr(row.direction, "value") else row.direction
            if (row.amount, row_date, row_dir, row.currency) not in fact_keys and (
                row.amount,
                row_date,
                row_dir,
                None,
            ) not in fact_keys:
                raise ValidationFailedError(
                    "Current source transaction identity requires review: source fact or currency differs"
                )
            if row.id not in aliased_rows:
                _, resolved = await resolve_transaction_identity(
                    db,
                    user_id=statement.user_id,
                    legacy_hash=row.dedup_hash,
                    currency=row.currency,
                    custody_scope=scope,
                )
                if resolved is None or resolved.id != row.id:
                    raise ValidationFailedError(
                        "Current source transaction identity requires review: legacy custody differs"
                    )

            candidate_hashes = [row.dedup_hash, *sorted(alias_hashes_by_row.get(row.id, ()))]
            if row.currency:
                candidate_hashes.append(versioned_transaction_hash(row.dedup_hash, row.currency, scope))
            source_row = next(
                (
                    ordinal
                    for ch in candidate_hashes
                    for ordinal in ordinals_by_hash.get(ch, ())
                    if ordinal not in used_ordinals
                ),
                next(ordinal for ordinal in range(1, len(rows) + 2) if ordinal not in used_ordinals),
            )
            used_ordinals.add(source_row)
            setattr(row, "source_row", source_row)
        rows.sort(key=lambda r: (getattr(r, "source_row", 1), r.txn_date, r.created_at))
    else:
        for idx, row in enumerate(rows):
            setattr(row, "source_row", idx + 1)
    return rows


def _direction_val(direction: object) -> object:
    return direction.value if hasattr(direction, "value") else direction


def _signed_txn_amount(txn: AtomicTransaction) -> Decimal:
    return txn.amount if _direction_val(txn.direction) == TransactionDirection.IN.value else -txn.amount


def _undeclared_currency_row(currency: str, net: Decimal) -> dict:
    expected, delta = balance_check(Decimal("0"), Decimal("0"), net, currency)
    return {
        "currency": currency,
        "opening_balance": None,
        "closing_balance": None,
        "calculated_closing": str(expected),
        "closing_delta": str(delta),
        "closing_match": False,
        "declared_balance": False,
    }


def _per_currency_validation_response(per_currency: list[dict], primary_currency: str, *, declared_mode: bool) -> dict:
    primary = next((row for row in per_currency if row["currency"] == primary_currency), per_currency[0])
    return {
        "opening_balance": primary["opening_balance"],
        "closing_balance": primary["closing_balance"],
        "calculated_closing": primary["calculated_closing"],
        "opening_delta": "0",
        "closing_delta": primary["closing_delta"],
        "opening_match": declared_mode,
        "closing_known": declared_mode,
        "closing_match": primary["closing_match"] if declared_mode else False,
        "balance_valid": all(row["closing_match"] for row in per_currency) if declared_mode else False,
        "per_currency": per_currency,
        "validated_at": datetime.now(UTC).isoformat(),
    }


async def validate_balance_chain(
    db: AsyncSession,
    statement_id: UUID,
    *,
    statement: StatementSummary | None = None,
    transactions: list[AtomicTransaction] | None = None,
    include_previous_statement: bool = True,
) -> dict:
    if statement is None:
        statement = await db.get(StatementSummary, statement_id)
        if not statement:
            raise ResourceNotFoundError("Statement not found")

    if transactions is None:
        transactions = await resolve_statement_transactions(db, statement)

    typed_balances = statement.typed_currency_balances()
    if len(typed_balances):
        balance_dicts = [
            {
                "currency": balance.currency.code,
                "opening": str(balance.opening.amount),
                "closing": str(balance.closing.amount),
            }
            for balance in typed_balances
        ]
        txn_payloads = [
            {
                "amount": str(txn.amount),
                "direction": _direction_val(txn.direction),
                "currency": txn.currency.strip().upper(),
            }
            for txn in transactions
        ]
        eval_res = evaluate_statement_balance(
            opening=None,
            closing=None,
            currency=statement.currency,
            currency_balances=balance_dicts,
            transactions=txn_payloads,
            tolerance=BALANCE_TOLERANCE,
        )
        per_currency = []
        for row in eval_res.get("per_currency", []):
            ccy = row["currency"]
            if row.get("declared_balance"):
                bal = typed_balances.get(ccy)
                assert bal is not None
                per_currency.append(
                    {
                        "currency": ccy,
                        "opening_balance": str(bal.opening.amount),
                        "closing_balance": str(bal.closing.amount),
                        "calculated_closing": row["expected_closing"],
                        "closing_delta": row["raw_difference"],
                        "closing_match": bool(row["balance_valid"]),
                        "declared_balance": True,
                    }
                )
            else:
                per_currency.append(
                    {
                        "currency": ccy,
                        "opening_balance": None,
                        "closing_balance": None,
                        "calculated_closing": row["expected_closing"],
                        "closing_delta": row["raw_difference"],
                        "closing_match": False,
                        "declared_balance": False,
                    }
                )
        declared = set(typed_balances.currencies())
        primary_currency = (statement.currency or "").strip().upper()
        if (
            primary_currency
            and primary_currency not in declared
            and not any(row["currency"] == primary_currency for row in per_currency)
        ):
            per_currency.append(_undeclared_currency_row(primary_currency, Decimal("0")))

        return _per_currency_validation_response(per_currency, primary_currency, declared_mode=True)

    transaction_currencies = {txn.currency.strip().upper() for txn in transactions}
    scalar_currency = (statement.currency or "").strip().upper()
    if len(transaction_currencies) > 1 or (transaction_currencies and scalar_currency not in transaction_currencies):
        nets = {currency: Decimal("0") for currency in transaction_currencies}
        for txn in transactions:
            nets[txn.currency.strip().upper()] += _signed_txn_amount(txn)
        per_currency = [_undeclared_currency_row(ccy, nets[ccy]) for ccy in sorted(nets)]
        return _per_currency_validation_response(per_currency, scalar_currency, declared_mode=False)

    opening_balance = statement.effective_opening_balance() or Decimal("0")
    opening_delta = Decimal("0.00")
    txn_payloads = [{"amount": str(txn.amount), "direction": _direction_val(txn.direction)} for txn in transactions]
    eval_res = evaluate_statement_balance(
        opening=opening_balance,
        closing=statement.closing_balance if statement.closing_balance is not None else Decimal("0"),
        currency=statement.currency,
        currency_balances=None,
        transactions=txn_payloads,
        tolerance=BALANCE_TOLERANCE,
    )
    calculated_closing = Decimal(eval_res["expected_closing"])

    closing_known = statement.closing_balance is not None
    closing_delta = Decimal(eval_res["raw_difference"]) if closing_known else abs(calculated_closing)

    prev_statement = await _get_previous_approved_statement(db, statement) if include_previous_statement else None
    result: dict = {
        "opening_balance": str(opening_balance),
        "closing_balance": str(statement.closing_balance) if closing_known else None,
        "calculated_closing": str(calculated_closing),
        "opening_delta": str(opening_delta),
        "closing_delta": str(closing_delta),
        "opening_match": opening_delta <= BALANCE_TOLERANCE,
        "closing_known": closing_known,
        "closing_match": closing_known and closing_delta <= BALANCE_TOLERANCE,
        "balance_valid": (opening_delta <= BALANCE_TOLERANCE)
        and (not closing_known or closing_delta <= BALANCE_TOLERANCE),
        "per_currency": [],
        "validated_at": datetime.now(UTC).isoformat(),
    }
    if prev_statement is not None and prev_statement.closing_balance is not None:
        cross_period_delta = opening_balance - prev_statement.closing_balance
        result["previous_closing_balance"] = str(prev_statement.closing_balance)
        result["previous_period_end"] = prev_statement.period_end.isoformat() if prev_statement.period_end else None
        result["cross_period_delta"] = str(cross_period_delta)
        result["cross_period_match"] = abs(cross_period_delta) <= account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE
        result["has_date_gap"] = bool(
            statement.period_start
            and prev_statement.period_end
            and (statement.period_start - prev_statement.period_end).days > 1
        )
    return result


async def _get_previous_approved_statement(db: AsyncSession, statement: StatementSummary) -> StatementSummary | None:
    if not statement.period_start:
        return None
    filters = [
        StatementSummary.user_id == statement.user_id,
        StatementSummary.status == BankStatementStatus.APPROVED,
        StatementSummary.period_end < statement.period_start,
    ]
    if statement.account_id is not None:
        filters.append(StatementSummary.account_id == statement.account_id)
    else:
        filters.append(StatementSummary.account_id.is_(None))
        if statement.institution:
            filters.append(StatementSummary.institution == statement.institution)
        if statement.account_last4:
            filters.append(StatementSummary.account_last4 == statement.account_last4)

    return (
        await db.execute(
            select(StatementSummary).where(and_(*filters)).order_by(desc(StatementSummary.period_end)).limit(1)
        )
    ).scalar_one_or_none()


async def _get_statement_for_update(db: AsyncSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    """Lock the statement row and return it as the database holds it now.

    `populate_existing` makes the row replace the cached object. A caller that read the statement before
    the lock, for example the approve route, then sees a status that another transaction committed in between,
    such as the PARSING of a rerun.
    """
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not statement:
        raise ResourceNotFoundError("Statement not found or access denied")
    return statement


def _raise_if_balance_chain_invalid(validation_result: dict) -> None:
    failed_currencies = [
        row["currency"] for row in validation_result.get("per_currency", []) if not row["closing_match"]
    ]
    if failed_currencies:
        raise BalanceChainValidationError(f"Balance mismatch for currency: {', '.join(failed_currencies)}")

    verdict = evaluate_promotion(
        [
            InvariantResult(
                name="opening_balance_chain",
                passed=validation_result["opening_match"],
                delta=Decimal(validation_result["opening_delta"]),
                tolerance=BALANCE_TOLERANCE,
            ),
            InvariantResult(
                name="closing_balance_chain",
                passed=(not validation_result.get("closing_known", True)) or validation_result["closing_match"],
                delta=Decimal(validation_result["closing_delta"]),
                tolerance=BALANCE_TOLERANCE,
            ),
        ],
        confidence_rank=0,
        min_confidence=0,
    )
    if verdict.is_authoritative:
        return
    if verdict.failed_invariant == "opening_balance_chain":
        raise BalanceChainValidationError(
            f"Opening balance mismatch: delta={validation_result['opening_delta']} exceeds tolerance "
            f"{BALANCE_TOLERANCE}"
        )
    raise BalanceChainValidationError(
        f"Balance mismatch: delta={validation_result['closing_delta']} exceeds tolerance {BALANCE_TOLERANCE}"
    )


def _has_unresolved_statement_conflicts(transactions: list[AtomicTransaction]) -> bool:
    seen: set[tuple] = set()
    by_abs_amount: dict[tuple, object] = {}
    for txn in transactions:
        direction = _direction_val(txn.direction)
        balance_key = None if txn.balance_after is None else txn.balance_after.normalize()
        duplicate_key = (txn.txn_date, txn.description.casefold(), txn.amount.copy_abs(), direction, balance_key)
        if duplicate_key in seen:
            return True
        seen.add(duplicate_key)

        transfer_key = (txn.txn_date, txn.amount.copy_abs())
        paired_dir = by_abs_amount.get(transfer_key)
        if paired_dir is not None and paired_dir != direction:
            return True
        by_abs_amount[transfer_key] = direction
    return False


# A month that is approved on one account and uploaded again on another account of the user posts each row twice:
# the row identity holds the account, so no unique key sees it (#2917). These two numbers define "the same month".
OTHER_STATEMENT_MIN_MATCHED_ROWS = 3
OTHER_STATEMENT_MIN_MATCHED_SHARE = Decimal("0.8")


@dataclass(frozen=True)
class OtherStatementMatch:
    """An approved statement of another account whose rows equal the rows of this statement."""

    statement_id: UUID
    account_name: str
    matched_rows: int
    total_rows: int


def _row_key(txn: AtomicTransaction) -> tuple:
    return (txn.txn_date, txn.amount.copy_abs(), _direction_val(txn.direction))


async def find_other_account_statement_matches(
    db: AsyncSession, statement: StatementSummary, transactions: list[AtomicTransaction]
) -> list[OtherStatementMatch]:
    """Return each approved statement of another account that holds the rows of this statement.

    Rows are equal when date, absolute amount and direction are equal. The description is not compared: a PDF and
    a CSV of one month print different descriptions.
    """
    currency = (statement.currency or "").strip().upper()
    if (
        len(transactions) < OTHER_STATEMENT_MIN_MATCHED_ROWS
        or statement.account_id is None
        or not currency
        or statement.period_start is None
        or statement.period_end is None
    ):
        return []
    others = (
        await db.execute(
            select(StatementSummary, Account.name)
            .join(Account, Account.id == StatementSummary.account_id)
            .where(
                StatementSummary.user_id == statement.user_id,
                StatementSummary.id != statement.id,
                StatementSummary.account_id != statement.account_id,
                StatementSummary.status == BankStatementStatus.APPROVED,
                func.upper(StatementSummary.currency) == currency,
                StatementSummary.period_start <= statement.period_end,
                StatementSummary.period_end >= statement.period_start,
            )
            .order_by(StatementSummary.created_at)
        )
    ).all()
    mine = Counter(_row_key(txn) for txn in transactions)
    matches: list[OtherStatementMatch] = []
    for other, account_name in others:
        theirs = Counter(_row_key(txn) for txn in await resolve_statement_transactions(db, other))
        matched = sum((mine & theirs).values())
        if (
            matched >= OTHER_STATEMENT_MIN_MATCHED_ROWS
            and matched >= OTHER_STATEMENT_MIN_MATCHED_SHARE * len(transactions)
        ):
            matches.append(
                OtherStatementMatch(
                    statement_id=other.id,
                    account_name=account_name,
                    matched_rows=matched,
                    total_rows=len(transactions),
                )
            )
    return matches


async def _raise_if_statement_conflicts_unresolved(
    db: AsyncSession, statement: StatementSummary, transactions: list[AtomicTransaction]
) -> None:
    if statement.stage1_conflicts_resolved_at is not None:
        return
    if _has_unresolved_statement_conflicts(transactions):
        raise ValidationFailedError(
            "Cannot approve statement while unresolved duplicate or transfer-pair candidates remain"
        )
    for match in await find_other_account_statement_matches(db, statement, transactions):
        raise ValidationFailedError(
            f"{match.matched_rows} of {match.total_rows} rows equal the rows of an approved statement of account "
            f"{match.account_name}. Confirm that this statement is a different account before posting."
        )


def _raise_if_approved_envelope_incomplete(statement: StatementSummary) -> None:
    if statement.account_id is None:
        raise ValidationFailedError(
            "Account mapping required before posting. Confirm the statement account before posting."
        )
    if not (statement.currency or "").strip():
        raise ValidationFailedError(
            "Statement currency required before posting. Confirm the source currency before posting."
        )
    if statement.period_start is None or statement.period_end is None:
        raise ValidationFailedError(
            "Statement period required before posting. Confirm the source date range before posting."
        )
    if statement.period_start > statement.period_end:
        raise ValidationFailedError("Statement period is invalid. Confirm the source date range before posting.")
    if statement.opening_balance is None or statement.closing_balance is None:
        raise ValidationFailedError(
            "Statement opening and closing balances required before approval. Confirm the source balances first."
        )


# PARSED is the status that waits for a review. APPROVED passes too: the auto-approve sets it as the candidate mark
# before it posts (`auto_approve_parsed_candidate`), and a repeated approve posts nothing new. Any other status, such
# as the PARSING of a rerun, must not be approved: its entries would disagree with the statement.
_APPROVABLE_STATUSES = frozenset({BankStatementStatus.PARSED, BankStatementStatus.APPROVED})


async def approve_statement_with_transactions(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    ignore_run_id: UUID | None = None,
    statement: StatementSummary | None = None,
    expected_source_result_digest: str | None = None,
) -> tuple[StatementSummary, list[AtomicTransaction]]:
    if statement is None:
        statement = await _get_statement_for_update(db, statement_id, user_id)
    # An active run changes the statement under the approve, whatever its status says: a rerun parses it again, or a
    # classify run writes answers. The route answers 409 with its id. Only the auto-approve of a classify run passes
    # `ignore_run_id`: that run ends in the transaction of its approve.
    active_run = await get_active_run(db, statement_id)
    if active_run is not None and active_run.id != ignore_run_id:
        raise ActiveRunExists(active_run.id)
    if expected_source_result_digest is not None:
        current_result = await get_current_statement_extraction_result(
            db, user_id=user_id, statement_id=statement_id, statement=statement
        )
        if current_result is None or current_result.content_digest != expected_source_result_digest:
            raise ConflictError("Extraction result changed since you opened this page. Reload and review again.")
    if statement.status not in _APPROVABLE_STATUSES:
        raise ValidationFailedError(
            f"Statement cannot be approved while its status is {statement.status.value}. Reload the statement."
        )
    await require_current_statement_envelope_trust(db, statement=statement)
    _raise_if_approved_envelope_incomplete(statement)
    transactions = await resolve_statement_transactions(db, statement)
    validation_result = await validate_balance_chain(
        db,
        statement_id,
        statement=statement,
        transactions=transactions,
        include_previous_statement=False,
    )

    _raise_if_balance_chain_invalid(validation_result)
    await _raise_if_statement_conflicts_unresolved(db, statement, transactions)

    statement.stage1_status = Stage1Status.APPROVED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.balance_validation_result = validation_result
    statement.status = BankStatementStatus.APPROVED
    await db.flush()
    return statement, transactions


async def reject_statement(
    db: AsyncSession, statement_id: UUID, user_id: UUID, reason: str | None = None
) -> StatementSummary:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.REJECTED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.status = BankStatementStatus.REJECTED
    statement.stage1_conflicts_resolved_at = None
    if reason:
        statement.validation_error = reason
    await db.flush()
    return statement


async def resolve_statement_conflicts(db: AsyncSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_conflicts_resolved_at = datetime.now(UTC)
    await db.flush()
    return statement


def find_statement_review_conflicts(
    transactions: list[AtomicTransaction],
) -> tuple[list[AtomicTransaction], list[AtomicTransaction]]:
    """Identify duplicate and opposite-direction transfer-pair candidates within a statement."""
    duplicates: list[AtomicTransaction] = []
    transfer_pairs: list[AtomicTransaction] = []
    seen: dict[tuple[Any, ...], AtomicTransaction] = {}
    by_abs_amount: dict[tuple[Any, ...], AtomicTransaction] = {}
    for txn in transactions:
        balance_key = None if txn.balance_after is None else txn.balance_after.normalize()
        dedup_key = (txn.txn_date, txn.description.casefold(), txn.amount.copy_abs(), txn.direction, balance_key)
        if dedup_key in seen:
            duplicates.extend([seen[dedup_key], txn])
        else:
            seen[dedup_key] = txn

        transfer_key = (txn.txn_date, txn.amount.copy_abs())
        paired = by_abs_amount.get(transfer_key)
        if paired and paired.direction != txn.direction:
            transfer_pairs.extend([paired, txn])
        else:
            by_abs_amount[transfer_key] = txn
    return duplicates, transfer_pairs
