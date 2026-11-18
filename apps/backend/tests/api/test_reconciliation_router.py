from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, TraceRecordType, TraceResult
from src.audit.orm import TraceRecordRow
from src.extraction import BankStatementStatus, DocumentType, TransactionClassification
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    ValidationError,
    post_journal_entry,
    submit_manual_journal_entry,
    validate_manual_journal_entry_for_post,
)
from src.reconciliation import EntryCreationError, ReconciliationMatch, ReconciliationStatus
from src.schemas.reconciliation import ReconciliationStatusEnum
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
    UserFactory,
)

pytestmark = pytest.mark.asyncio


async def _make_statement(
    db,
    user: User,
    *,
    institution: str = "Test Bank",
    status: BankStatementStatus = BankStatementStatus.PARSED,
    **kwargs,
) -> StatementSummary:
    doc = await UploadedDocumentFactory.create_async(db, user_id=user.id)
    return await StatementSummaryFactory.create_async(
        db,
        user_id=user.id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
        institution=institution,
        status=status,
        **kwargs,
    )


def _make_txn(statement: StatementSummary, amount: Decimal = Decimal("100.00"), **kwargs) -> AtomicTransaction:
    return AtomicTransactionFactory.build(
        user_id=statement.user_id,
        source_documents=[
            {"doc_id": str(statement.uploaded_document_id), "doc_type": DocumentType.BANK_STATEMENT.value}
        ],
        txn_date=date(2024, 1, 15),
        amount=amount,
        **kwargs,
    )


async def _create_anchored_entry(
    db, *, user_id, bank: Account, counter: Account, entry_date: date, memo: str, amount: Decimal
) -> JournalEntry:
    entry = await submit_manual_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        rationale=f"Test operator attested reconciliation candidate: {memo}",
        lines_data=[
            {"account_id": counter.id, "direction": Direction.DEBIT, "amount": amount, "currency": "SGD"},
            {"account_id": bank.id, "direction": Direction.CREDIT, "amount": amount, "currency": "SGD"},
        ],
        base_currency="SGD",
    )
    await db.refresh(entry, ["lines"])
    await validate_manual_journal_entry_for_post(db, user_id=user_id, entry=entry, base_currency="SGD")
    return await post_journal_entry(db, entry.id, user_id, base_currency="SGD")


async def _seed_txns(db, user: User, count: int = 1) -> tuple[StatementSummary, list[AtomicTransaction]]:
    stmt = await _make_statement(db, user)
    txns = [_make_txn(stmt) for _ in range(count)]
    db.add_all(txns)
    await db.commit()
    return stmt, txns


async def _seed_matches(db, user: User, statuses: list[ReconciliationStatus]) -> list[ReconciliationMatch]:
    stmt = await _make_statement(db, user)
    txns = [_make_txn(stmt) for _ in statuses]
    db.add_all(txns)
    await db.flush()
    matches = [
        ReconciliationMatchFactory.build(atomic_txn_id=txn.id, status=s, match_score=85, journal_entry_ids=[])
        for txn, s in zip(txns, statuses)
    ]
    db.add_all(matches)
    await db.commit()
    return matches


create_test_statement = _make_statement
_seed_router_txns = _seed_txns


async def create_anchored_match_entry(
    db, *, user_id, bank_account: Account, counter_account: Account, entry_date: date, memo: str, amount: Decimal
) -> JournalEntry:
    return await _create_anchored_entry(
        db, user_id=user_id, bank=bank_account, counter=counter_account, entry_date=entry_date, memo=memo, amount=amount
    )


def create_test_transaction(_db, statement: StatementSummary, **kwargs) -> AtomicTransaction:
    kwargs.pop("status", None)
    return _make_txn(statement, **kwargs)


def create_test_match(_db, transaction: AtomicTransaction, **kwargs) -> ReconciliationMatch:
    kwargs.setdefault("status", ReconciliationStatus.PENDING_REVIEW)
    kwargs.setdefault("match_score", 85)
    kwargs.setdefault("journal_entry_ids", [])
    return ReconciliationMatchFactory.build(atomic_txn_id=transaction.id, **kwargs)


async def _seed_router_match(
    db,
    user: User,
    *,
    status: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW,
    score: int = 85,
    journal_entry_ids: list[str] | None = None,
    statement: StatementSummary | None = None,
) -> tuple[StatementSummary, AtomicTransaction, ReconciliationMatch]:
    stmt = statement or await _make_statement(db, user)
    txn = _make_txn(stmt)
    db.add(txn)
    await db.flush()
    match = ReconciliationMatchFactory.build(
        atomic_txn_id=txn.id, status=status, match_score=score, journal_entry_ids=journal_entry_ids or []
    )
    db.add(match)
    await db.commit()
    return stmt, txn, match


async def _seed_expense_setup(
    db, user: User, *, expense_name: str = "Expense"
) -> tuple[Account, StatementSummary, AtomicTransaction, Account]:
    bank = await AccountFactory.create_async(db, user_id=user.id, name=f"Mapped Bank {uuid4().hex[:8]}")
    stmt = await _make_statement(db, user, account_id=bank.id)
    expense = await AccountFactory.create_async(
        db, user_id=user.id, name=f"{expense_name} {uuid4().hex[:8]}", type=AccountType.EXPENSE
    )
    txn = _make_txn(stmt)
    db.add(txn)
    await db.commit()
    return bank, stmt, txn, expense


async def _create_approved_statement(db, user: User) -> StatementSummary:
    custody = await AccountFactory.create_async(db, user_id=user.id, name=f"Custody {uuid4().hex[:8]}")
    today = date.today()
    return await _make_statement(
        db,
        user,
        account_id=custody.id,
        period_start=today,
        period_end=today,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )


class TestReconciliationEndpoints:
    async def test_run_reconciliation_success(self, client: AsyncClient, db, test_user: User):
        statement, _ = await _seed_txns(db, test_user, count=2)
        body = (resp := await client.post("/reconciliation/runs", json={"statement_id": str(statement.id)})).json()
        assert (
            resp.status_code == status.HTTP_200_OK
            and {"matches_created", "auto_accepted", "pending_review", "unmatched"} <= body.keys()
            and body["unmatched"] >= 0
        )

    @pytest.mark.parametrize(
        ("method", "path_prefix", "path_suffix", "json_body", "detail_part"),
        [
            ("POST", "/reconciliation/runs", "", None, "Statement"),
            ("PATCH", "/reconciliation/matches/", "", {"action": "accept"}, "Match"),
            ("PATCH", "/reconciliation/matches/", "", {"action": "reject"}, "Match"),
            ("GET", "/reconciliation/transactions/", "/anomalies", None, "Transaction"),
            (
                "POST",
                "/reconciliation/unmatched/",
                "/reviewed-dispositions",
                {
                    "intent": "expense",
                    "counter_account_id": str(uuid4()),
                    "category": "DINING",
                    "rationale": "Reviewed source evidence.",
                },
                "Transaction",
            ),
        ],
    )
    async def test_reconciliation_not_found_endpoints(
        self, client: AsyncClient, test_user: User, method, path_prefix, path_suffix, json_body, detail_part
    ):
        path = path_prefix if path_prefix == "/reconciliation/runs" else f"{path_prefix}{uuid4()}{path_suffix}"
        body = {"statement_id": str(uuid4())} if path_prefix == "/reconciliation/runs" else json_body
        response = await client.request(method, path, json=body)
        assert response.status_code == status.HTTP_404_NOT_FOUND and detail_part in response.json()["detail"]

    @pytest.mark.parametrize(
        ("url", "statuses", "expected_len"),
        [
            ("/reconciliation/matches", [ReconciliationStatus.PENDING_REVIEW, ReconciliationStatus.AUTO_ACCEPTED], 2),
            (
                "/reconciliation/matches?status=pending_review",
                [ReconciliationStatus.PENDING_REVIEW, ReconciliationStatus.AUTO_ACCEPTED],
                1,
            ),
            ("/reconciliation/pending", [ReconciliationStatus.PENDING_REVIEW, ReconciliationStatus.PENDING_REVIEW], 2),
        ],
    )
    async def test_list_matches_and_pending(
        self, client: AsyncClient, db, test_user: User, url, statuses, expected_len
    ):
        await _seed_matches(db, test_user, statuses)
        data = (resp := await client.get(url)).json()
        assert (
            resp.status_code == status.HTTP_200_OK
            and {"items", "total"} <= data.keys()
            and len(data["items"]) == expected_len
        )

    async def test_accept_reject_and_batch_accept(self, client: AsyncClient, db, test_user: User):
        account, statement, txn1, expense = await _seed_expense_setup(db, test_user, expense_name="Batch Expense")
        txn2, txn3 = _make_txn(statement, amount=Decimal("8.00")), _make_txn(statement, amount=Decimal("9.00"))
        db.add_all([txn2, txn3])
        await db.flush()
        matches = []
        for t, score in ((txn1, 85), (txn2, 75), (txn3, 90)):
            entry = await _create_anchored_entry(
                db,
                user_id=test_user.id,
                bank=account,
                counter=expense,
                entry_date=t.txn_date,
                memo=f"Match {t.id}",
                amount=t.amount,
            )
            matches.append(
                ReconciliationMatchFactory.build(
                    atomic_txn_id=t.id, journal_entry_ids=[str(entry.id)], match_score=score
                )
            )
        db.add_all(matches)
        await db.commit()

        accepted = await client.patch(f"/reconciliation/matches/{matches[0].id}", json={"action": "accept"})
        rejected = await client.patch(f"/reconciliation/matches/{matches[1].id}", json={"action": "reject"})
        batch = await client.post(
            "/reconciliation/matches", json={"action": "accept", "match_ids": [str(matches[2].id)]}
        )
        empty_batch = await client.post("/reconciliation/matches", json={"action": "accept", "match_ids": []})
        assert (accepted.status_code, rejected.status_code, batch.status_code, empty_batch.status_code) == (
            200,
            200,
            200,
            200,
        )
        assert (
            accepted.json()["status"],
            rejected.json()["status"],
            batch.json()["approved_count"],
            batch.json()["rejected_count"],
            empty_batch.json()["approved_count"],
            empty_batch.json()["rejected_count"],
        ) == (ReconciliationStatusEnum.ACCEPTED.value, ReconciliationStatusEnum.REJECTED.value, 1, 0, 0, 0)

    async def test_filters_unmatched_by_statement(self, client: AsyncClient, db, test_user: User):
        selected_stmt, (selected_txn,) = await _seed_txns(db, test_user, count=1)
        await _seed_txns(db, test_user, count=1)
        foreign_stmt, _ = await _seed_txns(db, await UserFactory.create_async(db), count=1)

        all_resp = await client.get("/reconciliation/unmatched")
        scoped = await client.get("/reconciliation/unmatched", params={"statement_id": str(selected_stmt.id)})
        foreign = await client.get("/reconciliation/unmatched", params={"statement_id": str(foreign_stmt.id)})
        assert all_resp.status_code == 200 and {"items", "total"} <= all_resp.json().keys()
        assert (
            scoped.status_code == 200
            and scoped.json()["total"] == 1
            and [i["id"] for i in scoped.json()["items"]] == [str(selected_txn.id)]
        )
        assert foreign.status_code == 404 and "Statement" in foreign.json()["detail"]

    async def test_statement_without_document_unmatched_is_empty(self, client: AsyncClient, db, test_user: User):
        statement = await _make_statement(db, test_user)
        statement.uploaded_document_id = None
        await db.commit()
        assert (
            resp := await client.get("/reconciliation/unmatched", params={"statement_id": str(statement.id)})
        ).status_code == status.HTTP_200_OK and resp.json() == {"items": [], "total": 0}

    async def test_submit_reviewed_disposition_from_unmatched_success(self, client: AsyncClient, db, test_user: User):
        _, _, transaction, expense = await _seed_expense_setup(db, test_user, expense_name="Expense - Dining")
        response = await client.post(
            f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions",
            json={
                "intent": "expense",
                "counter_account_id": str(expense.id),
                "category": "DINING",
                "rationale": "Reviewed against the merchant and receipt.",
            },
        )
        assert (
            response.status_code == status.HTTP_200_OK
            and {"id", "entry_date", "memo", "status", "total_amount"} <= response.json().keys()
        )
        entries = (
            (
                await db.execute(
                    select(JournalEntry).where(
                        JournalEntry.user_id == test_user.id,
                        JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES),
                        JournalEntry.source_id == transaction.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        traces = (
            (
                await db.execute(
                    select(TraceRecordRow)
                    .where(
                        TraceRecordRow.scope_id == str(test_user.id), TraceRecordRow.target_id == str(transaction.id)
                    )
                    .order_by(TraceRecordRow.occurred_at, TraceRecordRow.id)
                )
            )
            .scalars()
            .all()
        )
        manual = next(row for row in traces if row.assertion_kind == "economic_intent")
        decisions = [row for row in traces if row.record_type is TraceRecordType.DECISION]
        assert (
            len(entries) == 1
            and len(traces) == 4
            and len(decisions) == 2
            and all(row.result is TraceResult.AUTHORITATIVE for row in decisions)
        )
        assert (
            manual.record_type,
            manual.authority_package,
            manual.authority_tier,
            manual.provenance,
            manual.execution_stage,
            manual.score,
        ) == (TraceRecordType.OBSERVATION, "reconciliation", "CODE-ONLY", "manual", "manual.adjudication", None)
        assert (
            await db.execute(
                select(TransactionClassification).where(TransactionClassification.atomic_txn_id == transaction.id)
            )
        ).scalars().all() == []

    async def test_submit_reviewed_disposition_auto_binds_unmapped_statement_account(
        self, client: AsyncClient, db, test_user: User
    ):
        stmt1, stmt2 = [
            await _make_statement(
                db, test_user, account_id=None, institution="Standard Chartered Bank", account_last4="9988"
            )
            for _ in range(2)
        ]
        expense = await AccountFactory.create_async(
            db, user_id=test_user.id, name=f"Expense - Unmapped {uuid4().hex[:8]}", type=AccountType.EXPENSE
        )
        txn1, txn2 = _make_txn(stmt1, amount=Decimal("88.50")), _make_txn(stmt2, amount=Decimal("42.00"))
        db.add_all([txn1, txn2])
        await db.commit()

        for txn, rationale in ((txn1, "First."), (txn2, "Second.")):
            assert (
                await client.post(
                    f"/reconciliation/unmatched/{txn.id}/reviewed-dispositions",
                    json={
                        "intent": "expense",
                        "counter_account_id": str(expense.id),
                        "category": "DINING",
                        "rationale": rationale,
                    },
                )
            ).status_code == status.HTTP_200_OK
        [await db.refresh(s) for s in (stmt1, stmt2)]
        custody = await db.get(Account, stmt1.account_id)
        assert custody is not None and (custody.name, custody.type, custody.currency, stmt2.account_id) == (
            "Standard Chartered Bank *9988",
            AccountType.ASSET,
            "SGD",
            custody.id,
        )

    async def test_reviewed_disposition_idempotent_and_conflicts(self, client: AsyncClient, db, test_user: User):
        _, _, transaction, expense = await _seed_expense_setup(db, test_user, expense_name="Expense - Transport")
        income = await AccountFactory.create_async(
            db, user_id=test_user.id, name=f"Income - Invalid {uuid4().hex[:8]}", type=AccountType.INCOME
        )
        await db.commit()
        payload = {
            "intent": "expense",
            "counter_account_id": str(expense.id),
            "category": "TRANSPORT",
            "rationale": "Reviewed transit charge.",
        }
        first = await client.post(f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions", json=payload)
        second = await client.post(f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions", json=payload)
        assert first.status_code == 200 and second.status_code == 200 and second.json()["id"] == first.json()["id"]
        assert (
            conflict := await client.post(
                f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions",
                json={**payload, "rationale": "A different evidence review must not rewrite the posted decision."},
            )
        ).status_code == 400 and "incompatible" in conflict.json()["detail"].lower()
        assert (
            await client.post(
                f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions",
                json={**payload, "counter_account_id": str(income.id)},
            )
        ).status_code == 400
        assert (
            len(
                (await db.execute(select(TraceRecordRow).where(TraceRecordRow.target_id == str(transaction.id))))
                .scalars()
                .all()
            )
            == 4
        )

    async def test_reviewed_disposition_rejects_unmatched_bypasses(self, client: AsyncClient, db, test_user: User):
        _, statement, transfer_txn, expense = await _seed_expense_setup(
            db, test_user, expense_name="Expense - Matched Target"
        )
        asset = await AccountFactory.create_async(
            db, user_id=test_user.id, name=f"Asset - Transfer Target {uuid4().hex[:8]}"
        )
        matched_txn = _make_txn(statement)
        db.add(matched_txn)
        await db.flush()
        db.add(ReconciliationMatchFactory.build(atomic_txn_id=matched_txn.id, journal_entry_ids=[]))
        await db.commit()

        assert (
            t := await client.post(
                f"/reconciliation/unmatched/{transfer_txn.id}/reviewed-dispositions",
                json={"intent": "transfer", "counter_account_id": str(asset.id), "rationale": "Needs matched pair."},
            )
        ).status_code == 400 and "transfer_unmatched" in t.json()["detail"]
        assert (
            m := await client.post(
                f"/reconciliation/unmatched/{matched_txn.id}/reviewed-dispositions",
                json={
                    "intent": "expense",
                    "counter_account_id": str(expense.id),
                    "category": "DINING",
                    "rationale": "Already matched.",
                },
            )
        ).status_code == 400 and "already has a reconciliation match" in m.json()["detail"]
        for txn_id in (transfer_txn.id, matched_txn.id):
            assert (
                await db.execute(select(JournalEntry).where(JournalEntry.source_id == txn_id))
            ).scalars().all() == []

    @pytest.mark.parametrize("field", ["category", "rationale"])
    async def test_reviewed_disposition_rejects_blank_semantic_fields(
        self, field: str, client: AsyncClient, db, test_user: User
    ):
        _, _, transaction, expense = await _seed_expense_setup(db, test_user, expense_name="Expense - Blank Input")
        resp = await client.post(
            f"/reconciliation/unmatched/{transaction.id}/reviewed-dispositions",
            json={
                "intent": "expense",
                "counter_account_id": str(expense.id),
                "category": "DINING",
                "rationale": "Reviewed source evidence.",
                field: "   ",
            },
        )
        assert (
            resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
            and (await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))).scalars().all()
            == []
        )

    async def test_legacy_unmatched_routes_anomalies_and_unauthenticated(
        self, client: AsyncClient, public_client: AsyncClient, db, test_user: User
    ):
        _, (transaction,) = await _seed_txns(db, test_user, count=1)
        assert (await public_client.get("/reconciliation/stats")).status_code == status.HTTP_401_UNAUTHORIZED
        assert (
            a := await client.get(f"/reconciliation/transactions/{transaction.id}/anomalies")
        ).status_code == status.HTTP_200_OK and isinstance(a.json(), list)
        assert (
            (await client.post(f"/reconciliation/unmatched/{transaction.id}/create-entry")).status_code,
            (await client.post("/reconciliation/unmatched/batch-create", json={"all": True})).status_code,
        ) == (404, 404)
        assert (
            await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
        ).scalars().all() == []

    @pytest.mark.parametrize("valid_entry", [True, False])
    async def test_list_matches_entry_summaries(self, client: AsyncClient, db, test_user: User, valid_entry: bool):
        entry_ids = (
            [str((await JournalEntryFactory.create_balanced_async(db, test_user.id))[0].id)]
            if valid_entry
            else [str(uuid4())]
        )
        txn = _make_txn(await _make_statement(db, test_user))
        db.add(txn)
        await db.flush()
        db.add(ReconciliationMatchFactory.build(atomic_txn_id=txn.id, journal_entry_ids=entry_ids))
        await db.commit()

        resp = await client.get("/reconciliation/matches")
        entries = resp.json()["items"][0]["entries"]
        assert resp.status_code == status.HTTP_200_OK and (
            (len(entries) > 0 and {"id", "total_amount"} <= entries[0].keys()) if valid_entry else entries == []
        )


@pytest.mark.parametrize(
    ("target", "exc", "url", "body", "detail_part"),
    [
        (
            "src.routers.reconciliation.execute_matching",
            ValidationError("Processing account currency is SGD; got transfer currency USD"),
            "/reconciliation/runs",
            {},
            "Processing account currency is SGD",
        ),
        (
            "src.reconciliation.extension.review_queue.accept_pending_matches",
            EntryCreationError("Account mapping required before posting"),
            "/reconciliation/matches",
            {"action": "accept", "match_ids": [str(uuid4())]},
            None,
        ),
    ],
)
async def test_reconciliation_router_error_mappings(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, target, exc, url, body, detail_part
) -> None:
    monkeypatch.setattr(target, AsyncMock(side_effect=exc))
    assert (resp := await client.post(url, json=body)).status_code == 400 and (
        detail_part is None or detail_part in resp.json()["detail"]
    )


async def test_run_reconciliation_filters_unmatched(
    client: AsyncClient, db, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement, _ = await _seed_txns(db, test_user, count=1)
    monkeypatch.setattr(
        "src.routers.reconciliation.execute_matching",
        AsyncMock(
            return_value=[
                ReconciliationMatch(
                    atomic_txn_id=uuid4(), journal_entry_ids=[], match_score=s, score_breakdown={}, status=st
                )
                for s, st in ((90, ReconciliationStatus.AUTO_ACCEPTED), (70, ReconciliationStatus.PENDING_REVIEW))
            ]
        ),
    )
    body = (resp := await client.post("/reconciliation/runs", json={"statement_id": str(statement.id)})).json()
    assert resp.status_code == 200 and (
        body["matches_created"],
        body["auto_accepted"],
        body["pending_review"],
        body["unmatched"],
    ) == (2, 1, 1, 1)


async def test_reconciliation_stats_bucket_distribution(client: AsyncClient, db, test_user: User) -> None:
    statement = await _create_approved_statement(db, test_user)
    txns = [_make_txn(statement, amount=Decimal(str(10 + i))) for i in range(4)]
    db.add_all(txns)
    await db.flush()
    db.add_all(
        [
            ReconciliationMatchFactory.build(
                atomic_txn_id=txn.id,
                match_score=score,
                status=ReconciliationStatus.AUTO_ACCEPTED if score >= 80 else ReconciliationStatus.PENDING_REVIEW,
                journal_entry_ids=[],
            )
            for txn, score in zip(txns, [55, 70, 85, 95])
        ]
    )
    await db.commit()

    stats = (resp := await client.get("/reconciliation/stats")).json()
    assert (
        resp.status_code == 200
        and {
            "total_transactions",
            "matched_transactions",
            "unmatched_transactions",
            "pending_review",
            "auto_accepted",
            "match_rate",
            "score_distribution",
        }
        <= stats.keys()
    )
    assert (
        stats["total_transactions"],
        stats["matched_transactions"],
        stats["match_rate"],
        stats["score_distribution"],
    ) == (4, 2, 50.0, {"0-59": 1, "60-79": 1, "80-89": 1, "90-100": 1})


async def test_unmatched_exclusions_are_tenant_scoped(client: AsyncClient, db, test_user: User) -> None:
    statement = await _create_approved_statement(db, test_user)
    source_collision, visible = (
        _make_txn(statement, amount=Decimal("4.00")),
        _make_txn(statement, amount=Decimal("5.00")),
    )
    other_user = await UserFactory.create_async(db)
    other_txn = _make_txn(await _create_approved_statement(db, other_user), amount=Decimal("6.00"))
    db.add_all([source_collision, visible, other_txn])
    await db.flush()
    db.add_all(
        [
            JournalEntry(
                user_id=other_user.id,
                entry_date=date.today(),
                memo="Foreign source-id collision",
                source_type=JournalEntrySourceType.AUTO_PARSED,
                source_id=source_collision.id,
                status=JournalEntryStatus.DRAFT,
            ),
            ReconciliationMatchFactory.build(
                atomic_txn_id=other_txn.id, match_score=Decimal("80"), journal_entry_ids=[]
            ),
        ]
    )
    await db.commit()

    unmatched = (resp := await client.get("/reconciliation/unmatched", params={"limit": 50, "offset": 0})).json()
    assert (
        resp.status_code == 200
        and unmatched["total"] == 2
        and {i["id"] for i in unmatched["items"]} == {str(source_collision.id), str(visible.id)}
    )
