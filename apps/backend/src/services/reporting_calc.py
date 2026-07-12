"""Thin re-export shim — ``reporting_calc`` moved to ``src.reporting`` (#1666).

The pure calculation primitives live in
``src.reporting.extension.reporting_calc`` and are published via the package
root. This shim keeps the two ``services/``-side consumers that in-flight
parallel PRs own resolving without an edit:

- ``services/reporting/manual_valuation.py`` (#1610: ``ReportError``,
  ``_quantize_money``),
- ``services/annualized_income.py`` (#1671 Wave B: ``income_bucket``).

Whichever of those PRs repoints/deletes its consumer last also deletes this
shim.
"""

from src.reporting import ReportError, _quantize_money, income_bucket

__all__ = ["ReportError", "_quantize_money", "income_bucket"]
