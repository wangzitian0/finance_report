"""Chat API router for the AI advisor."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from src.deps import CurrentUserId, DbSession
from src.llm.extension.catalog import LitellmCatalog
from src.models.chat import ChatMessage, ChatSession, ChatSessionStatus
from src.observability import get_logger
from src.platform import get_owned_or_404, raise_bad_request, raise_not_found, raise_service_unavailable
from src.schemas.chat import (
    ChatHistoryResponse,
    ChatMessagePreview,
    ChatMessageResponse,
    ChatRequest,
    ChatResponseMetadata,
    ChatSessionResponse,
    ChatSessionStatusEnum,
    ChatSuggestionsResponse,
)
from src.schemas.streaming import ChatStreamEnvelope
from src.services.ai_advisor import AIAdvisorError, AIAdvisorService, detect_language

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)
SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS = 2.0


@router.post("", response_class=StreamingResponse)
async def chat_message(
    payload: ChatRequest,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> StreamingResponse:
    """Send a chat message and stream the AI response."""
    service = AIAdvisorService()
    if payload.model:
        allowed_models = {service.primary_model, *service.fallback_models}
        allowed = payload.model in allowed_models
        if not allowed:
            try:
                allowed = await LitellmCatalog().get(payload.model) is not None
            except Exception as e:
                logger.error("Failed to validate model", model=payload.model, error=str(e))
                raise_service_unavailable("Unable to validate requested model at this time.", cause=e)
        if not allowed:
            raise_bad_request("Invalid model selection.")
    try:
        stream = await service.chat_stream(
            db,
            user_id,
            payload.message,
            payload.session_id,
            payload.model,
        )
    except AIAdvisorError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise_not_found("Chat session", cause=exc)
        if "api key" in detail.lower():
            raise_service_unavailable("AI service temporarily unavailable.", cause=exc)
        raise_bad_request(detail, cause=exc)

    # Commit session creation, user message, and any refusal messages
    # that were flushed by the service layer.  For live-streaming responses,
    # _stream_and_store commits the assistant message after the generator completes.
    await db.commit()

    # Declare the streaming response's out-of-band payload (session id, model
    # name, grounding metadata) through the typed contract so the header
    # structure is validated and testable. Wire bytes are unchanged.
    raw_metadata = getattr(stream, "metadata", None)
    advisor_metadata: ChatResponseMetadata | None = None
    if isinstance(raw_metadata, ChatResponseMetadata):
        advisor_metadata = raw_metadata
    elif isinstance(raw_metadata, dict):
        advisor_metadata = ChatResponseMetadata.model_validate(raw_metadata)
    envelope = ChatStreamEnvelope(
        session_id=stream.session_id,
        model_name=stream.model_name,
        advisor_metadata=advisor_metadata,
    )

    return StreamingResponse(
        stream.stream,
        media_type=envelope.media_type.value,
        headers=envelope.to_headers(),
    )


@router.get("/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> ChatHistoryResponse:
    """Retrieve chat session history."""
    sessions: list[ChatSessionResponse] = []

    if session_id:
        session_result = await db.execute(
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .where(ChatSession.user_id == user_id)
            .where(ChatSession.status == ChatSessionStatus.ACTIVE)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            raise_not_found("Chat session")

        messages_result = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
        )
        messages = messages_result.scalars().all()
        message_responses = [ChatMessageResponse.model_validate(msg) for msg in messages]
        last_message = message_responses[-1] if message_responses else None

        sessions.append(
            ChatSessionResponse(
                id=session.id,
                title=session.title,
                status=ChatSessionStatusEnum(session.status.value),
                created_at=session.created_at,
                updated_at=session.updated_at,
                last_active_at=session.last_active_at,
                message_count=len(message_responses),
                last_message=(
                    ChatMessagePreview(
                        role=last_message.role,
                        content=last_message.content,
                        created_at=last_message.created_at,
                    )
                    if last_message
                    else None
                ),
                messages=message_responses,
            )
        )
    else:
        # Optimized query to fetch sessions with message count and last message in fewer steps
        # Using subqueries to avoid N+1 problem
        count_subquery = (
            select(func.count(ChatMessage.id))
            .where(ChatMessage.session_id == ChatSession.id)
            .correlate(ChatSession)
            .scalar_subquery()
        )

        last_msg_subquery = (
            select(ChatMessage.id)
            .where(ChatMessage.session_id == ChatSession.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
            .correlate(ChatSession)
            .scalar_subquery()
        )

        result = await db.execute(
            select(ChatSession, count_subquery, last_msg_subquery)
            .where(ChatSession.user_id == user_id)
            .where(ChatSession.status == ChatSessionStatus.ACTIVE)
            .order_by(ChatSession.last_active_at.desc(), ChatSession.created_at.desc())
            .limit(limit)
        )

        session_data = result.all()
        if not session_data:
            return ChatHistoryResponse(sessions=[])

        # Fetch all "last messages" in one batch
        last_msg_ids = [row[2] for row in session_data if row[2] is not None]
        last_messages_map = {}
        if last_msg_ids:
            msg_result = await db.execute(select(ChatMessage).where(ChatMessage.id.in_(last_msg_ids)))
            last_messages_map = {msg.id: msg for msg in msg_result.scalars().all()}

        for session, message_count, last_msg_id in session_data:
            last_message_obj = last_messages_map.get(last_msg_id)
            last_message = None
            if last_message_obj:
                last_message = ChatMessagePreview(
                    role=last_message_obj.role.value,
                    content=last_message_obj.content,
                    created_at=last_message_obj.created_at,
                )
            sessions.append(
                ChatSessionResponse(
                    id=session.id,
                    title=session.title,
                    status=ChatSessionStatusEnum(session.status.value),
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    last_active_at=session.last_active_at,
                    message_count=message_count or 0,
                    last_message=last_message,
                    messages=[],
                )
            )

    return ChatHistoryResponse(sessions=sessions)


@router.delete("/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> None:
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
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> ChatSuggestionsResponse:
    """Return a suggested question list for the chat UI."""
    resolved_language = language or (detect_language(message) if message else "en")
    suggestions_en = [
        "What are my expenses this month?",
        "What is my current net worth?",
        "Which categories grew the most this month?",
        "How is my reconciliation health?",
        "Any unusual spending trends?",
    ]
    suggestions_zh = [
        "\u8fd9\u4e2a\u6708\u6211\u7684\u652f\u51fa\u662f\u591a\u5c11\uff1f",
        "\u6211\u7684\u51c0\u8d44\u4ea7\u662f\u591a\u5c11\uff1f",
        "\u54ea\u4e9b\u652f\u51fa\u7c7b\u522b\u589e\u957f\u6700\u591a\uff1f",
        "\u6211\u7684\u5bf9\u8d26\u60c5\u51b5\u5982\u4f55\uff1f",
        "\u6709\u6ca1\u6709\u5f02\u5e38\u7684\u6d88\u8d39\u8d8b\u52bf\uff1f",
    ]
    suggestions = suggestions_zh if resolved_language == "zh" else suggestions_en
    structured_suggestions = []
    if include_structured and db is not None and user_id is not None:
        try:
            context = await asyncio.wait_for(
                AIAdvisorService().get_advisor_context(db, user_id),
                timeout=SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS,
            )
            structured_suggestions = context.get("suggestions") or []
        except TimeoutError as exc:
            logger.warning(
                "Timed out loading structured chat suggestions",
                timeout_seconds=SUGGESTIONS_CONTEXT_TIMEOUT_SECONDS,
                error=str(exc),
            )
        except Exception as exc:
            logger.warning("Failed to load structured chat suggestions", error=str(exc))
    return ChatSuggestionsResponse(suggestions=suggestions, structured_suggestions=structured_suggestions)
