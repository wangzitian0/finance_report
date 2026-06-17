"""litellm-backed transport + scene client (EPIC-023 EPIC A).

``litellm_stream`` / ``litellm_complete`` are the single chokepoint that talks to
litellm; everything provider-specific is resolved by :mod:`src.llm.routing`, and
``drop_params=True`` lets litellm silently drop fields a given model rejects
(e.g. Z.AI/GLM rejecting ``seed`` — the quirk that previously needed bespoke
handling). :class:`LitellmClient` is the scene-keyed surface implementing the
``LLMClient`` protocol on top of a ``ConfigSource``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Any

import litellm

from src.llm.common import (
    ChatResult,
    ConfigSource,
    LLMConfigError,
    LLMError,
    Message,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
    Usage,
)
from src.llm.common.protocols import CostMeter
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
    """Stream text delta chunks for one completion via litellm."""
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


async def litellm_complete(
    messages: Sequence[Message],
    *,
    provider: ProviderRef,
    model_id: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    reasoning: ReasoningEffort | None = None,
    extra_body: dict[str, Any] | None = None,
) -> ChatResult:
    """Non-streaming completion returning text + usage + cost."""
    kwargs = _base_kwargs(
        provider=provider,
        model_id=model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning=reasoning,
        seed=None,
        extra_body=extra_body,
    )
    try:
        response = await litellm.acompletion(**kwargs)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _wrap(exc) from exc

    choices = getattr(response, "choices", None) or []
    text = ""
    if choices:
        msg = getattr(choices[0], "message", None)
        text = (getattr(msg, "content", None) or "") if msg is not None else ""

    raw_usage = getattr(response, "usage", None)
    usage = Usage(
        prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
    )
    cost = _safe_cost(response)
    return ChatResult(text=text, model_id=kwargs["model"], usage=usage, cost_usd=cost)


def _safe_cost(response: Any) -> Decimal | None:
    """Best-effort USD cost from litellm; never let cost telemetry break a call."""
    try:
        value = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 - cost is telemetry, not correctness
        return None
    if value is None:
        return None
    return Decimal(str(value))


def estimate_cost_usd(model: str, messages: Sequence[Message], completion_text: str) -> Decimal | None:
    """Best-effort USD cost for a streamed call from prompt + completion text.

    Streaming yields no usage object, so the budget meter would never accumulate on
    the live path. litellm's pricing table maps many models (it returns ``None`` /
    raises for ones it doesn't know — e.g. a self-hosted vLLM — in which case spend
    simply isn't counted for that model). Never raises."""
    try:
        value = litellm.completion_cost(model=model, messages=list(messages), completion=completion_text)
    except Exception:  # noqa: BLE001 - cost is telemetry, not correctness
        return None
    if not value:
        return None
    return Decimal(str(value))


async def resolve_provider_and_model(config_source: ConfigSource, model_id: str) -> tuple[ProviderRef, str]:
    """Resolve ``model_id`` against ``config_source`` to ``(provider, bare_model)``.

    A binding may qualify its model as ``provider_id/model`` (DB-backed config
    always does, so the exact provider is selected even with several configured).
    If the leading segment is a known provider id, it is used and stripped — for
    any provider count. Otherwise: with a single provider the whole ``model_id``
    is the model (it may contain slashes — OpenRouter's ``vendor/model``); with
    several providers an unqualified or unknown-provider id is a config error,
    never a silent fallback to the wrong credentials.

    Shared by :class:`LitellmClient` and the ``ai_streaming`` transport so the
    per-user binding's provider qualifier is honoured everywhere (a user with
    several providers must not fail closed on a qualified binding).
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


class LitellmClient:
    """Scene-keyed ``LLMClient`` resolving config through a ``ConfigSource``."""

    def __init__(self, config_source: ConfigSource, cost_meter: CostMeter | None = None) -> None:
        self._config = config_source
        self._cost = cost_meter

    async def _resolve(self, scene: Scene) -> tuple[ProviderRef, str, SceneBinding]:
        binding = await self._config.get_binding(scene)
        if binding is None:
            raise LLMConfigError(f"No model bound for scene {scene.value!r}")
        provider, model = await self._resolve_provider(binding.model_id)
        return provider, model, binding

    async def _resolve_provider(self, model_id: str) -> tuple[ProviderRef, str]:
        return await resolve_provider_and_model(self._config, model_id)

    def stream(
        self, scene: Scene, messages: Sequence[Message], *, reasoning: ReasoningEffort | None = None
    ) -> AsyncIterator[str]:
        return self._stream(scene, messages, reasoning=reasoning)

    def stream_json(
        self, scene: Scene, messages: Sequence[Message], *, reasoning: ReasoningEffort | None = None
    ) -> AsyncIterator[str]:
        # JSON mode is prompt-driven (no response_format) — same rationale as the
        # legacy path: several providers reject it with multimodal inputs.
        return self._stream(scene, messages, reasoning=reasoning)

    async def _stream(
        self, scene: Scene, messages: Sequence[Message], *, reasoning: ReasoningEffort | None
    ) -> AsyncIterator[str]:
        if self._cost is not None:
            await self._cost.check_budget()
        provider, model, binding = await self._resolve(scene)
        async for chunk in litellm_stream(
            messages,
            provider=provider,
            model_id=model,
            max_tokens=binding.max_tokens,
            reasoning=reasoning or binding.reasoning,
        ):
            yield chunk

    async def complete(
        self, scene: Scene, messages: Sequence[Message], *, reasoning: ReasoningEffort | None = None
    ) -> ChatResult:
        if self._cost is not None:
            await self._cost.check_budget()
        provider, model, binding = await self._resolve(scene)
        result = await litellm_complete(
            messages,
            provider=provider,
            model_id=model,
            max_tokens=binding.max_tokens,
            reasoning=reasoning or binding.reasoning,
        )
        if self._cost is not None:
            await self._cost.record(scene, result.model_id, result.usage, result.cost_usd)
        return result
