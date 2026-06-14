"""Tests for the provider-neutral AI streaming utilities."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx_sse import ServerSentEvent

from src.services.ai_streaming import (
    AIStreamError,
    _stream_ai_base,
    accumulate_stream,
    stream_ai_chat,
    stream_ai_json,
)


class MockAsyncIterator:
    """Helper to create async iterators for testing."""

    def __init__(self, items: list[Any]):
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

    async def test_stream_uses_settings_api_key_when_not_provided(self):
        """AC6.7.3: Stream uses settings API key when not provided."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with patch("src.services.ai_streaming.settings") as mock_settings:
                    mock_settings.ai_api_key = "settings-api-key"
                    mock_settings.ai_base_url = "https://test.openrouter.ai/api/v1"

                    chunks = []
                    async for chunk in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                    ):
                        chunks.append(chunk)

                    assert chunks == ["Hello"]

    async def test_stream_raises_when_no_api_key_available(self):
        """AC6.7.3: Stream raises error when no API key available."""
        with patch("src.services.ai_streaming.settings") as mock_settings:
            mock_settings.ai_api_key = None

            with pytest.raises(AIStreamError) as exc_info:
                async for _ in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                ):
                    pass

            assert "API key not configured" in str(exc_info.value)
            assert exc_info.value.retryable is False


class TestStreamAIChat:
    """Tests for stream_ai_chat function."""

    async def test_stream_ai_chat_success(self):
        """AC6.7.1: Successful streaming chat completion."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                assert chunks == ["Hello", " world"]

    async def test_stream_adds_openrouter_headers_for_legacy_provider(self):
        """OpenRouter provider keeps required attribution headers."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client),
            patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect,
            patch("src.services.ai_streaming.settings") as mock_settings,
        ):
            mock_settings.ai_provider = "openrouter"
            mock_settings.ai_chat_completions_path = "/chat/completions"
            mock_aconnect.return_value.__aenter__.return_value = mock_event_source

            chunks = []
            async for chunk in stream_ai_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="test-model",
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
            ):
                chunks.append(chunk)

            headers = mock_aconnect.call_args.kwargs["headers"]
            assert chunks == ["Hello"]
            assert headers["HTTP-Referer"] == "https://finance-report.local"
            assert headers["X-Title"] == "Finance Report Backend"

    async def test_stream_omits_openrouter_headers_for_zai_provider(self):
        """Provider-neutral GLM access does not send OpenRouter-only headers."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with (
            patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client),
            patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect,
            patch("src.services.ai_streaming.settings") as mock_settings,
        ):
            mock_settings.ai_provider = "zai"
            mock_settings.ai_chat_completions_path = "/chat/completions"
            mock_aconnect.return_value.__aenter__.return_value = mock_event_source

            chunks = []
            async for chunk in stream_ai_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="glm-5.1",
                api_key="test-key",
                base_url="https://api.z.ai/api/coding/paas/v4",
            ):
                chunks.append(chunk)

            headers = mock_aconnect.call_args.kwargs["headers"]
            assert chunks == ["Hello"]
            assert "HTTP-Referer" not in headers
            assert "X-Title" not in headers

    async def test_stream_ai_chat_handles_http_error(self):
        """AC6.7.2: Stream handles HTTP errors."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")
        mock_response.headers = {"content-type": "text/plain"}

        mock_event_source = MagicMock()
        mock_event_source.response = mock_response

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with pytest.raises(AIStreamError) as exc_info:
                    async for _ in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        pass

                assert "HTTP 500" in str(exc_info.value)
                assert "Internal Server Error" in str(exc_info.value)

    async def test_stream_ai_chat_handles_done_signal(self):
        """AC6.7.1: Stream stops on [DONE] signal."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data="[DONE]"),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                assert chunks == ["Hello"]
                assert "Should not appear" not in "".join(chunks)

    async def test_stream_ai_chat_handles_malformed_json(self):
        """AC6.7.1: Stream skips malformed JSON and continues."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                # Should skip malformed chunk but continue streaming
                assert chunks == ["Hello", " world"]


class TestStreamAIJson:
    """Tests for stream_ai_json function."""

    async def test_stream_ai_json_success(self):
        """AC6.7.1: Successful JSON mode streaming."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_json(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                    timeout=360.0,
                    max_tokens=8192,
                    temperature=0.0,
                    do_sample=False,
                    thinking={"type": "disabled"},
                ):
                    chunks.append(chunk)

                payload = mock_aconnect.call_args.kwargs["json"]
                assert chunks == ['{"result":', ' "success"}']
                assert payload["max_tokens"] == 8192
                assert payload["temperature"] == 0.0
                assert payload["do_sample"] is False
                assert payload["thinking"] == {"type": "disabled"}


class TestStreamErrorHandling:
    """Tests for OpenRouter stream error handling."""

    async def test_stream_handles_mid_stream_error(self):
        """AC6.7.2: Stream handles mid-stream error in response body."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"}}]}'),
            ServerSentEvent(data='{"error":{"message":"Model overloaded","code":"server_error"}}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with pytest.raises(AIStreamError) as exc_info:
                    chunks = []
                    async for chunk in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                assert "Mid-stream error" in str(exc_info.value)
                assert exc_info.value.retryable is True  # server_error is retryable

    async def test_stream_handles_mid_stream_error_not_retryable(self):
        """AC6.7.2: Mid-stream error with non-retryable code."""
        events = [
            ServerSentEvent(data='{"error":{"message":"Invalid request","code":"invalid_request"}}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with pytest.raises(AIStreamError) as exc_info:
                    async for _ in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        pass

                assert exc_info.value.retryable is False  # invalid_request is not retryable

    async def test_stream_handles_finish_reason_error(self):
        """AC6.7.2: Stream handles finish_reason error."""
        events = [
            ServerSentEvent(data='{"choices":[{"delta":{"content":"Hello"},"finish_reason":"error"}]}'),
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with pytest.raises(AIStreamError) as exc_info:
                    async for _ in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        pass

                assert "terminated with error" in str(exc_info.value)
                assert exc_info.value.retryable is True

    async def test_stream_ignores_sse_comments(self):
        """AC6.7.1: SSE comments are ignored during streaming."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                # Should only get actual content, not comments
                assert chunks == ["Hello", " world"]

    async def test_stream_logs_warning_chunks_but_no_content(self):
        """AC6.7.2: Warning logged when chunks received but no content."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with patch("src.services.ai_streaming.logger") as mock_logger:
                    chunks = []
                    async for chunk in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                    assert chunks == []  # No content extracted

                    # Verify warning was logged about empty content
                    warning_calls = [call for call in mock_logger.warning.call_args_list]
                    assert any("no content" in str(call).lower() for call in warning_calls)

    async def test_stream_logs_warning_no_chunks(self):
        """AC6.7.2: Warning logged when no chunks received."""
        events = [
            ServerSentEvent(data="[DONE]"),  # Immediately done, no chunks
        ]

        mock_event_source = MagicMock()
        mock_event_source.response.status_code = 200
        mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.__aenter__.return_value = mock_client

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                with patch("src.services.ai_streaming.logger") as mock_logger:
                    chunks = []
                    async for chunk in stream_ai_chat(
                        messages=[{"role": "user", "content": "Hi"}],
                        model="test-model",
                        api_key="test-key",
                    ):
                        chunks.append(chunk)

                    assert chunks == []

                    # Verify warning was logged about no chunks
                    warning_calls = [call for call in mock_logger.warning.call_args_list]
                    assert any("no chunks" in str(call).lower() for call in warning_calls)

    async def test_stream_skips_empty_choices(self):
        """AC6.7.1: Events with empty choices are skipped."""
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

        with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
            with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
                mock_aconnect.return_value.__aenter__.return_value = mock_event_source

                chunks = []
                async for chunk in stream_ai_chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model="test-model",
                    api_key="test-key",
                ):
                    chunks.append(chunk)

                assert chunks == ["Hello"]


class TestAccumulateStream:
    """Tests for accumulate_stream helper."""

    async def test_accumulate_stream(self):
        """AC6.7.1: Accumulate chunks into single string."""
        stream = mock_stream_generator(["Hello", " ", "world"])
        result = await accumulate_stream(stream)
        assert result == "Hello world"

    async def test_accumulate_stream_empty(self):
        """AC6.7.1: Accumulate empty stream returns empty string."""
        stream = mock_stream_generator([])
        result = await accumulate_stream(stream)
        assert result == ""


async def test_stream_base_includes_response_format_payload() -> None:
    events = [ServerSentEvent(data='{"choices":[{"delta":{"content":"{}"}}]}'), ServerSentEvent(data="[DONE]")]
    mock_event_source = MagicMock()
    mock_event_source.response.status_code = 200
    mock_event_source.aiter_sse = MagicMock(return_value=MockAsyncIterator(events))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client

    with patch("src.services.ai_streaming.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.ai_streaming.aconnect_sse") as mock_aconnect:
            mock_aconnect.return_value.__aenter__.return_value = mock_event_source

            chunks = []
            async for chunk in _stream_ai_base(
                messages=[{"role": "user", "content": "json"}],
                model="test-model",
                api_key="test-key",
                timeout=30,
                connect_timeout=10,
                response_format={"type": "json_object"},
                mode_label="test",
            ):
                chunks.append(chunk)

            assert chunks == ["{}"]
            assert mock_aconnect.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}
