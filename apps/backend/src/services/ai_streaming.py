"""AI provider streaming utilities for OpenAI-compatible chat models.

The public function names remain for backward compatibility with existing
call sites, but configuration is provider-neutral.
"""

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class AIStreamError(Exception):
    """Raised when AI provider streaming fails."""

    def __init__(self, message: str, retryable: bool = False):
        """
        Initialize AI provider streaming error.

        Args:
            message: Error description
            retryable: Whether this error can be retried (e.g., HTTP 429 rate limits,
                       HTTP 5xx server errors). Network timeouts raise httpx exceptions
                       directly and are not wrapped.
        """
        super().__init__(message)
        self.retryable = retryable


async def _stream_ai_base(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float,
    connect_timeout: float,
    max_tokens: int | None = None,
    temperature: float | None = None,
    do_sample: bool | None = None,
    thinking: dict[str, Any] | None = None,
    response_format: dict[str, str] | None = None,
    mode_label: str = "streaming",
) -> AsyncIterator[str]:
    """
    Base streaming implementation for OpenAI-compatible chat APIs.

    Internal helper that handles the common logic for both JSON and chat modes.
    """
    if not api_key:
        api_key = getattr(settings, "ai_api_key", None)
    if not isinstance(api_key, str) or not api_key:
        raise AIStreamError("AI provider API key not configured", retryable=False)

    if not base_url:
        base_url = getattr(settings, "ai_base_url", None)
    if not isinstance(base_url, str) or not base_url:
        raise AIStreamError("AI provider base URL not configured", retryable=False)

    chat_path = getattr(settings, "ai_chat_completions_path", "/chat/completions")
    if not isinstance(chat_path, str) or not chat_path:
        chat_path = "/chat/completions"
    chat_url = f"{base_url.rstrip('/')}/{chat_path.lstrip('/')}"

    payload: dict[str, Any] = {
        "model": model,
        "stream": True,
        "messages": messages,
    }
    if response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if do_sample is not None:
        payload["do_sample"] = do_sample
    if thinking is not None:
        payload["thinking"] = thinking

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if settings.ai_provider == "openrouter":
        headers["HTTP-Referer"] = "https://finance-report.local"
        headers["X-Title"] = "Finance Report Backend"

    timeout_config = httpx.Timeout(timeout, connect=connect_timeout, read=timeout)
    start_time = time.perf_counter()
    chunk_count = 0
    total_chars = 0

    logger.info(
        "Starting AI provider streaming request",
        provider=settings.ai_provider,
        model=model,
        mode=mode_label,
        timeout=timeout,
    )

    async with (
        httpx.AsyncClient(timeout=timeout_config) as client,
        aconnect_sse(
            client,
            "POST",
            chat_url,
            headers=headers,
            json=payload,
        ) as event_source,
    ):
        if event_source.response.status_code != 200:
            error_text = await event_source.response.aread()
            error_body = error_text.decode("utf-8", errors="replace")
            error_message = f"HTTP {event_source.response.status_code}: {error_body}"
            retryable = event_source.response.status_code in (429, 500, 502, 503, 504)

            logger.error(
                "AI provider HTTP error",
                provider=settings.ai_provider,
                model=model,
                status_code=event_source.response.status_code,
                error_body=error_body[:500],
                retryable=retryable,
                mode=mode_label,
                headers=dict(event_source.response.headers),
            )

            raise AIStreamError(error_message, retryable=retryable)

        chunk_count = 0
        content_count = 0

        async for event in event_source.aiter_sse():
            # Ignore SSE comments (some providers emit progress comments)
            if event.data.startswith(":") or not event.data.strip():
                continue

            if event.data == "[DONE]":
                break

            chunk_count += 1

            try:
                chunk_data = json.loads(event.data)

                # Check for mid-stream errors (OpenAI-compatible providers can
                # send an error object in the response body)
                if "error" in chunk_data:
                    error_info = chunk_data["error"]
                    error_msg = error_info.get("message", str(error_info))
                    error_code = error_info.get("code", "unknown")
                    logger.error(
                        f"AI provider mid-stream error ({mode_label})",
                        provider=settings.ai_provider,
                        error_code=error_code,
                        error_message=error_msg,
                        model=model,
                    )
                    raise AIStreamError(
                        f"Mid-stream error: {error_msg}", retryable=error_code in ("server_error", "timeout")
                    )

                choices = chunk_data.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]

                # Check for error finish_reason
                finish_reason = choice.get("finish_reason")
                if finish_reason == "error":
                    logger.error(
                        f"AI provider stream terminated with error ({mode_label})",
                        provider=settings.ai_provider,
                        model=model,
                        chunk_data_preview=str(chunk_data)[:500],
                    )
                    raise AIStreamError("Stream terminated with error", retryable=True)

                delta = choice.get("delta", {})
                content = delta.get("content", "")
                if content:
                    content_count += 1
                    total_chars += len(content)
                    yield content

            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse JSON in SSE event ({mode_label})",
                    data_preview=event.data[:200],
                )
                continue

        # Log summary for debugging empty responses
        if chunk_count > 0 and content_count == 0:
            logger.warning(
                f"AI provider stream received chunks but no content ({mode_label})",
                provider=settings.ai_provider,
                model=model,
                chunk_count=chunk_count,
                content_count=content_count,
            )
        elif chunk_count == 0:
            logger.warning(
                f"AI provider stream received no chunks ({mode_label})",
                provider=settings.ai_provider,
                model=model,
            )

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "AI provider streaming completed",
        provider=settings.ai_provider,
        model=model,
        mode=mode_label,
        duration_ms=round(duration_ms, 2),
        chunk_count=chunk_count,
        content_count=content_count,
        total_chars=total_chars,
    )


async def stream_ai_json(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 180.0,
    max_tokens: int | None = None,
    temperature: float | None = None,
    do_sample: bool | None = None,
    thinking: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """
    Stream OpenAI-compatible chat completions for JSON extraction.

    Yields raw delta content chunks. For vision models, this includes
    the full JSON response as it's generated.

    Note: We intentionally do NOT set response_format={"type": "json_object"}
    because many providers (e.g., ModelRun for qwen-free models) do not support
    this parameter with multimodal/PDF inputs, returning HTTP 400 "Value error".
    The prompt already instructs the AI to return valid JSON.
    """
    async for chunk in _stream_ai_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        connect_timeout=10.0,
        max_tokens=max_tokens,
        temperature=temperature,
        do_sample=do_sample,
        thinking=thinking,
        response_format=None,
        mode_label="JSON extraction",
    ):
        yield chunk


async def stream_ai_chat(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """
    Stream OpenAI-compatible chat completions without JSON mode.

    Yields raw delta content chunks for plain text chat responses.

    Note: timeout increased to 120s to handle AI model cold starts and
    complex financial context processing which can take longer than typical API calls.
    """
    async for chunk in _stream_ai_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        connect_timeout=10.0,
        response_format=None,
        mode_label="chat mode",
    ):
        yield chunk


async def accumulate_stream(stream: AsyncIterator[str]) -> str:
    """Accumulate all chunks from a stream into a single string."""
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)
