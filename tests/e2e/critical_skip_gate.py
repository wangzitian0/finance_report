from __future__ import annotations

CRITICAL_MARKER = "critical"


def should_convert_skip_to_failure(
    *, strict_gates_enabled: bool, skipped: bool, has_critical_marker: bool, when: str
) -> bool:
    return (
        strict_gates_enabled
        and skipped
        and has_critical_marker
        and when in {"setup", "call"}
    )


def critical_skip_failure_message(node_id: str) -> str:
    return f"Critical E2E gate skipped: {node_id}. Critical deploy usability checks must fail instead of skip when STRICT_E2E_GATES=true."
