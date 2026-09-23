"""Tooling coverage anchor for reconciliation governance detector (#1994).

Re-exports live detector contract tests into the tooling suite so
common/reconciliation/extension/governance_detector.py is measured under
the `common` coverage component in CI.
"""

from __future__ import annotations

from apps.backend.tests.reconciliation.test_economic_disposition_governance import (
    test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact,
    test_detector_ignores_format_only_changes,
    test_detector_reports_unreadable_structure_as_a_finding,
)

__all__ = [
    "test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact",
    "test_detector_ignores_format_only_changes",
    "test_detector_reports_unreadable_structure_as_a_finding",
]
