from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.pricing.base.errors import InvalidObservationError, InvalidSubjectError
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject, SubjectKind


def test_subject_policy_and_observation_contracts():
    pair = PriceableSubject.currency_pair("usd", "sgd")
    policy = ResolutionPolicy()
    obs = PriceObservation(
        subject=PriceableSubject.security("AAPL"),
        value=Decimal("100"),
        as_of=date(2026, 1, 1),
        observed_at=datetime(2026, 6, 1, 12, tzinfo=UTC),
        source=ObservationSource.STATEMENT,
        authority=Authority.STATEMENT,
    )
    assert (
        (pair.kind, pair.key),
        PriceableSubject.security("AAPL"),
        PriceableSubject.component("property"),
        PriceableSubject.security("9988.HK") != PriceableSubject.security("BABA"),
        (
            policy.max_age_days,
            policy.min_authority,
            Authority.OVERRIDE > Authority.MANUAL > Authority.STATEMENT > Authority.CRAWLER,
        ),
        obs.as_of < obs.observed_at.date(),
    ) == (
        (SubjectKind.CURRENCY_PAIR, "USD/SGD"),
        PriceableSubject(SubjectKind.SECURITY, "AAPL"),
        PriceableSubject(SubjectKind.COMPONENT, "property"),
        True,
        (None, Authority.CRAWLER, True),
        True,
    )
    for args in ((SubjectKind.CURRENCY_PAIR, "USDSGD"), (SubjectKind.CURRENCY_PAIR, "US1/SGD")):
        with pytest.raises(InvalidSubjectError):
            PriceableSubject(*args)
    for fn, arg in ((PriceableSubject.security, ""), (PriceableSubject.component, "   ")):
        with pytest.raises(InvalidSubjectError):
            fn(arg)
    for val, ts in (
        (1.5, datetime(2026, 6, 1, 12, tzinfo=UTC)),
        (Decimal("0"), datetime(2026, 6, 1, 12, tzinfo=UTC)),
        (Decimal("NaN"), datetime(2026, 6, 1, 12, tzinfo=UTC)),
        (Decimal("100"), datetime(2026, 6, 1, 12)),
    ):
        with pytest.raises(InvalidObservationError):
            PriceObservation(
                subject=PriceableSubject.security("AAPL"),
                value=val,
                as_of=date(2026, 6, 1),
                observed_at=ts,
                source=ObservationSource.CRAWLER,
                authority=Authority.CRAWLER,
            )
