"""Tooling coverage anchor for reporting governance detector (#1996).

AC-reporting.cash-events.9: live governance detector contract proof.
Re-exports live detector contract tests into the tooling suite so
common/reporting/extension/governance_detector.py is measured under
the `common` coverage component in CI.
"""

from __future__ import annotations

from apps.backend.tests.reporting.test_cash_event_governance import (
    test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced,
    test_AC_reporting_cash_events_10_counterfactual_matrix_is_locked,
    test_detector_ignores_format_only_changes,
    test_detector_reports_unreadable_structure_as_a_finding,
)

__all__ = [
    "test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced",
    "test_AC_reporting_cash_events_10_counterfactual_matrix_is_locked",
    "test_detector_ignores_format_only_changes",
    "test_detector_reports_unreadable_structure_as_a_finding",
]
