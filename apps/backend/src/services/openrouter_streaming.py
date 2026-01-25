"""OpenRouter streaming utilities for vision and chat models."""

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class OpenRouterStreamError(Exception):
    """Raised when OpenRouter streaming fails."""

    def __init__(self, message: str, retryable: bool = False):
        """
        Initialize OpenRouter streaming error.

        Args:
            message: Error description
            retryable: Whether this error can be retried (e.g., HTTP 429 rate limits,
                       HTTP 5xx server errors). Network timeouts raise httpx exceptions
                       directly and are not wrapped.
        """
        super().__init__(message)
        self.retryable = retryable


async def _stream_openrouter_base(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float,
    connect_timeout: float,
    response_format: dict[str, str] | None = None,
    mode_label: str = "streaming",
) -> AsyncIterator[str]:
    """
    Base streaming implementation for OpenRouter API.

    Internal helper that handles the common logic for both JSON and chat modes.
    """
    if not api_key:
        api_key = settings.openrouter_api_key
    if not api_key:
        raise OpenRouterStreamError("OpenRouter API key not configured", retryable=False)

    if not base_url:
        base_url = settings.openrouter_base_url

    payload: dict[str, Any] = {
        "model": model,
        "stream": True,
        "messages": messages,
    }
    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://finance-report.local",
        "X-Title": "Finance Report Backend",
    }

    timeout_config = httpx.Timeout(timeout, connect=connect_timeout, read=timeout)
    start_time = time.perf_counter()
    chunk_count = 0
    total_chars = 0

    logger.info(
        "Starting OpenRouter streaming request",
        model=model,
        mode=mode_label,
        timeout=timeout,
    )

    async with (
        httpx.AsyncClient(timeout=timeout_config) as client,
        aconnect_sse(
            client,
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as event_source,
    ):
        if event_source.response.status_code != 200:
            error_text = await event_source.response.aread()
            error_message = f"HTTP {event_source.response.status_code}: {error_text.decode('utf-8', errors='replace')}"
            # Rate limits and service errors are retryable
            retryable = event_source.response.status_code in (429, 500, 502, 503, 504)
            raise OpenRouterStreamError(error_message, retryable=retryable)

        chunk_count = 0
        content_count = 0

        async for event in event_source.aiter_sse():
            # Ignore SSE comments (e.g., ": OPENROUTER PROCESSING")
            if event.data.startswith(":") or not event.data.strip():
                continue

            if event.data == "[DONE]":
                break

            chunk_count += 1

            try:
                chunk_data = json.loads(event.data)

                # Check for mid-stream errors (OpenRouter sends error in response body)
                if "error" in chunk_data:
                    error_info = chunk_data["error"]
                    error_msg = error_info.get("message", str(error_info))
                    error_code = error_info.get("code", "unknown")
                    logger.error(
                        f"OpenRouter mid-stream error ({mode_label})",
                        error_code=error_code,
                        error_message=error_msg,
                        model=model,
                    )
                    raise OpenRouterStreamError(
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
                        f"OpenRouter stream terminated with error ({mode_label})",
                        model=model,
                        chunk_data_preview=str(chunk_data)[:500],
                    )
                    raise OpenRouterStreamError("Stream terminated with error", retryable=True)

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
                f"OpenRouter stream received chunks but no content ({mode_label})",
                model=model,
                chunk_count=chunk_count,
                content_count=content_count,
            )
        elif chunk_count == 0:
            logger.warning(
                f"OpenRouter stream received no chunks ({mode_label})",
                model=model,
            )

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "OpenRouter streaming completed",
        model=model,
        mode=mode_label,
        duration_ms=round(duration_ms, 2),
        chunk_count=chunk_count,
        content_count=content_count,
        total_chars=total_chars,
    )


async def stream_openrouter_json(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 180.0,
) -> AsyncIterator[str]:
    """
    Stream OpenRouter chat completions with JSON mode.

    Yields raw delta content chunks. For vision models, this includes
    the full JSON response as it's generated.
    """
    async for chunk in _stream_openrouter_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        connect_timeout=10.0,
        response_format={"type": "json_object"},
        mode_label="JSON mode",
    ):
        yield chunk


async def stream_openrouter_chat(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """
    Stream OpenRouter chat completions without JSON mode.

    Yields raw delta content chunks for plain text chat responses.

    Note: timeout increased to 120s to handle AI model cold starts and
    complex financial context processing which can take longer than typical API calls.
    """
    async for chunk in _stream_openrouter_base(
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
