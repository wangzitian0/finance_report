from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.services.anomaly import detect_anomalies
from tests.factories import BankStatementFactory, BankStatementTransactionFactory


@pytest.mark.asyncio
async def test_detect_large_amount_anomaly(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    # Use 30 small txns so even with target included in avg,
    # avg ≈ (30*1 + 5000)/31 ≈ 162, ratio ≈ 30.8x > 10x threshold.
    for i in range(30):
        await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            amount=Decimal("1.00"),
            direction="DR",
            txn_date=date.today() - timedelta(days=(i % 29) + 1),
        )

    large_txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("5000.00"),
        direction="DR",
        txn_date=date.today(),
        description="HUGE PURCHASE ELECTRONICS",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, large_txn, user_id=test_user.id)
    types = [a.anomaly_type for a in anomalies]
    assert "LARGE_AMOUNT" in types


@pytest.mark.asyncio
async def test_no_anomalies_for_normal_transaction(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    for i in range(5):
        await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            amount=Decimal("50.00"),
            direction="DR",
            txn_date=date.today() - timedelta(days=i + 1),
            description=f"GROCERY STORE {i}",
        )

    normal_txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("55.00"),
        direction="DR",
        txn_date=date.today(),
        description="GROCERY STORE",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, normal_txn, user_id=test_user.id)
    types = [a.anomaly_type for a in anomalies]
    assert "LARGE_AMOUNT" not in types


@pytest.mark.asyncio
async def test_detect_new_merchant_anomaly(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("30.00"),
        direction="DR",
        txn_date=date.today(),
        description="BRANDNEWSHOP online",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, txn, user_id=test_user.id)
    types = [a.anomaly_type for a in anomalies]
    assert "NEW_MERCHANT" in types


@pytest.mark.asyncio
async def test_detect_weekend_large_anomaly(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    for i in range(5):
        await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            amount=Decimal("10.00"),
            direction="DR",
            txn_date=date.today() - timedelta(days=i + 1),
        )

    saturday = date.today()
    while saturday.weekday() != 5:
        saturday += timedelta(days=1)

    weekend_txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("500.00"),
        direction="DR",
        txn_date=saturday,
        description="WEEKEND SPLURGE",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, weekend_txn, user_id=test_user.id)
    types = [a.anomaly_type for a in anomalies]
    assert "WEEKEND_LARGE" in types


@pytest.mark.asyncio
async def test_detect_frequency_spike(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    today = date.today()

    for i in range(6):
        await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            amount=Decimal("10.00"),
            direction="DR",
            txn_date=today,
            description=f"COFFEESHOP order-{i}",
        )

    target_txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("10.00"),
        direction="DR",
        txn_date=today,
        description="COFFEESHOP order-7",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, target_txn, user_id=test_user.id)
    types = [a.anomaly_type for a in anomalies]
    assert "FREQUENCY_SPIKE" in types


@pytest.mark.asyncio
async def test_anomaly_result_has_severity(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    # avg includes target; 30*1 + 5000 / 31 ≈ 162, ratio ≈ 30.8x > 10x
    for i in range(30):
        await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            amount=Decimal("1.00"),
            direction="DR",
            txn_date=date.today() - timedelta(days=(i % 29) + 1),
        )

    large_txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        amount=Decimal("5000.00"),
        direction="DR",
        txn_date=date.today(),
        description="BIGPURCHASE electronics",
    )
    await db.commit()

    anomalies = await detect_anomalies(db, large_txn, user_id=test_user.id)
    large = next(a for a in anomalies if a.anomaly_type == "LARGE_AMOUNT")
    assert large.severity == "high"
    assert large.message
