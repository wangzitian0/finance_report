"""AI provider streaming utilities (litellm transport).

EPIC-023 PR3: the transport is litellm (via :mod:`src.llm.extension.client`), not raw
httpx. These functions keep their signatures for the existing call sites
(extraction, the AI advisor, reconciliation scoring), but provider selection now
comes from the layered config (DB providers first, env fallback) and litellm
handles provider routing + dropping model-rejected params (e.g. Z.AI/GLM
``seed``). When a caller passes an explicit ``api_key``/``base_url`` those win
(back-compat / tests); otherwise the configured default provider is resolved.
"""

import time
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from src.config import settings
from src.llm.base import (
    DecodeParams,
    LLMConfigError,
    LLMError,
    Message,
    ProviderRef,
    ReasoningEffort,
    estimate_tokens,
    estimate_tokens_from_chars,
)
from src.llm.extension.env_config import protocol_for
from src.llm.extension.factory import get_config_source, get_usage_meter
from src.observability import get_logger, record_ai_provider_call

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


def _estimate_prompt_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate prompt tokens from the *text* of the messages only.

    Multimodal messages carry base64 image payloads (a ``content`` list with
    ``image_url`` parts); counting those as text would be meaningless, so only
    string content and ``text`` parts are estimated. Image tokens are out of scope
    for this usage stat."""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str):
                        total += estimate_tokens(text)
    return total


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
            protocol=protocol_for(settings.ai_provider),
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
    messages: Sequence[Message],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    user_id: UUID | None = None,
    timeout: float,
    decode: DecodeParams = DecodeParams(),
    mode_label: str = "streaming",
) -> AsyncIterator[str]:
    """Stream delta chunks via litellm.

    ``DecodeParams.extra_body`` carries Z.AI/GLM-specific knobs; ``seed`` is a
    native param litellm drops for models that reject it. JSON mode stays
    prompt-driven and litellm owns the transport. ``user_id`` scopes provider
    resolution to that user's configured provider (else deployment default,
    else env).
    """
    # Deferred: src.llm.extension.client imports litellm at module level, and
    # importing this module must not (the no-litellm-at-root invariant in
    # src/llm/__init__.py extends to this module too, since it is imported
    # eagerly from llm.extension).
    from src.llm.extension.client import litellm_stream, resolve_provider_and_model

    resolved_lazily: list[ProviderRef] = []

    async def _lazy_provider() -> ProviderRef:
        prov = await _resolve_provider(api_key, base_url, user_id)
        resolved_lazily.append(prov)
        return prov

    provider: ProviderRef | None = None
    if api_key is None and user_id is not None:
        # Per-user path: honour a binding's ``provider_id/model`` qualifier so a
        # user with several providers resolves the exact one (the scene-less
        # ``_resolve_provider`` fails closed on >1). ``model`` becomes the bare model.
        try:
            provider, model = await resolve_provider_and_model(get_config_source(user_id), model)
        except LLMConfigError as exc:
            raise AIStreamError(str(exc), retryable=False) from exc
    # All other paths resolve LAZILY inside the llm layer (a cassette HIT never
    # needs credentials); an explicit api_key still resolves through the same
    # lazy closure on first network need.

    def _metric_provider_label() -> str:
        prov = provider or (resolved_lazily[0] if resolved_lazily else None)
        # "frozen" = the llm layer served a cassette; bounded label, never PII.
        return prov.protocol.value if prov is not None else "frozen"

    def _log_provider() -> tuple[str, str]:
        prov = provider or (resolved_lazily[0] if resolved_lazily else None)
        return (prov.label, prov.id) if prov is not None else ("frozen", "-")

    completion_chars = 0
    # AC-observability.10.4: time the provider call and emit a latency+outcome metric on
    # both the success and error paths. Labels are low-cardinality (provider
    # label, model id, bounded outcome) — never PII or response content.
    provider_call_start = time.perf_counter()
    try:
        async for content in litellm_stream(
            messages,
            provider=provider,
            provider_resolver=_lazy_provider if provider is None else None,
            model_id=model,
            decode=decode,
            timeout=timeout,
        ):
            # Tally length only — don't buffer the full response just to estimate tokens.
            completion_chars += len(content)
            yield content
    except LLMError as exc:
        record_ai_provider_call(
            # `provider.label` is user-editable free text (PII + unbounded
            # cardinality); the protocol family is a bounded StrEnum — safe label.
            provider=_metric_provider_label(),
            model=model,
            outcome="error",
            duration_ms=round((time.perf_counter() - provider_call_start) * 1000, 2),
        )
        _label, _pid = _log_provider()
        logger.error(
            "AI provider streaming failed",
            provider=_label,  # resolved provider (DB or env), not the env AI_PROVIDER
            provider_id=_pid,
            model=model,
            mode=mode_label,
            error=str(exc),
            retryable=exc.retryable,
        )
        raise AIStreamError(str(exc), retryable=exc.retryable) from exc
    else:
        record_ai_provider_call(
            # Bounded protocol-family label (see error path above) — never the
            # user-editable provider.label.
            provider=_metric_provider_label(),
            model=model,
            outcome="success",
            duration_ms=round((time.perf_counter() - provider_call_start) * 1000, 2),
        )
        # Count the request + (estimated) token usage. Usage telemetry must never
        # break a completed stream.
        try:
            await get_usage_meter().record(
                model,
                mode_label,
                _estimate_prompt_tokens(list(messages)),
                estimate_tokens_from_chars(completion_chars),
            )
        except Exception:  # noqa: BLE001 - usage telemetry is not correctness
            logger.debug("llm usage recording skipped", exc_info=True)


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
        decode=DecodeParams(
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            extra_body={
                key: value for key, value in (("do_sample", do_sample), ("thinking", thinking)) if value is not None
            },
        ),
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
    reasoning: ReasoningEffort | None = None,
    max_tokens: int | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Stream chat completions without JSON mode (plain text).

    ``reasoning``/``max_tokens`` let a caller apply a scene binding's configured
    reasoning depth and token cap (EPIC-023 AC23.4.5)."""
    async for chunk in _stream_ai_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        user_id=user_id,
        timeout=timeout,
        decode=DecodeParams(reasoning=reasoning, max_tokens=max_tokens),
        mode_label="chat mode",
    ):
        yield chunk


async def accumulate_stream(stream: AsyncIterator[str]) -> str:
    """Accumulate all chunks from a stream into a single string."""
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)
