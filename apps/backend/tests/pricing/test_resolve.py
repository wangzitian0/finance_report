from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from src.pricing.base.errors import NoObservationError
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.resolve import resolve, resolve_series

_SUBJ, _OTHER = PriceableSubject.security("AAPL"), PriceableSubject.security("MSFT")


def _obs(
    value: str,
    as_of: date,
    observed_at: datetime,
    source: ObservationSource = ObservationSource.CRAWLER,
    authority: Authority = Authority.CRAWLER,
    subject: PriceableSubject = _SUBJ,
    id: UUID | None = None,
) -> PriceObservation:
    ts = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
    return PriceObservation(
        subject=subject,
        value=Decimal(value),
        as_of=as_of,
        observed_at=ts,
        source=source,
        authority=authority,
        currency="USD",
        **({"id": id} if id else {}),
    )


def test_resolve_selection_rules_and_tie_breakers():
    d1, d15 = date(2026, 6, 1), date(2026, 6, 15)
    c = _obs("100", d1, datetime(2026, 6, 1, 12))
    assert resolve(_SUBJ, d1, ResolutionPolicy(), [c]) is c
    for policy, cands in (
        (ResolutionPolicy(), [_obs("200", d1, datetime(2026, 6, 1, 12), subject=_OTHER)]),
        (ResolutionPolicy(), [_obs("100", d15, datetime(2026, 6, 15, 12))]),
        (ResolutionPolicy(min_authority=Authority.MANUAL), [_obs("100", d1, datetime(2026, 6, 1, 12))]),
        (ResolutionPolicy(max_age_days=30), [_obs("90", date(2026, 1, 1), datetime(2026, 1, 1, 12))]),
        (ResolutionPolicy(), []),
    ):
        with pytest.raises(NoObservationError):
            resolve(_SUBJ, d1, policy, cands)

    manual = _obs("105", d1, datetime(2026, 6, 1, 12), ObservationSource.MANUAL, Authority.MANUAL)
    within = _obs("90", d1 - timedelta(days=10), datetime(2026, 5, 22, 12))
    ov = _obs("999", date(2026, 5, 1), datetime(2026, 5, 1, 9), ObservationSource.OVERRIDE, Authority.OVERRIDE)
    later = _obs("110", d1, datetime(2026, 5, 2, 9))
    backfilled = _obs("103", d1, datetime(2026, 6, 10, 9))
    hi_id = _obs("101", d1, datetime(2026, 6, 1, 9, tzinfo=UTC), id=UUID(int=2))
    lo_id = _obs("100", d1, datetime(2026, 6, 1, 9, tzinfo=UTC), id=UUID(int=1))
    assert (
        resolve(_SUBJ, d1, ResolutionPolicy(min_authority=Authority.MANUAL), [manual]) is manual,
        resolve(_SUBJ, d1, ResolutionPolicy(max_age_days=30), [within]) is within,
        resolve(_SUBJ, d1, ResolutionPolicy(), [c, ov]) is ov,
        resolve(_SUBJ, d1, ResolutionPolicy(), [_obs("100", date(2026, 5, 1), datetime(2026, 5, 1, 9)), later])
        is later,
        resolve(_SUBJ, d1, ResolutionPolicy(), [_obs("100", d1, datetime(2026, 6, 1, 9)), backfilled]) is backfilled,
        resolve(_SUBJ, d1, ResolutionPolicy(), [lo_id, hi_id]) is hi_id,
        resolve(_SUBJ, d1, ResolutionPolicy(), [hi_id, lo_id]) is hi_id,
    ) == (True, True, True, True, True, True, True)


@pytest.mark.parametrize(
    "policy",
    [
        ResolutionPolicy(),
        ResolutionPolicy(max_age_days=4),
        ResolutionPolicy(min_authority=Authority.STATEMENT),
        ResolutionPolicy(max_age_days=2, min_authority=Authority.MANUAL),
    ],
)
def test_AC_pricing_fx_4_resolve_series_equals_one_resolve_per_date(policy: ResolutionPolicy):
    rng, start = random.Random(2583), date(2026, 6, 1)
    cands = [
        _obs(
            str(rng.randint(90, 110)),
            start + timedelta(days=rng.randint(0, 40)),
            datetime(2026, 5, 1, tzinfo=UTC) + timedelta(hours=rng.randint(0, 3)),
            authority=rng.choice(list(Authority)),
            subject=rng.choice([_SUBJ, _SUBJ, _OTHER]),
            id=UUID(int=i + 1),
        )
        for i in range(300)
    ]
    dates = [start + timedelta(days=o) for o in range(-3, 46)]
    expected = {}
    for d in dates:
        try:
            expected[d] = resolve(_SUBJ, d, policy, cands)
        except NoObservationError:
            continue
    series = resolve_series(_SUBJ, dates, policy, cands)
    assert (series == expected, dates[0] not in series, len(series) > 30) == (True, True, True)
