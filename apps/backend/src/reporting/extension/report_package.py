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

from pydantic import ValidationError

from src.audit.money.currency import normalize_currency_code
from src.config import settings
from src.reporting.orm import ReportSnapshot
from src.schemas import (
    PersonalReportingFrameworkId,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageSnapshotResponse,
    PersonalReportPackageSnapshotStatus,
    PersonalReportPackageSnapshotSummary,
)


class PackageDocumentVersionError(ValueError):
    """A persisted snapshot cannot be reopened through the current document contract."""


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


def package_snapshot_summary(snapshot: ReportSnapshot) -> PersonalReportPackageSnapshotSummary:
    try:
        document = package_snapshot_document(snapshot)
    except PackageDocumentVersionError:
        # Historical JSON remains visible as explicitly unproven metadata, but
        # cannot re-enter readiness, rendering, or export as a typed document.
        data = snapshot.report_data
        return PersonalReportPackageSnapshotSummary(
            id=snapshot.id,
            package_id=str(data.get("package_id") or "personal-financial-report-package"),
            status=PersonalReportPackageSnapshotStatus.LEGACY_UNPROVEN,
            framework_id=PersonalReportingFrameworkId(
                data.get("framework_id") or PersonalReportingFrameworkId.US_GAAP_LIKE.value
            ),
            start_date=snapshot.start_date or snapshot.as_of_date,
            end_date=snapshot.as_of_date,
            as_of_date=snapshot.as_of_date,
            currency=str(data.get("currency") or settings.base_currency).upper(),
            readiness_state="legacy_unproven",
            is_latest=snapshot.is_latest,
            created_at=snapshot.created_at,
        )
    return PersonalReportPackageSnapshotSummary(
        id=snapshot.id,
        package_id=document.package_id,
        status=document.status,
        framework_id=document.context.framework_id,
        start_date=document.context.start_date,
        end_date=document.context.end_date,
        as_of_date=document.context.as_of_date,
        currency=document.context.currency,
        readiness_state=document.readiness.state.value,
        is_latest=snapshot.is_latest,
        created_at=snapshot.created_at,
    )


def package_snapshot_document(snapshot: ReportSnapshot) -> PersonalReportPackageDocument:
    """Validate one frozen v2 document instead of exposing the raw JSONB payload."""
    try:
        document = PersonalReportPackageDocument.model_validate(snapshot.report_data)
    except ValidationError as exc:
        raise PackageDocumentVersionError("This package snapshot predates document schema version 2") from exc
    if document.lifecycle is not PersonalReportPackageDocumentLifecycle.FROZEN:
        raise PackageDocumentVersionError("Saved package snapshot is not a frozen document")
    if document.snapshot_id != snapshot.id:
        raise PackageDocumentVersionError("Saved package document identity does not match its snapshot")
    return document


def package_snapshot_response(snapshot: ReportSnapshot) -> PersonalReportPackageSnapshotResponse:
    return PersonalReportPackageSnapshotResponse(
        **package_snapshot_summary(snapshot).model_dump(),
        document=package_snapshot_document(snapshot),
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


def package_snapshot_evidence_references(policy: Any) -> str:
    references: set[str] = set()
    decisions = policy.decisions if hasattr(policy, "decisions") else policy.get("decisions", [])
    gaps = policy.gaps if hasattr(policy, "gaps") else policy.get("gaps", [])
    for item in [*decisions, *gaps]:
        anchors = item.evidence_anchors if hasattr(item, "evidence_anchors") else item.get("evidence_anchors", [])
        for anchor in anchors:
            anchor_type = anchor.anchor_type if hasattr(anchor, "anchor_type") else anchor.get("anchor_type")
            source_id = anchor.source_id if hasattr(anchor, "source_id") else anchor.get("source_id")
            if anchor_type and source_id:
                references.add(f"{anchor_type}:{source_id}")
    return "|".join(sorted(references))


def package_snapshot_input_decision_references(document: PersonalReportPackageDocument) -> str:
    """Serialize the exact frozen input-decision manifest without live lookups."""
    return "|".join(
        sorted(f"{item.decision_id}@{input_ref}" for item in document.input_manifest for input_ref in item.input_refs)
    )


def package_snapshot_csv(snapshot: PersonalReportPackageSnapshotResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    document = snapshot.document
    section_payloads = document.sections.model_dump(mode="json")
    traceability = document.sections.traceability_appendix
    evidence_bundle_references = package_snapshot_evidence_references(document.framework_policy)
    input_decision_references = package_snapshot_input_decision_references(document)
    writer.writerow(document.contract.export_contract.csv_columns)
    for line in traceability.lines:
        section_payload = section_payloads.get(line.section_id, {})
        amount = resolve_payload_field(section_payload, line.amount_field)
        # Disclosure-only rows have no monetary/currency path; never fabricate
        # a presentation currency for those non-amount CSV records.
        currency = (
            resolve_payload_field(section_payload, line.currency_field) or snapshot.currency
            if line.currency_field
            else ""
        )
        writer.writerow(
            [
                snapshot.package_id,
                line.section_id,
                line.line_id,
                line.label,
                amount,
                currency,
                line.source_state,
                snapshot.framework_id.value,
                document.framework_policy.result_id,
                document.framework_policy.matrix_version,
                evidence_bundle_references,
                input_decision_references,
            ]
        )
    content = output.getvalue()
    output.close()
    return content
