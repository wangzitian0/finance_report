from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import AIAdvisorService
from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.config import settings


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
    assert (await db.execute(select(ChatSession).where(ChatSession.id == existing_id))).scalar_one() is not None and (
        await db.execute(select(ChatMessage).where(ChatMessage.id == msg_id))
    ).scalar_one_or_none() is None


async def test_post_chat_releases_db_session_during_llm_stream(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import active_guarded_app_transactions

    observed_open_during_stream: list[int] = []

    async def fake_stream_openrouter(self, *_args, **_kwargs):
        observed_open_during_stream.append(active_guarded_app_transactions())
        yield ("Checking ", "mock-model")
        observed_open_during_stream.append(active_guarded_app_transactions())
        yield ("balance.", "mock-model")

    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    monkeypatch.setattr(AIAdvisorService, "_stream_openrouter", fake_stream_openrouter)

    resp = await client.post("/chat", json={"message": "What is my balance?"})

    assert resp.status_code == 200
    assert "Checking balance." in resp.text
    assert observed_open_during_stream == [0, 0]
    msgs = (await db.execute(select(ChatMessage).order_by(ChatMessage.created_at))).scalars().all()
    assert [m.role for m in msgs] == [ChatMessageRole.USER, ChatMessageRole.ASSISTANT]
    assert "Checking balance." in msgs[1].content


async def test_post_chat_names_the_large_role_in_the_model_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The staging gate reads `X-Model-Name` to prove that staging pins no model (#2566, #2953)."""

    async def fake_stream_openrouter(self, *_args, **_kwargs):
        yield ("ok", self.large_model)

    monkeypatch.setattr(settings, "ai_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "large_model", "role-large-model", raising=False)
    monkeypatch.setattr(settings, "small_model", "role-small-model", raising=False)
    monkeypatch.setattr(AIAdvisorService, "_stream_openrouter", fake_stream_openrouter)

    resp = await client.post("/chat", json={"message": "What is my balance?"})

    assert resp.status_code == 200
    assert resp.headers["X-Model-Name"] == "role-large-model"
