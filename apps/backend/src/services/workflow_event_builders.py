"""Workflow event payload builders (split from workflow_events.py).

Pure constructors that turn statements / readiness blockers / package readiness
into WorkflowEventCreate payloads. No DB or session logic.
"""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from src.models.statement_summary import StatementSummary
from src.models.workflow import WorkflowEventFamily, WorkflowEventSeverity, WorkflowReportImpact
from src.schemas.workflow import WorkflowEventCreate

PACKAGE_WORKFLOW_SOURCE_ID = uuid5(NAMESPACE_URL, "finance-report:personal-financial-report-package")


def build_workflow_dedupe_key(*, family: WorkflowEventFamily, source_type: str, source_id: UUID) -> str:
    """Build the stable per-user dedupe key for a source-derived workflow event."""
    return f"{source_type}:{source_id}:{family.value}"


def _build_statement_event_payload(
    statement: StatementSummary,
    *,
    family: WorkflowEventFamily,
    occurred_at: datetime,
    severity: WorkflowEventSeverity,
    title: str,
    summary: str,
    action_href: str,
    report_impact: WorkflowReportImpact,
) -> WorkflowEventCreate:
    """Shared builder for the per-statement workflow events (uploaded / parse-failed
    / review-required / review-completed), which differ only in their family,
    timestamp, severity, copy, deep link, and report impact."""
    return WorkflowEventCreate(
        occurred_at=occurred_at,
        family=family,
        severity=severity,
        title=title,
        summary=summary,
        source_type="bank_statement",
        source_id=statement.id,
        action_href=action_href,
        report_impact=report_impact,
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )


def build_uploaded_statement_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the deterministic uploaded-statement workflow event payload."""
    return _build_statement_event_payload(
        statement,
        family=WorkflowEventFamily.SOURCE_UPLOADED,
        occurred_at=statement.created_at,
        severity=WorkflowEventSeverity.INFO,
        title="Statement uploaded",
        summary=f"{filename} was uploaded and is ready for processing.",
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.PROCESSING,
    )


def build_statement_parsing_failed_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the user-action event for a failed statement parse."""
    return _build_statement_event_payload(
        statement,
        family=WorkflowEventFamily.SOURCE_PARSING_FAILED,
        occurred_at=statement.updated_at or statement.created_at,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        title="Statement parsing failed",
        summary=f"{filename} could not be parsed and needs attention.",
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.BLOCKED,
    )


def build_review_required_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the user-action event for pending Stage 1 review."""
    return _build_statement_event_payload(
        statement,
        family=WorkflowEventFamily.REVIEW_REQUIRED,
        occurred_at=statement.updated_at or statement.created_at,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        title="Source review required",
        summary=f"{filename} needs source review before report readiness can advance.",
        # Deep-link straight to this statement's review surface (EPIC-022 PR2):
        # the standalone Review Queue page is gone; the notification card is the
        # entry point, so it must point at the specific item to review.
        action_href=f"/statements/{statement.id}/review",
        report_impact=WorkflowReportImpact.BLOCKED,
    )


def build_review_completed_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the routine success event for completed Stage 1 review."""
    return _build_statement_event_payload(
        statement,
        family=WorkflowEventFamily.REVIEW_COMPLETED,
        occurred_at=statement.stage1_reviewed_at or statement.updated_at or statement.created_at,
        severity=WorkflowEventSeverity.SUCCESS,
        title="Source review completed",
        summary=f"{filename} source review is complete.",
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.NONE,
    )


def _readiness_blocker_source_id(code: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"finance-report:readiness-blocker:{code}")


def build_readiness_blocker_event_payload(blocker: dict[str, str | int]) -> WorkflowEventCreate:
    """Build a lightweight user-facing event from a report-readiness blocker."""
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
        source_id=_readiness_blocker_source_id(code),
        action_href=str(blocker["action_href"]),
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key=f"readiness-blocker:{code}:{family.value}",
    )


def build_report_state_event_payload(package_readiness: dict) -> WorkflowEventCreate | None:
    """Build report ready/generated events from package readiness."""
    state = str(package_readiness["state"])
    if state not in {"ready", "generated"}:
        return None
    family = WorkflowEventFamily.REPORT_GENERATED if state == "generated" else WorkflowEventFamily.REPORT_READY
    title = "Report package generated" if state == "generated" else "Report package ready"
    summary = (
        "The personal report package has been generated."
        if state == "generated"
        else "The personal report package is ready to review."
    )
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=family,
        severity=WorkflowEventSeverity.SUCCESS,
        title=title,
        summary=summary,
        source_type="report_package",
        source_id=PACKAGE_WORKFLOW_SOURCE_ID,
        action_href=str(package_readiness["action_href"]),
        report_impact=WorkflowReportImpact.READY,
        dedupe_key=f"report-package:{family.value}",
    )
