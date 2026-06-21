"""Typed errors for the counter domain types."""

from __future__ import annotations


class CounterError(Exception):
    """Base class for every counter-domain error."""


class InvalidCounterKeyError(CounterError, ValueError):
    """A counter key did not match the namespaced ``domain.action`` shape.

    A :class:`~src.counter.types.key.CounterKey` is the package's self-owned SSOT
    term: lowercase dotted segments, non-empty. An invalid key is rejected at
    construction so a malformed identity is unrepresentable rather than caught
    later — the same discipline ``Money`` uses to reject ``float``.
    """


class NegativeCountError(CounterError, ValueError):
    """A :class:`~src.counter.types.count.Count` was given a negative tally.

    A count is a *non-negative* tally; negativity is meaningless for "how many
    times did X happen", so it cannot be constructed.
    """
