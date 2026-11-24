"""A fake model for tests that reach the model through `src.llm.extension.agent` (#3153)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from infra2_sdk.runtime import create_llm_agent as _create_llm_agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

import src.llm.extension.agent as agent_module


class SentToModel(list):
    """The contents that code sent to the fake model, and the decoding of each call.

    ``decodings`` holds the ``DecodingSpec`` that reached the SDK and ``extra_bodies`` the ``extra_body`` of the
    request. ``max_tokens`` is in ``extra_bodies``: the entry point moves it there (Z.AI ignores the other field).
    """

    def __init__(self) -> None:
        super().__init__()
        self.decodings: list[Any] = []
        self.extra_bodies: list[Any] = []


def install_fake_model(monkeypatch: pytest.MonkeyPatch, reply: Callable[[Any], str] | str) -> SentToModel:
    """Make each model call of the test answer with ``reply``, and return what the code sent.

    ``reply`` is a string, or a function of the last user content (a string, or a list of parts). The function
    returns the reply text, or raises: the SDK then re-raises the error as it does for a provider error, and
    product code may turn it into a fallback. So a reply function cannot fail the test with ``assert``: check
    the returned list after the call. A later call in the same test replaces the earlier model.
    """
    sent = SentToModel()

    def answer(content: Any) -> str:
        sent.append(content)
        return reply(content) if callable(reply) else reply

    def respond(messages: Any, _info: Any) -> ModelResponse:
        return ModelResponse(parts=[TextPart(answer(messages[-1].parts[-1].content))])

    async def respond_stream(messages: Any, _info: Any):
        yield answer(messages[-1].parts[-1].content)

    model = FunctionModel(respond, stream_function=respond_stream)

    def create(*args: Any, **kwargs: Any) -> Any:
        sent.decodings.append(kwargs.get("decoding"))
        sent.extra_bodies.append((kwargs.get("model_settings") or {}).get("extra_body"))
        return _create_llm_agent(*args, **{**kwargs, "model": model})

    monkeypatch.setattr(agent_module, "create_llm_agent", create)
    return sent
