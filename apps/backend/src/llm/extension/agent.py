"""The one model entry point of the app: an infra2-sdk agent for each call (#3153).

``complete_text`` and ``stream_text`` are the only functions that call ``create_llm_agent``. The SDK owns the
provider client, the retry of a model error, the redaction of an error and the telemetry. A caller gives the
call site, the role, the content and the decoding.

Errors: each failure of the model call leaves as one ``ModelCallFailed`` (``kind``, ``summary``), counted once in
``finance.llm.call.failed``. The SDK keeps the class of a provider error and turns every other error into a bare
``RuntimeError`` without the cause, so a caller cannot tell a provider fault from a bug by its class; this module
reads the class where the SDK kept it and marks the rest ``unclassified`` (logged as an ERROR). It does not wrap
the errors of its own arguments, ``CancelledError``, or the local refusals of a test run (a model request that
the session forbids), which must reach the test.

A ``thinking`` key or a ``max_tokens`` key in ``extra_body`` is refused: the SDK replaces the first, and the cap has
one place (``DecodingSpec.max_tokens``). The SDK retries a model error before the first byte of the answer: a
stream that fails after output has started is not retried.

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
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelHTTPError,
    ModelOverloadedError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelRequestTimeout,
    ModelServerError,
    ModelTimeoutError,
    ModelUnavailableError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import UsageLimits

import src.config
from src.llm.base.errors import ModelCallFailed, ModelFailureKind
from src.observability import get_logger, record_llm_call_failure

logger = get_logger(__name__)

Role = Literal["large", "small", "multimodal"]
Content = str | Sequence[Any]


class CallSite(StrEnum):
    """The name of a model call site. It is the agent name and the telemetry attribute ``infra.llm.call_site``."""

    RECONCILIATION_SEMANTIC_SCORE = "reconciliation.semantic_score"
    ADVISOR_CHAT = "advisor.chat"
    EXTRACTION_STATEMENT = "extraction.statement"
    CLASSIFICATION_PROPOSE = "extraction.classification"
    CSV_COLUMN_MAPPING = "extraction.csv_mapping"


def _file_part(part: Mapping[str, Any]) -> BinaryContent:
    """Return a ``{"type": "file", "file": {"file_data": "data:<type>;base64,<data>"}}`` part as binary content."""
    try:
        data_uri = str(part["file"]["file_data"])
    except (KeyError, TypeError) as exc:
        raise ValueError("A file part needs file.file_data") from exc
    header, separator, payload = data_uri.partition(",")
    if not separator or not header.startswith("data:") or ";base64" not in header:
        raise ValueError("A file part needs a base64 data URI")
    media_type = header[len("data:") : header.index(";")]
    data = base64.b64decode(payload, validate=True)
    if not media_type or not data:
        raise ValueError("A file part needs a media type and data")
    return BinaryContent(data=data, media_type=media_type)


def _image_part(part: Mapping[str, Any]) -> ImageUrl:
    try:
        return ImageUrl(url=str(part["image_url"]["url"]))
    except (KeyError, TypeError) as exc:
        raise ValueError("An image part needs image_url.url") from exc


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
            parts.append(_image_part(part))
        elif part.get("type") == "file":
            parts.append(_file_part(part))
        else:
            raise ValueError(f"Unsupported content part: {part.get('type')!r}")
    return parts


def to_message_history(history: Sequence[Mapping[str, Any]]) -> list[ModelMessage]:
    """Return earlier turns, ``{"role": "user" | "assistant", "content": text}``, as pydantic-ai messages.

    The system prompt is not a turn: pass it as ``system``.
    """
    messages: list[ModelMessage] = []
    for turn in history:
        role, text = turn.get("role"), str(turn.get("content", ""))
        if role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        elif role == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=text)]))
        else:
            raise ValueError(f"Unsupported history role: {role!r}")
    return messages


# The error of a replay for a request that has no recording. It is named, not imported: product code imports no recorder.
_RECORDING_REFUSALS = frozenset({"CannotOverwriteExistingCassetteException"})
_SUMMARY_LIMIT = 300
_BAD_REPLY_LABELS = frozenset(
    {"UnexpectedModelBehavior", "ContentFilterError", "OutputTokenLimitExceeded", "IncompleteToolCall"}
)


def model_call_failed(call_site: CallSite, kind: ModelFailureKind, summary: str) -> ModelCallFailed:
    """Count and log one failed model call, and return the error to raise.

    A call site raises the result for a reply that it cannot use (``bad_reply``); the entry point uses it for the
    failures below the SDK. An ``unclassified`` failure is an ERROR: it is an actionable fault. The others are
    expected outcomes of a call to a provider.
    """
    summary = summary[:_SUMMARY_LIMIT]  # a content-filter error carries the body of the answer: bound the text
    record_llm_call_failure(call_site=call_site.value, kind=kind.value)
    log = logger.error if kind is ModelFailureKind.UNCLASSIFIED else logger.warning
    log("Model call failed", call_site=call_site.value, kind=kind.value, summary=summary)
    return ModelCallFailed(kind, summary, call_site=call_site.value)


def _kind_of(exc: Exception) -> ModelFailureKind:
    """Return the failure kind that the class of an SDK error says."""
    if isinstance(exc, UsageLimitExceeded):
        return ModelFailureKind.USAGE_LIMIT
    if isinstance(exc, UserError):
        return ModelFailureKind.NOT_CONFIGURED
    if isinstance(exc, (ModelRateLimitError, ModelQuotaExceededError)):
        return ModelFailureKind.RATE_LIMIT
    if isinstance(exc, (ModelTimeoutError, ModelRequestTimeout)):
        return ModelFailureKind.TIMEOUT
    if isinstance(exc, (ModelServerError, ModelUnavailableError, ModelOverloadedError, ModelConnectionError)):
        return ModelFailureKind.UNAVAILABLE
    if isinstance(exc, ModelHTTPError):
        status = exc.status_code
        if status == 429:
            return ModelFailureKind.RATE_LIMIT
        return ModelFailureKind.UNAVAILABLE if status >= 500 else ModelFailureKind.REJECTED
    if isinstance(exc, ModelAPIError):
        return ModelFailureKind.REJECTED
    if isinstance(exc, UnexpectedModelBehavior):
        # A reply without text, a reply cut by the token limit or the content filter, a tool call that we never ask
        # for: the provider answered, and the answer has no text. ``ContentFilterError``, ``OutputTokenLimitExceeded``
        # and ``IncompleteToolCall`` are subclasses.
        return ModelFailureKind.BAD_REPLY
    # The SDK turns every other error into ``RuntimeError("<Class> (http=none, provider_code=none)")``. The label
    # still names a reply that the provider gave and the SDK could not use.
    if str(exc).partition(" (")[0] in _BAD_REPLY_LABELS:
        return ModelFailureKind.BAD_REPLY
    return ModelFailureKind.UNCLASSIFIED


def _is_local_refusal(exc: Exception) -> bool:
    """Return True for the refusals of a test run, which the SDK itself passes through unchanged."""
    if type(exc).__name__ in _RECORDING_REFUSALS:
        return True
    return isinstance(exc, RuntimeError) and "model requests are not allowed" in str(exc).lower()


def _wrap(call_site: CallSite, exc: Exception) -> Exception:
    if _is_local_refusal(exc):
        return exc
    return model_call_failed(call_site, _kind_of(exc), str(exc))


def _agent(
    call_site: CallSite,
    role: Role,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None,
    extra_body: Mapping[str, Any] | None,
    max_attempts: int,
    model: str | None = None,
    system: str | None = None,
) -> Any:
    body = dict(extra_body or {})
    if "thinking" in body:
        # The SDK replaces a ``thinking`` key of the body: the effort is set by ``DecodingSpec.thinking``.
        raise ValueError("Set thinking with DecodingSpec.thinking, not in extra_body")
    try:
        settings_for_sdk = src.config.settings.to_llm_settings()
    except ValueError as exc:
        # An empty provider, model or base URL: the same fault as a missing key.
        raise model_call_failed(call_site, ModelFailureKind.NOT_CONFIGURED, str(exc)) from exc
    if decoding.max_tokens is not None and str(settings_for_sdk.provider).strip().lower() == "zai":
        # See the module docstring: Z.AI honours ``max_tokens`` and ignores ``max_completion_tokens``. The other
        # providers keep the cap in the SDK field.
        if "max_tokens" in body:
            raise ValueError("Set the cap with DecodingSpec.max_tokens, not in extra_body")
        body["max_tokens"] = decoding.max_tokens
        decoding = dataclasses.replace(decoding, max_tokens=None)
    try:
        return create_llm_agent(
            settings_for_sdk,
            role=role,
            model=model,
            instructions=system,
            call_site=call_site.value,
            decoding=decoding,
            usage_limits=usage_limits,
            max_attempts=max_attempts,
            # A reply without text is an error of the call, not a reason for a second request.
            retries=0,
            model_settings={"extra_body": body} if body else None,
        )
    except ValueError as exc:
        # The SDK refuses a missing key or an unsupported provider when it builds the model.
        raise model_call_failed(call_site, ModelFailureKind.NOT_CONFIGURED, str(exc)) from exc


async def complete_text(
    call_site: CallSite,
    role: Role,
    content: Content,
    *,
    decoding: DecodingSpec,
    usage_limits: UsageLimits | None = None,
    extra_body: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
    model: str | None = None,
    system: str | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Send one user message and return the text of the reply.

    ``system`` is the instruction of the call and ``history`` the earlier turns (``{"role", "content"}``).
    The reply is streamed and joined, so ``decoding.timeout`` limits the wait for the next chunk. A failure of the
    call is a ``ModelCallFailed``.
    """
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts, model, system)
    user_content = to_user_content(content)  # an error of our own argument is not a failure of the call
    earlier = to_message_history(history)
    try:
        async with agent.run_stream(user_content, message_history=earlier or None) as stream:
            return str(await stream.get_output())
    except Exception as exc:
        raise _wrap(call_site, exc) from exc


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
    model: str | None = None,
    system: str | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> AsyncIterator[AsyncIterator[str]]:
    """Send one user message and give the text of the reply piece by piece.

    ``system`` and ``history`` are as in ``complete_text``.
    ``async with stream_text(...) as pieces: async for piece in pieces: ...``. The block closes the stream at
    once, also when the loop stops early or raises. A plain async generator would close it later, in another
    task, and cancel the task of the consumer. The iterator refuses use after the block: it would give a reply
    that stops where the buffer ended. A failure of the call, while the stream opens or while the consumer reads
    it, is a ``ModelCallFailed``; an error of the consumer's own code in the block passes unchanged.
    """
    agent = _agent(call_site, role, decoding, usage_limits, extra_body, max_attempts, model, system)
    earlier = to_message_history(history)
    stream_cm = agent.run_stream(to_user_content(content), message_history=earlier or None)
    try:
        stream = await stream_cm.__aenter__()
    except Exception as exc:
        raise _wrap(call_site, exc) from exc
    closed = False
    inner = stream.stream_text(delta=True, debounce_by=None)

    async def pieces() -> AsyncIterator[str]:
        if closed:
            raise RuntimeError("The iterator of stream_text was used after its block closed")
        try:
            async for piece in inner:
                yield piece
        except Exception as exc:
            raise _wrap(call_site, exc) from exc

    try:
        yield pieces()
    finally:
        closed = True
        await inner.aclose()
        await stream_cm.__aexit__(None, None, None)


__all__ = [
    "CallSite",
    "Content",
    "Role",
    "complete_text",
    "model_call_failed",
    "stream_text",
    "to_message_history",
    "to_user_content",
]
