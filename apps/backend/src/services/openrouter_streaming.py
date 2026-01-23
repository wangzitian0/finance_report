"""OpenRouter streaming utilities for vision and chat models."""

import json
from collections.abc import AsyncIterator

import httpx

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class OpenRouterStreamError(Exception):
    """Raised when OpenRouter streaming fails."""

    pass


async def stream_openrouter_json(
    messages: list[dict[str, str]],
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
    if not api_key:
        api_key = settings.openrouter_api_key
    if not api_key:
        raise OpenRouterStreamError("OpenRouter API key not configured")

    if not base_url:
        base_url = settings.openrouter_base_url

    payload = {
        "model": model,
        "stream": True,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://finance-report.local",
        "X-Title": "Finance Report Backend",
    }

    timeout_config = httpx.Timeout(timeout, connect=10.0, read=timeout)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise OpenRouterStreamError(
                    f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='replace')}"
                )

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
                        yield content
                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk", line=line)
                    continue


async def stream_openrouter_chat(
    messages: list[dict[str, str]],
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
    if not api_key:
        api_key = settings.openrouter_api_key
    if not api_key:
        raise OpenRouterStreamError("OpenRouter API key not configured")

    if not base_url:
        base_url = settings.openrouter_base_url

    payload = {
        "model": model,
        "stream": True,
        "messages": messages,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://finance-report.local",
        "X-Title": "Finance Report Backend",
    }

    timeout_config = httpx.Timeout(timeout, connect=5.0, read=timeout)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise OpenRouterStreamError(
                    f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='replace')}"
                )

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
                        yield content
                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk", line=line)
                    continue


async def accumulate_stream(stream: AsyncIterator[str]) -> str:
    """Accumulate all chunks from a stream into a single string."""
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)
