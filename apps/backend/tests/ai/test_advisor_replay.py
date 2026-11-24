"""Replay of one recorded advisor call: the system prompt, an earlier turn and the question as the SDK sends them (#3153).

Record again with: `LLM_API_KEY=<key> pytest --record-mode=rewrite tests/ai/test_advisor_replay.py`.
"""

import pytest

from src.advisor.extension.service import AIAdvisorService

CONVERSATION = [
    {"role": "system", "content": "You are a terse assistant. Answer each question with one lowercase word."},
    {"role": "user", "content": "Name a color."},
    {"role": "assistant", "content": "blue"},
    {"role": "user", "content": "Name a fruit."},
]


@pytest.mark.vcr
async def test_the_advisor_streams_the_answer_of_the_large_role_with_its_history(vcr_llm) -> None:
    """The replay matches the request body: the system message, the earlier user and assistant turns, `stream: true`."""
    pieces = [piece async for piece in AIAdvisorService()._stream_model(CONVERSATION)]
    assert len(pieces) >= 1 and "".join(pieces).strip()
