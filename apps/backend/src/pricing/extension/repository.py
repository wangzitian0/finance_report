"""``SqlObservationRepository`` — the ``ObservationRepository`` adapter (mechanism B).

Queries the 4 legacy tables during the transition (``FxRate`` / ``StockPrice``
for the global crawler sources; ``MarketDataOverride`` / ``ManualValuationSnapshot``
for the user-scoped manual sources) and translates each row into a
``PriceObservation``, so ``resolve()`` sees one uniform candidate list
regardless of which table a fact actually lives in today. The unification into
one physical table is later, package-internal work (#1610 DoD) — this adapter
is schema-preserving on purpose, so it can land ahead of that migration.

Per ``ObservationRepository``'s contract, ``user_id=None`` returns only the
global sources: the ``MarketDataOverride``/``ManualValuationSnapshot`` queries
below are gated on ``user_id is not None`` and always filter by it — there is
no code path that returns one user's manual data to a caller who didn't ask
for that user.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer3 import ManualValuationSnapshot
from src.models.market_data import FxRate, StockPrice
from src.models.portfolio import MarketDataOverride
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.subject import PriceableSubject, SubjectKind


class SqlObservationRepository:
    """``AsyncSession``-backed :class:`~src.pricing.base.repository.ObservationRepository`."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def candidates(
        self, subject: PriceableSubject, as_of: date, user_id: UUID | None = None
    ) -> list[PriceObservation]:
        if subject.kind is SubjectKind.CURRENCY_PAIR:
            return await self._fx_candidates(subject, as_of)
        if subject.kind is SubjectKind.SECURITY:
            return await self._security_candidates(subject, as_of, user_id)
        return await self._component_candidates(subject, as_of, user_id)

    async def _fx_candidates(self, subject: PriceableSubject, as_of: date) -> list[PriceObservation]:
        base, quote = subject.key.split("/")
        rows = (
            (
                await self._db.execute(
                    select(FxRate)
                    .where(FxRate.base_currency == base)
                    .where(FxRate.quote_currency == quote)
                    .where(FxRate.rate_date <= as_of)
                )
            )
            .scalars()
            .all()
        )
        return [
            PriceObservation(
                subject=subject,
                value=row.rate,
                as_of=row.rate_date,
                observed_at=row.created_at,
                source=ObservationSource.CRAWLER,
                authority=Authority.CRAWLER,
                currency=None,
            )
            for row in rows
        ]

    async def _security_candidates(
        self, subject: PriceableSubject, as_of: date, user_id: UUID | None
    ) -> list[PriceObservation]:
        price_rows = (
            (
                await self._db.execute(
                    select(StockPrice).where(StockPrice.symbol == subject.key).where(StockPrice.price_date <= as_of)
                )
            )
            .scalars()
            .all()
        )
        observations = [
            PriceObservation(
                subject=subject,
                value=row.price,
                as_of=row.price_date,
                observed_at=row.created_at,
                source=ObservationSource.CRAWLER,
                authority=Authority.CRAWLER,
                currency=row.currency,
            )
            for row in price_rows
        ]
        if user_id is not None:
            override_rows = (
                (
                    await self._db.execute(
                        select(MarketDataOverride)
                        .where(MarketDataOverride.asset_identifier == subject.key)
                        .where(MarketDataOverride.price_date <= as_of)
                        .where(MarketDataOverride.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            observations.extend(
                PriceObservation(
                    subject=subject,
                    value=row.price,
                    as_of=row.price_date,
                    observed_at=row.created_at,
                    source=ObservationSource.OVERRIDE,
                    authority=Authority.OVERRIDE,
                    currency=row.currency,
                )
                for row in override_rows
            )
        return observations

    async def _component_candidates(
        self, subject: PriceableSubject, as_of: date, user_id: UUID | None
    ) -> list[PriceObservation]:
        if user_id is None:
            # Manual valuations are inherently user-owned; there is no global
            # component observation to return.
            return []
        rows = (
            (
                await self._db.execute(
                    select(ManualValuationSnapshot)
                    .where(ManualValuationSnapshot.component_type == subject.key)
                    .where(ManualValuationSnapshot.as_of_date <= as_of)
                    .where(ManualValuationSnapshot.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        # Both the current head and superseded history rows are returned
        # (not filtered to superseded_by_id IS NULL): resolve()'s
        # (authority, as_of, observed_at) tie-break already picks the latest
        # observed_at among equal-authority/equal-as_of candidates, which is
        # exactly the version chain's head — the bitemporal split (#1610
        # ruling 3) falls out of resolve() rather than a second mechanism.
        return [
            PriceObservation(
                subject=subject,
                value=row.value,
                as_of=row.as_of_date,
                observed_at=row.created_at,
                source=ObservationSource.MANUAL,
                authority=Authority.MANUAL,
                currency=row.currency,
            )
            for row in rows
        ]
