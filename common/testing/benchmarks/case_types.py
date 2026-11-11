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
    status: str
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


def _read_registry(path: Path) -> list[dict[str, Any]]:
    try:
        domains = json.loads(path.read_text(encoding="utf-8"))["domains"]
        if not isinstance(domains, list):
            raise TypeError("domains must be a list")
        return domains
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the 30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


def load_flow_to_domain(path: Path = FLOWS_SSOT_PATH) -> dict[int, int]:
    try:
        return {f["id"]: d["id"] for d in _read_registry(path) for f in d["flows"]}
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the 30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


FLOW_TO_DOMAIN: dict[int, int] = load_flow_to_domain()


def load_flow_to_cases(path: Path = FLOWS_SSOT_PATH) -> dict[int, list[str]]:
    try:
        out: dict[int, list[str]] = {}
        for d in _read_registry(path):
            for f in d["flows"]:
                cases = f["benchmark_cases"]
                if (
                    not isinstance(cases, list)
                    or not cases
                    or not all(isinstance(c, str) and c for c in cases)
                ):
                    raise ValueError(f"Invalid benchmark_cases for flow {f.get('id')}")
                out[f["id"]] = list(cases)
        return out
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the 30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


FLOW_TO_CASES: dict[int, list[str]] = load_flow_to_cases()
DOMAIN_TO_CASES: dict[int, list[str]] = {
    dom: sorted(
        {
            c
            for fl, fd in FLOW_TO_DOMAIN.items()
            if fd == dom
            for c in FLOW_TO_CASES.get(fl, ())
        },
        key=lambda c: int(c) if c.isdigit() else c,
    )
    for dom in sorted(set(FLOW_TO_DOMAIN.values()))
}


def get_case_to_flows() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for fl, cases in FLOW_TO_CASES.items():
        for c in cases:
            out.setdefault(f"case_{c}", set()).add(fl)
    return out
