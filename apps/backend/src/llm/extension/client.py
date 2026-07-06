"""litellm-backed transport (EPIC-023 EPIC A).

``litellm_stream`` is the single chokepoint that talks to litellm; everything
provider-specific is resolved by :mod:`src.llm.extension.routing`, and ``drop_params=True``
lets litellm silently drop fields a given model rejects (e.g. Z.AI/GLM rejecting
``seed`` — the quirk that previously needed bespoke handling). Provider/model
selection is shared via :func:`resolve_provider_and_model`; the service-facing
entry point is ``services.ai_streaming`` (which counts request/token usage).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import litellm

from src.llm.base import (
    ConfigSource,
    LLMConfigError,
    LLMError,
    Message,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
)
from src.llm.extension.cassette import (
    Cassette as _Cassette,
    CassetteMiss,
    CassetteMode,
    CassetteRecorder,
    CassetteStore,
    CassetteTag,
    CassetteValidationError,
    _canonical_request,
    fingerprint,
    in_ci,
    layer_engaged,
    live_forced,
    refresh_requested,
)
from src.llm.extension.routing import build_call
from src.observability import get_logger

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


def _disable_litellm_aiohttp_transport() -> None:
    """Route litellm through its httpx transport instead of the default aiohttp one.

    litellm's aiohttp transport lazily creates an ``aiohttp.ClientSession`` per
    request handler and never closes it (no shared ``litellm.aclient_session``),
    so every ``acompletion`` leaks an "Unclosed client session" — an ERROR-level
    log plus a real socket/fd leak that accumulates under sustained parsing
    (#1442). The httpx transport litellm manages itself does not leak. Guarded so
    a future litellm rename can never break import."""
    try:
        litellm.disable_aiohttp_transport = True
    except Exception:  # noqa: BLE001 - transport hardening is never fatal
        pass


_harden_litellm_logging()
_disable_litellm_aiohttp_transport()

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
    elif provider.protocol is ProtocolFamily.GOOGLE_GEMINI:
        # Gemini 2.5+ "thinks" by default and those thinking tokens are charged
        # against max_output_tokens, so a verbose extraction (raw_text + category
        # per row) hits finish="length" and truncates mid-JSON -> 0 parsed rows.
        # Disable thinking when no reasoning is requested. Live-call kwarg ONLY —
        # deliberately NOT mirrored into the cassette fingerprint decode params, so
        # a Gemini-recorded cassette still replays under any default provider.
        kwargs["reasoning_effort"] = "disable"
    if seed is not None:
        # Native param so drop_params can strip it for models that reject seed.
        kwargs["seed"] = seed
    if extra_body:
        # Wire-level protocol filter (#1597): do_sample/thinking are semantic
        # request knobs that always live in the fingerprint, but only
        # OpenAI-compatible providers accept them on the wire — Gemini/Anthropic
        # reject unknown request fields with HTTP 400.
        body = dict(extra_body)
        if provider.protocol is not ProtocolFamily.OPENAI_COMPATIBLE:
            body.pop("do_sample", None)
            body.pop("thinking", None)
        if body:
            kwargs["extra_body"] = body
    return kwargs


# The streaming cassette's frozen-response convention: a streamed completion has
# no single provider "response dict", so we freeze the *accumulated text* under
# this key. Replay synthesises a stream from it (one chunk); the key is the only
# field replay reads, so any extra metadata a recorder adds is ignored.
_STREAM_TEXT_KEY = "stream_text"


def _stream_role(messages: Sequence[Message]) -> str:
    """Derive the cassette fingerprint role from the message modality.

    ``"vision"`` when any message content carries an image part (an ``image_url``
    part, or a part/dict whose ``type`` mentions ``image``); ``"text"`` otherwise.
    Callers need no change — the streaming transport classifies its own modality,
    matching the text/default-config-vision split that flows through this path.
    """
    for message in messages:
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, (list, tuple)):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            part_type = str(part.get("type", "")).lower()
            if "image" in part_type or "image_url" in part:
                return "vision"
    return "text"


def _stream_decode_params(
    *,
    max_tokens: int | None,
    temperature: float | None,
    reasoning: ReasoningEffort | None,
    seed: int | None,
    extra_body: dict[str, Any] | None,
) -> dict[str, Any]:
    """Decode params that change the bytes the provider emits (model id excluded).

    Mirrors ``cassette_completion``'s decode-param block so a streamed call and a
    non-streamed call with the same knobs key the same way."""
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
    return decode_params


async def _litellm_stream_live(kwargs: dict[str, Any]) -> AsyncIterator[str]:
    """The real litellm streaming call — yields content deltas, skipping empties.

    Extracted so OFF (passthrough) and RECORD (passthrough + accumulate) share the
    exact same transport; provider failures are normalised to ``LLMError`` here so
    both modes see the identical error contract OFF always had."""
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


async def litellm_stream(
    messages: Sequence[Message],
    *,
    provider: ProviderRef | None = None,
    provider_resolver: Callable[[], Awaitable[ProviderRef]] | None = None,
    model_id: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    reasoning: ReasoningEffort | None = None,
    seed: int | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float | None = None,
    cassette_store: CassetteStore | None = None,
    cassette_mode: CassetteMode | None = None,
    cassette_tag: CassetteTag = CassetteTag.FLOW_ONLY,
    cassette_validator: Any = None,
) -> AsyncIterator[str]:
    """Stream text delta chunks for one completion via litellm — cassette-aware.

    The streaming bridge for the cassette layer (EPIC-023 AC23.6): the real
    extraction transport is streaming and previously bypassed the record/replay
    layer entirely, so PR CI never exercised the LLM path. This routes the stream
    through that layer while preserving streaming for the caller.

    Explicit ``cassette_mode`` (IN-LAYER test seam only; no process env):

    - ``off`` — EXACT prior behaviour: a live ``litellm.acompletion(stream=True)``
      passthrough, deltas yielded as they arrive. Prod/staging run ``off`` so the
      staging ``-m llm`` gate stays live and real; this branch touches no cassette.
    - ``record`` — the real streaming call, accumulating the full text, then freeze
      a cassette (a ``correctness`` tag validates the accumulated text first), and
      yield the text so the caller still works. No re-stream of frozen bytes.
    - ``replay`` — fingerprint + cassette lookup with **zero network and no API
      key**; HIT synthesises the stream from the frozen text (one chunk); MISS is a
      hard ``CassetteMiss`` (never a network fallback).

    The fingerprint role is derived from the messages (``vision`` if any image
    part, else ``text``) and the key is model-id-agnostic — callers are unchanged.

    Note: we deliberately do NOT request ``stream_options={"include_usage": True}`` —
    Z.AI/GLM rejects unknown params with HTTP 400 and litellm won't drop it (it's a
    supported openai-compatible field). Token usage is estimated by the caller from
    text instead (see ``services.ai_streaming``)."""
    _provider_cache: list[ProviderRef] = [provider] if provider is not None else []

    async def _resolved_provider() -> ProviderRef:
        if _provider_cache:
            return _provider_cache[0]
        if provider_resolver is not None:
            resolved = await provider_resolver()
            _provider_cache.append(resolved)
            return resolved
        raise LLMConfigError("litellm_stream needs a provider (or provider_resolver) for a live call")

    async def _live_kwargs() -> dict[str, Any]:
        live_provider = await _resolved_provider()
        kwargs = _base_kwargs(
            provider=live_provider,
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
        return kwargs

    # ------- Transparent per-request decision (#1596) -------
    # No explicit legacy mode anywhere: the LAYER decides per request; downstream
    # cannot know (and never says) whether the response is real or frozen.
    # The explicit cassette_mode arg is the IN-LAYER test seam only (#1597);
    # no process env selects modes anymore — the layer decides per request.
    if cassette_mode is None:
        if live_forced() or not layer_engaged():
            # Explicit LIVE (staging -m llm gates, prod) or the layer is simply
            # not engaged (app runtime): exact live passthrough, store untouched.
            async for content in _litellm_stream_live(await _live_kwargs()):
                yield content
            return

        t_role = _stream_role(messages)
        t_decode = _stream_decode_params(
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning=reasoning,
            seed=seed,
            extra_body=extra_body,
        )
        t_key = fingerprint(role=t_role, messages=messages, decode_params=t_decode)
        t_store = cassette_store or CassetteStore()
        t_hit = t_store.get(t_key)

        if t_hit is not None and not refresh_requested():
            # HIT serves the frozen response — credentials are never resolved.
            t_store.mark_served(t_key)
            text = str(t_hit.response.get(_STREAM_TEXT_KEY, ""))
            if text:
                yield text
            return

        if in_ci():
            # Reaching here in CI means a MISS: refresh_requested() is always
            # False in CI, so any HIT was already served above. A MISS in CI is
            # ALWAYS the hard failure — even with a key present.
            raise CassetteMiss(t_key, scene=t_role)

        # Local MISS (or explicit refresh): a real call needs usable credentials.
        try:
            live_provider = await _resolved_provider()
        except LLMConfigError:
            live_provider = None
        if live_provider is None or not live_provider.api_key:
            raise CassetteMiss(t_key, scene=t_role)

        if cassette_tag is CassetteTag.CORRECTNESS and cassette_validator is None:
            raise CassetteValidationError(
                f"correctness cassette (role={t_role}) requires a ground-truth validator to record"
            )
        parts: list[str] = []
        async for content in _litellm_stream_live(await _live_kwargs()):
            parts.append(content)
        text = "".join(parts)
        if cassette_tag is CassetteTag.CORRECTNESS:
            try:
                ok = bool(cassette_validator({_STREAM_TEXT_KEY: text}))
            except Exception as exc:  # noqa: BLE001 - any validator error refuses the record
                raise CassetteValidationError(
                    f"correctness validation raised for role={t_role}: {type(exc).__name__}"
                ) from exc
            if not ok:
                raise CassetteValidationError(
                    f"correctness cassette (role={t_role}, key={t_key}) refused: response failed "
                    "ground-truth validation; recording it would freeze a wrong answer"
                )
        request = _canonical_request(role=t_role, messages=messages, decode_params=t_decode)
        t_store.put(
            _Cassette(key=t_key, role=t_role, tag=cassette_tag, request=request, response={_STREAM_TEXT_KEY: text})
        )
        t_store.mark_served(t_key)
        logger.info("llm cassette auto-recorded on miss", key=t_key, role=t_role, refresh=refresh_requested())
        if text:
            yield text
        return

    # ------- Legacy explicit-mode contract (compat until #1597 deletes it) -------
    # In-layer seam only: cassette_mode is None was handled above (transparent).
    mode = cassette_mode if cassette_mode is not None else CassetteMode.OFF

    if mode is CassetteMode.OFF:
        # OFF: the prior passthrough, byte-for-byte. Keeps prod/staging live & real.
        async for content in _litellm_stream_live(await _live_kwargs()):
            yield content
        return

    role = _stream_role(messages)
    decode_params = _stream_decode_params(
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning=reasoning,
        seed=seed,
        extra_body=extra_body,
    )
    key = fingerprint(role=role, messages=messages, decode_params=decode_params)
    store = cassette_store or CassetteStore()

    if mode is CassetteMode.REPLAY:
        cassette = store.get(key)
        if cassette is None:
            # Hard fail — no network fallback (replay needs no key, makes no call).
            raise CassetteMiss(key, scene=role)
        # Orphan-gate accounting (#1597): explicit-seam replays are serves too.
        store.mark_served(key)
        text = str(cassette.response.get(_STREAM_TEXT_KEY, ""))
        # Synthesise the stream from the frozen text as a single chunk; the caller
        # accumulates it back to the same string it would have streamed live.
        if text:
            yield text
        return

    # RECORD: real streaming call + accumulate, then freeze and replay-yield.
    if cassette_tag is CassetteTag.CORRECTNESS and cassette_validator is None:
        raise CassetteValidationError(f"correctness cassette (role={role}) requires a ground-truth validator to record")
    parts: list[str] = []
    async for content in _litellm_stream_live(await _live_kwargs()):
        parts.append(content)
    text = "".join(parts)
    response = {_STREAM_TEXT_KEY: text}
    if cassette_tag is CassetteTag.CORRECTNESS:
        ok = False
        try:
            ok = bool(cassette_validator(response)) if cassette_validator is not None else False
        except Exception as exc:  # noqa: BLE001 - any validator error refuses the record
            raise CassetteValidationError(
                f"correctness validation raised for role={role}: {type(exc).__name__}"
            ) from exc
        if not ok:
            raise CassetteValidationError(
                f"correctness cassette (role={role}, key={key}) refused: accumulated stream failed "
                "ground-truth validation; recording it would freeze a wrong answer"
            )
    request = _canonical_request(role=role, messages=messages, decode_params=decode_params)
    cassette = _Cassette(key=key, role=role, tag=cassette_tag, request=request, response=response)
    changed = store.put(cassette)
    logger.info("llm stream cassette recorded", key=key, role=role, tag=cassette_tag.value, changed=changed)
    # Yield the recorded text so a record run still produces output for the caller.
    if text:
        yield text


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
    # id is intentionally excluded (model-id-agnostic keying). Shared with the
    # streaming path so a streamed and non-streamed call key the same way.
    decode_params = _stream_decode_params(
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning=reasoning,
        seed=seed,
        extra_body=extra_body,
    )

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
