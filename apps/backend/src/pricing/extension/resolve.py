"""``resolve`` — the core domain service (#1610 ruling 1): pick one value from many.

Pure: it takes the candidate observations as an argument rather than fetching
them itself, so it needs no repository, no database, and is trivially unit
tested. The orchestration that calls ``repository.candidates()`` and then
``resolve()`` lives in ``extension/`` (a later commit).
"""

from __future__ import annotations

from datetime import date

from src.pricing.base.errors import NoObservationError
from src.pricing.base.observation import PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject


def resolve(
    subject: PriceableSubject,
    as_of: date,
    policy: ResolutionPolicy,
    candidates: list[PriceObservation],
) -> PriceObservation:
    """Pick the single observation ``candidates`` resolves to for ``subject``/``as_of``.

    Eligible candidates: same ``subject``, ``as_of`` on or before the
    requested date, ``authority >= policy.min_authority``, and — when
    ``policy.max_age_days`` is set — within that many days of the requested
    date. Among eligible candidates the winner is the one with, in order:
    highest authority, then latest ``as_of``, then latest ``observed_at``,
    then highest ``id`` — total-ordered even if two observations otherwise
    tie (``observed_at`` is wall-clock time and can genuinely collide, e.g.
    two crawler ticks recorded in the same batch); ``id`` carries no meaning
    of its own, it exists purely so ``resolve()`` never depends on the
    candidate list's incoming order.

    Raises :class:`NoObservationError` when no candidate is eligible.
    """
    eligible = [
        c
        for c in candidates
        if c.subject == subject
        and c.as_of <= as_of
        and c.authority >= policy.min_authority
        and (policy.max_age_days is None or (as_of - c.as_of).days <= policy.max_age_days)
    ]
    if not eligible:
        raise NoObservationError(f"no eligible observation for {subject.kind}:{subject.key} as of {as_of}")
    return max(eligible, key=lambda c: (c.authority, c.as_of, c.observed_at, c.id))
