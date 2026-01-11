"""Chat API router for the AI advisor."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import ChatMessage, ChatSession, ChatSessionStatus
from src.schemas.chat import (
    ChatHistoryResponse,
    ChatMessagePreview,
    ChatMessageResponse,
    ChatRequest,
    ChatSessionResponse,
    ChatSessionStatusEnum,
    ChatSuggestionsResponse,
)
from src.services.ai_advisor import AIAdvisorError, AIAdvisorService, detect_language

router = APIRouter(prefix="/api/chat", tags=["chat"])

MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def get_chat_user_id() -> UUID:
    """Return mock user ID until authentication is implemented."""
    return MOCK_USER_ID


@router.post("", response_class=StreamingResponse)
async def chat_message(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_chat_user_id),
) -> StreamingResponse:
    """Send a chat message and stream the AI response."""
    service = AIAdvisorService()
    try:
        stream = await service.chat_stream(db, user_id, payload.message, payload.session_id)
    except AIAdvisorError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "api key" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service temporarily unavailable.",
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    headers = {
        "X-Session-Id": str(stream.session_id),
        "Access-Control-Expose-Headers": "X-Session-Id",
    }
    if stream.model_name:
        headers["X-Model-Name"] = stream.model_name
        headers["Access-Control-Expose-Headers"] += ", X-Model-Name"

    return StreamingResponse(stream.stream, media_type="text/plain", headers=headers)


@router.get("/history", response_model=ChatHistoryResponse)
async def chat_history(
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_chat_user_id),
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
            raise HTTPException(status_code=404, detail="Chat session not found")

        messages_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
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
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .where(ChatSession.status == ChatSessionStatus.ACTIVE)
            .order_by(ChatSession.last_active_at.desc(), ChatSession.created_at.desc())
            .limit(limit)
        )
        for session in result.scalars().all():
            count_result = await db.execute(
                select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session.id)
            )
            message_count = count_result.scalar_one()
            last_result = await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(1)
            )
            last_message_obj = last_result.scalar_one_or_none()
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
                    message_count=message_count,
                    last_message=last_message,
                    messages=[],
                )
            )

    return ChatHistoryResponse(sessions=sessions)


@router.delete("/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_chat_user_id),
) -> None:
    """Soft-delete a chat session."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .where(ChatSession.user_id == user_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    session.status = ChatSessionStatus.DELETED
    await db.commit()


@router.get("/suggestions", response_model=ChatSuggestionsResponse)
async def suggestions(
    language: str | None = Query(default=None, pattern="^(en|zh)$"),
    message: str | None = Query(default=None, max_length=4000),
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
    return ChatSuggestionsResponse(suggestions=suggestions)
