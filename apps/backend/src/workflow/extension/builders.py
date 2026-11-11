"""Workflow event payload builders."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from src.extraction import StatementEventSource
from src.workflow.base.types import (
    WorkflowEventCreate,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowReportImpact,
)

PACKAGE_WORKFLOW_SOURCE_ID = uuid5(NAMESPACE_URL, "finance-report:personal-financial-report-package")
RECONCILIATION_WORKFLOW_SOURCE_ID = uuid5(NAMESPACE_URL, "finance-report:reconciliation-pending-review")

_STATEMENT_SPECS: dict[
    str, tuple[WorkflowEventFamily, str, WorkflowEventSeverity, str, str, WorkflowReportImpact]
] = {
    "uploaded": (
        WorkflowEventFamily.SOURCE_UPLOADED,
        "created",
        WorkflowEventSeverity.INFO,
        "Statement uploaded",
        "{filename} was uploaded and is ready for processing.",
        WorkflowReportImpact.PROCESSING,
    ),
    "failed": (
        WorkflowEventFamily.SOURCE_PARSING_FAILED,
        "updated",
        WorkflowEventSeverity.ACTION_REQUIRED,
        "Statement parsing failed",
        "{filename} could not be parsed and needs attention.",
        WorkflowReportImpact.BLOCKED,
    ),
    "review_required": (
        WorkflowEventFamily.REVIEW_REQUIRED,
        "updated",
        WorkflowEventSeverity.ACTION_REQUIRED,
        "Source review required",
        "{filename} needs source review before report readiness can advance.",
        WorkflowReportImpact.BLOCKED,
    ),
    "review_completed": (
        WorkflowEventFamily.REVIEW_COMPLETED,
        "reviewed",
        WorkflowEventSeverity.SUCCESS,
        "Source review completed",
        "{filename} source review is complete.",
        WorkflowReportImpact.NONE,
    ),
    "review_rejected": (
        WorkflowEventFamily.REVIEW_COMPLETED,
        "reviewed",
        WorkflowEventSeverity.WARNING,
        "Source review rejected",
        "{filename} source review was rejected.",
        WorkflowReportImpact.NONE,
    ),
}


def build_workflow_dedupe_key(*, family: WorkflowEventFamily, source_type: str, source_id: UUID) -> str:
    return f"{source_type}:{source_id}:{family.value}"


def _statement_event(kind: str, statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    family, ts_kind, severity, title, summary_tpl, impact = _STATEMENT_SPECS[kind]
    if ts_kind == "created":
        occurred_at = statement.created_at
    elif ts_kind == "updated":
        occurred_at = statement.updated_at or statement.created_at
    else:
        occurred_at = statement.stage1_reviewed_at or statement.updated_at or statement.created_at
    return WorkflowEventCreate(
        occurred_at=occurred_at,
        family=family,
        severity=severity,
        title=title,
        summary=summary_tpl.format(filename=filename),
        source_type="bank_statement",
        source_id=statement.id,
        action_href=f"/statements/{statement.id}",
        report_impact=impact,
        dedupe_key=build_workflow_dedupe_key(family=family, source_type="bank_statement", source_id=statement.id),
    )


def build_uploaded_statement_event_payload(statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    return _statement_event("uploaded", statement, filename)


def build_statement_parsing_failed_event_payload(statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    return _statement_event("failed", statement, filename)


def build_review_required_event_payload(statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    return _statement_event("review_required", statement, filename)


def build_review_completed_event_payload(statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    return _statement_event("review_completed", statement, filename)


def build_review_rejected_event_payload(statement: StatementEventSource, filename: str) -> WorkflowEventCreate:
    return _statement_event("review_rejected", statement, filename)


def build_readiness_blocker_event_payload(blocker: dict[str, str | int]) -> WorkflowEventCreate:
    code = str(blocker["code"])
    family = (
        WorkflowEventFamily.RECONCILIATION_BLOCKED
        if code == "reconciliation_blocked"
        else WorkflowEventFamily.REPORT_BLOCKED
    )
    count = int(blocker.get("count", 1))
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=family,
        severity=WorkflowEventSeverity.BLOCKED,
        title=str(blocker["label"]),
        summary=f"{blocker['reason']} ({count} item{'s' if count != 1 else ''}).",
        source_type="readiness_blocker",
        source_id=uuid5(NAMESPACE_URL, f"finance-report:readiness-blocker:{code}"),
        action_href=str(blocker["action_href"]),
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key=f"readiness-blocker:{code}:{family.value}",
    )


def build_reconciliation_review_event_payload(pending_count: int) -> WorkflowEventCreate:
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=WorkflowEventFamily.RECONCILIATION_BLOCKED,
        severity=WorkflowEventSeverity.BLOCKED,
        title="Reconciliation review required",
        summary=(
            f"{pending_count} pending reconciliation match"
            f"{'es' if pending_count != 1 else ''} must be accepted or rejected."
        ),
        source_type="reconciliation",
        source_id=RECONCILIATION_WORKFLOW_SOURCE_ID,
        action_href="/reconciliation?tab=review-queue",
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key="reconciliation:pending-review",
    )


def build_report_state_event_payload(package_readiness: dict) -> WorkflowEventCreate | None:
    state = str(package_readiness["state"])
    if state not in {"ready", "generated"}:
        return None
    is_gen = state == "generated"
    family = WorkflowEventFamily.REPORT_GENERATED if is_gen else WorkflowEventFamily.REPORT_READY
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=family,
        severity=WorkflowEventSeverity.SUCCESS,
        title="Report package generated" if is_gen else "Report package ready",
        summary=(
            "The personal report package has been generated."
            if is_gen
            else "The personal report package is ready to review."
        ),
        source_type="report_package",
        source_id=PACKAGE_WORKFLOW_SOURCE_ID,
        action_href=str(package_readiness["action_href"]),
        report_impact=WorkflowReportImpact.READY,
        dedupe_key=f"report-package:{family.value}",
    )
