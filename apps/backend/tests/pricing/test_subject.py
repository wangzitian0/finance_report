"""``PriceableSubject``/``ResolutionPolicy``/``PriceObservation`` construction — tested directly.

These are exercised indirectly everywhere else in ``tests/pricing/`` (every FX
and repository test builds one), but the identity/validation/dual-listing
rules (#1610 rulings 2 and 6) have no dedicated proof of their own until now.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.pricing.base.errors import InvalidObservationError, InvalidSubjectError
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject, SubjectKind


def test_currency_pair_builds_a_slash_separated_upper_cased_key():
    subject = PriceableSubject.currency_pair("usd", "sgd")
    assert subject.kind is SubjectKind.CURRENCY_PAIR
    assert subject.key == "USD/SGD"


def test_currency_pair_rejects_a_malformed_key():
    with pytest.raises(InvalidSubjectError):
        PriceableSubject(SubjectKind.CURRENCY_PAIR, "USDSGD")


def test_currency_pair_rejects_non_alpha_segments():
    with pytest.raises(InvalidSubjectError):
        PriceableSubject(SubjectKind.CURRENCY_PAIR, "US1/SGD")


def test_security_and_component_build_their_kind_with_the_key_as_is():
    assert PriceableSubject.security("AAPL") == PriceableSubject(SubjectKind.SECURITY, "AAPL")
    assert PriceableSubject.component("property") == PriceableSubject(SubjectKind.COMPONENT, "property")


def test_empty_key_is_rejected_for_any_kind():
    with pytest.raises(InvalidSubjectError):
        PriceableSubject.security("")
    with pytest.raises(InvalidSubjectError):
        PriceableSubject.component("   ")


def test_dual_listings_are_distinct_subjects_not_collapsed():
    """Ruling 6: the same equity under two symbols is NOT unified in this cut."""
    primary = PriceableSubject.security("9988.HK")
    secondary = PriceableSubject.security("BABA")
    assert primary != secondary


def test_subjects_with_the_same_kind_and_key_are_equal():
    assert PriceableSubject.security("AAPL") == PriceableSubject.security("AAPL")


def test_resolution_policy_defaults_to_unbounded_age_and_lowest_authority():
    policy = ResolutionPolicy()
    assert policy.max_age_days is None
    assert policy.min_authority is Authority.CRAWLER


def test_authority_ordering_places_override_above_manual_above_statement_above_crawler():
    assert Authority.OVERRIDE > Authority.MANUAL > Authority.STATEMENT > Authority.CRAWLER


def test_price_observation_rejects_a_float_value():
    with pytest.raises(InvalidObservationError):
        PriceObservation(
            subject=PriceableSubject.security("AAPL"),
            value=1.5,
            as_of=date(2026, 6, 1),
            observed_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
            source=ObservationSource.CRAWLER,
            authority=Authority.CRAWLER,
        )


def test_price_observation_rejects_a_non_positive_value():
    with pytest.raises(InvalidObservationError):
        PriceObservation(
            subject=PriceableSubject.security("AAPL"),
            value=Decimal("0"),
            as_of=date(2026, 6, 1),
            observed_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
            source=ObservationSource.CRAWLER,
            authority=Authority.CRAWLER,
        )


def test_price_observation_rejects_a_non_finite_value():
    with pytest.raises(InvalidObservationError):
        PriceObservation(
            subject=PriceableSubject.security("AAPL"),
            value=Decimal("NaN"),
            as_of=date(2026, 6, 1),
            observed_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
            source=ObservationSource.CRAWLER,
            authority=Authority.CRAWLER,
        )


def test_price_observation_rejects_a_naive_observed_at():
    """A naive datetime would raise TypeError the moment resolve() compares
    it against an aware one (e.g. a DB-sourced observation)."""
    with pytest.raises(InvalidObservationError):
        PriceObservation(
            subject=PriceableSubject.security("AAPL"),
            value=Decimal("100"),
            as_of=date(2026, 6, 1),
            observed_at=datetime(2026, 6, 1, 12),  # no tzinfo
            source=ObservationSource.CRAWLER,
            authority=Authority.CRAWLER,
        )


def test_price_observation_allows_observed_at_later_than_as_of():
    """A backfilled observation — ruling 3, not an error."""
    observation = PriceObservation(
        subject=PriceableSubject.security("AAPL"),
        value=Decimal("100"),
        as_of=date(2026, 1, 1),
        observed_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
        source=ObservationSource.STATEMENT,
        authority=Authority.STATEMENT,
    )
    assert observation.as_of < observation.observed_at.date()
