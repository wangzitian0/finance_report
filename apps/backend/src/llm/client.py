"""litellm-backed transport (EPIC-023 EPIC A).

``litellm_stream`` is the single chokepoint that talks to litellm; everything
provider-specific is resolved by :mod:`src.llm.routing`, and ``drop_params=True``
lets litellm silently drop fields a given model rejects (e.g. Z.AI/GLM rejecting
``seed`` — the quirk that previously needed bespoke handling). Provider/model
selection is shared via :func:`resolve_provider_and_model`; spend is priced via
:func:`cost_from_usage`. The service-facing entry point is ``services.ai_streaming``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Any

import litellm

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
    usage_sink: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Stream text delta chunks for one completion via litellm.

    When ``usage_sink`` is given, the final chunk's token usage is written to it
    (``prompt_tokens`` / ``completion_tokens`` / ``model``) so the caller can record
    real spend — streaming otherwise exposes no usage object."""
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
    if usage_sink is not None:
        # Ask litellm to emit a final usage-bearing chunk (OpenAI stream_options).
        kwargs["stream_options"] = {"include_usage": True}
    if timeout is not None:
        kwargs["timeout"] = timeout

    start = time.perf_counter()
    chars = 0
    success = False
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            raw_usage = getattr(chunk, "usage", None)
            if raw_usage is not None and usage_sink is not None:
                usage_sink["prompt_tokens"] = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
                usage_sink["completion_tokens"] = int(getattr(raw_usage, "completion_tokens", 0) or 0)
                usage_sink["model"] = kwargs.get("model")
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


def cost_from_usage(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    """USD cost from real token usage via litellm's price table, or ``None``.

    Returns ``None`` (logging at debug) for models litellm doesn't price — notably
    Z.AI/GLM — so the budget simply isn't metered for them rather than guessing.
    Add a per-model price to enforce the ceiling for those providers. Never raises."""
    if not prompt_tokens and not completion_tokens:
        return None
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
    except Exception:  # noqa: BLE001 - unpriced model -> not metered (telemetry, not correctness)
        logger.debug("no litellm price for model; spend not metered", model=model)
        return None
    # Convert each component to Decimal before summing (litellm returns floats).
    total = Decimal(str(prompt_cost or 0)) + Decimal(str(completion_cost or 0))
    return total if total else None


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
