"""Unit tests for POST /chat SSE framing via infra2_sdk.service.sse_stream_response."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.advisor import ChatStream
from src.llm import ModelFailureKind
from src.llm.extension.agent import CallSite, model_call_failed
from src.platform import ServiceUnavailableError
from src.routers import chat as chat_router
from src.schemas.chat import ChatRequest, ChatResponseMetadata

pytestmark = pytest.mark.no_db


def _patch_setup_db(monkeypatch: pytest.MonkeyPatch, base_currency: str = "SGD") -> None:
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = session
    cm.__aexit__.return_value = False
    monkeypatch.setattr(chat_router, "get_session_maker", lambda: (lambda: cm))
    monkeypatch.setattr(chat_router, "get_effective_base_currency", AsyncMock(return_value=base_currency))


async def _collect_body(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


def _parse_sse(raw: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for frame in raw.strip().split("\n\n"):
        if not frame.strip():
            continue
        ev = "message"
        data = "{}"
        for line in frame.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        events.append((ev, json.loads(data)))
    return events


async def test_chat_message_emits_sse_frames_and_envelope_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setup_db(monkeypatch)
    sid = uuid4()

    async def _gen():
        yield "Hello "
        yield "world"

    fake_stream = ChatStream(
        session_id=sid,
        stream=_gen(),
        model_name="glm-5.3-flash",
        cached=False,
        metadata=ChatResponseMetadata(),
    )
    service_instance = MagicMock()
    service_instance.chat_stream = AsyncMock(return_value=fake_stream)
    monkeypatch.setattr(chat_router, "AIAdvisorService", lambda: service_instance)

    response = await chat_router.chat_message(ChatRequest(message="Hi"), user_id=uuid4())
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers["x-session-id"] == str(sid)
    assert response.headers["x-model-name"] == "glm-5.3-flash"
    assert response.headers["x-accel-buffering"] == "no"

    raw = await _collect_body(response)
    events = _parse_sse(raw)
    assert events[0] == ("meta", {"session_id": str(sid), "model_name": "glm-5.3-flash"})
    assert [payload for ev, payload in events if ev == "delta"] == [{"text": "Hello "}, {"text": "world"}]
    assert events[-1] == ("done", {})


async def test_chat_message_midstream_failure_emits_error_event_and_prefirst_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setup_db(monkeypatch)
    sid = uuid4()

    async def _failing_midstream():
        yield "partial "
        raise model_call_failed(CallSite.ADVISOR_CHAT, ModelFailureKind.UNAVAILABLE, "upstream boom")

    service_instance = MagicMock()
    service_instance.chat_stream = AsyncMock(
        return_value=ChatStream(
            session_id=sid,
            stream=_failing_midstream(),
            model_name="glm-5.3-flash",
            cached=False,
            metadata=SimpleNamespace(citations=[], actions=[]),
        )
    )
    monkeypatch.setattr(chat_router, "AIAdvisorService", lambda: service_instance)

    response = await chat_router.chat_message(ChatRequest(message="Hi"), user_id=uuid4())
    events = _parse_sse(await _collect_body(response))
    assert ("delta", {"text": "partial "}) in events
    assert ("error", {"error": "AI service temporarily unavailable."}) in events
    assert "[Stream interrupted" not in json.dumps(events)

    async def _empty_stream():
        if False:
            yield ""

    service_instance.chat_stream = AsyncMock(
        return_value=ChatStream(
            session_id=sid,
            stream=_empty_stream(),
            model_name="glm-5.3-flash",
            cached=False,
            metadata=ChatResponseMetadata(),
        )
    )
    with pytest.raises(ServiceUnavailableError, match="AI service temporarily unavailable"):
        await chat_router.chat_message(ChatRequest(message="Hi"), user_id=uuid4())
