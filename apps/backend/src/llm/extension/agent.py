"""The one model entry point of the app: an infra2-sdk agent for each call (#3153).

``complete_text`` and ``stream_text`` are the only functions that call ``create_llm_agent``. The SDK owns the
provider client, the retry of a model error, the redaction of an error and the telemetry. A caller gives the
call site, the role, the content and the decoding.

Wire facts that this module fixes (each one was measured against Z.AI on 2026-11-23, see ``tests/llm``):

- The SDK sends ``DecodingSpec.max_tokens`` as ``max_completion_tokens``, and Z.AI ignores that field: a cap of 20
  produced 504 tokens. This module sends the cap as ``max_tokens`` in ``extra_body``, which Z.AI honours.
- ``DecodingSpec.timeout`` is the timeout of the HTTP client for each read. A streamed call keeps the meaning that
  the earlier code had: the longest wait for the next chunk, not a limit on the whole answer.
"""

from __future__ import annotations

import base64
import dataclasses
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
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


def _file_part(part: Mapping[str, Any]) -> BinaryContent:
    """Return a ``{"type": "file", "file": {"file_data": "data:<type>;base64,<data>"}}`` part as binary content."""
    header, _, payload = str(part["file"]["file_data"]).partition(",")
    if not header.startswith("data:") or ";base64" not in header:
        raise ValueError("A file part needs a base64 data URI")
    return BinaryContent(data=base64.b64decode(payload), media_type=header[len("data:") : header.index(";")])


def to_user_content(content: Content) -> str | list[Any]:
    """Return the content of one user message as pydantic-ai parts.

    A string stays a string. A part is a string, a pydantic-ai part, or one of the dicts that the media builders
    make: ``{"type": "text", "text": ...}``, ``{"type": "image_url", "image_url": {"url": ...}}`` and
    ``{"type": "file", "file": {"file_data": "data:application/pdf;base64,..."}}``.
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
        elif part.get("type") == "file":
            parts.append(_file_part(part))
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
    body = dict(extra_body or {})
    if decoding.max_tokens is not None:
        # See the module docstring: Z.AI honours ``max_tokens`` and ignores ``max_completion_tokens``.
        body["max_tokens"] = decoding.max_tokens
        decoding = dataclasses.replace(decoding, max_tokens=None)
    return create_llm_agent(
        src.config.settings.to_llm_settings(),
        role=role,
        call_site=call_site.value,
        decoding=decoding,
        usage_limits=usage_limits,
        max_attempts=max_attempts,
        # A reply without text is an error of the call, not a reason for a second request.
        retries=0,
        model_settings={"extra_body": body} if body else None,
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
    """Send one user message and return the text of the reply.

    The reply is streamed and joined, so ``decoding.timeout`` limits the wait for the next chunk.
    """
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts)
    async with agent.run_stream(to_user_content(content)) as stream:
        return str(await stream.get_output())


@asynccontextmanager
async def stream_text(
    call_site: CallSite,
    role: Role,
    content: Content,
    *,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None = None,
    extra_body: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
) -> AsyncIterator[AsyncIterator[str]]:
    """Send one user message and give the text of the reply piece by piece.

    ``async with stream_text(...) as pieces: async for piece in pieces: ...``. The block closes the stream at
    once, also when the loop stops early or raises. A plain async generator would close it later, in another
    task, and cancel the task of the consumer.
    """
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts)
    async with agent.run_stream(to_user_content(content)) as stream:
        yield stream.stream_text(delta=True, debounce_by=None)


__all__ = ["CallSite", "Content", "Role", "complete_text", "stream_text", "to_user_content"]
