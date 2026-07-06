"""Write-side domain services: recording manual valuations and market-data overrides.

Both dissolve ``ManualValuationSnapshot``/``MarketDataOverride`` into the
unified observation model as they're written (#1610 rulings 2 and 4 apply
symmetrically to the write path); reading them back out uniformly alongside
the crawler sources is ``SqlObservationRepository``'s job
(``extension/repository.py``).

Presentation classification (``liquidity_class``, notes, reminders) is an
asset-lifecycle/UI concern pricing does not own — callers supply it; pricing
only persists the observation fact and its versioning.

Both also publish ``PriceObserved`` through the platform outbox, in the same
``db`` session as the write (the ``counter.record_increment`` pattern): the
outbox row is enqueued, never dispatched, here — the caller's own commit is
what makes the event atomic with the state change, and the relay delivers it
post-commit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import to_money
from src.audit.money.currency import normalize_currency_code
from src.models.layer3 import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.models.portfolio import MarketDataOverride, PriceSource
from src.platform import OutboxEventBus
from src.pricing.base.events import PriceObserved
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.subject import PriceableSubject

#: The ``source_pkg`` tag every pricing event carries in the shared outbox.
SOURCE_PKG = "pricing"


async def record_manual_valuation(
    db: AsyncSession,
    user_id: UUID,
    *,
    component_type: ManualValuationComponentType,
    liquidity_class: ManualValuationLiquidityClass,
    as_of: date,
    value: Decimal,
    currency: str,
    source: str,
    valuation_basis: ManualValuationBasis | None = None,
    notes: str | None = None,
) -> PriceObservation:
    """Record a manual valuation as an append-only versioned fact (Axiom A).

    If a current version already exists for
    ``(user_id, component_type, source, as_of)``, this appends a new version
    and supersedes the prior one instead of overwriting it — the same
    3-flush ordered hand-off ``AssetService.create_valuation_snapshot``
    (``services/assets.py``) uses, valid under both the self-referencing FK
    and the partial-unique index (never two current heads at once).
    """
    normalized_currency = normalize_currency_code(currency)
    head = (
        await db.execute(
            select(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.component_type == component_type)
            .where(ManualValuationSnapshot.source == source)
            .where(ManualValuationSnapshot.as_of_date == as_of)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()

    snapshot = ManualValuationSnapshot(
        id=uuid4(),
        user_id=user_id,
        component_type=component_type,
        liquidity_class=liquidity_class,
        as_of_date=as_of,
        value=to_money(value),
        currency=normalized_currency,
        source=source,
        valuation_basis=valuation_basis,
        notes=notes,
        version=(head.version + 1) if head is not None else 1,
        # Park under the prior head so there is never a moment with two
        # current heads for the same key (checked per statement).
        superseded_by_id=head.id if head is not None else None,
    )
    db.add(snapshot)
    await db.flush()
    if head is not None:
        head.superseded_by_id = snapshot.id
        await db.flush()
        snapshot.superseded_by_id = None
        await db.flush()
    await db.refresh(snapshot)

    subject = PriceableSubject.component(component_type)
    bus = OutboxEventBus(db, source_pkg=SOURCE_PKG)
    bus.publish(
        PriceObserved.create(
            observation_id=snapshot.id,
            subject=subject,
            as_of=snapshot.as_of_date,
            source=ObservationSource.MANUAL,
            occurred_at=snapshot.created_at,
        )
    )

    return PriceObservation(
        id=snapshot.id,
        subject=subject,
        value=snapshot.value,
        as_of=snapshot.as_of_date,
        observed_at=snapshot.created_at,
        source=ObservationSource.MANUAL,
        authority=Authority.MANUAL,
        currency=snapshot.currency,
    )


async def record_override(
    db: AsyncSession,
    user_id: UUID,
    *,
    asset_identifier: str,
    as_of: date,
    price: Decimal,
    currency: str,
) -> PriceObservation:
    """Record a market-data override — a standalone high-authority observation.

    Per #1610 ruling 2, ``MarketDataOverride`` carries no version chain of
    its own (unlike ``ManualValuationSnapshot``): every override is simply a
    new row, and ``resolve()``'s ``(authority, as_of, observed_at)``
    tie-break already picks the most recently recorded override for a given
    ``as_of`` — "last write wins" falls out of ``resolve()``, not a second
    supersede mechanism.
    """
    normalized_currency = normalize_currency_code(currency)
    override = MarketDataOverride(
        user_id=user_id,
        asset_identifier=asset_identifier,
        price_date=as_of,
        price=to_money(price),
        currency=normalized_currency,
        source=PriceSource.MANUAL,
    )
    db.add(override)
    await db.flush()
    await db.refresh(override)

    subject = PriceableSubject.security(asset_identifier)
    bus = OutboxEventBus(db, source_pkg=SOURCE_PKG)
    bus.publish(
        PriceObserved.create(
            observation_id=override.id,
            subject=subject,
            as_of=override.price_date,
            source=ObservationSource.OVERRIDE,
            occurred_at=override.created_at,
        )
    )

    return PriceObservation(
        id=override.id,
        subject=subject,
        value=override.price,
        as_of=override.price_date,
        observed_at=override.created_at,
        source=ObservationSource.OVERRIDE,
        authority=Authority.OVERRIDE,
        currency=override.currency,
    )
