"""litellm-backed transport with transparent and explicit cassette policy (EPIC-023)."""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from typing import Any

import litellm

from src.llm.base import (
    ConfigSource,
    DecodeParams,
    LLMConfigError,
    LLMError,
    Message,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
)
from src.llm.extension.cassette import (
    CassetteMiss,
    CassetteMode,
    CassetteRecorder,
    CassetteStore,
    CassetteTag,
    _canonical_request as _canonical_request,
    fingerprint,
    in_ci,
    layer_engaged,
    live_forced,
    persist_recorded_cassette,
    refresh_requested,
    require_correctness_validator,
)
from src.llm.extension.routing import build_call
from src.observability import get_logger

logger = get_logger(__name__)


def _harden_litellm_logging() -> None:
    """Disable litellm stdout debug/message logging."""
    for attr, value in (("turn_off_message_logging", True), ("set_verbose", False), ("suppress_debug_info", True)):
        try:
            setattr(litellm, attr, value)
        except Exception:  # noqa: BLE001
            pass


def _disable_litellm_aiohttp_transport() -> None:
    """Force litellm onto httpx transport to prevent unclosed aiohttp sessions (#1442)."""
    try:
        litellm.disable_aiohttp_transport = True
    except Exception:  # noqa: BLE001
        pass


_harden_litellm_logging()
_disable_litellm_aiohttp_transport()

_GLM_53_FAMILY = re.compile(r"glm-5\.3(-[a-z]+)?", re.IGNORECASE)
_RETRYABLE_EXC = frozenset(
    {"RateLimitError", "Timeout", "APIConnectionError", "ServiceUnavailableError", "InternalServerError"}
)
_PROVIDER_CODE = re.compile(r"""["']code["']\s*:\s*["']?(\d{3,5})["']?""")
_CODE_TEXT = re.compile(r"\d{3,5}")
_CHAIN_DEPTH = 4
_STREAM_TEXT_KEY = "stream_text"


def _is_retryable(exc: Exception) -> bool:
    return type(exc).__name__ in _RETRYABLE_EXC


def _code_in_body(body: object) -> str | None:
    if not isinstance(body, Mapping):
        return None
    for source in (body.get("error"), body):
        if not isinstance(source, Mapping):
            continue
        code = source.get("code")
        if not isinstance(code, bool) and isinstance(code, str | int) and _CODE_TEXT.fullmatch(str(code)):
            return str(code)
    return None


def _provider_code(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    for _ in range(_CHAIN_DEPTH):
        if current is None:
            break
        if code := _code_in_body(getattr(current, "body", None)):
            return code
        current = current.__cause__ or current.__context__
    match = _PROVIDER_CODE.search(str(exc))
    return match.group(1) if match else None


def _wrap(exc: Exception) -> LLMError:
    """Wrap upstream provider errors without leaking request context text."""
    parts = [type(exc).__name__]
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        parts.append(f"http {status}")
    if code := _provider_code(exc):
        parts.append(f"provider code {code}")
    return LLMError(f"LLM provider call failed ({', '.join(parts)})", retryable=_is_retryable(exc))


def _base_kwargs(
    *,
    provider: ProviderRef,
    model_id: str,
    messages: Sequence[Message],
    decode: DecodeParams,
) -> dict[str, Any]:
    kwargs = build_call(provider, model_id).kwargs()
    kwargs["messages"] = list(messages)
    kwargs["drop_params"] = True
    if decode.max_tokens is not None:
        kwargs["max_tokens"] = decode.max_tokens
    if decode.temperature is not None:
        kwargs["temperature"] = decode.temperature
    if decode.reasoning is not None and decode.reasoning is not ReasoningEffort.NONE:
        kwargs["reasoning_effort"] = decode.reasoning.value
    elif provider.protocol is ProtocolFamily.GOOGLE_GEMINI:
        kwargs["reasoning_effort"] = "disable"
    if decode.seed is not None:
        kwargs["seed"] = decode.seed
    if decode.extra_body:
        body = dict(decode.extra_body)
        if provider.protocol is not ProtocolFamily.OPENAI_COMPATIBLE:
            body.pop("do_sample", None)
            body.pop("thinking", None)
        if body:
            kwargs["extra_body"] = body
    if provider.protocol is ProtocolFamily.OPENAI_COMPATIBLE and _GLM_53_FAMILY.fullmatch(
        model_id.removeprefix("openai/")
    ):
        body = dict(kwargs.get("extra_body", {}))
        body["thinking"] = {**body.get("thinking", {}), "type": "enabled"}
        kwargs["extra_body"] = body
        kwargs["reasoning_effort"] = (
            "high" if decode.reasoning in {ReasoningEffort.MEDIUM, ReasoningEffort.HIGH} else "low"
        )
        kwargs["allowed_openai_params"] = ["reasoning_effort"]
    return kwargs


def _stream_role(messages: Sequence[Message]) -> str:
    """Classify stream modality role as ``vision`` when any part carries an image, else ``text``."""
    for message in messages:
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list | tuple):
            continue
        for part in content:
            if isinstance(part, Mapping) and ("image" in str(part.get("type", "")).lower() or "image_url" in part):
                return "vision"
    return "text"


async def _litellm_stream_live(kwargs: dict[str, Any]) -> AsyncIterator[str]:
    """Execute live litellm streaming call and yield non-empty content deltas."""
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
    except Exception as exc:  # noqa: BLE001
        logger.error("litellm stream failed", model=kwargs.get("model"), error=str(exc), error_type=type(exc).__name__)
        raise _wrap(exc) from exc
    finally:
        logger.info(
            "litellm stream finished",
            model=kwargs.get("model"),
            success=success,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            total_chars=chars,
        )


@dataclass(frozen=True, slots=True)
class CassetteOptions:
    """In-layer cassette test/record controls kept out of transport signatures."""

    store: CassetteStore | None = None
    mode: CassetteMode | None = None
    tag: CassetteTag = CassetteTag.FLOW_ONLY
    validator: Any = None


async def _litellm_transport(
    messages: Sequence[Message],
    *,
    provider: ProviderRef | None = None,
    provider_resolver: Callable[[], Awaitable[ProviderRef]] | None = None,
    model_id: str,
    decode: DecodeParams = DecodeParams(),
    timeout: float | None = None,
) -> AsyncIterator[str]:
    """Perform one live provider stream with typed decode parameters."""
    if provider is None:
        if provider_resolver is None:
            raise LLMConfigError("litellm_stream needs a provider (or provider_resolver) for a live call")
        provider = await provider_resolver()
    kwargs = _base_kwargs(provider=provider, model_id=model_id, messages=messages, decode=decode)
    kwargs["stream"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout
    async for content in _litellm_stream_live(kwargs):
        yield content


def cassette_stream(transport: Callable[..., AsyncIterator[str]]) -> Callable[..., AsyncIterator[str]]:
    """Decorate a live stream with transparent and explicit cassette policy."""

    @wraps(transport)
    async def wrapped(
        messages: Sequence[Message],
        *,
        provider: ProviderRef | None = None,
        provider_resolver: Callable[[], Awaitable[ProviderRef]] | None = None,
        model_id: str,
        decode: DecodeParams = DecodeParams(),
        timeout: float | None = None,
        cassette: CassetteOptions | None = None,
    ) -> AsyncIterator[str]:
        async for content in _cassette_stream_dispatch(
            transport,
            messages,
            provider=provider,
            provider_resolver=provider_resolver,
            model_id=model_id,
            decode=decode,
            timeout=timeout,
            cassette=cassette or CassetteOptions(),
        ):
            yield content

    wrapped.__cassette_decorated__ = True  # type: ignore[attr-defined]
    return wrapped


async def _cassette_stream_dispatch(
    transport: Callable[..., AsyncIterator[str]],
    messages: Sequence[Message],
    *,
    provider: ProviderRef | None,
    provider_resolver: Callable[[], Awaitable[ProviderRef]] | None,
    model_id: str,
    decode: DecodeParams,
    timeout: float | None,
    cassette: CassetteOptions,
) -> AsyncIterator[str]:
    """Apply transparent (#1596) or explicit test-seam (#1597) cassette policy around a live stream."""
    _provider_cache: list[ProviderRef] = [provider] if provider is not None else []

    async def _resolved_provider() -> ProviderRef:
        if _provider_cache:
            return _provider_cache[0]
        if provider_resolver is not None:
            resolved = await provider_resolver()
            _provider_cache.append(resolved)
            return resolved
        raise LLMConfigError("litellm_stream needs a provider (or provider_resolver) for a live call")

    async def _live() -> AsyncIterator[str]:
        async for content in transport(
            messages,
            provider=await _resolved_provider(),
            model_id=model_id,
            decode=decode,
            timeout=timeout,
        ):
            yield content

    if (cassette.mode is None and (live_forced() or not layer_engaged())) or cassette.mode is CassetteMode.OFF:
        async for content in _live():
            yield content
        return

    role = _stream_role(messages)
    decode_params = decode.as_request()
    key = fingerprint(role=role, messages=messages, decode_params=decode_params)
    store = cassette.store or CassetteStore()

    if cassette.mode is None:
        hit = store.get(key)
        if hit is not None and not refresh_requested():
            store.mark_served(key)
            if text := str(hit.response.get(_STREAM_TEXT_KEY, "")):
                yield text
            return
        if in_ci():
            raise CassetteMiss(key, scene=role)
        try:
            live_provider = await _resolved_provider()
        except LLMConfigError:
            live_provider = None
        if live_provider is None or not live_provider.api_key:
            raise CassetteMiss(key, scene=role)
        failure_noun = "response"
    elif cassette.mode is CassetteMode.REPLAY:
        hit = store.get(key)
        if hit is None:
            raise CassetteMiss(key, scene=role)
        store.mark_served(key)
        if text := str(hit.response.get(_STREAM_TEXT_KEY, "")):
            yield text
        return
    else:
        failure_noun = "accumulated stream"

    require_correctness_validator(cassette.tag, cassette.validator, role=role)
    text = "".join([content async for content in _live()])
    changed = persist_recorded_cassette(
        store,
        key=key,
        role=role,
        tag=cassette.tag,
        validator=cassette.validator,
        messages=messages,
        decode_params=decode_params,
        response={_STREAM_TEXT_KEY: text},
        failure_noun=failure_noun,
    )
    if cassette.mode is None:
        store.mark_served(key)
        logger.info("llm cassette auto-recorded on miss", key=key, role=role, refresh=refresh_requested())
    else:
        logger.info("llm stream cassette recorded", key=key, role=role, tag=cassette.tag.value, changed=changed)
    if text:
        yield text


litellm_stream = cassette_stream(_litellm_transport)


async def cassette_completion(
    messages: Sequence[Message],
    *,
    role: str,
    provider: ProviderRef,
    model_id: str,
    recorder: CassetteRecorder | None = None,
    tag: CassetteTag = CassetteTag.FLOW_ONLY,
    validator: Any = None,
    decode: DecodeParams = DecodeParams(),
    timeout: float | None = None,
) -> dict[str, Any]:
    """Cassette-aware non-streaming completion (EPIC-023 AC23.5)."""
    recorder = recorder or CassetteRecorder()

    async def live_call() -> dict[str, Any]:
        kwargs = _base_kwargs(provider=provider, model_id=model_id, messages=messages, decode=decode)
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = await litellm.acompletion(**kwargs)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("litellm completion failed", model=kwargs.get("model"), error_type=type(exc).__name__)
            raise _wrap(exc) from exc
        if hasattr(response, "model_dump"):
            return dict(response.model_dump())
        if isinstance(response, dict):
            return dict(response)
        return {"text": str(response)}

    return await recorder.call(
        live_call,
        role=role,
        messages=messages,
        decode_params=decode.as_request(),
        tag=tag,
        validator=validator,
    )


async def resolve_provider_and_model(config_source: ConfigSource, model_id: str) -> tuple[ProviderRef, str]:
    """Resolve ``model_id`` against ``config_source`` to ``(provider, bare_model)``."""
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
