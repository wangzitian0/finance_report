"""Pure helpers for personal report-package snapshot assembly & export.

Stateless serialization, date/currency normalization, snapshot status,
DB-row -> schema mappers, and CSV export. Extracted from the reports router;
the snapshot *orchestration* stays in the router because it composes other
routers. Behavior unchanged.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from io import StringIO
from typing import Any
from uuid import UUID

from src.config import settings
from src.models.layer4 import ReportSnapshot
from src.money import normalize_currency_code
from src.schemas import (
    PersonalReportPackageSnapshotResponse,
    PersonalReportPackageSnapshotStatus,
    PersonalReportPackageSnapshotSummary,
)


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def package_dates(
    *,
    start_date: date | None,
    end_date: date | None,
    as_of_date: date | None,
) -> tuple[date, date, date]:
    report_end = end_date or as_of_date or date.today()
    report_start = start_date or report_end - timedelta(days=365)
    report_as_of = as_of_date or report_end
    return report_start, report_end, report_as_of


def package_currency(currency: str | None) -> str:
    return normalize_currency_code(currency or settings.base_currency)


def package_snapshot_status(readiness: dict[str, Any]) -> PersonalReportPackageSnapshotStatus:
    state = str(readiness.get("state") or "")
    blocking_count = int(readiness.get("blocking_count") or 0)
    if state in {"ready", "generated", "stale"} and blocking_count == 0:
        return PersonalReportPackageSnapshotStatus.TRUSTED
    return PersonalReportPackageSnapshotStatus.DRAFT


def package_snapshot_summary(snapshot: ReportSnapshot) -> PersonalReportPackageSnapshotSummary:
    data = snapshot.report_data
    return PersonalReportPackageSnapshotSummary(
        id=snapshot.id,
        package_id=data["package_id"],
        status=data["status"],
        framework_id=data["framework_id"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        as_of_date=data["as_of_date"],
        currency=data["currency"],
        readiness_state=data["readiness_state"],
        is_latest=snapshot.is_latest,
        created_at=snapshot.created_at,
    )


def package_snapshot_response(snapshot: ReportSnapshot) -> PersonalReportPackageSnapshotResponse:
    data = snapshot.report_data
    return PersonalReportPackageSnapshotResponse(
        **package_snapshot_summary(snapshot).model_dump(),
        payload=data["payload"],
    )


def resolve_payload_field(payload: dict[str, Any], path: str | None) -> Any:
    if not path:
        return ""
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return ""
        current = current[part]
    return current


def package_snapshot_evidence_references(policy: dict[str, Any]) -> str:
    references: set[str] = set()
    for item in [*policy.get("decisions", []), *policy.get("gaps", [])]:
        for anchor in item.get("evidence_anchors", []):
            anchor_type = anchor.get("anchor_type")
            source_id = anchor.get("source_id")
            if anchor_type and source_id:
                references.add(f"{anchor_type}:{source_id}")
    return "|".join(sorted(references))


def package_snapshot_csv(snapshot: PersonalReportPackageSnapshotResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    payload = snapshot.payload
    contract = payload["contract"]
    section_payloads = payload["section_payloads"]
    traceability = section_payloads["traceability_appendix"]
    evidence_bundle_references = package_snapshot_evidence_references(payload["framework_policy"])
    writer.writerow(contract["export_contract"]["csv_columns"])
    for line in traceability["lines"]:
        section_payload = section_payloads.get(line["section_id"], {})
        amount = resolve_payload_field(section_payload, line.get("amount_field"))
        currency = resolve_payload_field(section_payload, line.get("currency_field")) or snapshot.currency
        writer.writerow(
            [
                snapshot.package_id,
                line["section_id"],
                line["line_id"],
                line["label"],
                amount,
                currency,
                line["source_state"],
                snapshot.framework_id.value,
                payload["framework_policy"]["result_id"],
                payload["framework_policy"]["matrix_version"],
                evidence_bundle_references,
            ]
        )
    content = output.getvalue()
    output.close()
    return content
