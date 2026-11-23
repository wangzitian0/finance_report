"""The test guard refuses an LLM call while an application transaction is open (#3156)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from src.database import get_session_maker
from src.llm.extension import client as llm_client
from src.llm.extension.agent import CallSite, complete_text, stream_text
from src.llm.extension.semantic_scoring import ai_semantic_score

from infra2_sdk.runtime import DecodingSpec


async def test_llm_completion_inside_open_app_transaction_raises(db_engine) -> None:
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(
            RuntimeError, match="External I/O attempted while an application AsyncSession transaction is open"
        ):
            await llm_client.cassette_completion(
                [{"role": "user", "content": "ping"}],
                role="test",
                provider=MagicMock(),
                model_id="test-model",
            )
        await open_session.rollback()


_GUARD_MESSAGE = "External I/O attempted while an application AsyncSession transaction is open"
_DECODING = DecodingSpec("test.v1", thinking=False, timeout=5.0)


async def test_a_model_call_through_the_entry_point_inside_an_open_app_transaction_raises(db_engine, fake_llm) -> None:
    """#3153: the SDK sends through httpx2 and a fake model sends nothing; the guard sits at the entry point."""
    sent = fake_llm("reply")
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(RuntimeError, match=_GUARD_MESSAGE):
            await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING)
        with pytest.raises(RuntimeError, match=_GUARD_MESSAGE):
            async with stream_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING):
                pass
        await open_session.rollback()
    assert sent == []
    # The same calls pass once no transaction is open.
    assert await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING) == "reply"


async def test_the_semantic_score_does_not_swallow_the_guard_of_the_open_transaction(db_engine, fake_llm) -> None:
    """The caller `matching.score_single` runs this inline in the task that owns the session (review of #3194)."""
    sent = fake_llm('{"similarity_score": 90}')
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(RuntimeError, match=_GUARD_MESSAGE):
            await ai_semantic_score("compare A with B")
        await open_session.rollback()
    assert sent == [] and await ai_semantic_score("compare A with B") == 90
