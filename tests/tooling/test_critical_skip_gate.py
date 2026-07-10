"""Behavioral coverage for the critical-skip-to-failure gate's decision logic.

#1435 W1: replaces brittle `"text" in read("tests/e2e/conftest.py")` source
assertions (formerly in test_AC8_13_6_critical_e2e_skips_become_failures in
test_post_merge_e2e_gates.py) with real behavioral tests against the extracted
pure predicate should_convert_skip_to_failure() and the message builder
critical_skip_failure_message() — so a harmless reformat of the
pytest_runtest_makereport hookwrapper in conftest.py can no longer accidentally
pass or fail this check; only the actual skip-to-failure decision can.
"""

from __future__ import annotations

from tests.e2e.critical_skip_gate import (
    critical_skip_failure_message,
    should_convert_skip_to_failure,
)


def test_AC8_13_6_strict_gates_off_never_converts() -> None:
    """AC8.13.6: outside STRICT_E2E_GATES, a critical skip stays a skip."""
    assert (
        should_convert_skip_to_failure(
            strict_gates_enabled=False,
            skipped=True,
            has_critical_marker=True,
            when="call",
        )
        is False
    )


def test_AC8_13_6_non_critical_skip_never_converts() -> None:
    """AC8.13.6: a skip on a test without @pytest.mark.critical is left alone."""
    assert (
        should_convert_skip_to_failure(
            strict_gates_enabled=True,
            skipped=True,
            has_critical_marker=False,
            when="call",
        )
        is False
    )


def test_AC8_13_6_non_skip_result_never_converts() -> None:
    """AC8.13.6: a passing or failing critical test is untouched (only skips convert)."""
    assert (
        should_convert_skip_to_failure(
            strict_gates_enabled=True,
            skipped=False,
            has_critical_marker=True,
            when="call",
        )
        is False
    )


def test_AC8_13_6_teardown_phase_skip_never_converts() -> None:
    """AC8.13.6: a skip reported during teardown does not fail the gate — only setup/call."""
    assert (
        should_convert_skip_to_failure(
            strict_gates_enabled=True,
            skipped=True,
            has_critical_marker=True,
            when="teardown",
        )
        is False
    )


def test_AC8_13_6_critical_skip_under_strict_gates_converts_in_setup_and_call() -> None:
    """AC8.13.6: the ONLY converting case — strict gates on, critical marker, skipped, setup or call phase."""
    for when in ("setup", "call"):
        assert (
            should_convert_skip_to_failure(
                strict_gates_enabled=True,
                skipped=True,
                has_critical_marker=True,
                when=when,
            )
            is True
        )


def test_AC8_13_6_failure_message_names_the_failing_test_and_the_reason() -> None:
    """AC8.13.6: the converted failure's message identifies the test and demands STRICT_E2E_GATES."""
    message = critical_skip_failure_message(
        "tests/e2e/test_statement_full_journey.py::test_dbs_statement_full_journey"
    )

    assert (
        "tests/e2e/test_statement_full_journey.py::test_dbs_statement_full_journey"
        in message
    )
    assert "Critical E2E gate skipped" in message
    assert "STRICT_E2E_GATES=true" in message
