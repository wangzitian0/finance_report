"""``resolve()`` — the core domain service (#1610 ruling 1), tested directly.

Every other pricing test exercises ``resolve()`` only indirectly through the
FX wrappers or the repository adapter. These tests pin down its own contract
in isolation: subject/as_of filtering, ``ResolutionPolicy`` (``min_authority``/
``max_age_days``), and the deterministic tie-break — with plain in-memory
``PriceObservation`` fixtures, no database.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from src.pricing.base.errors import NoObservationError
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject

SUBJECT = PriceableSubject.security("AAPL")
OTHER_SUBJECT = PriceableSubject.security("MSFT")


def _observation(
    *,
    value: str,
    as_of: date,
    observed_at: datetime,
    source: ObservationSource = ObservationSource.CRAWLER,
    authority: Authority = Authority.CRAWLER,
    subject: PriceableSubject = SUBJECT,
    id: UUID | None = None,
) -> PriceObservation:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    kwargs = {"id": id} if id is not None else {}
    return PriceObservation(
        subject=subject,
        value=Decimal(value),
        as_of=as_of,
        observed_at=observed_at,
        source=source,
        authority=authority,
        currency="USD",
        **kwargs,
    )


def test_picks_the_only_eligible_candidate():
    from src.pricing.extension.resolve import resolve

    candidate = _observation(value="100", as_of=date(2026, 6, 1), observed_at=datetime(2026, 6, 1, 12))
    result = resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [candidate])
    assert result is candidate


def test_ignores_candidates_for_a_different_subject():
    from src.pricing.extension.resolve import resolve

    other = _observation(
        value="200", as_of=date(2026, 6, 1), observed_at=datetime(2026, 6, 1, 12), subject=OTHER_SUBJECT
    )
    with pytest.raises(NoObservationError):
        resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [other])


def test_ignores_candidates_dated_after_as_of():
    from src.pricing.extension.resolve import resolve

    future = _observation(value="100", as_of=date(2026, 6, 15), observed_at=datetime(2026, 6, 15, 12))
    with pytest.raises(NoObservationError):
        resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [future])


def test_min_authority_excludes_lower_authority_candidates():
    from src.pricing.extension.resolve import resolve

    crawler_only = _observation(
        value="100",
        as_of=date(2026, 6, 1),
        observed_at=datetime(2026, 6, 1, 12),
        source=ObservationSource.CRAWLER,
        authority=Authority.CRAWLER,
    )
    policy = ResolutionPolicy(min_authority=Authority.MANUAL)
    with pytest.raises(NoObservationError):
        resolve(SUBJECT, date(2026, 6, 1), policy, [crawler_only])


def test_min_authority_admits_the_configured_floor_and_above():
    from src.pricing.extension.resolve import resolve

    manual = _observation(
        value="105",
        as_of=date(2026, 6, 1),
        observed_at=datetime(2026, 6, 1, 12),
        source=ObservationSource.MANUAL,
        authority=Authority.MANUAL,
    )
    policy = ResolutionPolicy(min_authority=Authority.MANUAL)
    result = resolve(SUBJECT, date(2026, 6, 1), policy, [manual])
    assert result is manual


def test_max_age_days_excludes_stale_candidates():
    from src.pricing.extension.resolve import resolve

    stale = _observation(value="90", as_of=date(2026, 1, 1), observed_at=datetime(2026, 1, 1, 12))
    policy = ResolutionPolicy(max_age_days=30)
    with pytest.raises(NoObservationError):
        resolve(SUBJECT, date(2026, 6, 1), policy, [stale])


def test_max_age_days_admits_a_candidate_within_the_window():
    from src.pricing.extension.resolve import resolve

    as_of = date(2026, 6, 1)
    within_window = _observation(value="90", as_of=as_of - timedelta(days=10), observed_at=datetime(2026, 5, 22, 12))
    policy = ResolutionPolicy(max_age_days=30)
    result = resolve(SUBJECT, as_of, policy, [within_window])
    assert result is within_window


def test_tie_break_prefers_higher_authority_over_a_later_as_of():
    from src.pricing.extension.resolve import resolve

    crawler_latest = _observation(
        value="100",
        as_of=date(2026, 6, 1),
        observed_at=datetime(2026, 6, 1, 9),
        source=ObservationSource.CRAWLER,
        authority=Authority.CRAWLER,
    )
    override_older = _observation(
        value="999",
        as_of=date(2026, 5, 1),
        observed_at=datetime(2026, 5, 1, 9),
        source=ObservationSource.OVERRIDE,
        authority=Authority.OVERRIDE,
    )
    result = resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [crawler_latest, override_older])
    assert result is override_older


def test_tie_break_prefers_later_as_of_when_authority_is_equal():
    from src.pricing.extension.resolve import resolve

    earlier = _observation(value="100", as_of=date(2026, 5, 1), observed_at=datetime(2026, 5, 1, 9))
    later = _observation(value="110", as_of=date(2026, 6, 1), observed_at=datetime(2026, 5, 2, 9))
    result = resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [earlier, later])
    assert result is later


def test_tie_break_prefers_later_observed_at_when_authority_and_as_of_are_equal():
    """A late backfill for the same ``as_of`` wins — the bitemporal correction path."""
    from src.pricing.extension.resolve import resolve

    original = _observation(value="100", as_of=date(2026, 6, 1), observed_at=datetime(2026, 6, 1, 9))
    backfilled_correction = _observation(value="103", as_of=date(2026, 6, 1), observed_at=datetime(2026, 6, 10, 9))
    result = resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [original, backfilled_correction])
    assert result is backfilled_correction


def test_raises_no_observation_error_for_an_empty_candidate_list():
    from src.pricing.extension.resolve import resolve

    with pytest.raises(NoObservationError):
        resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [])


def test_tie_break_falls_back_to_id_when_authority_as_of_and_observed_at_all_collide():
    """A genuine timestamp collision (e.g. two crawler ticks in one batch) must
    still resolve deterministically — never depend on the candidates list's
    incoming order (Copilot review, PR #1617)."""
    from src.pricing.extension.resolve import resolve

    same_moment = datetime(2026, 6, 1, 9, tzinfo=UTC)
    lower_id = _observation(value="100", as_of=date(2026, 6, 1), observed_at=same_moment, id=UUID(int=1))
    higher_id = _observation(value="101", as_of=date(2026, 6, 1), observed_at=same_moment, id=UUID(int=2))

    # Order must not matter — try both permutations.
    assert resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [lower_id, higher_id]) is higher_id
    assert resolve(SUBJECT, date(2026, 6, 1), ResolutionPolicy(), [higher_id, lower_id]) is higher_id
