"""Token estimate of a chat message (``AIAdvisorService`` stores ``tokens_in`` and ``tokens_out``)."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Return a rough token count: about 4 characters for a token, and 0 for an empty text.

    The count is an estimate by design: exact counts and prices are out of scope.
    """
    return max(1, len(text) // 4) if text else 0
