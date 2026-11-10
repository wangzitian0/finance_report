'AC4.5.1'; from datetime import date, timedelta; from decimal import Decimal; from src.extraction import TransactionDirection; from src.reconciliation.extension.anomaly import detect_anomalies; from tests.factories import AtomicTransactionFactory; OUT = TransactionDirection.OUT
async def test_detect_large_amount_anomaly(db, test_user):
    for i in range(30): await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('1.00'), direction=OUT, txn_date=date.today() - timedelta(days=i % 29 + 1))
    large_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('5000.00'), direction=OUT, txn_date=date.today(), description='HUGE PURCHASE ELECTRONICS'); await db.commit(); anomalies = await detect_anomalies(db, large_txn, user_id=test_user.id); types = [a.anomaly_type for a in anomalies]; assert 'LARGE_AMOUNT' in types
async def test_no_anomalies_for_normal_transaction(db, test_user):
    for i in range(5): await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('50.00'), direction=OUT, txn_date=date.today() - timedelta(days=i + 1), description=f'GROCERY STORE {i}')
    normal_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('55.00'), direction=OUT, txn_date=date.today(), description='GROCERY STORE'); await db.commit(); anomalies = await detect_anomalies(db, normal_txn, user_id=test_user.id); types = [a.anomaly_type for a in anomalies]; assert 'LARGE_AMOUNT' not in types
async def test_detect_new_merchant_anomaly(db, test_user): txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('30.00'), direction=OUT, txn_date=date.today(), description='BRANDNEWSHOP online'); await db.commit(); anomalies = await detect_anomalies(db, txn, user_id=test_user.id); types = [a.anomaly_type for a in anomalies]; assert 'NEW_MERCHANT' in types
async def test_detect_weekend_large_anomaly(db, test_user):
    for i in range(5): await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('10.00'), direction=OUT, txn_date=date.today() - timedelta(days=i + 1))
    saturday = date.today()
    while saturday.weekday() != 5: saturday += timedelta(days=1)
    weekend_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('500.00'), direction=OUT, txn_date=saturday, description='WEEKEND SPLURGE'); await db.commit(); anomalies = await detect_anomalies(db, weekend_txn, user_id=test_user.id); types = [a.anomaly_type for a in anomalies]; assert 'WEEKEND_LARGE' in types
async def test_detect_frequency_spike(db, test_user):
    today = date.today()
    for i in range(6): await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('10.00'), direction=OUT, txn_date=today, description=f'COFFEESHOP order-{i}')
    target_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('10.00'), direction=OUT, txn_date=today, description='COFFEESHOP order-7'); await db.commit(); anomalies = await detect_anomalies(db, target_txn, user_id=test_user.id); types = [a.anomaly_type for a in anomalies]; assert 'FREQUENCY_SPIKE' in types
async def test_anomaly_result_has_severity(db, test_user):
    for i in range(30): await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('1.00'), direction=OUT, txn_date=date.today() - timedelta(days=i % 29 + 1))
    large_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, amount=Decimal('5000.00'), direction=OUT, txn_date=date.today(), description='BIGPURCHASE electronics'); await db.commit(); anomalies = await detect_anomalies(db, large_txn, user_id=test_user.id); large = next((a for a in anomalies if a.anomaly_type == 'LARGE_AMOUNT')); assert large.severity == 'high'; assert large.message
