"""Data types and canonical domain/flow mappings for benchmark scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FLOWS_SSOT_PATH = (
    Path(__file__).resolve().parents[3] / "common/meta/flows/thirty_flows_ssot.json"
)


@dataclass
class CaseResult:
    case_id: str
    case_name: str
    status: str  # PASS / FAIL / SKIPPED / ERROR
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


def load_flow_to_domain(path: Path = FLOWS_SSOT_PATH) -> dict[int, int]:
    """Read flow id -> domain id from the 30-flow registry (concept `thirty_wealth_flows`)."""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
        return {
            flow["id"]: domain["id"]
            for domain in registry["domains"]
            for flow in domain["flows"]
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the 30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


# Domain of each flow. The registry JSON is the only source.
FLOW_TO_DOMAIN: dict[int, int] = load_flow_to_domain()


def load_flow_to_cases(path: Path = FLOWS_SSOT_PATH) -> dict[int, list[str]]:
    """Read flow id -> benchmark cases from the 30-flow registry."""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
        result: dict[int, list[str]] = {}
        for domain in registry["domains"]:
            for flow in domain["flows"]:
                cases = flow["benchmark_cases"]
                if not isinstance(cases, list) or not cases:
                    raise ValueError(
                        f"Flow {flow.get('id')} benchmark_cases must be a non-empty list"
                    )
                for c in cases:
                    if not isinstance(c, str) or not c:
                        raise ValueError(
                            f"Flow {flow.get('id')} benchmark_cases entries must be non-empty strings"
                        )
                result[flow["id"]] = list(cases)
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the 30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


# Canonical mapping from 30 flows to holistic cases (1..6).
# The registry JSON is the only source.
FLOW_TO_CASES: dict[int, list[str]] = load_flow_to_cases()

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
    for domain in sorted(set(FLOW_TO_DOMAIN.values()))
}


def get_case_to_flows() -> dict[str, set[int]]:
    """Compute inverted case_id -> set of flow numbers dynamically from FLOW_TO_CASES."""
    case_to_flows: dict[str, set[int]] = {}
    for flow, cases in FLOW_TO_CASES.items():
        for case in cases:
            full_case_id = f"case_{case}"
            case_to_flows.setdefault(full_case_id, set()).add(flow)
    return case_to_flows
