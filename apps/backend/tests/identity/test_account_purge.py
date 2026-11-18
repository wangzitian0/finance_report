
from __future__ import annotations
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import func, select
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.identity import User
from src.identity.extension.account_purge import (
    DEFAULT_TEST_EMAIL_PATTERN,
    is_safe_purge_environment,
    owned_tables_in_delete_order,
    purge_test_accounts,
    select_test_user_ids,
)
from src.ledger import Account
from tests.factories import AccountFactory, JournalEntryFactory, UserFactory


async def _make_user(db, email: str) -> User:
    user = await UserFactory.create_async(db, email=email)
    await db.commit()
    return user


async def _user_exists(db, user_id: UUID) -> bool:
    db.expire_all()
    result = await db.execute(select(User.id).where(User.id == user_id))
    return result.first() is not None


async def _count(db, model, user_id: UUID) -> int:
    db.expire_all()
    result = await db.execute(select(func.count()).select_from(model).where(model.user_id == user_id))
    return result.scalar_one()


class TestTestAccountSelection:

    async def test_selection_matches_test_accounts_and_excludes_real_ones(self, db):
        qa = await _make_user(db, "qa.alice@example.com")
        e2e = await _make_user(db, "e2e-bob@test.example.com")
        load = await _make_user(db, "load-test-carol@example.com")
        real = await _make_user(db, "real.person@gmail.com")
        plain = await _make_user(db, "founder@example.com")
        selected = await select_test_user_ids(db, DEFAULT_TEST_EMAIL_PATTERN)
        emails = {email for _, email in selected}
        assert {qa.email, e2e.email, load.email} <= emails
        assert real.email not in emails
        assert plain.email not in emails

    def test_owned_tables_cover_core_user_data_and_exclude_users(self):
        names = {t.name for t in owned_tables_in_delete_order()}
        assert {"accounts", "journal_entries", "atomic_transactions", "uploaded_documents"} <= names
        assert "users" not in names

    def test_environment_guard_allows_dev_staging_and_refuses_production(self):
        assert all(
            (
                is_safe_purge_environment(safe) is True
                for safe in ("development", "dev", "local", "staging", "ci", "TEST")
            )
        )
        assert all((is_safe_purge_environment(unsafe) is False for unsafe in ("production", "prod", "prd", "", None)))


class TestPurge:
    async def test_apply_purges_clean_account_and_leaves_others(self, db):
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
        await db.commit()
        assert "qa.delete-me@example.com" in report.purged
        assert not await _user_exists(db, victim_id)
        assert await _count(db, Account, victim_id) == 0
        assert await _count(db, AtomicTransaction, victim_id) == 0
        assert await _user_exists(db, bystander_id)
        assert await _count(db, Account, bystander_id) == 1

    async def test_account_with_posted_ledger_entry_is_blocked_not_deleted(self, db):
        protected = await _make_user(db, "qa.has-ledger@example.com")
        protected_id = protected.id
        await JournalEntryFactory.create_balanced_async(db, user_id=protected_id, amount=Decimal("50.00"))
        await db.commit()
        report = await purge_test_accounts(db, apply=True)
        await db.commit()
        assert "qa.has-ledger@example.com" not in report.purged
        blocked_emails = {email for email, _ in report.blocked}
        assert "qa.has-ledger@example.com" in blocked_emails
        assert await _user_exists(db, protected_id)

    async def test_dry_run_reports_but_persists_nothing(self, db):
        victim = await _make_user(db, "qa.dry-run@example.com")
        victim_id = victim.id
        await AccountFactory.create_async(db, user_id=victim_id, name="QA Cash")
        await db.commit()
        report = await purge_test_accounts(db, apply=False)
        assert report.applied is False
        assert "qa.dry-run@example.com" in report.purged
        assert await _user_exists(db, victim_id)
        assert await _count(db, Account, victim_id) == 1

    async def test_no_matching_accounts_is_a_noop(self, db):
        await _make_user(db, "real.only@gmail.com")
        report = await purge_test_accounts(db, apply=True)
        assert report.matched == []
        assert report.purged == []
        assert report.blocked == []


class TestStagingTenantRotation:
    """Tests for #3050 staging-only disposable tenant rotation and trigger-safe cleanup."""

    async def test_owned_tables_loads_workflow_sync_states_and_child_fk_tables(self):
        from src.identity.extension.account_purge import non_user_child_tables_in_delete_order

        owned = {t.name for t in owned_tables_in_delete_order()}
        children = {t.name for t in non_user_child_tables_in_delete_order()}
        assert "workflow_sync_states" in owned
        assert {
            "atomic_transaction_source_documents",
            "atomic_position_source_documents",
            "journal_lines",
            "reconciliation_matches",
            "reconciliation_transfer_pair_legs",
        } <= children

    async def test_selection_respects_disposable_prefixes_age_and_allowlist(self, db):
        from datetime import UTC, datetime, timedelta
        from src.identity import DEFAULT_TEST_EMAIL_PATTERN, PERSISTENT_TEST_EMAILS

        old_ts = datetime.now(UTC) - timedelta(days=20)
        fresh_ts = datetime.now(UTC) - timedelta(days=3)

        disposable_aged = [
            "recon_disposition-abc123@test.example.com",
            "statements_journey_abc123@test.example.com",
            "accounts_journey_abc123@test.example.com",
            "journal_create_abc123@test.example.com",
            "journal_falsify_abc123@test.example.com",
            "agent-random-abc123@example.com",
            "case1-abc123@test.example.com",
            "qa-sweep-abc123@test.zitian.party",
        ]
        for email in disposable_aged:
            await UserFactory.create_async(db, email=email, created_at=old_ts, updated_at=old_ts)

        fresh = await UserFactory.create_async(
            db, email="e2e-fresh-abc123@test.example.com", created_at=fresh_ts, updated_at=fresh_ts
        )
        protected = [
            *[
                await UserFactory.create_async(db, email=e, created_at=old_ts, updated_at=old_ts)
                for e in sorted(PERSISTENT_TEST_EMAILS)
            ],
            await UserFactory.create_async(db, email="founder@example.com", created_at=old_ts, updated_at=old_ts),
            await UserFactory.create_async(db, email="real.person@gmail.com", created_at=old_ts, updated_at=old_ts),
        ]
        await db.commit()

        selected = await select_test_user_ids(
            db,
            DEFAULT_TEST_EMAIL_PATTERN,
            older_than_days=14,
            exclude_emails=PERSISTENT_TEST_EMAILS,
        )
        selected_emails = {email for _, email in selected}
        assert set(disposable_aged) <= selected_emails
        assert fresh.email not in selected_emails
        for user in protected:
            assert user.email not in selected_emails

    async def test_purge_test_accounts_rotates_trigger_tables_and_refuses_production(self, db):
        from datetime import UTC, datetime, timedelta
        import pytest
        from src.audit.base.trace import (
            TraceCausality,
            TraceRecordType,
            TraceResult,
            TraceScopeKind,
            TraceTargetClass,
        )
        from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow
        from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
        from src.extraction.orm.layer2 import AtomicTransactionSourceDocument
        from src.extraction.orm.reviewed_statement_envelope import (
            ReviewedStatementEnvelope,
            StatementExtractionResultRecord,
        )
        from src.extraction.orm.statement_summary import StatementSummary
        from src.extraction import BankStatementStatus, Stage1Status
        from src.identity import purge_test_accounts
        from src.ledger import JournalEntry, JournalLine
        from src.workflow.orm.models import WorkflowSyncState
        from tests.factories import AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory

        old_ts = datetime.now(UTC) - timedelta(days=20)
        victim = await UserFactory.create_async(
            db, email="recon_disposition-victim@test.example.com", created_at=old_ts, updated_at=old_ts
        )
        bystander = await UserFactory.create_async(
            db, email="real.keep-bystander@gmail.com", created_at=old_ts, updated_at=old_ts
        )

        # Seed immutable posted journal entry + lines + workflow sync state + source-document link + envelope + evidence + traces
        entry, debit_acct, _ = await JournalEntryFactory.create_balanced_async(
            db, user_id=victim.id, amount=Decimal("50.00")
        )
        await JournalEntryFactory.create_balanced_async(db, user_id=bystander.id, amount=Decimal("25.00"))

        doc = await UploadedDocumentFactory.create_async(db, user_id=victim.id, file_hash="a" * 64)
        txn = await AtomicTransactionFactory.create_async(db, user_id=victim.id, source_doc_id=doc.id)
        db.add(
            AtomicTransactionSourceDocument(
                atomic_txn_id=txn.id,
                uploaded_document_id=doc.id,
                doc_type="bank_statement",
                ordinal=0,
            )
        )
        db.add(
            WorkflowSyncState(
                user_id=victim.id,
                source_fingerprint="b" * 64,
                package_readiness={"ready": True},
            )
        )
        stmt = await StatementSummaryFactory.create_async(
            db,
            user_id=victim.id,
            account_id=debit_acct.id,
            uploaded_document_id=doc.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=BankStatementStatus.PARSED,
            stage1_status=Stage1Status.PENDING_REVIEW,
            file_hash="c" * 64,
        )
        trace_obs_id = uuid4()
        trace_dec_id = uuid4()
        trace_bystander_id = uuid4()
        common_trace = dict(
            schema_version="1",
            target_kind="STATEMENT",
            target_id=str(stmt.id),
            target_version="1",
            target_class=TraceTargetClass.GENERAL,
            assertion_kind="CHECK",
            assertion_id="balance",
            assertion_version="1",
            authority_package="extraction",
            proof_kind="exact",
            provenance="test",
            execution_stage="product.runtime",
            assertion_owner_digest="d" * 64,
            producer_version="v1",
            execution_id=str(uuid4()),
            evidence_manifest_digest="e" * 64,
            occurred_at=old_ts,
            reason_code="ok",
        )
        db.add_all(
            [
                TraceRecordRow(
                    id=trace_obs_id,
                    scope_kind=TraceScopeKind.TENANT,
                    scope_id=str(victim.id),
                    record_type=TraceRecordType.OBSERVATION,
                    authority_tier="CODE-ONLY",
                    result=TraceResult.PASS,
                    causality=None,
                    parent_count=0,
                    content_digest="1" * 64,
                    **common_trace,
                ),
                TraceRecordRow(
                    id=trace_dec_id,
                    scope_kind=TraceScopeKind.TENANT,
                    scope_id=str(victim.id),
                    record_type=TraceRecordType.DECISION,
                    authority_tier="CODE-ONLY",
                    result=TraceResult.AUTHORITATIVE,
                    causality=TraceCausality.DIRECT,
                    parent_count=1,
                    content_digest="2" * 64,
                    **common_trace,
                ),
                TraceRecordRow(
                    id=trace_bystander_id,
                    scope_kind=TraceScopeKind.TENANT,
                    scope_id=str(bystander.id),
                    record_type=TraceRecordType.OBSERVATION,
                    authority_tier="CODE-ONLY",
                    result=TraceResult.PASS,
                    causality=None,
                    parent_count=0,
                    content_digest="3" * 64,
                    **common_trace,
                ),
            ]
        )
        await db.flush()
        db.add(
            TraceRecordParentRow(
                scope_kind=TraceScopeKind.TENANT,
                scope_id=str(victim.id),
                record_id=trace_dec_id,
                parent_id=trace_obs_id,
            )
        )

        ext_res_id = uuid4()
        db.add(
            StatementExtractionResultRecord(
                id=ext_res_id,
                user_id=victim.id,
                statement_id=stmt.id,
                content_digest="f" * 64,
                source_content_digest="0" * 64,
                schema_version="1",
                producer_version="v1",
                payload={"ok": True},
                source_trace_record_id=trace_obs_id,
                created_at=old_ts,
            )
        )
        await db.flush()
        db.add(
            ReviewedStatementEnvelope(
                id=uuid4(),
                user_id=victim.id,
                statement_id=stmt.id,
                source_result_id=ext_res_id,
                account_id=debit_acct.id,
                currency="SGD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                opening_balance=Decimal("0.00"),
                closing_balance=Decimal("50.00"),
                rationale="confirmed in test",
                command_digest="4" * 64,
                review_trace_record_id=trace_dec_id,
                created_at=old_ts,
            )
        )
        ev1 = EvidenceNode(user_id=victim.id, node_kind="document", entity_type="uploaded_document", entity_id=doc.id)
        ev2 = EvidenceNode(
            user_id=victim.id, node_kind="journal_entry", entity_type="journal_entry", entity_id=entry.id
        )
        db.add_all([ev1, ev2])
        await db.flush()
        db.add(EvidenceEdge(user_id=victim.id, from_node_id=ev1.id, to_node_id=ev2.id, relation="POSTED_FROM"))
        victim_id = victim.id
        victim_email = victim.email
        entry_id = entry.id
        bystander_id = bystander.id
        await db.commit()

        # 1. Fail closed outside safe staging/dev environments
        with pytest.raises(PermissionError):
            await purge_test_accounts(
                db, environment="production", rotate_append_only=True, older_than_days=14, apply=True
            )

        # 2. Dry run persists nothing
        dry_report = await purge_test_accounts(
            db, environment="staging", rotate_append_only=True, older_than_days=14, apply=False
        )
        assert dry_report.applied is False
        assert victim_email in dry_report.purged
        assert await _user_exists(db, victim_id)

        # 3. Apply removes victim + every trigger/FK-protected row cleanly, sparing bystander
        apply_report = await purge_test_accounts(
            db, environment="staging", rotate_append_only=True, older_than_days=14, apply=True
        )
        await db.commit()
        assert apply_report.applied is True
        assert victim_email in apply_report.purged
        assert not apply_report.blocked
        assert not await _user_exists(db, victim_id)
        assert await _count(db, JournalEntry, victim_id) == 0
        assert await _count(db, StatementSummary, victim_id) == 0
        assert await _count(db, EvidenceNode, victim_id) == 0
        assert await _count(db, EvidenceEdge, victim_id) == 0
        assert await _count(db, WorkflowSyncState, victim_id) == 0
        assert (
            await db.execute(
                select(func.count()).select_from(JournalLine).where(JournalLine.journal_entry_id == entry_id)
            )
        ).scalar_one() == 0
        assert (
            await db.execute(
                select(func.count()).select_from(TraceRecordRow).where(TraceRecordRow.scope_id == str(victim_id))
            )
        ).scalar_one() == 0
        assert (
            await db.execute(
                select(func.count())
                .select_from(TraceRecordParentRow)
                .where(TraceRecordParentRow.scope_id == str(victim_id))
            )
        ).scalar_one() == 0
        assert await _user_exists(db, bystander_id)
        assert await _count(db, JournalEntry, bystander_id) == 1
        assert (
            await db.execute(
                select(func.count()).select_from(TraceRecordRow).where(TraceRecordRow.scope_id == str(bystander_id))
            )
        ).scalar_one() == 1

    async def test_purge_test_accounts_cleans_2hop_transfer_pair_legs_and_pairs(self, db):
        from datetime import UTC, datetime, timedelta
        from src.reconciliation.orm.reconciliation import (
            DispositionKind,
            ReconciliationMatch,
            ReconciliationStatus,
            ReconciliationTransferPair,
            ReconciliationTransferPairLeg,
            TransferPairDecision,
            TransferPairLegRole,
            TransferPairReviewState,
        )

        old_ts = datetime.now(UTC) - timedelta(days=20)
        victim_normal = await UserFactory.create_async(
            db, email="qa.transfer-normal@example.com", created_at=old_ts, updated_at=old_ts
        )
        victim_rotate = await UserFactory.create_async(
            db, email="qa.transfer-rotate@example.com", created_at=old_ts, updated_at=old_ts
        )
        bystander = await UserFactory.create_async(
            db, email="real.transfer-keep@gmail.com", created_at=old_ts, updated_at=old_ts
        )
        await db.flush()

        async def _seed_pair(user_id: UUID) -> tuple[UUID, tuple[UUID, UUID]]:
            t_out = AtomicTransaction(
                user_id=user_id,
                txn_date=date(2026, 2, 1),
                amount=Decimal("200.00"),
                direction=TransactionDirection.OUT,
                description="transfer out",
                currency="SGD",
                dedup_hash=uuid4().hex,
                source_documents=[],
            )
            t_in = AtomicTransaction(
                user_id=user_id,
                txn_date=date(2026, 2, 1),
                amount=Decimal("200.00"),
                direction=TransactionDirection.IN,
                description="transfer in",
                currency="SGD",
                dedup_hash=uuid4().hex,
                source_documents=[],
            )
            db.add_all([t_out, t_in])
            await db.flush()
            m_out = ReconciliationMatch(
                atomic_txn_id=t_out.id,
                disposition_kind=DispositionKind.TRANSFER_LEG,
                status=ReconciliationStatus.ACCEPTED,
                match_score=95,
            )
            m_in = ReconciliationMatch(
                atomic_txn_id=t_in.id,
                disposition_kind=DispositionKind.TRANSFER_LEG,
                status=ReconciliationStatus.ACCEPTED,
                match_score=95,
            )
            pair = ReconciliationTransferPair(
                decision=TransferPairDecision.REVIEWER_PAIRED,
                review_state=TransferPairReviewState.PAIRED,
                confidence=95,
            )
            db.add_all([m_out, m_in, pair])
            await db.flush()
            db.add_all(
                [
                    ReconciliationTransferPairLeg(
                        pair_id=pair.id, role=TransferPairLegRole.OUT, disposition_id=m_out.id
                    ),
                    ReconciliationTransferPairLeg(
                        pair_id=pair.id, role=TransferPairLegRole.IN, disposition_id=m_in.id
                    ),
                ]
            )
            await db.flush()
            return pair.id, (m_out.id, m_in.id)

        normal_pair_id, _ = await _seed_pair(victim_normal.id)
        rotate_pair_id, _ = await _seed_pair(victim_rotate.id)
        keep_pair_id, _ = await _seed_pair(bystander.id)
        normal_uid = victim_normal.id
        rotate_uid = victim_rotate.id
        keep_uid = bystander.id
        await db.commit()

        # 1. Normal mode: fails with IntegrityError if 2-hop legs aren't removed before reconciliation_matches
        normal_report = await purge_test_accounts(
            db, pattern=r"^qa\.transfer-normal@", rotate_append_only=False, apply=True
        )
        await db.commit()
        assert "qa.transfer-normal@example.com" in normal_report.purged
        assert not normal_report.blocked
        assert not await _user_exists(db, normal_uid)
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPairLeg)
                .where(ReconciliationTransferPairLeg.pair_id == normal_pair_id)
            )
        ).scalar_one() == 0
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPair)
                .where(ReconciliationTransferPair.id == normal_pair_id)
            )
        ).scalar_one() == 0

        # 2. Rotation mode: leaves zero orphan legs or pairs for victim while sparing bystander
        rotate_report = await purge_test_accounts(
            db,
            pattern=r"^qa\.transfer-rotate@",
            environment="staging",
            rotate_append_only=True,
            older_than_days=14,
            apply=True,
        )
        await db.commit()
        assert "qa.transfer-rotate@example.com" in rotate_report.purged
        assert not rotate_report.blocked
        assert not await _user_exists(db, rotate_uid)
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPairLeg)
                .where(ReconciliationTransferPairLeg.pair_id == rotate_pair_id)
            )
        ).scalar_one() == 0
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPair)
                .where(ReconciliationTransferPair.id == rotate_pair_id)
            )
        ).scalar_one() == 0
        assert await _user_exists(db, keep_uid)
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPairLeg)
                .where(ReconciliationTransferPairLeg.pair_id == keep_pair_id)
            )
        ).scalar_one() == 2
        assert (
            await db.execute(
                select(func.count())
                .select_from(ReconciliationTransferPair)
                .where(ReconciliationTransferPair.id == keep_pair_id)
            )
        ).scalar_one() == 1
