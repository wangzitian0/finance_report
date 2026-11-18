from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression

from src.audit import JournalEntrySourceType, Money
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    Entry,
    JournalEntry,
    JournalEntryStatus,
    account_service,
    initialize_opening_positions,
    post_entry,
    submit_system_journal_entry,
)
from src.ledger.base.processing import PROCESSING_ACCOUNT_CODE, PROCESSING_ACCOUNT_DESCRIPTION
from src.reporting import generate_cash_flow
from src.reporting.extension.cash_flow import _cash_event_rows_statement
from tests.reporting._report_fixtures import post_lines, seed_accounts, seed_fx_rates


async def _report(db: AsyncSession, user_id, cash_ids):
    return await generate_cash_flow(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
        cash_account_ids=frozenset(cash_ids),
    )


async def test_AC_reporting_cash_events_1_and_2_touch_and_authoritative_classification(
    db: AsyncSession, test_user
) -> None:
    cash, recv, pay, inc, exp, equip, liab = await seed_accounts(
        db,
        test_user.id,
        ("Custody A", AccountType.ASSET),
        ("Receivable", AccountType.ASSET),
        ("Payable", AccountType.LIABILITY),
        ("Salary", AccountType.INCOME),
        ("Utilities", AccountType.EXPENSE),
        ("Equipment", AccountType.ASSET),
        ("Equipment Loan", AccountType.LIABILITY),
    )
    accrual = await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Non-cash accrual",
        [(recv, Direction.DEBIT, "500"), (inc, Direction.CREDIT, "500")],
    )
    financed = await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Financed",
        [(equip, Direction.DEBIT, "900"), (liab, Direction.CREDIT, "900")],
    )
    pay_acc = await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Payable accrual",
        [(exp, Direction.DEBIT, "200"), (pay, Direction.CREDIT, "200")],
    )
    recv_set = await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Recv set",
        [(cash, Direction.DEBIT, "500"), (recv, Direction.CREDIT, "500")],
        event_type="investment_buy",
    )
    pay_set = await post_lines(
        db, test_user.id, date(2026, 1, 15), "Pay set", [(pay, Direction.DEBIT, "200"), (cash, Direction.CREDIT, "200")]
    )
    inv = await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 15),
        memo="Explicit inv",
        entry=Entry.transfer(
            debit=equip.id, credit=cash.id, money=Money(Decimal("100"), "SGD"), event_type="investment_buy"
        ),
        base_currency="SGD",
        operation="reporting-cash-event-proof",
    )

    rep = await _report(db, test_user.id, {cash.id})
    assert rep["operating"] == rep["financing"] == [] and [i["amount"] for i in rep["investing"]] == [
        Decimal("-100.00")
    ]
    assert (rep["cash_bridge"]["unclassified_cash"], rep["proof_state"], rep["proof_reasons"]) == (
        Decimal("300.00"),
        "unproven",
        ["cash_event_classification_ambiguous", "cash_event_decision_unproven"],
    )
    by_id = {i["journal_entry_id"]: i for i in rep["event_lineage"]}
    assert all(e.id not in by_id for e in (accrual, financed, pay_acc)) and {recv_set.id, pay_set.id, inv.id} <= set(
        by_id
    )
    assert by_id[recv_set.id]["activity"] is None and by_id[pay_set.id]["activity"] is None
    assert (
        by_id[inv.id]["activity"],
        by_id[inv.id]["source_type"],
        by_id[inv.id]["decision_authority_state"],
        by_id[inv.id]["decision_anchor_id"],
        by_id[inv.id]["event_types"],
    ) == ("Investing", "system", "anchored", inv.decision_anchor_id, ["investment_buy"])


async def test_AC_reporting_cash_events_3_and_4_internal_transfers_and_fx_bridge(db: AsyncSession, test_user) -> None:
    cash_a, cash_b, proc = await seed_accounts(
        db,
        test_user.id,
        ("Custody A", AccountType.ASSET),
        ("Custody B", AccountType.ASSET),
        (
            "Processing",
            AccountType.ASSET,
            "SGD",
            {"code": PROCESSING_ACCOUNT_CODE, "is_system": True, "description": PROCESSING_ACCOUNT_DESCRIPTION},
        ),
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Direct",
        [(cash_b, Direction.DEBIT, "100"), (cash_a, Direction.CREDIT, "100")],
    )
    await post_lines(
        db, test_user.id, date(2026, 1, 15), "Out", [(proc, Direction.DEBIT, "40"), (cash_a, Direction.CREDIT, "40")]
    )
    await post_lines(
        db, test_user.id, date(2026, 1, 15), "In", [(cash_b, Direction.DEBIT, "40"), (proc, Direction.CREDIT, "40")]
    )
    rep = await _report(db, test_user.id, {cash_a.id, cash_b.id})
    assert rep["operating"] == rep["investing"] == rep["financing"] == [] and rep["summary"][
        "net_cash_flow"
    ] == Decimal("0.00")
    assert rep["cash_bridge"] == {
        "classified_activity": Decimal("0.00"),
        "unclassified_cash": Decimal("0.00"),
        "opening_stock_adjustment": Decimal("0.00"),
        "fx_effect": Decimal("0.00"),
        "cash_delta": Decimal("0.00"),
        "discrepancy": Decimal("0.00"),
        "reconciles": True,
    }
    assert (rep["proof_state"], rep["proof_reasons"]) == ("proven", [])

    usd_cash, usd_inc = await seed_accounts(
        db, test_user.id, ("USD Custody", AccountType.ASSET, "USD"), ("USD Income", AccountType.INCOME, "USD")
    )
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2026, 1, 1)),
        ("USD", "SGD", "1.35", date(2026, 1, 15)),
        ("USD", "SGD", "1.40", date(2026, 1, 31)),
        commit=False,
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "FX receipt",
        [(usd_cash, Direction.DEBIT, "100"), (usd_inc, Direction.CREDIT, "100")],
    )
    fx_rep = await _report(db, test_user.id, {cash_a.id, cash_b.id, usd_cash.id})
    assert (fx_rep["summary"]["operating_activities"], fx_rep["summary"]["ending_cash"]) == (
        Decimal("135.00"),
        Decimal("140.00"),
    )
    assert fx_rep["cash_bridge"] == {
        "classified_activity": Decimal("135.00"),
        "unclassified_cash": Decimal("0.00"),
        "opening_stock_adjustment": Decimal("0.00"),
        "fx_effect": Decimal("5.00"),
        "cash_delta": Decimal("140.00"),
        "discrepancy": Decimal("0.00"),
        "reconciles": True,
    }


async def test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries(
    db: AsyncSession, test_user
) -> None:
    foreign_user = User(email=f"foreign-{uuid4()}@example.com", hashed_password="hashed")
    db.add(foreign_user)
    await db.flush()
    cash, own_inc = await seed_accounts(
        db, test_user.id, ("Custody A", AccountType.ASSET), ("Own Income", AccountType.INCOME)
    )
    f_cash, f_inc = await seed_accounts(
        db, foreign_user.id, ("Foreign Cash", AccountType.ASSET), ("Foreign Income", AccountType.INCOME)
    )
    await post_lines(
        db,
        foreign_user.id,
        date(2026, 1, 15),
        "Foreign",
        [(f_cash, Direction.DEBIT, "50"), (f_inc, Direction.CREDIT, "50")],
    )
    own = await post_lines(
        db, test_user.id, date(2026, 1, 15), "Own", [(cash, Direction.DEBIT, "20"), (own_inc, Direction.CREDIT, "20")]
    )

    stmt = _cash_event_rows_statement(test_user.id, end_date=date(2026, 1, 31), cash_account_ids=frozenset({cash.id}))
    eq_cols = {
        (el.left.table.name, el.left.name)
        for el in visitors.iterate(stmt)
        if isinstance(el, BinaryExpression)
        and el.operator is operators.eq
        and getattr(el.left, "table", None) is not None
    }
    assert {("journal_entries", "user_id"), ("accounts", "user_id")} <= eq_cols
    assert (
        len(
            [
                el
                for el in visitors.iterate(stmt)
                if isinstance(el, BinaryExpression)
                and el.operator is operators.ne
                and getattr(el.left, "name", None) == "user_id"
            ]
        )
        == 1
    )
    assert (
        len(
            [
                el
                for el in visitors.iterate(stmt)
                if isinstance(el, BinaryExpression)
                and el.operator is operators.in_op
                and getattr(el.left, "name", None) == "account_id"
            ]
        )
        == 1
    )

    rep = await _report(db, test_user.id, {cash.id})
    assert rep["summary"]["net_cash_flow"] == Decimal("20.00") and len(rep["event_lineage"]) == 1
    assert (
        rep["event_lineage"][0]["journal_entry_id"],
        rep["event_lineage"][0]["activity"],
        rep["event_lineage"][0]["reason_code"],
    ) == (own.id, "Operating", None)


async def test_AC_reporting_cash_events_6_and_7_one_projection_and_proof_state(db: AsyncSession, test_user) -> None:
    cash, income = await seed_accounts(
        db,
        test_user.id,
        ("Generic Custody", AccountType.ASSET, "SGD", {"code": "AUTO-BANK"}),
        ("Income", AccountType.INCOME),
    )
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 15),
        memo="Anchored",
        entry=Entry.transfer(debit=cash.id, credit=income.id, money=Money(Decimal("30"), "SGD")),
        base_currency="SGD",
        operation="reporting-cash-event-anchored-receipt",
    )
    proven = await _report(db, test_user.id, {cash.id})
    standalone = await generate_cash_flow(
        db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )
    assert proven["summary"] == standalone["summary"] and proven["proof_state"] == "proven"
    assert (standalone["proof_state"], standalone["proof_reasons"]) == (
        "unproven",
        ["cash_identity_compatibility_fallback"],
    )
    await post_lines(
        db, test_user.id, date(2026, 1, 15), "Legacy", [(cash, Direction.DEBIT, "10"), (income, Direction.CREDIT, "10")]
    )
    unanchored = await _report(db, test_user.id, {cash.id})
    assert (unanchored["proof_state"], unanchored["proof_reasons"]) == ("unproven", ["cash_event_decision_unproven"])


async def test_AC_reporting_cash_events_8_event_lineage_exposes_ledger_and_decision_anchors(
    db: AsyncSession, test_user
) -> None:
    cash, inc, liab = await seed_accounts(
        db,
        test_user.id,
        ("Custody", AccountType.ASSET),
        ("Income", AccountType.INCOME),
        ("Loan", AccountType.LIABILITY),
    )
    voided = await post_lines(
        db, test_user.id, date(2026, 1, 15), "Voided", [(cash, Direction.DEBIT, "90"), (inc, Direction.CREDIT, "90")]
    )
    reversal = await post_lines(
        db, test_user.id, date(2026, 1, 15), "VOID", [(inc, Direction.DEBIT, "90"), (cash, Direction.CREDIT, "90")]
    )
    voided.status, voided.void_reason, voided.void_reversal_entry_id = (
        JournalEntryStatus.VOID,
        "Counterfactual",
        reversal.id,
    )
    await db.flush()
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Mixed",
        [(cash, Direction.DEBIT, "100"), (inc, Direction.CREDIT, "60"), (liab, Direction.CREDIT, "40")],
    )
    rep = await _report(db, test_user.id, {cash.id})
    assert rep["operating"] == rep["financing"] == [] and (
        rep["proof_state"],
        rep["proof_reasons"],
        rep["cash_bridge"]["unclassified_cash"],
    ) == ("unproven", ["cash_event_classification_ambiguous", "cash_event_decision_unproven"], Decimal("100.00"))
    ev = rep["event_lineage"][0]
    assert (
        ev["activity"],
        ev["reason_code"],
        ev["source_type"],
        ev["source_id"],
        ev["decision_anchor_id"],
        ev["decision_authority_state"],
        ev["event_types"],
    ) == (None, "cash_event_classification_ambiguous", "manual", None, None, "legacy_unproven", [])
    assert ev["journal_entry_id"] != voided.id


async def test_AC_reporting_cash_events_12_statement_balance_sheet_categories_classify(
    db: AsyncSession, test_user
) -> None:
    cash, loans, invs, broker_cash = await seed_accounts(
        db,
        test_user.id,
        ("Main Checking", AccountType.ASSET),
        ("Loans Payable", AccountType.LIABILITY),
        ("Investments", AccountType.ASSET),
        ("Brokerage Custody Cash", AccountType.ASSET),
    )

    async def post_stmt(
        dt: date, memo: str, d_acc: Account, c_acc: Account, amt: str, cat: str, st: JournalEntrySourceType, op: str
    ) -> JournalEntry:
        return await submit_system_journal_entry(
            db,
            user_id=test_user.id,
            entry_date=dt,
            memo=memo,
            lines_data=[
                {
                    "account_id": d_acc.id,
                    "direction": Direction.DEBIT,
                    "amount": Decimal(amt),
                    "currency": "SGD",
                    "event_type": "bank_txn",
                    "tags": {"economic_category": cat} if d_acc.id != cash.id else None,
                },
                {
                    "account_id": c_acc.id,
                    "direction": Direction.CREDIT,
                    "amount": Decimal(amt),
                    "currency": "SGD",
                    "event_type": "bank_txn",
                    "tags": {"economic_category": cat} if c_acc.id != cash.id else None,
                },
            ],
            base_currency="SGD",
            operation=op,
            source_type=st,
        )

    e_loan = await post_stmt(
        date(2026, 1, 10),
        "Loan",
        loans,
        cash,
        "400.00",
        "LOAN_PRINCIPAL",
        JournalEntrySourceType.AUTO_PARSED,
        "stmt-loan",
    )
    e_inv = await post_stmt(
        date(2026, 1, 12),
        "Buy",
        invs,
        cash,
        "600.00",
        "INVESTMENT_TRADE",
        JournalEntrySourceType.USER_CONFIRMED,
        "stmt-trade",
    )
    e_sale = await post_stmt(
        date(2026, 1, 14),
        "Sale",
        cash,
        broker_cash,
        "250.00",
        "INVESTMENT_SALE",
        JournalEntrySourceType.AUTO_PARSED,
        "stmt-sale",
    )
    e_mis = await post_stmt(
        date(2026, 1, 16),
        "Spoof",
        invs,
        cash,
        "50.00",
        "LOAN_PRINCIPAL",
        JournalEntrySourceType.AUTO_PARSED,
        "stmt-mis",
    )
    await db.flush()
    rep = await _report(db, test_user.id, {cash.id})
    assert (
        rep["operating"] == []
        and [(i["subcategory"], i["amount"]) for i in rep["investing"]] == [("Investments", Decimal("-600.00"))]
        and [(i["subcategory"], i["amount"]) for i in rep["financing"]] == [("Loans Payable", Decimal("-400.00"))]
    )
    assert (
        rep["summary"]["operating_activities"],
        rep["summary"]["investing_activities"],
        rep["summary"]["financing_activities"],
        rep["summary"]["net_cash_flow"],
    ) == (Decimal("0.00"), Decimal("-600.00"), Decimal("-400.00"), Decimal("-800.00"))
    assert (
        rep["cash_bridge"]["classified_activity"],
        rep["cash_bridge"]["unclassified_cash"],
        rep["cash_bridge"]["reconciles"],
    ) == (Decimal("-1000.00"), Decimal("200.00"), True)
    by_id = {i["journal_entry_id"]: i for i in rep["event_lineage"]}
    assert set(by_id) == {e_loan.id, e_inv.id, e_sale.id, e_mis.id} and (
        by_id[e_loan.id]["activity"],
        by_id[e_inv.id]["activity"],
        by_id[e_sale.id]["activity"],
        by_id[e_mis.id]["activity"],
    ) == ("Financing", "Investing", None, None)


async def test_AC_reporting_2832_1_cross_period_gap_plug_bridges_as_opening_stock_adjustment(
    db: AsyncSession, test_user
) -> None:
    cash, salary = await seed_accounts(
        db, test_user.id, ("DBS Checking", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    gap_equity = await account_service.get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={cash.id: Decimal("10000.00")},
        currency="SGD",
        base_currency="SGD",
    )
    for dt, memo, d_acc, c_acc, amt, ev, op in (
        (date(2026, 1, 10), "Jan Salary", cash, salary, "2000.00", "bank_txn", "jan-salary"),
        (
            date(2026, 1, 25),
            "Gap plug",
            cash,
            gap_equity,
            "3000.00",
            account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE,
            "cross-period-gap-test",
        ),
    ):
        await submit_system_journal_entry(
            db,
            user_id=test_user.id,
            entry_date=dt,
            memo=memo,
            lines_data=[
                {
                    "account_id": d_acc.id,
                    "direction": Direction.DEBIT,
                    "amount": Decimal(amt),
                    "currency": "SGD",
                    "event_type": ev,
                },
                {
                    "account_id": c_acc.id,
                    "direction": Direction.CREDIT,
                    "amount": Decimal(amt),
                    "currency": "SGD",
                    "event_type": ev,
                },
            ],
            base_currency="SGD",
            operation=op,
        )
    await db.flush()
    rep = await _report(db, test_user.id, {cash.id})
    assert (
        rep["proof_state"],
        rep["proof_reasons"],
        rep["summary"]["beginning_cash"],
        rep["summary"]["operating_activities"],
        rep["summary"]["net_cash_flow"],
        rep["summary"]["ending_cash"],
    ) == ("proven", [], Decimal("10000.00"), Decimal("2000.00"), Decimal("2000.00"), Decimal("15000.00"))
    assert (
        rep["cash_bridge"]["opening_stock_adjustment"],
        rep["cash_bridge"]["unclassified_cash"],
        rep["cash_bridge"]["reconciles"],
    ) == (Decimal("3000.00"), Decimal("0.00"), True)
