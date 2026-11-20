from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.request_context import RequestContext
from src.schemas.chat import ChatActionChip, ChatCitation, ChatResponseMetadata
from src.schemas.streaming import (
    ADVISOR_METADATA_HEADER,
    EXPOSE_HEADERS_HEADER,
    ChatStreamEnvelope,
    ChatStreamMediaType,
    ExportStreamEnvelope,
    ExportStreamMediaType,
)


def test_AC6_33_chat_and_export_envelopes() -> None:
    sid = uuid4()
    min_h = ChatStreamEnvelope(session_id=sid).to_headers()
    meta = ChatResponseMetadata(citations=[ChatCitation(label="Balance sheet", source_ref="report:balance-sheet", confidence_tier="high", href="/reports?tab=balance-sheet")], actions=[ChatActionChip(kind="review", label="Review 2", href="/audit", count=2)])
    full_h = ChatStreamEnvelope(session_id=sid, model_name="anthropic/claude", advisor_metadata=meta).to_headers()
    empty_h = ChatStreamEnvelope(session_id=sid, model_name="m", advisor_metadata=ChatResponseMetadata()).to_headers()
    csv_env, json_env = ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename="balance-sheet-2026-01-01.csv"), ExportStreamEnvelope(media_type=ExportStreamMediaType.JSON, filename="snapshot.json")
    assert (min_h["X-Session-Id"], "X-Model-Name" in min_h, ADVISOR_METADATA_HEADER in min_h, min_h[EXPOSE_HEADERS_HEADER]) == (str(sid), False, False, "X-Session-Id")
    assert (full_h["X-Model-Name"], ChatResponseMetadata.model_validate(json.loads(full_h[ADVISOR_METADATA_HEADER])), full_h[EXPOSE_HEADERS_HEADER]) == ("anthropic/claude", meta, "X-Session-Id, X-Model-Name, X-Advisor-Metadata")
    assert ADVISOR_METADATA_HEADER not in empty_h and empty_h[EXPOSE_HEADERS_HEADER] == "X-Session-Id, X-Model-Name"
    assert (csv_env.media_type.value, csv_env.to_headers()["Content-Disposition"], json_env.media_type.value, json_env.to_headers()["Content-Disposition"]) == (
        "text/csv", "attachment; filename=balance-sheet-2026-01-01.csv", "application/json", "attachment; filename=snapshot.json",
    )
    with pytest.raises(ValidationError):
        ChatStreamEnvelope.model_validate({"session_id": str(sid), "advisor_metadata": {"citations": [{"label": ""}]}})


@pytest.mark.parametrize(("media_type", "filename"), [("application/pdf", "x.pdf"), (ExportStreamMediaType.CSV, "report\r\nSet-Cookie: x=1.csv"), (ExportStreamMediaType.CSV, "report\n.csv"), (ExportStreamMediaType.CSV, "report\r.csv"), (ExportStreamMediaType.CSV, 'report".csv'), (ExportStreamMediaType.CSV, "report;rm -rf.csv"), (ExportStreamMediaType.CSV, "../../etc/passwd"), (ExportStreamMediaType.CSV, "dir\\report.csv")])
def test_AC6_33_export_envelope_rejects_invalid_inputs(media_type, filename: str) -> None:
    with pytest.raises(ValidationError):
        ExportStreamEnvelope(media_type=media_type, filename=filename)


@pytest.mark.no_db
async def test_AC6_33_7_chat_router_uses_envelope_media_type_and_headers() -> None:
    from src.routers.chat import chat_message

    session_id = uuid4()

    async def mock_stream():
        yield "Hello"

    fake_db = MagicMock(commit=AsyncMock(), flush=AsyncMock())

    class _MakerCtx:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *_args):
            return False

    stream_obj = MagicMock(session_id=session_id, stream=mock_stream(), model_name="gpt-4", metadata={"citations": [{"label": "Balance Sheet", "source_ref": "balance_sheet.total_equity", "confidence_tier": "TRUSTED", "href": "/reports?tab=balance-sheet"}], "actions": []})
    with (
        patch("src.routers.chat.get_session_maker", return_value=(lambda: _MakerCtx())),
        patch("src.routers.chat.get_effective_base_currency", AsyncMock(return_value="SGD")),
        patch("src.routers.chat.AIAdvisorService", return_value=MagicMock(chat_stream=AsyncMock(return_value=stream_obj))),
    ):
        response = await chat_message(MagicMock(message="What is my net worth?", session_id=None), user_id=uuid4())
    parsed = ChatResponseMetadata.model_validate(json.loads(response.headers[ADVISOR_METADATA_HEADER]))
    assert (response.media_type, response.headers["X-Session-Id"], response.headers["X-Model-Name"], parsed.citations[0].label, response.headers[EXPOSE_HEADERS_HEADER]) == (
        ChatStreamMediaType.TEXT_PLAIN.value, str(session_id), "gpt-4", "Balance Sheet", "X-Session-Id, X-Model-Name, X-Advisor-Metadata",
    )
