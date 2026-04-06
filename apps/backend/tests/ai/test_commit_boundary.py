"""Tests for AI advisor commit boundary compliance (Issue #182)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus


@pytest.mark.asyncio
async def test_get_or_create_session_uses_flush_not_commit(db: AsyncSession, test_user) -> None:
    """AC12.3.1: _get_or_create_session uses flush(), allowing rollback."""
    from src.services.ai_advisor import AIAdvisorService

    service = AIAdvisorService()
    session = await service._get_or_create_session(db, test_user.id, None, "Hello world")

    assert session.id is not None
    assert session.title == "Hello world"

    await db.rollback()

    result = await db.execute(select(ChatSession).where(ChatSession.id == session.id))
    assert result.scalar_one_or_none() is None, "Session was committed instead of flushed"


@pytest.mark.asyncio
async def test_get_or_create_existing_session_uses_flush(db: AsyncSession, test_user) -> None:
    """AC12.3.2: _get_or_create_session with existing session uses flush()."""
    from src.services.ai_advisor import AIAdvisorService

    existing = ChatSession(
        user_id=test_user.id,
        title="Existing session",
        status=ChatSessionStatus.ACTIVE,
    )
    db.add(existing)
    await db.commit()
    await db.refresh(existing)
    session_id = existing.id

    service = AIAdvisorService()
    session = await service._get_or_create_session(db, test_user.id, session_id, "Follow-up")

    assert session.id == session_id

    await db.rollback()

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    refreshed = result.scalar_one()
    assert refreshed is not None


@pytest.mark.asyncio
async def test_record_message_uses_flush_not_commit(db: AsyncSession, test_user) -> None:
    """AC12.3.3: _record_message uses flush(), allowing rollback."""
    from src.services.ai_advisor import AIAdvisorService

    service = AIAdvisorService()

    session = ChatSession(
        user_id=test_user.id,
        title="Test session",
        status=ChatSessionStatus.ACTIVE,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    message = await service._record_message(db, session, ChatMessageRole.USER, "Test message")

    assert message.id is not None

    await db.rollback()

    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message.id))
    assert result.scalar_one_or_none() is None, "Message was committed instead of flushed"
