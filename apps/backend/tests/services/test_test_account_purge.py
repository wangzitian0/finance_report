"""Tests for the test/QA account purge tooling (#997 item 4, EPIC-008 AC8.17).

The purge must: select only disposable test accounts, remove an account and the
rows it owns, refuse (report, don't force) an account still holding immutable
ledger entries, and persist nothing on a dry run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

from src.identity import User
from src.models.account import Account
from src.models.layer2 import AtomicTransaction, TransactionDirection
from tests.support.account_purge import (
    DEFAULT_TEST_EMAIL_PATTERN,
    is_safe_purge_environment,
    owned_tables_in_delete_order,
    purge_test_accounts,
    select_test_user_ids,
)
from tests.factories import AccountFactory, JournalEntryFactory, UserFactory


async def _make_user(db, email: str) -> User:
    user = await UserFactory.create_async(db, email=email)
    await db.commit()
    return user


async def _user_exists(db, user_id: UUID) -> bool:
    db.expire_all()  # Core DELETEs bypass the ORM identity map; force a fresh read.
    result = await db.execute(select(User.id).where(User.id == user_id))
    return result.first() is not None


async def _count(db, model, user_id: UUID) -> int:
    db.expire_all()
    result = await db.execute(select(func.count()).select_from(model).where(model.user_id == user_id))
    return result.scalar_one()


class TestTestAccountSelection:
    """AC8.17.1: only disposable test accounts are selected."""

    async def test_selection_matches_test_accounts_and_excludes_real_ones(self, db):
        qa = await _make_user(db, "qa.alice@example.com")
        e2e = await _make_user(db, "e2e-bob@test.example.com")
        load = await _make_user(db, "load-test-carol@example.com")
        real = await _make_user(db, "real.person@gmail.com")
        plain = await _make_user(db, "founder@example.com")  # real local fixture, not qa/e2e

        selected = await select_test_user_ids(db, DEFAULT_TEST_EMAIL_PATTERN)
        emails = {email for _, email in selected}

        assert {qa.email, e2e.email, load.email} <= emails
        assert real.email not in emails
        assert plain.email not in emails

    def test_owned_tables_cover_core_user_data_and_exclude_users(self):
        names = {t.name for t in owned_tables_in_delete_order()}
        # Core user-owned tables must be in the purge set...
        assert {"accounts", "journal_entries", "atomic_transactions", "uploaded_documents"} <= names
        # ...and the users table is handled separately, never in this list.
        assert "users" not in names

    def test_environment_guard_allows_dev_staging_and_refuses_production(self):
        """AC8.17.5: the --apply environment guard fences off production."""
        for safe in ("development", "dev", "local", "staging", "ci", "TEST"):
            assert is_safe_purge_environment(safe) is True
        for unsafe in ("production", "prod", "prd", "", None):
            assert is_safe_purge_environment(unsafe) is False


class TestPurge:
    async def test_apply_purges_clean_account_and_leaves_others(self, db):
        """AC8.17.2: a clean test account and its owned rows are removed."""
        victim = await _make_user(db, "qa.delete-me@example.com")
        victim_id = victim.id
        await AccountFactory.create_async(db, user_id=victim_id, name="QA Cash")
        db.add(
            AtomicTransaction(
                user_id=victim_id,
                txn_date=date(2024, 1, 1),
                amount=Decimal("10.00"),
                direction=TransactionDirection.IN,
                description="seed",
                currency="SGD",
                dedup_hash=uuid4().hex,
                source_documents=[],
            )
        )
        bystander = await _make_user(db, "real.keep-me@gmail.com")
        bystander_id = bystander.id
        await AccountFactory.create_async(db, user_id=bystander_id, name="Real Cash")
        await db.commit()

        report = await purge_test_accounts(db, apply=True)
        await db.commit()  # the service leaves the final commit to the caller

        assert "qa.delete-me@example.com" in report.purged
        assert not await _user_exists(db, victim_id)
        assert await _count(db, Account, victim_id) == 0
        assert await _count(db, AtomicTransaction, victim_id) == 0
        # The non-test account is untouched.
        assert await _user_exists(db, bystander_id)
        assert await _count(db, Account, bystander_id) == 1

    async def test_account_with_posted_ledger_entry_is_blocked_not_deleted(self, db):
        """AC8.17.3: immutable ledger entries block the purge; account is preserved."""
        protected = await _make_user(db, "qa.has-ledger@example.com")
        protected_id = protected.id
        await JournalEntryFactory.create_balanced_async(db, user_id=protected_id, amount=Decimal("50.00"))
        await db.commit()

        report = await purge_test_accounts(db, apply=True)
        await db.commit()

        assert "qa.has-ledger@example.com" not in report.purged
        blocked_emails = {email for email, _ in report.blocked}
        assert "qa.has-ledger@example.com" in blocked_emails
        # Nothing was removed for the blocked account.
        assert await _user_exists(db, protected_id)

    async def test_dry_run_reports_but_persists_nothing(self, db):
        """AC8.17.4: dry run names the accounts it would purge but deletes nothing."""
        victim = await _make_user(db, "qa.dry-run@example.com")
        victim_id = victim.id
        await AccountFactory.create_async(db, user_id=victim_id, name="QA Cash")
        await db.commit()

        report = await purge_test_accounts(db, apply=False)

        assert report.applied is False
        assert "qa.dry-run@example.com" in report.purged  # "would purge"
        # Still there after a dry run.
        assert await _user_exists(db, victim_id)
        assert await _count(db, Account, victim_id) == 1

    async def test_no_matching_accounts_is_a_noop(self, db):
        await _make_user(db, "real.only@gmail.com")
        report = await purge_test_accounts(db, apply=True)
        assert report.matched == []
        assert report.purged == []
        assert report.blocked == []
