"""``ingest_statement_price`` — pricing's ``PriceObserved`` ingest subscriber (#1642).

The first cross-domain event consumer in this codebase; later ``data/`` sinks
copy this shape (``common/meta/migration-standard.md``, the wide-table
projection contract). The design decisions every copy inherits:

- **Consume from the payload alone.** The event carries the full observation
  copy (value/currency/user/subject); the handler never reads the producer's
  tables (boundary ruling 4: no shared transaction, no FK — the extraction
  fact id is carried as provenance).
- **Idempotent by the event's natural key.** Delivery is at-least-once
  (``OutboxRelay``), so redelivery must be a no-op: the handler dedups on
  ``observation_id`` (the upstream fact id), backed by a UNIQUE constraint on
  ``statement_price_observations.source_observation_id``.
- **Filter, don't loop.** Only ``source=statement`` events are ingested:
  pricing's own publications (manual/override) already live in pricing's
  store, and the ingest deliberately does NOT re-publish ``PriceObserved`` —
  the copy is the same fact the original event announced, and re-publishing
  would echo it forever.
- **Malformed events degrade to a loud no-op.** Retrying a deterministically
  bad payload can never succeed, and raising would wedge the relay batch
  behind the poison row — so the handler logs at error level and skips.
  (A dead-letter state is future platform work; see ``common/platform``.)

Wiring: the app composition root (``src/main.py``) owns the
``SubscriberRegistry`` and calls :func:`subscribe_price_ingest` at startup —
platform (L1) must not import pricing (L3), so the registration happens at
L4, matching the ``register_readiness_provider`` (#1676) / uploaded-document
readers (#1675 D3) inversion precedents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.observability import get_logger
from src.platform.base import DomainEvent, SubscriberRegistry
from src.pricing.base.errors import PricingError
from src.pricing.base.events import EVENT_TYPE
from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
from src.pricing.base.subject import PriceableSubject, SubjectKind
from src.pricing.orm.statement_observation import StatementPriceObservation

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _ParsedStatementPrice:
    """The validated pieces of a ``source=statement`` ``PriceObserved`` payload."""

    observation: PriceObservation
    source_observation_id: UUID
    user_id: UUID


def _parse_statement_payload(payload: dict, occurred_at: datetime) -> _ParsedStatementPrice:
    """Validate and convert the JSON payload; raises on anything malformed.

    Constructing :class:`PriceObservation` is the validation seam — it rejects
    non-``Decimal``, non-finite, and non-positive values and a naive
    ``observed_at``, so a bad copy is unrepresentable rather than checked.
    """
    user_id_raw = payload.get("user_id")
    if user_id_raw is None:
        raise ValueError("statement PriceObserved payload has no user_id")
    source_observation_id = UUID(payload["observation_id"])
    subject = PriceableSubject(SubjectKind(payload["subject_kind"]), payload["subject_key"])
    observation = PriceObservation(
        subject=subject,
        value=Decimal(payload["value"]),
        as_of=date.fromisoformat(payload["as_of"]),
        observed_at=occurred_at,
        source=ObservationSource.STATEMENT,
        authority=Authority.STATEMENT,
        currency=payload.get("currency"),
    )
    return _ParsedStatementPrice(
        observation=observation,
        source_observation_id=source_observation_id,
        user_id=UUID(user_id_raw),
    )


async def ingest_statement_price(db: AsyncSession, event: DomainEvent) -> PriceObservation | None:
    """Ingest one extraction-published ``PriceObserved`` into pricing's store.

    Returns the ingested :class:`PriceObservation`, or ``None`` when the event
    was skipped (not a statement source, a redelivered duplicate, or a
    malformed payload). Flushes but never commits — the caller (the handler
    closure in production, the test in tests) owns the transaction, and the
    transaction touches ONLY pricing's own aggregate (no cross-domain write).
    """
    payload = event.payload()
    if payload.get("source") != ObservationSource.STATEMENT.value:
        return None

    try:
        parsed = _parse_statement_payload(payload, event.occurred_at)
    except (KeyError, TypeError, ValueError, InvalidOperation, PricingError):
        logger.error(
            "Malformed statement PriceObserved payload; skipping (deterministic failure — "
            "a raise would wedge the relay batch behind this poison event)",
            observation_id=payload.get("observation_id"),
            subject_kind=payload.get("subject_kind"),
            subject_key=payload.get("subject_key"),
            exc_info=True,
        )
        return None

    # Idempotency (at-least-once delivery): dedup on the event's natural key —
    # the upstream fact id. The UNIQUE constraint on source_observation_id is
    # the hard backstop should two relay passes ever race this check.
    existing = await db.execute(
        select(StatementPriceObservation.id).where(
            StatementPriceObservation.source_observation_id == parsed.source_observation_id
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    obs = parsed.observation
    db.add(
        StatementPriceObservation(
            id=obs.id,
            user_id=parsed.user_id,
            subject_kind=obs.subject.kind.value,
            subject_key=obs.subject.key,
            value=obs.value,
            currency=obs.currency,
            as_of=obs.as_of,
            observed_at=obs.observed_at,
            source_observation_id=parsed.source_observation_id,
        )
    )
    await db.flush()
    return obs


def make_statement_price_handler(
    session_factory: async_sessionmaker[AsyncSession],
):
    """Build the production event handler: own session, own (pricing-only) commit."""

    async def _handle(event: DomainEvent) -> None:
        async with session_factory() as session:
            ingested = await ingest_statement_price(session, event)
            if ingested is not None:
                await session.commit()

    return _handle


def subscribe_price_ingest(
    registry: SubscriberRegistry,
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Register pricing's ``PriceObserved`` ingest handler on ``registry``.

    Called by the app composition root (``src/main.py``) with the registry the
    ``OutboxRelay`` dispatches from and the app's session factory.
    """
    registry.subscribe(EVENT_TYPE, make_statement_price_handler(session_factory))
