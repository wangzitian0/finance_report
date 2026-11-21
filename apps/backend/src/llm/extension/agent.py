"""The one model entry point of the app: an infra2-sdk agent for each call (#3153).

``complete_text`` and ``stream_text`` are the only functions that call ``create_llm_agent``. The SDK owns the
provider client, the retry of a model error, the redaction of an error and the telemetry. A caller gives the
call site, the role, the content and the decoding.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Literal

from infra2_sdk.runtime import DecodingSpec, create_llm_agent
from pydantic_ai import BinaryContent, ImageUrl
from pydantic_ai.usage import UsageLimits

import src.config

Role = Literal["large", "small", "multimodal"]
Content = str | Sequence[Any]


class CallSite(StrEnum):
    """The name of a model call site. It is the agent name and the telemetry attribute ``infra.llm.call_site``."""

    RECONCILIATION_SEMANTIC_SCORE = "reconciliation.semantic_score"


# A test puts a model object here. Production code never sets it. It is a plain module value, not a context
# variable: a test fixture enters and leaves the block in different contexts.
_model_override: list[Any] = []


@contextmanager
def override_model(model: Any) -> Iterator[None]:
    """Use ``model`` for each call inside the block in place of the model of the role."""
    _model_override.append(model)
    try:
        yield
    finally:
        _model_override.remove(model)


def to_user_content(content: Content) -> str | list[Any]:
    """Return the content of one user message as pydantic-ai parts.

    A string stays a string. A part is a string, a pydantic-ai part, or one of the dicts that the media
    builders make: ``{"type": "text", "text": ...}`` and ``{"type": "image_url", "image_url": {"url": ...}}``.
    """
    if isinstance(content, str):
        return content
    parts: list[Any] = []
    for part in content:
        if not isinstance(part, Mapping):
            parts.append(part)
        elif part.get("type") == "text":
            parts.append(str(part.get("text", "")))
        elif part.get("type") == "image_url":
            parts.append(ImageUrl(url=str(part["image_url"]["url"])))
        else:
            raise ValueError(f"Unsupported content part: {part.get('type')!r}")
    return parts


def _agent(
    call_site: CallSite,
    role: Role,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None,
    extra_body: Mapping[str, Any] | None,
    max_attempts: int,
) -> Any:
    return create_llm_agent(
        src.config.settings.to_llm_settings(),
        role=role,
        model=_model_override[-1] if _model_override else None,
        call_site=call_site.value,
        decoding=decoding,
        usage_limits=usage_limits,
        max_attempts=max_attempts,
        model_settings={"extra_body": dict(extra_body)} if extra_body else None,
    )


async def complete_text(
    call_site: CallSite,
    role: Role,
    content: Content,
    *,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None = None,
    extra_body: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
) -> str:
    """Send one user message and return the text of the reply."""
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts)
    result = await agent.run(to_user_content(content))
    return str(result.output)


async def stream_text(
    call_site: CallSite,
    role: Role,
    content: Content,
    *,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None = None,
    extra_body: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
) -> AsyncIterator[str]:
    """Send one user message and yield the text of the reply piece by piece."""
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts)
    async with agent.run_stream(to_user_content(content)) as stream:
        async for piece in stream.stream_text(delta=True):
            yield piece


__all__ = [
    "BinaryContent",
    "CallSite",
    "Content",
    "Role",
    "complete_text",
    "override_model",
    "stream_text",
    "to_user_content",
]
