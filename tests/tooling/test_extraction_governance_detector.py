"""Tooling coverage anchor for extraction governance detector (#1995).

AC-extraction.source-lifecycle.9: live governance detector contract proof.
Re-exports live detector contract tests into the tooling suite so
common/extraction/extension/governance_detector.py is measured under
the `common` coverage component in CI.
"""

from __future__ import annotations

from apps.backend.tests.extraction.test_source_lifecycle_governance import (
    test_AC_extraction_source_lifecycle_9_governance_detail_is_exact,
    test_detector_ignores_format_only_changes,
    test_detector_reports_unreadable_structure_as_a_finding,
)

__all__ = [
    "test_AC_extraction_source_lifecycle_9_governance_detail_is_exact",
    "test_detector_ignores_format_only_changes",
    "test_detector_reports_unreadable_structure_as_a_finding",
]
