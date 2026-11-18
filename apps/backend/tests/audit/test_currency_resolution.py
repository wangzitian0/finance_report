from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.audit.money import Currency, InvalidCurrencyError
from src.extraction.extension.currency_resolution import UNRESOLVED_PLACEHOLDER, CurrencyUnresolvedError, resolve_ingest_currency
from src.extraction.extension.review_queue import create_entry_from_txn

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(("candidates", "expected_code", "expected_unresolved"), [(("USD",), "USD", False), (("usd ",), "USD", False), ((None, "SGD"), "SGD", False), (("ZZZ", "EUR"), "EUR", False), ((), UNRESOLVED_PLACEHOLDER, True), ((None,), UNRESOLVED_PLACEHOLDER, True), ((None, None), UNRESOLVED_PLACEHOLDER, True), (("ZZZ",), UNRESOLVED_PLACEHOLDER, True), (("US", ""), UNRESOLVED_PLACEHOLDER, True)])
def test_AC12_40_1_and_2_resolve_ingest_currency(candidates, expected_code: str, expected_unresolved: bool) -> None:
    resolved = resolve_ingest_currency(*candidates)
    assert (resolved.code, resolved.unresolved) == (expected_code, expected_unresolved) and (not expected_unresolved or resolved.code != "SGD")


@pytest.mark.parametrize(("unresolved", "currency"), [(True, UNRESOLVED_PLACEHOLDER), (False, "USD")])
async def test_AC12_40_2_and_4_placeholder_and_promotion_guard(unresolved: bool, currency: str) -> None:
    with pytest.raises(InvalidCurrencyError):
        Currency(UNRESOLVED_PLACEHOLDER)
    user_id = uuid4()
    txn = SimpleNamespace(id=uuid4(), user_id=user_id, currency_unresolved=unresolved, currency=currency, txn_date=date(2024, 1, 1), source_documents=[])
    with pytest.raises(CurrencyUnresolvedError if unresolved else Exception) as exc_info:
        await create_entry_from_txn(None, txn, user_id=user_id, base_currency="SGD")
    assert unresolved or not isinstance(exc_info.value, CurrencyUnresolvedError)
