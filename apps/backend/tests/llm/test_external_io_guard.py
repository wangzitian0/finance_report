"""The test guard refuses an LLM call while an application transaction is open (#3156, #3153).

The guard raises ``UnexpectedExternalIO``, a ``BaseException``: no ``except Exception`` of product code can turn it into
a fallback. It also records the violation, and the fixture that installs it fails the test at teardown when the test
does not acknowledge it, so a catch of ``BaseException`` does not hide it either.
"""

from unittest.mock import MagicMock

import pytest
from infra2_sdk.runtime import DecodingSpec
from sqlalchemy import text

from src.database import get_session_maker
from src.llm.extension import client as llm_client
from src.llm.extension.agent import CallSite, complete_text, stream_text
from src.llm.extension.semantic_scoring import ai_semantic_score
from tests._support.guards import (
    UnexpectedExternalIO,
    acknowledge_violations,
    fail_on_unacknowledged_violations,
    record_violation,
)

_GUARD_MESSAGE = "External I/O attempted while an application AsyncSession transaction is open"
_DECODING = DecodingSpec("test.v1", thinking=False, timeout=5.0)


def test_the_guard_error_is_not_an_exception() -> None:
    """`except Exception` does not catch it, as it does not catch `KeyboardInterrupt` or `pytest.fail`."""
    assert issubclass(UnexpectedExternalIO, BaseException) and not issubclass(UnexpectedExternalIO, Exception)


def test_the_teardown_check_fails_a_test_that_went_on_after_a_refusal() -> None:
    fail_on_unacknowledged_violations()  # nothing recorded: no failure
    record_violation("LLM call")
    with pytest.raises(pytest.fail.Exception, match="the test went on"):
        fail_on_unacknowledged_violations()
    fail_on_unacknowledged_violations()  # the failure took the record


async def test_llm_completion_inside_open_app_transaction_raises(db_engine) -> None:
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(UnexpectedExternalIO, match=_GUARD_MESSAGE):
            await llm_client.cassette_completion(
                [{"role": "user", "content": "ping"}],
                role="test",
                provider=MagicMock(),
                model_id="test-model",
            )
        await open_session.rollback()
    assert len(acknowledge_violations()) == 1


async def test_a_model_call_through_the_entry_point_inside_an_open_app_transaction_raises(db_engine, fake_llm) -> None:
    """#3153: the SDK sends through httpx2 and a fake model sends nothing; the guard sits at the entry point."""
    sent = fake_llm("reply")
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(UnexpectedExternalIO, match=_GUARD_MESSAGE):
            await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING)
        with pytest.raises(UnexpectedExternalIO, match=_GUARD_MESSAGE):
            async with stream_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING):
                pass
        await open_session.rollback()
    assert sent == [] and len(acknowledge_violations()) == 2
    # The same calls pass once no transaction is open.
    assert await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING) == "reply"


async def test_the_semantic_score_does_not_swallow_the_guard_of_the_open_transaction(db_engine, fake_llm) -> None:
    """The caller `matching.score_single` runs this inline in the task that owns the session (review of #3194)."""
    sent = fake_llm('{"similarity_score": 90}')
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(UnexpectedExternalIO, match=_GUARD_MESSAGE):
            await ai_semantic_score("compare A with B")
        await open_session.rollback()
    assert sent == [] and len(acknowledge_violations()) == 1 and await ai_semantic_score("compare A with B") == 90


async def test_a_broad_catch_of_product_code_does_not_hide_a_violation(db_engine, fake_llm) -> None:
    """A violation that something swallows (`except BaseException`) is still recorded for the teardown of the fixture."""
    fake_llm("reply")
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        try:
            await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING)
        except BaseException:  # noqa: BLE001  (this is the swallow that the recording must survive)
            pass
        await open_session.rollback()
    # The teardown of the guard fixture would fail the test here; the test takes the record itself.
    assert len(acknowledge_violations()) == 1


async def test_a_model_call_in_a_child_task_of_the_transaction_owner_is_refused(db_engine, fake_llm) -> None:
    """Review of #3194, round 4: `_resolve_semantic_scores` calls the model in TaskGroup children of the owner task."""
    from src.reconciliation.extension.matching import _resolve_semantic_scores

    sent = fake_llm('{"similarity_score": 90}')
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        with pytest.raises(UnexpectedExternalIO, match=_GUARD_MESSAGE):
            await _resolve_semantic_scores(["compare A with B", "compare C with D"], max_concurrency=2)
        await open_session.rollback()
    assert sent == [] and len(acknowledge_violations()) >= 1
    # Once no transaction is open, the same calls reach the model.
    assert await _resolve_semantic_scores(["compare A with B"], max_concurrency=2) == {"compare A with B": 90}


async def test_a_model_call_in_a_task_that_does_not_descend_from_the_owner_is_not_refused(db_engine, fake_llm) -> None:
    """The guard stays task-scoped: a task that began before the transaction, or is unrelated, is not the owner's."""
    import asyncio

    fake_llm("reply")

    async def call() -> str:
        return await complete_text(CallSite.RECONCILIATION_SEMANTIC_SCORE, "small", "ping", decoding=_DECODING)

    unrelated = asyncio.ensure_future(call())  # created before the transaction opens: its context has no owner
    await asyncio.sleep(0)
    async with get_session_maker()() as open_session:
        await open_session.execute(text("SELECT 1"))
        assert await unrelated == "reply"
        await open_session.rollback()
    assert acknowledge_violations() == []
