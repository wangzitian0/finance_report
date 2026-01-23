"""Tests for OpenRouter streaming utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.openrouter_streaming import (
    OpenRouterStreamError,
    accumulate_stream,
    stream_openrouter_chat,
    stream_openrouter_json,
)


class MockAsyncIterator:
    """Helper to create async iterators for testing."""

    def __init__(self, items: list[str]):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


async def mock_stream_generator(chunks: list[str]):
    """Helper to create async generator for streaming mock."""
    for chunk in chunks:
        yield chunk


class TestStreamOpenRouterChat:
    """Tests for stream_openrouter_chat function."""

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_success(self):
        """Test successful streaming chat completion."""
        # Mock SSE response
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "data: [DONE]",
        ]

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_lines = MagicMock(return_value=MockAsyncIterator(sse_lines))

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in stream_openrouter_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="test-model",
                api_key="test-key",
            ):
                chunks.append(chunk)

            assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_handles_http_error(self):
        """Test handling of HTTP errors."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    pass

            assert "HTTP 500" in str(exc_info.value)
            assert "Internal Server Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_handles_done_signal(self):
        """Test that [DONE] signal stops iteration."""
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            "data: [DONE]",
            'data: {"choices":[{"delta":{"content":"Should not appear"}}]}',
        ]

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_lines = MagicMock(return_value=MockAsyncIterator(sse_lines))

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in stream_openrouter_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="test-model",
                api_key="test-key",
            ):
                chunks.append(chunk)

            assert chunks == ["Hello"]
            assert "Should not appear" not in "".join(chunks)

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_handles_malformed_json(self):
        """Test handling of malformed JSON chunks."""
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            "data: {invalid json}",
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "data: [DONE]",
        ]

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_lines = MagicMock(return_value=MockAsyncIterator(sse_lines))

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in stream_openrouter_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="test-model",
                api_key="test-key",
            ):
                chunks.append(chunk)

            # Should skip malformed chunk but continue streaming
            assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_timeout(self):
        """Test timeout handling."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock(side_effect=httpx.ReadTimeout("Request timed out"))

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.ReadTimeout):
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                    timeout=1.0,
                ):
                    pass

    @pytest.mark.asyncio
    async def test_stream_openrouter_chat_requires_api_key(self):
        """Test that API key is required."""
        with patch("src.services.openrouter_streaming.settings") as mock_settings:
            mock_settings.openrouter_api_key = None

            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                ):
                    pass

            assert "API key not configured" in str(exc_info.value)


class TestStreamOpenRouterJson:
    """Tests for stream_openrouter_json function."""

    @pytest.mark.asyncio
    async def test_stream_openrouter_json_success(self):
        """Test successful JSON mode streaming."""
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"{\\"result\\":"}}]}',
            'data: {"choices":[{"delta":{"content":" \\"success\\"}"}}]}',
            "data: [DONE]",
        ]

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_lines = MagicMock(return_value=MockAsyncIterator(sse_lines))

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in stream_openrouter_json(
                messages=[{"role": "user", "content": "Hi"}],
                model="test-model",
                api_key="test-key",
            ):
                chunks.append(chunk)

            assert chunks == ['{"result":', ' "success"}']


class TestAccumulateStream:
    """Tests for accumulate_stream helper."""

    @pytest.mark.asyncio
    async def test_accumulate_stream(self):
        """Test accumulating chunks into single string."""
        stream = mock_stream_generator(["Hello", " ", "world"])
        result = await accumulate_stream(stream)
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_accumulate_stream_empty(self):
        """Test accumulating empty stream."""
        stream = mock_stream_generator([])
        result = await accumulate_stream(stream)
        assert result == ""


class TestErrorRetryableFlags:
    """Test retryable flag is set correctly for different error types."""

    @pytest.mark.asyncio
    async def test_api_key_missing_not_retryable(self):
        """Missing API key errors should not be retryable."""
        with pytest.raises(OpenRouterStreamError) as exc_info:
            stream = stream_openrouter_chat(
                messages=[{"role": "user", "content": "test"}],
                model="openai/gpt-3.5-turbo",
                api_key=None,
            )
            async for _ in stream:
                pass

        assert not exc_info.value.retryable
        assert "API key not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rate_limit_error_retryable(self):
        """HTTP 429 rate limit errors should be retryable."""
        mock_response = AsyncMock()
        mock_response.status_code = 429
        mock_response.aread = AsyncMock(return_value=b"Rate limit exceeded")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "test"}],
                    model="openai/gpt-3.5-turbo",
                    api_key="test-key",
                ):
                    pass

            assert exc_info.value.retryable
            assert "429" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_server_error_retryable(self):
        """HTTP 5xx server errors should be retryable."""
        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_response.aread = AsyncMock(return_value=b"Service unavailable")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "test"}],
                    model="openai/gpt-3.5-turbo",
                    api_key="test-key",
                ):
                    pass

            assert exc_info.value.retryable
            assert "503" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_auth_error_not_retryable(self):
        """HTTP 401/403 auth errors should not be retryable."""
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.aread = AsyncMock(return_value=b"Unauthorized")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "test"}],
                    model="openai/gpt-3.5-turbo",
                    api_key="test-key",
                ):
                    pass

            assert not exc_info.value.retryable
            assert "401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_parse_failure_not_retryable(self):
        """Consecutive parse failures should not be retryable."""
        malformed_chunks = ["{invalid json}" for _ in range(11)]

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_lines = MagicMock(return_value=MockAsyncIterator(malformed_chunks))

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.stream = MagicMock()
        mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "test"}],
                    model="openai/gpt-3.5-turbo",
                    api_key="test-key",
                ):
                    pass

            assert not exc_info.value.retryable
            assert "Failed to parse" in str(exc_info.value)
