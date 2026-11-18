from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.cash_flow as cf_mod
from src.audit import Money
from src.identity import User
from src.ledger import AccountType, Entry, calculate_account_balance, post_entry
from src.reporting import generate_cash_flow
from tests.reporting._report_fixtures import seed_accounts


async def test_flow26_cash_flow_direct_method_invariants(db: AsyncSession, test_user: User) -> None:
    cash_hand, cash_bank, eq, rev, off, equip, inv, cap_gain, loan = await seed_accounts(
        db,
        test_user.id,
        ("Cash on Hand", AccountType.ASSET, "SGD", {"code": "1000"}),
        ("Bank Checking", AccountType.ASSET, "SGD", {"code": "1001"}),
        ("Opening Equity", AccountType.EQUITY, "SGD", {"code": "3000"}),
        ("Consulting", AccountType.INCOME, "SGD", {"code": "4000"}),
        ("Office Exp", AccountType.EXPENSE, "SGD", {"code": "5000"}),
        ("Equipment", AccountType.ASSET, "SGD", {"code": "1500"}),
        ("Securities", AccountType.ASSET, "SGD", {"code": "1200"}),
        ("Capital Gains", AccountType.INCOME, "SGD", {"code": "4100"}),
        ("Loan Payable", AccountType.LIABILITY, "SGD", {"code": "2100"}),
    )
    for dt, memo, op, entry in (
        (
            date(2025, 12, 31),
            "Init hand",
            "flow26-init-hand",
            Entry.transfer(debit=cash_hand.id, credit=eq.id, money=Money(Decimal("2000.00"), "SGD")),
        ),
        (
            date(2025, 12, 31),
            "Init bank",
            "flow26-init-bank",
            Entry.transfer(debit=cash_bank.id, credit=eq.id, money=Money(Decimal("8000.00"), "SGD")),
        ),
        (
            date(2025, 12, 31),
            "Init inv",
            "flow26-init-inv",
            Entry.transfer(debit=inv.id, credit=eq.id, money=Money(Decimal("5000.00"), "SGD")),
        ),
        (
            date(2026, 1, 5),
            "Retainer",
            "op-rev",
            Entry.transfer(debit=cash_bank.id, credit=rev.id, money=Money(Decimal("6000.00"), "SGD")),
        ),
        (
            date(2026, 1, 10),
            "Supplies",
            "op-exp",
            Entry.transfer(debit=off.id, credit=cash_bank.id, money=Money(Decimal("1800.00"), "SGD")),
        ),
        (
            date(2026, 1, 12),
            "Equip",
            "inv-buy",
            Entry.transfer(
                debit=equip.id, credit=cash_bank.id, money=Money(Decimal("3500.00"), "SGD"), event_type="investment_buy"
            ),
        ),
        (
            date(2026, 1, 15),
            "Sec sale",
            "inv-sale",
            Entry.of(
                Entry.transfer(
                    debit=cash_bank.id,
                    credit=inv.id,
                    money=Money(Decimal("2500.00"), "SGD"),
                    event_type="investment_sell",
                ).legs[0],
                Entry.transfer(
                    debit=cash_bank.id,
                    credit=inv.id,
                    money=Money(Decimal("2000.00"), "SGD"),
                    event_type="investment_sell",
                ).legs[1],
                Entry.transfer(
                    debit=cash_bank.id,
                    credit=cap_gain.id,
                    money=Money(Decimal("500.00"), "SGD"),
                    event_type="investment_realized_pnl",
                ).legs[1],
            ),
        ),
        (
            date(2026, 1, 18),
            "Drawdown",
            "fin-draw",
            Entry.transfer(
                debit=cash_bank.id,
                credit=loan.id,
                money=Money(Decimal("10000.00"), "SGD"),
                event_type="bank_txn",
                tags={"economic_category": "LOAN_PRINCIPAL"},
            ),
        ),
        (
            date(2026, 1, 25),
            "Repay",
            "fin-rep",
            Entry.transfer(
                debit=loan.id,
                credit=cash_bank.id,
                money=Money(Decimal("4000.00"), "SGD"),
                event_type="bank_txn",
                tags={"economic_category": "LOAN_PRINCIPAL"},
            ),
        ),
    ):
        await post_entry(
            db, user_id=test_user.id, entry_date=dt, memo=memo, entry=entry, base_currency="SGD", operation=op
        )
    await db.commit()

    cash_ids = frozenset((cash_hand.id, cash_bank.id))
    rep = await generate_cash_flow(
        db,
        test_user.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
        cash_account_ids=cash_ids,
    )
    s, b = rep["summary"], rep["cash_bridge"]
    assert (
        s["operating_activities"],
        s["investing_activities"],
        s["financing_activities"],
        s["net_cash_flow"],
        s["beginning_cash"],
        s["ending_cash"],
    ) == (
        Decimal("4200.00"),
        Decimal("-1000.00"),
        Decimal("6000.00"),
        Decimal("9200.00"),
        Decimal("10000.00"),
        Decimal("19200.00"),
    )
    ledger_sum = sum((await calculate_account_balance(db, aid, test_user.id) for aid in cash_ids), Decimal("0.00"))
    assert s["ending_cash"] == ledger_sum
    assert (b["reconciles"], b["cash_delta"], b["unclassified_cash"], b["fx_effect"], b["discrepancy"]) == (
        True,
        Decimal("9200.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert all(len(rep[sec]) >= 2 for sec in ("operating", "investing", "financing"))
    assert (rep["proof_state"], rep["proof_reasons"]) == ("proven", [])


async def test_flow26_cash_flow_bridge_exposes_discrepancy_when_imbalanced(
    db: AsyncSession, test_user: User, monkeypatch
) -> None:
    cash, rev = await seed_accounts(
        db,
        test_user.id,
        ("Checking Imbalance", AccountType.ASSET, "SGD", {"code": "1002"}),
        ("Sales Imbalance", AccountType.INCOME, "SGD", {"code": "4001"}),
    )
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 2, 10),
        memo="Inflow",
        entry=Entry.transfer(debit=cash.id, credit=rev.id, money=Money(Decimal("500.00"), "SGD")),
        base_currency="SGD",
        operation="cf-inflow-test",
    )
    await db.commit()
    kw = dict(
        start_date=date(2026, 2, 1), end_date=date(2026, 2, 28), currency="SGD", cash_account_ids=frozenset([cash.id])
    )
    ok = await generate_cash_flow(db, test_user.id, **kw)
    assert (ok["cash_bridge"]["fx_effect"], ok["cash_bridge"]["discrepancy"], ok["cash_bridge"]["reconciles"]) == (
        Decimal("0.00"),
        Decimal("0.00"),
        True,
    )
    monkeypatch.setattr(cf_mod, "_line_total", lambda _items: Decimal("0.00"))
    bad = await generate_cash_flow(db, test_user.id, **kw)
    assert (bad["cash_bridge"]["fx_effect"], bad["cash_bridge"]["discrepancy"], bad["cash_bridge"]["reconciles"]) == (
        Decimal("0.00"),
        Decimal("500.00"),
        False,
    )
