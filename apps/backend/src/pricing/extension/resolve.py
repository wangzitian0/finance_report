"""``resolve`` — the core domain service (#1610 ruling 1): pick one value from many.

Pure: it takes the candidate observations as an argument rather than fetching
them itself, so it needs no repository, no database, and is trivially unit
tested. The orchestration that calls ``repository.candidates()`` and then
``resolve()`` lives in ``extension/`` (a later commit).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import date

from src.pricing.base.errors import NoObservationError
from src.pricing.base.observation import Authority, PriceObservation
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


def resolve_series(
    subject: PriceableSubject,
    as_of_dates: Sequence[date],
    policy: ResolutionPolicy,
    candidates: list[PriceObservation],
) -> dict[date, PriceObservation]:
    """Return ``resolve(subject, d, policy, candidates)`` for each date ``d`` that has a winner.

    A date without an eligible candidate is absent from the result. The result
    is equal to one ``resolve`` call per date, but each call reads a short list:
    per authority, the candidates on the latest ``as_of`` on or before the date.
    The winner is always in that list. ``resolve`` ranks authority first and
    ``as_of`` second, and a later ``as_of`` is never older than ``max_age_days``
    when an earlier one is not.
    """
    by_authority: dict[Authority, list[PriceObservation]] = {}
    for candidate in candidates:
        if candidate.subject == subject:
            by_authority.setdefault(candidate.authority, []).append(candidate)
    groups: list[tuple[list[PriceObservation], list[date]]] = []
    for group in by_authority.values():
        group.sort(key=lambda c: c.as_of)
        groups.append((group, [c.as_of for c in group]))

    resolved: dict[date, PriceObservation] = {}
    for as_of in as_of_dates:
        shortlist: list[PriceObservation] = []
        for group, group_dates in groups:
            end = bisect_right(group_dates, as_of)
            if end:
                shortlist.extend(group[bisect_left(group_dates, group_dates[end - 1]) : end])
        try:
            resolved[as_of] = resolve(subject, as_of, policy, shortlist)
        except NoObservationError:
            continue
    return resolved
