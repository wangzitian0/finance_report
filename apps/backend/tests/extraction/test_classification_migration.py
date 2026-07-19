"""EPIC-018 AC18.16 (#1545 Migrate): the import → income-statement path reads the
classify node under the period's effective policy.

Real path under test: CSV statement parse -> Stage-1 approval -> flag-gated
classification -> auto-posted ledger entries -> income statement. Headline
invariant: publishing a new policy version NEVER changes an already-covered
period's as-reported figures (prospective from its effective_from cutoff).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentSource, StatementPostingOutcome, StatementPostingStatus
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement
from src.extraction.extension.transaction_classification import (
    POLICY_VERSIONS,
    CategoryProposal,
    ClassificationPolicy,
    TransactionCategory,
    backfill_classifications,
)
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import Account, AccountType, JournalEntry, JournalLine
from src.reporting import generate_income_statement
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

SALARY = Decimal("5000.00")
RENT = Decimal("1500.00")

_STUB_PROPOSALS = {
    "Salary": CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95),
    "Rent": CategoryProposal(category=TransactionCategory.HOUSING.value, confidence=95),
}


@pytest.fixture
def enabled_flag(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", True)


@pytest.fixture
def stub_proposer(monkeypatch):
    """Deterministic stand-in for the LLM boundary on the production call path."""

    async def proposer(transactions, policy):
        return [_STUB_PROPOSALS.get(t.description) for t in transactions]

    monkeypatch.setattr("src.extraction.extension.transaction_classification.propose_categories", proposer)
    return proposer


def _month_csv(year_month: str) -> bytes:
    # DBS column layout => rule-based CSV parser, no AI parsing fallback.
    return (
        f"Date,Description,Debit Amount,Credit Amount\n{year_month}-05,Salary,,{SALARY}\n{year_month}-20,Rent,{RENT},\n"
    ).encode()


async def _bank(db: AsyncSession, user_id: UUID) -> Account:
    bank = Account(user_id=user_id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    return bank


async def _ingest_month(
    db: AsyncSession,
    user_id: UUID,
    bank: Account,
    year_month: str,
    *,
    opening: Decimal,
    closing: Decimal,
) -> StatementPostingOutcome:
    csv_bytes = _month_csv(year_month)
    _result, statement, transactions = await parse_and_load_statement_projection(
        ExtractionService(),
        db=db,
        source=DocumentSource.resolve(path=Path(f"{year_month}.csv"), content=csv_bytes),
        institution="DBS",
        user_id=user_id,
        file_type="csv",
    )
    statement.account_id = bank.id
    statement.currency = bank.currency
    year, month = (int(part) for part in year_month.split("-"))
    statement.period_start = date(year, month, 1)
    statement.period_end = date(year, month, monthrange(year, month)[1])
    statement.opening_balance = opening
    statement.closing_balance = closing
    for transaction in transactions:
        transaction.currency = bank.currency
        transaction.currency_unresolved = False
        transaction.currency_resolved_by = user_id
        transaction.currency_resolved_at = datetime.now(UTC)
    await db.flush()
    approved = await approve_statement(db, statement.id, user_id)
    outcome = await auto_create_posted_entries_for_statement(db, approved, user_id, dependencies=posting_dependencies())
    return outcome


def _leaf_names(report_lines: list[dict]) -> set[str]:
    return {line["name"] for line in report_lines}


async def _june_report(db: AsyncSession, user_id: UUID) -> dict:
    report = await generate_income_statement(
        db, user_id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), currency="SGD"
    )
    # normalize to a comparable projection (drop nothing — as-reported means as-reported)
    return report


# --- AC18.16.2: the #1483 symptom, fixed and locked -------------------------------


@pytest.mark.asyncio
async def test_AC18_16_2_import_produces_categorized_income_statement(db, test_user, enabled_flag, stub_proposer):
    """AC-extraction.1816.2: AC18.16.2: after a real statement import with the flag on, the income statement
    has categorized leaf lines beyond the two Uncategorized buckets, while the
    persisted classification records retain model scores — the exact #1483 QA
    symptom, now a permanent regression lock."""
    bank = await _bank(db, test_user.id)
    outcome = await _ingest_month(db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT)
    assert outcome.status is StatementPostingStatus.POSTED
    assert outcome.created_count == 2

    report = await _june_report(db, test_user.id)
    income_names = _leaf_names(report["income"])
    expense_names = _leaf_names(report["expenses"])

    assert "Income - Salary" in income_names
    assert "Expense - Housing" in expense_names
    assert "Income - Uncategorized" not in income_names
    assert "Expense - Uncategorized" not in expense_names

    categorized = [
        line
        for line in report["income"] + report["expenses"]
        if line["name"] in ("Income - Salary", "Expense - Housing") and line["amount"]
    ]
    assert categorized
    classifications = (await db.execute(select(TransactionClassification))).scalars().all()
    assert len(classifications) == 2
    assert {row.tags["category"] for row in classifications if row.tags} == {"SALARY", "HOUSING"}
    assert all(row.confidence_score is not None for row in classifications)


# --- AC18.16.1 (headline): a new policy version never restates covered periods ----


@pytest.mark.asyncio
async def test_AC18_16_1_new_policy_version_never_restates_covered_periods(
    db, test_user, enabled_flag, stub_proposer, monkeypatch
):
    """AC-extraction.1816.1: AC18.16.1: publishing policy v2 (effective 2026-07-01) leaves June's
    as-reported income statement byte-identical; only July classifies under v2."""
    import src.extraction.extension.transaction_classification as tc

    bank = await _bank(db, test_user.id)
    await _ingest_month(db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT)
    june_before = await _june_report(db, test_user.id)

    # publish v2 with a July 1 cutoff (prospective by default)
    v2 = ClassificationPolicy(
        version=2,
        effective_from=date(2026, 7, 1),
        catalog=tuple(TransactionCategory),
        model_version="v2",
    )
    monkeypatch.setattr(tc, "POLICY_VERSIONS", (*POLICY_VERSIONS, v2))

    # July activity classifies under v2...
    await _ingest_month(db, test_user.id, bank, "2026-07", opening=SALARY - RENT, closing=2 * (SALARY - RENT))
    # ...and a full recompute over everything must still be prospective
    await backfill_classifications(db, test_user.id)

    june_after = await _june_report(db, test_user.id)
    assert june_after == june_before  # as-reported June figures are untouched

    # provenance: June rows anchored to policy v1, July rows to policy v2
    rows = (
        (
            await db.execute(
                select(TransactionClassification).join(
                    tc.ClassificationRule,
                    TransactionClassification.rule_version_id == tc.ClassificationRule.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    versions = set()
    for row in rows:
        rule = (
            await db.execute(select(tc.ClassificationRule).where(tc.ClassificationRule.id == row.rule_version_id))
        ).scalar_one()
        versions.add(rule.version_number)
    assert versions == {1, 2}


# --- AC18.16.3: flag OFF is byte-identical to today --------------------------------


@pytest.mark.asyncio
async def test_AC18_16_3_flag_off_routes_unknown_meaning_to_review(db, test_user, stub_proposer, monkeypatch):
    """AC-extraction.1816.3: disabled proposals cannot synthesize P&L meaning from direction."""
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank = await _bank(db, test_user.id)
    outcome = await _ingest_month(db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT)

    report = await _june_report(db, test_user.id)
    assert outcome.status is StatementPostingStatus.REVIEW_REQUIRED
    assert outcome.created_count == 0
    assert outcome.review_reasons == ("intent_missing",)
    assert _leaf_names(report["income"]) == set()
    assert _leaf_names(report["expenses"]) == set()
    count = len((await db.execute(select(TransactionClassification))).scalars().all())
    assert count == 0


# --- AC18.16.4: backfill is idempotent, dated, append-only -------------------------


@pytest.mark.asyncio
async def test_AC18_16_4_backfill_is_idempotent_dated_append_only(db, test_user, enabled_flag, stub_proposer):
    """AC-extraction.1816.4: AC18.16.4: backfilling historical transactions classifies once under the
    effective policy; a second run is a no-op (append-only, never rewrites)."""
    from tests.factories import AtomicTransactionFactory

    for desc in ("Salary", "Rent"):
        await AtomicTransactionFactory.create_async(
            db, user_id=test_user.id, description=desc, txn_date=date(2026, 5, 10)
        )

    first = await backfill_classifications(db, test_user.id)
    rows_first = (await db.execute(select(TransactionClassification))).scalars().all()
    assert first["classified"] == 2
    assert len(rows_first) == 2
    assert all(r.created_at is not None for r in rows_first)  # dated

    second = await backfill_classifications(db, test_user.id)
    rows_second = (await db.execute(select(TransactionClassification))).scalars().all()
    assert second["classified"] == 0  # idempotent no-op
    assert {r.id for r in rows_second} == {r.id for r in rows_first}  # append-only, kept


# --- AC18.16.5: re-classification never rewrites posted ledger entries -------------


@pytest.mark.asyncio
async def test_AC18_16_5_reclassification_never_rewrites_posted_entries(db, test_user, enabled_flag, stub_proposer):
    """AC-extraction.1816.5: AC18.16.5: the immutable ledger is stable across classification re-runs —
    category is a projection, journal entries are not silently rewritten."""
    bank = await _bank(db, test_user.id)
    await _ingest_month(db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT)

    def _snapshot(entries, lines):
        return (
            sorted((e.id, e.status.value, e.entry_date) for e in entries),
            sorted((ln.id, ln.account_id, str(ln.amount), ln.direction.value) for ln in lines),
        )

    entries = (await db.execute(select(JournalEntry))).scalars().all()
    lines = (await db.execute(select(JournalLine))).scalars().all()
    before = _snapshot(entries, lines)

    await backfill_classifications(db, test_user.id)  # recompute pass

    entries = (await db.execute(select(JournalEntry))).scalars().all()
    lines = (await db.execute(select(JournalLine))).scalars().all()
    assert _snapshot(entries, lines) == before


# --- AC18.16.3/.6 (CR #1555): the posting seam must never raise from policy lookup ---


@pytest.mark.asyncio
async def test_AC18_16_3_flag_off_never_evaluates_policy_even_for_pre_epoch_txns(db, test_user, monkeypatch):
    """CR #1555: with the flag off, posting a statement whose transactions predate
    every policy's effective_from must NOT raise — the flag gate comes before any
    policy evaluation (flag off = today's behaviour, unconditionally)."""
    import src.extraction.extension.transaction_classification as tc
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    # a registry that covers nothing before 2030 — policy_for would raise for 2026
    narrow = ClassificationPolicy(
        version=1,
        effective_from=date(2030, 1, 1),
        catalog=tuple(TransactionCategory),
        model_version="v1",
    )
    monkeypatch.setattr(tc, "POLICY_VERSIONS", (narrow,))

    bank = await _bank(db, test_user.id)
    outcome = await _ingest_month(db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT)

    assert outcome.status is StatementPostingStatus.REVIEW_REQUIRED
    assert outcome.created_count == 0
    assert outcome.review_reasons == ("intent_missing",)
    count = len((await db.execute(select(TransactionClassification))).scalars().all())
    assert count == 0


@pytest.mark.asyncio
async def test_AC18_16_6_uncovered_txn_dates_skip_classification_not_crash_posting(
    db, test_user, enabled_flag, stub_proposer, monkeypatch
):
    """CR #1555: flag ON, a transaction dated before every policy's effective_from
    is SKIPPED (stays in the Uncategorized tail) — it must never crash posting."""
    import src.extraction.extension.transaction_classification as tc

    narrow = ClassificationPolicy(
        version=1,
        effective_from=date(2026, 7, 1),  # June txns are uncovered, July covered
        catalog=tuple(TransactionCategory),
        model_version="v1",
    )
    monkeypatch.setattr(tc, "POLICY_VERSIONS", (narrow,))

    bank = await _bank(db, test_user.id)
    june_outcome = await _ingest_month(
        db, test_user.id, bank, "2026-06", opening=Decimal("0.00"), closing=SALARY - RENT
    )
    july_outcome = await _ingest_month(
        db, test_user.id, bank, "2026-07", opening=SALARY - RENT, closing=2 * (SALARY - RENT)
    )

    assert june_outcome.status is StatementPostingStatus.REVIEW_REQUIRED
    assert june_outcome.created_count == 0
    assert june_outcome.review_reasons == ("intent_missing",)
    assert july_outcome.status is StatementPostingStatus.POSTED
    assert july_outcome.created_count == 2
    rows = (await db.execute(select(TransactionClassification))).scalars().all()
    assert len(rows) == 2  # only July's two txns classified


def test_AC18_16_6_initial_policy_covers_all_history():
    """CR #1555: the DEFAULT initial basis covers all prior history (pre-2020
    statements are normal), so real imports never hit the uncovered edge."""
    from src.extraction.extension.transaction_classification import policy_for

    assert policy_for(date(1999, 1, 1)).version == 1
