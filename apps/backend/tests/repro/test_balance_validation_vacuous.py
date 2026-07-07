"""Repro for #1390 — balance-chain validation passes vacuously when closing_balance is None.

Synthetic data only. With no closing balance and no transactions, validation
coerces the missing balance to 0, computes a zero delta, and reports
`closing_match: true` — a confident verdict over no evidence. The missing balance
is also serialized as the literal string "None" (str(None)).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_validation_does_not_pass_vacuously_when_closing_balance_missing(db: AsyncSession, test_user):
    from src.extraction.extension.statement_validation import validate_balance_chain
    from src.models.statement_enums import BankStatementStatus
    from src.models.statement_summary import StatementSummary

    statement = StatementSummary(
        user_id=test_user.id,
        file_hash=uuid4().hex,
        institution="SynthBank",
        currency="SGD",
        opening_balance=None,
        closing_balance=None,  # no closing balance extracted
        status=BankStatementStatus.PARSED,
    )
    db.add(statement)
    await db.commit()
    await db.refresh(statement)

    result = await validate_balance_chain(db, statement.id)

    # A missing closing balance with zero transactions is "unknown", not "matched".
    assert result["closing_match"] is not True, (
        "closing_match reported True with no closing balance and no transactions "
        "(vacuous pass -> false confidence in the source review gate)"
    )
    # None must not be stringified into the JSON result as the literal "None".
    assert result["closing_balance"] != "None", (
        "closing_balance serialized as the string 'None' (str(None)); should be JSON null or omitted"
    )
