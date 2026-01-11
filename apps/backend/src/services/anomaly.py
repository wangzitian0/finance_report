"""Anomaly detection for reconciliation."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement, BankStatementTransaction
from src.services.reconciliation import normalize_text


@dataclass
class AnomalyResult:
    """Detected anomaly summary."""

    anomaly_type: str
    severity: str
    message: str


async def detect_anomalies(
    db: AsyncSession,
    txn: BankStatementTransaction,
    *,
    user_id: UUID,
) -> list[AnomalyResult]:
    """Detect anomalies for a transaction."""
    anomalies: list[AnomalyResult] = []
    lookback_start = txn.txn_date - timedelta(days=30)

    avg_result = await db.execute(
        select(func.avg(BankStatementTransaction.amount))
        .join(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatementTransaction.txn_date >= lookback_start)
        .where(BankStatementTransaction.direction == txn.direction)
    )
    avg_value = avg_result.scalar_one_or_none()
    avg_amount = Decimal(str(avg_value)) if avg_value is not None else Decimal("0")

    if avg_amount and txn.amount > avg_amount * Decimal("10"):
        anomalies.append(
            AnomalyResult(
                anomaly_type="LARGE_AMOUNT",
                severity="high",
                message="Amount is >10x 30-day average for this direction.",
            )
        )

    merchant_token = normalize_text(txn.description).split()[:1]
    if merchant_token:
        token = merchant_token[0]
        safe_token = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{safe_token}%"
        daily_count_result = await db.execute(
            select(func.count(BankStatementTransaction.id))
            .join(BankStatement)
            .where(BankStatement.user_id == user_id)
            .where(BankStatementTransaction.txn_date == txn.txn_date)
            .where(BankStatementTransaction.description.ilike(pattern, escape="\\"))
        )
        daily_count = daily_count_result.scalar_one_or_none() or 0
        if daily_count > 5:
            anomalies.append(
                AnomalyResult(
                    anomaly_type="FREQUENCY_SPIKE",
                    severity="medium",
                    message="More than 5 transactions for this merchant today.",
                )
            )

        history_start = txn.txn_date - timedelta(days=90)
        history_result = await db.execute(
            select(func.count(BankStatementTransaction.id))
            .join(BankStatement)
            .where(BankStatement.user_id == user_id)
            .where(BankStatementTransaction.txn_date >= history_start)
            .where(BankStatementTransaction.description.ilike(pattern, escape="\\"))
        )
        history_count = history_result.scalar_one_or_none() or 0
        if history_count <= 1:
            anomalies.append(
                AnomalyResult(
                    anomaly_type="NEW_MERCHANT",
                    severity="low",
                    message="Merchant has no recent history in last 90 days.",
                )
            )

    if txn.txn_date.weekday() >= 5 and txn.amount > avg_amount * Decimal("5"):
        anomalies.append(
            AnomalyResult(
                anomaly_type="WEEKEND_LARGE",
                severity="medium",
                message="Large weekend transaction compared to recent average.",
            )
        )

    return anomalies
