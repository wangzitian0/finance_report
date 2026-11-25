from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from src.audit.base.trace import TraceCausality, TraceRecordType, TraceResult, TraceScopeKind, TraceTargetClass
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow
from src.extraction import BankStatementStatus, Stage1Status, TransactionDirection
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.extraction.orm.reviewed_statement_envelope import ReviewedStatementEnvelope, StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import DEFAULT_TEST_EMAIL_PATTERN, PERSISTENT_TEST_EMAILS, User, purge_test_accounts
from src.identity.extension.account_purge import (
    is_safe_purge_environment,
    non_user_child_tables_in_delete_order,
    owned_tables_in_delete_order,
    select_test_user_ids,
)
from src.ledger import Account, JournalEntry, JournalLine
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
from src.workflow.orm.models import WorkflowSyncState
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
    UserFactory,
)


async def _user_exists(db, user_id: UUID) -> bool:
    db.expire_all()
    return (await db.execute(select(User.id).where(User.id == user_id))).first() is not None


async def _count_where(db, model, cond) -> int:
    db.expire_all()
    return (await db.execute(select(func.count()).select_from(model).where(cond))).scalar_one()


class TestTestAccountSelection:
    async def test_selection_matches_test_accounts_and_excludes_real_ones(self, db):
        matched_emails = ("qa.alice@example.com", "e2e-bob@test.example.com", "load-test-carol@example.com")
        excluded_emails = ("real.person@gmail.com", "founder@example.com")
        for email in (*matched_emails, *excluded_emails):
            await UserFactory.create_async(db, email=email)
        await db.commit()
        selected = {email for _, email in await select_test_user_ids(db, DEFAULT_TEST_EMAIL_PATTERN)}
        assert set(matched_emails) <= selected and set(excluded_emails).isdisjoint(selected)

    def test_owned_tables_and_environment_guard(self):
        names = {t.name for t in owned_tables_in_delete_order()}
        assert {
            "accounts",
            "journal_entries",
            "atomic_transactions",
            "uploaded_documents",
        } <= names and "users" not in names
        assert all(is_safe_purge_environment(s) for s in ("development", "dev", "local", "staging", "ci", "TEST"))
        assert not any(is_safe_purge_environment(u) for u in ("production", "prod", "prd", "", None))


class TestPurge:
    async def test_apply_purges_clean_account_and_leaves_others(self, db):
        victim_id = (await UserFactory.create_async(db, email="qa.delete-me@example.com")).id
        bystander_id = (await UserFactory.create_async(db, email="real.keep-me@gmail.com")).id
        await AccountFactory.create_async(db, user_id=victim_id, name="QA Cash")
        await AccountFactory.create_async(db, user_id=bystander_id, name="Real Cash")
        db.add(
            AtomicTransactionFactory.build(
                user_id=victim_id,
                txn_date=date(2024, 1, 1),
                amount=Decimal("10.00"),
                direction=TransactionDirection.IN,
                description="seed",
                source_documents=[],
            )
        )
        await db.commit()

        report = await purge_test_accounts(db, apply=True)
        await db.commit()
        assert (
            "qa.delete-me@example.com" in report.purged
            and not await _user_exists(db, victim_id)
            and await _user_exists(db, bystander_id)
        )
        assert (
            await _count_where(db, Account, Account.user_id == victim_id),
            await _count_where(db, AtomicTransaction, AtomicTransaction.user_id == victim_id),
            await _count_where(db, Account, Account.user_id == bystander_id),
        ) == (0, 0, 1)

    async def test_account_with_posted_ledger_entry_is_blocked_not_deleted(self, db):
        protected_id = (await UserFactory.create_async(db, email="qa.has-ledger@example.com")).id
        await JournalEntryFactory.create_balanced_async(db, user_id=protected_id, amount=Decimal("50.00"))
        await db.commit()
        report = await purge_test_accounts(db, apply=True)
        await db.commit()
        assert (
            "qa.has-ledger@example.com" not in report.purged
            and "qa.has-ledger@example.com" in {e for e, _ in report.blocked}
            and await _user_exists(db, protected_id)
        )

    async def test_dry_run_and_no_matching_accounts(self, db):
        await UserFactory.create_async(db, email="real.only@gmail.com")
        assert ((empty := await purge_test_accounts(db, apply=True)).matched, empty.purged, empty.blocked) == (
            [],
            [],
            [],
        )

        victim_id = (await UserFactory.create_async(db, email="qa.dry-run@example.com")).id
        await AccountFactory.create_async(db, user_id=victim_id, name="QA Cash")
        await db.commit()
        dry = await purge_test_accounts(db, apply=False)
        assert (
            not dry.applied
            and "qa.dry-run@example.com" in dry.purged
            and await _user_exists(db, victim_id)
            and await _count_where(db, Account, Account.user_id == victim_id) == 1
        )


class TestStagingTenantRotation:
    async def test_owned_tables_loads_workflow_sync_states_and_child_fk_tables(self):
        assert "workflow_sync_states" in {t.name for t in owned_tables_in_delete_order()}
        assert {
            "atomic_transaction_source_documents",
            "atomic_position_source_documents",
            "journal_lines",
            "reconciliation_matches",
            "reconciliation_transfer_pair_legs",
        } <= {t.name for t in non_user_child_tables_in_delete_order()}

    async def test_selection_respects_disposable_prefixes_age_and_allowlist(self, db):
        old_ts, fresh_ts = datetime.now(UTC) - timedelta(days=20), datetime.now(UTC) - timedelta(days=3)
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
            await UserFactory.create_async(db, email=e, created_at=old_ts, updated_at=old_ts)
            for e in [*sorted(PERSISTENT_TEST_EMAILS), "founder@example.com", "real.person@gmail.com"]
        ]
        await db.commit()

        selected = {
            email
            for _, email in await select_test_user_ids(
                db, DEFAULT_TEST_EMAIL_PATTERN, older_than_days=14, exclude_emails=PERSISTENT_TEST_EMAILS
            )
        }
        assert set(disposable_aged) <= selected and fresh.email not in selected
        assert all(user.email not in selected for user in protected)

    async def test_purge_test_accounts_rotates_trigger_tables_and_refuses_production(self, db):
        old_ts = datetime.now(UTC) - timedelta(days=20)
        victim = await UserFactory.create_async(
            db, email="recon_disposition-victim@test.example.com", created_at=old_ts, updated_at=old_ts
        )
        bystander = await UserFactory.create_async(
            db, email="real.keep-bystander@gmail.com", created_at=old_ts, updated_at=old_ts
        )
        entry, debit_acct, _ = await JournalEntryFactory.create_balanced_async(
            db, user_id=victim.id, amount=Decimal("50.00")
        )
        await JournalEntryFactory.create_balanced_async(db, user_id=bystander.id, amount=Decimal("25.00"))
        doc = await UploadedDocumentFactory.create_async(db, user_id=victim.id, file_hash="a" * 64)
        txn = await AtomicTransactionFactory.create_async(db, user_id=victim.id, source_doc_id=doc.id)
        db.add_all(
            [
                AtomicTransactionSourceDocument(
                    atomic_txn_id=txn.id, uploaded_document_id=doc.id, doc_type="bank_statement", ordinal=0
                ),
                WorkflowSyncState(user_id=victim.id, source_fingerprint="b" * 64, package_readiness={"ready": True}),
            ]
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
        obs_id, dec_id, ext_res_id = uuid4(), uuid4(), uuid4()
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
                    id=obs_id,
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
                    id=dec_id,
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
                    id=uuid4(),
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
        db.add_all(
            [
                TraceRecordParentRow(
                    scope_kind=TraceScopeKind.TENANT, scope_id=str(victim.id), record_id=dec_id, parent_id=obs_id
                ),
                StatementExtractionResultRecord(
                    id=ext_res_id,
                    user_id=victim.id,
                    statement_id=stmt.id,
                    content_digest="f" * 64,
                    source_content_digest="0" * 64,
                    schema_version="1",
                    producer_version="v1",
                    payload={"ok": True},
                    source_trace_record_id=obs_id,
                    created_at=old_ts,
                ),
            ]
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
                review_trace_record_id=dec_id,
                created_at=old_ts,
            )
        )
        ev1, ev2 = (
            EvidenceNode(user_id=victim.id, node_kind="document", entity_type="uploaded_document", entity_id=doc.id),
            EvidenceNode(user_id=victim.id, node_kind="journal_entry", entity_type="journal_entry", entity_id=entry.id),
        )
        db.add_all([ev1, ev2])
        await db.flush()
        db.add(EvidenceEdge(user_id=victim.id, from_node_id=ev1.id, to_node_id=ev2.id, relation="POSTED_FROM"))
        victim_id, victim_email, entry_id, bystander_id = victim.id, victim.email, entry.id, bystander.id
        await db.commit()

        with pytest.raises(PermissionError):
            await purge_test_accounts(
                db, environment="production", rotate_append_only=True, older_than_days=14, apply=True
            )
        dry = await purge_test_accounts(
            db, environment="staging", rotate_append_only=True, older_than_days=14, apply=False
        )
        assert not dry.applied and victim_email in dry.purged and await _user_exists(db, victim_id)

        apply_report = await purge_test_accounts(
            db, environment="staging", rotate_append_only=True, older_than_days=14, apply=True
        )
        await db.commit()
        assert (
            apply_report.applied
            and victim_email in apply_report.purged
            and not apply_report.blocked
            and not await _user_exists(db, victim_id)
        )
        for model, cond in (
            (JournalEntry, JournalEntry.user_id == victim_id),
            (StatementSummary, StatementSummary.user_id == victim_id),
            (EvidenceNode, EvidenceNode.user_id == victim_id),
            (EvidenceEdge, EvidenceEdge.user_id == victim_id),
            (WorkflowSyncState, WorkflowSyncState.user_id == victim_id),
            (JournalLine, JournalLine.journal_entry_id == entry_id),
            (TraceRecordRow, TraceRecordRow.scope_id == str(victim_id)),
            (TraceRecordParentRow, TraceRecordParentRow.scope_id == str(victim_id)),
        ):
            assert await _count_where(db, model, cond) == 0
        assert await _user_exists(db, bystander_id)
        assert (
            await _count_where(db, JournalEntry, JournalEntry.user_id == bystander_id),
            await _count_where(db, TraceRecordRow, TraceRecordRow.scope_id == str(bystander_id)),
        ) == (1, 1)

    async def test_purge_test_accounts_cleans_2hop_transfer_pair_legs_and_pairs(self, db):
        old_ts = datetime.now(UTC) - timedelta(days=20)
        victim_normal, victim_rotate, bystander = [
            await UserFactory.create_async(db, email=e, created_at=old_ts, updated_at=old_ts)
            for e in (
                "qa.transfer-normal@example.com",
                "qa.transfer-rotate@example.com",
                "real.transfer-keep@gmail.com",
            )
        ]
        await db.flush()

        async def _seed_pair(user_id: UUID) -> UUID:
            txns = [
                AtomicTransactionFactory.build(
                    user_id=user_id,
                    txn_date=date(2026, 2, 1),
                    amount=Decimal("200.00"),
                    direction=d,
                    description=f"transfer {d.value.lower()}",
                    source_documents=[],
                )
                for d in (TransactionDirection.OUT, TransactionDirection.IN)
            ]
            db.add_all(txns)
            await db.flush()
            matches = [
                ReconciliationMatchFactory.build(
                    atomic_txn_id=t.id,
                    disposition_kind=DispositionKind.TRANSFER_LEG,
                    status=ReconciliationStatus.ACCEPTED,
                    journal_entry_ids=[],
                )
                for t in txns
            ]
            pair = ReconciliationTransferPair(
                decision=TransferPairDecision.REVIEWER_PAIRED,
                review_state=TransferPairReviewState.PAIRED,
                confidence=95,
            )
            db.add_all([*matches, pair])
            await db.flush()
            db.add_all(
                [
                    ReconciliationTransferPairLeg(pair_id=pair.id, role=r, disposition_id=m.id)
                    for r, m in zip((TransferPairLegRole.OUT, TransferPairLegRole.IN), matches)
                ]
            )
            await db.flush()
            return pair.id

        normal_uid, rotate_uid, keep_uid = victim_normal.id, victim_rotate.id, bystander.id
        normal_pair_id, rotate_pair_id, keep_pair_id = (
            await _seed_pair(normal_uid),
            await _seed_pair(rotate_uid),
            await _seed_pair(keep_uid),
        )
        await db.commit()

        for pattern, uid, pair_id, kw in (
            (r"^qa\.transfer-normal@", normal_uid, normal_pair_id, {"rotate_append_only": False}),
            (
                r"^qa\.transfer-rotate@",
                rotate_uid,
                rotate_pair_id,
                {"environment": "staging", "rotate_append_only": True, "older_than_days": 14},
            ),
        ):
            report = await purge_test_accounts(db, pattern=pattern, apply=True, **kw)
            await db.commit()
            assert report.purged and not report.blocked and not await _user_exists(db, uid)
            assert (
                await _count_where(db, ReconciliationTransferPairLeg, ReconciliationTransferPairLeg.pair_id == pair_id),
                await _count_where(db, ReconciliationTransferPair, ReconciliationTransferPair.id == pair_id),
            ) == (0, 0)
        assert await _user_exists(db, keep_uid) and (
            await _count_where(
                db, ReconciliationTransferPairLeg, ReconciliationTransferPairLeg.pair_id == keep_pair_id
            ),
            await _count_where(db, ReconciliationTransferPair, ReconciliationTransferPair.id == keep_pair_id),
        ) == (2, 1)
