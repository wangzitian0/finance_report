"""Data types for benchmark scenario results."""

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
