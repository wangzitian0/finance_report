"""The test guard refuses an LLM call while an application transaction is open (#3156)."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.database import get_session_maker
from src.llm.extension import client as llm_client


async def test_llm_completion_inside_open_app_transaction_raises(db_engine) -> None:
    provider_call = AsyncMock(return_value={})
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(
            RuntimeError, match="External I/O attempted while an application AsyncSession transaction is open"
        ):
            await llm_client.cassette_completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                provider_call=provider_call,
            )
        await open_session.rollback()
    provider_call.assert_not_awaited()
