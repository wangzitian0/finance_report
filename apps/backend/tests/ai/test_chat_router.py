from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.advisor import AIAdvisorError
from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.llm import AIStreamError
from src.platform import BaseAppException, ResourceNotFoundError
from src.request_context import RequestContext
from src.routers.chat import SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS, chat_history, chat_message, delete_session, suggestions


def _ctx(db=None, user_id=None) -> RequestContext:
    ctx = RequestContext(db or MagicMock(flush=AsyncMock()), user_id or uuid4())
    ctx._base_currency = "SGD"
    return ctx


def _payload(message: str = "What are my expenses?", *, session_id=None) -> MagicMock:
    return MagicMock(message=message, session_id=session_id)


def _mock_chat_service(
    *,
    stream=None,
    model_name: str | None = None,
    metadata=None,
    side_effect=None,
) -> MagicMock:
    service = MagicMock()
    if side_effect is not None:
        service.chat_stream = AsyncMock(side_effect=side_effect)
    else:
        stream_obj = MagicMock(
            session_id=uuid4(), stream=stream, model_name=model_name, cached=False, metadata=metadata
        )
        service.chat_stream = AsyncMock(return_value=stream_obj)
    return service


def _make_mock_session(*, title: str = "Test Session") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        title=title,
        status=ChatSessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        last_active_at=now,
    )


def _make_mock_message(role: ChatMessageRole, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        role=role,
        content=content,
        model_name=None,
        tokens_used=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("kwargs", "expected_fragment"),
    [
        ({"language": "en"}, "What are my expenses"),
        ({"language": "zh"}, "支出"),
        ({"language": None, "message": "这个月花了多少钱"}, "这个月"),
        ({"message": "What are my expenses?"}, "What are my expenses"),
    ],
)
async def test_chat_suggestions_language_and_auto_detect(kwargs: dict, expected_fragment: str) -> None:
    response = await suggestions(**kwargs, ctx=RequestContext(MagicMock(), uuid4()))
    assert response.suggestions and expected_fragment in response.suggestions[0]


@pytest.mark.no_db
async def test_AC21_3_1_and_AC6_5_1_chat_suggestions_structured_and_timeout() -> None:
    mock_db, mock_user_id = MagicMock(), uuid4()
    fact = {
        "basis": "Report package is blocked by one review-required item.",
        "confidence_tier": "blocked",
        "source_refs": ["workflow.status", "report_package.readiness"],
        "limitation": "The report should not be treated as final until review is complete.",
        "next_action_href": "/reports?tab=package",
    }
    with patch("src.routers.chat.AIAdvisorService") as mock_cls:
        default_resp = await suggestions(language="en", ctx=RequestContext(mock_db, mock_user_id))
        assert default_resp.suggestions and default_resp.structured_suggestions == []
        mock_cls.assert_not_called()

        mock_cls.return_value = MagicMock(get_advisor_suggestions=AsyncMock(return_value=[fact]))
        structured_resp = await suggestions(language="en", include_structured=True, ctx=_ctx(mock_db, mock_user_id))
        item = structured_resp.structured_suggestions[0]
        assert (len(structured_resp.structured_suggestions), item.basis, item.confidence_tier, item.source_refs, item.next_action_href) == (
            1,
            fact["basis"],
            "blocked",
            ["workflow.status", "report_package.readiness"],
            "/reports?tab=package",
        )

    async def slow_context(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return [{"basis": "too slow"}]

    assert SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS > 0
    with (
        patch("src.routers.chat.SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS", 0.001),
        patch("src.routers.chat.AIAdvisorService") as mock_cls,
    ):
        mock_cls.return_value = MagicMock(get_advisor_suggestions=AsyncMock(side_effect=slow_context))
        timed_out = await suggestions(language="en", include_structured=True, ctx=_ctx(mock_db, mock_user_id))
        assert timed_out.suggestions and timed_out.structured_suggestions == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_substr"),
    [
        (AIAdvisorError("AI service temporarily unavailable.", status_code=503), 503, "temporarily unavailable"),
        (AIAdvisorError("Session not found", status_code=404), 404, ""),
        (AIAdvisorError("Invalid request format"), 400, ""),
    ],
)
async def test_chat_error_status_mapping(error: AIAdvisorError, expected_status: int, expected_substr: str) -> None:
    with patch("src.routers.chat.AIAdvisorService", return_value=_mock_chat_service(side_effect=error)):
        with pytest.raises(BaseAppException) as exc_info:
            await chat_message(_payload(), ctx=_ctx())
    assert exc_info.value.status_code == expected_status
    assert expected_substr in exc_info.value.detail.lower()


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("model_name", "metadata", "expected_header", "expected_exposed"),
    [
        ("gpt-4", None, ("X-Model-Name", "gpt-4"), "X-Model-Name"),
        (None, None, ("X-Model-Name", None), None),
        (
            None,
            {
                "citations": [{"label": "Balance Sheet", "source_ref": "balance_sheet.total_equity", "confidence_tier": "TRUSTED", "href": "/reports?tab=balance-sheet"}],
                "actions": [{"kind": "reconciliation_review", "label": "Review 2", "href": "/reconciliation?tab=review-queue", "count": 2}],
            },
            ("X-Advisor-Metadata", True),
            "X-Advisor-Metadata",
        ),
    ],
)
async def test_chat_response_headers(model_name, metadata, expected_header, expected_exposed) -> None:
    async def mock_stream():
        yield "Hello"

    service = _mock_chat_service(stream=mock_stream(), model_name=model_name, metadata=metadata)
    with patch("src.routers.chat.AIAdvisorService", return_value=service):
        response = await chat_message(_payload(), ctx=_ctx())
    header_name, expected_val = expected_header
    actual_val = response.headers.get(header_name)
    assert (actual_val is not None) if expected_val is True else (actual_val == expected_val)
    if expected_exposed:
        assert expected_exposed in response.headers.get("Access-Control-Expose-Headers", "")


@pytest.mark.no_db
async def test_AC_advisor_2555_1_stream_error_and_interruption_handling() -> None:
    mock_db, closed = MagicMock(flush=AsyncMock()), False

    async def pre_chunk_fail():
        raise AIAdvisorError("AI service temporarily unavailable.", status_code=503) from AIStreamError(message="AIStreamError: status=429 code=1302", retryable=True)
        yield

    async def midstream_fail():
        yield "Initial token"
        yield " second token"
        raise AIAdvisorError("AIStreamError: midstream reset") from AIStreamError(message="AIStreamError: midstream reset", retryable=True)

    async def empty_stream():
        nonlocal closed
        try:
            if False:
                yield ""
        finally:
            closed = True

    for stream_gen in (pre_chunk_fail(), empty_stream()):
        mock_db.flush.reset_mock()
        with patch("src.routers.chat.AIAdvisorService", return_value=_mock_chat_service(stream=stream_gen, model_name="glm-5.2")):
            with pytest.raises(BaseAppException) as exc_info:
                await chat_message(_payload(), ctx=_ctx(mock_db))
        assert exc_info.value.status_code == 503
        mock_db.flush.assert_not_awaited()
    assert closed is True

    with patch("src.routers.chat.AIAdvisorService", return_value=_mock_chat_service(stream=midstream_fail(), model_name="glm-5.2")):
        response = await chat_message(_payload(), ctx=_ctx(mock_db))
        assert [c async for c in response.body_iterator] == ["Initial token", " second token", "\n\n[Stream interrupted — please retry]"]


def _exec_db(*side_effects, flush: bool = False) -> MagicMock:
    kw: dict = {"execute": AsyncMock(side_effect=list(side_effects))}
    if flush:
        kw["flush"] = AsyncMock()
    return MagicMock(**kw)


async def test_delete_session_found_and_missing() -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await delete_session(uuid4(), ctx=RequestContext(_exec_db(SimpleNamespace(scalar_one_or_none=lambda: None)), uuid4()))
    assert exc_info.value.status_code == 404

    mock_session = MagicMock(spec=ChatSession)
    ok_db = _exec_db(SimpleNamespace(scalar_one_or_none=lambda: mock_session), flush=True)
    await delete_session(uuid4(), ctx=RequestContext(ok_db, uuid4()))
    assert mock_session.status == ChatSessionStatus.DELETED
    ok_db.flush.assert_awaited_once()


async def test_chat_history_single_list_and_missing() -> None:
    session, msg = _make_mock_session(title="Test Session"), _make_mock_message(ChatMessageRole.USER, "Test message")
    single_db = _exec_db(SimpleNamespace(scalar_one_or_none=lambda: session), SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [msg])))
    assert len((await chat_history(session_id=uuid4(), limit=20, ctx=RequestContext(single_db, uuid4()))).sessions) == 1

    active_session, last_msg = _make_mock_session(title="Active Session"), _make_mock_message(ChatMessageRole.ASSISTANT, "Latest answer")
    list_db = _exec_db(SimpleNamespace(all=lambda: [(active_session, 2, last_msg.id)]), SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [last_msg])))
    list_resp = await chat_history(session_id=None, limit=20, ctx=RequestContext(list_db, uuid4()))
    assert (len(list_resp.sessions), list_resp.sessions[0].message_count, list_resp.sessions[0].last_message is not None) == (1, 2, True)
    assert (await chat_history(session_id=None, limit=20, ctx=RequestContext(_exec_db(SimpleNamespace(all=lambda: [])), uuid4()))).sessions == []
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await chat_history(session_id=uuid4(), limit=20, ctx=RequestContext(_exec_db(SimpleNamespace(scalar_one_or_none=lambda: None)), uuid4()))
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    ("method", "path_tpl", "kwargs"),
    [
        ("get", "/chat/history", {"params": {"session_id": "{sid}"}}),
        ("post", "/chat/sessions/{sid}/messages", {"json": {"content": "Hello"}}),
    ],
)
async def test_nonexistent_session_routes_return_404(client, method: str, path_tpl: str, kwargs: dict) -> None:
    sid = str(uuid4())
    path = path_tpl.format(sid=sid)
    call_kwargs = {k: ({pk: pv.format(sid=sid) if isinstance(pv, str) else pv for pk, pv in v.items()} if k == "params" else v) for k, v in kwargs.items()}
    assert (await getattr(client, method)(path, **call_kwargs)).status_code == 404
