"""Contract: every no-AC test/support file stays classified (issue #511).

The classification registry is ``docs/project/traceability-exceptions.md`` and
is enforced at runtime by ``tools/lint_doc_consistency.py`` (checks #8 and #9).
This test pins the guarantee so a newly added unclassified no-AC test fails fast.
"""

from __future__ import annotations

from pathlib import Path

from common.testing import lint_doc_consistency as ldc

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS = ROOT / "docs" / "project" / "traceability-exceptions.md"


def test_AC8_13_132_no_unclassified_no_ac_test_files() -> None:
    """AC-testing.governance.8: AC8.13.132: every no-AC test/support file is classified in the registry."""
    violations = ldc.check_no_ac_test_exceptions()
    assert violations == [], "\n".join(v.message for v in violations)


def test_AC8_13_132_product_e2e_tests_are_not_exception_eligible() -> None:
    """AC8.13.132: product E2E tests cannot be parked on the exception allow-list."""
    violations = ldc.check_no_e2e_product_test_exceptions()
    assert violations == [], "\n".join(v.message for v in violations)


def test_AC8_13_132_registry_paths_cover_discovered_no_ac_files() -> None:
    """AC8.13.132: the registry is not stale — it lists the discovered no-AC files."""
    discovered = {ldc._display_path(path) for path in ldc.discover_no_ac_test_files()}
    classified = ldc.load_traceability_exception_paths(EXCEPTIONS)
    missing = sorted(discovered - classified)
    assert missing == [], "unclassified no-AC test files: " + ", ".join(missing)
