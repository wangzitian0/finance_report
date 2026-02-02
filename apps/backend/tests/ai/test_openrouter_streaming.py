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


class TestStreamApiKeyFallback:
    """Tests for API key fallback to settings."""

    @pytest.mark.asyncio
    async def test_stream_uses_settings_api_key_when_not_provided(self):
        """Test that stream uses settings.openrouter_api_key when api_key not provided."""
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

                with patch("src.services.openrouter_streaming.settings") as mock_settings:
                    mock_settings.openrouter_api_key = "settings-api-key"
                    mock_settings.openrouter_base_url = "https://test.openrouter.ai/api/v1"

                    chunks = []
                    async for chunk in stream_openrouter_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                    ):
                        chunks.append(chunk)

                    assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_stream_raises_when_no_api_key_available(self):
        """Test that stream raises error when no API key in settings or params."""
        with patch("src.services.openrouter_streaming.settings") as mock_settings:
            mock_settings.openrouter_api_key = None

            with pytest.raises(OpenRouterStreamError) as exc_info:
                async for _ in stream_openrouter_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                ):
                    pass

            assert "API key not configured" in str(exc_info.value)
            assert exc_info.value.retryable is False


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
        mock_response.headers = {"content-type": "text/plain"}

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


class TestStreamErrorHandling:
    """Tests for OpenRouter stream error handling."""

    @pytest.mark.asyncio
    async def test_stream_handles_mid_stream_error(self):
        """Test handling of mid-stream error in response body."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data='{"error":{"message":"Model overloaded","code":"server_error"}}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with pytest.raises(OpenRouterStreamError) as exc_info:
                    chunks = []
                    async for chunk in stream_openrouter_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                assert "Mid-stream error" in str(exc_info.value)
                assert exc_info.value.retryable is True  # server_error is retryable

    @pytest.mark.asyncio
    async def test_stream_handles_mid_stream_error_not_retryable(self):
        """Test mid-stream error with non-retryable code."""
        events = [
            ServerSentEvent(data='{"error":{"message":"Invalid request","code":"invalid_request"}}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

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

                assert exc_info.value.retryable is False  # invalid_request is not retryable

    @pytest.mark.asyncio
    async def test_stream_handles_finish_reason_error(self):
        """Test handling of finish_reason: error."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"},"finish_reason":"error"}]}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

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

                assert "terminated with error" in str(exc_info.value)
                assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_stream_ignores_sse_comments(self):
        """Test that SSE comments (starting with :) are ignored."""
        events = [
            ServerSentEvent(data=": OPENROUTER PROCESSING"),
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="   "),  # Empty/whitespace data
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

                # Should only get actual content, not comments
                assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_logs_warning_chunks_but_no_content(self):
        """Test warning is logged when chunks received but no content."""
        # Chunks with empty choices (no content extracted)
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{}}]}'),
            ServerSentEvent(data='{"choices":[{"delta":{"role":"assistant"}}]}'),
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

                with patch("src.services.openrouter_streaming.logger") as mock_logger:
                    chunks = []
                    async for chunk in stream_openrouter_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                    assert chunks == []  # No content extracted

                    # Verify warning was logged about empty content
                    warning_calls = [call for call in mock_logger.warning.call_args_list]
                    assert any("no content" in str(call).lower() for call in warning_calls)

    @pytest.mark.asyncio
    async def test_stream_logs_warning_no_chunks(self):
        """Test warning is logged when no chunks received at all."""
        events = [
            ServerSentEvent(data="[DONE]"),  # Immediately done, no chunks
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.openrouter_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.openrouter_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with patch("src.services.openrouter_streaming.logger") as mock_logger:
                    chunks = []
                    async for chunk in stream_openrouter_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                    assert chunks == []

                    # Verify warning was logged about no chunks
                    warning_calls = [call for call in mock_logger.warning.call_args_list]
                    assert any("no chunks" in str(call).lower() for call in warning_calls)

    @pytest.mark.asyncio
    async def test_stream_skips_empty_choices(self):
        """Test that events with empty choices are skipped."""
        events = [
            ServerSentEvent(data='{"choices":[]}'),  # Empty choices
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="{}"),  # No choices key
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
