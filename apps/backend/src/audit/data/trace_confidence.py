"""Fixed-cohort confidence projection over supersession heads."""

from __future__ import annotations

from dataclasses import dataclass

from src.audit.base.trace import (
    TraceLineage,
    TraceRecord,
    TraceRecordValidationError,
    TraceResult,
    current_heads,
)
from src.audit.ratio import Ratio


@dataclass(frozen=True, slots=True)
class TraceConfidenceProjection:
    cohort_id: str
    cohort_version: str
    members: tuple[TraceLineage, ...]

    def __post_init__(self) -> None:
        if not self.cohort_id.strip() or not self.cohort_version.strip():
            raise TraceRecordValidationError("cohort id and version are required")
        if not self.members or len(set(self.members)) != len(self.members):
            raise TraceRecordValidationError("cohort members must be non-empty and unique")

    def evaluate(self, records: list[TraceRecord]) -> Ratio:
        machine_graph = [record for record in records if record.authority.provenance != "manual"]
        heads = [record for record in current_heads(machine_graph) if record.lineage in self.members]
        by_lineage: dict[TraceLineage, list[TraceRecord]] = {}
        for record in heads:
            by_lineage.setdefault(record.lineage, []).append(record)
        if set(by_lineage) != set(self.members):
            raise TraceRecordValidationError("fixed cohort is missing a current lineage head")
        if any(len(values) != 1 for values in by_lineage.values()):
            raise TraceRecordValidationError("fixed cohort has ambiguous current lineage heads")
        passed = sum(
            values[0].result in {TraceResult.PASS, TraceResult.AUTHORITATIVE} for values in by_lineage.values()
        )
        return Ratio.fraction(passed, len(self.members))
