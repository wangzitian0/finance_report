"""AI provider streaming utilities (litellm transport).

EPIC-023 PR3: the transport is litellm (via :mod:`src.llm.client`), not raw
httpx. These functions keep their signatures for the existing call sites
(extraction, the AI advisor, reconciliation scoring), but provider selection now
comes from the layered config (DB providers first, env fallback) and litellm
handles provider routing + dropping model-rejected params (e.g. Z.AI/GLM
``seed``). When a caller passes an explicit ``api_key``/``base_url`` those win
(back-compat / tests); otherwise the configured default provider is resolved.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from src.config import settings
from src.llm.client import estimate_cost_usd, litellm_stream, resolve_provider_and_model
from src.llm.common import LLMBudgetExceeded, LLMConfigError, LLMError, ProviderRef
from src.llm.env_config import _protocol_for
from src.llm.factory import get_budget_meter, get_config_source
from src.llm.routing import build_call
from src.logger import get_logger

logger = get_logger(__name__)


class AIStreamError(Exception):
    """Raised when AI provider streaming fails."""

    def __init__(self, message: str, retryable: bool = False):
        """Initialize AI provider streaming error.

        ``retryable`` mirrors litellm's verdict on the underlying provider error
        (HTTP 429 / 5xx / timeout → retryable), preserving the prior contract.
        """
        super().__init__(message)
        self.retryable = retryable


async def _resolve_provider(api_key: str | None, base_url: str | None, user_id: UUID | None = None) -> ProviderRef:
    """Resolve the provider for a transport call.

    Explicit ``api_key`` wins (its protocol is taken from ``AI_PROVIDER``);
    otherwise resolve the configured default provider for ``user_id`` — the user's
    own provider if they configured one, else the deployment default, else the env
    fallback (see :func:`get_config_source`). ``user_id=None`` keeps the original
    deployment/env-only behaviour for background/user-less callers.
    """
    if api_key:
        return ProviderRef(
            id="explicit",
            label=settings.ai_provider,
            protocol=_protocol_for(settings.ai_provider),
            api_key=api_key,
            api_base=base_url or getattr(settings, "ai_base_url", None) or None,
        )
    providers = await get_config_source(user_id).list_providers()
    if not providers:
        raise AIStreamError("AI provider not configured", retryable=False)
    if len(providers) > 1:
        # This scene-less path can't disambiguate; fail closed rather than route a
        # prompt to a nondeterministically-chosen provider. Multi-provider use must
        # go through the scene-keyed client (provider_id/model bindings).
        raise AIStreamError(
            "Multiple AI providers configured; this path needs exactly one default provider", retryable=False
        )
    return providers[0]


async def _stream_ai_base(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    user_id: UUID | None = None,
    timeout: float,
    connect_timeout: float = 10.0,
    max_tokens: int | None = None,
    temperature: float | None = None,
    do_sample: bool | None = None,
    seed: int | None = None,
    thinking: dict[str, Any] | None = None,
    response_format: dict[str, str] | None = None,
    mode_label: str = "streaming",
) -> AsyncIterator[str]:
    """Stream delta chunks via litellm.

    ``do_sample``/``thinking`` are Z.AI/GLM-specific knobs forwarded through
    ``extra_body``; ``seed`` is a native param litellm drops for models that
    reject it. ``response_format`` and ``connect_timeout`` are accepted for
    signature compatibility but unused — JSON mode stays prompt-driven and
    litellm owns the transport. ``user_id`` scopes provider resolution to that
    user's configured provider (else deployment default, else env).
    """
    if api_key is None and user_id is not None:
        # Per-user path: honour a binding's ``provider_id/model`` qualifier so a
        # user with several providers resolves the exact one (the scene-less
        # ``_resolve_provider`` fails closed on >1). ``model`` becomes the bare model.
        try:
            provider, model = await resolve_provider_and_model(get_config_source(user_id), model)
        except LLMConfigError as exc:
            raise AIStreamError(str(exc), retryable=False) from exc
    else:
        provider = await _resolve_provider(api_key, base_url, user_id)

    # Enforce the daily spend ceiling on the live path (the scene-less transport
    # never went through LitellmClient's meter). Best-effort: blocks once today's
    # recorded spend reaches AI_DAILY_LIMIT_USD.
    meter = get_budget_meter()
    try:
        await meter.check_budget()
    except LLMBudgetExceeded as exc:
        raise AIStreamError(str(exc), retryable=False) from exc

    extra_body: dict[str, Any] = {}
    if do_sample is not None:
        extra_body["do_sample"] = do_sample
    if thinking is not None:
        extra_body["thinking"] = thinking

    collected: list[str] = []
    try:
        async for content in litellm_stream(
            messages,
            provider=provider,
            model_id=model,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            extra_body=extra_body or None,
            timeout=timeout,
        ):
            collected.append(content)
            yield content
    except LLMError as exc:
        logger.error(
            "AI provider streaming failed",
            provider=provider.label,  # resolved provider (DB or env), not the env AI_PROVIDER
            provider_id=provider.id,
            model=model,
            mode=mode_label,
            error=str(exc),
            retryable=exc.retryable,
        )
        raise AIStreamError(str(exc), retryable=exc.retryable) from exc
    else:
        # Record best-effort spend so the daily ceiling actually accumulates.
        # Cost/telemetry must never break a completed stream.
        try:
            cost = estimate_cost_usd(build_call(provider, model).model, messages, "".join(collected))
            await meter.record_cost(model, cost, scene=mode_label)
        except Exception:  # noqa: BLE001 - spend telemetry is not correctness
            logger.debug("llm spend recording skipped", exc_info=True)


async def stream_ai_json(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    user_id: UUID | None = None,
    timeout: float = 180.0,
    max_tokens: int | None = None,
    temperature: float | None = None,
    do_sample: bool | None = None,
    seed: int | None = None,
    thinking: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Stream chat completions for JSON extraction (prompt-driven JSON, no response_format)."""
    async for chunk in _stream_ai_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        user_id=user_id,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
        do_sample=do_sample,
        seed=seed,
        thinking=thinking,
        mode_label="JSON extraction",
    ):
        yield chunk


async def stream_ai_chat(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    user_id: UUID | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Stream chat completions without JSON mode (plain text)."""
    async for chunk in _stream_ai_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        user_id=user_id,
        timeout=timeout,
        mode_label="chat mode",
    ):
        yield chunk


async def accumulate_stream(stream: AsyncIterator[str]) -> str:
    """Accumulate all chunks from a stream into a single string."""
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)
