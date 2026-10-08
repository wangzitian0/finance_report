"""Data types and canonical domain/flow mappings for benchmark scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseResult:
    case_id: str
    case_name: str
    status: str  # PASS / FAIL / ERROR
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


# Canonical 7-domain grouping of the 30 flows defined in thirty_flows_ssot.json
FLOW_TO_DOMAIN: dict[int, int] = {
    1: 1,
    2: 1,
    3: 1,
    4: 1,
    5: 1,
    6: 2,
    7: 2,
    8: 2,
    9: 2,
    10: 2,
    11: 3,
    12: 3,
    13: 3,
    14: 3,
    15: 4,
    16: 4,
    17: 4,
    18: 4,
    19: 5,
    20: 5,
    21: 5,
    22: 5,
    23: 6,
    24: 6,
    25: 6,
    26: 6,
    27: 7,
    28: 7,
    29: 7,
    30: 7,
}

# Canonical mapping from 30 flows to holistic cases (1..6)
FLOW_TO_CASES: dict[int, list[str]] = {
    1: ["1"],
    2: ["1"],
    3: ["2"],
    4: ["5"],
    5: ["5", "6"],
    6: ["1"],
    7: ["1"],
    8: ["2"],
    9: ["2"],
    10: ["1"],
    11: ["2"],
    12: ["2"],
    13: ["2"],
    14: ["2", "5"],
    15: ["3"],
    16: ["3"],
    17: ["4"],
    18: ["3"],
    19: ["5"],
    20: ["5"],
    21: ["5", "6"],
    22: ["5"],
    23: ["1", "4", "6"],
    24: ["1", "6"],
    25: ["1"],
    26: ["1"],
    27: ["1", "5"],
    28: ["5"],
    29: ["2"],
    30: ["5"],
}

# Domain to holistic cases derived deterministically from FLOW_TO_DOMAIN and FLOW_TO_CASES
DOMAIN_TO_CASES: dict[int, list[str]] = {
    domain: sorted(
        {
            case
            for flow, flow_domain in FLOW_TO_DOMAIN.items()
            if flow_domain == domain
            for case in FLOW_TO_CASES.get(flow, [])
        },
        key=lambda c: int(c) if c.isdigit() else c,
    )
    for domain in range(1, 8)
}


def get_case_to_flows() -> dict[str, set[int]]:
    """Compute inverted case_id -> set of flow numbers dynamically from FLOW_TO_CASES."""
    case_to_flows: dict[str, set[int]] = {}
    for flow, cases in FLOW_TO_CASES.items():
        for case in cases:
            full_case_id = f"case_{case}"
            case_to_flows.setdefault(full_case_id, set()).add(flow)
    return case_to_flows
