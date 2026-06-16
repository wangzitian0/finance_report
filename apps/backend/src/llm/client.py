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

# litellm exception names that represent transient conditions worth retrying.
_RETRYABLE_EXC = frozenset(
    {"RateLimitError", "Timeout", "APIConnectionError", "ServiceUnavailableError", "InternalServerError"}
)


def _is_retryable(exc: Exception) -> bool:
    return type(exc).__name__ in _RETRYABLE_EXC


def _wrap(exc: Exception) -> LLMError:
    return LLMError(f"{type(exc).__name__}: {exc}", retryable=_is_retryable(exc))


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
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise every provider failure
        logger.error("litellm stream failed", model=kwargs.get("model"), error=str(exc), error_type=type(exc).__name__)
        raise _wrap(exc) from exc
    finally:
        logger.info(
            "litellm stream completed",
            model=kwargs.get("model"),
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


class LitellmClient:
    """Scene-keyed ``LLMClient`` resolving config through a ``ConfigSource``."""

    def __init__(self, config_source: ConfigSource, cost_meter: CostMeter | None = None) -> None:
        self._config = config_source
        self._cost = cost_meter

    async def _resolve(self, scene: Scene) -> tuple[ProviderRef, SceneBinding]:
        binding = await self._config.get_binding(scene)
        if binding is None:
            raise LLMConfigError(f"No model bound for scene {scene.value!r}")
        provider = await self._resolve_provider(binding.model_id)
        return provider, binding

    async def _resolve_provider(self, model_id: str) -> ProviderRef:
        # A binding may qualify its model as "provider_id/model"; otherwise fall
        # back to the sole configured provider.
        if "/" in model_id:
            provider = await self._config.get_provider(model_id.split("/", 1)[0])
            if provider is not None:
                return provider
        providers = await self._config.list_providers()
        if not providers:
            raise LLMConfigError("No LLM provider configured")
        if len(providers) > 1 and "/" not in model_id:
            raise LLMConfigError(f"Ambiguous provider for unqualified model {model_id!r}; qualify as provider/model")
        return providers[0]

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
        provider, binding = await self._resolve(scene)
        async for chunk in litellm_stream(
            messages,
            provider=provider,
            model_id=binding.model_id,
            max_tokens=binding.max_tokens,
            reasoning=reasoning or binding.reasoning,
        ):
            yield chunk

    async def complete(
        self, scene: Scene, messages: Sequence[Message], *, reasoning: ReasoningEffort | None = None
    ) -> ChatResult:
        if self._cost is not None:
            await self._cost.check_budget()
        provider, binding = await self._resolve(scene)
        result = await litellm_complete(
            messages,
            provider=provider,
            model_id=binding.model_id,
            max_tokens=binding.max_tokens,
            reasoning=reasoning or binding.reasoning,
        )
        if self._cost is not None:
            await self._cost.record(scene, result.model_id, result.usage, result.cost_usd)
        return result
