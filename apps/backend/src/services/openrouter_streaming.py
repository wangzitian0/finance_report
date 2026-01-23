"""OpenRouter streaming utilities for vision and chat models."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

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
            retryable: Whether this error can be retried (e.g., rate limits, timeouts)
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

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                error_message = (
                    f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='replace')}"
                )
                # Rate limits and service errors are retryable
                retryable = response.status_code in (429, 500, 502, 503, 504)
                raise OpenRouterStreamError(error_message, retryable=retryable)

            consecutive_failures = 0
            max_consecutive_failures = 10

            async for line in response.aiter_lines():
                if not line or not line.strip():
                    continue

                if line.startswith("data: "):
                    line = line[6:]

                if line == "[DONE]":
                    break

                try:
                    chunk_data = json.loads(line)
                    delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        consecutive_failures = 0
                        yield content
                except json.JSONDecodeError:
                    consecutive_failures += 1
                    logger.warning(
                        f"Failed to parse SSE chunk ({mode_label})",
                        line=line,
                        consecutive_failures=consecutive_failures,
                    )
                    if consecutive_failures >= max_consecutive_failures:
                        raise OpenRouterStreamError(
                            f"Failed to parse {max_consecutive_failures} consecutive SSE chunks",
                            retryable=False,
                        )
                    continue


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
