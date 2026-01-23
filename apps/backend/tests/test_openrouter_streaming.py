"""Tests for OpenRouter streaming utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx_sse import ServerSentEvent

from src.services.openrouter_streaming import (
    OpenRouterStreamError,
    accumulate_stream,
    stream_openrouter_chat,
    stream_openrouter_json,
)


class MockAsyncIterator:
    """Helper to create async iterators for testing."""

    def __init__(self, items: list[any]):
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
        # Mock SSE events
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data='{"choices":[{"delta":{"content":" world"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

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
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")

        mock_event_source = MagicMock()
        mock_event_source.response = mock_response

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

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
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

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
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="{invalid json}"),
            ServerSentEvent(data='{"choices":[{"delta":{"content":" world"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                # Should skip malformed chunk but continue streaming
                assert chunks == ["Hello", " world"]


class TestStreamOpenRouterJson:
    """Tests for stream_openrouter_json function."""

    @pytest.mark.asyncio
    async def test_stream_openrouter_json_success(self):
        """Test successful JSON mode streaming."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"{\\"result\\":"}}]}'),
            ServerSentEvent(data='{"choices":[{"delta":{"content":" \\"success\\"}"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

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
