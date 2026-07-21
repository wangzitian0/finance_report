"""Adversarial proofs for the reporting-owned cash-touch event projection."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression

from src.audit import Money
from src.identity import User
from src.ledger import Account, AccountType, Direction, Entry, JournalEntry, JournalEntryStatus, JournalLine, post_entry
from src.ledger.base.processing import PROCESSING_ACCOUNT_CODE, PROCESSING_ACCOUNT_DESCRIPTION
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_cash_flow
from src.reporting.extension.cash_flow import _cash_event_rows_statement


async def _account(db: AsyncSession, user_id, name: str, account_type: AccountType, **values) -> Account:
    currency = values.pop("currency", "SGD")
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency, **values)
    db.add(account)
    await db.flush()
    return account


async def _entry(
    db: AsyncSession,
    user_id,
    memo: str,
    lines,
    *,
    status=JournalEntryStatus.POSTED,
    event_type: str | None = None,
    entry_date: date = date(2026, 1, 15),
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        status=status,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=direction,
            amount=amount,
            currency=account.currency,
            event_type=event_type,
        )
        for account, direction, amount in lines
    )
    await db.flush()
    return entry


async def _report(db: AsyncSession, user_id, cash_ids):
    return await generate_cash_flow(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
        cash_account_ids=frozenset(cash_ids),
    )


async def test_AC_reporting_cash_events_1_2_only_cash_touch_events_are_classified(db: AsyncSession, test_user):
    """AC-reporting.cash-events.1 AC-reporting.cash-events.2: classify only cash-touch settlement events."""
    cash = await _account(db, test_user.id, "Custody A", AccountType.ASSET)
    receivable = await _account(db, test_user.id, "Receivable", AccountType.ASSET)
    payable = await _account(db, test_user.id, "Payable", AccountType.LIABILITY)
    income = await _account(db, test_user.id, "Salary", AccountType.INCOME)
    expense = await _account(db, test_user.id, "Utilities", AccountType.EXPENSE)
    equipment = await _account(db, test_user.id, "Equipment", AccountType.ASSET)
    liability = await _account(db, test_user.id, "Equipment Loan", AccountType.LIABILITY)
    await _entry(
        db,
        test_user.id,
        "Non-cash accrual",
        [(receivable, Direction.DEBIT, Decimal("500")), (income, Direction.CREDIT, Decimal("500"))],
    )
    await _entry(
        db,
        test_user.id,
        "Financed equipment",
        [(equipment, Direction.DEBIT, Decimal("900")), (liability, Direction.CREDIT, Decimal("900"))],
    )
    await _entry(
        db,
        test_user.id,
        "Non-cash payable accrual",
        [(expense, Direction.DEBIT, Decimal("200")), (payable, Direction.CREDIT, Decimal("200"))],
    )
    receivable_settlement = await _entry(
        db,
        test_user.id,
        "Receivable settlement",
        [(cash, Direction.DEBIT, Decimal("500")), (receivable, Direction.CREDIT, Decimal("500"))],
        event_type="investment_buy",
    )
    payable_settlement = await _entry(
        db,
        test_user.id,
        "Payable settlement",
        [(payable, Direction.DEBIT, Decimal("200")), (cash, Direction.CREDIT, Decimal("200"))],
    )
    investment = await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 15),
        memo="Explicit investment purchase",
        entry=Entry.transfer(
            debit=equipment.id,
            credit=cash.id,
            money=Money(Decimal("100"), "SGD"),
            event_type="investment_buy",
        ),
        base_currency="SGD",
        operation="reporting-cash-event-proof",
    )

    report = await _report(db, test_user.id, {cash.id})

    assert report["operating"] == []
    assert [item["amount"] for item in report["investing"]] == [Decimal("-100.00")]
    assert report["financing"] == []
    assert report["cash_bridge"]["unclassified_cash"] == Decimal("300.00")
    assert report["proof_state"] == "unproven"
    assert report["proof_reasons"] == [
        "cash_event_classification_ambiguous",
        "cash_event_decision_unproven",
    ]
    lineage_by_entry = {item["journal_entry_id"]: item for item in report["event_lineage"]}
    assert lineage_by_entry[receivable_settlement.id]["activity"] is None
    assert lineage_by_entry[payable_settlement.id]["activity"] is None
    assert lineage_by_entry[investment.id]["activity"] == "Investing"
    assert lineage_by_entry[investment.id]["source_type"] == "system"
    assert lineage_by_entry[investment.id]["decision_authority_state"] == "anchored"
    assert lineage_by_entry[investment.id]["decision_anchor_id"] == investment.decision_anchor_id
    assert lineage_by_entry[investment.id]["event_types"] == ["investment_buy"]


async def test_AC_reporting_cash_events_3_4_internal_transfers_are_neutral_and_bridge_ties(db: AsyncSession, test_user):
    """AC-reporting.cash-events.3 AC-reporting.cash-events.4: transfers are neutral and the bridge ties."""
    cash_a = await _account(db, test_user.id, "Custody A", AccountType.ASSET)
    cash_b = await _account(db, test_user.id, "Custody B", AccountType.ASSET)
    processing = await _account(
        db,
        test_user.id,
        "Processing",
        AccountType.ASSET,
        code=PROCESSING_ACCOUNT_CODE,
        is_system=True,
        description=PROCESSING_ACCOUNT_DESCRIPTION,
    )
    await _entry(
        db,
        test_user.id,
        "Direct transfer",
        [(cash_b, Direction.DEBIT, Decimal("100")), (cash_a, Direction.CREDIT, Decimal("100"))],
    )
    await _entry(
        db,
        test_user.id,
        "Transfer out",
        [(processing, Direction.DEBIT, Decimal("40")), (cash_a, Direction.CREDIT, Decimal("40"))],
    )
    await _entry(
        db,
        test_user.id,
        "Transfer in",
        [(cash_b, Direction.DEBIT, Decimal("40")), (processing, Direction.CREDIT, Decimal("40"))],
    )

    report = await _report(db, test_user.id, {cash_a.id, cash_b.id})

    assert report["operating"] == report["investing"] == report["financing"] == []
    assert report["summary"]["net_cash_flow"] == Decimal("0.00")
    assert report["cash_bridge"] == {
        "classified_activity": Decimal("0.00"),
        "unclassified_cash": Decimal("0.00"),
        "fx_effect": Decimal("0.00"),
        "cash_delta": Decimal("0.00"),
        "reconciles": True,
    }

    usd_cash = await _account(db, test_user.id, "USD Custody", AccountType.ASSET, currency="USD")
    usd_income = await _account(db, test_user.id, "USD Income", AccountType.INCOME, currency="USD")
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2026, 1, 1),
                source="cash-event-proof",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.35"),
                rate_date=date(2026, 1, 15),
                source="cash-event-proof",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.40"),
                rate_date=date(2026, 1, 31),
                source="cash-event-proof",
            ),
        ]
    )
    await _entry(
        db,
        test_user.id,
        "Foreign-currency receipt",
        [(usd_cash, Direction.DEBIT, Decimal("100")), (usd_income, Direction.CREDIT, Decimal("100"))],
    )

    fx_report = await _report(db, test_user.id, {cash_a.id, cash_b.id, usd_cash.id})

    assert fx_report["summary"]["operating_activities"] == Decimal("135.00")
    assert fx_report["summary"]["ending_cash"] == Decimal("140.00")
    assert fx_report["cash_bridge"] == {
        "classified_activity": Decimal("135.00"),
        "unclassified_cash": Decimal("0.00"),
        "fx_effect": Decimal("5.00"),
        "cash_delta": Decimal("140.00"),
        "reconciles": True,
    }


async def test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries(db: AsyncSession, test_user):
    """AC-reporting.cash-events.5: neither a foreign header nor a foreign account can leak a cash event."""
    foreign_user = User(email=f"foreign-{uuid4()}@example.com", hashed_password="hashed")
    db.add(foreign_user)
    await db.flush()
    cash = await _account(db, test_user.id, "Custody A", AccountType.ASSET)
    own_income = await _account(db, test_user.id, "Own Income", AccountType.INCOME)
    foreign_cash = await _account(db, foreign_user.id, "Foreign Cash", AccountType.ASSET)
    foreign_income = await _account(db, foreign_user.id, "Foreign Income", AccountType.INCOME)
    await _entry(
        db,
        foreign_user.id,
        "Foreign header",
        [(foreign_cash, Direction.DEBIT, Decimal("50")), (foreign_income, Direction.CREDIT, Decimal("50"))],
    )
    own_entry = await _entry(
        db,
        test_user.id,
        "Own event",
        [(cash, Direction.DEBIT, Decimal("20")), (own_income, Direction.CREDIT, Decimal("20"))],
    )

    report = await _report(db, test_user.id, {cash.id})
    statement = _cash_event_rows_statement(test_user.id, end_date=date(2026, 1, 31))
    equality_columns = {
        (element.left.table.name, element.left.name)
        for element in visitors.iterate(statement)
        if isinstance(element, BinaryExpression)
        and element.operator is operators.eq
        and getattr(element.left, "table", None) is not None
    }
    foreign_account_guards = [
        element
        for element in visitors.iterate(statement)
        if isinstance(element, BinaryExpression)
        and element.operator is operators.ne
        and getattr(element.left, "name", None) == "user_id"
    ]

    assert {("journal_entries", "user_id"), ("accounts", "user_id")} <= equality_columns
    assert len(foreign_account_guards) == 1
    assert report["summary"]["net_cash_flow"] == Decimal("20.00")
    assert len(report["event_lineage"]) == 1
    assert report["event_lineage"][0]["journal_entry_id"] == own_entry.id
    assert report["event_lineage"][0]["activity"] == "Operating"
    assert report["event_lineage"][0]["reason_code"] is None


async def test_AC_reporting_cash_events_6_7_one_projection_serves_proven_and_unproven_consumers(
    db: AsyncSession, test_user
):
    """AC-reporting.cash-events.6 AC-reporting.cash-events.7: one projection reports exact proof state."""
    cash = await _account(db, test_user.id, "Generic Custody", AccountType.ASSET, code="AUTO-BANK")
    income = await _account(db, test_user.id, "Income", AccountType.INCOME)
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 15),
        memo="Anchored receipt",
        entry=Entry.transfer(
            debit=cash.id,
            credit=income.id,
            money=Money(Decimal("30"), "SGD"),
        ),
        base_currency="SGD",
        operation="reporting-cash-event-anchored-receipt",
    )

    proven = await _report(db, test_user.id, {cash.id})
    standalone = await generate_cash_flow(db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    assert proven["summary"] == standalone["summary"]
    assert proven["proof_state"] == "proven"
    assert standalone["proof_state"] == "unproven"
    assert standalone["proof_reasons"] == ["cash_identity_compatibility_fallback"]

    await _entry(
        db,
        test_user.id,
        "Legacy-unproven receipt",
        [(cash, Direction.DEBIT, Decimal("10")), (income, Direction.CREDIT, Decimal("10"))],
    )
    unanchored = await _report(db, test_user.id, {cash.id})

    assert unanchored["proof_state"] == "unproven"
    assert unanchored["proof_reasons"] == ["cash_event_decision_unproven"]


async def test_AC_reporting_cash_events_8_10_lineage_void_and_ambiguous_events_fail_closed(db: AsyncSession, test_user):
    """AC-reporting.cash-events.8: exact lineage survives while void and ambiguous events fail closed."""
    cash = await _account(db, test_user.id, "Custody", AccountType.ASSET)
    income = await _account(db, test_user.id, "Income", AccountType.INCOME)
    liability = await _account(db, test_user.id, "Loan", AccountType.LIABILITY)
    voided = await _entry(
        db,
        test_user.id,
        "Voided receipt",
        [(cash, Direction.DEBIT, Decimal("90")), (income, Direction.CREDIT, Decimal("90"))],
    )
    reversal = await _entry(
        db,
        test_user.id,
        "VOID: Voided receipt",
        [(income, Direction.DEBIT, Decimal("90")), (cash, Direction.CREDIT, Decimal("90"))],
    )
    voided.status = JournalEntryStatus.VOID
    voided.void_reason = "Counterfactual fixture"
    voided.void_reversal_entry_id = reversal.id
    await db.flush()
    await _entry(
        db,
        test_user.id,
        "Mixed event",
        [
            (cash, Direction.DEBIT, Decimal("100")),
            (income, Direction.CREDIT, Decimal("60")),
            (liability, Direction.CREDIT, Decimal("40")),
        ],
    )

    report = await _report(db, test_user.id, {cash.id})

    assert report["operating"] == report["financing"] == []
    assert report["proof_state"] == "unproven"
    assert report["proof_reasons"] == [
        "cash_event_classification_ambiguous",
        "cash_event_decision_unproven",
    ]
    assert report["cash_bridge"]["unclassified_cash"] == Decimal("100.00")
    assert report["event_lineage"][0]["activity"] is None
    assert report["event_lineage"][0]["reason_code"] == "cash_event_classification_ambiguous"
    assert report["event_lineage"][0]["journal_entry_id"] != voided.id
    assert report["event_lineage"][0]["source_type"] == "manual"
    assert report["event_lineage"][0]["source_id"] is None
    assert report["event_lineage"][0]["decision_anchor_id"] is None
    assert report["event_lineage"][0]["decision_authority_state"] == "legacy_unproven"
    assert report["event_lineage"][0]["event_types"] == []


def test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced():
    """AC-reporting.cash-events.9: the package initiative projects onto existing blocking gates."""
    from common.meta.data.projection import contract_index
    from common.reporting.contract import CONTRACT

    projected = contract_index([CONTRACT])["governance"]["reporting/authoritative-cash-event-projection"]

    assert len(projected["guarantees"]) == 10
    assert {guarantee["enforcing_gate"] for guarantee in projected["guarantees"]} == {
        "ci.backend",
        "ci.backend_integration",
        "ci.lint",
    }
