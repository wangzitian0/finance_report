"""AC-ledger.77.* locks for processing and balance signature surgery."""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ledger import (
    Direction,
    calculate_account_balances,
    calculate_account_balances_in_base_currency,
    create_transfer_out_entry,
    find_transfer_pairs,
    get_or_create_processing_account,
    get_processing_balance,
    get_unpaired_transfers,
    list_processing_transfer_legs,
)
from src.ledger.extension import processing
from src.ledger.extension.account_service import get_or_create_opening_balance_equity_account


@pytest.mark.asyncio
async def test_processing_transfers_use_the_post_entry_front_door(monkeypatch) -> None:
    """AC-ledger.77.1."""
    processing_id = uuid4()
    captured = {}

    async def fake_processing_account(db, user_id, *, currency):
        return SimpleNamespace(id=processing_id, currency=currency)

    async def fake_post_entry(db, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), status="posted", lines=[])

    monkeypatch.setattr(processing, "get_or_create_processing_account", fake_processing_account)
    monkeypatch.setattr(processing, "post_entry", fake_post_entry)

    source_account_id = uuid4()
    result = await create_transfer_out_entry(
        SimpleNamespace(),
        uuid4(),
        source_account_id,
        Decimal("25.00"),
        date(2024, 1, 2),
        "Savings",
        currency="USD",
    )

    assert result.id is not None
    debits = sum(
        (leg.money.amount for leg in captured["entry"].legs if leg.direction == Direction.DEBIT),
        Decimal("0"),
    )
    credits = sum(
        (leg.money.amount for leg in captured["entry"].legs if leg.direction == Direction.CREDIT),
        Decimal("0"),
    )
    assert debits == credits == Decimal("25.00")
    assert {leg.account_id for leg in captured["entry"].legs} == {processing_id, source_account_id}


def test_processing_apis_require_explicit_currency() -> None:
    """AC-ledger.77.2."""
    for function in (
        get_or_create_processing_account,
        find_transfer_pairs,
        create_transfer_out_entry,
        get_processing_balance,
        get_unpaired_transfers,
        list_processing_transfer_legs,
    ):
        parameter = inspect.signature(function).parameters["currency"]
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    opening_currency = inspect.signature(get_or_create_opening_balance_equity_account).parameters["currency"]
    assert opening_currency.default is inspect.Parameter.empty
    assert "src.config" not in inspect.getsource(processing)


def test_account_balance_currency_spaces_are_explicit() -> None:
    """AC-ledger.77.3."""
    assert "use_base_currency" not in inspect.signature(calculate_account_balances).parameters
    assert "use_base_currency" not in inspect.signature(calculate_account_balances_in_base_currency).parameters
    assert calculate_account_balances is not calculate_account_balances_in_base_currency
