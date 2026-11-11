"""Pure helpers for personal report-package snapshot assembly & export."""

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
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value.value if isinstance(value, Enum) else value


def package_dates(*, start_date: date | None, end_date: date | None, as_of_date: date | None) -> tuple[date, date, date]:
    report_end = end_date or as_of_date or date.today()
    return start_date or report_end - timedelta(days=365), report_end, as_of_date or report_end


def package_currency(currency: str | None, *, default_currency: str = "SGD") -> str:
    return normalize_currency_code(currency or default_currency)


def package_snapshot_summary(
    snapshot: ReportSnapshot, *, default_currency: str = "SGD"
) -> PersonalReportPackageSnapshotSummary:
    try:
        doc = package_snapshot_document(snapshot)
    except PackageDocumentVersionError:
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
            currency=str(data.get("currency") or default_currency).upper(),
            readiness_state="legacy_unproven",
            is_latest=snapshot.is_latest,
            created_at=snapshot.created_at,
        )
    ctx = doc.context
    return PersonalReportPackageSnapshotSummary(
        id=snapshot.id,
        package_id=doc.package_id,
        status=doc.status,
        framework_id=ctx.framework_id,
        start_date=ctx.start_date,
        end_date=ctx.end_date,
        as_of_date=ctx.as_of_date,
        currency=ctx.currency,
        readiness_state=doc.readiness.state.value,
        is_latest=snapshot.is_latest,
        created_at=snapshot.created_at,
    )


def package_snapshot_document(snapshot: ReportSnapshot) -> PersonalReportPackageDocument:
    try:
        doc = PersonalReportPackageDocument.model_validate(snapshot.report_data)
    except ValidationError as exc:
        raise PackageDocumentVersionError("This package snapshot predates document schema version 2") from exc
    if doc.lifecycle is not PersonalReportPackageDocumentLifecycle.FROZEN:
        raise PackageDocumentVersionError("Saved package snapshot is not a frozen document")
    if doc.snapshot_id != snapshot.id:
        raise PackageDocumentVersionError("Saved package document identity does not match its snapshot")
    return doc


def package_snapshot_response(snapshot: ReportSnapshot) -> PersonalReportPackageSnapshotResponse:
    return PersonalReportPackageSnapshotResponse(
        **package_snapshot_summary(snapshot).model_dump(), document=package_snapshot_document(snapshot)
    )


def resolve_payload_field(payload: dict[str, Any], path: str | None) -> Any:
    if not path:
        return ""
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ""
        cur = cur[part]
    return cur


def _attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    return getattr(obj, key) if hasattr(obj, key) else obj.get(key, default)


def package_evidence_references(policy: Any) -> list[str]:
    refs: set[str] = set()
    for item in [*_attr_or_key(policy, "decisions", []), *_attr_or_key(policy, "gaps", [])]:
        for anchor in _attr_or_key(item, "evidence_anchors", []):
            atype, sid = _attr_or_key(anchor, "anchor_type"), _attr_or_key(anchor, "source_id")
            if atype and sid:
                refs.add(f"{atype}:{sid}")
    return sorted(refs)


def package_snapshot_evidence_references(policy: Any) -> str:
    return "|".join(package_evidence_references(policy))


def package_snapshot_input_decision_references(document: PersonalReportPackageDocument) -> str:
    return "|".join(sorted(f"{i.decision_id}@{ref}" for i in document.input_manifest for ref in i.input_refs))


def package_snapshot_csv(snapshot: PersonalReportPackageSnapshotResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    doc = snapshot.document
    section_payloads = doc.sections.model_dump(mode="json")
    ev_refs = package_snapshot_evidence_references(doc.framework_policy)
    in_refs = package_snapshot_input_decision_references(doc)
    writer.writerow(doc.contract.export_contract.csv_columns)
    for line in doc.sections.traceability_appendix.lines:
        sp = section_payloads.get(line.section_id, {})
        currency = (
            resolve_payload_field(sp, line.currency_field) or snapshot.currency if line.currency_field else ""
        )
        writer.writerow(
            [
                snapshot.package_id,
                line.section_id,
                line.line_id,
                line.label,
                resolve_payload_field(sp, line.amount_field),
                currency,
                line.source_state,
                snapshot.framework_id.value,
                doc.framework_policy.result_id,
                doc.framework_policy.matrix_version,
                ev_refs,
                in_refs,
            ]
        )
    return output.getvalue()
