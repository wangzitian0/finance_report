"""The error hierarchy of the model entry point and the token estimate of the chat history."""

from __future__ import annotations

from src.llm import LLMConfigError, LLMError, ModelCallFailed, ModelFailureKind, estimate_tokens


def test_the_errors_of_a_model_call_are_llm_errors_with_a_retry_flag() -> None:
    failed = ModelCallFailed(ModelFailureKind.RATE_LIMIT, "ModelRateLimitError (http=429)")
    assert (isinstance(failed, LLMError), failed.retryable, issubclass(LLMConfigError, LLMError)) == (True, True, True)
    assert LLMConfigError("no provider is configured").retryable is False


def test_estimate_tokens_is_four_characters_for_a_token_and_zero_for_an_empty_text() -> None:
    assert (estimate_tokens(""), estimate_tokens("abc"), estimate_tokens("abcd"), estimate_tokens("a" * 400)) == (0, 1, 1, 100)
