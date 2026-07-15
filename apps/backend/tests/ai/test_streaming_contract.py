"""Tests for the typed streaming contract (issue #1006, AC6.33).

These tests pin the structure of the streaming endpoints' out-of-band payload
(headers / media type) to typed Pydantic envelopes and assert that applying the
contract does NOT change the wire bytes the routers emitted before.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.advisor.base.types.chat import ChatActionChip, ChatCitation, ChatResponseMetadata
from src.platform.base.types.streaming import (
    ADVISOR_METADATA_HEADER,
    EXPOSE_HEADERS_HEADER,
    ChatStreamEnvelope,
    ChatStreamMediaType,
    ExportStreamEnvelope,
    ExportStreamMediaType,
)


def test_AC6_33_1_chat_envelope_minimal_headers() -> None:
    """AC-advisor.envelope.1: AC6.33.1: Chat envelope with only a session id emits the session header."""
    session_id = uuid4()
    envelope = ChatStreamEnvelope(session_id=session_id)

    headers = envelope.to_headers()

    assert envelope.media_type is ChatStreamMediaType.TEXT_PLAIN
    assert headers["X-Session-Id"] == str(session_id)
    assert "X-Model-Name" not in headers
    assert ADVISOR_METADATA_HEADER not in headers
    assert headers[EXPOSE_HEADERS_HEADER] == "X-Session-Id"


def test_AC6_33_2_chat_envelope_includes_model_and_metadata_headers() -> None:
    """AC-advisor.envelope.2: AC6.33.2: Model + grounding metadata are exposed and CORS-listed in order."""
    session_id = uuid4()
    metadata = ChatResponseMetadata(
        grounded=True,
        citations=[
            ChatCitation(
                label="Balance sheet",
                source_ref="report:balance-sheet",
                confidence_tier="high",
                href="/reports/balance-sheet",
            )
        ],
        actions=[ChatActionChip(kind="review", label="Review 2", href="/review", count=2)],
    )
    envelope = ChatStreamEnvelope(
        session_id=session_id,
        model_name="anthropic/claude",
        advisor_metadata=metadata,
    )

    headers = envelope.to_headers()

    assert headers["X-Model-Name"] == "anthropic/claude"
    # X-Advisor-Metadata must be valid JSON conforming to ChatResponseMetadata.
    parsed = ChatResponseMetadata.model_validate(json.loads(headers[ADVISOR_METADATA_HEADER]))
    assert parsed == metadata
    assert headers[EXPOSE_HEADERS_HEADER] == "X-Session-Id, X-Model-Name, X-Advisor-Metadata"


def test_AC6_33_3_chat_envelope_omits_empty_advisor_metadata() -> None:
    """AC-advisor.envelope.3: AC6.33.3: Empty grounding metadata is not exposed (wire output unchanged)."""
    envelope = ChatStreamEnvelope(
        session_id=uuid4(),
        model_name="m",
        advisor_metadata=ChatResponseMetadata(),  # not grounded, no citations/actions
    )

    headers = envelope.to_headers()

    assert ADVISOR_METADATA_HEADER not in headers
    assert headers[EXPOSE_HEADERS_HEADER] == "X-Session-Id, X-Model-Name"


def test_AC6_33_4_chat_envelope_rejects_invalid_advisor_metadata() -> None:
    """AC-advisor.envelope.4: AC6.33.4: Advisor metadata is validated against the typed model."""
    with pytest.raises(ValidationError):
        ChatStreamEnvelope.model_validate(
            {
                "session_id": str(uuid4()),
                "advisor_metadata": {"grounded": "not-a-bool", "citations": [{"label": ""}]},
            }
        )


def test_AC6_33_5_export_envelope_builds_attachment_headers() -> None:
    """AC-reporting.export-envelope.1: AC6.33.5: Export envelope declares media type + attachment disposition."""
    csv_env = ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename="balance-sheet-2026-01-01.csv")
    json_env = ExportStreamEnvelope(media_type=ExportStreamMediaType.JSON, filename="snapshot.json")

    assert csv_env.media_type.value == "text/csv"
    assert csv_env.to_headers()["Content-Disposition"] == "attachment; filename=balance-sheet-2026-01-01.csv"
    assert json_env.media_type.value == "application/json"
    assert json_env.to_headers()["Content-Disposition"] == "attachment; filename=snapshot.json"


def test_AC6_33_6_export_envelope_rejects_unknown_media_type() -> None:
    """AC-reporting.export-envelope.2: AC6.33.6: Export media type is constrained to the declared wire types."""
    with pytest.raises(ValidationError):
        ExportStreamEnvelope(media_type="application/pdf", filename="x.pdf")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_filename",
    [
        "report\r\nSet-Cookie: x=1.csv",  # CRLF header injection
        "report\n.csv",  # bare LF
        "report\r.csv",  # bare CR
        'report".csv',  # double-quote breaks the disposition parameter
        "report;rm -rf.csv",  # semicolon breaks out of the parameter
        "../../etc/passwd",  # forward-slash path separator
        "dir\\report.csv",  # backslash path separator
    ],
)
def test_AC6_33_9_export_envelope_rejects_unsafe_filename(bad_filename: str) -> None:
    """AC-reporting.export-envelope.4: AC6.33.9: Export filename rejects header-injection / disposition-breaking chars.

    The filename is interpolated into the Content-Disposition header, so CR/LF,
    double-quotes, semicolons, and path separators must be rejected rather than
    merely length-validated.
    """
    with pytest.raises(ValidationError):
        ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename=bad_filename)


def test_AC6_33_9_export_envelope_accepts_normal_filename() -> None:
    """AC6.33.9: A normal attachment filename still passes validation."""
    envelope = ExportStreamEnvelope(
        media_type=ExportStreamMediaType.CSV,
        filename="balance-sheet-2026-01-01.csv",
    )
    assert envelope.filename == "balance-sheet-2026-01-01.csv"
    assert envelope.to_headers()["Content-Disposition"] == ("attachment; filename=balance-sheet-2026-01-01.csv")


@pytest.mark.no_db
async def test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers() -> None:
    """AC-advisor.envelope.5: AC6.33.7: chat_message builds its response from the typed envelope.

    Wire output is unchanged: text/plain body, X-Session-Id header, and a
    dict-shaped advisor metadata payload is still coerced into the typed header.
    """
    from src.advisor.extension.api.chat import chat_message

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    session_id = uuid4()

    async def mock_stream():
        yield "Hello"

    metadata = {
        "grounded": True,
        "citations": [
            {
                "label": "Balance Sheet",
                "source_ref": "balance_sheet.total_equity",
                "confidence_tier": "TRUSTED",
                "href": "/reports/balance-sheet",
            }
        ],
        "actions": [],
    }

    with patch("src.advisor.extension.api.chat.AIAdvisorService") as MockService:
        stream_obj = MagicMock()
        stream_obj.session_id = session_id
        stream_obj.stream = mock_stream()
        stream_obj.model_name = "gpt-4"
        stream_obj.metadata = metadata  # dict path must still serialize
        mock_service = MagicMock()
        mock_service.chat_stream = AsyncMock(return_value=stream_obj)
        MockService.return_value = mock_service

        payload = MagicMock()
        payload.message = "What is my net worth?"
        payload.session_id = None
        payload.model = None

        response = await chat_message(payload, mock_db, uuid4())

    assert response.media_type == ChatStreamMediaType.TEXT_PLAIN.value
    assert response.headers["X-Session-Id"] == str(session_id)
    assert response.headers["X-Model-Name"] == "gpt-4"
    parsed = ChatResponseMetadata.model_validate(json.loads(response.headers[ADVISOR_METADATA_HEADER]))
    assert parsed.grounded is True
    assert parsed.citations[0].label == "Balance Sheet"
    assert response.headers[EXPOSE_HEADERS_HEADER] == "X-Session-Id, X-Model-Name, X-Advisor-Metadata"
