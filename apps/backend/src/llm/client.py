"""litellm-backed transport (EPIC-023 EPIC A).

``litellm_stream`` is the single chokepoint that talks to litellm; everything
provider-specific is resolved by :mod:`src.llm.routing`, and ``drop_params=True``
lets litellm silently drop fields a given model rejects (e.g. Z.AI/GLM rejecting
``seed`` — the quirk that previously needed bespoke handling). Provider/model
selection is shared via :func:`resolve_provider_and_model`; the service-facing
entry point is ``services.ai_streaming`` (which counts request/token usage).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import litellm

from src.llm.cassette import (
    CassetteRecorder,
    CassetteTag,
)
from src.llm.common import (
    ConfigSource,
    LLMConfigError,
    LLMError,
    Message,
    ProviderRef,
    ReasoningEffort,
)
from src.llm.routing import build_call
from src.logger import get_logger

logger = get_logger(__name__)


def _harden_litellm_logging() -> None:
    """Stop litellm from printing request bodies (which carry the provider api_key
    + prompt) to stdout. Best-effort + guarded so a renamed attribute in a future
    litellm version can never break import."""
    for attr, value in (("turn_off_message_logging", True), ("set_verbose", False), ("suppress_debug_info", True)):
        try:
            setattr(litellm, attr, value)
        except Exception:  # noqa: BLE001 - logging hardening is never fatal
            pass


_harden_litellm_logging()

# litellm exception names that represent transient conditions worth retrying.
_RETRYABLE_EXC = frozenset(
    {"RateLimitError", "Timeout", "APIConnectionError", "ServiceUnavailableError", "InternalServerError"}
)


def _is_retryable(exc: Exception) -> bool:
    return type(exc).__name__ in _RETRYABLE_EXC


def _wrap(exc: Exception) -> LLMError:
    # Surface only the exception class in the raised message — upstream provider
    # errors can embed request context (endpoints, headers, payload fragments).
    # The full detail is logged server-side (with the logger) by the caller.
    return LLMError(f"LLM provider call failed ({type(exc).__name__})", retryable=_is_retryable(exc))


def _base_kwargs(
    *,
    provider: ProviderRef,
    model_id: str,
    messages: Sequence[Message],
    max_tokens: int | None,
    temperature: float | None,
    reasoning: ReasoningEffort | None,
    seed: int | None,
    extra_body: dict[str, Any] | None,
) -> dict[str, Any]:
    call = build_call(provider, model_id)
    kwargs = call.kwargs()
    kwargs["messages"] = list(messages)
    # Let litellm drop params a given model rejects instead of erroring (the
    # Z.AI/GLM seed/response_format class of HTTP 400s).
    kwargs["drop_params"] = True
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning is not None and reasoning is not ReasoningEffort.NONE:
        kwargs["reasoning_effort"] = reasoning.value
    if seed is not None:
        # Native param so drop_params can strip it for models that reject seed.
        kwargs["seed"] = seed
    if extra_body:
        kwargs["extra_body"] = dict(extra_body)
    return kwargs


async def litellm_stream(
    messages: Sequence[Message],
    *,
    provider: ProviderRef,
    model_id: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    reasoning: ReasoningEffort | None = None,
    seed: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """Stream text delta chunks for one completion via litellm.

    Note: we deliberately do NOT request ``stream_options={"include_usage": True}`` —
    Z.AI/GLM rejects unknown params with HTTP 400 and litellm won't drop it (it's a
    supported openai-compatible field). Token usage is estimated by the caller from
    text instead (see ``services.ai_streaming``)."""
    kwargs = _base_kwargs(
        provider=provider,
        model_id=model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning=reasoning,
        seed=seed,
        extra_body=extra_body,
    )
    kwargs["stream"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout

    start = time.perf_counter()
    chars = 0
    success = False
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                chars += len(content)
                yield content
        success = True
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise every provider failure
        logger.error("litellm stream failed", model=kwargs.get("model"), error=str(exc), error_type=type(exc).__name__)
        raise _wrap(exc) from exc
    finally:
        # success=False covers both provider errors and a consumer that abandons
        # the generator early — dashboards can filter completed-OK from the rest.
        logger.info(
            "litellm stream finished",
            model=kwargs.get("model"),
            success=success,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            total_chars=chars,
        )


async def cassette_completion(
    messages: Sequence[Message],
    *,
    role: str,
    provider: ProviderRef,
    model_id: str,
    recorder: CassetteRecorder | None = None,
    tag: CassetteTag = CassetteTag.FLOW_ONLY,
    validator: Any = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    reasoning: ReasoningEffort | None = None,
    seed: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Cassette-aware non-streaming completion (EPIC-023 AC23.5).

    The chokepoint that gives CI deterministic LLM responses. In ``replay`` mode
    it returns the committed cassette response with **zero network and no API
    key**; a miss is a hard failure (``CassetteMiss``), never a network fallback.
    In ``record`` mode it performs the real litellm call and freezes the response
    (validated against ground-truth for a ``correctness`` cassette). In ``off``
    mode it is a plain live call.

    The fingerprint keys on ``role`` (the semantic modality role / scene), the
    messages, and the decode params — NOT ``model_id`` — so swapping models does
    not invalidate cassettes; ``model_id`` is used only by the live call.
    """
    recorder = recorder or CassetteRecorder()
    # Decode params that actually change the bytes the provider emits — the model
    # id is intentionally excluded (model-id-agnostic keying).
    decode_params: dict[str, Any] = {}
    if max_tokens is not None:
        decode_params["max_tokens"] = max_tokens
    if temperature is not None:
        decode_params["temperature"] = temperature
    if reasoning is not None and reasoning is not ReasoningEffort.NONE:
        decode_params["reasoning_effort"] = reasoning.value
    if seed is not None:
        decode_params["seed"] = seed
    if extra_body:
        decode_params["extra_body"] = dict(extra_body)

    async def live_call() -> dict[str, Any]:
        kwargs = _base_kwargs(
            provider=provider,
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning=reasoning,
            seed=seed,
            extra_body=extra_body,
        )
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = await litellm.acompletion(**kwargs)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise every provider failure
            logger.error("litellm completion failed", model=kwargs.get("model"), error_type=type(exc).__name__)
            raise _wrap(exc) from exc
        # litellm responses expose ``model_dump`` (pydantic) or are dict-like; fall
        # back to a minimal text projection so any provider's shape is freezable.
        if hasattr(response, "model_dump"):
            return dict(response.model_dump())
        if isinstance(response, dict):
            return dict(response)
        return {"text": str(response)}

    return await recorder.call(
        live_call,
        role=role,
        messages=messages,
        decode_params=decode_params,
        tag=tag,
        validator=validator,
    )


async def resolve_provider_and_model(config_source: ConfigSource, model_id: str) -> tuple[ProviderRef, str]:
    """Resolve ``model_id`` against ``config_source`` to ``(provider, bare_model)``.

    A binding may qualify its model as ``provider_id/model`` (DB-backed config
    always does, so the exact provider is selected even with several configured).
    If the leading segment is a known provider id, it is used and stripped — for
    any provider count. Otherwise: with a single provider the whole ``model_id``
    is the model (it may contain slashes — OpenRouter's ``vendor/model``); with
    several providers an unqualified or unknown-provider id is a config error,
    never a silent fallback to the wrong credentials.

    Used by the ``ai_streaming`` transport so the per-user binding's provider
    qualifier is honoured everywhere (a user with several providers must not fail
    closed on a qualified binding).
    """
    providers = await config_source.list_providers()
    if not providers:
        raise LLMConfigError("No LLM provider configured")
    if "/" in model_id:
        provider_id, _, model = model_id.partition("/")
        provider = await config_source.get_provider(provider_id)
        if provider is not None:
            return provider, model
        if len(providers) == 1:
            return providers[0], model_id
        raise LLMConfigError(f"Unknown provider id {provider_id!r} in model {model_id!r}")
    if len(providers) == 1:
        return providers[0], model_id
    raise LLMConfigError(f"Ambiguous provider for unqualified model {model_id!r}; qualify as provider_id/model")
