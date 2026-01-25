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

        async for event in event_source.aiter_sse():
            if event.data == "[DONE]":
                break

            try:
                chunk_data = json.loads(event.data)
                delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    chunk_count += 1
                    total_chars += len(content)
                    yield content
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse JSON in SSE event ({mode_label})",
                    data_preview=event.data[:200],
                )
                continue

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "OpenRouter streaming completed",
        model=model,
        mode=mode_label,
        duration_ms=round(duration_ms, 2),
        chunk_count=chunk_count,
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
    timeout: float = 30.0,
) -> AsyncIterator[str]:
    """
    Stream OpenRouter chat completions without JSON mode.

    Yields raw delta content chunks for plain text chat responses.
    """
    async for chunk in _stream_openrouter_base(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        connect_timeout=5.0,
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
