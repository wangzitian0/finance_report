"""Chat API router for the AI advisor."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from src.advisor import (
    AIAdvisorError,
    AIAdvisorService,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    detect_language,
)
from src.deps import CurrentUserId, DbSession
from src.llm import LitellmCatalog, LLMError
from src.observability import get_logger
from src.platform import get_owned_or_404, raise_bad_request, raise_not_found, raise_service_unavailable
from src.schemas.chat import (
    ChatHistoryResponse,
    ChatMessagePreview,
    ChatMessageResponse,
    ChatMessageRoleEnum,
    ChatRequest,
    ChatResponseMetadata,
    ChatSessionResponse,
    ChatSessionStatusEnum,
    ChatSuggestionsResponse,
)
from src.schemas.streaming import ChatStreamEnvelope

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS = 2.0

_SUGGESTIONS = {
    "en": [
        "What are my expenses this month?",
        "What is my current net worth?",
        "Which categories grew the most this month?",
        "How is my reconciliation health?",
        "Any unusual spending trends?",
    ],
    "zh": [
        "\u8fd9\u4e2a\u6708\u6211\u7684\u652f\u51fa\u662f\u591a\u5c11\uff1f",
        "\u6211\u7684\u51c0\u8d44\u4ea7\u662f\u591a\u5c11\uff1f",
        "\u54ea\u4e9b\u652f\u51fa\u7c7b\u522b\u589e\u957f\u6700\u591a\uff1f",
        "\u6211\u7684\u5bf9\u8d26\u60c5\u51b5\u5982\u4f55\uff1f",
        "\u6709\u6ca1\u6709\u5f02\u5e38\u7684\u6d88\u8d39\u8d8b\u52bf\uff1f",
    ],
}


def _session_dto(
    session: ChatSession,
    *,
    message_count: int,
    last_preview: ChatMessagePreview | None,
    messages: list[ChatMessageResponse],
) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        status=ChatSessionStatusEnum(session.status.value),
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_active_at=session.last_active_at,
        message_count=message_count,
        last_message=last_preview,
        messages=messages,
    )


async def _validate_requested_model(service: AIAdvisorService, model: str | None) -> None:
    if not model or model in {service.large_model, service.small_model}:
        return
    try:
        allowed = await LitellmCatalog().get(model) is not None
    except Exception as exc:
        logger.error("Failed to validate model", model=model, error=str(exc))
        raise_service_unavailable("Unable to validate requested model at this time.", cause=exc)
    if not allowed:
        raise_bad_request("Invalid model selection.")


@router.post("", response_class=StreamingResponse)
async def chat_message(payload: ChatRequest, *, db: DbSession, user_id: CurrentUserId) -> StreamingResponse:
    """Send a chat message and stream the AI response."""
    service = AIAdvisorService()
    await _validate_requested_model(service, payload.model)
    stream_iter = None
    try:
        stream = await service.chat_stream(db, user_id, payload.message, payload.session_id, payload.model)
        stream_iter = aiter(stream.stream)
        first_chunk = await anext(stream_iter, None)
    except AIAdvisorError as exc:
        if stream_iter is not None and hasattr(stream_iter, "aclose"):
            await stream_iter.aclose()
        detail = str(exc)
        low = detail.lower()
        if "not found" in low:
            raise_not_found("Chat session", cause=exc)
        if any(k in low for k in ("api key", "aistreamerror", "llmerror")) or isinstance(exc.__cause__, LLMError):
            raise_service_unavailable("AI service temporarily unavailable.", cause=exc)
        raise_bad_request(detail, cause=exc)

    if first_chunk is None or not str(first_chunk).strip():
        if stream_iter is not None and hasattr(stream_iter, "aclose"):
            await stream_iter.aclose()
        raise_service_unavailable("AI service temporarily unavailable.")

    await db.commit()

    async def primed_stream() -> AsyncIterator[str]:
        try:
            yield first_chunk
            async for chunk in stream_iter:
                yield chunk
        except (AIAdvisorError, LLMError) as exc:
            logger.warning("Chat stream interrupted after initial chunk", error=str(exc), exc_info=True)
            yield "\n\n[Stream interrupted — please retry]"
        finally:
            if hasattr(stream_iter, "aclose"):
                await stream_iter.aclose()

    raw_metadata = getattr(stream, "metadata", None)
    advisor_metadata = (
        raw_metadata
        if isinstance(raw_metadata, ChatResponseMetadata)
        else ChatResponseMetadata.model_validate(raw_metadata)
        if isinstance(raw_metadata, dict)
        else None
    )
    envelope = ChatStreamEnvelope(
        session_id=stream.session_id,
        model_name=stream.model_name,
        advisor_metadata=advisor_metadata,
    )
    return StreamingResponse(primed_stream(), media_type=envelope.media_type.value, headers=envelope.to_headers())


@router.get("/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ChatHistoryResponse:
    """Retrieve chat session history."""
    if session_id:
        session = (
            await db.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == user_id,
                    ChatSession.status == ChatSessionStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if not session:
            raise_not_found("Chat session")
        messages = (
            (
                await db.execute(
                    select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        msg_dtos = [ChatMessageResponse.model_validate(msg) for msg in messages]
        last = msg_dtos[-1] if msg_dtos else None
        preview = ChatMessagePreview(role=last.role, content=last.content, created_at=last.created_at) if last else None
        return ChatHistoryResponse(
            sessions=[_session_dto(session, message_count=len(msg_dtos), last_preview=preview, messages=msg_dtos)]
        )

    count_sq = (
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == ChatSession.id).correlate(ChatSession).scalar_subquery()
    )
    last_msg_sq = (
        select(ChatMessage.id)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    session_data = (
        await db.execute(
            select(ChatSession, count_sq, last_msg_sq)
            .where(ChatSession.user_id == user_id, ChatSession.status == ChatSessionStatus.ACTIVE)
            .order_by(ChatSession.last_active_at.desc(), ChatSession.created_at.desc())
            .limit(limit)
        )
    ).all()
    if not session_data:
        return ChatHistoryResponse(sessions=[])

    last_ids = [row[2] for row in session_data if row[2] is not None]
    last_map = (
        {
            msg.id: msg
            for msg in (await db.execute(select(ChatMessage).where(ChatMessage.id.in_(last_ids)))).scalars().all()
        }
        if last_ids
        else {}
    )
    sessions = []
    for chat_session, msg_count, last_id in session_data:
        last_obj = last_map.get(last_id)
        preview = (
            ChatMessagePreview(
                role=ChatMessageRoleEnum(last_obj.role.value),
                content=last_obj.content,
                created_at=last_obj.created_at,
            )
            if last_obj
            else None
        )
        sessions.append(_session_dto(chat_session, message_count=msg_count or 0, last_preview=preview, messages=[]))
    return ChatHistoryResponse(sessions=sessions)


@router.delete("/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: UUID, *, db: DbSession, user_id: CurrentUserId) -> None:
    """Soft-delete a chat session."""
    session = await get_owned_or_404(db, ChatSession, session_id, user_id, name="Chat session")
    session.status = ChatSessionStatus.DELETED
    await db.commit()


@router.get("/suggestions", response_model=ChatSuggestionsResponse)
async def suggestions(
    language: str | None = Query(default=None, pattern="^(en|zh)$"),
    message: str | None = Query(default=None, max_length=4000),
    include_structured: Annotated[
        bool,
        Query(
            description=(
                "Include source-cited Advisor Brief suggestions. Defaults to false so the base "
                "suggestion list stays lightweight."
            ),
        ),
    ] = False,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ChatSuggestionsResponse:
    """Return a suggested question list for the chat UI."""
    resolved = language or (detect_language(message) if message else "en")
    structured: list[Any] = []
    if include_structured and db is not None and user_id is not None:
        try:
            structured = await asyncio.wait_for(
                AIAdvisorService().get_advisor_suggestions(db, user_id),
                timeout=SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            logger.warning(
                "Timed out loading structured chat suggestions",
                timeout_seconds=SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS,
                error=str(exc),
            )
        except Exception as exc:
            logger.warning("Failed to load structured chat suggestions", error=str(exc))
    return ChatSuggestionsResponse(suggestions=_SUGGESTIONS["zh" if resolved == "zh" else "en"], structured_suggestions=structured)
