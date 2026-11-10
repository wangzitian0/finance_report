from __future__ import annotations; from decimal import Decimal; import pytest; from src.reconciliation import _within_combination_tolerance; from src.reconciliation.base.config import DEFAULT_CONFIG
class _Txn:
    def __init__(self, amount: Decimal, currency: str='USD') -> None: self.amount = amount; self.currency = currency
def _old_within_tolerance(combined: Decimal, amount: Decimal, config) -> bool: tolerance = max(amount * config.amount_percent, config.amount_absolute); return not abs(combined - amount) > tolerance * 2
@pytest.mark.parametrize('combined, amount', [(Decimal('100.00'), Decimal('100.00')), (Decimal('100.50'), Decimal('100.00')), (Decimal('100.21'), Decimal('100.00')), (Decimal('100.20'), Decimal('100.00')), (Decimal('99.79'), Decimal('100.00')), (Decimal('10000.00'), Decimal('9900.00')), (Decimal('0.30'), Decimal('0.10')), (Decimal('0.31'), Decimal('0.10'))])
def test_combination_tolerance_matches_legacy_formula(combined: Decimal, amount: Decimal) -> None: 'AC4.2.3'; txn = _Txn(amount); assert _within_combination_tolerance(combined, txn, DEFAULT_CONFIG) == _old_within_tolerance(combined, amount, DEFAULT_CONFIG)
