"""Data types and canonical domain/flow mappings for benchmark scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FLOWS_SSOT_PATH = (
    Path(__file__).resolve().parents[2] / "common/meta/flows/user_cases_ssot.json"
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
            f"Cannot read the user-cases/30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


def _domain_items(domain: dict[str, Any]) -> list[dict[str, Any]]:
    items = domain.get("user_cases")
    if items is None:
        items = domain["flows"]
    return items


def _legacy_flow_id(item: dict[str, Any]) -> int | None:
    if "legacy_flow_id" in item:
        val = item["legacy_flow_id"]
        return int(val) if val is not None else None
    fid = item["id"]
    return int(fid) if isinstance(fid, int) else None


def load_flow_to_domain(path: Path = FLOWS_SSOT_PATH) -> dict[int, int]:
    try:
        out: dict[int, int] = {}
        for d in _read_registry(path):
            for f in _domain_items(d):
                fid = _legacy_flow_id(f)
                if fid is not None:
                    out[fid] = d["id"]
        return out
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Cannot read the user-cases/30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


FLOW_TO_DOMAIN: dict[int, int] = load_flow_to_domain()


def load_flow_to_cases(path: Path = FLOWS_SSOT_PATH) -> dict[int, list[str]]:
    try:
        out: dict[int, list[str]] = {}
        for d in _read_registry(path):
            for f in _domain_items(d):
                fid = _legacy_flow_id(f)
                cases = f["benchmark_cases"]
                if not isinstance(cases, list) or not all(
                    isinstance(c, str) and c for c in cases
                ):
                    raise ValueError(f"Invalid benchmark_cases for item {f.get('id')}")
                if fid is None:
                    continue
                if not cases:
                    raise ValueError(f"Invalid benchmark_cases for flow {fid}")
                out[fid] = list(cases)
        return out
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the user-cases/30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


def load_domain_to_cases(path: Path = FLOWS_SSOT_PATH) -> dict[int, list[str]]:
    try:
        out: dict[int, list[str]] = {}
        for d in _read_registry(path):
            collected: set[str] = set()
            for f in _domain_items(d):
                for c in f.get("benchmark_cases", ()):
                    if isinstance(c, str) and c:
                        collected.add(c)
            out[int(d["id"])] = sorted(
                collected, key=lambda c: int(c) if c.isdigit() else c
            )
        return out
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Cannot read the user-cases/30-flow registry {path}: {type(exc).__name__}: {exc}"
        ) from exc


FLOW_TO_CASES: dict[int, list[str]] = load_flow_to_cases()
DOMAIN_TO_CASES: dict[int, list[str]] = load_domain_to_cases()


def get_case_to_flows() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for fl, cases in FLOW_TO_CASES.items():
        for c in cases:
            out.setdefault(f"case_{c}", set()).add(fl)
    return out
