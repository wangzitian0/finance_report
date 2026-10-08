"""AC-workflow.events.1: Statement rejection event severity and title test."""

from datetime import UTC, datetime
from uuid import uuid4

from src.workflow.base.types import WorkflowEventSeverity
from src.workflow.extension.builders import build_review_rejected_event_payload
from src.workflow.extension.events import StatementEventSource


def test_statement_rejection_emits_warning_severity_and_rejected_title():
    now = datetime.now(UTC)
    statement = StatementEventSource(
        id=uuid4(),
        user_id=uuid4(),
        uploaded_document_id=uuid4(),
        file_hash="dummyhash",
        status="rejected",
        stage1_status="_STAGE1_REJECTED",
        created_at=now,
        updated_at=now,
        stage1_reviewed_at=now,
    )
    payload = build_review_rejected_event_payload(statement, filename="margin_2025.csv")
    assert payload.severity == WorkflowEventSeverity.WARNING
    assert payload.title == "Source review rejected"
    assert "rejected" in payload.summary.lower()
    assert payload.action_href == f"/statements/{statement.id}"
