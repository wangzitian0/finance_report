"""Typed error hierarchy for the pricing package."""

from __future__ import annotations


class PricingError(Exception):
    """Base error for the pricing package."""


class InvalidSubjectError(PricingError):
    """A ``PriceableSubject`` was constructed with an inconsistent key shape."""


class InvalidObservationError(PricingError):
    """A ``PriceObservation`` was constructed with an invalid value or timestamp."""


class NoObservationError(PricingError):
    """``resolve`` found no observation for a subject as of a given date."""
