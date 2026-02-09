from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.models import BankStatementTransaction
from src.services.anomaly import detect_anomalies


@pytest.fixture
def db_engine():
    """Mock db_engine to avoid DB connection in unit tests."""
    return MagicMock()


@pytest.mark.asyncio
async def test_detect_large_amount_anomaly():
    """Test detection of amounts >10x average."""
    db = AsyncMock()
    user_id = uuid4()

    txn = BankStatementTransaction(
        id=uuid4(),
        txn_date=date(2023, 1, 1),
        amount=Decimal("1000"),
        direction="DEBIT",
        description="Generic Transaction",
    )

    # Mock Avg result -> 10. So 1000 > 100.
    mock_result_avg = MagicMock()
    mock_result_avg.scalar_one_or_none.return_value = 10

    # Mock other queries (daily count, history count)
    # The code executes avg first. Then if token found, counts.
    # "Generic Transaction" -> tokens ["Generic", "Transaction"]

    mock_result_daily = MagicMock()
    mock_result_daily.scalar_one_or_none.return_value = 1

    mock_result_history = MagicMock()
    mock_result_history.scalar_one_or_none.return_value = 10  # Existing merchant

    db.execute.side_effect = [mock_result_avg, mock_result_daily, mock_result_history]

    anomalies = await detect_anomalies(db, txn, user_id=user_id)

    assert any(a.anomaly_type == "LARGE_AMOUNT" for a in anomalies)
    assert not any(a.anomaly_type == "NEW_MERCHANT" for a in anomalies)


@pytest.mark.asyncio
async def test_detect_new_merchant_anomaly():
    """Test detection of new merchant (low history)."""
    db = AsyncMock()
    user_id = uuid4()

    txn = BankStatementTransaction(
        id=uuid4(), txn_date=date(2023, 1, 1), amount=Decimal("10"), direction="DEBIT", description="New Merchant"
    )

    # Avg 10. 10 <= 10*10. No large amount.
    mock_result_avg = MagicMock()
    mock_result_avg.scalar_one_or_none.return_value = 10

    # Daily count
    mock_result_daily = MagicMock()
    mock_result_daily.scalar_one_or_none.return_value = 1

    # History count -> 0 (New)
    mock_result_history = MagicMock()
    mock_result_history.scalar_one_or_none.return_value = 0

    db.execute.side_effect = [mock_result_avg, mock_result_daily, mock_result_history]

    anomalies = await detect_anomalies(db, txn, user_id=user_id)

    assert any(a.anomaly_type == "NEW_MERCHANT" for a in anomalies)


@pytest.mark.asyncio
async def test_detect_frequency_spike():
    """Test detection of frequency spike (>5 per day)."""
    db = AsyncMock()
    user_id = uuid4()

    txn = BankStatementTransaction(
        id=uuid4(), txn_date=date(2023, 1, 1), amount=Decimal("10"), direction="DEBIT", description="Spam Merchant"
    )

    mock_result_avg = MagicMock()
    mock_result_avg.scalar_one_or_none.return_value = 10

    # Daily count -> 6 (>5)
    mock_result_daily = MagicMock()
    mock_result_daily.scalar_one_or_none.return_value = 6

    mock_result_history = MagicMock()
    mock_result_history.scalar_one_or_none.return_value = 10

    db.execute.side_effect = [mock_result_avg, mock_result_daily, mock_result_history]

    anomalies = await detect_anomalies(db, txn, user_id=user_id)

    assert any(a.anomaly_type == "FREQUENCY_SPIKE" for a in anomalies)
