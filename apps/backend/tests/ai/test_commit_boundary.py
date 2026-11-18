from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import AIAdvisorService
from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus


async def test_advisor_session_and_message_use_flush_not_commit(db: AsyncSession, test_user) -> None:
    service, user_id = AIAdvisorService(), test_user.id
    session = await service._get_or_create_session(db, user_id, None, "Hello world")
    session_id = session.id
    assert session_id is not None and session.title == "Hello world"
    await db.rollback()
    assert (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none() is None

    existing = ChatSession(user_id=user_id, title="Existing session", status=ChatSessionStatus.ACTIVE)
    db.add(existing)
    await db.commit()
    await db.refresh(existing)
    existing_id = existing.id
    resumed = await service._get_or_create_session(db, user_id, existing_id, "Follow-up")
    msg = await service._record_message(db, existing, ChatMessageRole.USER, "Test message")
    msg_id = msg.id
    assert resumed.id == existing_id and msg_id is not None
    await db.rollback()
    assert (await db.execute(select(ChatSession).where(ChatSession.id == existing_id))).scalar_one() is not None and (await db.execute(select(ChatMessage).where(ChatMessage.id == msg_id))).scalar_one_or_none() is None
