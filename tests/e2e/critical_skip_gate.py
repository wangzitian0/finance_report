"""AC8.13.6: pure predicate + message for the critical-skip-to-failure gate.

Split out of conftest.py's `pytest_runtest_makereport` hookwrapper so the
condition and message text are unit-testable without pytest's report/item
machinery — see tests/tooling/test_critical_skip_gate.py (#1435 W1 / #1534).
"""

from __future__ import annotations

CRITICAL_MARKER = "critical"


def should_convert_skip_to_failure(
    *,
    strict_gates_enabled: bool,
    skipped: bool,
    has_critical_marker: bool,
    when: str,
) -> bool:
    """A skipped result for a @pytest.mark.critical test becomes a failure

    only when STRICT_E2E_GATES is enabled and the skip happened during
    setup or the test call itself (never during teardown, which always
    reports independently of the test outcome)."""
    return (
        strict_gates_enabled
        and skipped
        and has_critical_marker
        and when in {"setup", "call"}
    )


def critical_skip_failure_message(node_id: str) -> str:
    return (
        f"Critical E2E gate skipped: {node_id}. "
        "Critical deploy usability checks must fail instead of skip when "
        "STRICT_E2E_GATES=true."
    )
