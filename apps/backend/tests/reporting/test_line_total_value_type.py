from __future__ import annotations; from decimal import Decimal; from src.reporting.extension._core import _line_total
def test_line_total_sums_and_quantizes() -> None: 'AC5.2.1 AC5.3.1'; lines = [{'amount': '10.005'}, {'amount': Decimal('0.001')}, {'amount': '-2.50'}]; assert _line_total(lines) == Decimal('7.51'); assert _line_total([]) == Decimal('0.00')
