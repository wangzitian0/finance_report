"""A fake model for tests that reach the model through `src.llm.extension.agent` (#3153)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from infra2_sdk.llm import create_llm_agent as _create_llm_agent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

import src.llm.extension.agent as agent_module


class SentToModel(list):
    """The contents that code sent to the fake model, and the decoding of each call.

    ``decodings`` holds the ``DecodingSpec`` that reached the SDK, ``extra_bodies`` the ``extra_body`` of the
    request and ``models`` the model name that the caller asked for (None: the model of the role). For ``zai``,
    ``max_tokens`` is moved into ``extra_bodies`` so ``ZaiModel`` does not emit ``max_completion_tokens``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.decodings: list[Any] = []
        self.extra_bodies: list[Any] = []
        self.max_attempts: list[Any] = []
        self.requests: list[list[Any]] = []  # the pydantic-ai messages of each call: history and instructions
        self.models: list[Any] = []
        self.roles: list[Any] = []


def install_fake_model(monkeypatch: pytest.MonkeyPatch, reply: Callable[[Any], str] | str) -> SentToModel:
    """Make each model call of the test answer with ``reply``, and return what the code sent.

    ``reply`` is a string, or a function of the last user content (a string, or a list of parts). The function
    returns the reply text, or raises: the SDK then re-raises the error as it does for a provider error, and
    product code may turn it into a fallback. So a reply function cannot fail the test with ``assert``: check
    the returned list after the call. A later call in the same test replaces the earlier model.
    """
    sent = SentToModel()

    def answer(content: Any) -> Any:
        sent.append(content)
        return reply(content) if callable(reply) else reply

    def respond(messages: Any, _info: Any) -> ModelResponse:
        sent.requests.append(list(messages))
        result = answer(messages[-1].parts[-1].content)
        return ModelResponse(parts=[TextPart(result if isinstance(result, str) else "".join(map(str, result)))])

    async def respond_stream(messages: Any, _info: Any):
        sent.requests.append(list(messages))
        result = answer(messages[-1].parts[-1].content)
        # A list is a reply in several chunks; an exception in the list is raised at its place (a failure after the
        # first chunk), and each chunk gives the event loop a turn so that two tasks can interleave.
        for chunk in [result] if isinstance(result, (str, BaseException)) else result:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk
            await asyncio.sleep(0)

    model = FunctionModel(respond, stream_function=respond_stream)

    def create(*args: Any, **kwargs: Any) -> Any:
        sent.decodings.append(kwargs.get("decoding"))
        sent.extra_bodies.append((kwargs.get("model_settings") or {}).get("extra_body"))
        sent.max_attempts.append(kwargs.get("max_attempts"))
        sent.models.append(kwargs.get("model"))
        sent.roles.append(kwargs.get("role"))
        return _create_llm_agent(*args, **{**kwargs, "model": model})

    monkeypatch.setattr(agent_module, "create_llm_agent", create)
    return sent
