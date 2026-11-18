from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import event, insert, inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
from src.audit.extension.trace_repository import _row_from_record
from src.audit.orm import TraceRecordParentRow, TraceRecordRow
from src.config import settings
from src.extraction import RuleType
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    initialize_opening_positions,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate, StockPrice
from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement

STANDARD_CHART_SPEC: tuple[tuple[str, AccountType], ...] = (
    ("Cash", AccountType.ASSET),
    ("Credit Card", AccountType.LIABILITY),
    ("Owner Equity", AccountType.EQUITY),
    ("Salary", AccountType.INCOME),
    ("Dining", AccountType.EXPENSE),
)


async def seed_accounts(
    db: AsyncSession,
    user_id: UUID,
    *specs: tuple[Any, ...],
    currency: str = "SGD",
    commit: bool = False,
) -> list[Account]:
    accounts = []
    for spec in specs:
        name, acct_type = spec[0], spec[1]
        acct_ccy = spec[2] if len(spec) > 2 else currency
        extra = spec[3] if len(spec) > 3 else {}
        accounts.append(Account(user_id=user_id, name=name, type=acct_type, currency=acct_ccy, **extra))
    db.add_all(accounts)
    if commit:
        await db.commit()
        for account in accounts:
            await db.refresh(account)
    else:
        await db.flush()
    return accounts


async def build_standard_chart_of_accounts(db: AsyncSession, user_id: UUID, *, currency: str = "SGD") -> list[Account]:
    return await seed_accounts(db, user_id, *STANDARD_CHART_SPEC, currency=currency, commit=True)


def make_entry(
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines: list[tuple[Any, ...]],
    *,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
    event_type: str | None = None,
) -> JournalEntry:
    entry = JournalEntry(user_id=user_id, entry_date=entry_date, memo=memo, source_type=source_type, status=status)
    entry.lines = [
        JournalLine(
            account_id=item[0].id,
            direction=item[1],
            amount=Decimal(str(item[2])),
            currency=item[3] if len(item) > 3 else item[0].currency or "SGD",
            fx_rate=item[4] if len(item) > 4 else None,
            tags=tags,
            event_type=item[5] if len(item) > 5 else event_type,
        )
        for item in lines
    ]
    return entry


def make_pair_entry(
    user_id: UUID,
    entry_date: date,
    memo: str,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal | str,
    *,
    currency: str = "SGD",
    fx_rate: Decimal | None = None,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
    event_type: str | None = None,
) -> JournalEntry:
    return make_entry(
        user_id,
        entry_date,
        memo,
        [
            (debit_account, Direction.DEBIT, amount, currency, fx_rate),
            (credit_account, Direction.CREDIT, amount, currency, fx_rate),
        ],
        status=status,
        source_type=source_type,
        tags=tags,
        event_type=event_type,
    )


async def post_lines(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines: list[tuple[Any, ...]],
    *,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
    event_type: str | None = None,
    commit: bool = False,
) -> JournalEntry:
    entry = make_entry(
        user_id, entry_date, memo, lines, status=status, source_type=source_type, tags=tags, event_type=event_type
    )
    db.add(entry)
    await (db.commit() if commit else db.flush())
    return entry


async def post_pair(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal | str,
    *,
    currency: str | None = None,
    fx_rate: Decimal | None = None,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
    event_type: str | None = None,
    commit: bool = False,
) -> JournalEntry:
    ccy = currency if currency is not None else (debit_account.currency or "SGD")
    return await post_lines(
        db,
        user_id,
        entry_date,
        memo,
        [
            (debit_account, Direction.DEBIT, amount, ccy, fx_rate),
            (credit_account, Direction.CREDIT, amount, ccy, fx_rate),
        ],
        status=status,
        source_type=source_type,
        tags=tags,
        event_type=event_type,
        commit=commit,
    )


async def seed_fx_rates(
    db: AsyncSession, *rates: tuple[str, str, Decimal | str, date], commit: bool = True
) -> list[FxRate]:
    models = [
        FxRate(base_currency=b, quote_currency=q, rate=Decimal(str(r)), rate_date=d, source="test")
        for b, q, r, d in rates
    ]
    db.add_all(models)
    await (db.commit() if commit else db.flush())
    return models


async def seed_valuations(
    db: AsyncSession,
    user_id: UUID,
    *specs: tuple[Any, ...],
    commit: bool = False,
) -> list[ManualValuationSnapshot]:
    snaps = [
        ManualValuationSnapshot(
            user_id=user_id,
            component_type=spec[0],
            liquidity_class=spec[1],
            value=Decimal(str(spec[2])),
            currency=spec[3],
            as_of_date=spec[4],
            source=spec[5],
            **(spec[6] if len(spec) > 6 else {}),
        )
        for spec in specs
    ]
    db.add_all(snaps)
    await (db.commit() if commit else db.flush())
    return snaps


@contextmanager
def count_sql_statements(db_engine: Any) -> Iterator[dict[str, int]]:
    counter = {"count": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
    try:
        yield counter
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _count)


async def all_pages(
    client: Any, path: str, params: dict[str, Any], *, limit: int, item_key: str
) -> tuple[list[Any], int]:
    items: list[Any] = []
    offset = 0
    total: int | None = None
    while True:
        resp = await client.get(path, params={**params, "limit": limit, "offset": offset})
        assert resp.status_code == 200, resp.text
        page = resp.json()
        assert (page["limit"], page["offset"]) == (limit, offset)
        if total is None:
            total = page["total"]
        assert page["total"] == total
        assert len(page[item_key]) == min(limit, max(total - offset, 0))
        items.extend(page[item_key])
        offset += limit
        if offset >= total:
            return items, total


YEAR_ENTRY_COUNT = 1000
YEAR_PERIOD = {"start_date": "2026-01-01", "end_date": "2026-12-31", "as_of_date": "2026-12-31", "currency": "SGD"}
JUNE_PERIOD = {"start_date": "2026-06-01", "end_date": "2026-06-30", "as_of_date": "2026-06-30", "currency": "SGD"}


async def seed_ready_package_state(
    db: AsyncSession,
    user_id: UUID,
    monkeypatch: Any,
    *,
    opening_date: date = date(2025, 1, 1),
    opening_cash: Decimal = Decimal("10000"),
    with_card: bool = False,
) -> tuple[Account, Account, Account]:
    from hashlib import sha256
    from src.extraction import BankStatementStatus, StatementSummary

    monkeypatch.setattr(settings, "enable_ai_classification", True)
    cats = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}

    async def proposer(txns, _policy):
        return [
            CategoryProposal(category=cats[i.description].value, confidence=99, reason="readiness-fixture")
            for i in txns
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank, securities, income = await seed_accounts(
        db, user_id, ("DBS", AccountType.ASSET), ("Securities", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=opening_date,
        balances={bank.id: opening_cash, securities.id: Decimal("0")},
        currency="SGD",
        base_currency="SGD",
    )
    if with_card:
        [card] = await seed_accounts(db, user_id, ("Visa card", AccountType.LIABILITY))
        db.add(
            StatementSummary(
                user_id=user_id,
                file_hash=sha256(f"{user_id}:{card.id}:2026-05-01".encode()).hexdigest(),
                institution="DBS",
                account_id=card.id,
                currency="SGD",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 28),
                opening_balance=Decimal("1000.00"),
                closing_balance=Decimal("1200.00"),
                status=BankStatementStatus.APPROVED,
            )
        )
    db.add(
        ClassificationRule(
            user_id=user_id,
            created_by=user_id,
            version_number=1,
            effective_date=date(2026, 1, 1),
            rule_name="Reviewed investment",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Buy security"]},
            tag_mappings={"intent": "transfer"},
            default_account_id=securities.id,
        )
    )
    await _ingest_reviewed_bank_statement(db, user_id=user_id, bank=bank, securities_id=securities.id)
    await db.commit()
    return bank, securities, income


async def seed_year_of_anchored_entries(
    db: AsyncSession, user_id: UUID, *, bank: Account | None = None, categories: Sequence[str] = ()
) -> None:
    bank = bank or Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    exp_names = list(categories) or ["Groceries"]
    expenses = [
        Account(user_id=user_id, name=n.title(), code=f"5{i:03d}", type=AccountType.EXPENSE, currency="SGD")
        for i, n in enumerate(exp_names, 1)
    ]
    db.add_all([bank, salary, *expenses])
    await db.flush()
    policy, scope, now = SystemJournalCommandPolicy(), TraceScope.tenant(user_id), datetime.now(UTC)
    trace_rows, parent_rows, entry_rows, line_rows = [], [], [], []
    for idx in range(YEAR_ENTRY_COUNT):
        e_date, memo, is_inc = date(2026, 1, 1) + timedelta(days=idx % 365), f"year-scale entry {idx}", idx % 2 == 0
        amt = Decimal("3000.00") if is_inc else Decimal(f"{idx % 90 + 10}.25")
        exp = expenses[idx % len(expenses)]
        debit, credit = (bank.id, salary.id) if is_inc else (exp.id, bank.id)
        counter_id = salary.id if is_inc else exp.id
        tags = {"economic_category": "SALARY" if is_inc else exp_names[idx % len(exp_names)]}
        lines_data = [
            {"account_id": debit, "direction": Direction.DEBIT, "amount": amt, "currency": "SGD"},
            {"account_id": credit, "direction": Direction.CREDIT, "amount": amt, "currency": "SGD"},
        ]
        target = journal_command_target(
            entry_date=e_date,
            memo=memo,
            lines_data=lines_data,
            base_currency="SGD",
            source_identity=f"ledger-system:year-scale:{idx}",
        )
        obs = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=VersionedTraceRef("ledger_system_input", "year-scale", "1"),
            authority=policy.authority,
            result=TraceResult.PASS,
            execution_id=f"ledger-system:{target.id}:{target.version}",
            evidence_manifest_digest=target.version,
            occurred_at=now,
            score=None,
            reason_code="ledger_system_command_materialized",
        )
        dec = TraceRecord.decision(
            scope=scope, target=target, policy=policy, execution_id=obs.execution_id, occurred_at=now, parents=(obs,)
        )
        trace_rows.extend((_row_from_record(obs), _row_from_record(dec)))
        parent_rows.append(
            {"scope_kind": scope.kind, "scope_id": scope.id, "record_id": dec.record_id, "parent_id": obs.record_id}
        )
        eid = uuid4()
        entry_rows.append(
            {
                "id": eid,
                "user_id": user_id,
                "entry_date": e_date,
                "memo": memo,
                "source_type": JournalEntrySourceType.SYSTEM,
                "source_id": None,
                "decision_anchor_id": dec.record_id,
                "decision_authority_state": JournalEntryAuthorityState.ANCHORED,
                "base_currency": "SGD",
                "status": JournalEntryStatus.POSTED,
                "void_reason": None,
                "void_reversal_entry_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        for lno, line in enumerate(lines_data):
            line_rows.append(
                {
                    "id": uuid4(),
                    "journal_entry_id": eid,
                    "line_no": lno,
                    "account_id": line["account_id"],
                    "direction": line["direction"],
                    "amount": line["amount"],
                    "currency": "SGD",
                    "fx_rate": None,
                    "event_type": None,
                    "tags": tags if categories and line["account_id"] == counter_id else None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    cols = [(a.key, a.columns[0].name) for a in sa_inspect(TraceRecordRow).column_attrs]
    await db.execute(insert(TraceRecordRow.__table__), [{c: getattr(r, k) for k, c in cols} for r in trace_rows])
    await db.execute(insert(TraceRecordParentRow), parent_rows)
    await db.execute(insert(JournalEntry), entry_rows)
    await db.execute(insert(JournalLine), line_rows)
    await db.execute(text("ANALYZE trace_records, trace_record_parents"))
    await db.commit()


async def seed_reviewed_statement(db: AsyncSession, user_id: UUID, monkeypatch: Any) -> StockPrice:
    from tests.portfolio.test_portfolio_router import _make_atomic_position, _make_managed_position

    await seed_ready_package_state(db, user_id, monkeypatch)
    [brokerage] = await seed_accounts(db, user_id, ("Brokerage", AccountType.ASSET))
    price = StockPrice(
        symbol="AAPL", price=Decimal("125.05"), currency="SGD", price_date=date(2026, 6, 30), source="recorded-provider"
    )
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=user_id,
                component_type=ManualValuationComponentType.PROPERTY_VALUE,
                liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
                value=Decimal("250000.00"),
                currency="SGD",
                as_of_date=date(2026, 6, 20),
                source="Property appraisal",
            ),
            _make_managed_position(
                user_id,
                brokerage.id,
                "AAPL",
                quantity=Decimal("10"),
                cost_basis=Decimal("1000.00"),
                acquisition_date=date(2026, 6, 2),
            ),
            _make_atomic_position(
                user_id,
                "AAPL",
                broker="Brokerage",
                quantity=Decimal("10"),
                market_value=Decimal("1200.00"),
                snapshot_date=date(2026, 6, 30),
                dedup_hash="s8-aapl-2026-06-30",
            ),
            price,
        ]
    )
    await db.commit()
    return price
